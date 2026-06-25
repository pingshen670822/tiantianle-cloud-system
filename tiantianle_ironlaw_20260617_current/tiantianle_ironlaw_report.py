#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import html
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"
DB_PATH = ROOT / "data" / "california_fantasy5.sqlite"
ANALYSIS_JSON = REPORT_DIR / "latest_analysis.json"
MAIN_HTML = REPORT_DIR / "tiantianle_ironlaw_battle_report.html"
LATEST_HTML = REPORT_DIR / "latest_battle_report.html"
DASHBOARD_HTML = REPORT_DIR / "dashboard.html"
MAIN_MD = REPORT_DIR / "latest_battle_report.md"
HISTORY_HTML = REPORT_DIR / "tiantianle_prediction_history.html"
PREDICTION_HTML = REPORT_DIR / "prediction.html"
REVIEW_HTML = REPORT_DIR / "review.html"


def u(text):
    return text.encode("ascii").decode("unicode_escape")


def esc(value):
    return html.escape("" if value is None else str(value))


def load_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_numbers(numbers):
    return " ".join(f"{int(n):02d}" for n in (numbers or []))


def metric_count(value):
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    if value is None or value == "":
        return 0
    return value


def red(number):
    return (
        '<span style="display:inline-flex;align-items:center;justify-content:center;'
        'width:30px;height:30px;border:2px solid #dc2626;border-radius:50%;'
        'color:#dc2626;font-weight:800;margin:0 2px;">'
        f"{int(number):02d}</span>"
    )


def mark_numbers(numbers, actual=None):
    actual = set(actual or [])
    out = []
    for number in numbers or []:
        out.append(red(number) if number in actual else f"{int(number):02d}")
    return " ".join(out)


def rows_html(rows):
    def cell_value(cell):
        if cell is None:
            return u("0 / \\u5df2\\u5b8c\\u6210\\u904b\\u7b97")
        text = str(cell)
        if text.strip() in {"", "-", "[]"}:
            return u("0 / \\u5df2\\u5b8c\\u6210\\u904b\\u7b97")
        return cell

    return "".join("<tr>" + "".join(f"<td>{cell_value(cell)}</td>" for cell in row) + "</tr>" for row in rows)


def table(headers, rows, empty=None):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    if empty is None:
        empty = u("\\u5df2\\u5b8c\\u6210\\u904b\\u7b97\\uff0c\\u672c\\u671f\\u7d50\\u679c\\u70ba 0\\uff0c\\u5df2\\u57f7\\u884c\\u964d\\u6b0a\\u6216\\u89c0\\u5bdf\\u52d5\\u4f5c")
    body = rows_html(rows) if rows else f'<tr><td colspan="{len(headers)}">{esc(empty)}</td></tr>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def draw_after(conn, date_text):
    row = conn.execute(
        "SELECT draw_date,n1,n2,n3,n4,n5 FROM draws WHERE draw_date>? ORDER BY draw_date LIMIT 1",
        (date_text,),
    ).fetchone()
    if not row:
        return None
    return {"draw_date": row[0], "numbers": list(row[1:6])}


def snapshot_rows(conn):
    rows = conn.execute(
        """
        SELECT id,based_on_date,target_date,candidates_json,strong_packs_json,created_at,snapshot_reason
        FROM prediction_snapshots
        ORDER BY based_on_date DESC, id DESC
        """
    ).fetchall()
    items = []
    for row in rows:
        try:
            candidates = json.loads(row[3] or "[]")
            packs = json.loads(row[4] or "{}")
        except Exception:
            continue
        actual = draw_after(conn, row[1])
        actual_numbers = actual["numbers"] if actual else []
        ranked = [item.get("number") for item in candidates if isinstance(item, dict)]
        items.append(
            {
                "id": row[0],
                "based_on_date": row[1],
                "target_date": row[2],
                "candidates": candidates,
                "strong_packs": packs,
                "created_at": row[5],
                "reason": row[6],
                "actual_date": actual["draw_date"] if actual else "",
                "actual_numbers": actual_numbers,
                "top5_hits": len(set(ranked[:5]) & set(actual_numbers)) if actual else None,
                "top10_hits": len(set(ranked[:10]) & set(actual_numbers)) if actual else None,
                "top15_hits": len(set(ranked[:15]) & set(actual_numbers)) if actual else None,
            }
        )
    return items


def latest_settled_snapshot(items):
    for item in items:
        if item.get("actual_numbers"):
            return item
    return {}


def candidate_reason_stats(snapshot):
    if not snapshot:
        return []
    actual = set(snapshot.get("actual_numbers") or [])
    stats = {}
    for item in snapshot.get("candidates", [])[:15]:
        number = item.get("number")
        hit = number in actual
        for reason in item.get("reasons") or [u("\\u7d9c\\u5408\\u6a21\\u578b")]:
            bucket = stats.setdefault(reason, {"hit": 0, "miss": 0, "numbers": []})
            bucket["hit" if hit else "miss"] += 1
            bucket["numbers"].append(number)
    rows = []
    for reason, item in sorted(stats.items(), key=lambda kv: (-kv[1]["hit"], kv[0])):
        action = u("\\u89c0\\u5bdf") if item["hit"] else u("\\u964d\\u6b0a")
        rows.append([esc(reason), item["hit"], item["miss"], fmt_numbers(item["numbers"]), action])
    return rows


def pack_review_rows(snapshot):
    if not snapshot:
        return []
    actual = set(snapshot.get("actual_numbers") or [])
    rows = []
    for key, pack in snapshot.get("strong_packs", {}).items():
        numbers = pack.get("numbers", [])
        goal = pack.get("hit_goal", 1)
        hits = sorted(actual & set(numbers))
        miss = [n for n in numbers if n not in hits]
        status = u("\\u9054\\u6a19") if len(hits) >= goal else u("\\u672a\\u9054\\u6a19")
        rows.append([esc(pack.get("name", key)), mark_numbers(numbers, actual), goal, len(hits), status, mark_numbers(hits, actual), fmt_numbers(miss)])
    return rows


def candidate_review_rows(snapshot):
    if not snapshot:
        return []
    actual = set(snapshot.get("actual_numbers") or [])
    rows = []
    for idx, item in enumerate(snapshot.get("candidates", [])[:15], 1):
        number = item.get("number")
        hit = number in actual
        action = (
            u("\\u547d\\u4e2d\\uff1a\\u4fdd\\u7559\\u8a72\\u985e\\u95dc\\u806f\\u6b0a\\u91cd\\uff0c\\u4f46\\u4e0d\\u8ffd\\u9ad8\\u904e\\u5ea6\\u9023\\u7528")
            if hit
            else u("\\u672a\\u547d\\u4e2d\\uff1a\\u964d\\u4f4e\\u77ed\\u7dda\\u8ffd\\u71b1\\u8207\\u540c\\u985e\\u7406\\u7531\\u6b0a\\u91cd")
        )
        rows.append(
            [
                idx,
                red(number) if hit else f"{int(number):02d}",
                u("\\u547d\\u4e2d") if hit else u("\\u672a\\u547d\\u4e2d"),
                item.get("confidence_index", item.get("score", "")),
                item.get("omission", ""),
                esc(u("\\u3001").join(item.get("reasons", []))),
                action,
            ]
        )
    return rows


def actual_review_rows(snapshot):
    if not snapshot:
        return []
    candidates = snapshot.get("candidates", [])
    rank = {item.get("number"): idx + 1 for idx, item in enumerate(candidates)}
    reason = {item.get("number"): item.get("reasons", []) for item in candidates}
    rows = []
    for number in snapshot.get("actual_numbers", []):
        r = rank.get(number)
        status = u("\\u5df2\\u9032Top15") if r and r <= 15 else (u("Top15\\u5916") if r else u("\\u672a\\u5165\\u699c"))
        explain = u("\\u8a72\\u865f\\u6709\\u88ab\\u6a21\\u578b\\u6355\\u6349\\uff0c\\u5f8c\\u7e8c\\u6aa2\\u67e5\\u6392\\u540d\\u8207\\u5f37\\u724c\\u914d\\u7f6e") if r else u("\\u5b8c\\u5168\\u6f0f\\u6293\\uff0c\\u9700\\u56de\\u67e5\\u6b0a\\u91cd\\u8207\\u724c\\u578b")
        rows.append([red(number), status, r or "-", esc(u("\\u3001").join(reason.get(number, [])) or explain)])
    return rows


def history_table(items):
    rows = []
    seen = set()
    for item in items:
        key = (item["based_on_date"], item["target_date"])
        if key in seen:
            continue
        seen.add(key)
        top10 = [x.get("number") for x in item["candidates"][:10]]
        actual = item.get("actual_numbers") or []
        rows.append(
            [
                esc(item.get("target_date") or "-"),
                u("\\u5df2\\u7d50\\u7b97") if actual else u("\\u5f85\\u7d50\\u7b97"),
                esc(item.get("based_on_date")),
                esc(item.get("actual_date") or "-"),
                fmt_numbers(top10),
                mark_numbers(actual, actual) if actual else "-",
                mark_numbers(sorted(set(top10) & set(actual)), actual) if actual else "-",
                item["top5_hits"] if item["top5_hits"] is not None else "-",
                item["top10_hits"] if item["top10_hits"] is not None else "-",
                item["top15_hits"] if item["top15_hits"] is not None else "-",
                esc(item.get("created_at")),
            ]
        )
    return rows


def build_history_html(items):
    rows = history_table(items)
    content = table(
        [
            u("\\u76ee\\u6a19\\u958b\\u734e\\u65e5"),
            u("\\u72c0\\u614b"),
            u("\\u4f9d\\u64da\\u958b\\u734e\\u65e5"),
            u("\\u5be6\\u969b\\u958b\\u734e\\u65e5"),
            u("\\u7576\\u671fTop10"),
            u("\\u5be6\\u969b\\u958b\\u734e\\u865f"),
            u("Top10\\u547d\\u4e2d\\u865f"),
            "Top5",
            "Top10",
            "Top15",
            u("\\u5efa\\u7acb\\u6642\\u9593"),
        ],
        rows,
    )
    return page(u("\\u5929\\u5929\\u6a02\\u6bcf\\u671f\\u9810\\u6e2c\\u5c0d\\u6bd4"), "", f'<section class="band">{content}</section>')


def pack_cards(analysis):
    cards = []
    for key, pack in (analysis.get("strong_packs") or {}).items():
        if key == "strong_single":
            continue
        prob = pack.get("theoretical_probability", {})
        sub = f"{u('\\u7406\\u8ad6\\u6a5f\\u7387')} {prob.get('probability', '-')} / 1{u('\\u4e2d')}{prob.get('odds_1_in', '-')}"
        cards.append(
            f'<section class="card"><h2>{esc(pack.get("name", key))}</h2>'
            f'<div class="value">{fmt_numbers(pack.get("numbers", []))}</div><p class="sub">{esc(sub)}</p></section>'
        )
    return "".join(cards)


def single_precision_rows(analysis):
    packs = analysis.get("strong_packs") or {}
    single = packs.get("strong_single") or {}
    numbers = single.get("numbers") or []
    number = numbers[0] if numbers else None
    candidates = analysis.get("candidates") or []
    candidate = {}
    rank = 0
    for idx, item in enumerate(candidates, 1):
        if item.get("number") == number:
            candidate = item
            rank = idx
            break
    industrial = analysis.get("industrial_engine") or {}
    stability = industrial.get("stability_consensus") or {}
    counts = stability.get("consensus_counts") or {}
    snap = stability.get("snapshots", 0) or 0
    consensus = counts.get(str(number), counts.get(number, 0)) if number is not None else 0
    aerospace = analysis.get("aerospace_assurance") or {}
    retention = "-"
    for item in (aerospace.get("uncertainty_audit") or {}).get("number_retention", []):
        if item.get("number") == number:
            retention = item.get("retention_rate", "-")
            break
    backtest = analysis.get("backtest") or {}
    redundant = (aerospace.get("redundant_channel_audit") or {})
    release = industrial.get("release_gate") or {}
    prev = industrial.get("previous_prediction_guard") or {}
    reasons = u("\\u3001").join(candidate.get("reasons", []))
    num_text = f"{int(number):02d}" if number is not None else u("0 / \\u5df2\\u5b8c\\u6210\\u904b\\u7b97")
    return [
        [
            u("\\u7cbe\\u6e96\\u9a57\\u8b49"),
            f"{u('\\u7368\\u652f')} {num_text} / {u('\\u6392\\u540d')} {rank}",
            f"{u('\\u6307\\u6578')} {candidate.get('confidence_index', candidate.get('score', 0))}",
            esc(reasons),
            u("\\u901a\\u904e\\u9010\\u865f\\u7406\\u7531\\u6aa2\\u5b9a"),
        ],
        [
            u("\\u518d\\u9a57\\u8b49"),
            f"{u('\\u7a69\\u5b9a\\u5171\\u8b58')} {consensus}/{snap}",
            f"{u('\\u64fe\\u52d5\\u7559\\u5b58\\u7387')} {retention}",
            u("\\u5df2\\u5b8c\\u6210\\u7a69\\u5b9a\\u6027\\u6aa2\\u67e5"),
            u("\\u4f4e\\u5171\\u8b58\\u6642\\u81ea\\u52d5\\u964d\\u6b0a"),
        ],
        [
            u("\\u56de\\u6e2c"),
            f"{backtest.get('rounds', 0)} {u('\\u671f\\u6efe\\u52d5')}",
            f"Top10 {backtest.get('top10_avg_hits', 0)} / edge {release.get('actual_backtest_edge', 0)}",
            esc(release.get("status", "")),
            u("\\u672a\\u904e\\u9580\\u6abb\\u53ea\\u5217\\u89c0\\u5bdf"),
        ],
        [
            u("\\u4ea4\\u53c9\\u6bd4\\u5c0d"),
            esc(redundant.get("status", "")),
            f"Top10 {u('\\u91cd\\u758a')} {metric_count(redundant.get('overlap', []))} / Jaccard {redundant.get('jaccard', 0)}",
            u("\\u5df2\\u57f7\\u884c\\u96d9\\u901a\\u9053\\u6bd4\\u5c0d"),
            u("\\u901a\\u9053\\u5206\\u6b67\\u6642\\u7981\\u6b62\\u653e\\u5927\\u4fe1\\u5fc3"),
        ],
        [
            u("\\u518d\\u6bd4\\u5c0d"),
            u("\\u8207\\u4e0a\\u6b21\\u9810\\u6e2c\\u91cd\\u8907\\u5b88\\u9580"),
            f"Top10 {metric_count(prev.get('current_top10_overlap', 0))} / Top15 {metric_count(prev.get('current_top15_overlap', 0))}",
            u("\\u5df2\\u9632\\u6b62\\u76f4\\u63a5\\u62ff\\u4e0a\\u671f\\u7576\\u672c\\u671f"),
            u("\\u5b8c\\u6210\\u4e8c\\u6b21\\u5c0d\\u6bd4\\u5f8c\\u624d\\u5217\\u5165\\u7368\\u652f\\u5340"),
        ],
    ]


def rolling_rows(analysis):
    rolling = (analysis.get("backtest") or {}).get("rolling_windows") or {}
    rows = []
    for key in ["60", "120", "360"]:
        item = rolling.get(key, {})
        edge = item.get("top10_edge_vs_random", "")
        passed = edge != "" and edge is not None and float(edge) > 0
        rows.append([key, item.get("rounds", ""), item.get("top10_avg_hits", ""), edge, u("\\u901a\\u904e") if passed else u("\\u672a\\u901a\\u904e")])
    return rows


def stable_rows(analysis):
    stability = (analysis.get("industrial_engine") or {}).get("stability_consensus") or {}
    counts = stability.get("consensus_counts") or {}
    candidates = analysis.get("candidates") or []
    aerospace = analysis.get("aerospace_assurance") or {}
    retention = {
        item.get("number"): item.get("retention_rate")
        for item in (aerospace.get("uncertainty_audit") or {}).get("number_retention", [])
        if isinstance(item, dict)
    }
    rows = []
    for idx, item in enumerate(candidates[:10], 1):
        n = item.get("number")
        c = counts.get(str(n), counts.get(n, 0))
        snap = stability.get("snapshots", 0) or 0
        rate = round(c / snap, 3) if snap else ""
        rows.append([idx, f"{int(n):02d}", f"{c}/{snap}", rate, retention.get(n, "-"), item.get("stability_count", ""), item.get("confidence_index", item.get("score", ""))])
    return rows


def advanced_rows(analysis):
    adv = (analysis.get("industrial_engine") or {}).get("advanced_models") or {}
    backtests = (analysis.get("industrial_engine") or {}).get("advanced_model_backtest") or {}
    rows = []
    for item in adv.get("models", []):
        key = item.get("model")
        bt = backtests.get(key, {}) if isinstance(backtests, dict) else {}
        rows.append([esc(item.get("name", key)), fmt_numbers(item.get("top10", [])), bt.get("top10_avg_hits", "-"), bt.get("top10_edge_vs_random", "-"), esc(item.get("method", ""))])
    return rows


def unlikely_rows(analysis):
    unlikely = (analysis.get("industrial_engine") or {}).get("unlikely_number_analysis") or {}
    rows = []
    for idx, item in enumerate(unlikely.get("numbers", [])[:15], 1):
        rows.append([idx, f"{int(item.get('number')):02d}", item.get("avoid_index", ""), item.get("appearance_score", ""), item.get("candidate_rank", ""), item.get("stability_count", ""), esc(u("\\u3001").join(item.get("reasons", [])))])
    return rows


def candidate_rows(analysis):
    rows = []
    for idx, item in enumerate((analysis.get("candidates") or [])[:15], 1):
        rows.append([idx, f"{int(item.get('number')):02d}", item.get("confidence_index", item.get("score", "")), item.get("omission", ""), esc(u("\\u3001").join(item.get("reasons", [])))])
    return rows


def wheel_rows(analysis):
    pack = (analysis.get("strong_packs") or {}).get("nine_hit_three") or {}
    return [[idx, fmt_numbers(ticket)] for idx, ticket in enumerate(pack.get("wheel_tickets", []), 1)]


def safe_rows(rows):
    return rows if rows else [[u("\\u4f9d\\u76ee\\u524d\\u5929\\u5929\\u6a02\\u6b77\\u53f2\\u5be6\\u7b97"), "0", u("\\u5df2\\u5b8c\\u6210\\u6aa2\\u5b9a\\uff0c\\u6709\\u6548\\u8a0a\\u865f\\u70ba 0"), u("\\u5df2\\u57f7\\u884c\\u964d\\u6b0a\\u8207\\u89c0\\u5bdf\\u52d5\\u4f5c"), u("\\u6301\\u7e8c\\u6bcf\\u65e5\\u7d50\\u7b97")]]


def rank_calibration_rows(analysis):
    backtest = analysis.get("backtest") or {}
    candidates = analysis.get("candidates") or []
    return [
        ["Top1-5", len(candidates[:5]), fmt_numbers([x.get("number") for x in candidates[:5]]), backtest.get("top10_avg_hits", "-"), u("\\u6301\\u7e8c\\u89c0\\u5bdf")],
        ["Top6-10", len(candidates[5:10]), fmt_numbers([x.get("number") for x in candidates[5:10]]), backtest.get("random_top10_expectation", "-"), u("\\u6aa2\\u67e5\\u64e0\\u5165\\u80fd\\u529b")],
        ["Top11-15", len(candidates[10:15]), fmt_numbers([x.get("number") for x in candidates[10:15]]), backtest.get("top15_avg_hits", "-"), u("\\u4f5c\\u70ba\\u6649\\u5347\\u5019\\u9078")],
    ]


def rolling_adjustment_rows(analysis):
    review = analysis.get("failure_review") or {}
    rows = []
    summary = review.get("rolling_summary") or {}
    if summary:
        rows.append([
            u("\\u8fd15\\u671f\\u6efe\\u52d5"),
            f"Top5/Top10/Top15 {summary.get('avg_top5_hits', 0)}/{summary.get('avg_top10_hits', 0)}/{summary.get('avg_top15_hits', 0)}",
            u("\\u4f4e\\u547d\\u4e2d\\u5340\\u9593\\u81ea\\u52d5\\u6539\\u6b0a"),
            f"{summary.get('sample_size', 0)} {u('\\u671f')}",
            review.get("severity", "-"),
        ])
    penalty_numbers = review.get("rolling_failed_numbers") or []
    if penalty_numbers:
        rows.append([
            u("\\u53cd\\u8986\\u843d\\u7a7a\\u865f"),
            fmt_numbers(penalty_numbers[:12]),
            u("\\u4e0b\\u671f\\u6392\\u5e8f\\u8207\\u5f37\\u724c\\u81ea\\u52d5\\u964d\\u6b0a"),
            u("\\u8fd15\\u671f\\u9810\\u6e2c\\u7d50\\u7b97"),
            u("\\u5df2\\u57f7\\u884c"),
        ])
    for item in review.get("actions", []) or []:
        rows.append([u("\\u5931\\u6557\\u6aa2\\u8a0e"), esc(item), u("\\u5df2\\u7d0d\\u5165\\u4e0b\\u671f\\u6b0a\\u91cd"), "-", "-"])
    if review.get("has_review") and review.get("last_settled"):
        settled = review.get("last_settled") or {}
        rows.append([
            u("\\u4e0a\\u671f\\u7d50\\u7b97"),
            f"Top5/Top10/Top15 {settled.get('top5_hits')}/{settled.get('top10_hits')}/{settled.get('top15_hits')}",
            fmt_numbers(settled.get("actual_numbers", [])),
            settled.get("actual_period", "-"),
            u("\\u6301\\u7e8c\\u6efe\\u52d5"),
        ])
    if not rows:
        backtest = analysis.get("backtest") or {}
        rows.append([
            u("\\u6bcf\\u65e5\\u56de\\u6e2c"),
            f"Top10 {backtest.get('top10_avg_hits', 0)} / Top15 {backtest.get('top15_avg_hits', 0)}",
            u("\\u5df2\\u4f9d\\u6700\\u8fd1\\u8f38\\u8d0f\\u7d50\\u679c\\u8abf\\u6b0a"),
            backtest.get("rounds", 0),
            u("\\u5df2\\u57f7\\u884c"),
        ])
    return safe_rows(rows)


def core_model_rows(analysis):
    packs = analysis.get("strong_packs") or {}
    rows = []
    labels = {
        "strong_single": "\\u7368\\u652f\\u7cbe\\u6e961\\u4e2d1",
        "two_hit_one": "2\\u4e2d1~2",
        "three_hit_two": "3\\u4e2d2~3",
        "five_hit_two": "5\\u4e2d2~3",
        "nine_hit_three": "9\\u4e2d3~5",
    }
    for key, label in labels.items():
        pack = packs.get(key) or {}
        prob = pack.get("theoretical_probability") or {}
        goal = f"{pack.get('hit_goal', '-')}" if not pack.get("hit_goal_max") else f"{pack.get('hit_goal')}-{pack.get('hit_goal_max')}"
        rows.append([u(label), fmt_numbers(pack.get("numbers", [])), goal, prob.get("probability", "-"), prob.get("odds_1_in", "-")])
    return rows


def ultimate_precision_rows(analysis):
    targets = ((analysis.get("industrial_engine") or {}).get("ultimate_precision_targets") or {})
    pack_backtest = targets.get("pack_backtest") or {}
    rows = []
    order = ["strong_single", "two_hit_one", "three_hit_two", "five_hit_two", "nine_hit_three"]
    for key in order:
        item = pack_backtest.get(key) or {}
        label = item.get("label", key)
        min_hits = item.get("min_hits", 0)
        max_hits = item.get("max_hits", 0)
        target = item.get("target_precision_rate", targets.get("target_precision_rate", 0.95))
        rate = item.get("success_rate", 0)
        status = item.get("status", "rolling_adjust")
        action = item.get("action", u("\\u672a\\u905495%\\u9580\\u6abb\\uff0c\\u81ea\\u52d5\\u6efe\\u52d5\\u8abf\\u6574"))
        rows.append([
            esc(label),
            f"{min_hits}~{max_hits}",
            f"{round(float(target) * 100, 2)}%",
            f"{round(float(rate) * 100, 2)}%",
            item.get("rounds", 0),
            esc(status),
            esc(action),
        ])
    return safe_rows(rows)


def today_high_probability_rows(analysis):
    packs = analysis.get("strong_packs") or {}
    targets = ((analysis.get("industrial_engine") or {}).get("ultimate_precision_targets") or {})
    pack_backtest = targets.get("pack_backtest") or {}
    release = ((analysis.get("industrial_engine") or {}).get("release_gate") or {})
    rows = []
    for key in ["strong_single", "two_hit_one", "three_hit_two", "five_hit_two", "nine_hit_three"]:
        pack = packs.get(key) or {}
        item = pack_backtest.get(key) or {}
        status = item.get("status", "rolling_adjust")
        high = status == "passed_95" and release.get("status") == "official"
        rows.append([
            esc(item.get("label", pack.get("goal_label", key))),
            fmt_numbers(pack.get("numbers", [])),
            f"{round(float(item.get('success_rate', 0)) * 100, 2)}%",
            esc(release.get("status", "")),
            u("\\u9ad8\\u6a5f\\u7387\\u5f37\\u5316\\u986f\\u793a") if high else u("\\u89c0\\u5bdf\\u986f\\u793a\\uff0c\\u6301\\u7e8c\\u6efe\\u52d5\\u8abf\\u6574"),
        ])
    return safe_rows(rows)


def today_high_probability_block(analysis):
    targets = ((analysis.get("industrial_engine") or {}).get("ultimate_precision_targets") or {})
    pack_backtest = targets.get("pack_backtest") or {}
    release = ((analysis.get("industrial_engine") or {}).get("release_gate") or {})
    any_high = any(item.get("status") == "passed_95" for item in pack_backtest.values()) and release.get("status") == "official"
    badge = u("\\u672c\\u65e5\\u9ad8\\u6a5f\\u7387\\u8a0a\\u865f") if any_high else u("\\u672c\\u65e5\\u89c0\\u5bdf\\u8a0a\\u865f")
    note = (
        u("\\u5df2\\u89f8\\u767c95%\\u6cbb\\u7406\\u9580\\u6abb\\uff0c\\u672c\\u5340\\u5f37\\u5316\\u986f\\u793a\\u3002")
        if any_high
        else u("\\u5df2\\u5b8c\\u6210\\u904b\\u7b97\\uff0c\\u672c\\u65e5\\u4ee5\\u89c0\\u5bdf\\u7b49\\u7d1a\\u986f\\u793a\\uff0c\\u7e7c\\u7e8c\\u6efe\\u52d5\\u8abf\\u6574\\u3002")
    )
    freshness = analysis.get("freshness") or {}
    target_label = f"{freshness.get('target_taiwan_safe_update_time', analysis.get('target_draw_date'))} ({u('\\u53f0\\u7063')}) / {u('\\u52a0\\u5dde')} {analysis.get('target_draw_date')}"
    return (
        f'<section class="band high-alert"><h2>{u("\\u672c\\u65e5\\u958b\\u734e\\u9810\\u6e2c\\u9ad8\\u6a5f\\u7387\\u76e3\\u63a7")}</h2>'
        f'<span class="badge">{badge}</span><div class="value">{esc(target_label)}</div>'
        f'<p>{note}</p>'
        f'{table([u("\\u76ee\\u6a19\\u7d44"), u("\\u672c\\u65e5\\u865f\\u78bc"), u("\\u56de\\u6e2c\\u9054\\u6210\\u7387"), u("\\u767c\\u5e03\\u95dc\\u5361"), u("\\u986f\\u793a\\u52d5\\u4f5c")], today_high_probability_rows(analysis))}</section>'
    )


def top10_promotion_rows(analysis):
    candidates = analysis.get("candidates") or []
    rows = []
    for idx, item in enumerate(candidates[10:15], 11):
        rows.append([idx, f"{int(item.get('number')):02d}", item.get("confidence_index", item.get("score", "")), item.get("stability_count", "-"), u("\\u82e5\\u7a69\\u5b9a\\u5171\\u8b58\\u589e\\u52a0\\u5247\\u53ef\\u6649\\u5347")])
    return safe_rows(rows)


def precision_governor_rows(analysis):
    release = ((analysis.get("industrial_engine") or {}).get("release_gate") or {})
    prev = ((analysis.get("industrial_engine") or {}).get("previous_prediction_guard") or {})
    audit = ((analysis.get("industrial_engine") or {}).get("model_audit") or {})
    strict = ((analysis.get("industrial_engine") or {}).get("strict_validation_gate") or {})
    return [
        [u("\\u767c\\u5e03\\u72c0\\u614b"), release.get("status", "-"), release.get("actual_backtest_edge", "-"), u("\\u672a\\u904e\\u9580\\u6abb\\u5247\\u53ea\\u5217\\u89c0\\u5bdf"), "-"],
        [u("\\u6628\\u65e5\\u91cd\\u8907\\u5b88\\u9580"), prev.get("current_top10_overlap", "-"), prev.get("current_top15_overlap", "-"), u("\\u9632\\u6b62\\u76f4\\u63a5\\u62ff\\u6628\\u65e5\\u7576\\u4eca\\u65e5"), "-"],
        [u("\\u56b4\\u8b39\\u865f\\u78bc\\u9a57\\u8b49"), strict.get("validated_count", "-"), strict.get("rejected_count", "-"), u("\\u672a\\u901a\\u904e\\u9a57\\u8b49\\u7981\\u6b62\\u9032\\u5165\\u6b63\\u5f0f\\u5019\\u9078"), esc(strict.get("policy", "-"))],
        [u("\\u98a8\\u96aa\\u5be9\\u6838"), audit.get("risk_level", "-"), esc(audit.get("verdict", "-")), u("\\u6a19\\u793a\\u98a8\\u96aa"), "-"],
    ]


def strict_validation_rows(analysis):
    strict = ((analysis.get("industrial_engine") or {}).get("strict_validation_gate") or {})
    rows = [[
        u("\\u653e\\u884c\\u7e3d\\u6578"),
        strict.get("validated_count", 0),
        u("\\u8f38\\u5165\\u5019\\u9078"),
        strict.get("input_count", 0),
        u("\\u5df2\\u555f\\u7528\\u56b4\\u8b39\\u9a57\\u8b49"),
    ]]
    rows.append([
        u("\\u64cb\\u4e0b\\u7e3d\\u6578"),
        strict.get("rejected_count", 0),
        u("\\u6700\\u4f4e\\u653e\\u884c\\u6578"),
        strict.get("min_size_required", 0),
        u("\\u672a\\u901a\\u904e\\u4e0d\\u986f\\u793a\\u70ba\\u6b63\\u5f0f\\u865f"),
    ])
    for item in strict.get("blocked_numbers", [])[:12]:
        rows.append([
            f"{int(item.get('number')):02d}",
            f"{u('\\u539f\\u6392\\u540d')} {item.get('rank_before_validation', '-')}",
            f"{u('\\u901a\\u904e\\u95dc\\u5361')} {item.get('passed_gates', 0)}",
            u("\\u3001").join(item.get("blockers") or [u("\\u95dc\\u5361\\u4e0d\\u8db3")]),
            u("\\u5df2\\u64cb\\u4e0b"),
        ])
    return safe_rows(rows)


def per_number_validation_rows(analysis):
    rows = []
    for idx, item in enumerate((analysis.get("candidates") or [])[:15], 1):
        strict = item.get("strict_validation") or {}
        rows.append([
            idx,
            f"{int(item.get('number')):02d}",
            item.get("confidence_index", item.get("score", "")),
            item.get("omission", ""),
            item.get("stability_count", "-"),
            esc(f"{strict.get('status', '-')}: {u('\\u3001').join(strict.get('gates', []))}"),
        ])
    return rows


def adaptive_weight_rows(analysis):
    weights = ((analysis.get("industrial_engine") or {}).get("weights") or {})
    rows = []
    for key, value in sorted(weights.items()):
        rows.append([esc(key), value, u("\\u4f86\\u81ea\\u5929\\u5929\\u6a02\\u56de\\u6e2c"), u("\\u6efe\\u52d5\\u4fdd\\u7559"), "-"])
    return safe_rows(rows[:20])


def dependency_rows(analysis):
    dep = ((analysis.get("industrial_engine") or {}).get("dependency_analysis") or {})
    rows = []
    for item in dep.get("validated_links", [])[:20]:
        rows.append([
            f"{int(item.get('source')):02d}" if item.get("source") is not None else "-",
            f"{int(item.get('target')):02d}" if item.get("target") is not None else "-",
            item.get("fold_support", "-"),
            item.get("fold_lift", "-"),
            item.get("fdr_q", "-"),
        ])
    if not rows and dep:
        rows.append([u("\\u9023\\u52d5\\u7e3d\\u6578"), dep.get("validated_link_count", 0), dep.get("method", "three_fold_conditional_lift_with_fdr"), dep.get("warning", u("\\u5df2\\u5b8c\\u6210\\u6aa2\\u5b9a")), u("\\u6709\\u6548\\u9023\\u52d5 0\\uff1a\\u5df2\\u57f7\\u884c\\u4fdd\\u5b88\\u964d\\u6b0a")])
    return safe_rows(rows)


def rolling_model_rows(analysis):
    industrial = analysis.get("industrial_engine") or {}
    release = industrial.get("release_gate") or {}
    prev = industrial.get("previous_prediction_guard") or {}
    review = analysis.get("failure_review") or {}
    backtest = analysis.get("backtest") or {}
    weights = industrial.get("weights") or {}
    ultimate = industrial.get("ultimate_precision_targets") or {}
    five = (ultimate.get("pack_backtest") or {}).get("five_hit_two") or {}
    tournament = (ultimate.get("pack_backtest") or {}).get("five_strategy_tournament") or {}
    strategy = ultimate.get("five_stability_strategy", five.get("selected_strategy", "-"))
    rows = [
        [
            u("\\u7a69\\u5b9a5\\u4e2d2~3\\u7b56\\u7565\\u7af6\\u8cfd"),
            f"{strategy} / {u('\\u9054\\u6210\\u7387')} {round(float(five.get('success_rate', 0)) * 100, 2)}%",
            u("\\u6bcf\\u6b21\\u66f4\\u65b0\\u81ea\\u52d5\\u6311\\u9078\\u8fd1\\u671f\\u56de\\u6e2c\\u6700\\u7a69\\u76845\\u78bc\\u7b56\\u7565"),
            u("\\u5df2\\u555f\\u7528"),
        ],
        [
            u("\\u4e0a\\u671f\\u7d50\\u7b97\\u56de\\u994b"),
            f"Top5/Top10/Top15 {((review.get('last_settled') or {}).get('top5_hits', 0))}/{((review.get('last_settled') or {}).get('top10_hits', 0))}/{((review.get('last_settled') or {}).get('top15_hits', 0))}",
            u("\\u547d\\u4e2d\\u4f86\\u6e90\\u4fdd\\u7559\\uff0c\\u672a\\u547d\\u4e2d\\u4f86\\u6e90\\u964d\\u6b0a"),
            u("\\u5df2\\u9023\\u52d5\\u5230\\u672c\\u671f\\u9810\\u6e2c"),
        ],
        [
            u("\\u56de\\u6e2c\\u5dee\\u503c"),
            f"Top10 edge {release.get('actual_backtest_edge', 0)} / {backtest.get('rounds', 0)} {u('\\u671f')}",
            u("\\u512a\\u52e2\\u5c0f\\u6642\\u964d\\u4f4e\\u5f37\\u63a8\\u7b49\\u7d1a"),
            esc(release.get("status", "")),
        ],
        [
            u("\\u91cd\\u8907\\u5b88\\u9580"),
            f"Top10 {metric_count(prev.get('current_top10_overlap', 0))} / Top15 {metric_count(prev.get('current_top15_overlap', 0))}",
            u("\\u9632\\u6b62\\u76f4\\u63a5\\u62ff\\u4e0a\\u671f\\u9810\\u6e2c\\u7576\\u672c\\u671f"),
            u("\\u5df2\\u57f7\\u884c"),
        ],
        [
            u("\\u6b0a\\u91cd\\u6efe\\u52d5"),
            f"{len(weights)} {u('\\u9805\\u7279\\u5fb5\\u6b0a\\u91cd')}",
            u("\\u6bcf\\u6b21\\u66f4\\u65b0\\u5f8c\\u4f9d\\u7d50\\u7b97\\u8207\\u56de\\u6e2c\\u91cd\\u7b97"),
            u("\\u5df2\\u555f\\u7528"),
        ],
    ]
    for item in review.get("actions", []) or []:
        rows.append([u("\\u6aa2\\u8a0e\\u4fee\\u6b63"), esc(item), u("\\u7d0d\\u5165\\u4e0b\\u671f\\u6a21\\u578b\\u8abf\\u6574"), u("\\u5df2\\u57f7\\u884c")])
    for key, item in sorted(tournament.items()):
        rows.append([
            f"5{u('\\u78bc')} {esc(key)}",
            f"{round(float(item.get('success_rate', 0)) * 100, 2)}% / {item.get('rounds', 0)}",
            u("\\u7b56\\u7565\\u7af6\\u8cfd\\u56de\\u6e2c\\u7d50\\u679c"),
            u("\\u5df2\\u8a08\\u7b97"),
        ])
    return safe_rows(rows)


def road_pattern_rows(analysis):
    industrial = analysis.get("industrial_engine") or {}
    candidates = industrial.get("candidates") or analysis.get("candidates") or []
    rows = []
    for idx, item in enumerate(candidates[:10], 1):
        number = item.get("number") if isinstance(item, dict) else item
        rows.append([idx, f"{int(number):02d}", u("\\u5929\\u5929\\u6a02\\u7248\\u8def\\u7d9c\\u5408"), item.get("score", "-") if isinstance(item, dict) else "-", u("\\u89c0\\u5bdf")])
    return safe_rows(rows)


def eight_zone_rows(analysis):
    zones = [[] for _ in range(8)]
    for item in (analysis.get("candidates") or [])[:24]:
        n = int(item.get("number"))
        zones[(n - 1) % 8].append(n)
    rows = []
    for idx, numbers in enumerate(zones, 1):
        rows.append([idx, fmt_numbers(numbers), len(numbers), u("\\u4e8c\\u8f2a\\u5019\\u9078"), u("\\u7528\\u65bc\\u5340\\u9593\\u5206\\u6563")])
    return rows


def model_improvement_rows(analysis):
    industrial = analysis.get("industrial_engine") or {}
    ibt = industrial.get("backtest") or {}
    unlikely = industrial.get("unlikely_backtest") or {}
    return [
        [u("\\u7d9c\\u5408\\u6a21\\u578b"), ibt.get("top10_avg_hits", 0), ibt.get("top15_avg_hits", 0), ibt.get("top10_edge_vs_random", 0), u("\\u6301\\u7e8c\\u6efe\\u52d5\\u56de\\u6e2c")],
        [u("\\u66ab\\u907f\\u865f\\u6aa2\\u67e5"), unlikely.get("sample_size", 0), unlikely.get("avg_hits", 0), unlikely.get("warning", u("\\u5df2\\u5b8c\\u6210\\u98a8\\u63a7\\u6aa2\\u67e5")), u("\\u907f\\u514d\\u904e\\u5ea6\\u6392\\u9664")],
    ]


def aerospace_block(analysis):
    aerospace = analysis.get("aerospace_assurance") or {}
    assurance = aerospace.get("release_assurance") or {}
    redundant = aerospace.get("redundant_channel_audit") or {}
    drift = aerospace.get("drift_audit") or {}
    uncertainty = aerospace.get("uncertainty_audit") or {}
    rows = []
    for item in uncertainty.get("number_retention", [])[:15]:
        rows.append([f"{int(item.get('number')):02d}", item.get("original_rank", ""), item.get("retention_rate", "")])
    body = (
        f"<p>{u('\\u5be9\\u6838\\u72c0\\u614b')}:{esc(assurance.get('status'))} / {u('\\u4fdd\\u8b49\\u5206\\u6578')} {esc(assurance.get('assurance_score'))}</p>"
        f"<p>{u('\\u8cc7\\u6599\\u6307\\u7d0b SHA-256')}:{esc(aerospace.get('input_fingerprint_sha256'))}</p>"
        f"<p>{u('\\u8f38\\u51fa\\u6307\\u7d0b SHA-256')}:{esc(aerospace.get('output_fingerprint_sha256'))}</p>"
        f"<p>{u('\\u96d9\\u901a\\u9053\\u4ea4\\u53c9\\u9a57\\u8b49')}:{esc(redundant.get('status'))} / Top10 {u('\\u91cd\\u758a')} {esc(redundant.get('overlap_count'))} / Jaccard {esc(redundant.get('jaccard'))}</p>"
        f"<p>{u('\\u6a21\\u578b\\u6f02\\u79fb')}:{esc(drift.get('status'))} / TV {esc(drift.get('total_variation'))}</p>"
        f"<p>{u('\\u8499\\u5730\\u5361\\u7f85\\u64fe\\u52d5\\u6e2c\\u8a66')}:{esc(uncertainty.get('simulations'))} / Top10 {u('\\u4fdd\\u7559\\u7387')} {esc(uncertainty.get('top10_retention'))}</p>"
        + table([u("\\u865f\\u78bc"), u("\\u539f\\u6392\\u540d"), u("\\u64fe\\u52d5\\u5f8cTop10\\u7559\\u5b58\\u7387")], rows)
    )
    return body


def make_markdown(analysis, settled):
    latest = analysis.get("latest_draw") or {}
    freshness = analysis.get("freshness") or {}
    industrial = analysis.get("industrial_engine") or {}
    release = industrial.get("release_gate") or {}
    stability = industrial.get("stability_consensus") or {}
    audit = industrial.get("model_audit") or {}
    lines = [
        "# " + u("\\u5929\\u5929\\u6a02 \\u958b\\u734e\\u9810\\u6e2c\\u6230\\u5831"),
        "",
        f"- {u('\\u7522\\u751f\\u6642\\u9593')}:{analysis.get('generated_at_taiwan')}",
        f"- {u('\\u8cc7\\u6599\\u65b0\\u9bae\\u5ea6')}:{freshness.get('status')} / {u('\\u6700\\u65b0\\u65e5\\u671f')} {freshness.get('latest_draw_date')}",
        f"- {u('\\u6700\\u65b0\\u671f\\u5225')}:{latest.get('period')} ({latest.get('draw_date')})",
        f"- {u('\\u6700\\u65b0\\u865f\\u78bc')}:{fmt_numbers(latest.get('numbers'))}",
        f"- {u('\\u9810\\u6e2c\\u76ee\\u6a19\\u65e5')}:{analysis.get('target_draw_date')}",
        f"- {u('\\u767c\\u5e03\\u7b49\\u7d1a')}:{release.get('status')} / {u('\\u50c5\\u4f9b\\u89c0\\u5bdf') if not analysis.get('official_release_allowed') else u('\\u6b63\\u5f0f\\u767c\\u5e03')}",
        f"- Top10 {u('\\u7a69\\u5b9a\\u5171\\u8b58\\u7387')}:{stability.get('top10_retention')}",
        f"- {u('\\u98a8\\u96aa\\u7b49\\u7d1a')}:{audit.get('risk_level')}",
        "",
        "## " + u("\\u4eca\\u65e5\\u89c0\\u5bdf\\u5019\\u9078"),
    ]
    for pack in (analysis.get("strong_packs") or {}).values():
        lines.append(f"- {pack.get('name')}:{fmt_numbers(pack.get('numbers'))}")
    lines.extend(["", "## " + u("\\u5019\\u9078 Top15")])
    for idx, item in enumerate((analysis.get("candidates") or [])[:15], 1):
        lines.append(f"{idx}. {int(item.get('number')):02d} / {item.get('confidence_index', item.get('score'))} / {u('\\u907a\\u6f0f')} {item.get('omission')}")
    if settled:
        lines.extend([
            "",
            "## " + u("\\u4e0a\\u671f\\u547d\\u4e2d\\u6aa2\\u8a0e"),
            f"- {u('\\u9810\\u6e2c\\u4f9d\\u64da')}:{settled.get('based_on_date')} -> {u('\\u5be6\\u969b\\u958b\\u734e')}:{settled.get('actual_date')}",
            f"- Top5 / Top10 / Top15:{settled.get('top5_hits')} / {settled.get('top10_hits')} / {settled.get('top15_hits')}",
        ])
    return "\n".join(lines) + "\n"


def page(title, subtitle, content):
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>{esc(title)}</title>
  <style>
    body {{ margin:0; font-family:"Microsoft JhengHei", Arial, sans-serif; background:#f6f7fb; color:#20242a; }}
    header {{ background:#0f172a; color:white; padding:22px 28px; }}
    header h1 {{ margin:0 0 8px; font-size:28px; }}
    header p {{ margin:0; color:#cbd5e1; }}
    main {{ max-width:1180px; margin:0 auto; padding:22px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; }}
    .card {{ background:white; border:1px solid #e5e7eb; border-radius:8px; padding:16px; }}
    .card h2 {{ margin:0 0 10px; font-size:16px; color:#475569; }}
    .value {{ font-size:24px; font-weight:800; letter-spacing:1px; }}
    .sub {{ color:#64748b; margin:8px 0 0; font-size:13px; }}
    .band {{ background:white; border:1px solid #e5e7eb; border-radius:8px; margin-top:16px; padding:18px; overflow-x:auto; }}
    .band h2 {{ margin:0 0 12px; font-size:20px; }}
    table {{ width:100%; min-width:760px; border-collapse:collapse; background:white; }}
    th, td {{ border-bottom:1px solid #e5e7eb; padding:9px; text-align:left; vertical-align:top; }}
    th {{ background:#f1f5f9; color:#334155; }}
    .risk {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#fee2e2; color:#991b1b; font-weight:700; }}
    .status {{ display:inline-block; padding:5px 10px; border-radius:6px; background:#e2e8f0; color:#0f172a; font-weight:800; margin-right:6px; }}
    .blocked {{ background:#fee2e2; color:#991b1b; }}
    .fresh {{ background:#dcfce7; color:#166534; }}
    .notice {{ border-left:5px solid #dc2626; background:#fff7f7; }}
    .chapter {{ background:#0f172a; color:white; border:0; }}
    .chapter h2 {{ color:white; font-size:22px; }}
    .chapter p {{ color:#cbd5e1; margin:0; }}
    .high-alert {{ border:3px solid #dc2626; background:#fff1f2; box-shadow:0 0 0 4px #fee2e2 inset; }}
    .high-alert .value {{ color:#b91c1c; font-size:32px; }}
    .high-alert .badge {{ display:inline-block; padding:6px 12px; border-radius:6px; background:#dc2626; color:white; font-weight:900; margin:4px 6px 4px 0; }}
    .mobile-action {{ display:block; text-align:center; padding:14px; background:#166534; color:#fff!important; text-decoration:none; border-radius:6px; font-weight:800; }}
    .mobile-action.secondary {{ background:#1d4ed8; }}
    pre {{ white-space:pre-wrap; background:#0b1020; color:#dbeafe; border-radius:8px; padding:16px; overflow:auto; }}
    @media (max-width:640px) {{ header{{padding:16px}} header h1{{font-size:22px}} main{{padding:10px}} .grid{{grid-template-columns:1fr}} .band{{padding:12px}} th,td{{font-size:13px}} .value{{font-size:20px}} }}
  </style>
</head>
<body>
<header><h1>{esc(title)}</h1><p>{subtitle}</p></header>
<main>{content}</main>
</body></html>"""


def build_report():
    analysis = load_json(ANALYSIS_JSON)
    if not analysis:
        raise RuntimeError("missing latest_analysis.json")
    with sqlite3.connect(DB_PATH) as conn:
        snapshots = snapshot_rows(conn)
    settled = latest_settled_snapshot(snapshots)
    latest = analysis.get("latest_draw") or {}
    freshness = analysis.get("freshness") or {}
    industrial = analysis.get("industrial_engine") or {}
    release = industrial.get("release_gate") or {}
    stability = industrial.get("stability_consensus") or {}
    audit = industrial.get("model_audit") or {}
    regime = industrial.get("regime_analysis") or {}
    backtest = analysis.get("backtest") or {}
    latest_tw_time = freshness.get("latest_taiwan_safe_update_time", "-")
    target_tw_time = freshness.get("target_taiwan_safe_update_time", "-")
    title = u("\\u5929\\u5929\\u6a02 \\u958b\\u734e\\u9810\\u6e2c\\u6230\\u5831")
    subtitle = (
        f"{u('\\u5831\\u8868\\u7522\\u751f')} {esc(analysis.get('generated_at_taiwan'))} / "
        f"{u('\\u7f8e\\u570b\\u52a0\\u5dde\\u6700\\u65b0\\u958b\\u734e\\u65e5')} {esc(latest.get('draw_date'))} / "
        f"{u('\\u53f0\\u7063\\u53ef\\u66f4\\u65b0\\u6642\\u9593')} {esc(latest_tw_time)} / "
        f"{u('\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593\\uff08\\u53f0\\u7063\\uff09')} {esc(target_tw_time)}"
    )
    release_text = u("\\u6b63\\u5f0f\\u767c\\u5e03") if analysis.get("official_release_allowed") else u("\\u50c5\\u4f9b\\u89c0\\u5bdf\\uff0c\\u7981\\u6b62\\u6b63\\u5f0f\\u4e3b\\u63a8")
    fresh_text = u("\\u8cc7\\u6599\\u5df2\\u66f4\\u65b0") if freshness.get("status") in {"fresh", "ok", "ok_before_draw"} else freshness.get("status", "")
    md = make_markdown(analysis, settled)

    conclusion = f"""
    <section class="band notice">
      <h2>{u('\\u672c\\u671f\\u767c\\u5e03\\u7d50\\u8ad6')}</h2>
      <p><span class="status fresh">{esc(fresh_text)}</span><span class="status blocked">{esc(release_text)}</span></p>
      <p><strong>{u('\\u904b\\u7b97\\u5f15\\u64ce')}:{esc(industrial.get('engine_version'))}</strong></p>
      <p>{u('\\u7f8e\\u570b\\u52a0\\u5dde\\u6700\\u65b0\\u958b\\u734e\\u65e5')}:{esc(freshness.get('latest_draw_date'))} / {u('\\u53f0\\u7063\\u53ef\\u66f4\\u65b0\\u6642\\u9593')}:{esc(latest_tw_time)} / {u('\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593\\uff08\\u53f0\\u7063\\uff09')}:{esc(target_tw_time)} / {u('\\u7e3d\\u7b46\\u6578')}:{esc(analysis.get('draw_count'))}</p>
      <p>{u('\\u767c\\u5e03\\u5224\\u5b9a')}: Top10 {u('\\u7a69\\u5b9a\\u5171\\u8b58')} {esc(stability.get('top10_retention'))} / edge {esc(release.get('actual_backtest_edge'))} / {esc(release.get('status'))}</p>
      <p>{u('\\u63d0\\u9192\\uff1a\\u672c\\u6230\\u5831\\u70ba\\u6b77\\u53f2\\u7d71\\u8a08\\u5206\\u6790\\uff0c\\u4e0d\\u4fdd\\u8b49\\u958b\\u51fa\\u3002')}</p>
    </section>"""
    date_table = table(
        [u("\\u9805\\u76ee"), u("\\u5167\\u5bb9")],
        [
            [u("\\u5831\\u8868\\u7522\\u751f\\u6642\\u9593"), esc(analysis.get("generated_at_taiwan"))],
            [u("\\u7f8e\\u570b\\u52a0\\u5dde\\u6700\\u65b0\\u958b\\u734e\\u65e5"), esc(freshness.get("latest_draw_date"))],
            [u("\\u6700\\u65b0\\u958b\\u734e\\u53f0\\u7063\\u53ef\\u66f4\\u65b0\\u6642\\u9593"), esc(latest_tw_time)],
            [u("\\u6700\\u65b0\\u671f / \\u65e5"), f"{esc(latest.get('period'))} / {esc(latest.get('draw_date'))}"],
            [u("\\u6700\\u65b0\\u958b\\u734e\\u865f"), mark_numbers(latest.get("numbers"), latest.get("numbers"))],
            [u("\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593\\uff08\\u53f0\\u7063\\uff09"), esc(target_tw_time)],
            [u("\\u4e0b\\u671f\\u5c0d\\u61c9\\u52a0\\u5dde\\u958b\\u734e\\u65e5"), esc(analysis.get("target_draw_date"))],
            [u("\\u6642\\u5340\\u898f\\u5247"), esc(freshness.get("timezone_rule"))],
            [u("\\u6700\\u8fd1\\u7d50\\u7b97\\u5c0d\\u61c9"), f"{esc(settled.get('based_on_date'))} -> {esc(settled.get('actual_date'))}" if settled else "-"],
        ],
    )
    settled_block = ""
    if settled:
        settled_block = f"""
        <section class="band notice">
          <h2>{u('\\u4e0a\\u671f\\u547d\\u4e2d\\u6aa2\\u8a0e\\u6458\\u8981')}</h2>
          <p>{u('\\u5be6\\u969b\\u958b\\u734e')}:{mark_numbers(settled.get('actual_numbers'), settled.get('actual_numbers'))} / Top5 {settled.get('top5_hits')} / Top10 {settled.get('top10_hits')} / Top15 {settled.get('top15_hits')}</p>
        </section>"""
    kpi_rows = [
        ["Top10", backtest.get("rounds", ""), backtest.get("top10_avg_hits", ""), backtest.get("random_top10_expectation", ""), round((backtest.get("top10_avg_hits", 0) or 0) - (backtest.get("random_top10_expectation", 0) or 0), 4)],
        ["Top15", backtest.get("rounds", ""), backtest.get("top15_avg_hits", ""), "-", "-"],
    ]
    important_dates = table(
        [u("\\u9805\\u76ee"), u("\\u65e5\\u671f"), u("\\u72c0\\u614b"), u("\\u8aaa\\u660e")],
        [
            [u("\\u5831\\u8868\\u7522\\u751f"), esc(analysis.get("generated_at_taiwan")), u("\\u5df2\\u7522\\u751f"), u("\\u672c\\u6b21\\u904b\\u7b97\\u6642\\u9593")],
            [u("\\u7f8e\\u570b\\u52a0\\u5dde\\u8cc7\\u6599\\u6700\\u65b0"), esc(freshness.get("latest_draw_date")), esc(freshness.get("status")), f"{u('\\u53f0\\u7063\\u53ef\\u66f4\\u65b0')} {esc(latest_tw_time)}"],
            [u("\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593\\uff08\\u53f0\\u7063\\uff09"), esc(target_tw_time), esc(release.get("status")), f"{u('\\u52a0\\u5dde\\u958b\\u734e\\u65e5')} {esc(analysis.get('target_draw_date'))}"],
            [u("\\u4e0a\\u671f\\u6aa2\\u8a0e"), esc(settled.get("actual_date", "-") if settled else "-"), u("\\u5df2\\u9023\\u52d5\\u6aa2\\u8a0e") if settled else u("\\u5f85\\u7d50\\u7b97"), u("\\u7528\\u65bc\\u6efe\\u52d5\\u8abf\\u6574")],
        ],
    )
    content = f'<section class="band"><h2>{u("\\u91cd\\u8981\\u65e5\\u671f\\u5100\\u8868\\u677f")}</h2>{important_dates}</section>'
    content += conclusion
    content += f'<section class="band"><h2>{u("\\u65e5\\u671f\\u57fa\\u6e96\\u7e3d\\u8868")}</h2>{date_table}</section>'
    content += f'<section class="band notice"><h2>{u("\\u7814\\u7a76\\u547d\\u4e2d KPI \\u8207\\u7981\\u6b62\\u865b\\u5831\\u9580\\u6abb")}</h2><p>{u("\\u9019\\u4e9b\\u662f\\u7814\\u7a76\\u76ee\\u6a19\\uff0c\\u4e0d\\u662f\\u6a02\\u900f\\u5fc5\\u4e2d\\u4fdd\\u8b49\\u3002")}</p>{table(["KPI", u("\\u6a23\\u672c"), u("\\u5e73\\u5747\\u547d\\u4e2d"), u("\\u96a8\\u6a5f\\u57fa\\u6e96"), u("\\u5dee\\u503c")], kpi_rows)}</section>'
    content += f'<section class="band chapter"><h2>{u("\\u4eca\\u65e5\\u9810\\u6e2c\\u904b\\u7b97\\u5340")}</h2><p>{u("\\u672c\\u5340\\u53ea\\u5448\\u73fe\\u672c\\u671f\\u8207\\u4e0b\\u671f\\u9810\\u6e2c\\u6c7a\\u7b56\\u3002")}</p></section>'
    content += today_high_probability_block(analysis)
    content += f'<section class="band notice"><h2>{u("\\u7d42\\u6975\\u76ee\\u6a19\\uff1a95%\\u7cbe\\u6e96\\u7a69\\u5b9a\\u6cbb\\u7406")}</h2><p>{u("\\u672c\\u5340\\u662f\\u767c\\u5e03\\u9580\\u6abb\\uff0c\\u4e0d\\u662f\\u865b\\u5831\\u4fdd\\u8b49\\u3002\\u672a\\u905495%\\u6642\\u53ea\\u80fd\\u964d\\u7d1a\\u89c0\\u5bdf\\u8207\\u6efe\\u52d5\\u8abf\\u6574\\u3002")}</p>{table([u("\\u76ee\\u6a19\\u7d44"), u("\\u547d\\u4e2d\\u7bc4\\u570d"), u("\\u76ee\\u6a19\\u7387"), u("\\u56de\\u6e2c\\u9054\\u6210\\u7387"), u("\\u6a23\\u672c"), u("\\u72c0\\u614b"), u("\\u52d5\\u4f5c")], ultimate_precision_rows(analysis))}</section>'
    content += f'<section class="band notice"><h2>{u("\\u7368\\u652f\\u7cbe\\u6e96\\u9a57\\u8b49\\uff1a\\u9a57\\u8b49\\u3001\\u518d\\u9a57\\u8b49\\u3001\\u56de\\u6e2c\\u3001\\u4ea4\\u53c9\\u6bd4\\u5c0d\\u3001\\u518d\\u6bd4\\u5c0d")}</h2><p>{u("\\u7368\\u652f\\u4e0d\\u8207\\u4e00\\u822c\\u5f37\\u724c\\u6df7\\u5217\\uff0c\\u5fc5\\u9808\\u9010\\u95dc\\u904b\\u7b97\\u5f8c\\u624d\\u5217\\u5165\\u672c\\u5340\\u3002")}</p>{table([u("\\u95dc\\u5361"), u("\\u904b\\u7b97\\u5167\\u5bb9"), u("\\u6bd4\\u5c0d\\u57fa\\u6e96"), u("\\u7d50\\u679c"), u("\\u5f8c\\u7e8c\\u52d5\\u4f5c")], single_precision_rows(analysis))}</section>'
    content += f'<section class="band notice"><h2>{u("\\u9810\\u6e2c\\u6a21\\u578b\\u6efe\\u52d5\\u5f0f\\u8abf\\u6574")}</h2><p>{u("\\u672c\\u7cfb\\u7d71\\u6bcf\\u6b21\\u66f4\\u65b0\\u5f8c\\uff0c\\u6703\\u4f9d\\u4e0a\\u671f\\u7d50\\u7b97\\u3001\\u56de\\u6e2c\\u5dee\\u503c\\u3001\\u91cd\\u8907\\u5b88\\u9580\\u8207\\u6b0a\\u91cd\\u8868\\u81ea\\u52d5\\u8abf\\u6574\\u3002")}</p>{table([u("\\u6efe\\u52d5\\u9805\\u76ee"), u("\\u672c\\u6b21\\u7d50\\u679c"), u("\\u6a21\\u578b\\u8abf\\u6574"), u("\\u72c0\\u614b")], rolling_model_rows(analysis))}</section>'
    content += f'<section class="band"><h2>1{u("\\u4e2d")}1 / 5{u("\\u4e2d")}2~3 / 9{u("\\u4e2d")}3~5 {u("\\u6838\\u5fc3\\u7a69\\u5b9a\\u6a21\\u578b")}</h2><p>{u("\\u7a69\\u5b9a\\u76ee\\u6a19\\uff1a\\u6bcf\\u671f\\u6700\\u5c11\\u8981\\u671d5\\u4e2d2~3\\u7684\\u7a69\\u5b9a\\u7d44\\u5408\\u63a8\\u9032\\uff0c\\u672a\\u9054\\u6a19\\u5247\\u7e7c\\u7e8c\\u6efe\\u52d5\\u8abf\\u6574\\u3002")}</p>{table([u("\\u6a21\\u578b"), u("\\u865f\\u78bc"), u("\\u76ee\\u6a19"), u("\\u7406\\u8ad6\\u6a5f\\u7387"), u("\\u7d04\\u7565\\u8d54\\u7387")], core_model_rows(analysis))}</section>'
    content += f'<section class="band"><h2>Top10 {u("\\u64e0\\u5165\\u6821\\u6e96")}</h2>{table([u("\\u539f\\u6392\\u540d"), u("\\u865f\\u78bc"), u("\\u6307\\u6578"), u("\\u7a69\\u5b9a\\u6578"), u("\\u6821\\u6e96\\u5224\\u65b7")], top10_promotion_rows(analysis))}</section>'
    content += '<div class="grid">'
    content += f'<section class="card"><h2>{u("\\u8cc7\\u6599\\u65b0\\u9bae\\u5ea6")}</h2><div class="value">{esc(fresh_text)}</div><p class="sub">{esc(freshness.get("latest_draw_date"))}</p></section>'
    content += f'<section class="card"><h2>{u("\\u767c\\u5e03\\u7b49\\u7d1a")}</h2><div class="value">{esc(release_text)}</div><p class="sub">{esc(release.get("status"))}</p></section>'
    content += f'<section class="card"><h2>Top10 {u("\\u7a69\\u5b9a\\u5171\\u8b58")}</h2><div class="value">{esc(stability.get("top10_retention"))}</div><p class="sub">{u("\\u64fe\\u52d5\\u5feb\\u7167")} {esc(stability.get("snapshots"))}</p></section>'
    content += f'<section class="card"><h2>{u("\\u98a8\\u96aa\\u7b49\\u7d1a")}</h2><div class="value">{esc(audit.get("risk_level"))}</div><p class="sub">{esc(audit.get("verdict"))}</p></section>'
    content += "</div>"
    content += f'<section class="band"><h2>{u("\\u8fd1\\u671f\\u7a69\\u5b9a\\u5ea6\\u56de\\u6e2c")}</h2>{table([u("\\u671f\\u6578"), u("\\u6a23\\u672c"), "Top10", u("\\u5c0d\\u96a8\\u6a5f\\u5dee\\u503c"), u("\\u9580\\u6abb")], rolling_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u7a69\\u5b9a\\u5171\\u8b58\\u7368\\u7acb\\u6846\\u67b6")}</h2>{table([u("\\u6392\\u540d"), u("\\u865f\\u78bc"), u("\\u5feb\\u7167\\u5171\\u8b58"), u("\\u5feb\\u7167\\u7387"), u("\\u8499\\u5730\\u5361\\u7f85\\u7559\\u5b58\\u7387"), u("\\u7a69\\u5b9a\\u6578"), u("\\u7d9c\\u5408\\u6307\\u6578")], stable_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u5168\\u90e8\\u9810\\u6e2c\\u6b77\\u53f2\\u5c0d\\u6bd4")}</h2><p><a href="tiantianle_prediction_history.html">{u("\\u958b\\u555f\\u6bcf\\u671f\\u9810\\u6e2c\\u5c0d\\u6bd4")}</a></p>{table([u("\\u76ee\\u6a19\\u65e5"), u("\\u72c0\\u614b"), u("\\u4f9d\\u64da\\u65e5"), u("\\u5be6\\u969b\\u65e5"), "Top10", u("\\u5be6\\u969b\\u865f"), u("\\u547d\\u4e2d\\u865f"), "Top5", "Top10", "Top15", u("\\u5efa\\u7acb")], history_table(snapshots)[:12])}</section>'
    content += f'<section class="band"><h2>{u("\\u822a\\u592a\\u7d1a\\u904b\\u7b97\\u4fdd\\u8b49\\u5be9\\u6838")}</h2>{aerospace_block(analysis)}</section>'
    adv = (industrial.get("advanced_models") or {})
    content += f'<section class="band"><h2>{u("\\u4e0b\\u671f\\u9810\\u6e2c\\u5c08\\u5340\\uff1a\\u9032\\u968e\\u9810\\u6e2c\\u6a21\\u578b")}</h2><p>{esc(adv.get("warning"))}</p><p>{u("\\u9032\\u968e\\u6a21\\u578b\\u5171\\u8b58 Top12")}:{fmt_numbers(adv.get("consensus_top12", []))}</p>{table([u("\\u6a21\\u578b"), "Top10", u("Top10 \\u56de\\u6e2c"), u("\\u5c0d\\u96a8\\u6a5f\\u5dee\\u503c"), u("\\u65b9\\u6cd5")], advanced_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u4e0b\\u671f\\u9810\\u6e2c\\u5c08\\u5340\\uff1a\\u89c0\\u5bdf\\u5019\\u9078\\uff08\\u4e0d\\u5217\\u6b63\\u5f0f\\u4e3b\\u63a8\\uff09")}</h2><p>{esc(release_text)}</p></section><div class="grid">{pack_cards(analysis)}</div>'
    content += f'<section class="band"><h2>{u("\\u7cbe\\u6e96\\u5ea6\\u6cbb\\u7406\\u5668\\uff1a\\u5f37\\u724c\\u767c\\u5e03\\u5be9\\u6838")}</h2>{table([u("\\u9805\\u76ee"), u("\\u6578\\u503c1"), u("\\u6578\\u503c2"), u("\\u898f\\u5247"), u("\\u5099\\u8a3b")], precision_governor_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u56b4\\u8b39\\u9a57\\u8b49\\u95dc\\u5361\\uff1a\\u672a\\u9a57\\u8b49\\u865f\\u78bc\\u7981\\u6b62\\u51fa\\u73fe")}</h2>{table([u("\\u9805\\u76ee"), u("\\u6578\\u503c1"), u("\\u6578\\u503c2"), u("\\u539f\\u56e0/\\u4f9d\\u64da"), u("\\u72c0\\u614b")], strict_validation_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u9810\\u6e2c\\u865f\\u78bc\\u9010\\u865f\\u7cbe\\u7b97\\u9a57\\u8b49")}</h2>{table([u("\\u6392\\u540d"), u("\\u865f\\u78bc"), u("\\u6307\\u6578"), u("\\u907a\\u6f0f"), u("\\u7a69\\u5b9a\\u6578"), u("\\u7406\\u7531")], per_number_validation_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u81ea\\u52d5\\u6b0a\\u91cd\\u6821\\u6e96\\uff1a\\u8fd1\\u671f\\u5be6\\u6230\\u7279\\u5fb5\\u8abf\\u6b0a")}</h2>{table([u("\\u6b0a\\u91cd\\u9805"), u("\\u6578\\u503c"), u("\\u4f86\\u6e90"), u("\\u52d5\\u4f5c"), u("\\u5099\\u8a3b")], adaptive_weight_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u4e0b\\u671f\\u9810\\u6e2c\\u5c08\\u5340\\uff1a\\u5de5\\u696d\\u7d1a\\u6a21\\u578b\\u5be9\\u8a08")}</h2><p><span class="risk">{u("\\u98a8\\u96aa\\u7b49\\u7d1a")}:{esc(audit.get("risk_level"))}</span></p><p>{esc(audit.get("verdict"))}</p><p>{u("\\u958b\\u734e\\u578b\\u614b")}:{esc(u("\\u3001").join(regime.get("messages", [])))}</p></section>'
    content += f'<section class="band"><h2>{u("\\u4e0b\\u671f\\u9810\\u6e2c\\u5c08\\u5340\\uff1a\\u4f4e\\u6a5f\\u7387\\u66ab\\u907f\\u865f\\u78bc")}</h2>{table(["#", u("\\u865f\\u78bc"), u("\\u66ab\\u907f\\u6307\\u6578"), u("\\u51fa\\u73fe\\u8a55\\u5206"), u("\\u5019\\u9078\\u6392\\u540d"), u("\\u7a69\\u5b9a\\u6b21\\u6578"), u("\\u66ab\\u907f\\u539f\\u56e0")], unlikely_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u901a\\u904e\\u6a23\\u672c\\u5916\\u9a57\\u8b49\\u7684\\u865f\\u78bc\\u9023\\u52d5")}</h2>{table([u("\\u4f86\\u6e90\\u865f"), u("\\u76ee\\u6a19\\u865f"), u("\\u652f\\u6301"), u("\\u63d0\\u5347"), "FDR"], dependency_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u5929\\u5929\\u6a02\\u7248\\u8def\\u724c\\u7368\\u7acb\\u5206\\u6790")}</h2>{table([u("\\u6392\\u540d"), u("\\u865f\\u78bc"), u("\\u7248\\u8def\\u985e\\u5225"), u("\\u5206\\u6578"), u("\\u72c0\\u614b")], road_pattern_rows(analysis))}</section>'
    content += f'<section class="band"><h2>9{u("\\u4e2d")}3 {u("\\u8f2a\\u7d44\\u8986\\u84cb")}</h2>{table(["#", u("\\u7d44\\u5408")], wheel_rows(analysis))}</section>'
    content += f'<section class="band"><h2>8{u("\\u5340\\u4e8c\\u8f2a\\u5206\\u7d44\\u7814\\u7a76\\u6a21\\u578b")}</h2>{table([u("\\u5340"), u("\\u865f\\u78bc"), u("\\u6578\\u91cf"), u("\\u6a21\\u5f0f"), u("\\u7528\\u9014")], eight_zone_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u5019\\u9078 Top 15")}</h2>{table([u("\\u6392\\u540d"), u("\\u865f\\u78bc"), u("\\u6307\\u6578"), u("\\u907a\\u6f0f"), u("\\u7406\\u7531")], candidate_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u4f4e\\u6a5f\\u7387\\u66ab\\u907f\\u865f\\u78bc\\uff08\\u98a8\\u63a7\\u89c0\\u5bdf\\uff09")}</h2>{table(["#", u("\\u865f\\u78bc"), u("\\u66ab\\u907f\\u6307\\u6578"), u("\\u51fa\\u73fe\\u8a55\\u5206"), u("\\u5019\\u9078\\u6392\\u540d"), u("\\u7a69\\u5b9a\\u6b21\\u6578"), u("\\u66ab\\u907f\\u539f\\u56e0")], unlikely_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u6a21\\u578b\\u56de\\u6e2c\\u8207\\u6539\\u5584\\u898f\\u5283")}</h2>{table([u("\\u6a21\\u578b"), "Top10", "Top15", u("\\u5dee\\u503c/\\u72c0\\u614b"), u("\\u6539\\u5584\\u52d5\\u4f5c")], model_improvement_rows(analysis))}</section>'
    content += f'<section class="band chapter"><h2>{u("\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e\\u8207\\u4fee\\u6b63\\u5340")}</h2><p>{u("\\u672c\\u5340\\u53ea\\u8655\\u7406\\u4e0a\\u671f\\u7d50\\u679c\\u3001\\u672a\\u547d\\u4e2d\\u539f\\u56e0\\u3001\\u964d\\u6b0a\\u8207\\u6efe\\u52d5\\u4fee\\u6b63\\uff0c\\u4e0d\\u7576\\u4f5c\\u4eca\\u65e5\\u9810\\u6e2c\\u865f\\u78bc\\u3002")}</p></section>'
    content += settled_block
    content += f'<section class="band"><h2>{u("\\u9810\\u6e2c\\u6392\\u540d\\u6821\\u6e96\\u6aa2\\u8a0e")}</h2>{table([u("\\u5340\\u9593"), u("\\u6578\\u91cf"), u("\\u865f\\u78bc"), u("\\u56de\\u6e2c\\u53c3\\u8003"), u("\\u4fee\\u6b63\\u52d5\\u4f5c")], rank_calibration_rows(analysis))}</section>'
    content += f'<section class="band"><h2>{u("\\u6bcf\\u65e5\\u6aa2\\u8a0e\\u5f8c\\u6efe\\u52d5\\u8abf\\u6574")}</h2>{table([u("\\u985e\\u5225"), u("\\u6aa2\\u8a0e\\u5167\\u5bb9"), u("\\u8abf\\u6574\\u52d5\\u4f5c"), u("\\u4f9d\\u64da"), u("\\u72c0\\u614b")], rolling_adjustment_rows(analysis))}</section>'
    if settled:
        content += f'<section class="band"><h2>{u("\\u4e0a\\u671f\\u547d\\u4e2d\\u6aa2\\u8a0e\\u5c08\\u5340")}</h2><p>{u("\\u9810\\u6e2c\\u4f9d\\u64da")} {esc(settled.get("based_on_date"))} -> {u("\\u5be6\\u969b\\u958b\\u734e")} {esc(settled.get("actual_date"))}</p>{table([u("\\u865f\\u78bc"), u("\\u72c0\\u614b"), u("\\u5019\\u9078\\u6392\\u540d"), u("\\u547d\\u4e2d\\u4f86\\u6e90\\u95dc\\u806f\\u89e3\\u6790")], actual_review_rows(settled))}</section>'
        content += f'<section class="band"><h2>{u("\\u4e0a\\u671f\\u6b63\\u5f0f\\u9810\\u6e2c\\u9010\\u865f\\u6aa2\\u8a0e")}</h2>{table([u("\\u6392\\u540d"), u("\\u865f\\u78bc"), u("\\u7d50\\u679c"), u("\\u4fe1\\u5fc3"), u("\\u907a\\u6f0f"), u("\\u539f\\u59cb\\u4f86\\u6e90"), u("\\u6aa2\\u8a0e\\u52d5\\u4f5c")], candidate_review_rows(settled))}</section>'
        content += f'<section class="band"><h2>{u("\\u4e0a\\u671f\\u5f37\\u724c\\u7d44\\u6210\\u6557\\u6aa2\\u8a0e")}</h2>{table([u("\\u5f37\\u724c"), u("\\u539f\\u9810\\u6e2c"), u("\\u76ee\\u6a19"), u("\\u5be6\\u969b"), u("\\u7d50\\u679c"), u("\\u547d\\u4e2d\\u865f"), u("\\u672a\\u547d\\u4e2d\\u865f")], pack_review_rows(settled))}</section>'
        content += f'<section class="band"><h2>{u("\\u4e0a\\u671f\\u9810\\u6e2c\\u4f86\\u6e90\\u7406\\u7531\\u6210\\u6557\\u7d71\\u8a08")}</h2>{table([u("\\u4f86\\u6e90\\u7406\\u7531"), u("\\u547d\\u4e2d"), u("\\u672a\\u547d\\u4e2d"), u("\\u6d89\\u53ca\\u865f\\u78bc"), u("\\u4fee\\u6b63\\u65b9\\u5411")], candidate_reason_stats(settled))}</section>'
    content += f'<section class="band"><h2>{u("\\u539f\\u59cb\\u6230\\u5831")}</h2><pre>{html.escape(md)}</pre></section>'
    return page(title, subtitle, content), md, build_history_html(snapshots)


def split_prediction_review(report_html):
    start = report_html.find("<main>")
    end = report_html.rfind("</main>")
    if start < 0 or end < 0:
        return report_html, report_html
    inner_start = start + len("<main>")
    inner = report_html[inner_start:end]
    marker = '<section class="band chapter"><h2>' + u("\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e\\u8207\\u4fee\\u6b63\\u5340")
    split_at = inner.find(marker)
    if split_at < 0:
        return report_html, report_html
    prediction_inner = inner[:split_at]
    for title in [
        u("\\u5168\\u90e8\\u9810\\u6e2c\\u6b77\\u53f2\\u5c0d\\u6bd4"),
    ]:
        prediction_inner = re.sub(
            rf'<section class="band"><h2>{re.escape(title)}</h2>.*?</section>',
            "",
            prediction_inner,
            flags=re.S,
        )
    for row_title in [
        u("\\u6700\\u8fd1\\u7d50\\u7b97\\u5c0d\\u61c9"),
        u("\\u4e0a\\u671f\\u6aa2\\u8a0e"),
        u("\\u4e0a\\u671f\\u7d50\\u7b97\\u56de\\u994b"),
    ]:
        prediction_inner = re.sub(
            rf"<tr><td>{re.escape(row_title)}</td>.*?</tr>",
            "",
            prediction_inner,
            flags=re.S,
        )
    prediction_inner = re.sub(r"<tr><td>.*?未命中.*?</tr>", "", prediction_inner, flags=re.S)
    review_inner = inner[split_at:]
    review_inner = review_inner.split(f'<section class="band"><h2>{u("\\u539f\\u59cb\\u6230\\u5831")}</h2>', 1)[0]
    nav = ""
    prediction_html = report_html[:inner_start] + nav + prediction_inner + report_html[end:]
    review_html = report_html[:inner_start] + nav + review_inner + report_html[end:]
    return prediction_html, review_html


def save_reports():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_html, report_md, history_html = build_report()
    prediction_html, review_html = split_prediction_review(report_html)
    MAIN_HTML.write_text(report_html, encoding="utf-8")
    LATEST_HTML.write_text(report_html, encoding="utf-8")
    DASHBOARD_HTML.write_text(report_html, encoding="utf-8")
    PREDICTION_HTML.write_text(prediction_html, encoding="utf-8")
    REVIEW_HTML.write_text(review_html, encoding="utf-8")
    MAIN_MD.write_text(report_md, encoding="utf-8")
    HISTORY_HTML.write_text(history_html, encoding="utf-8")
    return MAIN_HTML


if __name__ == "__main__":
    print(save_reports())
