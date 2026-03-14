#!/usr/bin/env python3
"""Live diagram viewer: push SVGs/images to a browser without reloading."""

import asyncio
import json
import os
import re
from pathlib import Path
from aiohttp import web
import markdown

BASE_DIR = Path(__file__).parent
sse_clients: list[asyncio.Queue] = []


async def broadcast(event: str, data: str):
    lines = data.split("\n")
    msg = f"event: {event}\n" + "\n".join(f"data: {line}" for line in lines) + "\n\n"
    for q in sse_clients:
        await q.put(msg)


async def index(request):
    return web.Response(text=HTML, content_type="text/html")


async def post_show(request):
    """POST /show — push SVG content to the viewer."""
    body = await request.json()
    svg = body.get("svg", "")
    title = body.get("title", "")
    await broadcast("diagram", json.dumps({"svg": svg, "title": title}))
    return web.json_response({"ok": True})


async def post_clear(request):
    """POST /clear — clear all slides in the viewer."""
    await broadcast("clear", "")
    return web.json_response({"ok": True})


async def post_render_doc(request):
    """POST /render — render DESIGN.md with inline SVGs."""
    body = await request.json()
    md_path = Path(body.get("path", str(BASE_DIR / "DESIGN.md")))

    if not md_path.exists():
        return web.json_response({"error": f"not found: {md_path}"}, status=404)

    md_text = md_path.read_text()
    md_dir = md_path.parent

    # Extract SVG figures first, replace with placeholders
    figures = {}
    fig_idx = [0]

    def replace_svg_ref(match):
        alt = match.group(1)
        path = match.group(2)
        svg_path = md_dir / path
        if svg_path.exists() and path.endswith(".svg"):
            svg_content = svg_path.read_text()
            key = f"XFIGX{fig_idx[0]}XFIGX"
            figures[key] = f'<div class="figure"><div class="figure-title">{alt}</div><div class="figure-body">{svg_content}</div></div>'
            fig_idx[0] += 1
            return key
        return match.group(0)

    # Replace ![alt](path.svg) and > ![alt](path.svg) patterns
    md_text = re.sub(r'>\s*!\[([^\]]*)\]\(([^)]+\.svg)\)', replace_svg_ref, md_text)
    md_text = re.sub(r'!\[([^\]]*)\]\(([^)]+\.svg)\)', replace_svg_ref, md_text)

    # Remove ASCII code blocks that immediately follow an SVG figure placeholder
    # (the DESIGN.md has both SVG refs and ASCII fallbacks; browser only needs SVG)
    md_text = re.sub(r'(XFIGX\d+XFIGX)\s*\n```[^\n]*\n[\s\S]*?```', r'\1', md_text)

    # Render markdown to HTML using python-markdown
    html_content = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

    # Re-insert figures (and unwrap any <p> tags the renderer may have added)
    for key, fig_html in figures.items():
        html_content = html_content.replace(f"<p>{key}</p>", fig_html)
        html_content = html_content.replace(key, fig_html)

    await broadcast("document", json.dumps({"html": html_content}))
    return web.json_response({"ok": True})


async def events(request):
    q: asyncio.Queue = asyncio.Queue()
    sse_clients.append(q)

    resp = web.StreamResponse()
    resp.headers["Content-Type"] = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Connection"] = "keep-alive"
    await resp.prepare(request)

    try:
        while True:
            chunk = await q.get()
            await resp.write(chunk.encode())
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        sse_clients.remove(q)
    return resp


HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MCP Mesh — Design Document</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0d1117; color: #c9d1d9; min-height: 100vh; }
  #header { padding: 12px 24px; background: #161b22; border-bottom: 1px solid #30363d; display: flex; align-items: center; gap: 12px; }
  #header h1 { font-size: 16px; font-weight: 500; color: #8b949e; }
  #status { color: #484f58; font-size: 13px; }

  #content { max-width: 900px; margin: 0 auto; padding: 32px 24px; }

  /* Slides mode */
  #slides { display: flex; flex-direction: column; gap: 24px; }
  .slide { background: #161b22; border: 1px solid #30363d; border-radius: 12px; overflow: hidden; }
  .slide-title { padding: 12px 20px; font-size: 14px; font-weight: 600; border-bottom: 1px solid #30363d; color: #c9d1d9; }
  .slide-body { padding: 20px; display: flex; justify-content: center; align-items: center; }
  .slide-body svg { max-width: 100%; height: auto; }

  /* Document mode */
  #document { display: none; }
  #document.active { display: block; }
  #slides.hidden { display: none; }

  #document h1 { font-size: 28px; color: #e6edf3; margin: 32px 0 16px; padding-bottom: 8px; border-bottom: 1px solid #30363d; }
  #document h1:first-child { margin-top: 0; }
  #document h2 { font-size: 22px; color: #e6edf3; margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #21262d; }
  #document h3 { font-size: 16px; color: #e6edf3; margin: 20px 0 8px; }
  #document p { line-height: 1.7; margin: 8px 0; color: #c9d1d9; }
  #document code { background: #1a1a2e; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 13px; color: #e94560; }
  #document pre { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin: 12px 0; overflow-x: auto; }
  #document pre code { background: none; padding: 0; color: #c9d1d9; font-size: 12px; white-space: pre; }
  #document table { border-collapse: collapse; margin: 12px 0; width: 100%; }
  #document td { padding: 8px 12px; border: 1px solid #30363d; font-size: 13px; }
  #document tr:nth-child(1) td { background: #161b22; font-weight: 600; color: #e6edf3; }
  #document ul, #document ol { margin: 8px 0; padding-left: 24px; }
  #document li { line-height: 1.7; margin: 4px 0; }
  #document strong { color: #e6edf3; }
  #document a { color: #58a6ff; text-decoration: none; }

  .figure { background: #161b22; border: 1px solid #30363d; border-radius: 12px; margin: 20px 0; overflow: hidden; }
  .figure-title { padding: 10px 20px; font-size: 13px; font-weight: 600; color: #8b949e; border-bottom: 1px solid #30363d; }
  .figure-body { padding: 16px; display: flex; justify-content: center; }
  .figure-body svg { max-width: 100%; height: auto; }

  .new { animation: fadeIn 0.3s ease-out; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
</style>
</head>
<body>
  <div id="header">
    <h1>Live Viewer</h1>
    <span id="status">waiting...</span>
  </div>
  <div id="content">
    <div id="slides"></div>
    <div id="document"></div>
  </div>
<script>
  const slides = document.getElementById('slides');
  const doc = document.getElementById('document');
  const status = document.getElementById('status');
  let n = 0;

  const es = new EventSource('/events');

  es.addEventListener('diagram', e => {
    const {svg, title} = JSON.parse(e.data);
    n++;
    status.textContent = n + ' diagram' + (n === 1 ? '' : 's');
    slides.classList.remove('hidden');

    const div = document.createElement('div');
    div.className = 'slide new';
    div.innerHTML = (title ? '<div class="slide-title">' + title.replace(/</g,'&lt;') + '</div>' : '')
      + '<div class="slide-body">' + svg + '</div>';
    slides.appendChild(div);
    div.scrollIntoView({behavior: 'smooth', block: 'end'});
  });

  es.addEventListener('clear', e => {
    slides.innerHTML = '';
    doc.innerHTML = '';
    doc.classList.remove('active');
    slides.classList.remove('hidden');
    n = 0;
    status.textContent = 'cleared';
  });

  es.addEventListener('document', e => {
    const {html} = JSON.parse(e.data);
    slides.classList.add('hidden');
    doc.classList.add('active');
    doc.innerHTML = html;
    status.textContent = 'document rendered';
    window.scrollTo({top: 0, behavior: 'smooth'});
  });
</script>
</body>
</html>
"""

app = web.Application()
app.router.add_get("/", index)
app.router.add_post("/show", post_show)
app.router.add_post("/clear", post_clear)
app.router.add_post("/render", post_render_doc)
app.router.add_get("/events", events)

if __name__ == "__main__":
    print("Live viewer on http://localhost:8080")
    web.run_app(app, host="0.0.0.0", port=8080)
