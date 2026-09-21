import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
DATA = ROOT / "data"
DB_PATH = DATA / "california_fantasy5.sqlite"
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


def read_json(path, default=None):
    if default is None:
        default = {}
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"_read_error": str(exc)}


def text_numbers(values):
    return " ".join(f"{int(value):02d}" for value in values or [])


def db_summary():
    if not DB_PATH.exists():
        return {"ok": False, "reason": "資料庫不存在", "count": 0, "latest": ""}
    try:
        with sqlite3.connect(DB_PATH) as conn:
            count, latest = conn.execute("SELECT COUNT(*), MAX(draw_date) FROM draws").fetchone()
            pred_count, pred_latest, pred_target = conn.execute(
                "SELECT COUNT(*), MAX(based_on_date), MAX(target_date) FROM predictions"
            ).fetchone()
            low_count, low_latest = conn.execute(
                "SELECT COUNT(*), MAX(based_on_date) FROM low_probability_records"
            ).fetchone()
        return {
            "ok": bool(count and count >= 10000 and latest),
            "count": count or 0,
            "latest": latest or "",
            "prediction_count": pred_count or 0,
            "prediction_latest": pred_latest or "",
            "prediction_target": pred_target or "",
            "low_probability_count": low_count or 0,
            "low_probability_latest": low_latest or "",
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "count": 0, "latest": ""}


def main():
    REPORTS.mkdir(exist_ok=True)
    SITE.mkdir(exist_ok=True)

    analysis = read_json(REPORTS / "latest_analysis.json")
    site_analysis = read_json(SITE / "latest_analysis.json")
    sync = read_json(REPORTS / "mobile_sync_status.json")
    cloud = read_json(REPORTS / "cloud_publish_status.json")
    after_draw = read_json(REPORTS / "after_draw_auto_update_status.json")
    watchdog = read_json(REPORTS / "auto_update_watchdog_status.json")
    database = db_summary()

    latest = (analysis.get("latest_draw") or {}).get("draw_date") or (analysis.get("freshness") or {}).get("latest_draw_date")
    latest_numbers = (analysis.get("latest_draw") or {}).get("numbers") or []
    target = analysis.get("target_draw_date") or (analysis.get("freshness") or {}).get("target_draw_date")
    top9 = (analysis.get("prediction") or {}).get("top9") or []
    freshness = analysis.get("freshness") or {}
    latest_tw = freshness.get("latest_taiwan_safe_update_time") or analysis.get("latest_draw_taiwan_update_time")
    target_tw = freshness.get("target_taiwan_safe_update_time") or analysis.get("prediction_draw_taiwan_time")

    site_latest = (site_analysis.get("latest_draw") or {}).get("draw_date") or (site_analysis.get("freshness") or {}).get("latest_draw_date")
    site_target = site_analysis.get("target_draw_date") or (site_analysis.get("freshness") or {}).get("target_draw_date")

    checks = []

    def add(name, ok, action, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "action": action})

    add("本機最新資料", bool(latest and latest == database.get("latest")), "重跑全歷史重算並重建戰報", f"戰報 {latest or '-'} / 資料庫 {database.get('latest') or '-'}")
    add("手機同步資料", bool(latest and site_latest == latest and site_target == target), "重建手機檔並重新發布雲端", f"手機最新 {site_latest or '-'} / 手機下期 {site_target or '-'}")
    add("全歷史資料庫", bool(database.get("ok")), "重新匯入全歷史 CSV 與快取頁面", f"{database.get('count', 0)} 筆")
    add("下期預測產生", bool(target and len(top9) == 9 and len(set(top9)) == 9), "重新運算候選排序與九碼主推", text_numbers(top9))
    add("低機率紀錄", bool(database.get("low_probability_count", 0) > 0 and database.get("low_probability_latest") == latest), "重建低機率每日紀錄與每月檢討", f"低機率最新 {database.get('low_probability_latest') or '-'}")
    add("手機同步檢測", sync.get("status") in {"同步", "synced", "ok"} or not sync.get("mismatches"), "執行手機同步驗證與本機重建", sync.get("status") or "未記錄")
    local_sync_ok = bool(latest and site_latest == latest and site_target == target)
    add("雲端發布狀態", cloud.get("status") in {"cloud_published", "ok", "published"} or (cloud == {} and local_sync_ok), "下一輪守護重試雲端發布", cloud.get("status") or "未記錄")
    add("開獎後自救", after_draw.get("complete") is not False or local_sync_ok, "開獎後腳本會重試並交由守護程式續修", str(after_draw.get("complete", "未記錄")))
    add("守護程式狀態", not watchdog.get("_read_error"), "守護程式下輪重新讀取並修復", watchdog.get("checked_at_taiwan") or "未記錄")

    passed = sum(1 for item in checks if item["ok"])
    score = round(passed / len(checks) * 100, 1) if checks else 0
    status = "穩定" if score >= 95 else ("需觀察" if score >= 80 else "需立即修復")
    failed = [item for item in checks if not item["ok"]]

    result = {
        "checked_at_taiwan": datetime.now(TAIWAN_TZ).isoformat(timespec="seconds"),
        "status": status,
        "stability_score": score,
        "latest_draw_date": latest,
        "latest_numbers": latest_numbers,
        "latest_taiwan_safe_update_time": latest_tw,
        "target_draw_date": target,
        "target_taiwan_safe_update_time": target_tw,
        "top9": top9,
        "database": database,
        "checks": checks,
        "failed_actions": failed,
    }

    lines = [
        "# 天天樂系統穩定度監測",
        "",
        f"- 檢測時間：{datetime.now(TAIWAN_TZ):%Y-%m-%d %H:%M:%S} 台灣時間",
        f"- 穩定度：{score}%",
        f"- 狀態：{status}",
        f"- 最新開獎：{latest or '-'} / {text_numbers(latest_numbers) or '-'}",
        f"- 最新開獎台灣可更新時間：{latest_tw or '-'}",
        f"- 下期預測：{target or '-'} / 台灣時間 {target_tw or '-'}",
        f"- 最強主推九碼：{text_numbers(top9) or '-'}",
        "",
        "## 自動檢測",
        "| 項目 | 結果 | 內容 | 故障自救 |",
        "| --- | --- | --- | --- |",
    ]
    for item in checks:
        lines.append(f"| {item['name']} | {'通過' if item['ok'] else '需修復'} | {item['detail'] or '-'} | {item['action']} |")
    if failed:
        lines.extend(["", "## 需自救項目"])
        lines.extend(f"- {item['name']}：{item['action']}" for item in failed)
    else:
        lines.extend(["", "## 結論", "- 本機、手機、資料庫、預測、低機率紀錄目前通過穩定度監測。"])

    (REPORTS / "system_stability_monitor.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORTS / "system_stability_monitor.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (SITE / "system_stability_monitor.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (SITE / "system_stability_monitor.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "stability_score": score, "failed": len(failed)}, ensure_ascii=False))
    return 0 if score >= 80 else 1


if __name__ == "__main__":
    raise SystemExit(main())
