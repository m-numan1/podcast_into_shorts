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
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from config.settings import settings
from src.utils.logging_config import get_logger, setup_logging

log = get_logger(__name__)

_jobs: dict[str, dict] = {}
_cached_words: dict[str, list] = {}
_jobs_lock = threading.Lock()


def _lookup_cached_words(source: str = "", clip_id: str | None = None) -> list:
    """Find cached word timestamps for current media to power card subtitle rendering."""
    with _jobs_lock:
        if source and source in _cached_words and _cached_words[source]:
            return _cached_words[source]
        for k, words in reversed(list(_cached_words.items())):
            if words:
                return words
    return []


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
  .checks { display:flex; gap:1.2rem; margin-top:1rem; font-size:.9rem; color:var(--muted); flex-wrap: wrap; }
  .checks label { display:flex; align-items:center; gap:.4rem; margin:0; cursor:pointer; }
  pre.log { background:#000; border-radius:10px; padding:1rem; margin-top:1rem;
    font-size:.8rem; line-height:1.5; color:#9CA3AF; max-height:240px; overflow:auto;
    white-space:pre-wrap; word-break:break-word; font-family:ui-monospace,Consolas,monospace; }
  .banner { border-radius:10px; padding:.9rem 1.1rem; margin-bottom:1rem; font-size:.9rem;
            border:1px solid; }
  .banner.synthetic { background:rgba(245,158,11,.12); border-color:var(--warn); color:#FDE68A; }
  .banner.heuristic { background:rgba(99,102,241,.12); border-color:var(--accent); color:#C7D2FE; }
  .banner.error { background:rgba(239,68,68,.12); border-color:var(--err); color:#FECACA; }
  .banner.success { background:rgba(16,185,129,.12); border-color:var(--ok); color:#A7F3D0; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:1.25rem; }
  .clip { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:1.25rem; position:relative; display:flex; flex-direction:column; }
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

  /* Direct Card Shorts Actions */
  .card-render-box { margin: .8rem 0 1rem; background: rgba(31, 41, 55, 0.6); border: 1px dashed #4F46E5; border-radius: 10px; padding: .85rem; }
  .card-actions { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  .btn-card-create { background: linear-gradient(135deg, #6366F1, #8B5CF6); color: #fff; border: none; font-weight: 600; font-size: .84rem; padding: .55rem .95rem; border-radius: 8px; cursor: pointer; display: inline-flex; align-items: center; gap: .35rem; transition: transform .15s, opacity .15s; }
  .btn-card-create:hover:not(:disabled) { opacity: .92; transform: translateY(-1px); }
  .btn-card-rerender { background: transparent; border: 1px solid #4B5563; color: var(--muted); font-size: .75rem; padding: .3rem .6rem; border-radius: 6px; cursor: pointer; align-self: flex-start; margin-top: .2rem; }
  .btn-card-rerender:hover { color: #fff; border-color: var(--text); }
  .card-status { font-size: .82rem; margin-top: .5rem; display: flex; align-items: center; gap: .5rem; }
  .card-status.loading { color: #93C5FD; }
  .card-status.error { color: #FCA5A5; }
  .card-status.success { color: #6EE7B7; }
  .spinner { width: 14px; height: 14px; border: 2px solid rgba(255,255,255,.3); border-top-color: #fff; border-radius: 50%; animation: spin .7s linear infinite; display: inline-block; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Batch Bar */
  .batch-bar { background: linear-gradient(135deg, #111827, #1E1B4B); border: 1px solid #4F46E5; border-radius: 14px; padding: 1.2rem 1.5rem; margin-bottom: 1.5rem; display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; box-shadow: 0 4px 20px rgba(99,102,241,0.15); }
  .batch-info h2 { font-size: 1.15rem; margin-bottom: .2rem; color: #fff; display: flex; align-items: center; gap: .5rem; }
  .batch-info p { font-size: .85rem; color: #A5B4FC; }
  .batch-btns { display: flex; gap: .75rem; flex-wrap: wrap; }
  .btn-batch-create { background: var(--ok); color: #fff; font-weight: 700; padding: .75rem 1.3rem; border: none; border-radius: 10px; cursor: pointer; font-size: .95rem; font-family: inherit; display: inline-flex; align-items: center; gap: .4rem; }
  .btn-batch-create:hover:not(:disabled) { opacity: .92; }

  /* Quick Loader Bar */
  .quick-bar { display: flex; align-items: center; gap: .8rem; margin-top: 1rem; padding-top: .9rem; border-top: 1px solid rgba(55,65,81,.6); flex-wrap: wrap; font-size: .85rem; }
  .quick-label { color: var(--muted); font-weight: 500; }
  .btn-subtle { background: #1E293B; border: 1px solid #334155; color: #E2E8F0; padding: .45rem .85rem; border-radius: 7px; font-size: .82rem; cursor: pointer; font-family: inherit; display: inline-flex; align-items: center; gap: .35rem; }
  .btn-subtle:hover { background: #334155; border-color: #64748B; color: #fff; }

  /* Local File Picker & Badge */
  .btn-picker { background: #1E293B; border: 1px solid #4B5563; color: #E2E8F0; padding: .35rem .75rem; border-radius: 7px; font-size: .82rem; font-weight: 600; cursor: pointer; font-family: inherit; display: inline-flex; align-items: center; gap: .35rem; transition: background .15s, border-color .15s; }
  .btn-picker:hover { background: #334155; border-color: var(--accent); color: #fff; }
  .file-badge { margin: .55rem 0 .2rem; background: rgba(99, 102, 241, 0.12); border: 1px solid var(--accent); border-radius: 8px; padding: .45rem .8rem; display: inline-flex; align-items: center; gap: .6rem; font-size: .84rem; color: #C7D2FE; }
  .file-badge-name { font-weight: 600; color: #fff; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .file-badge-size { color: var(--muted); font-size: .78rem; }
  .file-badge-progress { font-weight: 600; font-size: .82rem; }
  .btn-clear-file { background: transparent; border: none; color: var(--muted); font-size: 1.15rem; cursor: pointer; line-height: 1; padding: 0 .2rem; }
  .btn-clear-file:hover { color: var(--err); }

  /* Figma-Inspired Dialog & AI Processing Loader */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    width: 100vw;
    height: 100vh;
    background: rgba(0, 0, 0, 0.85);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
    animation: fadeIn .2s ease-out;
  }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

  .modal-dialog {
    background: linear-gradient(145deg, #131B2E, #0F172A);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 20px;
    width: 100%;
    max-width: 580px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8), 0 0 35px rgba(99, 102, 241, 0.15);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    animation: popIn .25s cubic-bezier(0.16, 1, 0.3, 1);
  }
  @keyframes popIn {
    from { transform: scale(0.94); opacity: 0; }
    to { transform: scale(1); opacity: 1; }
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.25rem 1.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }
  .modal-badge {
    display: inline-flex;
    align-items: center;
    gap: .45rem;
    font-size: .72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: #818CF8;
    background: rgba(99, 102, 241, 0.15);
    padding: .2rem .55rem;
    border-radius: 999px;
    margin-bottom: .25rem;
  }
  .pulsing-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #6366F1;
    animation: pulseDot 1.4s infinite;
  }
  @keyframes pulseDot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: .4; transform: scale(0.7); }
  }
  .modal-title {
    font-size: 1.2rem;
    font-weight: 700;
    color: #FFFFFF;
    margin: 0;
  }
  .btn-modal-close {
    width: 40px;
    height: 40px;
    border-radius: 9999px;
    background: rgba(0, 0, 0, 0.9);
    opacity: 0.85;
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #FFFFFF;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: transform .15s, opacity .15s, background .15s;
  }
  .btn-modal-close:hover {
    opacity: 1;
    transform: scale(1.05);
    background: rgba(255, 255, 255, 0.15);
  }

  .modal-body {
    padding: 1.75rem 1.5rem 1.5rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  /* Animated Glowing Orb Visual */
  .loader-visual-container {
    position: relative;
    width: 90px;
    height: 90px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 1.25rem;
  }
  .pulse-ring {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    border: 2px solid #6366F1;
    animation: ringExpand 2.2s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
  }
  .ring-2 {
    animation-delay: 0.9s;
    border-color: #EC4899;
  }
  @keyframes ringExpand {
    0% { transform: scale(0.6); opacity: 0.8; }
    100% { transform: scale(1.4); opacity: 0; }
  }
  .pulse-core {
    width: 62px;
    height: 62px;
    border-radius: 50%;
    background: linear-gradient(135deg, #6366F1, #8B5CF6);
    box-shadow: 0 0 25px rgba(99, 102, 241, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.7rem;
    z-index: 2;
    animation: corePulse 2s ease-in-out infinite;
  }
  @keyframes corePulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.08); }
  }

  .stage-info {
    margin-bottom: 1.25rem;
  }
  .stage-main-text {
    font-size: 1.15rem;
    font-weight: 700;
    color: #FFFFFF;
    margin-bottom: .25rem;
  }
  .stage-detail-text {
    font-size: .88rem;
    color: #94A3B8;
  }

  /* Progress Bar */
  .progress-wrap {
    width: 100%;
    margin-bottom: 1.4rem;
  }
  .progress-bar-bg {
    width: 100%;
    height: 8px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 999px;
    overflow: hidden;
  }
  .progress-bar-fill {
    width: 15%;
    height: 100%;
    background: linear-gradient(90deg, #6366F1, #A855F7, #EC4899);
    border-radius: 999px;
    transition: width .4s ease;
  }
  .progress-meta {
    display: flex;
    justify-content: space-between;
    font-size: .8rem;
    color: #64748B;
    margin-top: .4rem;
  }
  #loaderPercentText {
    font-weight: 700;
    color: #C7D2FE;
  }

  /* Pipeline Steps Indicator */
  .pipeline-steps {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: .85rem .95rem;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    margin-bottom: 1rem;
  }
  .step-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: .3rem;
  }
  .step-icon {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: #1E293B;
    border: 1px solid #334155;
    color: #94A3B8;
    font-size: .75rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all .25s;
  }
  .step-label {
    font-size: .72rem;
    color: #64748B;
    font-weight: 500;
  }
  .step-connector {
    flex: 1;
    height: 2px;
    background: #1E293B;
    margin: 0 .4rem -1rem .4rem;
  }
  .step-item.active .step-icon {
    background: #6366F1;
    border-color: #818CF8;
    color: #fff;
    box-shadow: 0 0 10px rgba(99, 102, 241, 0.6);
    transform: scale(1.1);
  }
  .step-item.active .step-label {
    color: #C7D2FE;
    font-weight: 600;
  }
  .step-item.done .step-icon {
    background: #10B981;
    border-color: #10B981;
    color: #fff;
  }
  .step-item.done .step-label {
    color: #6EE7B7;
  }

  .tech-log-toggle {
    margin-top: .4rem;
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>Podcast to Shorts</h1>
  <p class="sub">Finds self-contained clips in long-form audio and video, and directly creates vertical shorts with styled subtitles.</p>

  <div class="card">
    <div class="row">
      <div class="grow">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:.4rem;">
          <label for="src" style="margin-bottom:0;">YouTube URL or Local Media File</label>
          <div>
            <button type="button" id="btnPickFile" class="btn-picker" title="Select a video or audio file from your device">
              📁 Choose Local File
            </button>
            <input type="file" id="localFileInput" accept="video/*,audio/*,.mp4,.mp3,.wav,.m4a,.mkv,.mov,.webm,.flac,.opus" style="display:none;">
          </div>
        </div>
        <input type="text" id="src" placeholder="Paste YouTube URL or choose a local file from device...">
      </div>
      <button type="button" id="go">🎬 Create Shorts</button>
    </div>

    <div id="fileInfoBox" class="file-badge" style="display:none;">
      <span>📁</span>
      <span id="fileBadgeName" class="file-badge-name"></span>
      <span id="fileBadgeSize" class="file-badge-size"></span>
      <span id="fileBadgeProgress" class="file-badge-progress"></span>
      <button type="button" id="btnClearFile" class="btn-clear-file" title="Clear selected file">&times;</button>
    </div>

    <div class="checks">
      <label for="aspectRatio">Format:
        <select id="aspectRatio" style="background:#1e293b; color:#fff; border:1px solid #334155; padding:.3rem .5rem; border-radius:6px; font-family:inherit; margin-left:.3rem;">
          <option value="9:16" selected>9:16 Vertical (Shorts/TikTok/Reels)</option>
          <option value="1:1">1:1 Square (LinkedIn/Insta)</option>
          <option value="16:9">16:9 Landscape (YouTube Highlights)</option>
        </select>
      </label>
      <label for="subPreset">Subtitle Style:
        <select id="subPreset" style="background:#1e293b; color:#fbbf24; font-weight:600; border:1px solid #4f46e5; padding:.3rem .5rem; border-radius:6px; font-family:inherit; margin-left:.3rem;">
          <option value="hormozi" selected>⚡ Hormozi Bold (Yellow Pop)</option>
          <option value="capcut_neon">✨ CapCut Neon (Cyan Pop)</option>
          <option value="mrbeast">🔥 MrBeast (Green Punch)</option>
          <option value="single_word">🎯 Single Word (Rapid Fire)</option>
          <option value="minimal">🕊️ Clean Minimal (Bottom)</option>
          <option value="default">Classic (Standard)</option>
        </select>
      </label>
      <label for="transcriptLang">Audio Language:
        <select id="transcriptLang" style="background:#1e293b; color:#fff; border:1px solid #334155; padding:.3rem .5rem; border-radius:6px; font-family:inherit; margin-left:.3rem;">
          <option value="" selected>Auto-detect</option>
          <option value="ur">Urdu (اردو)</option>
          <option value="hi">Hindi (हिंदी)</option>
          <option value="en">English</option>
          <option value="ar">Arabic (العربية)</option>
          <option value="es">Spanish</option>
        </select>
      </label>
    </div>
    <div class="quick-bar">
      <span class="quick-label">⚡ Direct Actions:</span>
      <button type="button" id="btnLoadRecent" class="btn-subtle" title="Load clips from outputs/final_clips.json">📂 Load Existing final_clips.json</button>
      <label class="btn-subtle" style="cursor:pointer;" title="Upload your own JSON file with clip timestamps">
        📤 Upload Custom JSON
        <input type="file" id="jsonFileInput" accept=".json" style="display:none;">
      </label>
    </div>
  </div>

  <div id="banners"></div>

  <div id="batchBar" class="batch-bar" style="display:none;">
    <div class="batch-info">
      <h2 id="batchTitle">🎬 Ready to Create Shorts</h2>
      <p id="batchSub">Click <strong>Create Short</strong> directly on any card below, or batch create all with your chosen subtitle style.</p>
    </div>
    <div class="batch-btns">
      <button type="button" id="btnCreateAll" class="btn-batch-create">🎬 Create All Shorts</button>
    </div>
  </div>

  <div class="grid" id="grid"></div>

  <!-- Processing Dialog Modal (Figma-inspired) -->
  <div id="loaderModal" class="modal-backdrop" style="display:none;">
    <div class="modal-dialog">
      <div class="modal-header">
        <div class="modal-header-info">
          <div class="modal-badge">
            <span class="pulsing-dot"></span>
            <span>AI Pipeline Active</span>
          </div>
          <h3 class="modal-title">Creating Your Shorts</h3>
        </div>
        <button type="button" id="btnCloseModal" class="btn-modal-close" title="Minimize dialog">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M1 1L11 11M1 11L11 1" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </button>
      </div>

      <div class="modal-body">
        <div class="loader-visual-container">
          <div class="pulse-ring ring-1"></div>
          <div class="pulse-ring ring-2"></div>
          <div class="pulse-core">
            <span class="pulse-icon">🎬</span>
          </div>
        </div>

        <div class="stage-info">
          <div id="stageStatusText" class="stage-main-text">Analyzing media...</div>
          <div id="stageDetailText" class="stage-detail-text">Preparing model environment</div>
        </div>

        <div class="progress-wrap">
          <div class="progress-bar-bg">
            <div id="loaderProgressBar" class="progress-bar-fill"></div>
          </div>
          <div class="progress-meta">
            <span id="loaderPercentText">15%</span>
            <span id="loaderEtaText">Directly creating vertical shorts</span>
          </div>
        </div>

        <div class="pipeline-steps">
          <div class="step-item active" id="step-dl">
            <div class="step-icon">1</div>
            <div class="step-label">Media & Audio</div>
          </div>
          <div class="step-connector"></div>
          <div class="step-item" id="step-transcribe">
            <div class="step-icon">2</div>
            <div class="step-label">Whisper Captions</div>
          </div>
          <div class="step-connector"></div>
          <div class="step-item" id="step-agents">
            <div class="step-icon">3</div>
            <div class="step-label">AI Editors</div>
          </div>
          <div class="step-connector"></div>
          <div class="step-item" id="step-render">
            <div class="step-icon">4</div>
            <div class="step-label">Render Shorts</div>
          </div>
        </div>

        <div class="tech-log-toggle">
          <button type="button" id="btnToggleLog" class="btn-subtle" style="font-size:.78rem; padding:.3rem .6rem;">
            ▶ View Technical Logs
          </button>
        </div>
        <pre class="log" id="log" style="display:none;"></pre>
      </div>
    </div>
  </div>
</div>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const logBox = $("log"), grid = $("grid"), banners = $("banners"), goBtn = $("go");
const batchBar = $("batchBar"), btnCreateAll = $("btnCreateAll");
const btnLoadRecent = $("btnLoadRecent"), jsonFileInput = $("jsonFileInput");
const btnPickFile = $("btnPickFile"), localFileInput = $("localFileInput");
const fileInfoBox = $("fileInfoBox"), fileBadgeName = $("fileBadgeName");
const fileBadgeSize = $("fileBadgeSize"), fileBadgeProgress = $("fileBadgeProgress");
const btnClearFile = $("btnClearFile");

/* Dialog Modal Elements */
const loaderModal = $("loaderModal"), btnCloseModal = $("btnCloseModal");
const stageStatusText = $("stageStatusText"), stageDetailText = $("stageDetailText");
const loaderProgressBar = $("loaderProgressBar"), loaderPercentText = $("loaderPercentText");
const btnToggleLog = $("btnToggleLog");

let timer = null;
let currentData = null;

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

btnPickFile.addEventListener("click", () => {
  localFileInput.click();
});

localFileInput.addEventListener("change", () => {
  const file = localFileInput.files && localFileInput.files[0];
  if (!file) return;

  fileBadgeName.textContent = file.name;
  fileBadgeSize.textContent = `(${formatFileSize(file.size)})`;
  fileBadgeProgress.textContent = "Uploading: 0%";
  fileBadgeProgress.style.color = "var(--warn)";
  fileInfoBox.style.display = "inline-flex";
  goBtn.disabled = true;

  logLine(`[upload] Selected local file: ${file.name} (${formatFileSize(file.size)})...`);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload?filename=" + encodeURIComponent(file.name));
  xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));

  xhr.upload.onprogress = (evt) => {
    if (evt.lengthComputable) {
      const pct = Math.round((evt.loaded / evt.total) * 100);
      fileBadgeProgress.textContent = `Uploading: ${pct}%`;
    }
  };

  xhr.onload = () => {
    goBtn.disabled = false;
    if (xhr.status >= 200 && xhr.status < 300) {
      try {
        const resp = JSON.parse(xhr.responseText);
        $("src").value = resp.path;
        fileBadgeProgress.textContent = "✅ Ready";
        fileBadgeProgress.style.color = "var(--ok)";
        logLine(`[upload done] File ready for shorts: ${resp.path}`);
      } catch (e) {
        fileBadgeProgress.textContent = "❌ Parse error";
        fileBadgeProgress.style.color = "var(--err)";
        banner("error", "Error parsing upload response: " + e.message);
      }
    } else {
      fileBadgeProgress.textContent = "❌ Upload failed";
      fileBadgeProgress.style.color = "var(--err)";
      banner("error", "Upload failed: " + xhr.responseText);
    }
  };

  xhr.onerror = () => {
    goBtn.disabled = false;
    fileBadgeProgress.textContent = "❌ Network error";
    fileBadgeProgress.style.color = "var(--err)";
    banner("error", "Network error while uploading file.");
  };

  xhr.send(file);
});

btnClearFile.addEventListener("click", () => {
  localFileInput.value = "";
  fileInfoBox.style.display = "none";
  if ($("src").value.includes("uploads") || $("src").value.includes("cache")) {
    $("src").value = "";
  }
});

function showLoader() {
  loaderModal.style.display = "flex";
  loaderProgressBar.style.width = "15%";
  loaderPercentText.textContent = "15%";
  stageStatusText.textContent = "Initializing Pipeline...";
  stageDetailText.textContent = "Analyzing media source and preparing models";
  updateStepIndicator(1);
}

function hideLoader() {
  loaderModal.style.display = "none";
}

btnCloseModal.addEventListener("click", () => {
  hideLoader();
});

btnToggleLog.addEventListener("click", () => {
  if (logBox.style.display === "none" || !logBox.style.display) {
    logBox.style.display = "block";
    btnToggleLog.textContent = "▼ Hide Technical Logs";
  } else {
    logBox.style.display = "none";
    btnToggleLog.textContent = "▶ View Technical Logs";
  }
});

function updateStepIndicator(stepNum) {
  const steps = [
    { el: $("step-dl"), num: 1 },
    { el: $("step-transcribe"), num: 2 },
    { el: $("step-agents"), num: 3 },
    { el: $("step-render"), num: 4 },
  ];
  steps.forEach(s => {
    if (!s.el) return;
    s.el.classList.remove("active", "done");
    if (s.num < stepNum) s.el.classList.add("done");
    else if (s.num === stepNum) s.el.classList.add("active");
  });
}

function updatePipelineProgress(lastLine) {
  if (!lastLine) return;
  const line = lastLine.toLowerCase();

  if (line.includes("download") || line.includes("extract audio") || line.includes("probing")) {
    updateStepIndicator(1);
    loaderProgressBar.style.width = "25%";
    loaderPercentText.textContent = "25%";
    stageStatusText.textContent = "Extracting Audio Track";
    stageDetailText.textContent = "Converting source to 16kHz high-clarity mono WAV...";
  } else if (line.includes("transcrib") || line.includes("whisper") || line.includes("caption")) {
    updateStepIndicator(2);
    loaderProgressBar.style.width = "50%";
    loaderPercentText.textContent = "50%";
    stageStatusText.textContent = "Transcribing with Whisper";
    stageDetailText.textContent = "Generating word-level timestamped subtitle cues...";
  } else if (line.includes("segment") || line.includes("candidate") || line.includes("feature") || line.includes("agent") || line.includes("editor")) {
    updateStepIndicator(3);
    loaderProgressBar.style.width = "75%";
    loaderPercentText.textContent = "75%";
    stageStatusText.textContent = "AI Editors Finding Best Clips";
    stageDetailText.textContent = "Scoring hooks, storyline, virality, and viewer retention...";
  } else if (line.includes("render") || line.includes("ffmpeg") || line.includes("burn")) {
    updateStepIndicator(4);
    loaderProgressBar.style.width = "90%";
    loaderPercentText.textContent = "90%";
    stageStatusText.textContent = "Rendering Vertical Shorts";
    stageDetailText.textContent = "Reframing to 9:16 and burning styled animated subtitles...";
  }
}

function logLine(text) {
  if (logBox) {
    logBox.textContent += (logBox.textContent ? String.fromCharCode(10) : "") + text;
    logBox.scrollTop = logBox.scrollHeight;
  }
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
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

function buildVideoWrap(clip, card, renderBox) {
  const parts = (clip.rendered_file_path || "").split(/[\\\\/]/);
  const filename = parts[parts.length - 1];
  if (!filename) return null;

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

  const reBtn = el("button", "btn-card-rerender", "🔄 Re-render Short");
  reBtn.type = "button";
  reBtn.addEventListener("click", () => {
    videoWrap.remove();
    const newBox = buildRenderBox(clip, card);
    card.insertBefore(newBox, card.querySelector(".m"));
  });
  videoWrap.appendChild(reBtn);

  return videoWrap;
}

function buildRenderBox(clip, card) {
  const box = el("div", "card-render-box");
  const actRow = el("div", "card-actions");

  const btnCreate = el("button", "btn-card-create", "🎬 Create Short");
  btnCreate.type = "button";
  btnCreate.title = "Render short with styled subtitles";

  const status = el("div", "card-status");
  status.style.display = "none";

  btnCreate.addEventListener("click", () => renderSingleCard(clip, card, box));

  actRow.appendChild(btnCreate);
  box.appendChild(actRow);
  box.appendChild(status);
  return box;
}

async function renderSingleCard(clip, card, renderBox) {
  const status = renderBox.querySelector(".card-status");
  const buttons = renderBox.querySelectorAll("button");
  buttons.forEach(b => b.disabled = true);

  const subStyleName = $("subPreset").selectedOptions[0]?.text || "Hormozi Bold";
  status.style.display = "flex";
  status.className = "card-status loading";
  status.replaceChildren();
  status.appendChild(el("span", "spinner"));
  status.appendChild(document.createTextNode(
    `🎬 Rendering short with ${subStyleName} subtitles...`
  ));

  const source = $("src").value.trim() || (currentData && (currentData.media_file_path || currentData.source)) || "";
  logLine(`[start render] clip #${clip.rank} (${clip.title}) subtitle_preset=${$("subPreset").value}...`);

  try {
    const res = await fetch("/api/render-card", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        clip,
        aspect_ratio: $("aspectRatio").value,
        subtitle_preset: $("subPreset").value,
      }),
    });
    const result = await res.json();
    if (!res.ok || result.status === "error") {
      throw new Error(result.error || res.statusText || "Rendering failed");
    }

    clip.rendered_file_path = result.clip.rendered_file_path;
    logLine(`[rendered] clip #${clip.rank} saved -> ${result.clip.rendered_file_path}`);

    renderBox.remove();
    const videoWrap = buildVideoWrap(clip, card, renderBox);
    if (videoWrap) {
      const metricAnchor = card.querySelector(".m");
      if (metricAnchor) card.insertBefore(videoWrap, metricAnchor);
      else card.appendChild(videoWrap);
    }

    const renderedFoot = card.querySelector(".rendered-path-foot");
    if (renderedFoot) {
      renderedFoot.textContent = "Rendered: " + clip.rendered_file_path;
    }
  } catch (err) {
    logLine(`[render error] #${clip.rank}: ${err.message}`);
    status.className = "card-status error";
    status.replaceChildren();
    status.textContent = "Error: " + err.message;
    buttons.forEach(b => b.disabled = false);
  }
}

function renderClips(data) {
  currentData = data;
  banners.replaceChildren();
  grid.replaceChildren();

  const clips = data.clips || [];
  if (clips.length > 0) {
    batchBar.style.display = "flex";
    const renderedCount = clips.filter(c => c.rendered_file_path).length;
    if (renderedCount === clips.length) {
      $("batchTitle").textContent = `🎬 ${clips.length} Shorts Ready`;
      $("batchSub").textContent = "All shorts are rendered with styled subtitles. Watch, download, or re-render below.";
      btnCreateAll.textContent = "🔄 Re-render All Shorts";
    } else {
      $("batchTitle").textContent = `🎬 ${clips.length} Clips Found (${renderedCount} Rendered)`;
      $("batchSub").textContent = "Directly create shorts using the buttons on each card, or batch render below.";
      btnCreateAll.textContent = "🎬 Create All Shorts";
    }
  } else {
    batchBar.style.display = "none";
  }

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

  clips.forEach(clip => {
    const card = el("div", "clip");
    card.id = `card-${clip.id}`;
    card.appendChild(el("div", "rank", "#" + clip.rank));
    card.appendChild(el("h3", null, clip.title));
    card.appendChild(el("div", "time",
      `${clip.start_timestamp} - ${clip.end_timestamp}  (${Number(clip.duration_seconds).toFixed(1)}s)`));

    const hook = el("div", "hook");
    hook.appendChild(el("strong", null, "Hook: "));
    hook.appendChild(document.createTextNode(clip.hook || ""));
    card.appendChild(hook);

    if (clip.rendered_file_path) {
      const vWrap = buildVideoWrap(clip, card, null);
      if (vWrap) card.appendChild(vWrap);
    } else {
      const rBox = buildRenderBox(clip, card);
      card.appendChild(rBox);
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
    const pathFoot = el("div", "rendered-path-foot", clip.rendered_file_path ? ("Rendered: " + clip.rendered_file_path) : "");
    foot.appendChild(pathFoot);
    card.appendChild(foot);

    const tags = el("div", "tags");
    (clip.suggested_hashtags || []).forEach(t => tags.appendChild(el("span", "tag", t)));
    card.appendChild(tags);

    grid.appendChild(card);
  });
}

async function batchRender() {
  if (!currentData || !currentData.clips || !currentData.clips.length) {
    banner("error", "No cards available to render.");
    return;
  }
  btnCreateAll.disabled = true;
  const styleName = $("subPreset").selectedOptions[0]?.text || "Hormozi Bold";
  logLine(`[batch start] Creating shorts for ${currentData.clips.length} cards (${styleName})...`);

  for (let i = 0; i < currentData.clips.length; i++) {
    const clip = currentData.clips[i];
    const cardEl = $(`card-${clip.id}`);
    if (!cardEl) continue;

    let renderBox = cardEl.querySelector(".card-render-box");
    if (!renderBox && !clip.rendered_file_path) {
      renderBox = buildRenderBox(clip, cardEl);
      cardEl.insertBefore(renderBox, cardEl.querySelector(".m"));
    }
    if (renderBox) {
      logLine(`[batch progress ${i + 1}/${currentData.clips.length}] rendering clip #${clip.rank}...`);
      await renderSingleCard(clip, cardEl, renderBox);
    }
  }

  logLine("[batch done] Finished processing all cards!");
  banner("success", "✅ All shorts have been created directly from cards!");
  btnCreateAll.disabled = false;
}

btnCreateAll.addEventListener("click", () => batchRender());

btnLoadRecent.addEventListener("click", async () => {
  btnLoadRecent.disabled = true;
  logLine("[load] Loading outputs/final_clips.json...");
  try {
    const res = await fetch("/api/load-json?file=final_clips.json");
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || res.statusText);

    if (data.media_file_path && !$("src").value.trim()) {
      $("src").value = data.media_file_path;
    }
    renderClips(data);
    logLine(`[load] Loaded ${(data.clips || []).length} clips from final_clips.json! You can directly create shorts with the cards now.`);
  } catch (err) {
    logLine(`[load error] ${err.message}`);
    banner("error", "Could not load final_clips.json: " + err.message);
  } finally {
    btnLoadRecent.disabled = false;
  }
});

jsonFileInput.addEventListener("change", (event) => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const parsed = JSON.parse(e.target.result);
      const data = Array.isArray(parsed) ? { clips: parsed, episode: file.name } : parsed;
      renderClips(data);
      logLine(`[upload] Loaded ${(data.clips || []).length} clips from ${file.name}!`);
    } catch (err) {
      banner("error", "Failed to parse JSON file: " + err.message);
    }
  };
  reader.readAsText(file);
});

async function poll(jobId, seenLogs) {
  let res;
  try {
    res = await fetch("/api/status?job_id=" + encodeURIComponent(jobId));
  } catch (e) {
    logLine("[error] lost connection: " + e.message);
    clearInterval(timer); goBtn.disabled = false;
    hideLoader();
    return seenLogs;
  }
  const data = await res.json();
  const newLogs = (data.logs || []).slice(seenLogs);
  newLogs.forEach(line => {
    logLine(line);
    updatePipelineProgress(line);
  });
  const count = (data.logs || []).length;

  if (data.status === "running") return count;

  clearInterval(timer);
  timer = null;
  goBtn.disabled = false;

  if (data.status === "error") {
    hideLoader();
    banners.replaceChildren();
    banner("error", "Failed at stage '" + (data.failed_stage || "unknown") + "': " + data.error);
    if (data.warnings && data.warnings.length) {
      const box = el("div", "banner heuristic", "Warnings:");
      const ul = el("ul", "warn");
      data.warnings.forEach(w => ul.appendChild(el("li", null, w)));
      box.appendChild(ul); banners.appendChild(box);
    }
  } else {
    loaderProgressBar.style.width = "100%";
    loaderPercentText.textContent = "100%";
    stageStatusText.textContent = "🎉 Shorts Created!";
    stageDetailText.textContent = `Generated ${(data.clips || []).length} shorts ready for download`;
    updateStepIndicator(5);
    setTimeout(() => {
      hideLoader();
      renderClips(data);
    }, 800);
  }
  return count;
}

goBtn.addEventListener("click", async () => {
  const source = $("src").value.trim();
  banners.replaceChildren();
  grid.replaceChildren();

  if (!source) {
    banner("error", "Please select a local media file or enter a YouTube URL.");
    return;
  }

  goBtn.disabled = true;
  logBox.textContent = "";
  logLine("[start] Processing: " + source);
  showLoader();

  let started;
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source,
        demo: false,
        render: true,
        aspect_ratio: $("aspectRatio").value,
        language: $("transcriptLang").value || undefined,
        subtitle_preset: $("subPreset").value,
      }),
    });
    started = await res.json();
    if (!res.ok) throw new Error(started.error || res.statusText);
  } catch (e) {
    logLine("[error] " + e.message);
    goBtn.disabled = false;
    hideLoader();
    banner("error", e.message);
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


def _get_model_info(reload_env: bool = True) -> str:
    """Reload settings from .env and return a descriptive string for terminal and logs."""
    if reload_env:
        try:
            from config.settings import Settings
            fresh = Settings()
            for k, v in fresh.model_dump().items():
                setattr(settings, k, v)
        except Exception as exc:
            log.warning("Could not refresh settings from .env: %s", exc)

    if settings.uses_llm:
        return f"LLM model (provider: {settings.default_llm_provider}, model: {settings.active_model_name})"
    return "Heuristic model (no LLM)"


def _run_job(
    job_id: str,
    source: str,
    demo: bool,
    render: bool,
    aspect_ratio: str = "9:16",
    language: str | None = None,
    subtitle_preset: str = "hormozi",
) -> None:
    """Worker thread: run the pipeline and store the result."""
    from src.graph.workflow import VideoEditorPipeline

    handler = ThreadJobLogHandler(job_id)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    def set_state(**fields) -> None:
        with _jobs_lock:
            _jobs[job_id].update(fields)

    try:
        model_info = _get_model_info()
        if language is not None:
            clean_lang = language.strip().lower()
            settings.transcript_language = None if clean_lang in ("auto", "auto-detect", "none", "") else language.strip()
        print(f"\n[ANALYSIS] Starting job {job_id} using: {model_info} (language={settings.transcript_language or 'auto'}, preset={subtitle_preset})", flush=True)
        log.info(
            "Starting pipeline analysis job %s (source=%r, demo=%s, render=%s, ratio=%s, language=%s, model=%s, preset=%s)",
            job_id, source, demo, render, aspect_ratio, settings.transcript_language or "auto", model_info, subtitle_preset,
        )
        settings.aspect_ratio = aspect_ratio  # type: ignore[assignment]
        settings.subtitle_preset = subtitle_preset
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

        words = [w for seg in state.transcript_segments for w in seg.words] if state.transcript_segments else []
        with _jobs_lock:
            _cached_words[job_id] = words
            if state.media_file_path:
                _cached_words[state.media_file_path] = words
            if state.source:
                _cached_words[state.source] = words

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

        if route.path == "/api/load-json":
            query = parse_qs(route.query)
            filename = query.get("file", ["final_clips.json"])[0]
            candidate = (settings.output_dir / filename).resolve()
            root = settings.output_dir.resolve()
            if root not in candidate.parents and candidate != root:
                self._send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            if not candidate.exists() or not candidate.is_file():
                self._send_json({"error": f"JSON file '{filename}' not found in {settings.output_dir}"}, HTTPStatus.NOT_FOUND)
                return
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    data = {"clips": data, "episode": filename}
                # Auto-resolve media path if missing
                candidate_media = data.get("media_file_path") or data.get("source") or ""
                if candidate_media and Path(candidate_media).is_file():
                    data["media_file_path"] = str(Path(candidate_media).resolve())
                elif candidate_media and (settings.cache_dir / candidate_media).is_file():
                    data["media_file_path"] = str((settings.cache_dir / candidate_media).resolve())
                self._send_json(data)
                return
            except Exception as exc:
                self._send_json({"error": f"Failed reading {filename}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

        if route.path == "/api/list-json-files":
            try:
                files = [f.name for f in settings.output_dir.glob("*.json") if f.is_file()]
                self._send_json({"files": sorted(files)})
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    # -------------------------------------------------------------- POST

    def do_POST(self) -> None:
        route = urlparse(self.path)
        if route.path not in ("/api/analyze", "/api/render-card", "/api/upload"):
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        if route.path == "/api/upload":
            try:
                query = parse_qs(route.query)
                filename = query.get("filename", [""])[0] or self.headers.get("X-Filename", "")
                filename = unquote(filename).strip() if filename else ""
                if not filename:
                    filename = f"upload_{uuid.uuid4().hex[:8]}.mp4"

                safe_name = Path(filename).name
                upload_dir = settings.cache_dir / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                dest = upload_dir / safe_name

                raw_length = self.headers.get("Content-Length")
                content_len = int(raw_length) if raw_length else None

                bytes_written = 0
                chunk_size = 1024 * 1024
                with open(dest, "wb") as f:
                    if content_len is not None:
                        remaining = content_len
                        while remaining > 0:
                            buf = self.rfile.read(min(chunk_size, remaining))
                            if not buf:
                                break
                            f.write(buf)
                            remaining -= len(buf)
                            bytes_written += len(buf)
                    else:
                        while True:
                            buf = self.rfile.read(chunk_size)
                            if not buf:
                                break
                            f.write(buf)
                            bytes_written += len(buf)

                dest_resolved = str(dest.resolve())
                log.info("Uploaded local file %s (%d bytes) to %s", safe_name, bytes_written, dest_resolved)
                self._send_json({
                    "status": "ok",
                    "path": dest_resolved,
                    "filename": safe_name,
                    "size_bytes": bytes_written,
                })
                return
            except Exception as exc:
                log.exception("Upload failed: %s", exc)
                self._send_json({"error": f"Upload failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
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

        aspect_ratio = str(payload.get("aspect_ratio") or "9:16").strip()
        subtitle_preset = str(payload.get("subtitle_preset") or settings.subtitle_preset).strip()
        language = payload.get("language")
        if language is not None:
            language = str(language).strip() or None

        if route.path == "/api/render-card":
            clip_data = payload.get("clip")
            if not clip_data or not isinstance(clip_data, dict):
                self._send_json({"error": "Clip data object is required"}, HTTPStatus.BAD_REQUEST)
                return

            source = str(payload.get("source") or "").strip()
            from src.providers.renderer import ClipRenderer

            try:
                renderer = ClipRenderer(
                    aspect_ratio=aspect_ratio,
                    subtitle_preset=subtitle_preset,
                )
                words = _lookup_cached_words(source, clip_data.get("id"))
                updated_clip = renderer.render_clip(
                    clip_data=clip_data,
                    media_path=source,
                    all_words=words,
                    aspect_ratio=aspect_ratio,
                    subtitle_preset=subtitle_preset,
                )
                self._send_json({"status": "done", "clip": updated_clip})
                return
            except Exception as exc:
                log.exception("Failed to render card clip %s: %s", clip_data.get("id"), exc)
                self._send_json({"status": "error", "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

        source = str(payload.get("source") or "").strip()
        demo = bool(payload.get("demo", False))
        render = bool(payload.get("render", True))
        if not source and not demo:
            self._send_json(
                {"error": "Please provide a YouTube URL or select a local media file."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        job_id = uuid.uuid4().hex[:16]
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "logs": [], "warnings": []}

        model_info = _get_model_info()
        print(f"\n[ANALYSE CLICKED] Analysis requested -> Using {model_info}\n", flush=True)

        # Analysis can take minutes; run it off the request thread so the
        # server stays responsive.
        threading.Thread(
            target=_run_job,
            args=(job_id, source, demo, render, aspect_ratio, language, subtitle_preset),
            daemon=True,
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
