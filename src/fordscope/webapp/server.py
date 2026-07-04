"""Stdlib HTTP server exposing the controller as a JSON API + one embedded page.

No third-party dependencies. ``create_server`` returns a ThreadingHTTPServer bound
to an ephemeral port when ``port=0`` (used by tests); ``run`` serves it and opens
a browser. Real-adapter connection over USB is NEEDS ON-CAR CHECK — the demo
(simulator) path is fully functional here.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .controller import FordScopeController, list_ports, NotConnectedError

INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>FordScope</title>
<style>
 body{background:#0b0d0e;color:#d6dbdd;font:14px/1.5 -apple-system,Menlo,monospace;margin:0;padding:24px}
 h1{color:#39d353;font-size:20px;margin:0 0 12px;letter-spacing:.5px}
 .banner{padding:8px 12px;border-radius:6px;margin:8px 0;min-height:18px;font-weight:600}
 .banner.sim{background:#3a2f00;color:#ffd166}
 .banner.live{background:#3a0d0d;color:#ff6b6b}
 .row{margin:10px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
 select,input,button{background:#15191b;color:#d6dbdd;border:1px solid #2a3033;border-radius:6px;padding:7px 10px;font:inherit}
 button{cursor:pointer;color:#39d353;border-color:#2f5c3a}
 button:hover{background:#1b2320}
 pre{background:#0f1213;border:1px solid #2a3033;border-radius:6px;padding:14px;overflow:auto;min-height:200px;white-space:pre-wrap}
 table{border-collapse:collapse;margin:10px 0}
 td{border:1px solid #2a3033;padding:6px 14px}
 td:last-child{color:#39d353;text-align:right}
 .hint{color:#7d888c;font-size:12px}
</style></head><body>
<h1>FordScope</h1>
<div class="hint">Native macOS diagnostics over your USB adapter (e.g. Vgate vLinker FS) — no Windows VM.</div>
<div id="banner" class="banner"></div>
<div class="row">
  <select id="port"></select>
  <button onclick="connect()">Connect</button>
  <button onclick="disconnect()">Disconnect</button>
</div>
<div class="row">
  <button onclick="run('/api/scan')">Whole-car scan</button>
  <button onclick="run('/api/dtc')">Trouble codes</button>
  <button onclick="run('/api/vin')">VIN</button>
  <button onclick="clearDtc()">Clear codes</button>
  <input id="pid" value="0C" size="4"><button onclick="readPid()">Read PID (hex)</button>
</div>
<div class="row">
  <input id="livepids" value="0C,05,0D" size="18" title="comma-separated hex PIDs">
  <button onclick="startLive()">Start live</button>
  <button onclick="stopLive()">Stop</button>
</div>
<table id="live"></table>
<pre id="out"></pre>
<script>
async function loadPorts(){const r=await fetch('/api/ports');const j=await r.json();
 const s=document.getElementById('port');s.innerHTML='';
 (j.ports||[]).forEach(p=>{const o=document.createElement('option');o.value=p;o.textContent=p;s.appendChild(o);});}
function setBanner(t){const b=document.getElementById('banner');b.textContent=t||'';
 b.className='banner'+(t&&t.indexOf('LIVE')>=0?' live':(t?' sim':''));}
async function connect(){const port=document.getElementById('port').value;
 const r=await fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({port})});
 const j=await r.json();setBanner(j.banner||j.error);}
async function disconnect(){await fetch('/api/disconnect',{method:'POST'});setBanner('');document.getElementById('out').textContent='';}
async function run(url){const r=await fetch(url);const j=await r.json();if(j.banner)setBanner(j.banner);
 document.getElementById('out').textContent=j.text||j.vin||j.error||JSON.stringify(j,null,2);}
async function readPid(){const pid=document.getElementById('pid').value;
 const r=await fetch('/api/read?pid='+encodeURIComponent(pid));const j=await r.json();
 document.getElementById('out').textContent=j.error?j.error:(j.name+': '+j.value+' '+j.unit);}
async function clearDtc(){
 if(!confirm('Clear stored trouble codes? This also resets emissions readiness monitors.'))return;
 const r=await fetch('/api/clear-dtc',{method:'POST'});const j=await r.json();
 if(j.banner)setBanner(j.banner);
 document.getElementById('out').textContent=j.ok?'Trouble codes cleared.':(j.error||'error');}
let liveTimer=null;
async function pollLive(){const pids=document.getElementById('livepids').value;
 const r=await fetch('/api/live?pids='+encodeURIComponent(pids));const j=await r.json();
 const t=document.getElementById('live');
 if(j.error){t.innerHTML='<tr><td>'+j.error+'</td></tr>';stopLive();return;}
 if(j.banner)setBanner(j.banner);
 t.innerHTML=(j.rows||[]).map(x=>'<tr><td>'+x.name+'</td><td>'+(x.value==null?'—':x.value+' '+x.unit)+'</td></tr>').join('');}
function startLive(){stopLive();pollLive();liveTimer=setInterval(pollLive,1000);}
function stopLive(){if(liveTimer){clearInterval(liveTimer);liveTimer=null;}}
loadPorts();
</script></body></html>"""


def _make_handler(controller: FordScopeController):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the console quiet
            pass

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, html):
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body_json(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            u = urlparse(self.path)
            try:
                if u.path == "/":
                    return self._html(INDEX_HTML)
                if u.path == "/api/ports":
                    return self._json({"ports": list_ports()})
                if u.path == "/api/scan":
                    return self._json({"text": controller.scan(), "banner": controller.banner})
                if u.path == "/api/dtc":
                    return self._json({"text": controller.dtc(), "banner": controller.banner})
                if u.path == "/api/vin":
                    return self._json({"vin": controller.vin(), "banner": controller.banner})
                if u.path == "/api/read":
                    pid = int(parse_qs(u.query).get("pid", ["0C"])[0], 16)
                    return self._json(controller.read_pid(pid))
                if u.path == "/api/live":
                    pids_str = parse_qs(u.query).get("pids", ["0C,05,0D"])[0]
                    pids = [int(p, 16) for p in pids_str.split(",") if p.strip()]
                    return self._json({"rows": controller.live(pids), "banner": controller.banner})
                return self._json({"error": "not found"}, 404)
            except NotConnectedError as exc:
                return self._json({"error": str(exc)}, 409)
            except Exception as exc:
                return self._json({"error": str(exc)}, 500)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/api/connect":
                    body = self._body_json()
                    banner = controller.connect(body.get("port", ""), profile=body.get("profile"))
                    return self._json({"banner": banner})
                if u.path == "/api/disconnect":
                    controller.disconnect()
                    return self._json({"ok": True})
                if u.path == "/api/clear-dtc":
                    controller.clear_dtcs()
                    return self._json({"ok": True, "banner": controller.banner})
                return self._json({"error": "not found"}, 404)
            except NotConnectedError as exc:
                return self._json({"error": str(exc)}, 409)
            except Exception as exc:
                return self._json({"error": str(exc)}, 400)

    return Handler


def create_server(controller=None, host="127.0.0.1", port=0) -> ThreadingHTTPServer:
    controller = controller or FordScopeController()
    return ThreadingHTTPServer((host, port), _make_handler(controller))


def run(host="127.0.0.1", port=8737, open_browser=True) -> None:
    server = create_server(host=host, port=port)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"FordScope web app running at {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
