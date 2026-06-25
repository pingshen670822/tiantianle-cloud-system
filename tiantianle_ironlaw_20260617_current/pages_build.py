#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import shutil
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
SITE_DIR = ROOT / "site"


def u(text):
    return text.encode("ascii").decode("unicode_escape")


def cloud_links():
    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPOSITORY").strip() or "OWNER/REPOSITORY"
    workflow_url = f"https://github.com/{repo}/actions/workflows/daily-update.yml"
    if "/" in repo:
        owner, name = repo.split("/", 1)
        page_url = f"https://{owner}.github.io/{name}/"
    else:
        page_url = "https://OWNER.github.io/REPOSITORY/"
    return repo, workflow_url, page_url


def inject_mobile_panel(html):
    repo, workflow_url, page_url = cloud_links()
    local_note = ""
    if repo == "OWNER/REPOSITORY":
        local_note = f"<p class=\"cloud-note\">{u('\\u76ee\\u524d\\u662f\\u672c\\u6a5f\\u9810\\u89bd\\uff1b\\u8981\\u8b8a\\u6210\\u624b\\u6a5f\\u514d\\u96fb\\u8166\\u96f2\\u7aef\\u7248\\uff0c\\u8acb\\u5148\\u57f7\\u884c\\u300c\\u5929\\u5929\\u6a02\\u96f2\\u7aef\\u4e00\\u9375\\u4e0a\\u7dda.bat\\u300d\\u3002')}</p>"
    panel = f"""
    <section class="band launch-panel">
      <h2>{u('\\u5929\\u5929\\u6a02\\u624b\\u6a5f\\u96f2\\u7aef\\u7368\\u7acb\\u7248')}</h2>
      <button class="mobile-action" type="button" onclick="location.href='index.html'">{u('\\u4e00\\u9375\\u555f\\u52d5\\u6700\\u65b0\\u9810\\u6e2c')}</button>
      <p><a class="cloud-update-link" href="{workflow_url}">{u('\\u767b\\u5165 GitHub \\u5f8c\\u7acb\\u5373\\u96f2\\u7aef\\u66f4\\u65b0')}</a></p>
      <p class="cloud-note">{u('\\u96f2\\u7aef\\u7db2\\u5740')}：<span>{page_url}</span></p>
      {local_note}
    </section>
    <button class="mobile-action sticky-launch" type="button" onclick="location.href='index.html'">{u('\\u4e00\\u9375\\u555f\\u52d5\\u6700\\u65b0\\u9810\\u6e2c')}</button>
    """
    style = """
    <style>
      .launch-panel{border:3px solid #166534!important;background:#f0fdf4!important}
      .mobile-action{display:block;width:100%;box-sizing:border-box;text-align:center;padding:18px;background:#166534;color:#fff!important;text-decoration:none;border:0;border-radius:8px;font-weight:900;font-size:20px;box-shadow:0 8px 18px rgba(22,101,52,.22)}
      .cloud-update-link{display:block;margin-top:12px;text-align:center;color:#1d4ed8;font-weight:900}
      .cloud-note{font-weight:800;color:#14532d;word-break:break-all}
      .sticky-launch{position:fixed;left:12px;right:12px;bottom:12px;width:calc(100% - 24px);z-index:9999}
      body{padding-bottom:82px}
      @media (max-width:640px){table{min-width:720px}.band{overflow-x:auto}.mobile-action{font-size:20px;padding:18px}}
    </style>
    <link rel="manifest" href="manifest.webmanifest">
    <meta name="theme-color" content="#111827">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-title" content="Tiantianle">
    <link rel="apple-touch-icon" href="icon-192.png">
    """
    script = """
    <script>
    async function forceRefresh(){
      if ('caches' in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map(key => caches.delete(key)));
      }
      location.reload(true);
    }
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function(){
        navigator.serviceWorker.register('service-worker.js?v=2026061602').catch(function(){});
      });
    }
    </script>
    """
    html = html.replace("tiantianle_prediction_history.html", "prediction-history.html")
    html = html.replace("</head>", style + "</head>")
    html = html.replace("</body>", script + "</body>")
    return html.replace("<main>", "<main>" + panel, 1)


def copy_text(src, dst):
    if src.exists():
        dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_icon(path, size):
    bg = (17, 24, 39)
    accent = (22, 101, 52)
    white = (255, 255, 255)
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            cx = x - size / 2
            cy = y - size / 2
            radius = (cx * cx + cy * cy) ** 0.5
            color = bg
            if radius < size * 0.38:
                color = accent
            if abs(cx) < size * 0.07 or abs(cy) < size * 0.07:
                color = white
            if radius < size * 0.12:
                color = (234, 179, 8)
            row.extend(color)
        rows.append(bytes(row))
    raw = b"".join(rows)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def write_pwa_files():
    offline = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{u('\\u5929\\u5929\\u6a02\\u96e2\\u7dda\\u63d0\\u793a')}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:28px;background:#f6f7fb;color:#111827}}.box{{max-width:680px;margin:auto;background:white;border:1px solid #d8dee9;border-radius:8px;padding:18px}}</style></head>
<body><div class="box"><h1>{u('\\u5929\\u5929\\u6a02')}</h1><p>{u('\\u76ee\\u524d\\u96e2\\u7dda\\uff0c\\u5df2\\u986f\\u793a\\u6700\\u8fd1\\u5feb\\u53d6\\u5167\\u5bb9\\u3002\\u8981\\u66f4\\u65b0\\u6700\\u65b0\\u9810\\u6e2c\\uff0c\\u8acb\\u9023\\u7dda\\u5f8c\\u518d\\u958b\\u555f\\u3002')}</p></div></body></html>"""
    (SITE_DIR / "offline.html").write_text(offline, encoding="utf-8")
    sw = """const CACHE_NAME = 'tiantianle-ironlaw-v2';
const APP_SHELL = ['index.html','prediction.html','review.html','prediction-history.html','manifest.webmanifest','offline.html','icon-192.png','icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request).then(response => {
    const copy = response.clone();
    caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
    return response;
  }).catch(() => caches.match(event.request).then(hit => hit || caches.match('offline.html'))));
});
"""
    (SITE_DIR / "service-worker.js").write_text(sw, encoding="utf-8")
    write_icon(SITE_DIR / "icon-192.png", 192)
    write_icon(SITE_DIR / "icon-512.png", 512)


def write_install_page():
    repo, workflow_url, page_url = cloud_links()
    local_note = ""
    if repo == "OWNER/REPOSITORY":
        local_note = "<section class=\"band warn\"><strong>目前你開的是電腦本機檔案。</strong><p>請先雙擊根目錄的「天天樂雲端一鍵上線.bat」。完成後手機要開 GitHub Pages 網址，才是真正免電腦雲端版。</p></section>"
    html = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#111827">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Tiantianle">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-192.png">
<title>天天樂手機雲端獨立版</title>
<style>
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft JhengHei",sans-serif;background:#f6f7fb;color:#111827}
header{background:#111827;color:white;padding:18px}main{max-width:760px;margin:auto;padding:14px}
.band{background:white;border:1px solid #d8dee9;border-radius:8px;margin:12px 0;padding:16px}
.btn{display:block;width:100%;box-sizing:border-box;text-align:center;padding:18px;margin:10px 0;border:0;border-radius:8px;background:#166534;color:#fff;text-decoration:none;font-weight:900;font-size:20px;box-shadow:0 8px 18px rgba(22,101,52,.22)}
.sticky-launch{position:fixed;left:12px;right:12px;bottom:12px;width:calc(100% - 24px);z-index:9999}
body{padding-bottom:82px}
.btn.blue{background:#1d4ed8}.btn.gray{background:#475569}.warn{border-color:#f97316;background:#fff7ed}ol{padding-left:22px}li{margin:8px 0}.url{word-break:break-all;font-weight:900;color:#14532d}
</style>
</head>
<body>
<header><h1>天天樂手機雲端獨立版</h1><p>使用 GitHub Pages 與 GitHub Actions，電腦關機也能從手機開啟。</p></header>
<main>
    """ + local_note + """
<section class="band">
<button id="installBtn" class="btn">一鍵啟動天天樂雲端版</button>
<a class="btn blue" href="__WORKFLOW_URL__">登入 GitHub 後立即雲端更新</a>
</section>
<section class="band"><h2>真正手機網址</h2><p class="url">__PAGE_URL__</p><p>手機安裝必須使用這個 GitHub Pages 網址，不是電腦的 file:/// 路徑。</p></section>
<section class="band">
<h2>Android / Chrome</h2>
<ol><li>手機開 GitHub Pages 網址。</li><li>點上方一鍵啟動天天樂雲端版。</li><li>瀏覽器若跳出安裝提示，選擇安裝 App。</li><li>安裝後從手機主畫面開啟天天樂。</li></ol>
<h2>iPhone / Safari</h2>
<ol><li>點 Safari 分享按鈕。</li><li>選擇「加入主畫面」。</li><li>完成後從主畫面開啟天天樂。</li></ol>
</section>
<section class="band"><p>這是雲端版入口：更新由 GitHub Actions 執行，畫面由 GitHub Pages 提供。手機不需要連回電腦。</p></section>
</main>
<button id="stickyBtn" class="btn sticky-launch">一鍵啟動天天樂雲端版</button>
<script>
let deferredPrompt=null;
window.addEventListener('beforeinstallprompt', function(e){e.preventDefault();deferredPrompt=e;});
async function launchTiantianle(){
  if(deferredPrompt){deferredPrompt.prompt();await deferredPrompt.userChoice;deferredPrompt=null;return;}
  location.href='index.html';
}
document.getElementById('installBtn').addEventListener('click', launchTiantianle);
document.getElementById('stickyBtn').addEventListener('click', launchTiantianle);
if('serviceWorker' in navigator) navigator.serviceWorker.register('service-worker.js?v=2026061602');
</script>
</body></html>"""
    html = html.replace("__WORKFLOW_URL__", workflow_url).replace("__PAGE_URL__", page_url)
    (SITE_DIR / "install.html").write_text(html, encoding="utf-8")


def main():
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORT_DIR / "tiantianle_ironlaw_battle_report.html"
    history = REPORT_DIR / "tiantianle_prediction_history.html"
    prediction = REPORT_DIR / "prediction.html"
    review = REPORT_DIR / "review.html"
    launch_source = prediction if prediction.exists() else report
    index_html = inject_mobile_panel(launch_source.read_text(encoding="utf-8", errors="replace"))
    (SITE_DIR / "index.html").write_text(index_html, encoding="utf-8")
    if prediction.exists():
        (SITE_DIR / "prediction.html").write_text(inject_mobile_panel(prediction.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    if review.exists():
        (SITE_DIR / "review.html").write_text(inject_mobile_panel(review.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    copy_text(history, SITE_DIR / "prediction-history.html")
    copy_text(REPORT_DIR / "latest_analysis.json", SITE_DIR / "latest_analysis.json")
    copy_text(REPORT_DIR / "system_health_report.md", SITE_DIR / "system_health_report.md")
    manifest = {
        "name": u("\\u5929\\u5929\\u6a02\\u624b\\u6a5f\\u7368\\u7acb\\u7248"),
        "short_name": u("\\u5929\\u5929\\u6a02"),
        "start_url": "index.html",
        "scope": "./",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f6f7fb",
        "theme_color": "#111827",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (SITE_DIR / "manifest.webmanifest").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_pwa_files()
    write_install_page()
    print(SITE_DIR / "index.html")


if __name__ == "__main__":
    main()
