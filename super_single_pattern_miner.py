from __future__ import annotations

import html
import itertools
import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
ANALYSIS_PATH = REPORTS / "latest_analysis.json"
DB_PATH = ROOT / "data" / "california_fantasy5.sqlite"
TAIWAN = timezone(timedelta(hours=8))
BASELINE = 5 / 39


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def fmt_number(value: Any) -> str:
    number = safe_int(value)
    return f"{number:02d}" if number else "-"


def fmt_numbers(values: Any) -> str:
    return " ".join(fmt_number(value) for value in values or [])


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_all(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=True, indent=2)
    for path in [
        REPORTS / "latest_analysis.json",
        SITE / "latest_analysis.json",
        SITE / "data" / "latest_analysis.json",
        SITE / "reports" / "latest_analysis.json",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def extract_draws() -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT draw_date,n1,n2,n3,n4,n5 FROM draws ORDER BY draw_date ASC"
        ).fetchall()
    output = []
    for row in rows:
        output.append(
            {
                "date": str(row[0]),
                "numbers": [int(row[1]), int(row[2]), int(row[3]), int(row[4]), int(row[5])],
            }
        )
    return output


def selected_number(analysis: dict[str, Any]) -> int:
    prediction = analysis.get("prediction") or {}
    for source in [
        prediction.get("top1"),
        prediction.get("strongest"),
        (analysis.get("super_single_decision") or {}).get("numbers"),
    ]:
        if source:
            return safe_int(source[0])
    return safe_int((analysis.get("super_single_decision") or {}).get("number"))


def find_candidate(analysis: dict[str, Any], number: int) -> dict[str, Any]:
    for item in analysis.get("official_candidates") or analysis.get("candidates") or []:
        if isinstance(item, dict) and safe_int(item.get("number")) == number:
            return item
    return {}


def rate_row(name: str, hits: int, samples: int, kind: str, detail: str, min_samples: int) -> dict[str, Any]:
    rate = hits / samples if samples else 0.0
    lift = rate / BASELINE if BASELINE else 0.0
    passed = samples >= min_samples and lift >= 1.0
    return {
        "name": name,
        "kind": kind,
        "hits": hits,
        "samples": samples,
        "rate": round(rate, 6),
        "lift": round(lift, 4),
        "passed": passed,
        "min_samples": min_samples,
        "detail": detail,
    }


def transition_single_signal(draws: list[dict[str, Any]], latest_numbers: list[int], number: int) -> list[dict[str, Any]]:
    rows = []
    for source in latest_numbers:
        samples = 0
        hits = 0
        for prev, nxt in zip(draws, draws[1:]):
            if source in prev["numbers"]:
                samples += 1
                if number in nxt["numbers"]:
                    hits += 1
        rows.append(rate_row(f"{fmt_number(source)} 拖 {fmt_number(number)}", hits, samples, "單號拖牌", f"前一期含 {fmt_number(source)}，下一期開 {fmt_number(number)}", 300))
    return rows


def transition_pair_signal(draws: list[dict[str, Any]], latest_numbers: list[int], number: int) -> list[dict[str, Any]]:
    rows = []
    for a, b in itertools.combinations(sorted(latest_numbers), 2):
        samples = 0
        hits = 0
        pair = {a, b}
        for prev, nxt in zip(draws, draws[1:]):
            if pair.issubset(set(prev["numbers"])):
                samples += 1
                if number in nxt["numbers"]:
                    hits += 1
        rows.append(rate_row(f"{fmt_number(a)}-{fmt_number(b)} 拖 {fmt_number(number)}", hits, samples, "雙號拖牌", f"前一期同含 {fmt_number(a)}、{fmt_number(b)}，下一期開 {fmt_number(number)}", 25))
    return rows


def delta_formula_signal(draws: list[dict[str, Any]], latest_numbers: list[int], number: int) -> list[dict[str, Any]]:
    rows = []
    deltas = []
    for source in latest_numbers:
        forward = (number - source) % 39
        backward = (source - number) % 39
        delta = forward if forward <= backward else -backward
        if delta == 0:
            continue
        deltas.append((source, delta))
    for source, delta in deltas:
        samples = 0
        hits = 0
        for prev, nxt in zip(draws, draws[1:]):
            if source in prev["numbers"]:
                samples += 1
                if number in nxt["numbers"]:
                    hits += 1
        sign = "+" if delta > 0 else ""
        rows.append(rate_row(f"{fmt_number(source)} {sign}{delta} 生成 {fmt_number(number)}", hits, samples, "差值拖牌", f"前一期含 {fmt_number(source)} 時，以位移 {sign}{delta} 指向 {fmt_number(number)}，下一期實際開 {fmt_number(number)} 的單顆命中率", 300))
    return rows


def date_signals(draws: list[dict[str, Any]], number: int, target_date: str) -> list[dict[str, Any]]:
    try:
        target = date.fromisoformat(target_date)
    except ValueError:
        return []
    buckets = {
        "同星期": lambda d: d.weekday() == target.weekday(),
        "同月份": lambda d: d.month == target.month,
        "同日期尾": lambda d: d.day % 10 == target.day % 10,
        "同月日尾": lambda d: (d.month + d.day) % 10 == (target.month + target.day) % 10,
    }
    rows = []
    for name, pred in buckets.items():
        samples = 0
        hits = 0
        for draw in draws:
            try:
                d = date.fromisoformat(draw["date"])
            except ValueError:
                continue
            if pred(d):
                samples += 1
                if number in draw["numbers"]:
                    hits += 1
        rows.append(rate_row(f"{name} {fmt_number(number)}", hits, samples, "日期牌", f"目標日 {target_date} 的{name}樣本", 200))
    return rows


def omission_before(draws: list[dict[str, Any]], idx: int, number: int) -> int:
    miss = 0
    for j in range(idx - 1, -1, -1):
        if number in draws[j]["numbers"]:
            return miss
        miss += 1
    return miss


def omission_signal(draws: list[dict[str, Any]], number: int) -> dict[str, Any]:
    current = 0
    for draw in reversed(draws):
        if number in draw["numbers"]:
            break
        current += 1
    lo = max(0, current - 2)
    hi = current + 2
    samples = 0
    hits = 0
    for idx in range(1, len(draws)):
        miss = omission_before(draws, idx, number)
        if lo <= miss <= hi:
            samples += 1
            if number in draws[idx]["numbers"]:
                hits += 1
    return rate_row(f"遺漏 {current} 期附近", hits, samples, "遺漏軌跡", f"目前 {fmt_number(number)} 遺漏 {current} 期，採 {lo}-{hi} 期相近樣本", 50)


def recent_signals(draws: list[dict[str, Any]], number: int) -> list[dict[str, Any]]:
    rows = []
    for window in [14, 30, 60, 120, 360, 720]:
        sample = draws[-window:] if len(draws) >= window else draws[:]
        hits = sum(1 for draw in sample if number in draw["numbers"])
        rows.append(rate_row(f"近 {len(sample)} 期", hits, len(sample), "近期軌跡", f"{fmt_number(number)} 的近期出現率；少於30期只列觀察不列通過", 30))
    return rows


def previous_prediction_info(target_date: str, number: int) -> dict[str, Any]:
    if not DB_PATH.exists():
        return {}
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            """
            SELECT based_on_date,target_date,candidates_json,status
            FROM predictions
            WHERE target_date < ?
            ORDER BY target_date DESC,id DESC
            LIMIT 1
            """,
            (target_date,),
        ).fetchone()
    if not row:
        return {}
    try:
        candidates = json.loads(row["candidates_json"] or "[]")
    except Exception:
        candidates = []
    nums = [safe_int(item.get("number")) for item in candidates if isinstance(item, dict)]
    return {
        "previous_target_date": row["target_date"],
        "previous_based_on_date": row["based_on_date"],
        "previous_status": row["status"],
        "previous_top1": nums[:1],
        "previous_top9": nums[:9],
        "same_as_previous_top1": bool(nums[:1] and nums[0] == number),
        "previous_rank": nums.index(number) + 1 if number in nums else None,
    }


def build_report(payload: dict[str, Any]) -> str:
    def tr(row: dict[str, Any]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(row.get('kind', '-')))}</td>"
            f"<td>{html.escape(str(row.get('name', '-')))}</td>"
            f"<td>{row.get('hits', 0)}/{row.get('samples', 0)}</td>"
            f"<td>{pct(row.get('rate'))}</td>"
            f"<td>{row.get('lift', 0)}</td>"
            f"<td>{'通過' if row.get('passed') else '未達'}</td>"
            f"<td>{html.escape(str(row.get('detail', '-')))}</td>"
            "</tr>"
        )

    signal_rows = "".join(tr(row) for row in payload.get("top_signals", []))
    all_rows = "".join(tr(row) for row in payload.get("signals", [])[:80])
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>天天樂終極獨隻軌跡稽核</title>
<style>
body{{margin:0;background:#f6f7fb;color:#172033;font-family:"Microsoft JhengHei","Noto Sans TC",Arial,sans-serif;line-height:1.55}}
header{{background:#111827;color:#fff;padding:24px 18px}}
main{{max-width:1180px;margin:0 auto;padding:18px}}
.hero{{font-size:52px;font-weight:900;color:#facc15}}
.band{{background:#fff;border:1px solid #dce3ee;border-radius:8px;margin:14px 0;padding:16px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{border-top:1px solid #e5e7eb;padding:8px;text-align:left;vertical-align:top}}
th{{background:#f8fafc}}
.ok{{color:#047857;font-weight:900}}.warn{{color:#b45309;font-weight:900}}
</style>
</head>
<body>
<header>
  <h1>天天樂終極獨隻軌跡稽核</h1>
  <div class="hero">{fmt_number(payload.get('selected_number'))}</div>
  <p>目標期：{html.escape(str(payload.get('target_draw_date')))} / 台灣時間 {html.escape(str(payload.get('target_taiwan_time')))}</p>
</header>
<main>
  <section class="band">
    <h2>結論</h2>
    <p><strong class="ok">本期必算獨隻：{fmt_number(payload.get('selected_number'))}</strong></p>
    <p>上一期是否同為獨隻：{html.escape('是' if (payload.get('previous_prediction') or {}).get('same_as_previous_top1') else '否')}；本期仍保留原因：已用最新開獎、全歷史、拖牌、日期與走步回測重新計算，不是複製上期。</p>
    <p>真實回測達 90%：<strong class="warn">{html.escape('已達' if (payload.get('truth_guard') or {}).get('meets_90') else '未達，禁止偽裝')}</strong>。系統會每天輸出獨隻，但回測未達 90% 不准寫成 90%。</p>
  </section>
  <section class="band">
    <h2>最強通過訊號</h2>
    <table><thead><tr><th>類別</th><th>訊號</th><th>命中</th><th>命中率</th><th>優勢倍數</th><th>判定</th><th>說明</th></tr></thead><tbody>{signal_rows}</tbody></table>
  </section>
  <section class="band">
    <h2>全部軌跡與規律檢查</h2>
    <table><thead><tr><th>類別</th><th>訊號</th><th>命中</th><th>命中率</th><th>優勢倍數</th><th>判定</th><th>說明</th></tr></thead><tbody>{all_rows}</tbody></table>
  </section>
</main>
</body>
</html>"""


def mine() -> dict[str, Any]:
    analysis = load_json(ANALYSIS_PATH)
    number = selected_number(analysis)
    if not number:
        raise RuntimeError("找不到本期獨隻")
    draws = extract_draws()
    latest = analysis.get("latest_draw") or {}
    latest_numbers = [safe_int(value) for value in latest.get("numbers") or []]
    target_date = str(analysis.get("target_draw_date") or "")
    target_time = str(analysis.get("prediction_draw_taiwan_time") or "")
    candidate = find_candidate(analysis, number)
    model_backtest = (
        (candidate.get("ultimate_super_single") or {}).get("model_backtest")
        or (analysis.get("ultimate_super_single_engine") or {}).get("selected_model_backtest")
        or {}
    )

    signals = []
    signals.extend(transition_single_signal(draws, latest_numbers, number))
    signals.extend(transition_pair_signal(draws, latest_numbers, number))
    signals.extend(delta_formula_signal(draws, latest_numbers, number))
    signals.extend(date_signals(draws, number, target_date))
    signals.extend(recent_signals(draws, number))
    if draws:
        signals.append(omission_signal(draws, number))
    signals = sorted(signals, key=lambda row: (row.get("passed", False), row.get("lift", 0), row.get("samples", 0)), reverse=True)
    passed_signals = [row for row in signals if row.get("passed")]
    backtest_rate = safe_float(model_backtest.get("hit_rate"))
    truth_guard = {
        "model_backtest_rounds": safe_int(model_backtest.get("rounds")),
        "model_backtest_hits": safe_int(model_backtest.get("hit_count")),
        "model_backtest_rate": round(backtest_rate, 6),
        "baseline_rate": round(BASELINE, 6),
        "backtest_lift": round(backtest_rate / BASELINE, 4) if BASELINE else 0,
        "meets_90": backtest_rate >= 0.90,
        "policy": "每日必算一顆獨隻；未有真實回測90%以上，不准標示90%以上準確。",
    }
    previous = previous_prediction_info(target_date, number)
    repeated_ok = bool(
        previous.get("same_as_previous_top1")
        and number not in latest_numbers
        and safe_int(candidate.get("rank"), 99) == 1
        and len(passed_signals) >= 3
    )
    payload = {
        "version": "super_single_pattern_miner_v20261007",
        "created_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        "selected_number": number,
        "latest_draw_date": latest.get("draw_date"),
        "latest_numbers": latest_numbers,
        "target_draw_date": target_date,
        "target_taiwan_time": target_time,
        "history_count": len(draws),
        "previous_prediction": previous,
        "same_single_reuse_validation": {
            "same_as_previous_top1": bool(previous.get("same_as_previous_top1")),
            "passed": repeated_ok or not previous.get("same_as_previous_top1"),
            "rule": "若與上期獨隻相同，必須最新開獎未含該號、當期重算仍為第一、至少三項軌跡訊號通過。",
        },
        "truth_guard": truth_guard,
        "passed_signal_count": len(passed_signals),
        "top_signals": signals[:12],
        "signals": signals,
    }

    analysis["super_single_pattern_mining"] = payload
    decision = analysis.setdefault("super_single_decision", {})
    decision["pattern_mining"] = {
        "passed_signal_count": len(passed_signals),
        "same_single_reuse_validation": payload["same_single_reuse_validation"],
        "truth_guard": truth_guard,
        "top_signals": signals[:5],
    }
    explanation = decision.setdefault("explanation", [])
    if not isinstance(explanation, list):
        explanation = []
        decision["explanation"] = explanation
    for row in signals[:5]:
        text = f"{row['kind']}：{row['name']}，命中率 {pct(row['rate'])}，優勢 {row['lift']} 倍"
        if text not in explanation:
            explanation.append(text)
    candidate["pattern_mining"] = decision["pattern_mining"]
    for collection_name in ["official_candidates", "candidates"]:
        collection = analysis.get(collection_name) or []
        for idx, item in enumerate(collection):
            if isinstance(item, dict) and safe_int(item.get("number")) == number:
                collection[idx] = {**item, "pattern_mining": decision["pattern_mining"]}
                break
    write_json_all(analysis)

    report = build_report(payload)
    for path in [
        REPORTS / "latest_super_single_pattern_audit.html",
        REPORTS / "終極獨隻軌跡稽核.html",
        SITE / "reports" / "latest_super_single_pattern_audit.html",
        SITE / "reports" / "終極獨隻軌跡稽核.html",
        SITE / "latest_super_single_pattern_audit.html",
        SITE / "終極獨隻軌跡稽核.html",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
    return {
        "selected_number": number,
        "latest_draw_date": latest.get("draw_date"),
        "target_draw_date": target_date,
        "passed_signal_count": len(passed_signals),
        "top_signal": signals[0] if signals else {},
        "truth_guard": truth_guard,
    }


if __name__ == "__main__":
    print(json.dumps(mine(), ensure_ascii=False, indent=2))
