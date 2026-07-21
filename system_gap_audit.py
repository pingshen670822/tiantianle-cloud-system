import argparse
import csv
import json
import pathlib
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


def db_summary():
    if not DB_PATH.exists():
        return {"exists": False, "count": 0, "latest_date": ""}
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT COUNT(*), MIN(draw_date), MAX(draw_date) FROM draws").fetchone()
    return {"exists": True, "count": row[0] or 0, "first_date": row[1] or "", "latest_date": row[2] or ""}


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

    if len(top9) != 9 or len(set(top9)) != 9:
        add_issue(issues, "預測結構", f"前九名格式錯誤：{numbers_text(top9)}", "九碼核心無法穩定檢討", "前九名必須固定九顆且不得重複", "嚴重")
    if len(top15) < 15 or len(set(top15[:15])) < 15:
        add_issue(issues, "預測結構", "前十五名不足或重複", "第十到第十五名備查會失真", "補齊前十五名排序與重複檢查", "嚴重")

    latest_overlap = sorted(set(int(n) for n in latest_numbers) & set(int(n) for n in top9))
    firewall = industrial.get("recent_draw_firewall") or {}
    if latest_overlap and not firewall.get("blocked_numbers"):
        add_issue(issues, "連莊防火牆", f"前九名含上期開出號：{numbers_text(latest_overlap)}", "容易被誤認為沿用上期預測", "剛開出號必須通過硬驗證才可進入前九", "嚴重")

    release_status = str(release.get("status", ""))
    if release_status not in {"official", "verified_research_complete", "watch_only", "正式", "研究觀察通過", "觀察中"}:
        add_issue(issues, "發布守門", f"發布狀態不明：{release_status or '-'}", "高信心區無法判讀", "發布守門必須固定為正式、研究觀察或觀察中", "需修正")
    if release_status in {"watch_only", "觀察中"}:
        add_issue(
            issues,
            "模型成熟度",
            "正式發布守門仍未通過",
            "高信心只能標示觀察，不能包裝成保證",
            "持續用小組競賽、成熟度、近期回測淘汰弱訊號",
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

    gap_rows = model_gap_rows(analysis)
    for item in gap_rows[:8]:
        add_issue(issues, "模型缺口", item["category"], item["impact"], item["fix"], "需補強")

    status = "通過" if not any(item["severity"] == "嚴重" for item in issues) else "需立即修正"
    payload = {
        "checked_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        "status": status,
        "latest_draw_date": latest_date,
        "latest_numbers": latest_numbers,
        "latest_taiwan_update_time": latest_tw,
        "target_draw_date": target_date,
        "target_taiwan_time": target_tw,
        "top9": top9,
        "top15": top15[:15],
        "draw_count": analysis.get("draw_count"),
        "database": db,
        "release_status": release_status,
        "model_maturity": maturity,
        "low_probability_backtest": low_backtest,
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
        "",
        "## 欠缺元素與修補動作",
        *table(["等級", "區域", "欠缺或風險", "影響", "修補方式"], issue_rows),
        "",
        "## 模型缺口明細",
        *table(["缺口", "證據", "影響", "已補或執行方向"], gap_detail_rows),
        "",
        "## 結論",
        "- 本檔每日更新後自動重建，作為下一期滾動修正依據。",
        "- 未通過正式守門的號碼只能標示觀察，不得包裝成保證。",
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

    print(json.dumps({"status": status, "issues": len(issues), "critical": sum(1 for item in issues if item["severity"] == "嚴重")}, ensure_ascii=False))
    if args.fail_on_critical and any(item["severity"] == "嚴重" for item in issues):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
