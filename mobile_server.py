#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
APP_FILE = ROOT / "美國加州天天樂_20260618_第1版.py"
TOKEN_FILE = ROOT / "mobile_access_token.txt"
URL_FILE = ROOT / "mobile_access_url.txt"
STATUS_FILE = ROOT / "mobile_status.json"
APP_NAME = "\u5929\u5929\u6a02"
APP_TITLE = APP_NAME + "\u624b\u6a5f\u7368\u7acb\u64cd\u4f5c"
RUN_LOCK = threading.Lock()


def access_token():
    env_token = os.environ.get("TIANTIANLE_TOKEN") or os.environ.get("MOBILE_TOKEN")
    if env_token:
        return env_token.strip()
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(16)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def write_status(status, message):
    payload = {
        "status": status,
        "message": message,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_status():
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "ready", "message": "ready", "time": ""}


def local_addresses():
    addresses = []
    try:
        host = socket.gethostname()
        for item in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = item[4][0]
            if ip not in addresses and not ip.startswith("127."):
                addresses.append(ip)
    except Exception:
        pass
    preferred = []
    for ip in addresses:
        if ip.startswith(("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")):
            preferred.append(ip)
    return preferred or addresses or ["127.0.0.1"]


def mobile_urls(token, port=5525):
    return [f"http://{ip}:{port}/?token={token}" for ip in local_addresses()]


def public_urls(token, port):
    base_url = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if base_url:
        return [f"{base_url}/?token={token}"]
    if os.environ.get("RENDER_EXTERNAL_URL"):
        return [f"{os.environ['RENDER_EXTERNAL_URL'].rstrip('/')}/?token={token}"]
    return mobile_urls(token, port)


def analysis_summary():
    path = ROOT / "reports" / "latest_analysis.json"
    if not path.exists():
        return {"top10": "", "draw_count": "", "latest": "", "release": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"top10": "", "draw_count": "", "latest": "", "release": ""}
    candidates = data.get("candidates") or []
    top10 = []
    for item in candidates[:10]:
        number = item.get("number") if isinstance(item, dict) else item
        try:
            top10.append(f"{int(number):02d}")
        except Exception:
            pass
    latest = data.get("latest_draw") or {}
    if isinstance(latest, dict):
        latest_text = latest.get("draw_date") or latest.get("date") or ""
    else:
        latest_text = str(latest) if latest else ""
    release = "\u53ef\u767c\u5e03" if data.get("official_release_allowed") else "\u89c0\u5bdf\u724c"
    return {
        "top10": " ".join(top10),
        "draw_count": data.get("draw_count", ""),
        "latest": latest_text,
        "release": release,
    }


def run_update():
    if not RUN_LOCK.acquire(blocking=False):
        write_status("running", "already running")
        return
    write_status("running", "updating")
    try:
        result = subprocess.run(
            [sys.executable, str(APP_FILE)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=900,
        )
        if result.returncode == 0:
            write_status("done", "updated")
        else:
            write_status("error", (result.stderr or result.stdout or "failed")[-1200:])
    except Exception as exc:
        write_status("error", str(exc))
    finally:
        RUN_LOCK.release()


def read_file(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def html_page(token):
    status = read_status()
    summary = analysis_summary()
    latest = ROOT / "reports" / "latest_battle_report.md"
    latest_time = ""
    if latest.exists():
        latest_time = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#102033">
<link rel="manifest" href="/manifest.json?token={token}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Tiantianle">
<link rel="apple-touch-icon" href="/icon-192.png?token={token}">
<title>{APP_TITLE}</title>
<style>
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f7fa;color:#172033}}
header{{background:#102033;color:white;padding:18px 16px}}
h1{{font-size:22px;margin:0 0 6px}} p{{margin:5px 0}} main{{padding:14px;max-width:860px;margin:auto}}
.panel{{background:white;border:1px solid #d7dde7;border-radius:8px;padding:14px;margin:12px 0;box-shadow:0 1px 5px #0001}}
.row{{display:flex;gap:10px;flex-wrap:wrap}}
button,a.btn{{appearance:none;border:0;border-radius:8px;background:#1b6fd8;color:white;padding:12px 14px;text-decoration:none;font-weight:700;min-width:132px;text-align:center}}
button.secondary,a.secondary{{background:#40546b}}
.status{{font-size:18px;font-weight:700}} .muted{{color:#657286;font-size:14px}}
.metric{{display:grid;grid-template-columns:96px 1fr;gap:8px;margin:8px 0;font-size:16px}}
.value{{font-weight:800;word-break:break-word}}
iframe{{width:100%;height:72vh;border:1px solid #d7dde7;border-radius:8px;background:white}}
</style>
</head>
<body>
<header><h1>{APP_TITLE}</h1><p>Tiantianle ironlaw independent edition</p></header>
<main>
<section class="panel">
<div class="status" id="status">{status.get("status","ready")} - {status.get("message","")}</div>
<p class="muted">Last report: {latest_time or "report engine ready"}</p>
<div class="metric"><div>Top10</div><div class="value">{summary.get("top10") or "-"}</div></div>
<div class="metric"><div>Latest</div><div class="value">{summary.get("latest") or "-"} / {summary.get("draw_count") or "-"} draws</div></div>
<div class="metric"><div>Release</div><div class="value">{summary.get("release") or "-"}</div></div>
<div class="row">
<button onclick="runNow()">Update and predict</button>
<a class="btn secondary" href="/report?token={token}">Open report</a>
<a class="btn secondary" href="/health-report?token={token}">Health</a>
<a class="btn secondary" href="/analysis.json?token={token}">Analysis JSON</a>
</div>
</section>
<section class="panel">
<iframe src="/report?token={token}" title="report"></iframe>
</section>
</main>
<script>
async function refreshStatus(){{
  const r=await fetch('/api/status?token={token}'); const s=await r.json();
  document.getElementById('status').textContent=(s.status||'ready')+' - '+(s.message||'');
}}
async function runNow(){{
  document.getElementById('status').textContent='running - updating';
  await fetch('/run?token={token}',{{method:'POST'}});
  setTimeout(refreshStatus,1200);
}}
setInterval(refreshStatus,5000);
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', function(){{
    navigator.serviceWorker.register('/service-worker.js?token={token}').catch(function(){{}});
  }});
}}
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def authed(self):
        qs = parse_qs(urlparse(self.path).query)
        return qs.get("token", [""])[0] == access_token()

    def send_text(self, text, content_type="text/html; charset=utf-8", code=200):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data, content_type, code=200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/ping":
            self.send_text('{"status":"ok"}', "application/json; charset=utf-8")
            return
        if path == "/manifest.json":
            manifest = {
                "name": APP_NAME + " Ironlaw Engine",
                "short_name": APP_NAME,
                "start_url": "/?token=" + access_token(),
                "display": "standalone",
                "background_color": "#f5f7fa",
                "theme_color": "#102033",
                "icons": [
                    {"src": "/icon-192.png?token=" + access_token(), "sizes": "192x192", "type": "image/png"},
                    {"src": "/icon-512.png?token=" + access_token(), "sizes": "512x512", "type": "image/png"},
                ],
            }
            self.send_text(json.dumps(manifest, ensure_ascii=False), "application/manifest+json; charset=utf-8")
            return
        if not self.authed():
            self.send_text("Forbidden", "text/plain; charset=utf-8", 403)
            return
        if path in ("/", "/index.html"):
            self.send_text(html_page(access_token()))
        elif path == "/service-worker.js":
            sw = """const CACHE_NAME='tiantianle-local-v1';
self.addEventListener('install',event=>{self.skipWaiting();});
self.addEventListener('activate',event=>{self.clients.claim();});
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET') return;
  event.respondWith(fetch(event.request).then(response=>{
    const copy=response.clone();
    caches.open(CACHE_NAME).then(cache=>cache.put(event.request,copy));
    return response;
  }).catch(()=>caches.match(event.request)));
});
"""
            self.send_text(sw, "application/javascript; charset=utf-8")
        elif path in ("/icon-192.png", "/icon-512.png"):
            icon = ROOT / "site" / path.lstrip("/")
            if icon.exists():
                self.send_bytes(icon.read_bytes(), "image/png")
            else:
                self.send_text("Not found", "text/plain; charset=utf-8", 404)
        elif path == "/report":
            html = read_file(ROOT / "reports" / "tiantianle_ironlaw_battle_report.html")
            self.send_text(html or "<h1>Tiantianle report engine ready</h1><p>Run update and predict to refresh the full report.</p>")
        elif path == "/analysis.json":
            self.send_text(read_file(ROOT / "reports" / "latest_analysis.json") or "{}", "application/json; charset=utf-8")
        elif path == "/health-report":
            self.send_text(read_file(ROOT / "reports" / "system_health_report.md") or "", "text/plain; charset=utf-8")
        elif path == "/api/status":
            self.send_text(json.dumps(read_status(), ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self.send_text("Not found", "text/plain; charset=utf-8", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.authed():
            self.send_text("Forbidden", "text/plain; charset=utf-8", 403)
            return
        if path == "/run":
            import threading

            threading.Thread(target=run_update, daemon=True).start()
            self.send_text(json.dumps({"started": True}, ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self.send_text("Not found", "text/plain; charset=utf-8", 404)

    def log_message(self, fmt, *args):
        return


def main():
    token = access_token()
    port = int(os.environ.get("PORT", "5525"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    urls = public_urls(token, port)
    local_url = f"http://127.0.0.1:{port}/?token={token}"
    text = "Phone URLs:\n" + "\n".join(urls) + "\n\nLocal URL:\n" + local_url + "\n"
    URL_FILE.write_text(text, encoding="utf-8")
    print(text)
    server.serve_forever()


if __name__ == "__main__":
    main()
