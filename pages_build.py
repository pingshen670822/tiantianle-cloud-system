#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import html
import os
import shutil
import struct
import zlib
from datetime import datetime
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


def build_version():
    analysis_path = REPORT_DIR / "latest_analysis.json"
    if analysis_path.exists():
        try:
            data = json.loads(analysis_path.read_text(encoding="utf-8"))
            stamp = str(data.get("generated_at_taiwan") or data.get("generated_at") or "")
            digits = "".join(ch for ch in stamp if ch.isdigit())
            if digits:
                return digits[:14]
        except Exception:
            pass
    return datetime.now().strftime("%Y%m%d%H%M%S")


def inject_mobile_panel(html):
    repo, workflow_url, page_url = cloud_links()
    version = build_version()
    local_note = ""
    if repo == "OWNER/REPOSITORY":
        local_note = f"<p class=\"cloud-note\">{u('\\u76ee\\u524d\\u662f\\u672c\\u6a5f\\u9810\\u89bd\\uff1b\\u8981\\u8b8a\\u6210\\u624b\\u6a5f\\u514d\\u96fb\\u8166\\u96f2\\u7aef\\u7248\\uff0c\\u8acb\\u5148\\u57f7\\u884c\\u300c\\u5929\\u5929\\u6a02\\u96f2\\u7aef\\u4e00\\u9375\\u4e0a\\u7dda.bat\\u300d\\u3002')}</p>"
    panel = f"""
    <section class="band launch-panel">
      <h2>{u('\\u5929\\u5929\\u6a02\\u624b\\u6a5f\\u96f2\\u7aef\\u7368\\u7acb\\u7248')}</h2>
      <button class="mobile-action" type="button" onclick="forceRefresh()">{u('\\u4e00\\u9375\\u555f\\u52d5\\u6700\\u65b0\\u9810\\u6e2c')}</button>
      <p><a class="cloud-update-link" href="{workflow_url}">{u('\\u767b\\u5165 GitHub \\u5f8c\\u7acb\\u5373\\u96f2\\u7aef\\u66f4\\u65b0')}</a></p>
      <p class="cloud-note">{u('\\u96f2\\u7aef\\u7db2\\u5740')}：<span>{page_url}</span></p>
      {local_note}
    </section>
    <button class="mobile-action sticky-launch" type="button" onclick="forceRefresh()">{u('\\u4e00\\u9375\\u555f\\u52d5\\u6700\\u65b0\\u9810\\u6e2c')}</button>
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
    <link rel="manifest" href="manifest.webmanifest?v={version}">
    <meta name="theme-color" content="#111827">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-title" content="Tiantianle">
    <link rel="apple-touch-icon" href="icon-192.png">
    """
    script = """
    <script>
    async function forceRefresh(){
      if ('serviceWorker' in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(reg => reg.update()));
      }
      if ('caches' in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map(key => caches.delete(key)));
      }
      location.href = 'index.html?v={version}&t=' + Date.now();
    }
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function(){
        navigator.serviceWorker.register('service-worker.js?v={version}', { updateViaCache: 'none' }).then(function(reg){ reg.update(); }).catch(function(){});
      });
    }
    </script>
    """
    style = style.replace("{version}", version)
    script = script.replace("{version}", version)
    html = html.replace("tiantianle_prediction_history.html", "prediction-history.html")
    html = html.replace("</head>", style + "</head>")
    html = html.replace("</body>", script + "</body>")
    return html.replace("<main>", "<main>" + panel, 1)


def copy_text(src, dst):
    if src.exists():
        dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def esc(value):
    return html.escape("" if value is None else str(value))


def fmt_numbers(numbers):
    return " ".join(f"{int(n):02d}" for n in numbers if str(n).strip().isdigit())


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def confidence_level(item):
    confidence = safe_float(item.get("confidence_index", item.get("score", 0)))
    if 0 < confidence <= 1:
        confidence *= 100
    probability = safe_float(item.get("model_probability_percent", 0))
    stability = safe_int(item.get("stability_count", 0))
    cross = item.get("cross_validation") or {}
    passed = safe_int(cross.get("passed_count", 0))
    total = safe_int(cross.get("total_count", 0))
    status = str(cross.get("status", "-") or "-")
    if confidence >= 88 and (probability >= 15 or stability >= 5) and passed >= 3:
        level = u("\\u9ad8\\u4fe1\\u5fc3")
        css = "confidence-high"
    elif confidence >= 85 or probability >= 15 or stability >= 5:
        level = u("\\u4e2d\\u9ad8\\u4fe1\\u5fc3")
        css = "confidence-mid"
    else:
        level = u("\\u89c0\\u5bdf")
        css = "confidence-watch"
    detail = (
        f"{u('\\u4fe1\\u5fc3\\u6307\\u6578')} {round(confidence, 2)} / "
        f"{u('\\u6a21\\u578b\\u6a5f\\u7387')} {round(probability, 2)}% / "
        f"{u('\\u7a69\\u5b9a\\u5171\\u8b58')} {stability} / "
        f"{u('\\u4ea4\\u53c9\\u9a57\\u8b49')} {passed}/{total} {status}"
    )
    return level, detail, css


def build_confidence_rows(candidates):
    rows = []
    for idx, item in enumerate(candidates[:15], 1):
        level, detail, css = confidence_level(item)
        if level == u("\\u89c0\\u5bdf"):
            continue
        reasons = u("\\u3001").join(item.get("reasons", []))
        rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{int(item.get('number')):02d}</td>"
            f"<td><span class=\"{css}\">{esc(level)}</span><br><span class=\"small\">{esc(detail)}</span></td>"
            f"<td>{esc(reasons)}</td>"
            "</tr>"
        )
    if not rows:
        return f"<tr><td colspan=\"4\">{u('\\u5df2\\u5b8c\\u6210\\u904b\\u7b97\\uff0c\\u672c\\u671f\\u7121\\u9ad8\\u4fe1\\u5fc3\\u5019\\u9078\\u3002')}</td></tr>"
    return "".join(rows)


def build_home_page():
    repo, workflow_url, page_url = cloud_links()
    data = {}
    analysis_path = REPORT_DIR / "latest_analysis.json"
    if analysis_path.exists():
        data = json.loads(analysis_path.read_text(encoding="utf-8"))
    freshness = data.get("freshness") or {}
    latest = data.get("latest_draw") or {}
    packs = data.get("strong_packs") or {}
    candidates = data.get("candidates") or []
    top10 = fmt_numbers([item.get("number") for item in candidates[:10]])
    confidence_rows = build_confidence_rows(candidates)
    pack_rows = []
    for key, label in [
        ("strong_single", u("\\u7368\\u652f\\u7cbe\\u6e961\\u4e2d1")),
        ("two_hit_one", "2" + u("\\u4e2d") + "1~2"),
        ("three_hit_two", "3" + u("\\u4e2d") + "2~3"),
        ("five_hit_two", "5" + u("\\u4e2d") + "2~3"),
        ("nine_hit_three", "9" + u("\\u4e2d") + "3~5"),
    ]:
        pack = packs.get(key) or {}
        pack_rows.append(f"<tr><th>{esc(label)}</th><td>{esc(fmt_numbers(pack.get('numbers') or []))}</td><td>{esc(pack.get('hit_goal'))}</td></tr>")
    page_title = u("\\u5929\\u5929\\u6a02 \\u624b\\u6a5f\\u96f2\\u7aef\\u9996\\u9801")
    subtitle = (
        f"{u('\\u5831\\u8868\\u7522\\u751f')} {esc(data.get('generated_at_taiwan'))} / "
        f"{u('\\u6700\\u65b0\\u958b\\u734e')} {esc(latest.get('draw_date'))} / "
        f"{u('\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593\\uff08\\u53f0\\u7063\\uff09')} {esc(freshness.get('target_taiwan_safe_update_time'))}"
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>{esc(page_title)}</title>
<style>
body{{margin:0;font-family:"Microsoft JhengHei",Arial,sans-serif;background:#f6f7fb;color:#111827}}
header{{background:#0f172a;color:white;padding:22px 28px}}header h1{{margin:0 0 8px;font-size:28px}}header p{{margin:0;color:#cbd5e1}}
main{{max-width:980px;margin:auto;padding:18px}}.band{{background:white;border:1px solid #e5e7eb;border-radius:8px;margin-top:14px;padding:16px;overflow-x:auto}}
.tabs{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px}}.tabs a{{display:block;text-align:center;padding:14px;border-radius:8px;background:#e5e7eb;color:#111827;font-weight:900;text-decoration:none}}.tabs a.active{{background:#166534;color:white}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}.card{{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:16px}}.card h2{{margin:0 0 8px;font-size:15px;color:#475569}}.value{{font-size:22px;font-weight:900}}
table{{width:100%;min-width:640px;border-collapse:collapse}}th,td{{border-bottom:1px solid #e5e7eb;padding:10px;text-align:left}}th{{background:#f1f5f9}}
.high-note{{border:3px solid #dc2626;background:#fff1f2;box-shadow:0 0 0 4px #fee2e2 inset}}.high-note h2{{color:#991b1b}}.small{{font-size:13px;color:#475569}}
.confidence-high{{display:inline-block;padding:4px 8px;border-radius:6px;background:#dc2626;color:white;font-weight:900}}.confidence-mid{{display:inline-block;padding:4px 8px;border-radius:6px;background:#f97316;color:white;font-weight:900}}
.primary{{display:block;text-align:center;padding:18px;border-radius:8px;background:#166534;color:white!important;font-size:20px;font-weight:900;text-decoration:none}}
.secondary{{background:#1d4ed8}}.danger{{background:#991b1b}}.url{{word-break:break-all;color:#14532d;font-weight:800}}
@media(max-width:640px){{header{{padding:16px}}header h1{{font-size:22px}}main{{padding:10px}}.tabs{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header><h1>{esc(page_title)}</h1><p>{subtitle}</p></header>
<main>
<nav class="tabs">
<a class="active" href="index.html">{u('\\u9996\\u9801')}</a>
<a href="prediction.html">{u('\\u4e0b\\u671f\\u9810\\u6e2c')}</a>
<a href="review.html">{u('\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e')}</a>
</nav>
<section class="band"><a class="primary" href="prediction.html">{u('\\u67e5\\u770b\\u4e0b\\u671f\\u9810\\u6e2c')}</a></section>
<section class="band"><a class="primary danger" href="review.html">{u('\\u67e5\\u770b\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e')}</a></section>
<section class="band"><a class="primary secondary" href="{esc(workflow_url)}">{u('\\u7acb\\u5373\\u96f2\\u7aef\\u66f4\\u65b0')}</a><p class="url">{esc(page_url)}</p></section>
<section class="band high-note"><h2>{u('\\u9ad8\\u6a5f\\u7387\\uff0f\\u9ad8\\u4fe1\\u5fc3\\u9810\\u6e2c\\u52a0\\u8a3b')}</h2><p>{u('\\u6a5f\\u7387\\u9ad8\\u6216\\u4fe1\\u5fc3\\u9ad8\\u7684\\u865f\\u78bc\\u5df2\\u5f37\\u5236\\u986f\\u793a\\u8aaa\\u660e\\uff0c\\u4e26\\u4fdd\\u7559\\u767c\\u5e03\\u95dc\\u5361\\u72c0\\u614b\\u3002')}</p><table><tr><th>{u('\\u6392\\u540d')}</th><th>{u('\\u865f\\u78bc')}</th><th>{u('\\u9ad8\\u4fe1\\u5fc3\\u8aaa\\u660e')}</th><th>{u('\\u4f86\\u6e90\\u7406\\u7531')}</th></tr>{confidence_rows}</table></section>
<div class="grid">
<section class="card"><h2>{u('\\u6700\\u65b0\\u958b\\u734e\\u65e5')}</h2><div class="value">{esc(latest.get('draw_date'))}</div></section>
<section class="card"><h2>{u('\\u53f0\\u7063\\u53ef\\u66f4\\u65b0\\u6642\\u9593')}</h2><div class="value">{esc(freshness.get('latest_taiwan_safe_update_time'))}</div></section>
<section class="card"><h2>{u('\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593')}</h2><div class="value">{esc(freshness.get('target_taiwan_safe_update_time'))}</div></section>
<section class="card"><h2>{u('\\u5168\\u6b77\\u53f2\\u7b46\\u6578')}</h2><div class="value">{esc(data.get('draw_count'))}</div></section>
</div>
<section class="band"><h2>{u('\\u672c\\u671f\\u6838\\u5fc3\\u9810\\u6e2c\\u6458\\u8981')}</h2><p><strong>Top10:</strong> {esc(top10)}</p><table><tr><th>{u('\\u6a21\\u578b')}</th><th>{u('\\u865f\\u78bc')}</th><th>{u('\\u76ee\\u6a19')}</th></tr>{''.join(pack_rows)}</table></section>
</main>
</body></html>"""


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
    version = build_version()
    offline = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{u('\\u5929\\u5929\\u6a02\\u96e2\\u7dda\\u63d0\\u793a')}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:28px;background:#f6f7fb;color:#111827}}.box{{max-width:680px;margin:auto;background:white;border:1px solid #d8dee9;border-radius:8px;padding:18px}}</style></head>
<body><div class="box"><h1>{u('\\u5929\\u5929\\u6a02')}</h1><p>{u('\\u76ee\\u524d\\u96e2\\u7dda\\uff0c\\u5df2\\u986f\\u793a\\u6700\\u8fd1\\u5feb\\u53d6\\u5167\\u5bb9\\u3002\\u8981\\u66f4\\u65b0\\u6700\\u65b0\\u9810\\u6e2c\\uff0c\\u8acb\\u9023\\u7dda\\u5f8c\\u518d\\u958b\\u555f\\u3002')}</p></div></body></html>"""
    (SITE_DIR / "offline.html").write_text(offline, encoding="utf-8")
    sw = f"""const CACHE_NAME = 'tiantianle-ironlaw-{version}';
const APP_SHELL = ['index.html','prediction.html','review.html','prediction-history.html','latest_analysis.json','system_health_report.md','manifest.webmanifest','offline.html','icon-192.png','icon-512.png'];
self.addEventListener('install', event => {{
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL.map(url => url + '?v={version}')).catch(() => cache.addAll(APP_SHELL))));
  self.skipWaiting();
}});
self.addEventListener('activate', event => {{
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))));
  self.clients.claim();
}});
self.addEventListener('fetch', event => {{
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  const isFreshFile = url.pathname.endsWith('.html') || url.pathname.endsWith('.json') || url.pathname.endsWith('.md') || url.pathname.endsWith('service-worker.js') || url.pathname.endsWith('manifest.webmanifest') || url.pathname.endsWith('/');
  if (isFreshFile) {{
    url.searchParams.set('v', '{version}');
    event.respondWith(fetch(url.toString(), {{ cache: 'no-store' }}).then(response => {{
      const copy = response.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
      return response;
    }}).catch(() => caches.match(event.request).then(hit => hit || caches.match('offline.html'))));
    return;
  }}
  event.respondWith(fetch(event.request).then(response => {{
    const copy = response.clone();
    caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
    return response;
  }}).catch(() => caches.match(event.request).then(hit => hit || caches.match('offline.html'))));
}});
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
<link rel="manifest" href="manifest.webmanifest?v={version}">
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
if('serviceWorker' in navigator) navigator.serviceWorker.register('service-worker.js?v=' + Date.now(), { updateViaCache: 'none' });
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
    index_html = inject_mobile_panel(build_home_page())
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
