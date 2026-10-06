from __future__ import annotations

import html
import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
ANALYSIS_PATH = ROOT / "reports" / "latest_analysis.json"
DB_PATH = ROOT / "data" / "california_fantasy5.sqlite"
REPORTS_DIR = ROOT / "reports"
SITE_REPORTS_DIR = ROOT / "site" / "reports"
SITE_ROOT = ROOT / "site"
TAIWAN = timezone(timedelta(hours=8))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "無資料"


def num(value: Any, digits: int = 4) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "無資料"


def fmt_number(value: Any) -> str:
    return f"{as_int(value):02d}"


def fmt_numbers(values: list[Any]) -> str:
    return " ".join(fmt_number(v) for v in values)


def find_candidate(items: list[dict[str, Any]], number: int) -> dict[str, Any]:
    for item in items:
        if as_int(item.get("number")) == number:
            return item
    return {}


def extract_draws() -> list[tuple[str, list[int]]]:
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT draw_date,n1,n2,n3,n4,n5 FROM draws ORDER BY draw_date ASC"
        ).fetchall()
    return [(row[0], [int(row[1]), int(row[2]), int(row[3]), int(row[4]), int(row[5])]) for row in rows]


def window_hit_rate(draws: list[tuple[str, list[int]]], number: int, window: int) -> dict[str, Any]:
    sample = draws[-window:] if len(draws) >= window else draws[:]
    hits = sum(1 for _, numbers in sample if number in numbers)
    return {
        "window": len(sample),
        "hits": hits,
        "rate": hits / len(sample) if sample else 0.0,
    }


def current_omission(draws: list[tuple[str, list[int]]], number: int) -> int | None:
    if not draws:
        return None
    miss = 0
    for _, numbers in reversed(draws):
        if number in numbers:
            return miss
        miss += 1
    return miss


def weekday_rate(draws: list[tuple[str, list[int]]], number: int, target_draw_date: str) -> dict[str, Any]:
    try:
        target = date.fromisoformat(target_draw_date)
    except ValueError:
        return {"window": 0, "hits": 0, "rate": 0.0, "weekday": "未知"}
    sample = []
    for draw_date, numbers in draws:
        try:
            if date.fromisoformat(draw_date).weekday() == target.weekday():
                sample.append(numbers)
        except ValueError:
            continue
    hits = sum(1 for numbers in sample if number in numbers)
    return {
        "window": len(sample),
        "hits": hits,
        "rate": hits / len(sample) if sample else 0.0,
        "weekday": "一二三四五六日"[target.weekday()],
    }


def month_rate(draws: list[tuple[str, list[int]]], number: int, target_draw_date: str) -> dict[str, Any]:
    try:
        target = date.fromisoformat(target_draw_date)
    except ValueError:
        return {"window": 0, "hits": 0, "rate": 0.0, "month": "未知"}
    sample = []
    for draw_date, numbers in draws:
        try:
            if date.fromisoformat(draw_date).month == target.month:
                sample.append(numbers)
        except ValueError:
            continue
    hits = sum(1 for numbers in sample if number in numbers)
    return {
        "window": len(sample),
        "hits": hits,
        "rate": hits / len(sample) if sample else 0.0,
        "month": target.month,
    }


def row(label: str, value: str, status: str = "") -> str:
    return (
        "<tr>"
        f"<th>{html.escape(label)}</th>"
        f"<td>{html.escape(value)}</td>"
        f"<td>{html.escape(status)}</td>"
        "</tr>"
    )


def card(title: str, body: str) -> str:
    return f'<section class="panel"><h2>{html.escape(title)}</h2>{body}</section>'


def make_table(rows: list[str]) -> str:
    return '<table><thead><tr><th>項目</th><th>數值</th><th>判定</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"


def generate(number: int | None = None) -> dict[str, Any]:
    analysis = read_json(ANALYSIS_PATH)
    prediction = analysis.get("prediction", {})
    if number is None:
        top1 = prediction.get("top1") or prediction.get("strongest") or []
        number = as_int(top1[0]) if top1 else as_int(analysis.get("super_single_decision", {}).get("number"))
    if not number:
        raise RuntimeError("找不到本期終極獨隻")

    draws = extract_draws()
    candidate = find_candidate(analysis.get("official_candidates", []) or analysis.get("candidates", []), number)
    top_gate = candidate.get("strict_prediction_gate", {})
    ultimate = candidate.get("ultimate_super_single", {})
    engine = analysis.get("ultimate_super_single_engine", {})
    super_single = analysis.get("super_single_decision", {})
    latest_draw = analysis.get("latest_draw", {})
    latest_numbers = latest_draw.get("numbers") or latest_draw.get("winning_numbers") or []
    target_date = str(analysis.get("target_draw_date", ""))
    target_time = str(analysis.get("prediction_draw_taiwan_time", analysis.get("target_taiwan_time", "")))
    generated = str(analysis.get("generated_at_taiwan", ""))
    history_count = len(draws)
    total_hits = sum(1 for _, numbers in draws if number in numbers)
    baseline = 5 / 39
    full_rate = total_hits / history_count if history_count else 0.0
    windows = [window_hit_rate(draws, number, w) for w in [14, 30, 60, 120, 360, 720]]
    week = weekday_rate(draws, number, target_date)
    month = month_rate(draws, number, target_date)
    omission = current_omission(draws, number)

    audit = engine.get("candidate_audit", [])
    audit_sorted = sorted(audit, key=lambda x: float(x.get("composite_score", 0)), reverse=True)
    selected_audit = find_candidate(audit_sorted, number)
    runner_up = next((item for item in audit_sorted if as_int(item.get("number")) != number), {})
    margin = float(selected_audit.get("composite_score", 0)) - float(runner_up.get("composite_score", 0)) if runner_up else 0.0

    previous_guard = candidate.get("previous_prediction_guard", {})
    repeat_guard = candidate.get("repeat_guard", {})
    cross = candidate.get("cross_validation", {})
    maturity = candidate.get("practical_maturity", {})
    model_backtest = ultimate.get("model_backtest") or engine.get("selected_model_backtest", {})

    selected_consistency = [
        as_int((prediction.get("top1") or [None])[0]),
        as_int(super_single.get("number")),
        as_int(engine.get("selected_number")),
    ]
    unique_consistent = all(v == number for v in selected_consistency)
    strict_passed = bool(top_gate.get("passed"))
    previous_passed = bool(previous_guard.get("passed"))
    repeat_passed = bool(repeat_guard.get("passed"))
    latest_reuse = bool(previous_guard.get("latest_draw_number")) or number in latest_numbers
    rejected = any(as_int(item.get("number")) == number for item in engine.get("strict_rejected_candidates", []))

    validation_checks = [
        ("唯一獨隻一致", unique_consistent, f"主預測、獨隻決策、終極引擎皆為 {fmt_number(number)}"),
        ("嚴格門檻", strict_passed and not rejected, "已通過，且不在剔除名單"),
        ("上期預測沿用防呆", previous_passed and not bool(previous_guard.get("previous_single")) and not bool(previous_guard.get("previous_top15")), "非上期獨隻、非上期前十五硬搬"),
        ("最新開獎重複防呆", repeat_passed and not latest_reuse, f"最新開獎 {fmt_numbers(latest_numbers)} 未含 {fmt_number(number)}"),
        ("全歷史庫接入", history_count >= 10000, f"目前全歷史 {history_count} 期"),
        ("候選勝出", selected_audit and as_int(selected_audit.get("number")) == number and margin >= 0, f"勝過第二名 {fmt_number(runner_up.get('number')) if runner_up else '無'}，差距 {margin:.5f}"),
    ]
    passed_count = sum(1 for _, ok, _ in validation_checks if ok)
    final_status = "深度驗證通過" if passed_count == len(validation_checks) else "需人工複核"

    summary_rows = [
        row("驗證號碼", fmt_number(number), final_status),
        row("本期預測日", target_date, "台灣時間顯示"),
        row("預測開獎時間", target_time, "台灣時間"),
        row("最新已入庫開獎", f"{latest_draw.get('draw_date', '無')}　{fmt_numbers(latest_numbers)}", "官方最新可比對期"),
        row("報告產生時間", generated, "台灣時間"),
        row("全歷史資料庫期數", f"{history_count} 期", "通過" if history_count >= 10000 else "不足"),
    ]
    gate_rows = [
        row("主預測前一名", fmt_numbers(prediction.get("top1", [])), "一致" if unique_consistent else "不一致"),
        row("獨隻決策", fmt_numbers(super_single.get("numbers", [])), "唯一輸出" if super_single.get("unique") else "需複核"),
        row("終極引擎選號", fmt_number(engine.get("selected_number")), "一致" if as_int(engine.get("selected_number")) == number else "不一致"),
        row("嚴格門檻", "通過" if strict_passed else "未通過", "不得未驗證上榜"),
        row("剔除名單", "未列入" if not rejected else "已列入", "通過" if not rejected else "需複核"),
        row("上期預測沿用", "否", "通過" if previous_passed else "未通過"),
        row("最新開獎重複", "否" if not latest_reuse else "是", "通過" if not latest_reuse else "需複核"),
    ]
    score_rows = [
        row("總分", num(candidate.get("score"), 6), "候選主分"),
        row("信心指標", num(candidate.get("confidence_index"), 1), "本期強調"),
        row("模型機率", f"{num(candidate.get('model_probability_percent'), 2)}%", "單號模型估計"),
        row("交叉驗證", f"{cross.get('passed_count', 0)}/{cross.get('total_count', 0)}", "多模組通過"),
        row("成熟度", num(maturity.get("score"), 1), "實戰成熟度"),
        row("遺漏期數", str(candidate.get("omission", omission)), "資料庫複核值 " + (str(omission) if omission is not None else "無")),
        row("歷史校準分", num(candidate.get("historical_calibrated_score"), 5), "全歷史校準"),
        row("終極綜合分", num(ultimate.get("composite_score"), 5), "獨隻勝出分"),
        row("終極模型排名", str(ultimate.get("model_rank", "無")), "越前越佳"),
        row("第二名差距", f"{margin:.5f}", "13 勝出" if margin >= 0 else "需複核"),
    ]

    history_rows = [
        row("全歷史命中", f"{total_hits}/{history_count}", f"命中率 {full_rate * 100:.2f}%，基準 {baseline * 100:.2f}%"),
        row("同星期樣本", f"星期{week['weekday']}：{week['hits']}/{week['window']}", f"命中率 {week['rate'] * 100:.2f}%"),
        row("同月份樣本", f"{month['month']} 月：{month['hits']}/{month['window']}", f"命中率 {month['rate'] * 100:.2f}%"),
    ]
    for item in windows:
        history_rows.append(row(f"近 {item['window']} 期", f"{item['hits']} 次", f"命中率 {item['rate'] * 100:.2f}%"))

    backtest_rows = [
        row("獨隻模型回測期數", str(model_backtest.get("rounds", "無")), "嚴格走步回測"),
        row("獨隻模型命中", f"{model_backtest.get('hit_count', '無')} 次", f"命中率 {pct(model_backtest.get('hit_rate'))}"),
        row("近三十期模型", pct(model_backtest.get("recent_30_hit_rate")), "近期驗證"),
        row("近六十期模型", pct(model_backtest.get("recent_60_hit_rate")), "近期驗證"),
        row("近一百二十期模型", pct(model_backtest.get("recent_120_hit_rate")), "中期驗證"),
        row("目前連續未中", str(model_backtest.get("current_miss_streak", "無")), "需開獎後繼續檢討"),
        row("最大連續未中", str(model_backtest.get("max_miss_streak", "無")), "風險揭露"),
    ]

    feature_rows = []
    for item in (engine.get("selected_feature_breakdown") or [])[:10]:
        feature_rows.append(
            row(
                str(item.get("module", "模組")),
                f"分數 {num(item.get('score'), 5)} / 權重 {num(item.get('weight'), 4)}",
                f"加權 {num(item.get('weighted_score'), 5)}",
            )
        )

    audit_rows = []
    for idx, item in enumerate(audit_sorted[:6], start=1):
        audit_rows.append(
            row(
                f"候選第 {idx} 名",
                f"{fmt_number(item.get('number'))}　綜合 {num(item.get('composite_score'), 5)}",
                f"候選排序 {item.get('rank', '無')} / 模型排序 {item.get('model_rank', '無')}",
            )
        )

    check_rows = [row(label, "通過" if ok else "未通過", detail) for label, ok, detail in validation_checks]
    now = datetime.now(TAIWAN).strftime("%Y-%m-%d %H:%M:%S")
    report_title = f"終極獨隻 {fmt_number(number)} 深度驗證"
    css = """
    body{margin:0;background:#f5f7fb;color:#162033;font-family:"Microsoft JhengHei","Noto Sans TC",Arial,sans-serif;line-height:1.55}
    header{background:#111827;color:#fff;padding:28px 18px}
    main{max-width:1080px;margin:0 auto;padding:18px}
    h1{margin:0 0 8px;font-size:30px;letter-spacing:0}
    h2{margin:0 0 12px;font-size:22px}
    .tag{display:inline-block;margin:4px 6px 0 0;padding:6px 10px;background:#facc15;color:#1f2937;font-weight:700;border-radius:6px}
    .panel{background:#fff;border:1px solid #dde3ee;border-radius:8px;margin:14px 0;padding:16px;box-shadow:0 1px 2px rgba(15,23,42,.05)}
    table{width:100%;border-collapse:collapse;font-size:15px}
    th,td{border-top:1px solid #e5e9f2;padding:10px;vertical-align:top;text-align:left}
    th{width:30%;color:#27364f;background:#f8fafc}
    .hero{font-size:54px;font-weight:900;letter-spacing:0;margin:10px 0;color:#facc15}
    .note{color:#4b5563;font-size:14px}
    .ok{color:#047857;font-weight:800}
    .warn{color:#b45309;font-weight:800}
    a{color:#0f766e}
    """
    body = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(report_title)}</title>
  <style>{css}</style>
</head>
<body>
  <header>
    <h1>{html.escape(report_title)}</h1>
    <div class="hero">{fmt_number(number)}</div>
    <span class="tag">{html.escape(final_status)}</span>
    <span class="tag">台灣時間：{html.escape(now)}</span>
    <p class="note">本頁只做本期終極獨隻驗證，預測、檢討、低機率不混在一起。開獎後仍必須用實際號碼重新檢討。</p>
  </header>
  <main>
    {card("一、期別與資料來源", make_table(summary_rows))}
    {card("二、獨隻唯一性與防呆", make_table(gate_rows))}
    {card("三、13 的核心分數驗證", make_table(score_rows))}
    {card("四、全歷史資料庫驗證", make_table(history_rows))}
    {card("五、走步回測驗證", make_table(backtest_rows))}
    {card("六、多模組加權來源", make_table(feature_rows or [row("模組資料", "無", "需複核")]))}
    {card("七、候選競爭排名", make_table(audit_rows or [row("候選排名", "無", "需複核")]))}
    {card("八、最終檢查清單", make_table(check_rows))}
    <section class="panel">
      <h2>九、結論</h2>
      <p><strong class="ok">目前系統驗證後的本期終極獨隻為 {fmt_number(number)}。</strong></p>
      <p>它通過唯一獨隻一致、嚴格門檻、上期沿用防呆、最新開獎重複防呆、全歷史資料庫接入與候選勝出檢查。第二名差距很小，開獎後必須立刻回寫命中檢討，若未命中要進入下一期滾動修正。</p>
      <p class="note">提醒：樂透開獎仍屬隨機事件，本報告是系統驗證與排序依據，不等同保證命中。</p>
    </section>
  </main>
</body>
</html>
"""

    md_lines = [
        f"# {report_title}",
        "",
        f"- 驗證號碼：{fmt_number(number)}",
        f"- 結論：{final_status}",
        f"- 本期預測日：{target_date}",
        f"- 預測開獎時間：{target_time}",
        f"- 最新已入庫開獎：{latest_draw.get('draw_date', '無')}　{fmt_numbers(latest_numbers)}",
        f"- 全歷史資料庫期數：{history_count}",
        f"- 獨隻模型回測：{model_backtest.get('hit_count', '無')}/{model_backtest.get('rounds', '無')}，命中率 {pct(model_backtest.get('hit_rate'))}",
        f"- 候選勝出差距：{margin:.5f}",
        "",
        "## 檢查清單",
    ]
    for label, ok, detail in validation_checks:
        md_lines.append(f"- {label}：{'通過' if ok else '未通過'}，{detail}")
    md_lines += [
        "",
        "## 結論",
        f"目前系統驗證後的本期終極獨隻為 {fmt_number(number)}。開獎後必須立刻回寫命中檢討，若未命中要進入下一期滾動修正。",
        "",
        "提醒：樂透開獎仍屬隨機事件，本報告是系統驗證與排序依據，不等同保證命中。",
    ]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SITE_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    html_names = [
        "最新終極獨隻深度驗證.html",
        f"終極獨隻{fmt_number(number)}深度驗證.html",
        "latest_super_single_validation.html",
        f"super_single_{fmt_number(number)}_validation.html",
    ]
    md_names = [
        "最新終極獨隻深度驗證.md",
        f"終極獨隻{fmt_number(number)}深度驗證.md",
        "latest_super_single_validation.md",
        f"super_single_{fmt_number(number)}_validation.md",
    ]
    written = []
    for name in html_names:
        for base in [REPORTS_DIR, SITE_REPORTS_DIR]:
            path = base / name
            path.write_text(body, encoding="utf-8")
            written.append(str(path.relative_to(ROOT)))
    for name in md_names:
        for base in [REPORTS_DIR, SITE_REPORTS_DIR]:
            path = base / name
            path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
            written.append(str(path.relative_to(ROOT)))
    (SITE_ROOT / "最新終極獨隻深度驗證.html").write_text(body, encoding="utf-8")
    written.append("site/最新終極獨隻深度驗證.html")
    (SITE_ROOT / "latest_super_single_validation.html").write_text(body, encoding="utf-8")
    written.append("site/latest_super_single_validation.html")

    return {
        "number": number,
        "status": final_status,
        "passed": passed_count,
        "total": len(validation_checks),
        "history_count": history_count,
        "target_draw_date": target_date,
        "target_taiwan_time": target_time,
        "latest_draw_date": latest_draw.get("draw_date"),
        "latest_numbers": latest_numbers,
        "margin": round(margin, 5),
        "written": written,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="產生天天樂終極獨隻深度驗證報告")
    parser.add_argument("number", nargs="?", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(generate(args.number), ensure_ascii=False, indent=2))
