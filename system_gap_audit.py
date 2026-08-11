import argparse
import csv
import hashlib
import json
import pathlib
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = pathlib.Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
SITE_DIR = ROOT / "site"
DATA_DIR = ROOT / "data"
ANALYSIS_PATH = REPORT_DIR / "latest_analysis.json"
DB_PATH = DATA_DIR / "california_fantasy5.sqlite"
TAIWAN = ZoneInfo("Asia/Taipei")
OPEN_SYNC_SCRIPT_RE = re.compile(
    r"\s*<script>\s*\(function\(\)\{\s*if \(window\.TIANTIANLE_OPEN_SYNC_VERSION.*?\}\)\(\);\s*</script>",
    re.S,
)


def read_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def numbers_text(numbers):
    return " ".join(f"{int(number):02d}" for number in numbers or [])


def csv_count(path):
    if not path.exists():
        return 0, "", ""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return 0, "", ""
    return len(rows), rows[0].get("draw_date", ""), rows[-1].get("draw_date", "")


def file_digest(path):
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comparable_file_digest(path):
    if not path.exists():
        return ""
    if path.suffix.lower() == ".html":
        text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        text = OPEN_SYNC_SCRIPT_RE.sub("", text)
        text = re.sub(r"\s+</body>", "</body>", text)
        text = re.sub(r"\s+</html>", "</html>", text)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    return file_digest(path)


def db_summary():
    if not DB_PATH.exists():
        return {"exists": False, "count": 0, "latest_date": ""}
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT COUNT(*), MIN(draw_date), MAX(draw_date) FROM draws").fetchone()
    return {"exists": True, "count": row[0] or 0, "first_date": row[1] or "", "latest_date": row[2] or ""}


def review_storage_summary():
    summary = {
        "snapshot_duplicate_groups": 0,
        "snapshot_duplicate_rows": 0,
        "archive_duplicate_groups": 0,
    }
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT COUNT(*), SUM(extra_count)
                    FROM (
                        SELECT COUNT(*) - 1 AS extra_count
                        FROM prediction_snapshots
                        GROUP BY based_on_date,target_date,snapshot_reason
                        HAVING COUNT(*) > 1
                    )
                    """
                ).fetchone()
                summary["snapshot_duplicate_groups"] = int(rows[0] or 0)
                summary["snapshot_duplicate_rows"] = int(rows[1] or 0)
            except sqlite3.Error:
                pass
    archive = REPORT_DIR / "daily_prediction_review_archive.jsonl"
    if archive.exists():
        seen = set()
        duplicates = set()
        for line in archive.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (payload.get("expected_taiwan_safe_update_time"), payload.get("latest_draw_date"))
            if key in seen:
                duplicates.add(key)
            seen.add(key)
        summary["archive_duplicate_groups"] = len(duplicates)
    return summary


def latest_expected_taiwan_time(now=None):
    now = now or datetime.now(TAIWAN)
    today_safe = now.replace(hour=9, minute=50, second=0, microsecond=0)
    if now < today_safe:
        today_safe = today_safe.replace(day=today_safe.day)
        return today_safe.fromtimestamp(today_safe.timestamp() - 86400, TAIWAN)
    return today_safe


def add_issue(issues, area, problem, impact, fix, severity="需修正"):
    issues.append(
        {
            "area": area,
            "problem": problem,
            "impact": impact,
            "fix": fix,
            "severity": severity,
        }
    )


def dedupe_issues(issues):
    seen = set()
    deduped = []
    for item in issues:
        key = (
            item.get("severity", ""),
            item.get("area", ""),
            item.get("problem", ""),
            item.get("impact", ""),
            item.get("fix", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


PUBLISH_BLOCKING_AREAS = {
    "檔案完整度",
    "全歷史資料庫",
    "資料庫",
    "手機同步",
    "預測結構",
    "假運算防呆",
}


def is_publish_blocking_issue(item):
    if item.get("severity") != "嚴重":
        return False
    return item.get("area") in PUBLISH_BLOCKING_AREAS


def model_gap_rows(analysis):
    industrial = analysis.get("industrial_engine") or {}
    gap = industrial.get("prediction_gap_diagnosis") or {}
    rows = []
    for item in gap.get("missing_elements") or []:
        rows.append(
            {
                "category": item.get("category", "-"),
                "evidence": item.get("evidence", "-"),
                "impact": item.get("impact", "-"),
                "fix": item.get("fix", "-"),
            }
        )
    return rows


def table(headers, rows):
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    if not rows:
        output.append("| " + " | ".join(["目前無"] + ["-"] * (len(headers) - 1)) + " |")
        return output
    for row in rows:
        output.append("| " + " | ".join(str(value).replace("\n", " ") for value in row) + " |")
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-on-critical", action="store_true")
    parser.add_argument("--fail-on-publish-blocking", action="store_true")
    parser.add_argument("--local-only", action="store_true")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    analysis = read_json(ANALYSIS_PATH)
    latest = analysis.get("latest_draw") or {}
    freshness = analysis.get("freshness") or {}
    prediction = analysis.get("prediction") or {}
    industrial = analysis.get("industrial_engine") or {}
    release = industrial.get("release_gate") or {}
    maturity = industrial.get("practical_maturity") or {}
    correction = industrial.get("multi_model_correction") or {}
    entry_gate = industrial.get("full_system_entry_gate") or {}
    post_draw_correction = industrial.get("post_draw_error_correction") or {}
    post9_leak = industrial.get("post9_hit_leak_audit") or (entry_gate.get("post9_hit_leak_audit") or {})
    strong_single_validation = industrial.get("strong_single_validation") or {}
    low = analysis.get("low_probability_avoid") or {}
    low_backtest = low.get("backtest") or (industrial.get("unlikely_backtest") or {})
    issues = []

    latest_date = latest.get("draw_date") or freshness.get("latest_draw_date") or ""
    latest_numbers = latest.get("numbers") or []
    target_date = analysis.get("target_draw_date") or ""
    target_tw = freshness.get("target_taiwan_safe_update_time") or analysis.get("prediction_draw_taiwan_time") or ""
    latest_tw = freshness.get("latest_taiwan_safe_update_time") or analysis.get("latest_draw_taiwan_update_time") or ""
    top9 = prediction.get("top9") or [item.get("number") for item in (analysis.get("candidates") or [])[:9]]
    top15 = prediction.get("top15") or [item.get("number") for item in (analysis.get("candidates") or [])[:15]]
    strong_packs = analysis.get("strong_packs") or analysis.get("strong_prediction_packs") or {}
    strong_single = ((strong_packs.get("strong_single") or {}).get("numbers") or prediction.get("strongest") or prediction.get("top1") or [])

    required_files = [
        REPORT_DIR / "latest_analysis.json",
        REPORT_DIR / "latest_battle_report.html",
        REPORT_DIR / "prediction.html",
        REPORT_DIR / "review.html",
        REPORT_DIR / "tiantianle_low_probability_avoid.html",
        REPORT_DIR / "monthly_summary.html",
        SITE_DIR / "index.html",
        SITE_DIR / "latest_analysis.json",
        SITE_DIR / "reports" / "latest_battle_report.html",
    ]
    for path in required_files:
        if not path.exists():
            add_issue(issues, "檔案完整度", f"缺少 {path.relative_to(ROOT)}", "戰報或手機頁可能無法開啟", "重新執行一鍵更新並禁止發布半成品", "嚴重")

    sync_pairs = [
        (REPORT_DIR / "latest_analysis.json", SITE_DIR / "latest_analysis.json", "最新分析資料"),
        (REPORT_DIR / "latest_analysis.json", SITE_DIR / "reports" / "latest_analysis.json", "手機報表分析資料"),
        (REPORT_DIR / "complete_report.html", SITE_DIR / "complete_report.html", "完整戰報"),
        (REPORT_DIR / "complete_report.html", SITE_DIR / "reports" / "complete_report.html", "手機完整戰報"),
        (REPORT_DIR / "tiantianle_low_probability_avoid.html", SITE_DIR / "reports" / "tiantianle_low_probability_avoid.html", "低機率頁"),
    ]
    for left, right, label in sync_pairs:
        if left.exists() and right.exists() and comparable_file_digest(left) != comparable_file_digest(right):
            add_issue(
                issues,
                "手機同步",
                f"{label} 本機與手機資料夾內容不同",
                "手機版可能看到舊資料或不完整頁面",
                "一鍵更新必須重新建頁並重新發布手機雲端",
                "嚴重",
            )

    stale_cloud_files = sorted(path.name for path in ROOT.glob("cloud_*") if path.is_file())
    if stale_cloud_files:
        add_issue(
            issues,
            "舊檔殘留",
            "外層仍有過期雲端快照：" + ", ".join(stale_cloud_files[:12]),
            "容易誤點到舊戰報，造成手機與電腦日期看起來不同步",
            "一鍵流程已加入自動清理外層 cloud_* 舊快照",
            "需修正",
        )

    legacy_empty_db = DATA_DIR / "california_fantasy5.db"
    if legacy_empty_db.exists() and legacy_empty_db.stat().st_size == 0:
        add_issue(
            issues,
            "舊檔殘留",
            "data/california_fantasy5.db 是 0 位元舊資料庫",
            "人工檢查時容易誤認資料庫壞掉",
            "正式資料庫使用 california_fantasy5.sqlite；一鍵流程已加入自動清理空舊庫",
            "需修正",
        )

    for csv_path in [ROOT / "fantasy5_full_history.csv", DATA_DIR / "california_fantasy5.csv", DATA_DIR / "fantasy5_full_history.csv"]:
        count, first_date, last_date = csv_count(csv_path)
        if count < 10000:
            add_issue(issues, "全歷史資料庫", f"{csv_path.name} 只有 {count} 筆", "回測樣本不足會使排序不穩", "重新匯入全歷史資料庫", "嚴重")
        if latest_date and last_date and last_date != latest_date:
            add_issue(issues, "全歷史資料庫", f"{csv_path.name} 最後日期 {last_date}，最新開獎 {latest_date}", "運算可能不是用最新資料", "開獎後更新必須先同步 CSV 再運算", "嚴重")

    db = db_summary()
    if not db["exists"] or db["count"] < 10000:
        add_issue(issues, "資料庫", "本機資料庫不存在或筆數不足", "模型無法用全歷史穩定回測", "重建資料庫並匯入全歷史 CSV", "嚴重")
    if latest_date and db.get("latest_date") and db["latest_date"] != latest_date:
        add_issue(issues, "資料庫", f"資料庫最新 {db['latest_date']}，戰報最新 {latest_date}", "資料庫與戰報不同步", "重新執行主程式並重新輸出戰報", "嚴重")

    review_storage = review_storage_summary()
    if review_storage["snapshot_duplicate_rows"] > 0:
        add_issue(
            issues,
            "檢討儲存",
            f"預測快照重複 {review_storage['snapshot_duplicate_rows']} 筆",
            "戰報可能重複計算同一期，造成月統計與檢討失真",
            "主程式已改為同一期同原因只保留最新快照並每日自動去重",
            "嚴重",
        )
    if review_storage["archive_duplicate_groups"] > 0:
        add_issue(
            issues,
            "檢討儲存",
            f"開獎後歸檔重複 {review_storage['archive_duplicate_groups']} 組",
            "同一期重試會被看成多期檢討，造成命中率判讀失真",
            "自動更新歸檔已改為同一期覆寫最後狀態",
            "嚴重",
        )

    if len(top9) != 9 or len(set(top9)) != 9:
        add_issue(issues, "預測結構", f"前九名格式錯誤：{numbers_text(top9)}", "九碼核心無法穩定檢討", "前九名必須固定九顆且不得重複", "嚴重")
    if len(top15) < 15 or len(set(top15[:15])) < 15:
        add_issue(issues, "預測結構", "前十五名不足或重複", "第十到第十五名備查會失真", "補齊前十五名排序與重複檢查", "嚴重")

    latest_overlap = sorted(set(int(n) for n in latest_numbers) & set(int(n) for n in top9))
    firewall = industrial.get("recent_draw_firewall") or {}
    if latest_overlap and not firewall.get("blocked_numbers"):
        add_issue(issues, "連莊防火牆", f"前九名含上期開出號：{numbers_text(latest_overlap)}", "容易被誤認為沿用上期預測", "剛開出號必須通過硬驗證才可進入前九", "嚴重")

    failure_gate = industrial.get("recent_failure_front_gate") or {}
    review = analysis.get("failure_review") or {}
    failed_numbers = set(int(n) for n in (review.get("rolling_failed_numbers") or []) if str(n).isdigit())
    failed_top9 = sorted(failed_numbers & set(int(n) for n in top9))
    revalidated = set(int(n) for n in (failure_gate.get("revalidated_numbers") or []) if str(n).isdigit())
    entry_revalidated = {
        int(item.get("number"))
        for item in (analysis.get("official_candidates") or analysis.get("candidates") or [])
        if item.get("number") is not None
        and (item.get("entry_validation") or {}).get("passed_for_main")
        and (item.get("entry_validation") or {}).get("status") in {
            "主列重驗通過",
            "核心通過",
            "主列補位通過",
            "低迷重整主列通過",
            "失準急救主列通過",
        }
    }
    if failed_top9 and not set(failed_top9).issubset(revalidated | entry_revalidated):
        add_issue(
            issues,
            "近期失準守門",
            f"近期失準號仍進前九：{numbers_text(failed_top9)}",
            "會讓下一期排序被失準結構拖走",
            "近期失準號必須完成全歷史、成熟度與交叉驗算重驗才可回前九",
            "嚴重",
        )
    if review.get("severity") == "critical" and correction.get("status") != "已執行":
        add_issue(
            issues,
            "多模型競賽校正",
            "近期失準時沒有啟動重新排序",
            "原模型方向會持續拖住下一期預測",
            "主程式必須自動換模型競賽、降權弱模型、前移漏抓與後段命中號",
            "嚴重",
        )
    if post9_leak.get("active"):
        add_issue(
            issues,
            "九名後命中外漏",
            f"近{post9_leak.get('checked_periods', 0)}期九名後命中 {post9_leak.get('post9_hits', 0)} 顆，前九命中 {post9_leak.get('front9_hits', 0)} 顆",
            "有效號碼被壓到第十名後，前九精準度會下降",
            "第15版已啟動完美日期牌與完美必拖牌，日期型態、拖牌共現、前五強支撐與近窗回測未通過者不得列強拖",
            "需補強",
        )

    candidates = analysis.get("official_candidates") or analysis.get("candidates") or []
    candidate_map = {int(item.get("number")): item for item in candidates if item.get("number") is not None}
    top9_gate_failed = []
    for number in top9:
        try:
            number_int = int(number)
        except (TypeError, ValueError):
            continue
        validation = (candidate_map.get(number_int) or {}).get("entry_validation") or {}
        if not validation.get("passed_for_main"):
            top9_gate_failed.append(number_int)
    if entry_gate.get("status") != "已執行":
        add_issue(
            issues,
            "全系統主列放行",
            f"放行門狀態 {entry_gate.get('status', '-')}",
            "未達標號碼可能進入前九或強牌",
            "每期必須先跑全歷史回測、多模型校正、強牌治理、精算小牌競賽，再放行主列",
            "嚴重",
        )
    if int(entry_gate.get("main_count", 0) or 0) < 9:
        add_issue(
            issues,
            "全系統主列放行",
            f"主列通過數 {entry_gate.get('main_count', 0)} 顆",
            "前九主列未滿或含未過門號碼",
            "未滿九顆時不得包裝成完整主推，必須重新校正模型與門檻",
            "嚴重",
        )
    if top9_gate_failed:
        add_issue(
            issues,
            "全系統主列放行",
            f"前九含未通過號碼：{numbers_text(top9_gate_failed)}",
            "戰報會把未驗證號碼混入主選",
            "強制套用全系統放行門，未通過只能留在備查或觀察",
            "嚴重",
        )

    recalculation = analysis.get("recalculation_manifest") or {}
    if recalculation.get("previous_prediction_reused") is not False:
        add_issue(
            issues,
            "假運算防呆",
            "重算宣告未明確禁止沿用上期預測",
            "可能把上期預測包裝成新一期",
            "每期必須重新產生 fingerprint，並寫入 previous_prediction_reused=false",
            "嚴重",
        )
    if post_draw_correction.get("status") not in {"已執行", "首次或無上期可檢討"}:
        add_issue(
            issues,
            "錯誤模組滾動修正",
            "缺少開獎後錯誤模組修正協議",
            "失誤模組不會被降權或重新校正",
            "開獎檢討後必須輸出落空、漏抓、強牌失準與模型權重修正清單",
            "嚴重",
        )
    if post_draw_correction.get("status") == "已執行" and not post_draw_correction.get("rolling_recomputed"):
        add_issue(
            issues,
            "錯誤模組滾動修正",
            "已完成上期檢討但沒有滾動修正資料",
            "下一期模型仍可能沿用失準邏輯",
            "每期檢討後必須重算 penalized、boosted、漏抓回收與強牌治理",
            "嚴重",
        )
    try:
        strong_single_numbers = [int(number) for number in strong_single]
    except (TypeError, ValueError):
        strong_single_numbers = []
    if len(strong_single_numbers) != 1:
        add_issue(
            issues,
            "最強獨支",
            f"最強獨支不是一顆：{numbers_text(strong_single_numbers)}",
            "無法檢討 1中1 模型",
            "每期必須由全系統放行主列產出一顆獨支，並保留驗證證據",
            "嚴重",
        )
    elif strong_single_validation.get("number") != strong_single_numbers[0]:
        add_issue(
            issues,
            "最強獨支",
            "獨支號碼與獨支驗證資料不一致",
            "可能出現假資料或戰報顯示不同步",
            "獨支輸出必須和 strong_single_validation 完全一致",
            "嚴重",
        )
    elif strong_single_validation.get("status") not in {"已驗證", "觀察輸出"}:
        add_issue(
            issues,
            "最強獨支",
            f"獨支驗證狀態不明：{strong_single_validation.get('status', '-')}",
            "獨支可能未經多模組驗證",
            "必須通過主列放行、多模型、交叉驗算、成熟度與上期開獎防呆",
            "嚴重",
        )
    if strong_single_numbers and set(strong_single_numbers) & set(int(n) for n in latest_numbers):
        if not strong_single_validation.get("latest_draw_reuse_allowed"):
            add_issue(
                issues,
                "最強獨支",
                f"獨支疑似使用上期開獎號：{numbers_text(strong_single_numbers)}",
                "容易被誤認為拿上期開獎號忽弄",
                "上期開獎號不得列獨支，除非完成嚴格連莊重驗並明確標示",
                "嚴重",
            )

    release_status = str(release.get("status", ""))
    if release_status not in {"official", "verified_research_complete", "watch_only", "正式", "研究觀察通過", "觀察中"}:
        add_issue(issues, "發布守門", f"發布狀態不明：{release_status or '-'}", "高信心區無法判讀", "發布守門必須固定為正式、研究觀察或觀察中", "需修正")
    if release_status in {"watch_only", "觀察中"}:
        add_issue(
            issues,
            "模型成熟度",
            "正式高信心觸發多模型校正",
            "原排序方向需要重新壓低弱模型並提高漏抓回收",
            "已啟動多模型競賽校正，後續強牌與九碼核心改用重排結果",
            "需補強",
        )

    if float(maturity.get("top10_avg_maturity", 0) or 0) < 70:
        add_issue(
            issues,
            "模型成熟度",
            f"前十平均成熟度 {maturity.get('top10_avg_maturity', '-')}",
            "前十核心仍有不穩定號碼",
            "成熟度未達 70 前不得升為正式高信心",
            "需補強",
        )

    low_avg = float(low_backtest.get("avg_accidental_hits", 0) or 0)
    low_edge = float(low_backtest.get("edge_vs_random", 0) or 0)
    if low_avg > 1.2 or low_edge >= 0:
        add_issue(
            issues,
            "低機率暫避",
            f"暫避平均誤中 {low_avg}，優勢值 {low_edge}",
            "低機率清單仍可能誤開偏高",
            "暫避核心排除前十五名、近期實開風險與回收號，並每日記錄誤開",
            "需補強",
        )

    low_guard = analysis.get("low_probability_monthly_guard") or low.get("monthly_guard") or {}
    for key, label in [("five_miss", "5不中"), ("ten_miss", "10不中"), ("fifteen_miss", "15不中")]:
        guard = low_guard.get(key) or {}
        pack = (low.get("avoid_packs") or {}).get(key) or {}
        confidence_label = str(pack.get("confidence_label", ""))
        try:
            confidence_index = float(pack.get("confidence_index", 0) or 0)
        except Exception:
            confidence_index = 0
        high_confidence_labels = {"高避開信心", "中高避開信心"}
        if guard.get("status") == "降級" and (confidence_label in high_confidence_labels or confidence_index > float(guard.get("confidence_cap", 100) or 100)):
            add_issue(
                issues,
                "低機率暫避",
                f"{label} 已觸發月度誤開降級但仍顯示高信心",
                "低機率誤開偏高會被包裝成高信心避開",
                "套用月度誤開守門，降級後不得標示高信心",
                "嚴重",
            )

    gap_rows = model_gap_rows(analysis)
    for item in gap_rows[:8]:
        add_issue(issues, "模型缺口", item["category"], item["impact"], item["fix"], "需補強")

    issues = dedupe_issues(issues)
    critical_count = sum(1 for item in issues if item["severity"] == "嚴重")
    publish_blocking_count = sum(1 for item in issues if is_publish_blocking_issue(item))
    needs_fix_count = sum(1 for item in issues if item["severity"] == "需修正")
    needs_strengthen_count = sum(1 for item in issues if item["severity"] == "需補強")
    has_critical = critical_count > 0
    status = "需立即修正" if has_critical else ("無嚴重缺漏，仍需模型補強" if issues else "通過")
    payload = {
        "checked_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        "status": status,
        "critical": critical_count,
        "publish_blocking": publish_blocking_count,
        "needs_fix": needs_fix_count,
        "needs_strengthen": needs_strengthen_count,
        "issue_count": len(issues),
        "latest_draw_date": latest_date,
        "latest_numbers": latest_numbers,
        "latest_taiwan_update_time": latest_tw,
        "target_draw_date": target_date,
        "target_taiwan_time": target_tw,
        "top9": top9,
        "top15": top15[:15],
        "draw_count": analysis.get("draw_count"),
        "database": db,
        "review_storage": review_storage,
        "release_status": release_status,
        "multi_model_correction": correction,
        "full_system_entry_gate": entry_gate,
        "post_draw_error_correction": post_draw_correction,
        "post9_hit_leak_audit": post9_leak,
        "strong_single_validation": strong_single_validation,
        "model_maturity": maturity,
        "low_probability_backtest": low_backtest,
        "low_probability_monthly_guard": low_guard,
        "issues": issues,
    }

    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    (REPORT_DIR / "system_gap_audit.json").write_text(json_text, encoding="utf-8")
    (SITE_DIR / "system_gap_audit.json").write_text(json_text, encoding="utf-8")
    (SITE_DIR / "reports").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "reports" / "system_gap_audit.json").write_text(json_text, encoding="utf-8")

    issue_rows = [[item["severity"], item["area"], item["problem"], item["impact"], item["fix"]] for item in issues]
    gap_detail_rows = [[item["category"], item["evidence"], item["impact"], item["fix"]] for item in gap_rows]
    lines = [
        "# 天天樂系統缺口總檢討",
        "",
        f"- 檢查時間：{payload['checked_at_taiwan']} 台灣時間",
        f"- 結論：{status}",
        f"- 最新開獎：{latest_date} / {numbers_text(latest_numbers)}",
        f"- 下期預測台灣時間：{target_tw}",
        f"- 主資料筆數：{analysis.get('draw_count', '-')}",
        f"- 前九名：{numbers_text(top9)}",
        f"- 第十到第十五名：{numbers_text(top15[9:15])}",
        f"- 發布守門：{release_status or '-'}",
        f"- 多模型競賽校正：{correction.get('status', '-')} / 前九重排 {numbers_text(correction.get('new_top9') or top9)}",
        f"- 全系統主列放行：{entry_gate.get('status', '-')} / 主列 {numbers_text(entry_gate.get('main_numbers') or [])}",
        f"- 九名後外漏檢測：{post9_leak.get('status', '-')} / 前九 {post9_leak.get('front9_hits', 0)} / 九名後 {post9_leak.get('post9_hits', 0)}",
        f"- 錯誤模組滾動修正：{post_draw_correction.get('status', '-')} / 滾動重算 {post_draw_correction.get('rolling_recomputed', '-')}",
        f"- 最強獨支驗證：{strong_single_validation.get('status', '-')} / {numbers_text([strong_single_validation.get('number')]) if strong_single_validation.get('number') else '-'}",
        f"- 檢討快照重複：{review_storage['snapshot_duplicate_rows']} 筆",
        f"- 開獎後歸檔重複：{review_storage['archive_duplicate_groups']} 組",
        "",
        "## 欠缺元素與修補動作",
        *table(["等級", "區域", "欠缺或風險", "影響", "修補方式"], issue_rows),
        "",
        "## 模型缺口明細",
        *table(["缺口", "證據", "影響", "已補或執行方向"], gap_detail_rows),
        "",
        "## 結論",
        "- 本檔每日更新後自動重建，作為下一期滾動修正依據。",
        "- 原排序達標不足時，系統會自動啟動多模型重排、弱模型降權、漏抓回收與後段命中前移。",
    ]
    markdown = "\n".join(lines) + "\n"
    for path in [
        REPORT_DIR / "system_gap_audit.md",
        REPORT_DIR / "天天樂系統缺口總檢討.md",
        SITE_DIR / "system_gap_audit.md",
        SITE_DIR / "天天樂系統缺口總檢討.md",
        SITE_DIR / "reports" / "system_gap_audit.md",
        SITE_DIR / "reports" / "天天樂系統缺口總檢討.md",
    ]:
        path.write_text(markdown, encoding="utf-8")

    print(json.dumps({"status": status, "issues": len(issues), "critical": critical_count, "publish_blocking": publish_blocking_count}, ensure_ascii=False))
    if args.fail_on_publish_blocking and publish_blocking_count > 0:
        raise SystemExit(2)
    if args.fail_on_critical and has_critical:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
