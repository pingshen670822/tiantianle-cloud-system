from __future__ import annotations

import csv
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
HISTORY = ROOT / "fantasy5_full_history.csv"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def fmt_number(value: Any) -> str:
    try:
        return f"{int(value):02d}"
    except Exception:
        return "-"


def fmt_numbers(values: Any) -> str:
    return " ".join(fmt_number(value) for value in validation_gate.numbers(values or []))


def safe_float(value: Any) -> float:
    return validation_gate.safe_float(value)


def load_history() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not HISTORY.exists():
        return rows
    with HISTORY.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            draw_date = str(raw.get("draw_date") or raw.get("date") or "")[:10]
            nums = validation_gate.numbers([raw.get(f"n{i}") for i in range(1, 6)], limit=5)
            if draw_date and len(nums) == 5:
                rows.append({"draw_date": draw_date, "numbers": nums})
    rows.sort(key=lambda item: item["draw_date"])
    return rows


def count_hits(draws: list[dict[str, Any]], number: int) -> int:
    return sum(1 for row in draws if number in set(row.get("numbers") or []))


def percent(value: float) -> float:
    return round(value, 2)


def build_report() -> dict[str, Any]:
    analysis = read_json(REPORTS / "latest_analysis.json")
    draws = load_history()
    latest = analysis.get("latest_draw") or {}
    latest_numbers = set(validation_gate.numbers(latest.get("numbers") or [], limit=5))
    prediction = analysis.get("prediction") or {}
    top9 = validation_gate.numbers(prediction.get("top9") or [], limit=9)
    top5 = set(validation_gate.numbers(prediction.get("top5") or [], limit=5))
    top3 = set(validation_gate.numbers(prediction.get("top3") or [], limit=3))
    top2 = set(validation_gate.numbers(prediction.get("top2") or [], limit=2))
    top1 = set(validation_gate.numbers(prediction.get("top1") or [], limit=1))
    low_avoid = set(
        validation_gate.numbers(prediction.get("low_probability_15_not_hit") or [], limit=15)
        + validation_gate.numbers(prediction.get("low_probability_10_not_hit") or [], limit=10)
        + validation_gate.numbers(prediction.get("low_probability_5_not_hit") or [], limit=5)
    )
    official_order = {number: index for index, number in enumerate(top9, start=1)}
    candidates = {
        validation_gate.safe_int(item.get("number")): item
        for item in (analysis.get("official_candidates") or analysis.get("candidates") or [])
        if isinstance(item, dict) and 1 <= validation_gate.safe_int(item.get("number")) <= 39
    }
    total = max(len(draws), 1)
    recent_30 = draws[-30:]
    recent_100 = draws[-100:]
    rows: list[dict[str, Any]] = []
    for number in range(1, 40):
        item = candidates.get(number, {"number": number})
        check = validation_gate.candidate_pack_checks(item, latest_numbers)
        full_hits = count_hits(draws, number)
        hit_30 = count_hits(recent_30, number)
        hit_100 = count_hits(recent_100, number)
        model_probability = safe_float(item.get("model_probability_percent"))
        score = safe_float(item.get("score"))
        confidence = safe_float(item.get("confidence_index"))
        if number in top1:
            category = "獨隻"
        elif number in top2:
            category = "二碼核心"
        elif number in top3:
            category = "三碼核心"
        elif number in top5:
            category = "五碼核心"
        elif number in top9:
            category = "九碼正式"
        elif check.get("passed"):
            category = "備選通過"
        elif number in low_avoid:
            category = "低機率暫避"
        else:
            category = "觀察"
        rows.append(
            {
                "number": number,
                "number_text": fmt_number(number),
                "category": category,
                "official_top9": number in top9,
                "official_order": official_order.get(number),
                "model_probability_percent": percent(model_probability),
                "confidence": round(confidence, 1),
                "score": round(score, 6),
                "full_history_hits": full_hits,
                "full_history_rate_percent": percent(full_hits / total * 100),
                "recent_30_hits": hit_30,
                "recent_30_rate_percent": percent(hit_30 / max(len(recent_30), 1) * 100),
                "recent_100_hits": hit_100,
                "recent_100_rate_percent": percent(hit_100 / max(len(recent_100), 1) * 100),
                "omission": validation_gate.safe_int(item.get("omission")),
                "stability_count": validation_gate.safe_int(item.get("stability_count")),
                "validation_passed": bool(check.get("passed")),
                "passed_checks": validation_gate.safe_int(check.get("passed_count")),
                "total_checks": validation_gate.safe_int(check.get("total_count")),
                "release_tier": check.get("release_tier") or "未放行",
                "remediation_notes": check.get("remediation_notes") or [],
                "failed_checks": [
                    str(row.get("name"))
                    for row in check.get("checks", [])
                    if not row.get("passed")
                ],
            }
        )
    rows.sort(key=lambda row: (-row["model_probability_percent"], -row["confidence"], -row["score"], row["number"]))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    payload = {
        "title": "天天樂01到39全號碼機率表",
        "created_at_taiwan": datetime.now(TAIWAN).strftime("%Y-%m-%d %H:%M:%S"),
        "latest_draw_date": latest.get("draw_date"),
        "latest_numbers": validation_gate.numbers(latest.get("numbers") or [], limit=5),
        "target_draw_date": analysis.get("target_draw_date"),
        "target_taiwan_time": analysis.get("prediction_draw_taiwan_time"),
        "draw_count": len(draws),
        "official_top9": top9,
        "summary": {
            "single": fmt_numbers(prediction.get("top1")),
            "two": fmt_numbers(prediction.get("top2")),
            "three": fmt_numbers(prediction.get("top3")),
            "five": fmt_numbers(prediction.get("top5")),
            "nine": fmt_numbers(top9),
            "policy": "01~39 全部列出；正式推薦必須通過逐號驗證，觀察與暫避不得混作主推。",
        },
        "numbers": rows,
    }
    return payload


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{esc(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def render_html(payload: dict[str, Any]) -> str:
    table_rows: list[list[str]] = []
    for row in payload["numbers"]:
        status_class = "ok" if row["official_top9"] else ("low" if row["category"] == "低機率暫避" else "")
        notes = "、".join(row["remediation_notes"]) if row["remediation_notes"] else "-"
        failed = "、".join(row["failed_checks"]) if row["failed_checks"] else "無"
        table_rows.append(
            [
                esc(row["rank"]),
                esc(row["official_order"] or "-"),
                f"<strong class=\"num {status_class}\">{esc(row['number_text'])}</strong>",
                esc(row["category"]),
                esc(row["model_probability_percent"]),
                esc(row["confidence"]),
                esc(row["score"]),
                esc(row["full_history_hits"]),
                esc(row["full_history_rate_percent"]),
                esc(row["recent_30_hits"]),
                esc(row["recent_30_rate_percent"]),
                esc(row["recent_100_hits"]),
                esc(row["recent_100_rate_percent"]),
                esc(row["omission"]),
                esc(row["stability_count"]),
                esc(f"{row['passed_checks']}/{row['total_checks']}"),
                esc(row["release_tier"]),
                esc(notes),
                esc(failed),
            ]
        )
    summary = payload["summary"]
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(payload['title'])}</title>
  <style>
    body{{font-family:"Microsoft JhengHei",Arial,sans-serif;margin:0;background:#f5f7fb;color:#111827}}
    header{{background:#111827;color:white;padding:20px 16px}}
    main{{max-width:1280px;margin:0 auto;padding:16px}}
    section{{background:white;border:1px solid #dbe3ee;border-radius:8px;padding:16px;margin-bottom:14px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}
    .card{{border:1px solid #e5e7eb;border-radius:8px;padding:12px;background:#f8fafc}}
    .label{{font-size:13px;color:#64748b;font-weight:800}}
    .value{{font-size:22px;font-weight:900;margin-top:4px}}
    .num{{font-size:18px;font-weight:900;color:#334155}}
    .num.ok{{color:#b91c1c}}
    .num.low{{color:#64748b}}
    .table-wrap{{overflow:auto}}
    table{{width:100%;border-collapse:collapse;min-width:1260px}}
    th,td{{border-bottom:1px solid #e5e7eb;padding:8px;text-align:left;vertical-align:top;font-size:13px}}
    th{{background:#eef2f7;white-space:nowrap}}
  </style>
</head>
<body>
<header>
  <h1>天天樂01到39全號碼機率表</h1>
  <p>建立時間：{esc(payload['created_at_taiwan'])} 台灣時間</p>
</header>
<main>
  <section>
    <h2>本期基準</h2>
    <div class="grid">
      <div class="card"><div class="label">最新開獎</div><div class="value">{esc(payload['latest_draw_date'])}</div><div>{esc(fmt_numbers(payload['latest_numbers']))}</div></div>
      <div class="card"><div class="label">預測目標</div><div class="value">{esc(payload['target_draw_date'])}</div><div>台灣開獎 {esc(payload['target_taiwan_time'])}</div></div>
      <div class="card"><div class="label">全歷史筆數</div><div class="value">{esc(payload['draw_count'])}</div></div>
      <div class="card"><div class="label">正式九碼</div><div class="value">{esc(summary['nine'])}</div></div>
    </div>
  </section>
  <section>
    <h2>核心組合</h2>
    <p><strong>獨隻：</strong>{esc(summary['single'])}　<strong>2中1~2：</strong>{esc(summary['two'])}　<strong>3中1~3：</strong>{esc(summary['three'])}　<strong>5中1~5：</strong>{esc(summary['five'])}</p>
    <p>{esc(summary['policy'])}</p>
  </section>
  <section>
    <h2>01到39全號碼表</h2>
    {table(["機率排名", "正式序", "號碼", "分類", "模型單號機率", "信心", "總分", "全歷史次數", "全歷史率", "近30次", "近30率", "近100次", "近100率", "遺漏", "穩定", "驗證", "驗證型態", "補強理由", "未過項"], table_rows)}
  </section>
</main>
</body>
</html>"""


def main() -> None:
    payload = build_report()
    html_text = render_html(payload)
    json_paths = [
        REPORTS / "latest_full_probability_table.json",
        SITE / "latest_full_probability_table.json",
        SITE / "reports" / "latest_full_probability_table.json",
    ]
    html_paths = [
        REPORTS / "latest_full_probability_table.html",
        REPORTS / "全號碼機率表.html",
        SITE / "latest_full_probability_table.html",
        SITE / "reports" / "latest_full_probability_table.html",
        SITE / "reports" / "全號碼機率表.html",
    ]
    for path in json_paths:
        write_json(path, payload)
    for path in html_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_text, encoding="utf-8")
    print(json.dumps({"status": "ok", "numbers": len(payload["numbers"]), "report": str(html_paths[0])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
