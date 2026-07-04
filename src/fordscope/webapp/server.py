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

INDEX_HTML = r"""<!doctype html>
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
  <select id="profile" title="module profile for scans">
    <option value="">Vehicle: Auto</option>
    <option value="fusion2016">2016 Ford Fusion</option>
    <option value="generic">Generic Ford</option>
  </select>
  <button onclick="connect()">Connect</button>
  <button onclick="disconnect()">Disconnect</button>
</div>
<div class="row">
  <button onclick="run('/api/scan')">Whole-car scan</button>
  <button onclick="run('/api/dtc')">Trouble codes</button>
  <button onclick="run('/api/vin')">VIN</button>
  <button onclick="showFreeze()">Freeze frame</button>
  <button onclick="showReadiness()">Readiness</button>
  <button onclick="showDriveCycle()">Drive cycle</button>
  <button onclick="showCalibration()">Calibration</button>
  <button onclick="showDtcStates()">DTC states</button>
  <button onclick="showMonitors()">Monitor tests</button>
  <button onclick="showReport()">Health report</button>
  <button onclick="window.location='/api/report.txt'">Download report</button>
  <button onclick="clearDtc()">Clear codes</button>
  <input id="pid" value="0C" size="4"><button onclick="readPid()">Read PID (hex)</button>
</div>
<div class="row">
  <input id="livepids" value="0C,05,0D" size="18" title="comma-separated hex PIDs">
  <button onclick="startLive()">Start live</button>
  <button onclick="stopLive()">Stop</button>
  <button onclick="showSupported()">Supported PIDs</button>
  <input id="logsamples" value="10" size="4" title="samples"><button onclick="downloadLog()">Download log (CSV)</button>
</div>
<div id="supported" class="row"></div>
<table id="live"></table>
<pre id="out"></pre>
<script>
async function loadPorts(){const r=await fetch('/api/ports');const j=await r.json();
 const s=document.getElementById('port');s.innerHTML='';
 (j.ports||[]).forEach(p=>{const o=document.createElement('option');o.value=p;o.textContent=p;s.appendChild(o);});}
function setBanner(t){const b=document.getElementById('banner');b.textContent=t||'';
 b.className='banner'+(t&&t.indexOf('LIVE')>=0?' live':(t?' sim':''));}
async function connect(){const port=document.getElementById('port').value;
 const profile=document.getElementById('profile').value||null;
 const r=await fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({port,profile})});
 const j=await r.json();setBanner(j.banner||j.error);}
async function disconnect(){await fetch('/api/disconnect',{method:'POST'});setBanner('');document.getElementById('out').textContent='';}
async function run(url){const r=await fetch(url);const j=await r.json();if(j.banner)setBanner(j.banner);
 document.getElementById('out').textContent=j.text||j.vin||j.error||JSON.stringify(j,null,2);}
async function readPid(){const pid=document.getElementById('pid').value;
 const r=await fetch('/api/read?pid='+encodeURIComponent(pid));const j=await r.json();
 document.getElementById('out').textContent=j.error?j.error:(j.name+': '+j.value+' '+j.unit);}
async function showReport(){const r=await fetch('/api/report');const j=await r.json();
 if(j.banner)setBanner(j.banner);
 document.getElementById('out').textContent=j.report||j.error||'';}
async function showReadiness(){const r=await fetch('/api/readiness');const j=await r.json();
 if(j.banner)setBanner(j.banner);
 if(j.error){document.getElementById('out').textContent=j.error;return;}
 const pass=j.ready && !j.mil_on;
 let s=(pass?'READY — likely to PASS inspection':'NOT READY — would likely FAIL')+'\n';
 s+='  Check-engine (MIL): '+(j.mil_on?'ON':'off')+'\n';
 s+='  Stored trouble codes: '+j.dtc_count;
 if(j.not_ready && j.not_ready.length) s+='\n  Monitors not complete: '+j.not_ready.join(', ');
 document.getElementById('out').textContent=s;}
async function showFreeze(){const r=await fetch('/api/freeze');const j=await r.json();
 if(j.banner)setBanner(j.banner);
 if(j.error){document.getElementById('out').textContent=j.error;return;}
 let s='Freeze frame '+(j.dtc?'(triggered by '+j.dtc+')':'(no stored freeze frame)')+':\n';
 s+=(j.rows||[]).map(x=>'  '+x.name+': '+x.value+' '+x.unit).join('\n');
 document.getElementById('out').textContent=s;}
async function showCalibration(){const r=await fetch('/api/calibration');const j=await r.json();
 if(j.banner)setBanner(j.banner);
 if(j.error){document.getElementById('out').textContent=j.error;return;}
 let s='Calibration IDs: '+((j.calids&&j.calids.length)?j.calids.join(', '):'(none reported)')+'\n';
 s+='CVN: '+((j.cvns&&j.cvns.length)?j.cvns.join(', '):'(none reported)');
 document.getElementById('out').textContent=s;}
async function showDtcStates(){const r=await fetch('/api/dtc-states');const j=await r.json();
 if(j.banner)setBanner(j.banner);
 if(j.error){document.getElementById('out').textContent=j.error;return;}
 let s='';['confirmed','pending','permanent'].forEach(k=>{const b=j[k];if(!b)return;
  s+=k.toUpperCase()+(b.available===false?' (could not read)':'')+' — '+b.meaning+'\n';
  s+=(b.codes&&b.codes.length?b.codes.map(c=>'  '+c.code+' '+(c.definition||'')).join('\n'):'  (none)')+'\n\n';});
 document.getElementById('out').textContent=s.trim();}
async function showMonitors(){const r=await fetch('/api/monitor-tests');const j=await r.json();
 if(j.banner)setBanner(j.banner);
 if(j.error){document.getElementById('out').textContent=j.error;return;}
 const ms=j.monitors||[];
 let s=ms.length?'Emission monitor self-tests (Mode 06):\n':'No Mode 06 monitor data.';
 ms.forEach(m=>{const pass=m.tests.every(t=>t.passed);
  s+='  '+m.category+': '+(pass?'PASS':'FAIL')+(m.standardized?'':' [OEM-specific MID]')+'\n';
  m.tests.forEach(t=>{s+='    TID '+t.tid_hex+': '+t.value+'  ['+t.min+'..'+t.max+']  '+(t.passed?'ok':'OUT OF RANGE')+'\n';});});
 document.getElementById('out').textContent=s;}
async function showDriveCycle(){const r=await fetch('/api/drive-cycle');const j=await r.json();
 if(j.banner)setBanner(j.banner);
 if(j.error){document.getElementById('out').textContent=j.error;return;}
 const tips=j.tips||[];
 let s=tips.length?'Drive-cycle guidance for not-ready monitors:\n':'All monitors ready — no drive cycle needed.';
 tips.forEach(t=>{s+='  • '+t.monitor+(t.ford_verified?' [Ford-verified]':' (generic)')+': '+t.guidance+'\n';});
 document.getElementById('out').textContent=s;}
async function clearDtc(){
 if(!confirm('Clear stored trouble codes? This also resets emissions readiness monitors.'))return;
 const r=await fetch('/api/clear-dtc',{method:'POST'});const j=await r.json();
 if(j.banner)setBanner(j.banner);
 document.getElementById('out').textContent=j.ok?'Trouble codes cleared.':(j.error||'error');}
let liveTimer=null;
let liveHistory={};
function sparkline(vals){const w=120,h=24,n=vals.length;if(n<2)return '';
 const nums=vals.filter(v=>typeof v==='number');if(nums.length<2)return '';
 const lo=Math.min(...nums),hi=Math.max(...nums),span=(hi-lo)||1;
 const pts=vals.map((v,i)=>{const x=(i/(n-1))*w;const y=typeof v==='number'?h-((v-lo)/span)*h:h;return x.toFixed(1)+','+y.toFixed(1);}).join(' ');
 return '<svg class="spark" width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none"><polyline fill="none" stroke="#c0392b" stroke-width="1.5" points="'+pts+'"/></svg>';}
async function pollLive(){const pids=document.getElementById('livepids').value;
 const r=await fetch('/api/live?pids='+encodeURIComponent(pids));const j=await r.json();
 const t=document.getElementById('live');
 if(j.error){t.innerHTML='<tr><td>'+j.error+'</td></tr>';stopLive();return;}
 if(j.banner)setBanner(j.banner);
 (j.rows||[]).forEach(x=>{const k=x.pid;if(!(k in liveHistory))liveHistory[k]=[];const hh=liveHistory[k];hh.push(typeof x.value==='number'?x.value:null);if(hh.length>40)hh.shift();});
 t.innerHTML=(j.rows||[]).map(x=>'<tr><td>'+x.name+'</td><td>'+(x.value==null?'—':x.value+' '+x.unit)+'</td><td>'+sparkline(liveHistory[x.pid]||[])+'</td></tr>').join('');}
function startLive(){stopLive();liveHistory={};pollLive();liveTimer=setInterval(pollLive,1000);}
function stopLive(){if(liveTimer){clearInterval(liveTimer);liveTimer=null;}}
function downloadLog(){const pids=document.getElementById('livepids').value;
 const n=document.getElementById('logsamples').value;
 window.location='/api/log?pids='+encodeURIComponent(pids)+'&samples='+encodeURIComponent(n);}
function addLive(hex){const i=document.getElementById('livepids');
 const cur=i.value.split(',').map(s=>s.trim()).filter(Boolean);
 if(!cur.includes(hex)){cur.push(hex);i.value=cur.join(',');}}
async function showSupported(){const r=await fetch('/api/supported');const j=await r.json();
 if(j.banner)setBanner(j.banner);const d=document.getElementById('supported');
 if(j.error){d.textContent=j.error;return;}
 d.innerHTML=(j.pids||[]).map(p=>'<button title="'+(p.decodable?'add to live dashboard':'no decoder yet')+'" onclick="addLive(\''+p.hex+'\')">'+p.hex+' '+p.name+'</button>').join('');}
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

        def _download(self, text, filename, content_type):
            body = text.encode()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _csv(self, text, filename="fordscope-log.csv"):
            self._download(text, filename, "text/csv")

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
                    text, banner = controller.snapshot(controller.scan)
                    return self._json({"text": text, "banner": banner})
                if u.path == "/api/dtc":
                    text, banner = controller.snapshot(controller.dtc)
                    return self._json({"text": text, "banner": banner})
                if u.path == "/api/vin":
                    vin, banner = controller.snapshot(controller.vin)
                    return self._json({"vin": vin, "banner": banner})
                if u.path == "/api/read":
                    pid = int(parse_qs(u.query).get("pid", ["0C"])[0], 16)
                    return self._json(controller.read_pid(pid))
                if u.path == "/api/live":
                    pids_str = parse_qs(u.query).get("pids", ["0C,05,0D"])[0]
                    pids = [int(p, 16) for p in pids_str.split(",") if p.strip()]
                    rows, banner = controller.snapshot(lambda: controller.live(pids))
                    return self._json({"rows": rows, "banner": banner})
                if u.path == "/api/supported":
                    pids, banner = controller.snapshot(controller.supported_pids)
                    return self._json({"pids": pids, "banner": banner})
                if u.path == "/api/freeze":
                    fr, banner = controller.snapshot(controller.freeze_frame)
                    return self._json({**fr, "banner": banner})
                if u.path == "/api/readiness":
                    rd, banner = controller.snapshot(controller.readiness)
                    return self._json({**rd, "banner": banner})
                if u.path == "/api/calibration":
                    cal, banner = controller.snapshot(controller.calibration)
                    return self._json({**cal, "banner": banner})
                if u.path == "/api/live-stats":
                    stats, banner = controller.snapshot(controller.live_stats)
                    return self._json({"stats": stats, "banner": banner})
                if u.path == "/api/dtc-states":
                    st, banner = controller.snapshot(controller.dtc_states)
                    return self._json({**st, "banner": banner})
                if u.path == "/api/monitor-tests":
                    monitors, banner = controller.snapshot(controller.monitor_tests)
                    return self._json({"monitors": monitors, "banner": banner})
                if u.path == "/api/drive-cycle":
                    tips, banner = controller.snapshot(controller.drive_cycle_coach)
                    return self._json({"tips": tips, "banner": banner})
                if u.path == "/api/report":
                    report, banner = controller.snapshot(controller.health_report)
                    return self._json({"report": report, "banner": banner})
                if u.path == "/api/report.txt":
                    return self._download(
                        controller.health_report(), "fordscope-health-report.txt", "text/plain"
                    )
                if u.path == "/api/log":
                    q = parse_qs(u.query)
                    pids = [int(p, 16) for p in q.get("pids", ["0C,05,0D"])[0].split(",") if p.strip()]
                    samples = min(int(q.get("samples", ["10"])[0]), 1000)
                    return self._csv(controller.log_csv(pids, samples))
                return self._json({"error": "not found"}, 404)
            except NotConnectedError as exc:
                return self._json({"error": str(exc)}, 409)
            except ValueError as exc:  # bad hex/int query param -> client error
                return self._json({"error": str(exc)}, 400)
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
                    _, banner = controller.snapshot(controller.clear_dtcs)
                    return self._json({"ok": True, "banner": banner})
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
    finally:
        # shutdown() stops the serve loop but does NOT release the listening socket;
        # server_close() does. Without it, each run/Ctrl-C cycle leaks one fd.
        server.server_close()
