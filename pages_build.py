#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import html
import os
import shutil
import struct
import subprocess
import zlib
from datetime import datetime
from itertools import combinations
from pathlib import Path

from 中文顯示工具 import localize_plain_text, localize_visible_html, write_alias


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
SITE_DIR = ROOT / "site"
DEFAULT_CLOUD_REPO = "pingshen670822/tiantianle-cloud-system"
SITE_BUILD_VERSION = datetime.now().strftime("%Y%m%d%H%M%S")


def u(text):
    return text.encode("ascii").decode("unicode_escape")


def repo_from_git_remote():
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
        ).strip()
    except Exception:
        return ""
    if remote.endswith(".git"):
        remote = remote[:-4]
    if remote.startswith("git@github.com:"):
        repo = remote.split(":", 1)[1]
    elif "github.com/" in remote:
        repo = remote.split("github.com/", 1)[1]
    else:
        return ""
    repo = repo.strip("/")
    parts = [part for part in repo.split("/") if part]
    if len(parts) < 2:
        return ""
    return "/".join(parts[-2:])


def cloud_links():
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip() or DEFAULT_CLOUD_REPO or repo_from_git_remote()
    if "/" not in repo:
        repo = DEFAULT_CLOUD_REPO
    workflow_url = f"https://github.com/{repo}/actions/workflows/daily-update.yml"
    owner, name = repo.split("/", 1)
    page_url = f"https://{owner}.github.io/{name}/"
    saved_url_path = ROOT / "tiantianle-mobile-cloud-url.txt"
    if saved_url_path.exists():
        saved_url = saved_url_path.read_text(encoding="utf-8", errors="ignore").strip()
        expected = page_url.rstrip("/")
        if saved_url.startswith("https://") and saved_url.rstrip("/") == expected:
            page_url = saved_url.rstrip("/") + "/"
    return repo, workflow_url, page_url


def build_version():
    return SITE_BUILD_VERSION
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
      <a class="mobile-action" href="{workflow_url}">{u('\\u4e00\\u9375\\u96f2\\u7aef\\u66f4\\u65b0\\u6700\\u65b0\\u958b\\u734e')}</a>
      <button class="mobile-refresh" type="button" onclick="forceRefresh()">{u('\\u91cd\\u65b0\\u8b80\\u53d6\\u96f2\\u7aef\\u6700\\u65b0\\u9801')}</button>
      <a class="cloud-update-link" href="reset.html?v={version}">{u('\\u624b\\u6a5f\\u6c92\\u66f4\\u65b0\\u9ede\\u9019\\u88e1\\u6e05\\u9664\\u820a\\u5feb\\u53d6')}</a>
      <p class="cloud-note">{u('\\u96f2\\u7aef\\u7db2\\u5740')}：<span>{u('\\u5df2\\u8a2d\\u5b9a\\uff0c\\u624b\\u6a5f\\u53ef\\u76f4\\u63a5\\u6536\\u85cf\\u672c\\u9801')}</span></p>
      <p class="cloud-note" id="mobileUpdateStatus">{u('\\u7248\\u672c')} {version}</p>
      {local_note}
    </section>
    <a class="mobile-action sticky-launch" href="{workflow_url}">{u('\\u4e00\\u9375\\u96f2\\u7aef\\u66f4\\u65b0')}</a>
    """
    style = """
    <style>
      .launch-panel{border:3px solid #166534!important;background:#f0fdf4!important}
      .mobile-action{display:block;width:100%;box-sizing:border-box;text-align:center;padding:18px;background:#166534;color:#fff!important;text-decoration:none;border:0;border-radius:8px;font-weight:900;font-size:20px;box-shadow:0 8px 18px rgba(22,101,52,.22)}
      .mobile-refresh{display:block;width:100%;box-sizing:border-box;text-align:center;margin-top:10px;padding:13px;background:#1d4ed8;color:#fff!important;border:0;border-radius:8px;font-weight:900;font-size:16px}
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
    window.TIANTIANLE_BUILD_VERSION = '{version}';
    function setMobileStatus(text) {
      var el = document.getElementById('mobileUpdateStatus');
      if (el) el.textContent = text;
    }
    async function clearMobileCaches() {
      if ('serviceWorker' in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(async function(reg) {
          try {
            if (reg.active) reg.active.postMessage({ type: 'CLEAR_CACHE' });
            await reg.update();
            await reg.unregister();
          } catch (err) {}
        }));
      }
      if ('caches' in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map(function(key) { return caches.delete(key); }));
      }
    }
    const REFRESH_CHECK_MS = 30000;
    async function forceRefresh() {
      setMobileStatus('更新中 ' + new Date().toLocaleTimeString());
      await clearMobileCaches();
      try {
        await fetch('latest_analysis.json?force=' + Date.now(), { cache: 'no-store' });
      } catch (err) {}
      location.replace('首頁.html?v={version}&force=' + Date.now());
    }
    async function autoRefreshIfStale() {
      try {
        const res = await fetch('version.json?check=' + Date.now(), { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        const stamp = String(data.version || data.generated_at_taiwan || data.generated_at || '').replace(/\\D/g, '').slice(0, 14);
        if (stamp && stamp !== window.TIANTIANLE_BUILD_VERSION && !sessionStorage.getItem('tiantianle_refreshed_' + stamp)) {
          sessionStorage.setItem('tiantianle_refreshed_' + stamp, '1');
          await clearMobileCaches();
          location.replace('首頁.html?v=' + stamp + '&auto=' + Date.now());
        }
      } catch (err) {}
    }
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function(){
        navigator.serviceWorker.register('service-worker.js?v={version}', { updateViaCache: 'none' }).then(function(reg){
          reg.update();
          if (reg.waiting) reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        }).catch(function(){});
        autoRefreshIfStale();
        setInterval(autoRefreshIfStale, REFRESH_CHECK_MS);
      });
      document.addEventListener('visibilitychange', function() {
        if (!document.hidden) autoRefreshIfStale();
      });
      window.addEventListener('online', autoRefreshIfStale);
      navigator.serviceWorker.addEventListener('controllerchange', function() {
        if (!sessionStorage.getItem('tiantianle_controller_reloaded')) {
          sessionStorage.setItem('tiantianle_controller_reloaded', '1');
          location.reload();
        }
      });
    } else {
      window.addEventListener('load', autoRefreshIfStale);
      document.addEventListener('visibilitychange', function() {
        if (!document.hidden) autoRefreshIfStale();
      });
      window.addEventListener('online', autoRefreshIfStale);
      setInterval(autoRefreshIfStale, REFRESH_CHECK_MS);
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


def prefer_chinese_links(html_text):
    replacements = {
        'href="reports/完整_report.html"': 'href="reports/complete_report.html"',
        "href='reports/完整_report.html'": "href='reports/complete_report.html'",
        'href="完整_report.html"': 'href="complete_report.html"',
        "href='完整_report.html'": "href='complete_report.html'",
        'href="index.html"': 'href="首頁.html"',
        'href="prediction.html"': 'href="下期預測.html"',
        'href="review.html"': 'href="上期未命中檢討.html"',
        'href="prediction-history.html"': 'href="預測歷史對比.html"',
        'href="tiantianle_prediction_history.html"': 'href="預測歷史對比.html"',
        'href="monthly_summary.html"': 'href="每月總整理.html"',
        'href="reports/latest_battle_report.html"': 'href="reports/complete_report.html"',
        'href="reset.html': 'href="清除快取.html',
        'href="install.html': 'href="安裝手機版.html',
    }
    result = html_text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def finalize_user_html(html_text):
    return prefer_chinese_links(localize_visible_html(html_text))


def reset_dir(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_public_tree(src, dst):
    if not src.exists():
        return
    reset_dir(dst)
    blocked_name_parts = ("token", "secret", "credential", "password", "github_device_login")
    blocked_names = {".env", ".env.local", ".env.production"}
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if lowered in blocked_names or any(part in lowered for part in blocked_name_parts):
            continue
        if "__pycache__" in path.parts or path.suffix.lower() == ".pyc":
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def write_version_file():
    version = build_version()
    analysis_path = REPORT_DIR / "latest_analysis.json"
    payload = {"version": version, "generated_at_taiwan": "", "latest_draw_date": "", "target_draw_date": ""}
    if analysis_path.exists():
        try:
            data = json.loads(analysis_path.read_text(encoding="utf-8"))
            latest = data.get("latest_draw") or {}
            payload.update(
                {
                    "generated_at_taiwan": data.get("generated_at_taiwan") or data.get("generated_at") or "",
                    "latest_draw_date": latest.get("draw_date") or "",
                    "target_draw_date": data.get("target_draw_date") or "",
                }
            )
        except Exception:
            pass
    version_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (SITE_DIR / "version.json").write_text(version_text, encoding="utf-8")
    (SITE_DIR / "版本.json").write_text(version_text, encoding="utf-8")


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


def zh_text(value):
    if value is None or value == "":
        return "-"
    return localize_plain_text(str(value))


def display_time(value):
    text = "" if value is None else str(value)
    if not text:
        return "-"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except Exception:
        text = text.replace("T", " ")
        if "+" in text:
            text = text.split("+", 1)[0]
        return text[:16] if len(text) >= 16 else text


def zh_join(values, limit=None):
    cleaned = []
    for value in values or []:
        if isinstance(value, dict):
            text = value.get("label") or value.get("name") or value.get("model") or value.get("source") or ""
        else:
            text = value
        text = zh_text(text).strip()
        if text and text != "-":
            cleaned.append(text)
    if limit:
        cleaned = cleaned[:limit]
    return "、".join(cleaned) or "-"


def mobile_status(value):
    mapping = {
        "passed": "通過",
        "watch_only": "觀察中",
        "watch": "觀察",
        "mature": "成熟通過",
        "high_confidence_watch": "高信心觀察",
        "usable_watch": "可觀察",
        "usable_觀察": "可觀察",
        "precision_watch": "精算觀察",
        "precision_觀察": "精算觀察",
        "verified_research_complete": "研究驗證完成",
        "fast_daily_recomputed": "每日快速重算完成",
        "strict_reentry_gate_enforced": "連莊達標守門",
    }
    return mapping.get(str(value or ""), zh_text(value))


def candidate_reason_text(item, limit=6):
    source_text = zh_join(item.get("model_sources") or [], limit)
    if source_text != "-":
        return source_text
    return zh_join(item.get("reasons") or [], limit)


def candidate_route_text(item):
    text = candidate_reason_text(item, 8)
    parts = []
    if any(key in text for key in ["頻率", "十期", "五期", "二十期", "一百期", "三百期"]):
        parts.append("頻率版路")
    if any(key in text for key in ["拖牌", "共現", "對子"]):
        parts.append("拖牌共現")
    if "尾數" in text:
        parts.append("尾數版路")
    if "日期" in text:
        parts.append("日期版路")
    if any(key in text for key in ["遺漏", "補償"]):
        parts.append("遺漏補償")
    if any(key in text for key in ["全歷史", "綜合", "重算"]):
        parts.append("全歷史綜合")
    if not parts:
        parts.append("全歷史排序")
    return "、".join(dict.fromkeys(parts))


def candidate_guard_text(item):
    guard = item.get("previous_prediction_guard") or {}
    pieces = []
    if guard:
        if guard.get("reentry_required"):
            pieces.append("連莊達標通過" if guard.get("reentry_passed") else "連莊未達標剔除")
        else:
            pieces.append("非上期沿用")
        if guard.get("penalty"):
            pieces.append(f"降權 {guard.get('penalty')}")
    return "、".join(pieces) or "守門通過"


def build_mobile_number_verification_block(data):
    rows = []
    for item in (data.get("official_candidates") or data.get("candidates") or [])[:9]:
        cross = item.get("cross_validation") or {}
        maturity = item.get("practical_maturity") or {}
        rows.append(
            "<tr>"
            f"<th>{int(item.get('number')):02d}</th>"
            f"<td>{esc(candidate_route_text(item))}</td>"
            f"<td>{esc(candidate_reason_text(item, 8))}</td>"
            f"<td>{esc(cross.get('passed_count', '-'))}/{esc(cross.get('total_count', '-'))}</td>"
            f"<td>{u('\\u7a69\\u5b9a')} {esc(item.get('stability_count', '-'))} / {u('\\u907a\\u6f0f')} {esc(item.get('omission', '-'))}</td>"
            f"<td>{esc(candidate_guard_text(item))}</td>"
            f"<td>{u('\\u6210\\u719f\\u5ea6')} {esc(maturity.get('score', '-'))} / {esc(mobile_status(maturity.get('tier', '-')))}</td>"
            "</tr>"
        )
    return (
        f"<section class='band diagnosis'><h2>{u('\\u9010\\u865f\\u591a\\u91cd\\u9a57\\u7b97\\u660e\\u7d30')}</h2>"
        f"<p>{u('\\u6bcf\\u4e00\\u9846\\u865f\\u78bc\\u90fd\\u5217\\u51fa\\u7248\\u8def\\u3001\\u62d6\\u724c\\u6216\\u5171\\u73fe\\u6aa2\\u67e5\\u3001\\u4ea4\\u53c9\\u9a57\\u7b97\\u8207\\u5b88\\u9580\\u7d50\\u679c\\uff1b\\u6c92\\u6709\\u9a57\\u8b49\\u7684\\u865f\\u78bc\\u4e0d\\u5f97\\u9032\\u5165\\u524d\\u4e5d\\u3002')}</p>"
        f"<table><tr><th>{u('\\u865f\\u78bc')}</th><th>{u('\\u7248\\u8def')}</th><th>{u('\\u4f86\\u6e90\\u8b49\\u64da')}</th><th>{u('\\u4ea4\\u53c9')}</th><th>{u('\\u7a69\\u5b9a')}</th><th>{u('\\u5b88\\u9580')}</th><th>{u('\\u7d50\\u8ad6')}</th></tr>{''.join(rows)}</table></section>"
    )


def confidence_level(item):
    confidence = safe_float(item.get("confidence_index", item.get("score", 0)))
    if 0 < confidence <= 1:
        confidence *= 100
    probability = safe_float(item.get("model_probability_percent", 0))
    stability = safe_int(item.get("stability_count", 0))
    cross = item.get("cross_validation") or {}
    passed = safe_int(cross.get("passed_count", 0))
    total = safe_int(cross.get("total_count", 0))
    status = zh_text(cross.get("status", "-") or "-")
    maturity = item.get("practical_maturity") or {}
    maturity_score = safe_float(maturity.get("score", 0))
    maturity_tier = mobile_status(maturity.get("tier", "-") or "-")
    rank = safe_int(item.get("rank", 99), 99)
    top9_core = bool(item.get("top9_core", rank <= 9)) and rank <= 9
    top9_note = "前九核心" if top9_core else "前九外備查"
    if not top9_core or maturity_score < 58:
        level = u("\\u89c0\\u5bdf")
        css = "confidence-watch"
    elif confidence >= 88 and (probability >= 15 or stability >= 5) and passed >= 3 and maturity_score >= 70:
        level = u("\\u9ad8\\u4fe1\\u5fc3")
        css = "confidence-high"
    elif confidence >= 85 or probability >= 15 or stability >= 5 or maturity_score >= 70:
        level = u("\\u4e2d\\u9ad8\\u4fe1\\u5fc3")
        css = "confidence-mid"
    else:
        level = u("\\u89c0\\u5bdf")
        css = "confidence-watch"
    detail = (
        f"{u('\\u4fe1\\u5fc3\\u6307\\u6578')} {round(confidence, 2)} / "
        f"{u('\\u6a21\\u578b\\u6a5f\\u7387')} {round(probability, 2)}% / "
        f"{u('\\u7a69\\u5b9a\\u5171\\u8b58')} {stability} / "
        f"{u('\\u4ea4\\u53c9\\u9a57\\u8b49')} {passed}/{total} {status} / "
        f"{u('\\u6210\\u719f\\u5ea6')} {round(maturity_score, 1)} {maturity_tier} / {top9_note}"
    )
    return level, detail, css


def ultra_precision_candidate_score(item):
    confidence = safe_float(item.get("confidence_index", item.get("score", 0)))
    if 0 < confidence <= 1:
        confidence *= 100
    probability = safe_float(item.get("model_probability_percent", 0))
    stability = safe_int(item.get("stability_count", 0))
    cross = item.get("cross_validation") or {}
    passed = safe_int(cross.get("passed_count", 0))
    total = max(1, safe_int(cross.get("total_count", 0)))
    maturity = item.get("practical_maturity") or {}
    maturity_score = safe_float(maturity.get("score", 0))
    frontload = safe_float(item.get("top9_frontload_score", 0))
    base_score = safe_float(item.get("score", 0))
    score = 0.0
    score += max(0.0, min(1.0, (confidence - 50) / 49)) * 27
    score += min(probability / 18.5, 1.0) * 18
    score += min(stability / 5, 1.0) * 17
    score += (passed / total) * 19
    score += min(maturity_score / 82, 1.0) * 11
    score += min(frontload, 1.0) * 5
    score += min(base_score, 1.0) * 3
    guard = item.get("previous_prediction_guard") or {}
    repeat = item.get("repeat_guard") or {}
    if guard and not guard.get("passed"):
        score -= 7
    if repeat and not repeat.get("passed"):
        score -= 6
    tier = str(maturity.get("tier", ""))
    if tier == "blocked_low_maturity":
        score -= 12
    elif tier == "research_only":
        score -= 3
    if u("\\u0054\\u006f\\u0070\\u0039\\u524d\\u79fb\\u6821\\u6e96") in (item.get("reasons") or []):
        score += 1.5
    return round(max(0.0, score), 2)


def ultra_precision_recommendations(candidates, analysis=None):
    analysis = analysis or {}
    engine_precision = (
        analysis.get("precision_micro_models")
        or ((analysis.get("industrial_engine") or {}).get("precision_micro_models"))
        or ((analysis.get("primary_tiantianle_core") or {}).get("precision_micro_models"))
        or {}
    )
    if engine_precision.get("single") or engine_precision.get("two") or engine_precision.get("three"):
        return engine_precision
    pool = [item for item in candidates[:9] if item.get("top9_core", safe_int(item.get("rank"), 99) <= 9)]
    scored = sorted(
        [
            {"number": int(item.get("number")), "score": ultra_precision_candidate_score(item), "item": item}
            for item in pool
            if item.get("number") is not None
        ],
        key=lambda row: (row["score"], safe_float(row["item"].get("score", 0)), -row["number"]),
        reverse=True,
    )
    score_map = {row["number"]: row["score"] for row in scored}
    item_map = {row["number"]: row["item"] for row in scored}

    def zone(number):
        if number <= 10:
            return "01-10"
        if number <= 20:
            return "11-20"
        if number <= 30:
            return "21-30"
        return "31-39"

    def combo_score(numbers):
        values = [score_map[number] for number in numbers]
        if not values:
            return 0
        tails = [number % 10 for number in numbers]
        zones = [zone(number) for number in numbers]
        penalty = (len(tails) - len(set(tails))) * 2.6
        penalty += max(0, max((zones.count(label) for label in set(zones)), default=0) - 2) * 2.2
        stability = sum(min(safe_int(item_map[number].get("stability_count")), 5) for number in numbers) / len(numbers)
        cross_passed = sum(safe_int((item_map[number].get("cross_validation") or {}).get("passed_count")) for number in numbers) / len(numbers)
        return round((sum(values) / len(values)) * 0.72 + min(values) * 0.18 + stability + cross_passed * 0.75 - penalty, 2)

    def best_combo(size):
        if len(score_map) < size:
            return {"numbers": [], "score": 0}
        if size == 1:
            row = max(scored, key=lambda item: item["score"])
            return {"numbers": [row["number"]], "score": row["score"]}
        return max(
            ({"numbers": list(combo), "score": combo_score(combo)} for combo in combinations(score_map, size)),
            key=lambda row: (row["score"], sum(score_map[n] for n in row["numbers"])),
        )

    return {"single": best_combo(1), "two": best_combo(2), "three": best_combo(3), "ranked": scored}


def build_ultra_precision_block(candidates, analysis=None):
    rec = ultra_precision_recommendations(candidates, analysis)
    labels = [
        ("single", u("\\u7368\\u96bb1\\u4e2d1")),
        ("two", "2" + u("\\u4e2d") + "1~2"),
        ("three", "3" + u("\\u4e2d") + "1~3"),
    ]
    rows = []
    for key, label in labels:
        item = rec.get(key) or {}
        recent_60 = item.get("recent_60") or {}
        random_rate = item.get("random_success_probability")
        model_text = zh_text(item.get("selected_model_label") or item.get("selected_model") or u("\\u7d9c\\u5408\\u7cbe\\u7b97"))
        recent_text = (
            f"{u('\\u8fd160\\u671f')} {recent_60.get('pass_rate', '-')}"
            + (f" / {u('\\u96a8\\u6a5f')} {random_rate}" if random_rate is not None else "")
        )
        rows.append(
            "<tr>"
            f"<th>{esc(label)}</th>"
            f"<td>{esc(fmt_numbers(item.get('numbers') or []))}</td>"
            f"<td>{esc(item.get('score', 0))}</td>"
            f"<td>{esc(model_text)}</td>"
            f"<td>{esc(recent_text)}</td>"
            "</tr>"
        )
    return (
        f"<section class=\"band high-note\"><h2>{u('\\u8d85\\u5f37\\u4fe1\\u5fc3\\u9ad8\\u6a5f\\u7387\\u5f37\\u63a8\\u7cbe\\u7b97')}</h2>"
        f"<p>{u('\\u53ea\\u5728\\u524d\\u4e5d\\u6838\\u5fc3\\u5167\\u7cbe\\u7b97\\uff0c\\u4e26\\u7528\\u8fd1\\u0033\\u0030\\u002f\\u0036\\u0030\\u002f\\u0031\\u0032\\u0030\\u671f\\u5be6\\u6230\\u7af6\\u8cfd\\u9078\\u6a21\\u578b\\uff1b\\u7b2c\\u5341\\u81f3\\u5341\\u4e94\\u540d\\u4e0d\\u5217\\u9ad8\\u4fe1\\u5fc3\\u3002')}</p>"
        f"<table><tr><th>{u('\\u76ee\\u6a19')}</th><th>{u('\\u5f37\\u63a8\\u865f\\u78bc')}</th><th>{u('\\u7cbe\\u7b97\\u5206')}</th><th>{u('\\u63a1\\u7528\\u6a21\\u578b')}</th><th>{u('\\u5be6\\u6230\\u57fa\\u6e96')}</th></tr>{''.join(rows)}</table></section>"
    )


def build_confidence_rows(candidates):
    rows = []
    for idx, item in enumerate(candidates[:9], 1):
        level, detail, css = confidence_level(item)
        if level == u("\\u89c0\\u5bdf"):
            continue
        reasons = candidate_reason_text(item, 6)
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


def build_signal_focus(candidates):
    focus = []
    for item in candidates[:9]:
        level, detail, css = confidence_level(item)
        if level == u("\\u89c0\\u5bdf"):
            continue
        focus.append((item, level, detail, css))
        if len(focus) >= 5:
            break
    if not focus:
        return ""
    numbers = " ".join(f"{int(item.get('number')):02d}" for item, _, _, _ in focus)
    detail = " / ".join(f"{int(item.get('number')):02d}:{level}" for item, level, _, _ in focus)
    return (
        f"<section class=\"band signal-focus\"><h2>{u('\\u672c\\u671f\\u4e3b\\u4fe1\\u5fc3\\u724c')}</h2>"
        f"<div class=\"signal-numbers\">{esc(numbers)}</div>"
        f"<p class=\"signal-detail\">{esc(detail)}</p>"
        f"<p class=\"small\">{u('\\u9ad8\\u4fe1\\u5fc3\\u865f\\u78bc\\u5df2\\u4ee5\\u52a0\\u7c97\\u7d05\\u8272\\u5340\\u584a\\u5f37\\u8abf\\uff0c\\u6b63\\u5f0f\\u8207\\u975e\\u6b63\\u5f0f\\u72c0\\u614b\\u4ecd\\u4f9d\\u767c\\u5e03\\u95dc\\u5361\\u5224\\u5b9a\\u3002')}</p></section>"
    )


def build_mobile_avoid_rows(data, group_name):
    avoid = data.get("low_probability_avoid") or {}
    groups = avoid.get("groups") or {}
    rows = []
    for idx, item in enumerate((groups.get(group_name) or [])[:15], 1):
        rows.append(
            f"<tr><th>{idx}</th><td>{int(item.get('number')):02d}</td>"
            f"<td>{esc(item.get('avoid_confidence', '-'))}</td><td>{esc(item.get('confidence_label', '-'))}</td>"
            f"<td>{esc('、'.join(item.get('reasons', [])))}</td></tr>"
        )
    if not rows:
        rows.append(f"<tr><td colspan='5'>{u('\\u672c\\u671f\\u5df2\\u904b\\u7b97\\uff0c\\u6682\\u7121\\u984d\\u5916\\u907f\\u958b\\u865f')}</td></tr>")
    return "".join(rows)


def build_mobile_recalculation_block(data):
    manifest = data.get("recalculation_manifest") or {}
    basis = manifest.get("basis") or {}
    policy = data.get("strict_recommendation_policy") or {}
    prediction = data.get("prediction") or {}
    high = prediction.get("formal_high_confidence") or prediction.get("high_confidence_watch") or []
    return (
        f"<section class='band diagnosis'><h2>{u('\\u6bcf\\u671f\\u91cd\\u7b97\\u8b49\\u660e')}</h2>"
        f"<p><strong>{esc(manifest.get('status', '-'))}</strong>：{esc(manifest.get('visible_note', '-'))}</p>"
        f"<p>{u('\\u91cd\\u7b97\\u6307\\u7d0b')}：{esc(manifest.get('fingerprint', '-'))}</p>"
        f"<p>{u('\\u4f9d\\u64da\\u958b\\u734e')}：{esc(basis.get('latest_draw_date', ''))} {esc(fmt_numbers(basis.get('latest_numbers', [])))}</p>"
        f"<p>{u('\\u63a8\\u85a6\\u6a21\\u5f0f')}：{esc(policy.get('mode', prediction.get('recommendation_mode', '-')))} / {esc(policy.get('message', prediction.get('recommendation_message', '-')))}</p>"
        f"<p><strong>{u('\\u9ad8\\u4fe1\\u5fc3\\u865f\\u78bc')}：</strong>{esc(fmt_numbers(high))}</p></section>"
    )


def build_mobile_no_reuse_guard_block(data):
    industrial = data.get("industrial_engine") or {}
    guard = industrial.get("previous_prediction_guard") or {}
    if not guard:
        return ""
    top9 = (data.get("prediction") or {}).get("top9") or [item.get("number") for item in (data.get("candidates") or [])[:9]]
    rows = [
        (u("\\u672c\\u671f\\u524d\\u4e5d"), fmt_numbers(top9), u("\\u6bcf\\u671f\\u91cd\\u65b0\\u904b\\u7b97")),
        (u("\\u4e0a\\u671f\\u9810\\u6e2c"), fmt_numbers(guard.get("previous_top9") or []), esc(guard.get("actual_date") or guard.get("target_date") or "-")),
        (u("\\u524d\\u4e5d\\u91cd\\u758a"), fmt_numbers(guard.get("current_top9_overlap") or []), f"{len(guard.get('current_top9_overlap') or [])}/9"),
        (u("\\u9054\\u6a19\\u9023\\u838a"), fmt_numbers(guard.get("top9_reentry_passed") or guard.get("reentry_passed") or []), u("\\u901a\\u904e\\u624d\\u80fd\\u7559\\u5728\\u524d\\u4e5d")),
        (u("\\u672a\\u9054\\u6a19\\u5254\\u9664"), fmt_numbers((guard.get("reentry_rejected") or [])[:15]), u("\\u5df2\\u64cb\\u4e0b")),
        (u("\\u524d\\u4e5d\\u66ff\\u63db"), f"{u('\\u5254\\u9664')} {fmt_numbers(guard.get('demoted_from_raw_top9') or [])}", f"{u('\\u88dc\\u5165')} {fmt_numbers(guard.get('promoted_to_top9') or [])}"),
    ]
    body = "".join(f"<tr><th>{esc(label)}</th><td>{esc(numbers or '-')}</td><td>{esc(note or '-')}</td></tr>" for label, numbers, note in rows)
    return (
        f"<section class='band diagnosis'><h2>{u('\\u4e0a\\u671f\\u6cbf\\u7528\\u5b88\\u9580')}</h2>"
        f"<p>{u('\\u4e0a\\u671f\\u865f\\u78bc\\u4e0d\\u5f97\\u76f4\\u63a5\\u6cbf\\u7528\\uff1b\\u9023\\u838a\\u5fc5\\u9808\\u9054\\u6a19\\u3002')}</p>"
        f"<table><tr><th>{u('\\u9805\\u76ee')}</th><th>{u('\\u865f\\u78bc')}</th><th>{u('\\u5224\\u5b9a')}</th></tr>{body}</table></section>"
    )



def build_mobile_ironlaw_block(data):
    decision = data.get("latest_ironlaw") or data.get("decisive_battle_plan") or {}
    if not decision:
        return ""
    high_numbers = decision.get("high_confidence_core") or [item.get("number") for item in (decision.get("high_confidence_numbers") or []) if item.get("number") is not None]
    avoid_numbers = decision.get("defensive_avoid") or []
    avoid_packs = decision.get("avoid_packs") or ((data.get("low_probability_avoid") or {}).get("avoid_packs") or {})

    def action_row(label, numbers):
        return f"<tr><th>{esc(label)}</th><td>{esc(fmt_numbers(numbers) or '-')}</td></tr>"

    pack_rows = []
    for key, label in [("five_miss", "5不中"), ("ten_miss", "10不中"), ("fifteen_miss", "15不中")]:
        pack = avoid_packs.get(key) or {}
        pack_rows.append(
            f"<tr><td>{esc(label)}</td><td>{esc(fmt_numbers(pack.get('numbers') or []))}</td><td>{esc(pack.get('confidence_label', '-'))}</td><td>{esc(pack.get('confidence_index', '-'))}</td></tr>"
        )
    time_rows = []
    for item in decision.get("time_table", []) or []:
        time_rows.append(f"<tr><td>{esc(item.get('item', '-'))}</td><td>{esc(item.get('content', '-'))}</td></tr>")
    if not time_rows:
        time_rows = [
            f"<tr><td>{u('\\u958b\\u734e\\u5f8c\\u66f4\\u65b0')}</td><td>{u('\\u590f\\u4ee4\\u53f0\\u7063\\u6642\\u9593\\u4e0a\\u534810:00\\u524d\\u5b8c\\u6210\\u540c\\u6b65\\u3002')}</td></tr>",
            f"<tr><td>{u('\\u5348\\u9593\\u91cd\\u7b97')}</td><td>{u('\\u6bcf\\u65e5\\u4e0b\\u534813:00\\u5b8c\\u6210\\u56de\\u6e2c\\u8207\\u91cd\\u5efa\\u624b\\u6a5f\\u7248\\u3002')}</td></tr>",
        ]
    return (
        f"<section class='band signal-focus'><h2>{u('\\u672c\\u671f\\u660e\\u78ba\\u4f5c\\u6230\\u7b54\\u6848')}</h2>"
        f"<p><strong>{esc(decision.get('conclusion', decision.get('action_label', '-')))}</strong></p>"
        f"<table>"
        f"{action_row(u('\\u660e\\u78ba\\u7368\\u96bb'), decision.get('primary_single') or [])}"
        f"{action_row(u('\\u660e\\u78ba') + '2' + u('\\u4e2d') + '1', decision.get('two_hit_one') or [])}"
        f"{action_row(u('\\u660e\\u78ba') + '3' + u('\\u4e2d') + '1~3', decision.get('three_hit_one') or [])}"
        f"{action_row(u('\\u660e\\u78ba') + '5' + u('\\u4e2d') + '2', decision.get('five_hit_two') or [])}"
        f"{action_row(u('\\u660e\\u78ba') + '9' + u('\\u4e2d') + '3', decision.get('nine_hit_three') or [])}"
        f"{action_row(u('\\u9ad8\\u6a5f\\u7387\\u4fe1\\u5fc3\\u724c'), high_numbers[:9])}"
        f"{action_row(u('\\u9632\\u5b88\\u907f\\u958b'), avoid_numbers[:10])}"
        f"</table>"
        f"<h3>{u('\\u4f4e\\u6a5f\\u7387\\u907f\\u96aa\\u5305')}</h3><table><tr><th>{u('\\u985e\\u5225')}</th><th>{u('\\u865f\\u78bc')}</th><th>{u('\\u4fe1\\u5fc3')}</th><th>{u('\\u6307\\u6a19')}</th></tr>{''.join(pack_rows)}</table>"
        f"<h3>{u('\\u6bcf\\u65e5\\u66f4\\u65b0\\u9435\\u5f8b\\u6642\\u9593\\u8868')}</h3><table><tr><th>{u('\\u9805\\u76ee')}</th><th>{u('\\u5167\\u5bb9')}</th></tr>{''.join(time_rows)}</table>"
        f"</section>"
    )
def build_mobile_avoid_block(data):
    avoid = data.get("low_probability_avoid") or {}
    backtest = avoid.get("backtest") or {}
    header = f"<tr><th>#</th><th>{u('\\u865f\\u78bc')}</th><th>{u('\\u907f\\u958b\\u4fe1\\u5fc3')}</th><th>{u('\\u7b49\\u7d1a')}</th><th>{u('\\u7406\\u7531')}</th></tr>"
    return (
        f"<section class='band danger-zone'><h2>{u('\\u4f4e\\u6a5f\\u7387\\u4e0d\\u4e2d\\u5206\\u6790')}</h2>"
        f"<p>{esc(avoid.get('warning', u('\\u4f4e\\u6a5f\\u7387\\u662f\\u98a8\\u63a7\\u907f\\u958b\\uff0c\\u4e0d\\u662f\\u7d55\\u5c0d\\u4fdd\\u8b49\\u3002')))}</p>"
        f"<p>{u('\\u56de\\u6e2c')}：{u('\\u6a23\\u672c')} {esc(backtest.get('rounds', '-'))} / {u('\\u96f6\\u8aa4\\u5165\\u7387')} {esc(backtest.get('zero_hit_rate', '-'))}</p>"
        f"<h3>{u('\\u4e94\\u4e0d\\u4e2d')}</h3><table>{header}{build_mobile_avoid_rows(data, '五不中')}</table>"
        f"<h3>{u('\\u5341\\u4e0d\\u4e2d')}</h3><table>{header}{build_mobile_avoid_rows(data, '十不中')}</table>"
        f"<h3>{u('\\u5341\\u4e94\\u4e0d\\u4e2d')}</h3><table>{header}{build_mobile_avoid_rows(data, '十五不中')}</table></section>"
    )
def build_home_page():
    repo, workflow_url, page_url = cloud_links()
    data = {}
    analysis_path = REPORT_DIR / "latest_analysis.json"
    if analysis_path.exists():
        data = json.loads(analysis_path.read_text(encoding="utf-8"))
    freshness = data.get("freshness") or {}
    latest = data.get("latest_draw") or {}
    industrial = data.get("industrial_engine") or {}
    maturity = industrial.get("practical_maturity") or {}
    release = industrial.get("release_gate") or {}
    packs = data.get("strong_packs") or {}
    candidates = data.get("candidates") or []
    top9 = fmt_numbers([item.get("number") for item in candidates[:9]])
    confidence_rows = build_confidence_rows(candidates)
    signal_focus = build_signal_focus(candidates)
    ultra_precision_block = build_ultra_precision_block(candidates, data)
    ultra = ultra_precision_recommendations(candidates, data)
    gap_diagnosis = industrial.get("prediction_gap_diagnosis") or {}
    gap_rows = []
    for item in (gap_diagnosis.get("missing_elements") or [])[:6]:
        gap_rows.append(
            f"<tr><th>{esc(item.get('category', '-'))}</th><td>{esc(item.get('evidence', '-'))}</td>"
            f"<td>{esc(item.get('fix', '-'))}</td></tr>"
        )
    if not gap_rows:
        gap_rows.append(
            f"<tr><th>{u('\\u76ee\\u524d\\u8a3a\\u65b7')}</th><td>{u('\\u672a\\u898b\\u91cd\\u5927\\u7d50\\u69cb\\u7f3a\\u53e3')}</td>"
            f"<td>{u('\\u7e7c\\u7e8c\\u6bcf\\u671f\\u6efe\\u52d5\\u91cd\\u7b97')}</td></tr>"
        )
    gap_action_text = u("\\u3001").join((gap_diagnosis.get("active_action_labels") or gap_diagnosis.get("active_actions") or [])[:6]) or "-"
    pack_rows = []

    def add_pack_row(label, numbers, goal, maturity_text):
        pack_rows.append(
            f"<tr><th>{esc(label)}</th><td>{esc(fmt_numbers(numbers or []))}</td>"
            f"<td>{esc(goal)}</td><td>{esc(maturity_text)}</td></tr>"
        )

    for ultra_key, label, goal in [
        ("single", u("\\u8d85\\u5f37\\u7cbe\\u7b97\\u7368\\u96bb1\\u4e2d1"), "1"),
        ("two", u("\\u8d85\\u5f37\\u7cbe\\u7b972\\u4e2d1~2"), "1~2"),
        ("three", u("\\u8d85\\u5f37\\u7cbe\\u7b973\\u4e2d1~3"), "1~3"),
    ]:
        item = ultra.get(ultra_key) or {}
        add_pack_row(label, item.get("numbers") or [], goal, f"{u('\\u4e8c\\u6b21\\u7cbe\\u7b97')} {item.get('score', 0)} / {mobile_status(item.get('status', 'watch_only'))}")

    for key, label in [
        ("five_hit_two", "5" + u("\\u4e2d") + "2~3"),
        ("nine_hit_three", "9" + u("\\u4e2d") + "3~5"),
    ]:
        pack = packs.get(key) or {}
        pack_maturity = pack.get("maturity") or {}
        maturity_value = pack_maturity.get("avg_score", pack_maturity.get("avg", "-"))
        maturity_status = pack_maturity.get("status")
        if maturity_status is None and "passed" in pack_maturity:
            maturity_status = "passed" if pack_maturity.get("passed") else "watch_only"
        maturity_text = f"{maturity_value} / {mobile_status(maturity_status or '-')}"
        add_pack_row(label, pack.get("numbers") or [], pack.get("hit_goal"), maturity_text)
    page_title = u("\\u5929\\u5929\\u6a02 \\u624b\\u6a5f\\u96f2\\u7aef\\u9996\\u9801")
    subtitle = (
        f"{u('\\u5831\\u8868\\u7522\\u751f')} {esc(display_time(data.get('generated_at_taiwan')))} / "
        f"{u('\\u6700\\u65b0\\u958b\\u734e')} {esc(latest.get('draw_date'))} / "
        f"{u('\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593\\uff08\\u53f0\\u7063\\uff09')} {esc(freshness.get('target_taiwan_safe_update_time'))}"
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>{esc(page_title)}</title>
<style>
body{{margin:0;font-family:"Microsoft JhengHei",Arial,sans-serif;background:#f6f7fb;color:#111827}}
header{{background:#0f172a;color:white;padding:22px 28px}}header h1{{margin:0 0 8px;font-size:28px}}header p{{margin:0;color:#cbd5e1}}
main{{max-width:980px;margin:auto;padding:18px}}.band{{background:white;border:1px solid #e5e7eb;border-radius:8px;margin-top:14px;padding:16px;overflow-x:auto}}
 .tabs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:14px}}.tabs a{{display:block;text-align:center;padding:14px;border-radius:8px;background:#e5e7eb;color:#111827;font-weight:900;text-decoration:none}}.tabs a.active{{background:#166534;color:white}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}.card{{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:16px}}.card h2{{margin:0 0 8px;font-size:15px;color:#475569}}.value{{font-size:22px;font-weight:900}}
table{{width:100%;min-width:640px;border-collapse:collapse}}th,td{{border-bottom:1px solid #e5e7eb;padding:10px;text-align:left}}th{{background:#f1f5f9}}
  .high-note{{border:3px solid #dc2626;background:#fff1f2;box-shadow:0 0 0 4px #fee2e2 inset}}.high-note h2{{color:#991b1b}}.small{{font-size:13px;color:#475569}}
  .diagnosis{{border:3px solid #1d4ed8;background:#eff6ff}}.diagnosis h2{{color:#1e3a8a}}.danger-zone{{border:3px solid #991b1b;background:#fff1f2}}.danger-zone h2{{color:#7f1d1d}}
  .signal-focus{{border:4px solid #b91c1c;background:#fff1f2;box-shadow:0 0 0 5px #fee2e2 inset}}.signal-focus h2{{color:#991b1b}}.signal-numbers{{font-size:34px;line-height:1.25;font-weight:900;color:#991b1b;letter-spacing:0}}.signal-detail{{font-weight:900;color:#7f1d1d}}
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
<a class="active" href="首頁.html">{u('\\u9996\\u9801')}</a>
<a href="下期預測.html">{u('\\u4e0b\\u671f\\u9810\\u6e2c')}</a>
<a href="上期未命中檢討.html">{u('\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e')}</a>
<a href="每月總整理.html">{u('\\u6bcf\\u6708\\u7e3d\\u6574\\u7406')}</a>
</nav>
<section class="band"><a class="primary" href="下期預測.html">{u('\\u67e5\\u770b\\u4e0b\\u671f\\u9810\\u6e2c')}</a></section>
<section class="band"><a class="primary danger" href="上期未命中檢討.html">{u('\\u67e5\\u770b\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e')}</a></section>
<section class="band"><a class="primary secondary" href="每月總整理.html">{u('\\u67e5\\u770b\\u6bcf\\u6708\\u7e3d\\u6574\\u7406')}</a></section>
<section class="band"><a class="primary secondary" href="reports/complete_report.html">{u('\\u67e5\\u770b\\u5b8c\\u6574\\u6230\\u5831')}</a></section>
<section class="band"><a class="primary secondary" href="{esc(workflow_url)}">{u('\\u7acb\\u5373\\u96f2\\u7aef\\u66f4\\u65b0')}</a><p class="url">{u('\\u624b\\u6a5f\\u96f2\\u7aef\\u7db2\\u5740\\u5df2\\u8a2d\\u5b9a')}</p></section>
{build_mobile_recalculation_block(data)}
{build_mobile_no_reuse_guard_block(data)}
{build_mobile_ironlaw_block(data)}
{build_mobile_number_verification_block(data)}
{signal_focus}
{ultra_precision_block}
{build_mobile_avoid_block(data)}
<section class="band diagnosis"><h2>{u('\\u5168\\u7cfb\\u7d71\\u547d\\u4e2d\\u7387\\u7f3a\\u53e3\\u8a3a\\u65b7')}</h2><p><strong>{u('\\u65b0\\u589e\\u6a21\\u578b')}:</strong> {esc(gap_diagnosis.get('new_model_added', '-'))} / <strong>{u('\\u72c0\\u614b')}:</strong> {esc(gap_diagnosis.get('status_label', gap_diagnosis.get('status', '-')))}</p><p class="small">{esc(gap_diagnosis.get('message', '-'))}</p><p class="small"><strong>{u('\\u5df2\\u555f\\u7528\\u52d5\\u4f5c')}:</strong> {esc(gap_action_text)}</p><table><tr><th>{u('\\u7f3a\\u53e3')}</th><th>{u('\\u8b49\\u64da')}</th><th>{u('\\u5df2\\u88dc\\u5f37')}</th></tr>{''.join(gap_rows)}</table></section>
<section class="band high-note"><h2>{u('\\u9ad8\\u6a5f\\u7387\\uff0f\\u9ad8\\u4fe1\\u5fc3\\u9810\\u6e2c\\u52a0\\u8a3b')}</h2><p>{u('\\u6a5f\\u7387\\u9ad8\\u6216\\u4fe1\\u5fc3\\u9ad8\\u7684\\u865f\\u78bc\\u5df2\\u9650\\u5236\\u5728\\u524d\\u4e5d\\u6838\\u5fc3\\u5167\\u986f\\u793a\\uff0c\\u7b2c\\u5341\\u81f3\\u5341\\u4e94\\u540d\\u53ea\\u5217\\u5099\\u67e5\\u3002')}</p><table><tr><th>{u('\\u6392\\u540d')}</th><th>{u('\\u865f\\u78bc')}</th><th>{u('\\u9ad8\\u4fe1\\u5fc3\\u8aaa\\u660e')}</th><th>{u('\\u4f86\\u6e90\\u7406\\u7531')}</th></tr>{confidence_rows}</table></section>
<div class="grid">
<section class="card"><h2>{u('\\u6700\\u65b0\\u958b\\u734e\\u65e5')}</h2><div class="value">{esc(latest.get('draw_date'))}</div></section>
<section class="card"><h2>{u('\\u53f0\\u7063\\u53ef\\u66f4\\u65b0\\u6642\\u9593')}</h2><div class="value">{esc(freshness.get('latest_taiwan_safe_update_time'))}</div></section>
<section class="card"><h2>{u('\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593')}</h2><div class="value">{esc(freshness.get('target_taiwan_safe_update_time'))}</div></section>
<section class="card"><h2>{u('\\u5168\\u6b77\\u53f2\\u7b46\\u6578')}</h2><div class="value">{esc(data.get('draw_count'))}</div></section>
<section class="card"><h2>{u('\\u767c\\u5e03\\u72c0\\u614b')}</h2><div class="value">{esc(mobile_status(release.get('status', '-')))}</div><p class="small">{u('\\u6b63\\u5f0f\\u767c\\u5e03') if data.get('official_release_allowed') else u('\\u975e\\u6b63\\u5f0f\\u4fdd\\u8b49')}</p></section>
<section class="card"><h2>{u('\\u5be6\\u6230\\u6210\\u719f\\u5ea6')}</h2><div class="value">{esc(maturity.get('top10_avg_maturity', '-'))}</div><p class="small">{esc(mobile_status(maturity.get('status', '-')))}</p></section>
</div>
<section class="band"><h2>{u('\\u672c\\u671f\\u6838\\u5fc3\\u9810\\u6e2c\\u6458\\u8981')}</h2><p><strong>{u('\\u524d\\u4e5d\\u6838\\u5fc3')}:</strong> {esc(top9)}</p><table><tr><th>{u('\\u6a21\\u578b')}</th><th>{u('\\u865f\\u78bc')}</th><th>{u('\\u76ee\\u6a19')}</th><th>{u('\\u6210\\u719f\\u5ea6')}</th></tr>{''.join(pack_rows)}</table></section>
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
    not_found = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="0; url=reports/complete_report.html?v={version}">
<title>{u('\\u5929\\u5929\\u6a02\\u5b8c\\u6574\\u6230\\u5831')}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft JhengHei",sans-serif;margin:0;padding:28px;background:#f6f7fb;color:#111827}}a{{display:block;margin-top:16px;padding:14px;background:#166534;color:white;text-align:center;border-radius:8px;text-decoration:none;font-weight:900}}</style></head>
<body><h1>{u('\\u6b63\\u5728\\u958b\\u555f\\u5b8c\\u6574\\u6230\\u5831')}</h1><p>{u('\\u82e5\\u9801\\u9762\\u672a\\u81ea\\u52d5\\u8df3\\u8f49\\uff0c\\u8acb\\u9ede\\u4e0b\\u65b9\\u6309\\u9215\\u3002')}</p><a href="reports/complete_report.html?v={version}">{u('\\u958b\\u555f\\u5b8c\\u6574\\u6230\\u5831')}</a>
<script>location.replace('reports/complete_report.html?v={version}');</script></body></html>"""
    (SITE_DIR / "404.html").write_text(not_found, encoding="utf-8")
    offline = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{u('\\u5929\\u5929\\u6a02\\u96e2\\u7dda\\u63d0\\u793a')}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:28px;background:#f6f7fb;color:#111827}}.box{{max-width:680px;margin:auto;background:white;border:1px solid #d8dee9;border-radius:8px;padding:18px}}</style></head>
<body><div class="box"><h1>{u('\\u5929\\u5929\\u6a02')}</h1><p>{u('\\u76ee\\u524d\\u96e2\\u7dda\\uff0c\\u5df2\\u986f\\u793a\\u6700\\u8fd1\\u5feb\\u53d6\\u5167\\u5bb9\\u3002\\u8981\\u66f4\\u65b0\\u6700\\u65b0\\u9810\\u6e2c\\uff0c\\u8acb\\u9023\\u7dda\\u5f8c\\u518d\\u958b\\u555f\\u3002')}</p></div></body></html>"""
    (SITE_DIR / "offline.html").write_text(offline, encoding="utf-8")
    (SITE_DIR / "離線頁.html").write_text(offline, encoding="utf-8")
    reset = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"><meta http-equiv="Pragma" content="no-cache"><meta http-equiv="Expires" content="0">
<title>{u('\\u5929\\u5929\\u6a02\\u624b\\u6a5f\\u66f4\\u65b0')}</title>
<style>body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft JhengHei",sans-serif;background:#f6f7fb;color:#111827}}main{{max-width:680px;margin:auto;padding:28px}}.box{{background:#fff;border:1px solid #d8dee9;border-radius:8px;padding:18px}}.status{{font-weight:900;color:#166534}}a{{display:block;margin-top:14px;padding:14px;background:#166534;color:#fff;text-align:center;border-radius:8px;text-decoration:none;font-weight:900}}</style></head>
<body><main><div class="box"><h1>{u('\\u5929\\u5929\\u6a02')}</h1><p class="status" id="status">{u('\\u6b63\\u5728\\u6e05\\u9664\\u624b\\u6a5f\\u820a\\u5feb\\u53d6\\u4e26\\u91cd\\u8b80\\u96f2\\u7aef\\u6700\\u65b0\\u7248')}</p><a href="首頁.html?v={version}&manual=1">{u('\\u7acb\\u5373\\u9032\\u5165\\u6700\\u65b0\\u7248')}</a></div></main>
<script>
(async function(){{
  var status = document.getElementById('status');
  try {{
    if ('serviceWorker' in navigator) {{
      var regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map(function(reg) {{ return reg.unregister(); }}));
    }}
    if ('caches' in window) {{
      var keys = await caches.keys();
      await Promise.all(keys.map(function(key) {{ return caches.delete(key); }}));
    }}
    status.textContent = '{u('\\u5df2\\u6e05\\u9664\\u820a\\u5feb\\u53d6\\uff0c\\u6b63\\u5728\\u8f09\\u5165\\u6700\\u65b0\\u7248')}';
  }} catch (err) {{
    status.textContent = '{u('\\u5df2\\u91cd\\u65b0\\u8b80\\u53d6\\u96f2\\u7aef\\uff0c\\u6b63\\u5728\\u9032\\u5165\\u6700\\u65b0\\u7248')}';
  }}
  location.replace('首頁.html?v={version}&reset=' + Date.now());
}})();
</script></body></html>"""
    (SITE_DIR / "reset.html").write_text(reset, encoding="utf-8")
    (SITE_DIR / "清除快取.html").write_text(reset, encoding="utf-8")
    sw = f"""const CACHE_NAME = 'tiantianle-ironlaw-{version}';
const APP_SHELL = ['index.html','首頁.html','prediction.html','下期預測.html','review.html','上期未命中檢討.html','monthly_summary.html','每月總整理.html','六月總整理.html','prediction-history.html','預測歷史對比.html','complete_report.html','完整_report.html','完整戰報.html','天天樂完整戰報.html','reports/complete_report.html','reports/monthly_summary.html','reports/每月總整理.html','reports/六月總整理.html','reports/完整_report.html','reports/完整戰報.html','reports/天天樂完整戰報.html','reports/latest_battle_report.html','latest_analysis.json','最新分析資料.json','version.json','版本.json','system_health_report.md','系統健康報告.md','manifest.webmanifest','offline.html','離線頁.html','reset.html','清除快取.html','404.html','icon-192.png','icon-512.png'];
async function deleteAllCaches() {{
  const keys = await caches.keys();
  await Promise.all(keys.map(key => caches.delete(key)));
}}
async function deleteOldCaches() {{
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)));
}}
self.addEventListener('install', event => {{
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL.map(url => url + '?v={version}')).catch(() => cache.addAll(APP_SHELL))));
  self.skipWaiting();
}});
self.addEventListener('activate', event => {{
  event.waitUntil(deleteOldCaches().then(() => caches.open(CACHE_NAME)));
  self.clients.claim();
}});
self.addEventListener('message', event => {{
  if (!event.data) return;
  if (event.data.type === 'SKIP_WAITING') self.skipWaiting();
  if (event.data.type === 'CLEAR_CACHE') event.waitUntil(deleteAllCaches());
}});
self.addEventListener('fetch', event => {{
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  const path = decodeURIComponent(url.pathname);
  const isReportShortcut = path.includes('complete_report') || path.includes('完整_report') || path.includes('完整戰報') || path.includes('latest_battle_report') || path.endsWith('/reports/');
  const stableReportUrl = new URL('reports/complete_report.html?v={version}', self.registration.scope).toString();
  const isFreshFile = url.pathname.endsWith('.html') || url.pathname.endsWith('.json') || url.pathname.endsWith('.md') || url.pathname.endsWith('service-worker.js') || url.pathname.endsWith('manifest.webmanifest') || url.pathname.endsWith('/');
  if (isFreshFile) {{
    url.searchParams.set('v', '{version}');
    event.respondWith(fetch(url.toString(), {{ cache: 'no-store', headers: {{ 'Cache-Control': 'no-cache' }} }}).then(response => {{
      if (!response.ok && isReportShortcut) return fetch(stableReportUrl, {{ cache: 'no-store', headers: {{ 'Cache-Control': 'no-cache' }} }});
      return response;
    }}).catch(() => {{
      if (isReportShortcut) return fetch(stableReportUrl, {{ cache: 'no-store', headers: {{ 'Cache-Control': 'no-cache' }} }}).catch(() => caches.match('reports/complete_report.html').then(hit => hit || caches.match('complete_report.html') || caches.match('offline.html')));
      return caches.match(event.request).then(hit => hit || caches.match('offline.html'));
    }}));
    return;
  }}
  event.respondWith(fetch(event.request, {{ cache: 'no-store' }}).then(response => {{
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
<header><h1>天天樂手機雲端獨立版</h1><p>使用雲端頁面與雲端自動更新，電腦關機也能從手機開啟。</p></header>
<main>
    """ + local_note + """
<section class="band">
<button id="installBtn" class="btn">一鍵啟動天天樂雲端版</button>
<a class="btn blue" href="__WORKFLOW_URL__">登入雲端帳號後立即雲端更新</a>
</section>
<section class="band"><h2>真正手機網址</h2><p class="url">雲端網址已設定</p><p>手機安裝必須使用雲端網址，不是電腦本機路徑。</p></section>
<section class="band">
<h2>安卓手機瀏覽器</h2>
<ol><li>手機開雲端網址。</li><li>點上方一鍵啟動天天樂雲端版。</li><li>瀏覽器若跳出安裝提示，選擇安裝手機版。</li><li>安裝後從手機主畫面開啟天天樂。</li></ol>
<h2>蘋果手機瀏覽器</h2>
<ol><li>點瀏覽器分享按鈕。</li><li>選擇「加入主畫面」。</li><li>完成後從主畫面開啟天天樂。</li></ol>
</section>
<section class="band"><p>這是雲端版入口：更新由雲端自動執行，畫面由雲端頁面提供。手機不需要連回電腦。</p></section>
</main>
<button id="stickyBtn" class="btn sticky-launch">一鍵啟動天天樂雲端版</button>
<script>
let deferredPrompt=null;
window.addEventListener('beforeinstallprompt', function(e){e.preventDefault();deferredPrompt=e;});
async function launchTiantianle(){
  if(deferredPrompt){deferredPrompt.prompt();await deferredPrompt.userChoice;deferredPrompt=null;return;}
  location.href='首頁.html';
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
    index_html = finalize_user_html(inject_mobile_panel(build_home_page()))
    (SITE_DIR / "index.html").write_text(index_html, encoding="utf-8")
    (SITE_DIR / "首頁.html").write_text(index_html, encoding="utf-8")
    if prediction.exists():
        prediction_html = finalize_user_html(inject_mobile_panel(prediction.read_text(encoding="utf-8", errors="replace")))
        (SITE_DIR / "prediction.html").write_text(prediction_html, encoding="utf-8")
        (SITE_DIR / "下期預測.html").write_text(prediction_html, encoding="utf-8")
    if review.exists():
        review_html = finalize_user_html(inject_mobile_panel(review.read_text(encoding="utf-8", errors="replace")))
        (SITE_DIR / "review.html").write_text(review_html, encoding="utf-8")
        (SITE_DIR / "上期未命中檢討.html").write_text(review_html, encoding="utf-8")
    if history.exists():
        history_html = finalize_user_html(history.read_text(encoding="utf-8", errors="replace"))
        (SITE_DIR / "prediction-history.html").write_text(history_html, encoding="utf-8")
        (SITE_DIR / "預測歷史對比.html").write_text(history_html, encoding="utf-8")
    copy_text(REPORT_DIR / "latest_analysis.json", SITE_DIR / "latest_analysis.json")
    write_alias(SITE_DIR / "latest_analysis.json", "最新分析資料.json")
    copy_text(REPORT_DIR / "system_health_report.md", SITE_DIR / "system_health_report.md")
    write_alias(SITE_DIR / "system_health_report.md", "系統健康報告.md")
    write_version_file()
    copy_public_tree(REPORT_DIR, SITE_DIR / "reports")
    for source, aliases in {
        SITE_DIR / "reports" / "latest_battle_report.html": [
            "天天樂完整戰報.html",
            "天天樂最新戰報.html",
            "最新完整戰報.html",
            "完整戰報.html",
            "完整_report.html",
            "complete_report.html",
            "tiantianle_complete_report.html",
        ],
        SITE_DIR / "reports" / "prediction.html": ["下期預測.html", "天天樂下期預測.html"],
        SITE_DIR / "reports" / "review.html": ["上期未命中檢討.html", "天天樂上期未命中檢討.html"],
        SITE_DIR / "reports" / "monthly_summary.html": ["monthly_summary.html", "每月總整理.html", "六月總整理.html", "天天樂每月總整理.html"],
        SITE_DIR / "reports" / "latest_battle_report.md": ["最新戰報.md", "天天樂最新戰報.md"],
        SITE_DIR / "reports" / "tiantianle_prediction_history.html": ["預測歷史對比.html", "天天樂預測歷史對比.html"],
    }.items():
        for alias in aliases:
            write_alias(source, alias)
    root_report_source = SITE_DIR / "reports" / "latest_battle_report.html"
    for alias in [
        "complete_report.html",
        "tiantianle_complete_report.html",
        "latest_battle_report.html",
        "完整_report.html",
        "完整戰報.html",
        "天天樂完整戰報.html",
        "最新完整戰報.html",
    ]:
        copy_text(root_report_source, SITE_DIR / alias)
    root_monthly_source = SITE_DIR / "reports" / "monthly_summary.html"
    for alias in [
        "monthly_summary.html",
        "每月總整理.html",
        "六月總整理.html",
        "天天樂每月總整理.html",
    ]:
        copy_text(root_monthly_source, SITE_DIR / alias)
    version = build_version()
    manifest = {
        "name": u("\\u5929\\u5929\\u6a02\\u624b\\u6a5f\\u7368\\u7acb\\u7248"),
        "short_name": u("\\u5929\\u5929\\u6a02"),
        "id": "./",
        "start_url": f"首頁.html?v={version}&pwa=1",
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
    write_alias(SITE_DIR / "install.html", "安裝手機版.html")
    print(SITE_DIR / "index.html")


if __name__ == "__main__":
    main()


