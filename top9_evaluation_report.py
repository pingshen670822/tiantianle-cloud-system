from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import tenfold_validation_gate as validation_gate


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
TAIWAN = timezone(timedelta(hours=8))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fmt_number(number: Any) -> str:
    try:
        return f"{int(number):02d}"
    except Exception:
        return "-"


def fmt_numbers(values: Any) -> str:
    return " ".join(fmt_number(value) for value in validation_gate.numbers(values or []))


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


CHECK_LABELS = {
    "候選資料存在": "候選資料存在",
    "最新開獎重複防呆": "剛開出重複防呆",
    "上期沿用防呆": "上期沿用防呆",
    "交叉驗算": "交叉驗算",
    "成熟度": "實戰成熟度",
    "信心指標": "信心指標",
    "模型保守機率": "模型保守機率",
    "全歷史校準分": "全歷史校準分",
    "候選總分": "候選總分",
    "公式模組支撐": "公式模組支撐",
    "全歷史模型來源": "全歷史模型來源",
    "產號理由足量": "產號理由足量",
    "主列或輔助放行": "主列或輔助放行",
}


def candidate_row(analysis: dict[str, Any], number: int, latest_numbers: set[int], position: int, official: bool) -> dict[str, Any]:
    candidate = validation_gate.find_candidate(analysis, number)
    check = validation_gate.candidate_pack_checks(candidate, latest_numbers) if candidate else {}
    failed = [
        CHECK_LABELS.get(item.get("name"), item.get("name"))
        for item in check.get("checks", [])
        if not item.get("passed")
    ]
    release_tier = str(check.get("release_tier") or ("完全通過" if not failed else "未放行"))
    remediation_notes = [str(item) for item in (check.get("remediation_notes") or []) if str(item)]
    passed_count = int(check.get("passed_count") or 0)
    total_count = int(check.get("total_count") or 0)
    confidence = float(candidate.get("confidence_index") or 0) if candidate else 0.0
    score = float(candidate.get("score") or 0) if candidate else 0.0
    probability = float(candidate.get("model_probability_percent") or 0) if candidate else 0.0
    omission = int(candidate.get("omission") or 0) if candidate else 0
    stability = int(candidate.get("stability_count") or 0) if candidate else 0

    if official and position <= 3:
        tier = "主力高信心區"
    elif official and position <= 5:
        tier = "主選延伸區"
    elif official:
        tier = "正式九碼延伸區"
    else:
        tier = "未放行觀察"

    if official and passed_count >= total_count:
        conclusion = f"{release_tier}，列入正式九碼池"
    elif official:
        conclusion = "不符合正式推薦，必須移出正式池"
    else:
        conclusion = "未通過正式放行，不得混入正式九碼"

    return {
        "position": position,
        "number": number,
        "number_text": fmt_number(number),
        "tier": tier,
        "score": round(score, 6),
        "confidence": round(confidence, 1),
        "model_probability_percent": round(probability, 2),
        "omission": omission,
        "stability_count": stability,
        "passed_checks": passed_count,
        "total_checks": total_count,
        "failed_checks": failed,
        "release_tier": release_tier,
        "remediation_notes": remediation_notes,
        "official": official,
        "conclusion": conclusion,
    }


def build_report() -> dict[str, Any]:
    analysis = read_json(REPORTS / "latest_analysis.json")
    latest = analysis.get("latest_draw") or {}
    latest_numbers = set(validation_gate.numbers(latest.get("numbers") or [], limit=5))
    pool = validation_gate.numbers((analysis.get("prediction") or {}).get("top9") or [], limit=9)
    rows = [candidate_row(analysis, number, latest_numbers, index + 1, True) for index, number in enumerate(pool)]

    rejected: list[dict[str, Any]] = []
    for candidate in (analysis.get("official_candidates") or analysis.get("candidates") or [])[:25]:
        number = validation_gate.safe_int(candidate.get("number"))
        if not (1 <= number <= 39) or number in pool:
            continue
        row = candidate_row(analysis, number, latest_numbers, len(rejected) + 1, False)
        if row["passed_checks"] >= 9 or number in latest_numbers:
            rejected.append(row)
        if len(rejected) >= 8:
            break

    gate = analysis.get("tenfold_validation_gate") or {}
    target_time = analysis.get("prediction_draw_taiwan_time") or gate.get("target_taiwan_time") or ""
    payload = {
        "title": "天天樂最新九碼全面評估",
        "created_at_taiwan": datetime.now(TAIWAN).strftime("%Y-%m-%d %H:%M:%S"),
        "latest_draw_date": latest.get("draw_date"),
        "latest_numbers": validation_gate.numbers(latest.get("numbers") or [], limit=5),
        "target_draw_date": analysis.get("target_draw_date") or gate.get("target_draw_date"),
        "target_taiwan_time": target_time,
        "official_pool_count": len(pool),
        "official_pool": rows,
        "rejected_watch": rejected,
        "tenfold_status": gate.get("status"),
        "tenfold_passed_count": gate.get("passed_count"),
        "tenfold_total_count": gate.get("total_count"),
        "summary": {
            "single": fmt_numbers((analysis.get("prediction") or {}).get("top1")),
            "two": fmt_numbers((analysis.get("prediction") or {}).get("top2")),
            "three": fmt_numbers((analysis.get("prediction") or {}).get("top3")),
            "five": fmt_numbers((analysis.get("prediction") or {}).get("top5")),
            "nine": fmt_numbers(pool),
            "note": "正式推薦必須逐號全項通過；未通過者只列未放行觀察，不得硬塞九碼。",
        },
    }
    return payload


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def render_html(payload: dict[str, Any]) -> str:
    official_rows = []
    for row in payload["official_pool"]:
        failed = "、".join(row["failed_checks"]) if row["failed_checks"] else "無"
        official_rows.append(
            [
                esc(row["position"]),
                f"<strong class=\"num\">{esc(row['number_text'])}</strong>",
                esc(row["tier"]),
                esc(row["confidence"]),
                esc(row["model_probability_percent"]),
                esc(row["score"]),
                esc(row["omission"]),
                esc(row["stability_count"]),
                esc(f"{row['passed_checks']}/{row['total_checks']}"),
                esc(row["release_tier"]),
                esc("、".join(row["remediation_notes"]) if row["remediation_notes"] else "無"),
                esc(failed),
                esc(row["conclusion"]),
            ]
        )

    rejected_rows = []
    for row in payload["rejected_watch"]:
        failed = "、".join(row["failed_checks"]) if row["failed_checks"] else "無"
        rejected_rows.append(
            [
                f"<strong class=\"num muted\">{esc(row['number_text'])}</strong>",
                esc(row["confidence"]),
                esc(row["model_probability_percent"]),
                esc(row["score"]),
                esc(row["omission"]),
                esc(f"{row['passed_checks']}/{row['total_checks']}"),
                esc(row["release_tier"]),
                esc(failed),
                esc(row["conclusion"]),
            ]
        )

    summary = payload["summary"]
    count_note = (
        f"正式九碼池目前 {payload['official_pool_count']} 顆；系統禁止用未全項通過號碼硬補。"
        if payload["official_pool_count"] < 9
        else "正式九碼池已滿 9 顆。"
    )
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(payload['title'])}</title>
  <style>
    body{{font-family:"Microsoft JhengHei",Arial,sans-serif;margin:0;background:#f5f7fb;color:#111827}}
    header{{background:#111827;color:white;padding:20px 16px}}
    main{{max-width:1180px;margin:0 auto;padding:16px}}
    section{{background:white;border:1px solid #dbe3ee;border-radius:8px;padding:16px;margin-bottom:14px}}
    h1,h2{{margin:0 0 10px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}
    .card{{border:1px solid #e5e7eb;border-radius:8px;padding:12px;background:#f8fafc}}
    .label{{font-size:13px;color:#64748b;font-weight:700}}
    .value{{font-size:24px;font-weight:900;margin-top:4px}}
    .num{{font-size:20px;font-weight:900;color:#b91c1c}}
    .muted{{color:#475569}}
    .ok{{color:#047857;font-weight:900}}
    .warn{{color:#b45309;font-weight:900}}
    .table-wrap{{overflow:auto}}
    table{{width:100%;border-collapse:collapse;min-width:980px}}
    th,td{{border-bottom:1px solid #e5e7eb;padding:9px;text-align:left;vertical-align:top}}
    th{{background:#eef2f7;white-space:nowrap}}
    td{{font-size:14px}}
  </style>
</head>
<body>
<header>
  <h1>天天樂最新九碼全面評估</h1>
  <p>建立時間：{esc(payload['created_at_taiwan'])} 台灣時間</p>
</header>
<main>
  <section>
    <h2>本期基準</h2>
    <div class="grid">
      <div class="card"><div class="label">最新開獎</div><div class="value">{esc(payload['latest_draw_date'])}</div><div>{esc(fmt_numbers(payload['latest_numbers']))}</div></div>
      <div class="card"><div class="label">預測目標</div><div class="value">{esc(payload['target_draw_date'])}</div><div>台灣開獎 {esc(payload['target_taiwan_time'])}</div></div>
      <div class="card"><div class="label">十重驗證</div><div class="value ok">{esc(payload['tenfold_status'])}</div><div>{esc(payload['tenfold_passed_count'])}/{esc(payload['tenfold_total_count'])}</div></div>
      <div class="card"><div class="label">九碼池狀態</div><div class="value warn">{esc(payload['official_pool_count'])} 顆</div><div>{esc(count_note)}</div></div>
    </div>
  </section>
  <section>
    <h2>核心組合</h2>
    <div class="grid">
      <div class="card"><div class="label">最強獨隻</div><div class="value num">{esc(summary['single'])}</div></div>
      <div class="card"><div class="label">2中1~2</div><div class="value num">{esc(summary['two'])}</div></div>
      <div class="card"><div class="label">3中1~3</div><div class="value num">{esc(summary['three'])}</div></div>
      <div class="card"><div class="label">5中1~5</div><div class="value num">{esc(summary['five'])}</div></div>
    </div>
    <p><strong>正式九碼池：</strong>{esc(summary['nine'])}</p>
    <p>{esc(summary['note'])}</p>
  </section>
  <section>
    <h2>正式池逐號評估</h2>
    {table(["序", "號碼", "層級", "信心", "模型機率", "總分", "遺漏", "穩定", "驗證", "驗證型態", "補強理由", "弱點", "結論"], official_rows)}
  </section>
  <section>
    <h2>未放行候選檢查</h2>
    <p>這一區只說明為什麼高分候選沒有進正式池，不能當正式推薦。</p>
    {table(["號碼", "信心", "模型機率", "總分", "遺漏", "驗證", "驗證型態", "未過項", "結論"], rejected_rows)}
  </section>
</main>
</body>
</html>"""


def main() -> None:
    payload = build_report()
    html_text = render_html(payload)
    json_paths = [
        REPORTS / "latest_top9_evaluation.json",
        SITE / "latest_top9_evaluation.json",
        SITE / "reports" / "latest_top9_evaluation.json",
    ]
    html_paths = [
        REPORTS / "latest_top9_evaluation.html",
        REPORTS / "最新九碼全面評估.html",
        SITE / "latest_top9_evaluation.html",
        SITE / "reports" / "latest_top9_evaluation.html",
        SITE / "reports" / "最新九碼全面評估.html",
    ]
    for path in json_paths:
        write_json(path, payload)
    for path in html_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_text, encoding="utf-8")
    print(json.dumps({"status": "ok", "pool_count": payload["official_pool_count"], "report": str(html_paths[0])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
