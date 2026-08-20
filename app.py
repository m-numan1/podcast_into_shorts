"""Local web dashboard.

Fixes over the original:
  B19 clip data was interpolated into `innerHTML`, so a transcript or video
      title containing markup executed as script. The client now builds nodes
      and assigns `textContent`.
  B20 `do_POST` had no try/except and read `Content-Length` unbounded; a
      malformed body produced an unhandled exception and no JSON response.
  B21 `HTTPServer` is single-threaded while `pipeline.run()` blocks for minutes
      under Whisper, so one request stalled every other. Analysis now runs in a
      worker thread and the client polls for progress.

Also: the external Google Fonts stylesheet is gone (it broke the offline mode
the project advertises), errors/warnings/provenance are surfaced, and results
state plainly when they are synthetic or heuristically scored.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from config.settings import settings
from src.utils.logging_config import get_logger, setup_logging

log = get_logger(__name__)

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Podcast to Shorts</title>
<style>
  :root {
    --bg: #0B0F19; --card: #111827; --line: #374151; --accent: #6366F1;
    --text: #F9FAFB; --muted: #9CA3AF; --warn: #F59E0B; --err: #EF4444;
    --ok: #10B981;
    --font: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: var(--font); background: var(--bg); color: var(--text);
         padding: 2rem 1rem; min-height: 100vh; }
  .wrap { max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 1.9rem; margin-bottom: .3rem; }
  .sub { color: var(--muted); margin-bottom: 2rem; }
  .card { background: var(--card); border: 1px solid var(--line);
          border-radius: 14px; padding: 1.5rem; margin-bottom: 1.5rem; }
  label { display:block; font-size:.85rem; color: var(--muted); margin-bottom:.4rem; }
  .row { display: flex; gap: .75rem; flex-wrap: wrap; align-items: flex-end; }
  .row > .grow { flex: 1 1 320px; }
  input[type=text] { width:100%; background:#1F2937; border:1px solid var(--line);
    padding:.8rem 1rem; border-radius:10px; color:#fff; font-size:1rem; font-family:inherit; }
  input[type=text]:focus { outline:none; border-color: var(--accent); }
  button { background: var(--accent); color:#fff; font-weight:600; padding:.8rem 1.4rem;
    border:none; border-radius:10px; cursor:pointer; font-size:1rem; font-family:inherit; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .checks { display:flex; gap:1.2rem; margin-top:1rem; font-size:.9rem; color:var(--muted); }
  .checks label { display:flex; align-items:center; gap:.4rem; margin:0; cursor:pointer; }
  pre.log { background:#000; border-radius:10px; padding:1rem; margin-top:1rem;
    font-size:.8rem; line-height:1.5; color:#9CA3AF; max-height:240px; overflow:auto;
    white-space:pre-wrap; word-break:break-word; font-family:ui-monospace,Consolas,monospace; }
  .banner { border-radius:10px; padding:.9rem 1.1rem; margin-bottom:1rem; font-size:.9rem;
            border:1px solid; }
  .banner.synthetic { background:rgba(245,158,11,.12); border-color:var(--warn); color:#FDE68A; }
  .banner.heuristic { background:rgba(99,102,241,.12); border-color:var(--accent); color:#C7D2FE; }
  .banner.error { background:rgba(239,68,68,.12); border-color:var(--err); color:#FECACA; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:1.25rem; }
  .clip { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:1.25rem; position:relative; }
  .rank { position:absolute; top:1rem; right:1rem; background:var(--accent); color:#fff;
          font-size:.75rem; font-weight:700; padding:.2rem .6rem; border-radius:99px; }
  .clip h3 { font-size:1.05rem; margin-bottom:.5rem; padding-right:3.5rem; line-height:1.35; }
  .time { color:var(--warn); font-weight:600; font-size:.85rem; margin-bottom:.75rem;
          font-family:ui-monospace,Consolas,monospace; }
  .hook { background:rgba(99,102,241,.1); border-left:3px solid var(--accent);
          padding:.6rem .8rem; border-radius:6px; font-style:italic; font-size:.9rem;
          margin-bottom:.75rem; }
  .m { display:flex; justify-content:space-between; font-size:.82rem; color:var(--muted);
       margin-bottom:.3rem; }
  .m b { color:var(--text); }
  .tags { margin-top:.7rem; display:flex; flex-wrap:wrap; gap:.35rem; }
  .tag { background:#1F2937; color:var(--muted); padding:.15rem .5rem; border-radius:5px;
         font-size:.72rem; }
  .foot { border-top:1px solid var(--line); margin-top:.8rem; padding-top:.7rem;
          font-size:.82rem; color:var(--muted); }
  ul.warn { margin:.5rem 0 0 1.2rem; font-size:.85rem; color:#FDE68A; }
  .video-wrap { margin: .8rem 0 1rem; border-radius: 10px; overflow: hidden; background: #000; display: flex; flex-direction: column; gap: .5rem; padding: .5rem; border: 1px solid var(--line); }
  .clip-video { width: 100%; max-height: 420px; outline: none; background: #000; border-radius: 8px; }
  .dl-btn { display: inline-flex; align-items: center; justify-content: center; gap: .4rem; background: var(--ok); color: #fff; text-decoration: none; font-size: .85rem; font-weight: 600; padding: .5rem 1rem; border-radius: 8px; text-align: center; }
  .dl-btn:hover { opacity: .9; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Podcast to Shorts</h1>
  <p class="sub">Finds self-contained clips in long-form audio and video, and optionally renders them vertically.</p>

  <div class="card">
    <div class="row">
      <div class="grow">
        <label for="src">YouTube URL or local media path</label>
        <input type="text" id="src" placeholder="https://www.youtube.com/watch?v=...">
      </div>
      <button type="button" id="go">Analyse</button>
    </div>
    <div class="checks">
      <label><input type="checkbox" id="demo"> Demo mode (synthetic fixture)</label>
      <label><input type="checkbox" id="render"> Render MP4s (needs ffmpeg)</label>
    </div>
    <pre class="log" id="log" hidden></pre>
  </div>

  <div id="banners"></div>
  <div class="grid" id="grid"></div>
</div>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const logBox = $("log"), grid = $("grid"), banners = $("banners"), goBtn = $("go");
let timer = null;

function logLine(text) {
  logBox.hidden = false;
  logBox.textContent += (logBox.textContent ? String.fromCharCode(10) : "") + text;
  logBox.scrollTop = logBox.scrollHeight;
}



function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  // textContent, never innerHTML: clip text comes from transcripts and video
  // titles and must never be parsed as markup.
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function banner(kind, text) {
  banners.appendChild(el("div", "banner " + kind, text));
}

function metric(label, value) {
  const row = el("div", "m");
  row.appendChild(el("span", null, label));
  row.appendChild(el("b", null, value));
  return row;
}

function renderClips(data) {
  banners.replaceChildren();
  grid.replaceChildren();

  const p = data.provenance || {};
  if (data.is_synthetic) {
    banner("synthetic", "Synthetic fixture data - these results do not describe real media. Do not publish them.");
  }
  if (p.scoring_mode === "heuristic") {
    banner("heuristic", "Scored without a language model. Rankings come from measured signals only and are a weak proxy for editorial judgement.");
  }
  if (data.warnings && data.warnings.length) {
    const box = el("div", "banner heuristic", "Warnings:");
    const ul = el("ul", "warn");
    data.warnings.forEach(w => ul.appendChild(el("li", null, w)));
    box.appendChild(ul);
    banners.appendChild(box);
  }

  (data.clips || []).forEach(clip => {
    const card = el("div", "clip");
    card.appendChild(el("div", "rank", "#" + clip.rank));
    card.appendChild(el("h3", null, clip.title));
    card.appendChild(el("div", "time",
      `${clip.start_timestamp} - ${clip.end_timestamp}  (${Number(clip.duration_seconds).toFixed(1)}s)`));

    const hook = el("div", "hook");
    hook.appendChild(el("strong", null, "Hook: "));
    hook.appendChild(document.createTextNode(clip.hook || ""));
    card.appendChild(hook);

    if (clip.rendered_file_path) {
      const parts = clip.rendered_file_path.split(/[\\\\/]/);
      const filename = parts[parts.length - 1];
      if (filename) {
        const videoWrap = el("div", "video-wrap");
        const video = document.createElement("video");
        video.controls = true;
        video.preload = "metadata";
        video.className = "clip-video";
        video.src = "/renders/" + encodeURIComponent(filename);
        videoWrap.appendChild(video);

        const dlBtn = el("a", "dl-btn", "⬇ Download Short (MP4)");
        dlBtn.href = "/renders/" + encodeURIComponent(filename);
        dlBtn.setAttribute("download", filename);
        videoWrap.appendChild(dlBtn);

        card.appendChild(videoWrap);
      }
    }

    card.appendChild(metric("Overall", Number(clip.overall_score).toFixed(2) + " / 10"));
    card.appendChild(metric("Virality", Number(clip.virality_score).toFixed(2) + " / 10"));
    card.appendChild(metric("Confidence", Number(clip.confidence_score).toFixed(2) + " / 10"));
    card.appendChild(metric("Retention", clip.viewer_retention_prediction));
    card.appendChild(metric("Cut adjust",
      `${Number(clip.start_adjustment_sec).toFixed(2)}s / +${Number(clip.end_adjustment_sec).toFixed(2)}s`));

    const foot = el("div", "foot");
    foot.appendChild(el("div", null, clip.one_sentence_summary));
    foot.appendChild(el("div", null, "Why: " + (clip.why_this_clip_was_selected || "")));
    if (clip.rendered_file_path) {
      foot.appendChild(el("div", null, "Rendered: " + clip.rendered_file_path));
    }
    card.appendChild(foot);

    const tags = el("div", "tags");
    (clip.suggested_hashtags || []).forEach(t => tags.appendChild(el("span", "tag", t)));
    card.appendChild(tags);

    grid.appendChild(card);
  });
}

async function poll(jobId, seenLogs) {
  let res;
  try {
    res = await fetch("/api/status?job_id=" + encodeURIComponent(jobId));
  } catch (e) {
    logLine("[error] lost connection: " + e.message);
    clearInterval(timer); goBtn.disabled = false;
    return seenLogs;
  }
  const data = await res.json();
  (data.logs || []).slice(seenLogs).forEach(logLine);
  const count = (data.logs || []).length;

  if (data.status === "running") return count;

  clearInterval(timer);
  timer = null;
  goBtn.disabled = false;

  if (data.status === "error") {
    banners.replaceChildren();
    banner("error", "Failed at stage '" + (data.failed_stage || "unknown") + "': " + data.error);
    if (data.warnings && data.warnings.length) {
      const box = el("div", "banner heuristic", "Warnings:");
      const ul = el("ul", "warn");
      data.warnings.forEach(w => ul.appendChild(el("li", null, w)));
      box.appendChild(ul); banners.appendChild(box);
    }
  } else {
    logLine("[done] " + (data.clips || []).length + " clips processed");
    renderClips(data);
  }
  return count;
}

goBtn.addEventListener("click", async () => {
  const source = $("src").value.trim();
  const demo = $("demo").checked;
  banners.replaceChildren();
  grid.replaceChildren();

  if (!source && !demo) {
    banner("error", "Please enter a YouTube URL / local file path, or check 'Demo mode'.");
    return;
  }

  goBtn.disabled = true;
  logBox.textContent = "";
  logLine("[start] " + (demo ? "demo mode" : source));

  let started;
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, demo, render: $("render").checked }),
    });
    started = await res.json();
    if (!res.ok) throw new Error(started.error || res.statusText);
  } catch (e) {
    logLine("[error] " + e.message);
    goBtn.disabled = false;
    return;
  }

  let seen = 0;
  timer = setInterval(async () => { seen = await poll(started.job_id, seen); }, 800);
});
</script>
</body>
</html>
"""


class ThreadJobLogHandler(logging.Handler):
    """Custom logging handler that streams logs to _jobs[job_id]['logs'] in real-time."""

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id
        self.formatter = logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with _jobs_lock:
                if self.job_id in _jobs:
                    _jobs[self.job_id]["logs"].append(msg)
        except Exception:
            self.handleError(record)


def _run_job(job_id: str, source: str, demo: bool, render: bool) -> None:
    """Worker thread: run the pipeline and store the result."""
    from src.graph.workflow import VideoEditorPipeline

    handler = ThreadJobLogHandler(job_id)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    def set_state(**fields) -> None:
        with _jobs_lock:
            _jobs[job_id].update(fields)

    try:
        log.info("Starting pipeline analysis job %s (source=%r, demo=%s, render=%s)", job_id, source, demo, render)
        pipeline = VideoEditorPipeline()
        state = pipeline.run(source, demo_mode=demo, render=render, thread_id=job_id)
        provenance = state.provenance()
        if state.error:
            set_state(
                status="error",
                error=state.error,
                failed_stage=state.failed_stage,
                warnings=list(state.warnings),
            )
            return
        set_state(
            status="done",
            warnings=list(state.warnings),
            title=state.podcast_title,
            provenance=provenance.model_dump(mode="json"),
            is_synthetic=provenance.is_synthetic,
            clips=[c.model_dump(mode="json") for c in state.final_clips],
            media_file_path=state.media_file_path,
            source=state.source,
        )
        log.info("Pipeline job %s completed with %d clips", job_id, len(state.final_clips))
    except Exception as exc:  # a worker crash must not kill the server
        log.exception("Job %s crashed", job_id)
        set_state(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            failed_stage="server",
        )
    finally:
        root_logger.removeHandler(handler)


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "PodcastShorts/2.0"

    def log_message(self, format: str, *args) -> None:  # route through logging
        log.debug("%s - %s", self.address_string(), format % args)


    # ------------------------------------------------------------ helpers

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length header is required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Content-Length is not an integer") from exc
        if length < 0:
            raise ValueError("Content-Length is negative")
        # Bounded read: the original trusted the header and read whatever it said.
        if length > settings.max_request_bytes:
            raise ValueError(
                f"Request body too large ({length} > {settings.max_request_bytes} bytes)"
            )
        if length == 0:
            return {}
        body = self.rfile.read(length)
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object")
        return parsed

    # --------------------------------------------------------------- GET

    def do_GET(self) -> None:
        route = urlparse(self.path)
        if route.path in ("/", "/index.html"):
            body = HTML_PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route.path == "/health":
            self._send_json({
                "status": "ok",
                "scoring_mode": "llm" if settings.uses_llm else "heuristic",
                "embedding_backend": settings.embedding_backend,
            })
            return

        if route.path == "/api/status":
            job_ids = parse_qs(route.query).get("job_id", [])
            if not job_ids:
                self._send_json({"error": "job_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            with _jobs_lock:
                job = _jobs.get(job_ids[0])
                snapshot = dict(job) if job else None
            if snapshot is None:
                self._send_json({"error": "unknown job_id"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(snapshot)
            return

        if route.path.startswith("/renders/"):
            raw_name = route.path[len("/renders/"):]
            filename = unquote(raw_name)
            render_root = settings.render_dir.resolve()
            file_path = (settings.render_dir / filename).resolve()
            if render_root not in file_path.parents and file_path != render_root:
                self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if not file_path.exists() or not file_path.is_file():
                self._send_json({"error": "file not found"}, HTTPStatus.NOT_FOUND)
                return

            try:
                stat = file_path.stat()
                file_size = stat.st_size
                ext = file_path.suffix.lower()
                mime_type = "video/mp4" if ext == ".mp4" else "video/webm" if ext == ".webm" else "application/octet-stream"

                range_header = self.headers.get("Range")
                if range_header and range_header.startswith("bytes="):
                    ranges = range_header.replace("bytes=", "").split("-")
                    start = int(ranges[0]) if ranges[0] else 0
                    end = int(ranges[1]) if len(ranges) > 1 and ranges[1] else file_size - 1
                    end = min(end, file_size - 1)
                    length = max(0, end - start + 1)

                    self.send_response(HTTPStatus.PARTIAL_CONTENT)
                    self.send_header("Content-Type", mime_type)
                    self.send_header("Content-Length", str(length))
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()

                    with open(file_path, "rb") as f:
                        f.seek(start)
                        self.wfile.write(f.read(length))
                    return

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with open(file_path, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
                return
            except Exception as exc:
                log.exception("Error serving render file %s: %s", filename, exc)
                return

        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    # -------------------------------------------------------------- POST

    def do_POST(self) -> None:
        route = urlparse(self.path)
        if route.path != "/api/analyze":
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"malformed JSON: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            log.exception("Failed reading request body")
            self._send_json(
                {"error": f"{type(exc).__name__}: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        source = str(payload.get("source") or "").strip()
        demo = bool(payload.get("demo"))
        render = bool(payload.get("render"))
        if not source and not demo:
            self._send_json(
                {"error": "Provide 'source', or set 'demo' to true."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        job_id = uuid.uuid4().hex[:16]
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "logs": [], "warnings": []}

        # Analysis can take minutes; run it off the request thread so the
        # server stays responsive.
        threading.Thread(
            target=_run_job, args=(job_id, source, demo, render), daemon=True
        ).start()
        self._send_json({"job_id": job_id, "status": "running"}, HTTPStatus.ACCEPTED)



def run_server(host: str | None = None, port: int | None = None) -> None:
    setup_logging(settings.log_level)
    settings.ensure_directories()
    host = host or settings.server_host
    port = port or settings.server_port
    server = ThreadingHTTPServer((host, port), RequestHandler)
    server.daemon_threads = True
    log.info("Dashboard on http://%s:%d", host, port)
    print(f"Dashboard: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Podcast to Shorts web dashboard")
    parser.add_argument("--host", default=settings.server_host)
    parser.add_argument("--port", type=int, default=settings.server_port)
    cli_args = parser.parse_args()
    run_server(cli_args.host, cli_args.port)
