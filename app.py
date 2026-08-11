import sys
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from src.graph.workflow import VideoEditorPipeline
from config.settings import settings

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Video Editor for Podcasters</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-main: #0B0F19;
            --bg-card: #111827;
            --bg-card-hover: #1F2937;
            --accent-primary: #6366F1;
            --accent-glow: rgba(99, 102, 241, 0.4);
            --accent-success: #10B981;
            --accent-warning: #F59E0B;
            --text-primary: #F9FAFB;
            --text-secondary: #9CA3AF;
            --border-color: #374151;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-main);
            color: var(--text-primary);
            padding: 2rem;
            min-height: 100vh;
        }
        .header {
            max-width: 1200px;
            margin: 0 auto 3rem auto;
            text-align: center;
        }
        .header h1 {
            font-family: 'Outfit', sans-serif;
            font-size: 2.75rem;
            font-weight: 800;
            background: linear-gradient(135deg, #818CF8 0%, #C084FC 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        .header p {
            color: var(--text-secondary);
            font-size: 1.1rem;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
        }
        .input-group {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
        }
        input[type="text"] {
            flex: 1;
            background: #1F2937;
            border: 1px solid var(--border-color);
            padding: 1rem 1.25rem;
            border-radius: 12px;
            color: #FFF;
            font-size: 1rem;
            outline: none;
            transition: border-color 0.2s;
        }
        input[type="text"]:focus {
            border-color: var(--accent-primary);
        }
        button {
            background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
            color: white;
            font-weight: 600;
            padding: 1rem 2rem;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-size: 1rem;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px var(--accent-glow);
        }
        .status-box {
            margin-top: 1.5rem;
            background: #000;
            border-radius: 12px;
            padding: 1rem;
            font-family: monospace;
            font-size: 0.9rem;
            color: #10B981;
            max-height: 200px;
            overflow-y: auto;
        }
        .clip-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
            gap: 1.5rem;
            margin-top: 2rem;
        }
        .clip-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            transition: transform 0.2s, border-color 0.2s;
            position: relative;
        }
        .clip-card:hover {
            transform: translateY(-4px);
            border-color: var(--accent-primary);
        }
        .rank-badge {
            position: absolute;
            top: 1rem;
            right: 1rem;
            background: linear-gradient(135deg, #6366F1 0%, #A855F7 100%);
            color: white;
            font-weight: 700;
            font-size: 0.85rem;
            padding: 0.25rem 0.75rem;
            border-radius: 999px;
        }
        .clip-title {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 0.75rem;
            padding-right: 4rem;
        }
        .timestamp-bar {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--accent-warning);
            font-weight: 600;
            font-size: 0.9rem;
            margin-bottom: 1rem;
        }
        .hook-box {
            background: rgba(99, 102, 241, 0.1);
            border-left: 4px solid var(--accent-primary);
            padding: 0.75rem 1rem;
            border-radius: 6px;
            font-style: italic;
            margin-bottom: 1rem;
            font-size: 0.95rem;
        }
        .metric-row {
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }
        .metric-val {
            color: var(--text-primary);
            font-weight: 600;
        }
        .tag {
            display: inline-block;
            background: #1F2937;
            color: #9CA3AF;
            padding: 0.2rem 0.6rem;
            border-radius: 6px;
            font-size: 0.75rem;
            margin-right: 0.4rem;
            margin-top: 0.4rem;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>AI Video Editor for Podcasters</h1>
        <p>LangGraph Multi-Agent Creative Intelligence Suite for YouTube Shorts, TikTok & Reels</p>
    </div>

    <div class="container">
        <div class="card">
            <h2>Analyze Podcast Episode</h2>
            <p style="color: var(--text-secondary); margin-top: 0.25rem;">Enter a YouTube URL or path to run 8 LangGraph nodes & 6 specialized AI Editor agents.</p>
            <div class="input-group">
                <input type="text" id="sourceUrl" value="https://www.youtube.com/watch?v=sample_podcast_episode" placeholder="Enter YouTube Podcast URL or audio file path...">
                <button onclick="runPipeline()">Run AI Editor</button>
            </div>
            <div id="statusBox" class="status-box" style="display: none;">
                <div>[Status Log] Pipeline initialized...</div>
            </div>
        </div>

        <div id="resultsContainer" style="display: none;">
            <h2>Publish-Ready Short Video Recommendations</h2>
            <div id="clipGrid" class="clip-grid"></div>
        </div>
    </div>

    <script>
        async function runPipeline() {
            const url = document.getElementById('sourceUrl').value;
            const statusBox = document.getElementById('statusBox');
            statusBox.style.display = 'block';
            statusBox.innerHTML = '<div>[System] Starting LangGraph pipeline for: ' + url + '...</div>';
            
            try {
                const res = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ source: url })
                });
                const data = await res.json();
                
                statusBox.innerHTML += '<div>[Success] Analysis finished! Generated ' + data.clips.length + ' top recommendations.</div>';
                renderClips(data.clips);
            } catch(e) {
                statusBox.innerHTML += '<div style="color: #EF4444;">[Error] Pipeline execution failed: ' + e.message + '</div>';
            }
        }

        function renderClips(clips) {
            const container = document.getElementById('resultsContainer');
            const grid = document.getElementById('clipGrid');
            grid.innerHTML = '';
            container.style.display = 'block';

            clips.forEach(clip => {
                const card = document.createElement('div');
                card.className = 'clip-card';
                card.innerHTML = `
                    <div class="rank-badge">RANK #${clip.rank}</div>
                    <div class="clip-title">${clip.title}</div>
                    <div class="timestamp-bar">
                        ⏱️ [${clip.start_timestamp} ➔ ${clip.end_timestamp}] (${clip.duration_seconds.toFixed(1)}s)
                    </div>
                    <div class="hook-box">
                        <strong>Hook:</strong> "${clip.hook}"
                    </div>
                    <div style="font-size: 0.9rem; margin-bottom: 1rem; color: #D1D5DB;">
                        <strong>Summary:</strong> ${clip.one_sentence_summary}
                    </div>
                    <div class="metric-row">
                        <span>Virality Score:</span>
                        <span class="metric-val" style="color: #F59E0B;">${clip.virality_score.toFixed(1)} / 10</span>
                    </div>
                    <div class="metric-row">
                        <span>Confidence Score:</span>
                        <span class="metric-val" style="color: #10B981;">${clip.confidence_score.toFixed(1)} / 10</span>
                    </div>
                    <div class="metric-row">
                        <span>Retention Prediction:</span>
                        <span class="metric-val" style="color: #818CF8;">${clip.viewer_retention_prediction}</span>
                    </div>
                    <div style="font-size: 0.85rem; color: #9CA3AF; margin-top: 0.75rem; border-top: 1px solid #374151; padding-top: 0.75rem;">
                        <strong>Why Selected:</strong> ${clip.why_this_clip_was_selected}
                    </div>
                    <div style="margin-top: 0.75rem;">
                        <strong>Thumbnail Text:</strong> "${clip.suggested_thumbnail_text}"
                    </div>
                    <div style="margin-top: 0.5rem;">
                        ${clip.suggested_hashtags.map(tag => `<span class="tag">${tag}</span>`).join('')}
                    </div>
                `;
                grid.appendChild(card);
            });
        }
    </script>
</body>
</html>
"""

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self):
        if self.path == "/api/analyze":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8")) if body else {}
            
            source = payload.get("source", "https://www.youtube.com/watch?v=sample_podcast")
            pipeline = VideoEditorPipeline()
            final_state = pipeline.run(source)
            
            clips_data = [clip.model_dump() for clip in final_state.final_clips]
            response_payload = {
                "status": "success",
                "title": final_state.podcast_title,
                "logs": final_state.logs,
                "clips": clips_data
            }
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode("utf-8"))
        else:
            self.send_error(404, "Endpoint Not Found")

def run_server(port: int = 5050):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, RequestHandler)
    print(f"[SERVER] AI Video Editor Web Dashboard running at: http://127.0.0.1:{port}")
    httpd.serve_forever()

if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)
