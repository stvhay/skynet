#!/usr/bin/env python3
"""Chat bridge: a web UI that activates when an external GET request arrives."""

import asyncio

from aiohttp import web

# State: when a GET /message comes in, we store a Future here
pending_request: asyncio.Future | None = None
# SSE clients waiting to hear about state changes
sse_clients: list[asyncio.Queue] = []


async def broadcast(event: str, data: str = ""):
    for q in sse_clients:
        await q.put(f"event: {event}\ndata: {data}\n\n")


async def index(request):
    return web.Response(text=HTML, content_type="text/html")


async def get_message(request):
    """Long-poll GET: blocks until the UI sends a message.

    If ?reply=... is provided, that text is displayed in the UI as an
    assistant message before blocking for the next human input.
    """
    global pending_request
    if pending_request is not None:
        return web.json_response({"error": "another request already pending"}, status=409)

    # If a reply was included, show it in the UI first
    reply = request.query.get("reply")
    if reply:
        print(f"[DEBUG] reply received: {repr(reply)}")
        await broadcast("response", reply)

    loop = asyncio.get_event_loop()
    pending_request = loop.create_future()
    await broadcast("status", "waiting")

    try:
        message = await pending_request
    finally:
        pending_request = None
        await broadcast("status", "idle")

    return web.json_response({"message": message})


async def post_send(request):
    """Called by the UI to resolve the pending GET."""
    global pending_request
    if pending_request is None or pending_request.done():
        return web.json_response({"error": "no pending request"}, status=400)

    body = await request.json()
    msg = body.get("message", "")
    pending_request.set_result(msg)
    return web.json_response({"ok": True})


async def events(request):
    """SSE stream for UI state updates."""
    q: asyncio.Queue = asyncio.Queue()
    sse_clients.append(q)

    resp = web.StreamResponse()
    resp.headers["Content-Type"] = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Connection"] = "keep-alive"
    await resp.prepare(request)

    # Send current state immediately
    state = "waiting" if (pending_request and not pending_request.done()) else "idle"
    await resp.write(f"event: status\ndata: {state}\n\n".encode())

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
<title>Chat Bridge</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
  #status-bar { padding: 12px 20px; background: #16213e; font-size: 14px; border-bottom: 1px solid #0f3460; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
  .dot.idle { background: #555; }
  .dot.waiting { background: #e94560; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  #messages { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 8px; }
  .msg { padding: 10px 14px; border-radius: 12px; max-width: 70%; word-wrap: break-word; }
  .msg.system { background: #16213e; color: #888; align-self: center; font-size: 13px; }
  .msg.user { background: #0f3460; align-self: flex-end; }
  .msg.assistant { background: #533483; align-self: flex-start; }
  #input-area { padding: 16px 20px; background: #16213e; display: flex; gap: 10px; border-top: 1px solid #0f3460; }
  #msg-input { flex: 1; padding: 10px 14px; border-radius: 8px; border: 1px solid #0f3460; background: #1a1a2e; color: #e0e0e0; font-size: 15px; outline: none; }
  #msg-input:focus { border-color: #e94560; }
  #send-btn { padding: 10px 24px; border-radius: 8px; border: none; background: #e94560; color: white; font-size: 15px; cursor: pointer; transition: opacity 0.2s; }
  #send-btn:disabled { opacity: 0.3; cursor: not-allowed; }
</style>
</head>
<body>
  <div id="status-bar"><span class="dot idle" id="dot"></span><span id="status-text">Idle — waiting for incoming request</span></div>
  <div id="messages">
    <div class="msg system">Chat bridge ready. Send button activates when a GET /message request arrives.</div>
  </div>
  <div id="input-area">
    <input id="msg-input" type="text" placeholder="Type a message..." disabled>
    <button id="send-btn" disabled>Send</button>
  </div>
<script>
  const dot = document.getElementById('dot');
  const statusText = document.getElementById('status-text');
  const messages = document.getElementById('messages');
  const input = document.getElementById('msg-input');
  const btn = document.getElementById('send-btn');

  function addMsg(text, cls) {
    const d = document.createElement('div');
    d.className = 'msg ' + cls;
    d.textContent = text;
    messages.appendChild(d);
    messages.scrollTop = messages.scrollHeight;
  }

  const es = new EventSource('/events');
  es.addEventListener('response', e => {
    addMsg(e.data, 'assistant');
  });
  es.addEventListener('status', e => {
    if (e.data === 'waiting') {
      dot.className = 'dot waiting';
      statusText.textContent = 'Request pending — type your response';
      input.disabled = false;
      btn.disabled = false;
      input.focus();
      addMsg('Incoming request — send button activated', 'system');
    } else {
      dot.className = 'dot idle';
      statusText.textContent = 'Idle — waiting for incoming request';
      input.disabled = true;
      btn.disabled = true;
    }
  });

  async function send() {
    const msg = input.value.trim();
    if (!msg) return;
    addMsg(msg, 'user');
    input.value = '';
    input.disabled = true;
    btn.disabled = true;
    await fetch('/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg})
    });
  }

  btn.addEventListener('click', send);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
</script>
</body>
</html>
"""


app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/message", get_message)
app.router.add_post("/send", post_send)
app.router.add_get("/events", events)

if __name__ == "__main__":
    print("Chat bridge running on http://localhost:8080")
    print("  UI:          GET  /")
    print("  Long-poll:   GET  /message")
    print("  Send (UI):   POST /send")
    web.run_app(app, host="0.0.0.0", port=8080)
