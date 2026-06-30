#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import html
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

from 中文顯示工具 import localize_plain_text, localize_visible_html, write_alias


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
LOW_PROBABILITY_HTML = REPORT_DIR / "tiantianle_low_probability_avoid.html"


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


def candidate_confidence_parts(item):
    confidence = safe_float(item.get("confidence_index", item.get("score", 0)))
    if 0 < confidence <= 1:
        confidence *= 100
    probability = safe_float(item.get("model_probability_percent", 0))
    stability = safe_int(item.get("stability_count", 0))
    cross = item.get("cross_validation") or {}
    passed = safe_int(cross.get("passed_count", 0))
    total = safe_int(cross.get("total_count", 0))
    status = str(cross.get("status", "-") or "-")
    rank = safe_int(item.get("rank", item.get("_display_rank", 99)), 99)
    top9_core = bool(item.get("top9_core", rank <= 9)) and rank <= 9
    top9_note = u("\\u0054\\u006f\\u0070\\u0039\\u6838\\u5fc3") if top9_core else u("\\u0054\\u006f\\u0070\\u0039\\u5916\\u5099\\u67e5")
    if not top9_core:
        level = u("\\u89c0\\u5bdf")
        css = "confidence-watch"
    elif confidence >= 88 and (probability >= 15 or stability >= 5) and passed >= 3:
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
        f"{u('\\u4ea4\\u53c9\\u9a57\\u8b49')} {passed}/{total} {status} / {top9_note}"
    )
    return level, detail, css, confidence, probability, stability, passed, total


def confidence_note(item, compact=False):
    level, detail, css, *_ = candidate_confidence_parts(item)
    if compact:
        return f'<span class="{css}">{esc(level)}</span> {esc(detail)}'
    return f'<span class="{css}">{esc(level)}</span><br><span class="sub">{esc(detail)}</span>'


def is_high_confidence_candidate(item):
    level, *_ = candidate_confidence_parts(item)
    return level == u("\\u9ad8\\u4fe1\\u5fc3")


def is_display_confidence_candidate(item):
    level, *_ = candidate_confidence_parts(item)
    return level in {u("\\u9ad8\\u4fe1\\u5fc3"), u("\\u4e2d\\u9ad8\\u4fe1\\u5fc3")}


def high_confidence_candidates(analysis, limit=9):
    rows = []
    for idx, item in enumerate((analysis.get("candidates") or [])[:9], 1):
        if is_display_confidence_candidate(item):
            copied = dict(item)
            copied["_display_rank"] = idx
            rows.append(copied)
    return rows[:limit]


def pack_confidence_note(analysis, numbers):
    candidates = {safe_int(item.get("number")): item for item in (analysis.get("candidates") or []) if isinstance(item, dict)}
    high_notes = []
    mid_notes = []
    for number in numbers or []:
        item = candidates.get(safe_int(number))
        if not item:
            continue
        level, detail, *_ = candidate_confidence_parts(item)
        note = f"{int(number):02d} {level}({detail})"
        if level == u("\\u9ad8\\u4fe1\\u5fc3"):
            high_notes.append(note)
        elif level == u("\\u4e2d\\u9ad8\\u4fe1\\u5fc3"):
            mid_notes.append(note)
    if high_notes:
        return u("\\u9ad8\\u4fe1\\u5fc3\\u52a0\\u8a3b\\uff1a") + "；".join(high_notes[:4])
    if mid_notes:
        return u("\\u4e2d\\u9ad8\\u4fe1\\u5fc3\\u52a0\\u8a3b\\uff1a") + "；".join(mid_notes[:4])
    return u("\\u672c\\u7d44\\u7121\\u9ad8\\u4fe1\\u5fc3\\u865f\\uff0c\\u4f9d\\u89c0\\u5bdf\\u7b49\\u7d1a\\u986f\\u793a")


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


def ultra_precision_recommendations(analysis):
    engine_precision = (
        analysis.get("precision_micro_models")
        or ((analysis.get("industrial_engine") or {}).get("precision_micro_models"))
        or ((analysis.get("primary_tiantianle_core") or {}).get("precision_micro_models"))
        or {}
    )
    if engine_precision.get("single") or engine_precision.get("two") or engine_precision.get("three"):
        return engine_precision
    candidates = [
        item for item in (analysis.get("candidates") or [])[:9]
        if item.get("top9_core", safe_int(item.get("rank"), 99) <= 9)
    ]
    scored = sorted(
        [
            {
                "number": int(item.get("number")),
                "score": ultra_precision_candidate_score(item),
                "item": item,
            }
            for item in candidates
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
        duplicate_tail_penalty = (len(tails) - len(set(tails))) * 2.6
        zone_penalty = max(0, max((zones.count(label) for label in set(zones)), default=0) - 2) * 2.2
        stability = sum(min(safe_int(item_map[number].get("stability_count")), 5) for number in numbers) / len(numbers)
        cross_passed = sum(safe_int((item_map[number].get("cross_validation") or {}).get("passed_count")) for number in numbers) / len(numbers)
        score = (sum(values) / len(values)) * 0.72 + min(values) * 0.18 + stability * 1.0 + cross_passed * 0.75
        return round(score - duplicate_tail_penalty - zone_penalty, 2)

    def best_combo(size):
        if len(score_map) < size:
            return {"numbers": [], "score": 0}
        if size == 1:
            row = max(scored, key=lambda item: item["score"])
            return {"numbers": [row["number"]], "score": row["score"]}
        best = max(
            ({"numbers": list(combo), "score": combo_score(combo)} for combo in combinations(score_map, size)),
            key=lambda row: (row["score"], sum(score_map[n] for n in row["numbers"])),
        )
        return best

    return {
        "single": best_combo(1),
        "two": best_combo(2),
        "three": best_combo(3),
        "ranked": scored,
        "policy": "Top9-only ultra precision second pass; no Top10-15 high confidence promotion",
    }


def ultra_precision_rows(analysis):
    rec = ultra_precision_recommendations(analysis)
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
        model_text = item.get("selected_model_label") or item.get("selected_model") or u("\\u7d9c\\u5408\\u7cbe\\u7b97")
        recent_text = (
            f"{u('\\u8fd160\\u671f')} {recent_60.get('pass_rate', '-')}"
            + (f" / {u('\\u96a8\\u6a5f')} {random_rate}" if random_rate is not None else "")
        )
        rows.append([
            label,
            fmt_numbers(item.get("numbers", [])),
            item.get("score", 0),
            model_text,
            recent_text,
            u("\\u5f37\\u63a8\\u89c0\\u5bdf\\uff0c\\u975e\\u4fdd\\u8b49\\u5fc5\\u4e2d"),
        ])
    return rows


def ultra_precision_block(analysis):
    rec = ultra_precision_recommendations(analysis)
    ranked_rows = []
    for row in rec.get("ranked", [])[:9]:
        item = row.get("item") or {}
        maturity = item.get("practical_maturity") or {}
        cross = item.get("cross_validation") or {}
        ranked_rows.append([
            f"{int(row.get('number')):02d}",
            row.get("score"),
            item.get("confidence_index", "-"),
            item.get("model_probability_percent", "-"),
            item.get("stability_count", "-"),
            f"{cross.get('passed_count', 0)}/{cross.get('total_count', 0)}",
            maturity.get("score", "-"),
            esc(u("\\u3001").join(item.get("reasons", []))),
        ])
    return (
        f'<section class="band high-alert"><h2>{u("\\u8d85\\u5f37\\u4fe1\\u5fc3\\u9ad8\\u6a5f\\u7387\\u5f37\\u63a8\\u7cbe\\u7b97")}</h2>'
        f'<p>{u("\\u672c\\u5340\\u53ea\\u5728\\u0054\\u006f\\u0070\\u0039\\u6838\\u5fc3\\u5167\\u505a\\u4e8c\\u6b21\\u7cbe\\u7b97\\uff0c\\u4e26\\u7528\\u8fd1\\u0033\\u0030\\u002f\\u0036\\u0030\\u002f\\u0031\\u0032\\u0030\\u671f\\u5be6\\u6230\\u7af6\\u8cfd\\u9078\\u6a21\\u578b\\uff1b\\u0054\\u006f\\u0070\\u0031\\u0030\\u002d\\u0031\\u0035\\u4ecd\\u53ea\\u80fd\\u5099\\u67e5\\u3002")}</p>'
        f'{table([u("\\u76ee\\u6a19"), u("\\u5f37\\u63a8\\u865f\\u78bc"), u("\\u7cbe\\u7b97\\u5206"), u("\\u672c\\u671f\\u63a1\\u7528\\u6a21\\u578b"), u("\\u5be6\\u6230\\u57fa\\u6e96"), u("\\u72c0\\u614b")], ultra_precision_rows(analysis))}'
        f'{table([u("\\u865f\\u78bc"), u("\\u7cbe\\u7b97\\u5206"), u("\\u4fe1\\u5fc3"), u("\\u4fdd\\u5b88\\u6a5f\\u7387"), u("\\u7a69\\u5b9a"), u("\\u4ea4\\u53c9"), u("\\u6210\\u719f"), u("\\u4f86\\u6e90")], ranked_rows)}</section>'
    )


def metric_count(value):
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    if value is None or value == "":
        return 0
    return value


def industrial_backtest(analysis):
    return ((analysis.get("industrial_engine") or {}).get("backtest") or {})


def precision_governor(analysis):
    return ((analysis.get("industrial_engine") or {}).get("precision_governor") or {})


def release_label(analysis):
    status = ((analysis.get("industrial_engine") or {}).get("release_gate") or {}).get("status")
    if analysis.get("official_release_allowed") or status == "official":
        return u("\\u6b63\\u5f0f\\u767c\\u5e03")
    if status == "verified_research_complete":
        return u("\\u5be6\\u6230\\u7814\\u7a76\\u5b8c\\u6574\\u7248\\uff08\\u975e\\u6b63\\u5f0f\\u4fdd\\u8b49\\uff09")
    return u("\\u50c5\\u4f9b\\u89c0\\u5bdf\\uff0c\\u7981\\u6b62\\u6b63\\u5f0f\\u4e3b\\u63a8")


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
            return "-"
        text = str(cell)
        if text.strip() in {"", "-", "[]"}:
            return "-"
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


def draw_on(conn, date_text):
    if not date_text:
        return None
    row = conn.execute(
        "SELECT draw_date,n1,n2,n3,n4,n5 FROM draws WHERE draw_date=?",
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
        target_actual = draw_on(conn, row[2])
        actual = target_actual or draw_after(conn, row[1])
        actual_numbers = actual["numbers"] if actual else []
        ranked = [item.get("number") for item in candidates if isinstance(item, dict)]
        hit_numbers = sorted(set(ranked[:15]) & set(actual_numbers)) if actual else []
        missed_actual_numbers = sorted(set(actual_numbers) - set(ranked[:15])) if actual else []
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
                "hit_numbers": hit_numbers,
                "missed_actual_numbers": missed_actual_numbers,
                "review_source": "target_date" if target_actual else "next_draw_after_based_on",
                "exact_target_review": bool(target_actual),
            }
        )
    return items


def latest_settled_snapshot(items, latest_draw_date=None):
    if latest_draw_date:
        for item in items:
            if item.get("actual_date") == latest_draw_date and item.get("actual_numbers"):
                return item
        return {}
    for item in items:
        if item.get("actual_numbers"):
            return item
    return {}


def latest_settled_prediction_for_actual_date(conn, latest_draw_date):
    if not latest_draw_date:
        return {}
    row = conn.execute(
        """
        SELECT id,based_on_date,target_date,candidates_json,strong_packs_json,created_at,
               actual_date,actual_numbers_json,top5_hits,top10_hits,top15_hits,
               strong_pack_hits_json,status
        FROM predictions
        WHERE status='settled' AND actual_date=?
        ORDER BY id DESC LIMIT 1
        """,
        (latest_draw_date,),
    ).fetchone()
    if not row:
        return {}
    try:
        candidates = json.loads(row[3] or "[]")
        packs = json.loads(row[4] or "{}")
        actual_numbers = json.loads(row[7] or "[]")
        strong_pack_hits = json.loads(row[11] or "{}")
    except Exception:
        return {}
    ranked = [item.get("number") for item in candidates if isinstance(item, dict)]
    hit_numbers = sorted(set(ranked[:15]) & set(actual_numbers))
    missed_actual_numbers = sorted(set(actual_numbers) - set(ranked[:15]))
    return {
        "id": row[0],
        "based_on_date": row[1],
        "target_date": row[2],
        "candidates": candidates,
        "strong_packs": packs,
        "created_at": row[5],
        "reason": "predictions_settled_exact_latest_draw",
        "actual_date": row[6],
        "actual_numbers": actual_numbers,
        "top5_hits": row[8],
        "top10_hits": row[9],
        "top15_hits": row[10],
        "strong_pack_hits": strong_pack_hits,
        "hit_numbers": hit_numbers,
        "missed_actual_numbers": missed_actual_numbers,
        "review_source": "\u5168\u6b77\u53f2\u56de\u6e2c\u7d50\u7b97\u8868\uff1a\u6700\u65b0\u958b\u734e\u65e5\u7cbe\u6e96\u5c0d\u61c9",
        "exact_target_review": True,
    }


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
    release = ((analysis.get("industrial_engine") or {}).get("release_gate") or {})
    for key, pack in (analysis.get("strong_packs") or {}).items():
        if key == "strong_single":
            continue
        prob = pack.get("theoretical_probability", {})
        sub = f"{u('\\u7406\\u8ad6\\u6a5f\\u7387')} {prob.get('probability', '-')} / 1{u('\\u4e2d')}{prob.get('odds_1_in', '-')}"
        confidence = pack_confidence_note(analysis, pack.get("numbers", []))
        release_note = f"{u('\\u767c\\u5e03\\u95dc\\u5361')} {release.get('status', '-')}"
        cards.append(
            f'<section class="card"><h2>{esc(pack.get("name", key))}</h2>'
            f'<div class="value">{fmt_numbers(pack.get("numbers", []))}</div><p class="sub">{esc(sub)}</p>'
            f'<p class="confidence-line">{esc(confidence)}</p><p class="sub">{esc(release_note)}</p></section>'
        )
    return "".join(cards)


def single_precision_rows(analysis):
    packs = analysis.get("strong_packs") or {}
    ultra_single = (ultra_precision_recommendations(analysis).get("single") or {})
    single = packs.get("strong_single") or {}
    numbers = ultra_single.get("numbers") or single.get("numbers") or []
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
    backtest = industrial_backtest(analysis)
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
    rolling = industrial_backtest(analysis).get("rolling_windows") or {}
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
    avoid = analysis.get("low_probability_avoid") or {}
    groups = avoid.get("groups") or {}
    items = groups.get("十五不中") or (((analysis.get("industrial_engine") or {}).get("unlikely_number_analysis") or {}).get("numbers", [])[:15])
    rows = []
    for idx, item in enumerate(items[:15], 1):
        rows.append([
            idx,
            f"{int(item.get('number')):02d}",
            item.get("avoid_confidence", item.get("avoid_index", item.get("avoid_score", ""))),
            item.get("confidence_label", "-"),
            item.get("appearance_score", ""),
            item.get("candidate_rank", ""),
            item.get("stability_count", ""),
            esc(u("\\u3001").join(item.get("reasons", []))),
        ])
    return rows


def avoid_group_rows(analysis, group_name):
    avoid = analysis.get("low_probability_avoid") or {}
    groups = avoid.get("groups") or {}
    rows = []
    for idx, item in enumerate(groups.get(group_name, []), 1):
        rows.append([
            idx,
            f"{int(item.get('number')):02d}",
            item.get("avoid_confidence", ""),
            item.get("confidence_label", "-"),
            item.get("appearance_score", ""),
            item.get("candidate_rank", ""),
            esc(u("\\u3001").join(item.get("reasons", []))),
        ])
    return safe_rows(rows)


def low_probability_avoid_block(analysis):
    avoid = analysis.get("low_probability_avoid") or {}
    backtest = avoid.get("backtest") or {}
    warning = avoid.get("warning") or u("\\u4f4e\\u6a5f\\u7387\\u4ee3\\u8868\\u6a21\\u578b\\u5efa\\u8b70\\u907f\\u958b\\uff0c\\u4e0d\\u662f\\u7d55\\u5c0d\\u4fdd\\u8b49\\u3002")
    headers = ["#", u("\\u865f\\u78bc"), u("\\u907f\\u958b\\u4fe1\\u5fc3"), u("\\u4fe1\\u5fc3\\u7b49\\u7d1a"), u("\\u51fa\\u73fe\\u8a55\\u5206"), u("\\u5019\\u9078\\u6392\\u540d"), u("\\u907f\\u958b\\u7406\\u7531")]
    return (
        f'<section class="band danger-zone"><h2>{u("\\u4f4e\\u6a5f\\u7387\\u4e0d\\u4e2d\\u5206\\u6790\\u7e3d\\u89bd")}</h2>'
        f'<p>{esc(warning)}</p>'
        f'<p>{u("\\u56de\\u6e2c\\u6458\\u8981")}：{u("\\u6a23\\u672c")} {esc(backtest.get("rounds", "-"))} / {u("\\u5e73\\u5747\\u8aa4\\u5165")} {esc(backtest.get("avg_accidental_hits", "-"))} / {u("\\u96f6\\u8aa4\\u5165\\u7387")} {esc(backtest.get("zero_hit_rate", "-"))}</p>'
        f'<h3>{u("\\u4e94\\u4e0d\\u4e2d")}</h3>{table(headers, avoid_group_rows(analysis, "五不中"))}'
        f'<h3>{u("\\u5341\\u4e0d\\u4e2d")}</h3>{table(headers, avoid_group_rows(analysis, "十不中"))}'
        f'<h3>{u("\\u5341\\u4e94\\u4e0d\\u4e2d")}</h3>{table(headers, avoid_group_rows(analysis, "十五不中"))}</section>'
    )


def strict_recalculation_rows(analysis):
    manifest = analysis.get("recalculation_manifest") or {}
    basis = manifest.get("basis") or {}
    return [
        [u("\\u91cd\\u65b0\\u904b\\u7b97"), esc(manifest.get("status", "-")), esc(manifest.get("visible_note", "-"))],
        [u("\\u4f9d\\u64da\\u958b\\u734e"), esc(basis.get("latest_draw_date", "-")), fmt_numbers(basis.get("latest_numbers", []))],
        [u("\\u4e0b\\u671f\\u76ee\\u6a19"), esc(basis.get("target_draw_date", analysis.get("target_draw_date", "-"))), esc(basis.get("target_taiwan_safe_update_time", analysis.get("prediction_draw_taiwan_time", "-")))],
        [u("\\u91cd\\u7b97\\u6307\\u7d0b"), esc(manifest.get("fingerprint", "-")), u("\\u6bcf\\u671f\\u6703\\u56e0\\u6700\\u65b0\\u958b\\u734e\\u8207\\u9810\\u6e2c\\u7d50\\u679c\\u6539\\u8b8a")],
    ]


def strict_recommendation_rows(analysis):
    policy = analysis.get("strict_recommendation_policy") or {}
    rows = []
    for item in (policy.get("formal_recommendations") or policy.get("high_confidence_watch") or [])[:9]:
        rows.append([
            item.get("rank", "-"),
            f"{int(item.get('number')):02d}",
            item.get("confidence_level", "-"),
            item.get("confidence_index", "-"),
            item.get("model_probability_percent", "-"),
            f"{item.get('stability_count', '-')}/{item.get('cross_validation_passed', '-')}",
            item.get("maturity_level", "-"),
            esc(u("\\u3001").join(item.get("reasons", []))),
        ])
    return safe_rows(rows)


def strict_recommendation_block(analysis):
    policy = analysis.get("strict_recommendation_policy") or {}
    return (
        f'<section class="band high-alert"><h2>{u("\\u56b4\\u683c\\u9ad8\\u4fe1\\u5fc3\\u63a8\\u85a6\\u5340")}</h2>'
        f'<p><strong>{esc(policy.get("mode", "-"))}</strong>：{esc(policy.get("message", "-"))}</p>'
        f'<p>{esc(policy.get("visible_rule", "-"))}</p>'
        f'{table([u("\\u6392\\u540d"), u("\\u865f\\u78bc"), u("\\u7b49\\u7d1a"), u("\\u4fe1\\u5fc3\\u6307\\u6578"), u("\\u6a21\\u578b\\u6a5f\\u7387"), u("\\u7a69\\u5b9a/\\u9a57\\u8b49"), u("\\u6210\\u719f\\u5ea6"), u("\\u4f9d\\u64da")], strict_recommendation_rows(analysis))}</section>'
    )


def candidate_rows(analysis):
    rows = []
    for idx, item in enumerate((analysis.get("candidates") or [])[:15], 1):
        rows.append([
            idx,
            f"{int(item.get('number')):02d}",
            item.get("confidence_index", item.get("score", "")),
            confidence_note(item),
            item.get("omission", ""),
            esc(u("\\u3001").join(item.get("reasons", []))),
        ])
    return rows


def wheel_rows(analysis):
    pack = (analysis.get("strong_packs") or {}).get("nine_hit_three") or {}
    return [[idx, fmt_numbers(ticket)] for idx, ticket in enumerate(pack.get("wheel_tickets", []), 1)]


def safe_rows(rows):
    return rows if rows else [[u("\\u4f9d\\u76ee\\u524d\\u5929\\u5929\\u6a02\\u6b77\\u53f2\\u5be6\\u7b97"), "0", u("\\u5df2\\u5b8c\\u6210\\u6aa2\\u5b9a\\uff0c\\u6709\\u6548\\u8a0a\\u865f\\u70ba 0"), u("\\u5df2\\u57f7\\u884c\\u964d\\u6b0a\\u8207\\u89c0\\u5bdf\\u52d5\\u4f5c"), u("\\u6301\\u7e8c\\u6bcf\\u65e5\\u7d50\\u7b97")]]


def rank_calibration_rows(analysis):
    backtest = industrial_backtest(analysis)
    candidates = analysis.get("candidates") or []
    return [
        ["Top1-5", len(candidates[:5]), fmt_numbers([x.get("number") for x in candidates[:5]]), backtest.get("top10_avg_hits", "-"), u("\\u6301\\u7e8c\\u89c0\\u5bdf")],
        ["Top6-9", len(candidates[5:9]), fmt_numbers([x.get("number") for x in candidates[5:9]]), backtest.get("random_top10_expectation", "-"), u("\\u524d9\\u6838\\u5fc3\\u58d3\\u7e2e")],
        ["Top10-15", len(candidates[9:15]), fmt_numbers([x.get("number") for x in candidates[9:15]]), backtest.get("top15_avg_hits", "-"), u("\\u5099\\u67e5\\uff0c\\u4e0d\\u5217\\u9ad8\\u4fe1\\u5fc3")],
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
    ultra = ultra_precision_recommendations(analysis)
    for ultra_key, label, goal in [
        ("single", "\\u8d85\\u5f37\\u7cbe\\u7b97\\u7368\\u96bb1\\u4e2d1", "1"),
        ("two", "\\u8d85\\u5f37\\u7cbe\\u7b972\\u4e2d1~2", "1-2"),
        ("three", "\\u8d85\\u5f37\\u7cbe\\u7b973\\u4e2d1~3", "1-3"),
    ]:
        item = ultra.get(ultra_key) or {}
        rows.append([
            u(label),
            fmt_numbers(item.get("numbers", [])),
            goal,
            f"{u('\\u4e8c\\u6b21\\u7cbe\\u7b97\\u5206')} {item.get('score', 0)}",
            "Top9",
        ])
    labels = {
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
    packs = analysis.get("strong_packs") or {}
    rows = []
    order = ["strong_single", "two_hit_one", "three_hit_two", "five_hit_two", "nine_hit_three"]
    threshold_label = u("\\u9580\\u6abb")
    below_95_label = u("\\u672a\\u905495%")
    reached_95_label = u("\\u905495%")
    for key in order:
        pack = packs.get(key) or {}
        governance = pack.get("governance") or {}
        label = pack.get("name", key)
        min_hits = pack.get("hit_goal", governance.get("goal", 0))
        max_hits = pack.get("hit_goal_max", 5 if key == "nine_hit_three" else min_hits)
        target = 0.95
        rate = governance.get("pass_rate", 0)
        required = governance.get("required_pass_rate", 0)
        status = pack.get("status", "research_prediction")
        action = (
            u("\\u672a\\u9054\\u5be6\\u6230\\u9580\\u6abb\\uff0c\\u50c5\\u5217\\u89c0\\u5bdf\\u4e26\\u6efe\\u52d5\\u964d\\u6b0a")
            if not pack.get("official_release")
            else u("\\u5df2\\u904e\\u5be6\\u6230\\u9580\\u6abb")
        )
        rows.append([
            esc(label),
            f"{min_hits}~{max_hits}",
            f"{round(float(target) * 100, 2)}%",
            f"{round(float(rate) * 100, 2)}% / {threshold_label} {round(float(required) * 100, 2)}%",
            governance.get("rounds", 0),
            esc(f"{status} / {below_95_label if float(rate or 0) < target else reached_95_label}"),
            esc(action),
        ])
    return safe_rows(rows)


def today_high_probability_rows(analysis):
    packs = analysis.get("strong_packs") or {}
    release = ((analysis.get("industrial_engine") or {}).get("release_gate") or {})
    rows = []
    ultra = ultra_precision_recommendations(analysis)
    for ultra_key, label in [
        ("single", u("\\u8d85\\u5f37\\u7cbe\\u7b97\\u7368\\u96bb1\\u4e2d1")),
        ("two", u("\\u8d85\\u5f37\\u7cbe\\u7b972\\u4e2d1~2")),
        ("three", u("\\u8d85\\u5f37\\u7cbe\\u7b973\\u4e2d1~3")),
    ]:
        item = ultra.get(ultra_key) or {}
        numbers = item.get("numbers") or []
        rows.append([
            label,
            fmt_numbers(numbers),
            esc(pack_confidence_note(analysis, numbers)),
            f"{u('\\u0054\\u006f\\u0070\\u0039\\u4e8c\\u6b21\\u7cbe\\u7b97\\u5206')} {item.get('score', 0)}",
            esc(f"{release.get('status', '')} / ultra_precision"),
            u("\\u9ad8\\u4fe1\\u5fc3\\u5f37\\u63a8\\u89c0\\u5bdf\\uff0c\\u975e\\u4fdd\\u8b49\\u5fc5\\u4e2d"),
        ])
    for key in ["five_hit_two", "nine_hit_three"]:
        pack = packs.get(key) or {}
        governance = pack.get("governance") or {}
        status = pack.get("status") or ("released" if pack.get("official_release") else "research_prediction")
        pass_rate = safe_float(governance.get("pass_rate", 0))
        required = safe_float(governance.get("required_pass_rate", 0))
        edge = safe_float(governance.get("pass_rate_edge_vs_random", 0))
        threshold_label = u("\\u9580\\u6abb")
        high = bool(pack.get("official_release")) and release.get("status") == "official"
        rate_text = (
            f"{round(pass_rate * 100, 2)}% / {threshold_label} {round(required * 100, 2)}% / "
            f"edge {round(edge * 100, 2)}%"
        )
        action = (
            u("\\u9ad8\\u6a5f\\u7387\\u5f37\\u5316\\u986f\\u793a")
            if high
            else u("\\u672a\\u904e\\u6b63\\u5f0f\\u5be6\\u6230\\u9580\\u6abb\\uff0c\\u50c5\\u5217\\u89c0\\u5bdf\\u5019\\u9078")
        )
        rows.append([
            esc(pack.get("name", key)),
            fmt_numbers(pack.get("numbers", [])),
            esc(pack_confidence_note(analysis, pack.get("numbers", []))),
            rate_text,
            esc(f"{release.get('status', '')} / {status}"),
            action,
        ])
    return safe_rows(rows)


def today_high_probability_block(analysis):
    release = ((analysis.get("industrial_engine") or {}).get("release_gate") or {})
    packs = analysis.get("strong_packs") or {}
    official_high = any(pack.get("official_release") for pack in packs.values()) and release.get("status") == "official"
    high_candidates = [item for item in high_confidence_candidates(analysis, limit=15) if is_high_confidence_candidate(item)]
    any_high = official_high or bool(high_candidates)
    badge = (
        u("\\u672c\\u65e5\\u9ad8\\u6a5f\\u7387\\u6b63\\u5f0f\\u8a0a\\u865f")
        if official_high
        else u("\\u672c\\u65e5\\u9ad8\\u4fe1\\u5fc3\\u5019\\u9078\\uff08\\u89c0\\u5bdf\\uff09")
        if high_candidates
        else u("\\u672c\\u65e5\\u89c0\\u5bdf\\u8a0a\\u865f")
    )
    note = (
        u("\\u5df2\\u89f8\\u767c95%\\u6cbb\\u7406\\u9580\\u6abb\\uff0c\\u672c\\u5340\\u5f37\\u5316\\u986f\\u793a\\u3002")
        if official_high
        else u("\\u672c\\u65e5\\u6709\\u9ad8\\u4fe1\\u5fc3\\u5019\\u9078\\uff0c\\u5df2\\u52a0\\u8a3b\\u986f\\u793a\\uff1b\\u76ee\\u524d\\u767c\\u5e03\\u95dc\\u5361\\u672a\\u6539\\u6210\\u6b63\\u5f0f\\u4fdd\\u8b49\\uff0c\\u4ecd\\u4ee5\\u89c0\\u5bdf\\u7b49\\u7d1a\\u5448\\u73fe\\u3002")
        if high_candidates
        else u("\\u5df2\\u5b8c\\u6210\\u904b\\u7b97\\uff0c\\u672c\\u65e5\\u4ee5\\u89c0\\u5bdf\\u7b49\\u7d1a\\u986f\\u793a\\uff0c\\u7e7c\\u7e8c\\u6efe\\u52d5\\u8abf\\u6574\\u3002")
    )
    freshness = analysis.get("freshness") or {}
    target_label = f"{freshness.get('target_taiwan_safe_update_time', analysis.get('target_draw_date'))} ({u('\\u53f0\\u7063')}) / {u('\\u52a0\\u5dde')} {analysis.get('target_draw_date')}"
    return (
        f'<section class="band high-alert"><h2>{u("\\u672c\\u65e5\\u958b\\u734e\\u9810\\u6e2c\\u9ad8\\u6a5f\\u7387\\u76e3\\u63a7")}</h2>'
        f'<span class="badge">{badge}</span><div class="value">{esc(target_label)}</div>'
        f'<p>{note}</p>'
        f'{table([u("\\u76ee\\u6a19\\u7d44"), u("\\u672c\\u65e5\\u865f\\u78bc"), u("\\u9ad8\\u4fe1\\u5fc3\\u8aaa\\u660e"), u("\\u56de\\u6e2c\\u9054\\u6210\\u7387"), u("\\u767c\\u5e03\\u95dc\\u5361"), u("\\u986f\\u793a\\u52d5\\u4f5c")], today_high_probability_rows(analysis))}</section>'
    )


def high_confidence_candidate_block(analysis):
    rows = []
    focus_numbers = []
    focus_details = []
    for item in high_confidence_candidates(analysis, limit=10):
        reasons = u("\\u3001").join(item.get("reasons", []))
        if len(focus_numbers) < 5:
            level, detail, *_ = candidate_confidence_parts(item)
            focus_numbers.append(item.get("number"))
            focus_details.append(f"{int(item.get('number')):02d}:{level}")
        rows.append([
            item.get("_display_rank", "-"),
            f"{int(item.get('number')):02d}",
            confidence_note(item),
            esc(reasons),
            u("\\u5df2\\u5728\\u672c\\u65e5\\u9810\\u6e2c\\u5206\\u9801\\u8207\\u624b\\u6a5f\\u9996\\u9801\\u52a0\\u8a3b\\u986f\\u793a"),
        ])
    focus = (
        f'<div class="signal-focus"><div class="signal-title">{u("\\u672c\\u671f\\u4e3b\\u4fe1\\u5fc3\\u724c")}</div>'
        f'<div class="signal-numbers">{fmt_numbers(focus_numbers)}</div>'
        f'<div class="signal-detail">{esc(" / ".join(focus_details))}</div></div>'
        if focus_numbers else ""
    )
    return (
        f'<section class="band high-alert"><h2>{u("\\u9ad8\\u6a5f\\u7387\\uff0f\\u9ad8\\u4fe1\\u5fc3\\u9810\\u6e2c\\u52a0\\u8a3b\\u8aaa\\u660e")}</h2>'
        f'<p>{u("\\u51e1\\u4fe1\\u5fc3\\u6307\\u6578\\u3001\\u6a21\\u578b\\u6a5f\\u7387\\u3001\\u7a69\\u5b9a\\u5171\\u8b58\\u6216\\u4ea4\\u53c9\\u9a57\\u8b49\\u9054\\u6a19\\u8005\\uff0c\\u5fc5\\u9808\\u4f4d\\u65bc\\u0054\\u006f\\u0070\\u0039\\u6838\\u5fc3\\u624d\\u80fd\\u52a0\\u8a3b\\u70ba\\u9ad8\\u4fe1\\u5fc3\\uff1b\\u0054\\u006f\\u0070\\u0031\\u0030\\u002d\\u0031\\u0035\\u53ea\\u80fd\\u5217\\u5099\\u67e5\\u3002")}</p>'
        f'{focus}'
        f'{table([u("\\u6392\\u540d"), u("\\u865f\\u78bc"), u("\\u9ad8\\u4fe1\\u5fc3\\u8aaa\\u660e"), u("\\u4f86\\u6e90\\u7406\\u7531"), u("\\u986f\\u793a\\u72c0\\u614b")], safe_rows(rows))}</section>'
    )


def explicit_action_block(analysis):
    decision = analysis.get("latest_ironlaw") or analysis.get("decisive_battle_plan") or {}
    packs = analysis.get("strong_packs") or {}
    latest = analysis.get("latest_draw") or {}
    freshness = analysis.get("freshness") or {}
    target = decision.get("target_taiwan_safe_update_time") or freshness.get("target_taiwan_safe_update_time") or analysis.get("target_draw_date") or "-"
    data_day = latest.get("draw_date") or freshness.get("latest_draw_date") or decision.get("latest_draw_date") or "-"
    avoid_packs = decision.get("avoid_packs") or ((analysis.get("low_probability_avoid") or {}).get("avoid_packs") or {})
    defensive_avoid = decision.get("defensive_avoid") or (avoid_packs.get("ten_miss") or {}).get("numbers") or []
    rec = ultra_precision_recommendations(analysis)
    candidates = analysis.get("candidates") or []
    candidate_by_number = {int(item.get("number")): item for item in candidates if item.get("number") is not None}

    def pack_numbers(key, fallback_key=None, rec_key=None):
        numbers = decision.get(key) or []
        if not numbers and rec_key:
            numbers = (rec.get(rec_key) or {}).get("numbers") or []
        if not numbers and fallback_key:
            numbers = (packs.get(fallback_key) or {}).get("numbers") or []
        return [int(n) for n in numbers if str(n).strip().isdigit()]

    def action_card(title, numbers, sub):
        value = fmt_numbers(numbers) if numbers else "-"
        return (
            '<section class="card hot-main">'
            f"<h2>{esc(title)}</h2>"
            f'<div class="value">{esc(value)}</div>'
            f'<p class="sub">{esc(sub)}</p>'
            "</section>"
        )

    def rate_text(value):
        if value is None or value == "":
            return "-"
        value = safe_float(value)
        if 0 <= value <= 1:
            return f"{round(value * 100, 1)}%"
        return f"{round(value, 2)}%"

    def status_text(value):
        mapping = {
            "official": "正式發布",
            "formal": "正式高信心",
            "high_confidence_watch": "高信心觀察",
            "research_prediction": "研究觀察",
            "watch_only": "觀察中",
            "blocked": "暫停發布",
            "strict_downshift": "嚴格降級",
        }
        return mapping.get(str(value or ""), str(value or "-"))

    high_rows = []
    high_source = decision.get("high_confidence_numbers") or []
    if not high_source:
        for idx, item in enumerate(high_confidence_candidates(analysis, limit=9), 1):
            level, detail, _css, confidence, probability, _stability, passed, total = candidate_confidence_parts(item)
            high_source.append({
                "number": item.get("number"),
                "rank": item.get("_display_rank", idx),
                "model_probability_percent": probability,
                "confidence_index": confidence,
                "confidence_level": level,
                "stability_count": item.get("stability_count", "-"),
                "cross_validation_passed": f"{passed}/{total}",
                "reason": detail,
                "note": "高機率信心牌；本期攻擊核心優先關注，仍需依風控分批使用。",
            })
    for idx, item in enumerate(high_source[:9], 1):
        number = item.get("number")
        if number is None:
            continue
        high_rows.append([
            f"{int(number):02d}",
            esc(item.get("rank", idx)),
            f"{round(safe_float(item.get('model_probability_percent')), 2)}%",
            esc(item.get("confidence_index", "-")),
            esc(status_text(item.get("confidence_level", "-"))),
            esc(item.get("stability_count", "-")),
            esc(item.get("cross_validation_passed", "-")),
            esc(item.get("reason", "-")),
            esc(item.get("note", "-")),
        ])

    def micro_rows():
        rows = []
        specs = [
            ("single", "獨支1中1", "primary_single"),
            ("two", "2中1", "two_hit_one"),
            ("three", "3中1", "three_hit_one"),
        ]
        for rec_key, label, decision_key in specs:
            item = rec.get(rec_key) or {}
            numbers = pack_numbers(decision_key, rec_key=rec_key)
            candidate_items = [candidate_by_number.get(int(n), {}) for n in numbers]
            ranks = [safe_int(row.get("rank", row.get("_display_rank", 0))) for row in candidate_items if row]
            cross_passed = sum(safe_int((row.get("cross_validation") or {}).get("passed_count", 0)) for row in candidate_items)
            stability = sum(safe_int(row.get("stability_count", 0)) for row in candidate_items)
            tails = "、".join(sorted({str(int(n) % 10) for n in numbers})) if numbers else "-"
            zones = item.get("zones") or (packs.get(decision_key) or {}).get("zones") or {}
            zone_text = "、".join(f"{k}:{v}" for k, v in zones.items()) if zones else "-"
            recent_30 = item.get("recent_30") or {}
            recent_60 = item.get("recent_60") or {}
            recent_120 = item.get("recent_120") or {}
            multi_window = f"30期{recent_30.get('pass_rate', '-')} / 60期{recent_60.get('pass_rate', '-')} / 120期{recent_120.get('pass_rate', '-')}"
            rows.append([
                label,
                status_text(item.get("status")),
                fmt_numbers(numbers),
                "、".join(str(rank) for rank in ranks) if ranks else "-",
                item.get("score", item.get("precision_score", "-")),
                rate_text(item.get("random_success_probability") or ((item.get("theoretical_probability") or {}).get("probability"))),
                cross_passed,
                stability,
                item.get("selected_model_label") or item.get("selected_model") or "綜合精算",
                rate_text(recent_60.get("pass_rate")),
                tails,
                multi_window,
                tails,
                zone_text,
            ])
        return rows

    avoid_pack_rows = []
    for key, label in [("five_miss", "5不中"), ("ten_miss", "10不中"), ("fifteen_miss", "15不中")]:
        pack = avoid_packs.get(key) or {}
        avoid_pack_rows.append([
            label,
            mark_numbers(pack.get("numbers") or []),
            esc(pack.get("confidence_label", "-")),
            esc(pack.get("confidence_index", "-")),
            esc(pack.get("avg_avoid_score", "-")),
            esc(pack.get("min_avoid_score", "-")),
        ])

    high_numbers = {int(item.get("number")) for item in high_source[:9] if item.get("number") is not None}
    special_35 = candidate_by_number.get(35)
    if special_35:
        rank_35 = special_35.get("_display_rank") or special_35.get("rank") or "-"
        cross_35 = special_35.get("cross_validation") or {}
        passed_35 = cross_35.get("passed_count", "-")
        total_35 = cross_35.get("total_count", "-")
        status_35 = "本期高機率信心牌" if 35 in high_numbers else "特別追蹤／備查"
        action_35 = (
            "35 已進本期高信心核心。"
            if 35 in high_numbers
            else f"35 已加註追蹤；本期排序第 {rank_35} 名，未通過前九名高信心守門，不混入本期主推。"
        )
        tracking_35_rows = [[
            "35",
            status_35,
            esc(rank_35),
            rate_text(special_35.get("model_probability_percent")),
            esc(special_35.get("confidence_index", "-")),
            f"{passed_35}/{total_35}",
            esc(special_35.get("stability_count", "-")),
            action_35,
        ]]
    else:
        tracking_35_rows = [[
            "35",
            "特別追蹤／候選外",
            "-",
            "-",
            "-",
            "-",
            "-",
            "本期未進候選核心，禁止寫成主推；下期重新驗證後再判定。",
        ]]

    time_rows = []
    for row in decision.get("time_table", []) or []:
        time_rows.append([esc(row.get("item", "-")), esc(row.get("content", "-"))])
    if not time_rows:
        time_rows = [
            ["每日開獎時間", "夏令台灣時間上午09:50；冬令台灣時間上午10:50。"],
            ["開獎後更新截止", "上午10:00前完成最新開獎匯入、命中結算、重新運算與手機同步。"],
            ["午間完整重算", "每日下午13:00完成重新回測、校正模型、重建戰報與手機版。"],
        ]

    primary_single = pack_numbers("primary_single", "strong_single", "single")
    two_hit_one = pack_numbers("two_hit_one", "two_hit_one", "two")
    three_hit_one = pack_numbers("three_hit_one", "three_hit_two", "three")
    five_hit_two = pack_numbers("five_hit_two", "five_hit_two")
    nine_hit_three = pack_numbers("nine_hit_three", "nine_hit_three")
    core_numbers = nine_hit_three or decision.get("high_confidence_core") or [item.get("number") for item in high_source[:9] if item.get("number") is not None]
    cards = [
        action_card("明確獨支", primary_single, "本期一號核心"),
        action_card("明確2中1", two_hit_one, "本期雙核心"),
        action_card("明確3中1", three_hit_one, "本期三號核心"),
        action_card("明確5中2", five_hit_two, "本期五號攻擊組"),
        action_card("明確9中3", nine_hit_three, "本期九號覆蓋組"),
        action_card("防守避開", defensive_avoid, "低分與弱訊號風控"),
    ]
    return (
        '<section class="band notice">'
        f'<h2>每日更新鐵律時間表</h2>'
        f'{table(["項目", "內容"], time_rows)}'
        '</section>'
        '<section class="band hotbox">'
        f'<h2>本期明確作戰答案（全歷史資料庫運算至 {esc(data_day)} / 目標台灣時間 {esc(target)}）</h2>'
        f'<p><strong>{esc(decision.get("conclusion", decision.get("action_label", "高信心觀察強化")))}</strong></p>'
        f'<p>{esc(decision.get("release_rule", "高信心牌必須通過多重守門後才顯示。"))}</p>'
        f'<p>{esc(decision.get("recompute_rule", "每期開獎後重新運算，禁止沿用上期預測。"))}</p>'
        f'<div class="grid">{"".join(cards)}</div>'
        f'<h3>高機率信心牌特別強調</h3>'
        f'{table(["號碼", "排名", "保守機率", "信心指數", "信心", "穩定", "交叉通過", "明確原因", "備註"], high_rows, "本期無通過高信心守門號碼")}'
        f'<div class="signal-focus"><div class="signal-title">35特別追蹤加註</div><div class="signal-numbers">35</div><div class="signal-detail">若未進前九名高信心核心，只能列備查追蹤，不能混成本期主推。</div></div>'
        f'{table(["號碼", "本期定位", "排名", "保守機率", "信心指數", "交叉通過", "穩定", "處理"], tracking_35_rows)}'
        f'<h3>獨支 / 2中1 / 3中1 短包超強信心精算</h3>'
        f'{table(["短包", "狀態", "號碼", "排名", "多模型仲裁分", "保守機率", "交叉通過", "穩定次數", "召回分", "月漏回拉", "冷彈分", "多視窗", "尾轉分", "區間配額"], micro_rows())}'
        f'<p>本期9碼攻擊核心：{fmt_numbers(core_numbers)}</p>'
        '</section>'
    )


def avoid_focus_block(analysis):
    decision = analysis.get("latest_ironlaw") or analysis.get("decisive_battle_plan") or {}
    avoid = analysis.get("low_probability_avoid") or {}
    global_backtest = industrial_backtest(analysis)
    avoid_packs = decision.get("avoid_packs") or avoid.get("avoid_packs") or {}
    prediction = analysis.get("prediction") or {}
    fallbacks = {
        "five_miss": prediction.get("low_probability_5_not_hit") or [],
        "ten_miss": prediction.get("low_probability_10_not_hit") or [],
        "fifteen_miss": prediction.get("low_probability_15_not_hit") or [],
    }
    rows = []
    for key, label in [("five_miss", "5不中"), ("ten_miss", "10不中"), ("fifteen_miss", "15不中")]:
        pack = avoid_packs.get(key) or {}
        numbers = pack.get("numbers") or fallbacks.get(key) or []
        if numbers:
            rows.append([
                label,
                mark_numbers(numbers),
                esc(pack.get("confidence_label", "高避開信心")),
                esc(pack.get("confidence_index", "-")),
                esc(pack.get("avg_avoid_score", "-")),
                esc(pack.get("min_avoid_score", "-")),
                "已獨立列入低機率避開分頁",
            ])
    backtest = avoid.get("backtest") or {}
    avoid_rounds = backtest.get("rounds") or global_backtest.get("rounds", "-")
    accidental = backtest.get("avg_accidental_hits", "依避開分排序")
    zero_rate = backtest.get("zero_hit_rate", "依避開分排序")
    summary_rows = [[
        "避開回測",
        f"{avoid_rounds} 期",
        f"平均誤入 {accidental}",
        f"零誤入率 {zero_rate}",
        "每期重新運算後同步手機",
    ]]
    return (
        '<section class="band danger-zone">'
        '<h2>低機率避開重點</h2>'
        '<p>本區只放本期低機率避開，不混入下期攻擊牌。</p>'
        f'{table(["回測", "樣本", "平均", "穩定", "同步"], summary_rows)}'
        f'{table(["避開包", "號碼", "信心指標", "避開分", "最低分", "最低暫避分", "處理"], rows, "本期低機率避開已完成檢查，無可公開避開包")}'
        '</section>'
    )


def model_backtest_focus_block(analysis):
    backtest = industrial_backtest(analysis)
    release = ((analysis.get("industrial_engine") or {}).get("release_gate") or {})
    maturity = ((analysis.get("industrial_engine") or {}).get("practical_maturity") or {})
    packs = analysis.get("strong_packs") or {}
    action_map = {
        "fast_daily_publish_then_deep_review": "快速發布後深度複核",
        "watch_only": "只列觀察",
        "strict_downshift": "嚴格降級",
        "official": "正式",
    }
    maturity_action = action_map.get(str(maturity.get("action", "")), maturity.get("action", "-"))
    rows = [
        ["全歷史回測", f"{backtest.get('rounds', 0)} 期", f"前十平均 {backtest.get('top10_avg_hits', '-')}", f"前十五平均 {backtest.get('top15_avg_hits', '-')}", "已納入本期排序"],
        ["發布守門", release_label(analysis), f"優勢值 {release.get('actual_backtest_edge', '-')}", f"前十保留 {release.get('top10_retention', '-')}", "未過守門不寫成正式保證"],
        ["實戰成熟度", esc(maturity.get("status_label") or maturity.get("status") or "-"), f"平均 {maturity.get('top10_avg_maturity', '-')}", esc(maturity_action), "每期滾動修正"],
    ]
    pack_rows = []
    for key, label in [
        ("strong_single", "獨支"),
        ("two_hit_one", "2中1"),
        ("precision_three_hit_one", "3中1"),
        ("five_hit_two", "5中2"),
        ("nine_hit_three", "9中3"),
    ]:
        pack = packs.get(key) or {}
        governance = pack.get("governance") or {}
        if not pack:
            continue
        numbers = pack.get("numbers", [])
        theory = pack.get("theoretical_probability") or {}
        probability = theory.get("probability")
        if probability is not None:
            probability_text = f"理論覆蓋 {round(safe_float(probability) * 100, 2)}%"
        else:
            probability_text = f"理論覆蓋 {round((len(numbers) * 5 / 39) * 100, 2)}%"
        expected_hits = round(len(numbers) * 5 / 39, 3) if numbers else "-"
        rounds_text = governance.get("rounds") or backtest.get("rounds", "-")
        pass_text = f"達成率 {governance.get('pass_rate')}" if governance.get("pass_rate") is not None else probability_text
        avg_text = f"平均命中 {governance.get('avg_hits')}" if governance.get("avg_hits") is not None else f"期望命中 {expected_hits}"
        pack_rows.append([
            label,
            fmt_numbers(numbers),
            f"{rounds_text} 期",
            pass_text,
            avg_text,
            "正式" if pack.get("official_release") else "觀察",
        ])
    return (
        '<section class="band notice">'
        '<h2>模型回測重點</h2>'
        '<p>本區只放模型回測、發布守門、成熟度，不混入上期檢討。</p>'
        f'{table(["項目", "樣本", "指標一", "指標二", "處理"], rows)}'
        f'{table(["牌組", "號碼", "回測期數", "達成率", "平均命中", "發布"], pack_rows, "本期模型已完成回測，無額外可公開牌組")}'
        '</section>'
    )


def compact_percent(value, digits=1):
    if value is None or value == "":
        return "-"
    number = safe_float(value)
    if 0 <= number <= 1:
        number *= 100
    return f"{round(number, digits)}%"


def compact_decimal(value, digits=3):
    if value is None or value == "":
        return "-"
    return str(round(safe_float(value), digits))


def compact_status(value):
    mapping = {
        "official": "正式發布",
        "formal": "正式高信心",
        "released": "已發布",
        "research_prediction": "研究預測",
        "watch_only": "觀察候選",
        "high_confidence_watch": "高信心觀察",
        "strict_downshift": "嚴格降級",
        "recomputed_updated_watch_only_pending": "已重算待觀察",
        "fast_daily_recomputed": "快速重算完成",
        "ok": "資料已更新",
        "fresh": "資料已更新",
        "complete": "完整",
        "passed": "通過",
        "blocked": "暫停發布",
    }
    text = str(value or "-")
    return mapping.get(text, text)


def compact_pack_status(pack):
    if pack.get("official_release"):
        return "正式發布"
    return compact_status(pack.get("status") or "觀察候選")


def compact_candidate_rows_tiantianle(analysis, limit=9):
    rows = []
    candidates = analysis.get("official_candidates") or analysis.get("candidates") or []
    for rank, item in enumerate(candidates[:limit], 1):
        cross = item.get("cross_validation") or {}
        sources = item.get("model_sources") or []
        source_text = "、".join(str(source.get("label") or source.get("model") or "") for source in sources[:4] if source)
        if not source_text:
            source_text = "、".join(str(reason) for reason in (item.get("reasons") or [])[:4]) or "-"
        score = item.get("score")
        score_text = compact_percent(score, 1) if score is not None and safe_float(score) <= 1 else compact_decimal(item.get("confidence_index", score), 1)
        rows.append([
            f"{int(item.get('number')):02d}",
            item.get("rank", rank),
            score_text,
            compact_decimal(item.get("confidence_index"), 1),
            f"{compact_decimal(item.get('model_probability_percent'), 2)}%",
            item.get("omission", "-"),
            cross.get("passed_count", "-"),
            esc(source_text),
        ])
    return rows


def compact_pack_rows_tiantianle(analysis):
    packs = analysis.get("strong_packs") or {}
    backtest = industrial_backtest(analysis)
    order = [
        ("strong_single", "獨隻1中1"),
        ("two_hit_one", "2中1"),
        ("three_hit_two", "3中1"),
        ("five_hit_two", "5中2"),
        ("nine_hit_three", "9中3"),
    ]
    rows = []
    for key, label in order:
        pack = packs.get(key) or {}
        if not pack:
            continue
        gov = pack.get("governance") or {}
        numbers = pack.get("numbers") or []
        theory = pack.get("theoretical_probability") or {}
        pass_rate = gov.get("pass_rate")
        avg_hits = gov.get("avg_hits")
        if pass_rate is None:
            pass_rate = theory.get("probability")
        if avg_hits is None:
            avg_hits = round(len(numbers) * 5 / 39, 3) if numbers else None
        rows.append([
            label,
            fmt_numbers(numbers),
            compact_pack_status(pack),
            f"{gov.get('rounds') or backtest.get('rounds', '-')} 期",
            compact_percent(pass_rate, 2),
            compact_decimal(avg_hits, 3),
            "通過" if gov.get("passed") else "觀察",
        ])
    return rows


def compact_super_single_html_tiantianle(analysis):
    packs = analysis.get("strong_packs") or {}
    candidates = analysis.get("official_candidates") or analysis.get("candidates") or []
    pack = packs.get("strong_single") or {}
    numbers = pack.get("numbers") or ((analysis.get("latest_ironlaw") or {}).get("primary_single") or [])
    number = safe_int(numbers[0], 0) if numbers else 0
    item = next((row for row in candidates if safe_int(row.get("number")) == number), {}) if number else {}
    cross = item.get("cross_validation") or {}
    sources = item.get("model_sources") or []
    source_text = "、".join(str(source.get("label") or source.get("model") or "") for source in sources[:6] if source)
    if not source_text:
        source_text = "、".join(str(reason) for reason in (item.get("reasons") or [])[:6]) or "全歷史快速重算"
    decision_label = "本期最高分獨隻"
    score = item.get("score", pack.get("avg_score", pack.get("score_sum")))
    return f"""
    <div class="band singlebox">
      <h2>最強獨隻1中1</h2>
      <div class="grid">
        <div class="card hot-card"><div class="label">獨隻號碼</div><div class="value num">{number:02d}</div></div>
        <div class="card"><div class="label">判定</div><div class="value">{esc(decision_label)}</div></div>
        <div class="card"><div class="label">獨隻總分</div><div class="value">{compact_percent(score, 1)}</div></div>
        <div class="card"><div class="label">模型機率</div><div class="value">{compact_decimal(item.get('model_probability_percent'), 2)}%</div></div>
        <div class="card"><div class="label">交叉層數</div><div class="value">{cross.get('passed_count', '-')}/{cross.get('total_count', '-')}</div></div>
      </div>
      <p><strong>運算邏輯：</strong>全歷史資料庫、多模型交叉驗算、前九名核心壓縮。</p>
      <p><strong>來源模型：</strong>{esc(source_text)}</p>
      <p><strong>風控：</strong>未過正式門檻時只列觀察，不包裝成保證。</p>
    </div>
    """


def compact_review_html_tiantianle(settled):
    if not settled:
        return "<p>目前沒有已結算資料；禁止用舊期檢討冒充上期。</p>"
    actual = settled.get("actual_numbers") or []
    misses = [number for number in settled.get("top15", []) if number not in actual]
    hit_summary = f"{settled.get('top5_hits')} / {settled.get('top10_hits')} / {settled.get('top15_hits')}"
    summary_rows = [
        ["實際開獎", fmt_numbers(actual)],
        ["前五 / 前十 / 前十五", hit_summary],
        ["前十命中號", mark_numbers(settled.get("top10", []), actual)],
        ["前十五未中號", fmt_numbers(misses)],
    ]
    rows = []
    for key, value in (settled.get("strong_pack_hits") or {}).items():
        rows.append([
            value.get("name") or key,
            fmt_numbers(value.get("numbers", [])),
            value.get("hits", "-"),
            "達標" if value.get("passed") else "未達標",
        ])
    return (
        f"<p><strong>已結算：上期預測檢討：{esc(settled.get('based_on_date'))} 預測到 {esc(settled.get('actual_date'))} 開獎</strong></p>"
        f'{table(["項目", "結果"], summary_rows)}'
        f'<h3>強牌檢討</h3>{table(["類型", "號碼", "命中", "結果"], rows, "沒有強牌檢討")}'
    )


def compact_model_rows_tiantianle(analysis):
    backtest = industrial_backtest(analysis)
    advanced = ((analysis.get("industrial_engine") or {}).get("advanced_model_backtest") or {})
    rows = [
        ["整體排序模型", f"{backtest.get('rounds', 0)} 期", backtest.get("top5_avg_hits", "-"), backtest.get("top10_avg_hits", "-"), backtest.get("top15_avg_hits", "-"), backtest.get("top10_edge_vs_random", "0")],
        ["前九核心壓縮", f"{backtest.get('rounds', 0)} 期", "-", backtest.get("top10_avg_hits", "-"), backtest.get("top15_avg_hits", "-"), "每期重算"],
    ]
    for name, data in list((advanced.get("strategies") or advanced).items())[:6] if isinstance(advanced, dict) else []:
        if not isinstance(data, dict):
            continue
        rows.append([
            name,
            f"{data.get('rounds', backtest.get('rounds', '-'))} 期",
            data.get("top5_avg_hits", "-"),
            data.get("top10_avg_hits", "-"),
            data.get("top15_avg_hits", "-"),
            data.get("top10_edge_vs_random", "-"),
        ])
    return rows


def compact_lifecycle_rows_tiantianle(analysis):
    review = analysis.get("failure_review") or {}
    backtest = industrial_backtest(analysis)
    monthly = review.get("monthly_review") or {}
    rows = [
        ["滾動式修正", "已啟用", backtest.get("top10_avg_hits", "-"), f"{analysis.get('draw_count', '-')} 筆", "每期開獎後重新調整權重"],
        ["低命中降權", "已啟用", review.get("severity", "-"), monthly.get("month", "-"), "落空號與弱來源自動降權"],
        ["高信心守門", "已啟用", release_label(analysis), "-", "未過守門不列正式保證"],
    ]
    for action in (review.get("actions") or [])[:5]:
        rows.append(["檢討修正", "已納入", "-", "-", esc(action)])
    return rows


def compact_original_rank_rows_tiantianle(analysis):
    rows = []
    for idx, item in enumerate((analysis.get("official_candidates") or analysis.get("candidates") or [])[:15], 1):
        rows.append([
            idx,
            f"{int(item.get('number')):02d}",
            compact_decimal(item.get("score"), 6),
            compact_percent(item.get("confidence_index"), 1),
            f"{item.get('omission', '-')}",
            item.get("stability_count", "-"),
            "分數排序基準",
        ])
    if not rows:
        latest = analysis.get("latest_draw") or {}
        rows.append(["基準", fmt_numbers(latest.get("numbers", [])), "-", "-", "-", "-", "最新開獎基準已載入"])
    return rows


def compact_recent_dual_track_rows_tiantianle(analysis, settled=None, snapshots=None):
    source_items = []
    seen = set()
    for item in [settled] + list(snapshots or []):
        if not item or not item.get("actual_numbers"):
            continue
        key = (item.get("based_on_date"), item.get("target_date"), item.get("actual_date"))
        if key in seen:
            continue
        seen.add(key)
        source_items.append(item)
    source_items.sort(key=lambda row: str(row.get("actual_date") or ""), reverse=True)
    rows = []
    for item in source_items[:10]:
        candidates = item.get("candidates") or []
        actual_numbers = item.get("actual_numbers") or []
        actual = set(actual_numbers)
        raw_top10 = [
            row.get("number")
            for row in sorted(candidates, key=lambda row: (-safe_float(row.get("score")), int(row.get("number", 0))))[:10]
            if isinstance(row, dict) and row.get("number") is not None
        ]
        rolling_top10 = [row.get("number") for row in candidates[:10] if isinstance(row, dict) and row.get("number") is not None]
        raw_hits = sorted(actual & set(raw_top10))
        rolling_hits = sorted(actual & set(rolling_top10))
        rows.append([
            item.get("actual_date") or item.get("target_date") or "-",
            mark_numbers(actual_numbers, actual_numbers),
            mark_numbers(raw_top10, actual_numbers),
            len(raw_hits),
            mark_numbers(rolling_top10, actual_numbers),
            len(rolling_hits),
            len(rolling_hits) - len(raw_hits),
            fmt_numbers(sorted(set(rolling_hits) - set(raw_hits))) or "-",
            fmt_numbers(sorted(set(raw_hits) - set(rolling_hits))) or "-",
        ])
    if not rows:
        latest = analysis.get("latest_draw") or {}
        candidates = analysis.get("official_candidates") or analysis.get("candidates") or []
        top10 = [row.get("number") for row in candidates[:10] if isinstance(row, dict)]
        rows.append([
            latest.get("draw_date", "-"),
            fmt_numbers(latest.get("numbers", [])),
            fmt_numbers(top10),
            "待結算",
            fmt_numbers(top10),
            "待結算",
            "每日重算",
            "已納入下期",
            "-",
        ])
    return rows


def compact_dual_track_html_tiantianle(analysis, settled=None, snapshots=None):
    comparison = analysis.get("dual_track_model_comparison") or (
        (analysis.get("industrial_engine") or {}).get("dual_track_model_comparison") or {}
    )
    backtest = industrial_backtest(analysis)
    candidates = analysis.get("official_candidates") or analysis.get("candidates") or []
    raw_top10 = [
        row.get("number")
        for row in sorted(candidates, key=lambda row: (-safe_float(row.get("score")), int(row.get("number", 0))))[:10]
        if isinstance(row, dict) and row.get("number") is not None
    ]
    rolling_top10 = [row.get("number") for row in candidates[:10] if isinstance(row, dict) and row.get("number") is not None]
    actual = set((settled or {}).get("actual_numbers") or [])
    raw_hits = len(actual & set(raw_top10)) if actual else "-"
    rolling_hits = len(actual & set(rolling_top10)) if actual else "-"
    if comparison.get("status") == "evaluated":
        summary = comparison.get("summary") or {}
        raw = summary.get("raw_unadjusted") or {}
        rolling = summary.get("rolling_adjusted") or {}
        delta = summary.get("delta") or {}
        sample_count = comparison.get("sample_count", backtest.get("rounds", "-"))
        raw_avg = compact_decimal(raw.get("top10_avg_hits"), 3)
        rolling_avg = compact_decimal(rolling.get("top10_avg_hits"), 3)
        delta_text = compact_decimal(delta.get("top10_avg_hit_delta"), 3)
        decision = summary.get("decision_label") or "已完成雙軌對照"
    else:
        sample_count = backtest.get("rounds", "-")
        raw_avg = backtest.get("top10_avg_hits", "-")
        rolling_avg = backtest.get("top10_avg_hits", "-")
        delta_text = "本期同步"
        decision = "全歷史基準與滾動排序同步檢查"
    return f"""
      <div class="band">
        <h2>雙軌模型對照（原始未調整 vs 滾動調整）</h2>
        <div class="grid">
          <div class="card"><div class="label">對照期數</div><div class="value">{esc(sample_count)}</div></div>
          <div class="card"><div class="label">原始前十平均</div><div class="value">{esc(raw_avg)}</div></div>
          <div class="card"><div class="label">滾動前十平均</div><div class="value">{esc(rolling_avg)}</div></div>
          <div class="card"><div class="label">前十差值</div><div class="value">{esc(delta_text)}</div></div>
          <div class="card"><div class="label">判定</div><div class="value">{esc(decision)}</div></div>
        </div>
        {table(["項目", "結果"], [
            ["原始未調整前十", mark_numbers(raw_top10, actual)],
            ["滾動調整前十", mark_numbers(rolling_top10, actual)],
            ["上期對照命中", f"{raw_hits} / {rolling_hits}"],
            ["原則", "每期開獎後重新結算，不沿用舊期預測"],
        ])}
      </div>
      <div class="band">
        <h2>原始模型未調整排名</h2>
        {table(["排名", "號碼", "分數", "信心", "遺漏", "穩定", "判定"], compact_original_rank_rows_tiantianle(analysis))}
      </div>
      <div class="band">
        <h2>近期逐期對照</h2>
        {table(["開獎日", "實際號", "原始前十", "原始中", "滾動前十", "滾動中", "差值", "救回", "錯殺"], compact_recent_dual_track_rows_tiantianle(analysis, settled, snapshots))}
      </div>
    """


def compact_low_review_html_tiantianle(settled):
    if not settled:
        return "<p>目前沒有已結算的低機率檢討資料。</p>"
    actual = set(settled.get("actual_numbers") or [])
    rows = []
    for key, value in (settled.get("unlikely_pack_hits") or {}).items():
        rows.append([
            value.get("name") or key,
            fmt_numbers(value.get("numbers", [])),
            "0",
            value.get("accidental_hits", 0),
            "達標" if value.get("passed") else "未達標",
            mark_numbers(value.get("hit_numbers", []), actual),
            fmt_numbers(value.get("avoided_numbers", [])),
        ])
    if not rows:
        candidates = settled.get("candidates") or []
        ranked = [item.get("number") for item in candidates if isinstance(item, dict) and item.get("number") is not None]
        fallback_packs = [
            ("5不中", ranked[-5:]),
            ("10不中", ranked[-10:]),
            ("15不中", ranked[-15:]),
        ]
        for label, numbers in fallback_packs:
            numbers = [int(number) for number in numbers if number is not None]
            hit_numbers = sorted(actual & set(numbers))
            avoided_numbers = [number for number in numbers if number not in hit_numbers]
            rows.append([
                label,
                fmt_numbers(numbers),
                "0",
                len(hit_numbers),
                "達標" if not hit_numbers else "未達標",
                mark_numbers(hit_numbers, actual),
                fmt_numbers(avoided_numbers),
            ])
    return (
        f"<p><strong>低機率檢討：{esc(settled.get('based_on_date'))} 預測到 {esc(settled.get('actual_date'))} 開獎</strong></p>"
        f'{table(["暫避包", "原暫避號", "目標誤中", "實際誤中", "結果", "誤中號", "成功避開號"], rows, "已完成低機率檢查，等待下一期結算")}'
    )


def compact_low_summary_rows_tiantianle(analysis):
    decision = analysis.get("latest_ironlaw") or analysis.get("decisive_battle_plan") or {}
    avoid = analysis.get("low_probability_avoid") or {}
    avoid_packs = decision.get("avoid_packs") or avoid.get("avoid_packs") or {}
    prediction = analysis.get("prediction") or {}
    fallbacks = {
        "five_miss": prediction.get("low_probability_5_not_hit") or [],
        "ten_miss": prediction.get("low_probability_10_not_hit") or [],
        "fifteen_miss": prediction.get("low_probability_15_not_hit") or [],
    }
    rows = []
    for key, label in [("five_miss", "5不中"), ("ten_miss", "10不中"), ("fifteen_miss", "15不中")]:
        pack = avoid_packs.get(key) or {}
        numbers = pack.get("numbers") or fallbacks.get(key) or []
        rows.append([
            label,
            fmt_numbers(numbers),
            pack.get("confidence_index", "-"),
            compact_percent(pack.get("avg_avoid_score"), 1),
            '<a href="天天樂低機率精準暫避.html">開啟低機率頁</a>',
        ])
    return rows


def build_low_probability_compact_report(analysis, settled):
    latest = analysis.get("latest_draw") or {}
    freshness = analysis.get("freshness") or {}
    avoid = analysis.get("low_probability_avoid") or {}
    backtest = avoid.get("backtest") or industrial_backtest(analysis)
    rows = compact_low_summary_rows_tiantianle(analysis)
    number_rows = []
    for group_name in ["五不中", "十不中", "十五不中"]:
        for row in avoid_group_rows(analysis, group_name):
            number_rows.append(row)
    report_time = analysis.get("generated_at_taiwan", "-")
    target_time = freshness.get("target_taiwan_safe_update_time") or analysis.get("prediction_draw_taiwan_time") or "-"
    review = compact_low_review_html_tiantianle(settled)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>天天樂 低機率精準暫避</title>
  <style>
    body{{margin:0;background:#f8fafc;color:#172033;font-family:"Microsoft JhengHei",Arial,sans-serif;}}
    header{{background:#7f1d1d;color:white;padding:22px 24px;}}
    main{{max-width:1180px;margin:0 auto;padding:18px;}}
    .band{{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:14px;overflow:auto;}}
    table{{width:100%;border-collapse:collapse;min-width:840px;}}
    th,td{{border-bottom:1px solid #e5e7eb;padding:9px;text-align:left;vertical-align:top;}}
    th{{background:#fee2e2;}}
    a{{color:#0f766e;font-weight:800;}}
  </style>
</head>
<body>
<header>
  <h1>天天樂 低機率精準暫避</h1>
  <p>產生時間 {esc(report_time)} / 最新開獎 {esc(latest.get('draw_date'))} / 下期台灣時間 {esc(target_time)}</p>
</header>
<main>
  <section class="band"><h2>低機率說明</h2><p>本頁只放經過運算的暫避號碼，用於風險控管；低機率不等於絕對不開。</p><p><a href="latest_battle_report.html">回到主戰報</a></p></section>
  <section class="band"><h2>上期低機率達標檢討</h2>{review}</section>
  <section class="band"><h2>5不中 / 10不中 / 15不中 暫避包</h2><p>回測樣本：{esc(backtest.get('rounds', '-'))} 期</p>{table(["暫避包", "號碼", "信心指標", "平均暫避分", "明細"], rows)}</section>
  <section class="band"><h2>逐號暫避細項</h2>{table(["#", "號碼", "避開信心", "等級", "出現評分", "候選排名", "避開理由"], number_rows, "本期無逐號暫避細項")}</section>
</main>
</body>
</html>"""


def build_compact_tiantianle_report(analysis, settled, snapshots=None):
    latest = analysis.get("latest_draw") or {}
    freshness = analysis.get("freshness") or {}
    decision = analysis.get("latest_ironlaw") or analysis.get("decisive_battle_plan") or {}
    prediction = analysis.get("prediction") or {}
    candidates = analysis.get("official_candidates") or analysis.get("candidates") or []
    high_numbers = [item.get("number") for item in (decision.get("high_confidence_numbers") or [])[:9]]
    if not high_numbers:
        high_numbers = prediction.get("high_confidence_watch") or []
    top9 = decision.get("nine_hit_three") or prediction.get("top9") or []
    latest_date = latest.get("draw_date") or freshness.get("latest_draw_date") or "-"
    latest_numbers = fmt_numbers(latest.get("numbers", []))
    target_time = freshness.get("target_taiwan_safe_update_time") or analysis.get("prediction_draw_taiwan_time") or "-"
    report_time = analysis.get("generated_at_taiwan", "-")
    history_info = analysis.get("history_completeness") or {}
    count = analysis.get("draw_count", "-")
    status_text = compact_status(freshness.get("status", "ok"))
    review_html = compact_review_html_tiantianle(settled)
    low_review_html = compact_low_review_html_tiantianle(settled)
    low_rows = compact_low_summary_rows_tiantianle(analysis)
    dual_track_html = compact_dual_track_html_tiantianle(analysis, settled, snapshots)
    return f"""<!doctype html>
<html lang="zh-Hant" data-compact-report="true">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>天天樂 精算預測戰報</title>
  <style>
    body{{margin:0;background:#f5f7fb;color:#172033;font-family:"Microsoft JhengHei",Arial,sans-serif;}}
    header{{background:#111827;color:white;padding:22px 24px;}}
    main{{max-width:1180px;margin:0 auto;padding:18px;}}
    .tabs{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;position:sticky;top:0;z-index:5;background:#f5f7fb;padding:10px 0;}}
    .tabs button{{border:1px solid #cbd5e1;background:white;border-radius:7px;padding:10px 14px;font-weight:800;cursor:pointer;}}
    .tabs button.active{{background:#0f766e;color:white;border-color:#0f766e;}}
    .panel{{display:none;}}
    .panel.active{{display:block;}}
    .band{{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:14px;overflow:auto;}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;}}
    .card{{border:1px solid #e5e7eb;border-radius:8px;padding:12px;background:#fbfdff;}}
    .hot-card{{border-color:#fecaca;background:#fff1f2;}}
    .singlebox{{border-color:#fecaca;background:#fffafa;}}
    .warn{{background:#fff7ed;border-color:#fed7aa;}}
    .label{{font-size:13px;color:#64748b;font-weight:700;}}
    .value{{font-size:22px;font-weight:900;margin-top:6px;}}
    table{{width:100%;border-collapse:collapse;min-width:760px;}}
    th,td{{border-bottom:1px solid #e5e7eb;padding:9px;text-align:left;vertical-align:top;}}
    th{{background:#f1f5f9;}}
    .num{{font-size:20px;font-weight:900;color:#b91c1c;}}
    a{{color:#0f766e;font-weight:800;}}
    @media(max-width:680px){{main{{padding:10px}}header{{padding:16px}}table{{min-width:680px}}}}
  </style>
</head>
<body>
<header>
  <h1>天天樂 精算預測戰報</h1>
  <p>產生時間 {esc(report_time)} / 全歷史資料 {esc(history_info.get('status', '完整'))} / 共 {esc(count)} 筆</p>
  <p>最新開獎 {esc(latest_date)} / {esc(latest_numbers)}　下期台灣時間 {esc(target_time)}</p>
</header>
<main>
  <nav class="tabs">
    <button class="active" data-tab="prediction">下期預測</button>
    <button data-tab="review">上期檢討</button>
    <button data-tab="models">模型成效</button>
    <button data-tab="avoid">低機率</button>
  </nav>
  <section id="prediction" class="panel active">
    <div class="band">
      <h2>核心決策</h2>
      <div class="grid">
        <div class="card"><div class="label">資料狀態</div><div class="value">{esc(status_text)}</div></div>
        <div class="card"><div class="label">檢查</div><div class="value">已重算</div></div>
        <div class="card"><div class="label">下期台灣時間</div><div class="value">{esc(target_time)}</div></div>
        <div class="card hot-card"><div class="label">獨隻</div><div class="value">{fmt_numbers(decision.get('primary_single') or (analysis.get('strong_packs') or {}).get('strong_single', {}).get('numbers', [])) or '-'}</div></div>
        <div class="card"><div class="label">9碼核心</div><div class="value">{fmt_numbers(top9) or '-'}</div></div>
      </div>
      <p>運算原則：只顯示完成運算後的精準資訊；依全歷史資料庫、多模型交叉驗算與滾動回測輸出。</p>
      <p><strong>高機率信心牌：</strong>{fmt_numbers(high_numbers) or "本期未過正式高信心守門"}</p>
    </div>
    {compact_super_single_html_tiantianle(analysis)}
    <div class="band">
      <h2>下期精算前9名</h2>
      {table(["號碼", "排名", "分數", "信心", "機率", "遺漏", "驗算數", "來源模型"], compact_candidate_rows_tiantianle(analysis, 9))}
    </div>
    <div class="band">
      <h2>強牌組精算</h2>
      {table(["類型", "號碼", "狀態", "回測期", "達標率", "平均命中", "判定"], compact_pack_rows_tiantianle(analysis))}
    </div>
  </section>
  <section id="review" class="panel">
    <div class="band">
      <h2>上期命中檢討</h2>
      {review_html}
    </div>
  </section>
  <section id="models" class="panel">
    {dual_track_html}
    <div class="band">
      <h2>模型回測摘要</h2>
      {table(["模型", "回測期", "前五平均", "前十平均", "前十五平均", "前十優勢"], compact_model_rows_tiantianle(analysis))}
    </div>
    <div class="band">
      <h2>強牌實戰統計</h2>
      {table(["類型", "號碼", "狀態", "回測期", "達標率", "平均命中", "判定"], compact_pack_rows_tiantianle(analysis))}
    </div>
    <div class="band">
      <h2>模型滾動調整</h2>
      {table(["模型", "動作", "近期優勢", "長期優勢", "原因"], compact_lifecycle_rows_tiantianle(analysis))}
    </div>
  </section>
  <section id="avoid" class="panel">
    <div class="band">
      <h2>低機率達標檢討</h2>
      {low_review_html}
    </div>
    <div class="band warn">
      <h2>低機率精準暫避</h2>
      <p>低機率分析已獨立開頁，主頁只保留 5不中、10不中、15不中 摘要。</p>
      <p><a href="天天樂低機率精準暫避.html">開啟 天天樂低機率精準暫避.html</a></p>
      {table(["暫避包", "號碼", "信心指標", "平均暫避分", "明細"], low_rows)}
    </div>
  </section>
</main>
<script>
  document.querySelectorAll('.tabs button').forEach(btn=>btn.addEventListener('click',()=>{{
    document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  }}));
</script>
</body>
</html>"""

def top10_promotion_rows(analysis):
    audit = ((analysis.get("industrial_engine") or {}).get("top9_frontload_audit") or {})
    candidates = analysis.get("candidates") or []
    rows = []
    for item in audit.get("promoted_to_top9", []) or []:
        rows.append([
            f"{item.get('from_rank')} -> {item.get('to_rank')}",
            f"{int(item.get('number')):02d}",
            item.get("frontload_score", "-"),
            f"{u('\\u5f8c\\u6bb5\\u547d\\u4e2d')} {item.get('late_hit_count', 0)} / {u('\\u6f0f\\u6293\\u56de\\u6536')} {item.get('missed_actual_count', 0)}",
            u("\\u5df2\\u62c9\\u5165\\u0054\\u006f\\u0070\\u0039\\u6838\\u5fc3"),
        ])
    for item in audit.get("demoted_from_top9", []) or []:
        rows.append([
            f"{item.get('from_rank')} -> {item.get('to_rank')}",
            f"{int(item.get('number')):02d}",
            item.get("frontload_score", "-"),
            u("\\u524d9\\u5f31\\u52e2\\u88ab\\u64e0\\u51fa"),
            u("\\u6539\\u5217\\u5099\\u67e5"),
        ])
    if not rows:
        for idx, item in enumerate(candidates[:9], 1):
            rows.append([idx, f"{int(item.get('number')):02d}", item.get("top9_frontload_score", "-"), item.get("stability_count", "-"), u("\\u0054\\u006f\\u0070\\u0039\\u6838\\u5fc3\\u4fdd\\u7559")])
    return safe_rows(rows)


def precision_governor_rows(analysis):
    release = ((analysis.get("industrial_engine") or {}).get("release_gate") or {})
    prev = ((analysis.get("industrial_engine") or {}).get("previous_prediction_guard") or {})
    audit = ((analysis.get("industrial_engine") or {}).get("model_audit") or {})
    strict = ((analysis.get("industrial_engine") or {}).get("strict_validation_gate") or {})
    maturity = ((analysis.get("industrial_engine") or {}).get("practical_maturity") or {})
    return [
        [u("\\u767c\\u5e03\\u72c0\\u614b"), release.get("status", "-"), release.get("actual_backtest_edge", "-"), u("\\u672a\\u904e\\u9580\\u6abb\\u5247\\u53ea\\u5217\\u89c0\\u5bdf"), "-"],
        [u("\\u5be6\\u6230\\u6210\\u719f\\u5ea6"), maturity.get("status", "-"), maturity.get("top10_avg_maturity", "-"), u("\\u672a\\u9054\\u9580\\u6abb\\u7981\\u6b62\\u6b63\\u5f0f\\u9ad8\\u4fe1\\u5fc3"), esc(maturity.get("action", "-"))],
        [u("\\u6628\\u65e5\\u91cd\\u8907\\u5b88\\u9580"), prev.get("current_top10_overlap", "-"), prev.get("current_top15_overlap", "-"), u("\\u9632\\u6b62\\u76f4\\u63a5\\u62ff\\u6628\\u65e5\\u7576\\u4eca\\u65e5"), "-"],
        [u("\\u56b4\\u8b39\\u865f\\u78bc\\u9a57\\u8b49"), strict.get("validated_count", "-"), strict.get("rejected_count", "-"), u("\\u672a\\u901a\\u904e\\u9a57\\u8b49\\u7981\\u6b62\\u9032\\u5165\\u6b63\\u5f0f\\u5019\\u9078"), esc(strict.get("policy", "-"))],
        [u("\\u98a8\\u96aa\\u5be9\\u6838"), audit.get("risk_level", "-"), esc(audit.get("verdict", "-")), u("\\u6a19\\u793a\\u98a8\\u96aa"), "-"],
    ]


def prediction_gap_diagnosis_rows(analysis):
    diagnosis = ((analysis.get("industrial_engine") or {}).get("prediction_gap_diagnosis") or {})
    rows = [[
        u("\\u65b0\\u589e\\u88dc\\u5f37\\u6a21\\u578b"),
        esc(diagnosis.get("new_model_added", "-")),
        esc(diagnosis.get("status_label", diagnosis.get("status", "-"))),
        esc(diagnosis.get("message", "-")),
    ]]
    for item in diagnosis.get("missing_elements", [])[:12]:
        rows.append([
            esc(item.get("category", "-")),
            esc(item.get("evidence", "-")),
            esc(item.get("impact", "-")),
            esc(item.get("fix", "-")),
        ])
    if len(rows) == 1:
        rows.append([
            u("\\u76ee\\u524d\\u6aa2\\u6e2c"),
            u("\\u672a\\u898b\\u91cd\\u5927\\u7d50\\u69cb\\u7f3a\\u53e3"),
            u("\\u6301\\u7e8c\\u6efe\\u52d5\\u7af6\\u8cfd"),
            u("\\u6bcf\\u671f\\u91cd\\u65b0\\u904b\\u7b97"),
        ])
    for action in (diagnosis.get("active_action_labels") or diagnosis.get("active_actions") or [])[:8]:
        rows.append([
            u("\\u5df2\\u555f\\u7528\\u52d5\\u4f5c"),
            esc(action),
            u("\\u5df2\\u7d0d\\u5165\\u4e0b\\u671f\\u6b0a\\u91cd"),
            u("\\u624b\\u6a5f\\u8207\\u96fb\\u8166\\u540c\\u6b65"),
        ])
    return safe_rows(rows)


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
        maturity = item.get("practical_maturity") or {}
        rows.append([
            idx,
            f"{int(item.get('number')):02d}",
            item.get("confidence_index", item.get("score", "")),
            confidence_note(item),
            esc(f"{maturity.get('score', '-')} / {maturity.get('tier', '-')}"),
            item.get("omission", ""),
            item.get("stability_count", "-"),
            esc(f"{strict.get('status', '-')}: {u('\\u3001').join(strict.get('gates', []))}"),
        ])
    return rows


def practical_maturity_rows(analysis):
    industrial = analysis.get("industrial_engine") or {}
    maturity = industrial.get("practical_maturity") or {}
    rows = [[
        u("\\u7e3d\\u9ad4\\u72c0\\u614b"),
        maturity.get("status", "-"),
        f"Top10 {maturity.get('top10_avg_maturity', '-')} / Top15 {maturity.get('top15_avg_maturity', '-')}",
        esc(maturity.get("required", "-")),
        esc(maturity.get("action", "-")),
    ]]
    for idx, item in enumerate(maturity.get("top10_numbers", [])[:10], 1):
        number = item.get("number")
        rows.append([
            f"#{idx}",
            f"{int(number):02d}" if number is not None else "-",
            item.get("maturity", "-"),
            esc(item.get("tier", "-")),
            f"{item.get('cross_validation_passed', 0)} {u('\\u95dc')}",
        ])
    return safe_rows(rows)


def adaptive_weight_rows(analysis):
    weights = ((analysis.get("industrial_engine") or {}).get("weights") or {})
    labels = {
        "similar_draw_knn": u("\\u76f8\\u4f3c\\u6b77\\u53f2\\u8fd1\\u9130"),
        "omission_phase_rebound": u("\\u907a\\u6f0f\\u76f8\\u4f4d\\u56de\\u5f48"),
        "regime_gap_bridge": u("\\u578b\\u614b\\u7f3a\\u53e3\\u6a4b\\u63a5"),
        "positive_edge_core": u("\\u6b63\\u908a\\u969b\\u6838\\u5fc3"),
        "bayesian_posterior": u("\\u8c9d\\u6c0f\\u5f8c\\u9a57"),
        "distribution_balance": u("\\u5206\\u5e03\\u5e73\\u8861"),
        "cross_consensus": u("\\u591a\\u6a21\\u578b\\u5171\\u8b58"),
        "monte_carlo_stability": u("\\u8499\\u5730\\u5361\\u7f85\\u7a69\\u5b9a"),
        "rank_error_correction": u("\\u6392\\u540d\\u932f\\u4f4d\\u4fee\\u6b63"),
        "missed_hit_recovery": u("\\u6f0f\\u547d\\u4e2d\\u56de\\u6536"),
    }
    rows = []
    for key, value in sorted(weights.items()):
        rows.append([esc(labels.get(key, key)), value, u("\\u4f86\\u81ea\\u5929\\u5929\\u6a02\\u56de\\u6e2c"), u("\\u6efe\\u52d5\\u4fdd\\u7559"), "-"])
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
    backtest = industrial_backtest(analysis)
    weights = industrial.get("weights") or {}
    five_pack = (analysis.get("strong_packs") or {}).get("five_hit_two") or {}
    five = five_pack.get("governance") or {}
    strategy = five.get("best_variant", "-")
    threshold_label = u("\\u9580\\u6abb")
    rows = [
        [
            u("\\u7a69\\u5b9a5\\u4e2d2~3\\u7b56\\u7565\\u7af6\\u8cfd"),
            f"{strategy} / {u('\\u9054\\u6210\\u7387')} {round(float(five.get('pass_rate', 0)) * 100, 2)}% / {threshold_label} {round(float(five.get('required_pass_rate', 0)) * 100, 2)}%",
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
    for key, item in sorted((five.get("variant_results") or {}).items()):
        rows.append([
            f"5{u('\\u78bc')} {esc(key)}",
            f"{round(float(item.get('pass_rate', 0)) * 100, 2)}% / {item.get('rounds', 0)}",
            u("\\u7b56\\u7565\\u7af6\\u8cfd\\u56de\\u6e2c\\u7d50\\u679c"),
            u("\\u5df2\\u8a08\\u7b97"),
        ])
    return safe_rows(rows)


def monthly_review_rows(analysis):
    monthly = ((analysis.get("failure_review") or {}).get("monthly_review") or {})
    if not monthly.get("has_review"):
        return [[u("\\u672c\\u6708\\u6a23\\u672c"), 0, "-", u("\\u5c1a\\u7121\\u5df2\\u7d50\\u7b97\\u9810\\u6e2c")]]
    return safe_rows([
        [u("\\u6708\\u4efd"), monthly.get("month"), u("\\u6a23\\u672c"), monthly.get("sample_size")],
        [u("Top5"), monthly.get("avg_top5_hits"), u("\\u672c\\u6708\\u5e73\\u5747\\u547d\\u4e2d"), "-"],
        [u("Top10"), monthly.get("avg_top10_hits"), u("\\u672c\\u6708\\u5e73\\u5747\\u547d\\u4e2d"), esc(monthly.get("top10_distribution"))],
        [u("Top15"), monthly.get("avg_top15_hits"), u("\\u672c\\u6708\\u5e73\\u5747\\u547d\\u4e2d"), "-"],
        [u("\\u672c\\u6708\\u53cd\\u8986\\u843d\\u7a7a\\u865f"), fmt_numbers(monthly.get("monthly_failed_numbers", [])), u("\\u4e0b\\u671f\\u8edf\\u964d\\u6b0a"), u("\\u5df2\\u5957\\u7528")],
        [u("\\u672c\\u6708\\u5f8c\\u6bb5\\u547d\\u4e2d\\u865f"), fmt_numbers([item.get("number") for item in monthly.get("monthly_late_hit_numbers", [])]), u("\\u53ef\\u4f5cTop10\\u64e0\\u5165\\u89c0\\u5bdf"), u("\\u5df2\\u5957\\u7528")],
    ])


def monthly_pack_rows(analysis):
    monthly = ((analysis.get("failure_review") or {}).get("monthly_review") or {})
    pack_summary = monthly.get("pack_summary") or {}
    labels = {
        "strong_single": u("\\u5f37\\u73681\\u4e2d1"),
        "two_hit_one": "2" + u("\\u4e2d") + "1",
        "three_hit_two": "3" + u("\\u4e2d") + "2~3",
        "five_hit_two": "5" + u("\\u4e2d") + "2~3",
        "nine_hit_three": "9" + u("\\u4e2d") + "3~5",
        "legacy_three_hit_one": u("\\u820a\\u898f\\u683c3\\u78bc\\u7d44\\uff08\\u5df2\\u505c\\u7528\\uff09"),
    }
    rows = []
    for key in ["strong_single", "two_hit_one", "three_hit_two", "five_hit_two", "nine_hit_three", "legacy_three_hit_one"]:
        item = pack_summary.get(key)
        if not item:
            continue
        rows.append([
            labels.get(key, key),
            item.get("rounds", 0),
            f"{round(float(item.get('pass_rate', 0)) * 100, 2)}%",
            item.get("avg_hits", 0),
            item.get("zero_hit_rate", 0),
            esc(item.get("status")),
        ])
    return safe_rows(rows)


def monthly_best_plan_rows(analysis):
    monthly = ((analysis.get("failure_review") or {}).get("monthly_review") or {})
    plan = monthly.get("best_rolling_plan") or {}
    rows = []
    if not plan:
        return [[u("\\u6700\\u4f73\\u65b9\\u6848"), "-", "-", u("\\u5f85\\u672c\\u6708\\u6a23\\u672c\\u7d2f\\u7a4d")]]
    rows.append([u("\\u6a21\\u5f0f"), esc(plan.get("mode")), u("\\u4e3b\\u5c64"), esc(plan.get("primary_watch_layer"))])
    rows.append([u("\\u76f8\\u5c0d\\u7a69\\u5b9a\\u7d44"), esc(plan.get("relative_stable_pack")), u("\\u6b63\\u5f0f\\u9ad8\\u6a5f\\u7387"), u("\\u7981\\u6b62") if plan.get("no_official_high_probability") else u("\\u53ef\\u653e\\u884c")])
    for item in plan.get("actions", []):
        rows.append([u("\\u52d5\\u4f5c"), esc(item), u("\\u72c0\\u614b"), u("\\u5df2\\u5957\\u7528")])
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
    release = industrial.get("release_gate") or {}
    unlikely = industrial.get("unlikely_backtest") or {}
    return [
        [u("\\u7d9c\\u5408\\u6a21\\u578b"), ibt.get("top10_avg_hits", 0), ibt.get("top15_avg_hits", 0), release.get("actual_backtest_edge", 0), u("\\u6301\\u7e8c\\u6efe\\u52d5\\u56de\\u6e2c")],
        [u("\\u66ab\\u907f\\u865f\\u6aa2\\u67e5"), unlikely.get("rounds", 0), unlikely.get("avg_accidental_hits", 0), unlikely.get("edge_vs_random", u("\\u5df2\\u5b8c\\u6210\\u98a8\\u63a7\\u6aa2\\u67e5")), u("\\u907f\\u514d\\u904e\\u5ea6\\u6392\\u9664")],
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
    maturity_summary = industrial.get("practical_maturity") or {}
    decision = analysis.get("latest_ironlaw") or analysis.get("decisive_battle_plan") or {}
    rec = ultra_precision_recommendations(analysis)
    avoid_packs = decision.get("avoid_packs") or ((analysis.get("low_probability_avoid") or {}).get("avoid_packs") or {})
    high_numbers = [item.get("number") for item in (decision.get("high_confidence_numbers") or []) if item.get("number") is not None]
    if not high_numbers:
        high_numbers = decision.get("high_confidence_core") or []
    lines = [
        "# " + u("\\u5929\\u5929\\u6a02 \\u958b\\u734e\\u9810\\u6e2c\\u6230\\u5831"),
        "",
        f"- 產生時間：{analysis.get('generated_at_taiwan')}",
        f"- 資料新鮮度：{freshness.get('status')} / 最新日期 {freshness.get('latest_draw_date')}",
        f"- 最新期別：{latest.get('period')} ({latest.get('draw_date')})",
        f"- 最新號碼：{fmt_numbers(latest.get('numbers'))}",
        f"- 最新開獎來源：{freshness.get('latest_source') or latest.get('source') or '-'}",
        f"- 最新來源確認：{freshness.get('latest_source_confirmed')}",
        f"- 預測目標日：{analysis.get('target_draw_date')}",
        f"- 預測台灣時間：{analysis.get('prediction_draw_taiwan_time') or freshness.get('target_taiwan_safe_update_time')}",
        f"- 發布等級：{release.get('status')} / {release_label(analysis)}",
        f"- 穩定共識率：{stability.get('top10_retention')}",
        f"- 實戰成熟度：{maturity_summary.get('status')} / {maturity_summary.get('top10_avg_maturity')} / {maturity_summary.get('action')}",
        f"- 風險等級：{audit.get('risk_level')}",
        "",
        "## 本期明確作戰答案",
        f"- 作戰結論：{decision.get('action_label', '-')} / 等級 {decision.get('grade', '-')}",
        f"- 明確獨支：{fmt_numbers(decision.get('primary_single', [])) or '-'}",
        f"- 明確2中1：{fmt_numbers(decision.get('two_hit_one', [])) or '-'}",
        f"- 明確3中1：{fmt_numbers(decision.get('three_hit_one', [])) or '-'}",
        f"- 明確5中2：{fmt_numbers(decision.get('five_hit_two', [])) or '-'}",
        f"- 明確9中3：{fmt_numbers(decision.get('nine_hit_three', [])) or '-'}",
        f"- 高機率信心牌：{fmt_numbers(high_numbers) or '-'}",
        f"- 防守避開：{fmt_numbers((decision.get('defensive_avoid') or [])[:10]) or '-'}",
        "",
        "## 高機率信心牌特別強調",
    ]
    for item in (decision.get("high_confidence_numbers") or [])[:9]:
        lines.append(
            f"- {int(item.get('number')):02d}：排名 {item.get('rank', '-')} / 保守機率 {item.get('model_probability_percent', '-')}% / "
            f"信心 {item.get('confidence_index', '-')} / 穩定 {item.get('stability_count', '-')} / 交叉通過 {item.get('cross_validation_passed', '-')} / {item.get('note', '-')}"
        )
    if not (decision.get("high_confidence_numbers") or []):
        for item in high_confidence_candidates(analysis, limit=9):
            _, detail, *_ = candidate_confidence_parts(item)
            lines.append(f"- {int(item.get('number')):02d}：{detail}")
    def markdown_status(value):
        mapping = {
            "official": "正式發布",
            "formal": "正式高信心",
            "high_confidence_watch": "高信心觀察",
            "research_prediction": "研究觀察",
            "watch_only": "觀察中",
            "blocked": "暫停發布",
            "strict_downshift": "嚴格降級",
        }
        return mapping.get(str(value or ""), str(value or "-"))

    lines.extend(["", "## 獨支 / 2中1 / 3中1 短包超強信心精算"])
    for key, label in [("single", "獨支1中1"), ("two", "2中1"), ("three", "3中1")]:
        item = rec.get(key) or {}
        recent_60 = item.get("recent_60") or {}
        lines.append(
            f"- {label}：{fmt_numbers(item.get('numbers', [])) or '-'} / 狀態 {markdown_status(item.get('status'))} / "
            f"多模型仲裁分 {item.get('score', item.get('precision_score', '-'))} / 60期通過率 {recent_60.get('pass_rate', '-')} / "
            f"採用模型 {item.get('selected_model_label') or item.get('selected_model') or '綜合精算'}"
        )
    lines.extend(["", "## 低機率避險包"])
    for key, label in [("five_miss", "5不中"), ("ten_miss", "10不中"), ("fifteen_miss", "15不中")]:
        pack = avoid_packs.get(key) or {}
        lines.append(
            f"- {label}：{fmt_numbers(pack.get('numbers', [])) or '-'} / {pack.get('confidence_label', '-')} / "
            f"信心指標 {pack.get('confidence_index', '-')} / 平均暫避分 {pack.get('avg_avoid_score', '-')}"
        )
    lines.extend(["", "## 每日更新鐵律時間表"])
    for row in decision.get("time_table", []) or []:
        lines.append(f"- {row.get('item', '-')}：{row.get('content', '-')}")
    lines.extend(["", "## 候選前15名"])
    for idx, item in enumerate((analysis.get("candidates") or [])[:15], 1):
        maturity = item.get("practical_maturity") or {}
        lines.append(
            f"{idx}. {int(item.get('number')):02d} / 信心 {item.get('confidence_index', item.get('score'))} / "
            f"成熟度 {maturity.get('score', '-')} {maturity.get('tier', '-')} / 遺漏 {item.get('omission')}"
        )
    if settled:
        lines.extend([
            "",
            "## 上期命中檢討",
            f"- 預測依據：{settled.get('based_on_date')} -> 實際開獎：{settled.get('actual_date')}",
            f"- 前五 / 前十 / 前十五：{settled.get('top5_hits')} / {settled.get('top10_hits')} / {settled.get('top15_hits')}",
            f"- 命中號：{fmt_numbers(settled.get('hit_numbers', [])) or '-'}",
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
    .value {{ font-size:24px; font-weight:800; letter-spacing:0; }}
    .sub {{ color:#64748b; margin:8px 0 0; font-size:13px; }}
    .confidence-line {{ color:#991b1b; font-weight:900; margin:10px 0 0; line-height:1.5; }}
    .confidence-high {{ display:inline-block; padding:4px 8px; border-radius:6px; background:#dc2626; color:white; font-weight:900; }}
    .confidence-mid {{ display:inline-block; padding:4px 8px; border-radius:6px; background:#f97316; color:white; font-weight:900; }}
    .confidence-watch {{ display:inline-block; padding:4px 8px; border-radius:6px; background:#e2e8f0; color:#334155; font-weight:900; }}
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
    .danger-zone {{ border:3px solid #991b1b; background:#fff1f2; }} .danger-zone h2 {{ color:#7f1d1d; }}
    .hotbox {{ border:2px solid #dc2626; background:#fff7ed; box-shadow:0 0 0 3px rgba(220,38,38,.08); }}
    .hotbox h2 {{ color:#991b1b; }}
    .hot-main {{ background:#fff1f2; font-weight:800; }}
    .signal-focus {{ margin:12px 0; padding:14px; border:4px solid #b91c1c; border-radius:8px; background:#fff; }}
    .signal-title {{ color:#991b1b; font-weight:900; }}
    .signal-numbers {{ color:#991b1b; font-size:38px; line-height:1.25; font-weight:900; letter-spacing:0; }}
    .signal-detail {{ color:#7f1d1d; font-weight:900; }}
    .mobile-action {{ display:block; text-align:center; padding:14px; background:#166534; color:#fff!important; text-decoration:none; border-radius:6px; font-weight:800; }}
    .mobile-action.secondary {{ background:#1d4ed8; }}
    .tabbar {{ position:sticky; top:0; z-index:5; display:flex; gap:8px; flex-wrap:wrap; background:#f6f7fb; padding:10px 0 14px; }}
    .tabbar button {{ border:1px solid #cbd5e1; background:white; color:#0f172a; border-radius:8px; padding:10px 14px; font-weight:800; cursor:pointer; }}
    .tabbar button.active {{ background:#0f172a; color:white; border-color:#0f172a; }}
    .tab-panel {{ display:none; }}
    .tab-panel.active {{ display:block; }}
    .tab-panel > .band:first-child {{ margin-top:0; }}
    details.advanced {{ margin-top:16px; border:1px solid #cbd5e1; border-radius:8px; background:#fff; padding:12px; }}
    details.advanced > summary {{ cursor:pointer; font-weight:900; color:#0f172a; }}
    details.advanced .band {{ margin-top:12px; }}
    .tabs {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:14px; }}
    .tabs a {{ display:block; text-align:center; padding:12px; border-radius:8px; background:#e5e7eb; color:#111827; font-weight:900; text-decoration:none; }}
    .tabs a.active {{ background:#166534; color:white; }}
    pre {{ white-space:pre-wrap; background:#0b1020; color:#dbeafe; border-radius:8px; padding:16px; overflow:auto; }}
    @media (max-width:640px) {{ header{{padding:16px}} header h1{{font-size:22px}} main{{padding:10px}} .grid{{grid-template-columns:1fr}} .band{{padding:12px}} th,td{{font-size:13px}} .value{{font-size:20px}} .tabs{{grid-template-columns:1fr}} }}
  </style>
</head>
<body>
<header><h1>{esc(title)}</h1><p>{subtitle}</p></header>
<main>{content}</main>
</body></html>"""


def apply_latest_battle_tabs(report_html):
    nav = (
        '<main>\n'
        '<nav class="tabbar" aria-label="' + u("\\u6230\\u5831\\u5206\\u9801") + '">'
        '<button type="button" class="active" data-tab="prediction">' + u("\\u4e0b\\u671f\\u9810\\u6e2c") + '</button>'
        '<button type="button" data-tab="avoid">' + u("\\u4f4e\\u6a5f\\u7387\\u907f\\u958b") + '</button>'
        '<button type="button" data-tab="review">' + u("\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e") + '</button>'
        '<button type="button" data-tab="models">' + u("\\u6a21\\u578b\\u56de\\u6e2c\\u8207\\u6539\\u5584\\u898f\\u5283") + '</button>'
        '</nav>'
        '<div id="prediction" class="tab-panel active"></div>'
        '<div id="avoid" class="tab-panel"></div>'
        '<div id="review" class="tab-panel"></div>'
        '<div id="models" class="tab-panel"></div>'
    )
    script = f"""
<script>
(() => {{
  const main = document.querySelector("main");
  const panels = {{
    prediction: document.getElementById("prediction"),
    avoid: document.getElementById("avoid"),
    review: document.getElementById("review"),
    models: document.getElementById("models")
  }};
  const tabbar = document.querySelector(".tabbar");
  const classify = (element) => {{
    if (element === tabbar || element.classList.contains("tab-panel")) return null;
    const title = (element.querySelector("h2")?.textContent || "").trim();
    if (element.classList.contains("grid")) return "prediction";
    if (/低機率|暫避|避開|不中/.test(title)) return "avoid";
    if (/上期|檢討|KPI|校準|滾動|歷史對比|本月|未命中/.test(title)) return "review";
    if (/模型|回測|航太|版路|穩定共識|8區|連動|輪組|成熟度|權重|改善規劃|工業級/.test(title)) return "models";
    if (/重要日期|明確作戰|高機率|本期發布|日期基準|下期預測|候選|低機率|今日|本日|終極目標|獨支|逐號/.test(title)) return "prediction";
    return "prediction";
  }};
  Array.from(main.children).forEach((element) => {{
    const target = classify(element);
    if (target) panels[target].appendChild(element);
  }});
  document.querySelectorAll(".tabbar button").forEach((button) => {{
    button.addEventListener("click", () => {{
      document.querySelectorAll(".tabbar button").forEach((item) => item.classList.remove("active"));
      Object.values(panels).forEach((panel) => panel.classList.remove("active"));
      button.classList.add("active");
      panels[button.dataset.tab].classList.add("active");
      window.scrollTo({{ top: 0, behavior: "smooth" }});
    }});
  }});
  const compactPanel = (panel, keepPattern, detailTitle) => {{
    const details = document.createElement("details");
    details.className = "advanced";
    const summary = document.createElement("summary");
    summary.textContent = detailTitle;
    details.appendChild(summary);
    Array.from(panel.children).forEach((element) => {{
      if (element.classList.contains("grid")) return;
      const title = (element.querySelector("h2")?.textContent || "").trim();
      if (!keepPattern.test(title)) details.appendChild(element);
    }});
    if (details.children.length > 1) panel.appendChild(details);
  }};
  compactPanel(
    panels.prediction,
    /重要日期|明確作戰|高機率|本期發布|日期基準|下期預測專區|精準度治理器|候選 Top 15/,
    "{u("\\u9032\\u968e\\u9810\\u6e2c\\u7d30\\u7bc0")}"
  );
  compactPanel(
    panels.avoid,
    /低機率|暫避|避開|不中/,
    "{u("\\u9032\\u968e\\u907f\\u958b\\u7d30\\u7bc0")}"
  );
  compactPanel(
    panels.review,
    /上期命中檢討摘要|上期命中檢討專區|每日檢討後滾動調整|研究命中 KPI|上期未命中/,
    "{u("\\u9032\\u968e\\u6aa2\\u8a0e\\u7d30\\u7bc0")}"
  );
  compactPanel(
    panels.models,
    /模型回測與改善規劃|自動權重校準|近期穩定度回測|進階預測模型|穩定共識/,
    "{u("\\u9032\\u968e\\u6a21\\u578b\\u7d30\\u7bc0")}"
  );
}})();
</script>
"""
    if '<nav class="tabbar"' in report_html:
        return report_html
    return report_html.replace("<main>", nav, 1).replace("</main>", "</main>" + script, 1)


def build_report():
    analysis = load_json(ANALYSIS_JSON)
    if not analysis:
        raise RuntimeError("missing latest_analysis.json")
    latest = analysis.get("latest_draw") or {}
    freshness = analysis.get("freshness") or {}
    latest_draw_date = latest.get("draw_date") or freshness.get("latest_draw_date")
    with sqlite3.connect(DB_PATH) as conn:
        snapshots = snapshot_rows(conn)
        settled = latest_settled_prediction_for_actual_date(conn, latest_draw_date) or latest_settled_snapshot(snapshots, latest_draw_date)
    industrial = analysis.get("industrial_engine") or {}
    release = industrial.get("release_gate") or {}
    stability = industrial.get("stability_consensus") or {}
    audit = industrial.get("model_audit") or {}
    regime = industrial.get("regime_analysis") or {}
    backtest = industrial_backtest(analysis)
    latest_tw_time = freshness.get("latest_taiwan_safe_update_time", "-")
    target_tw_time = freshness.get("target_taiwan_safe_update_time", "-")
    title = u("\\u5929\\u5929\\u6a02 \\u958b\\u734e\\u9810\\u6e2c\\u6230\\u5831")
    subtitle = (
        f"{u('\\u5831\\u8868\\u7522\\u751f')} {esc(analysis.get('generated_at_taiwan'))} / "
        f"{u('\\u7f8e\\u570b\\u52a0\\u5dde\\u6700\\u65b0\\u958b\\u734e\\u65e5')} {esc(latest.get('draw_date'))} / "
        f"{u('\\u53f0\\u7063\\u53ef\\u66f4\\u65b0\\u6642\\u9593')} {esc(latest_tw_time)} / "
        f"{u('\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593\\uff08\\u53f0\\u7063\\uff09')} {esc(target_tw_time)}"
    )
    release_text = release_label(analysis)
    fresh_text = u("\\u8cc7\\u6599\\u5df2\\u66f4\\u65b0") if freshness.get("status") in {"fresh", "ok", "ok_before_draw"} else freshness.get("status", "")
    md = make_markdown(analysis, settled)
    compact_html = build_compact_tiantianle_report(analysis, settled, snapshots)
    return compact_html, md, build_history_html(snapshots)

    conclusion = f"""
    <section class="band notice">
      <h2>{u('\\u672c\\u671f\\u767c\\u5e03\\u7d50\\u8ad6')}</h2>
      <p><span class="status fresh">{esc(fresh_text)}</span><span class="status blocked">{esc(release_text)}</span></p>
      <p><strong>{u('\\u904b\\u7b97\\u5f15\\u64ce')}:{esc(industrial.get('engine_version'))}</strong></p>
      <p>{u('\\u7f8e\\u570b\\u52a0\\u5dde\\u6700\\u65b0\\u958b\\u734e\\u65e5')}:{esc(freshness.get('latest_draw_date'))} / {u('\\u53f0\\u7063\\u53ef\\u66f4\\u65b0\\u6642\\u9593')}:{esc(latest_tw_time)} / {u('\\u4e0b\\u671f\\u9810\\u6e2c\\u6642\\u9593\\uff08\\u53f0\\u7063\\uff09')}:{esc(target_tw_time)} / {u('\\u7e3d\\u7b46\\u6578')}:{esc(analysis.get('draw_count'))}</p>
      <p>{u('\\u767c\\u5e03\\u5224\\u5b9a')}: Top10 {u('\\u7a69\\u5b9a\\u5171\\u8b58')} {esc(stability.get('top10_retention'))} / edge {esc(release.get('actual_backtest_edge'))} / {esc(release.get('status'))}</p>
      <p>{u('\\u63d0\\u9192\\uff1a\\u672c\\u6230\\u5831\\u70ba\\u6b77\\u53f2\\u7d71\\u8a08\\u5206\\u6790\\uff0c\\u4e0d\\u4fdd\\u8b49\\u958b\\u51fa\\u3002')}</p>
    </section>"""
    history_info = analysis.get("history_completeness") or {}
    raw_history_status = str(history_info.get("status", "-"))
    history_status = {
        "complete": "完整",
        "ok": "完整",
        "fresh": "完整",
        "partial": "不足",
        "missing": "不足",
    }.get(raw_history_status, raw_history_status)
    backtest = industrial_backtest(analysis)
    latest_review_ok = bool(settled and settled.get("actual_date") == latest_draw_date)
    review_pair = f"{settled.get('based_on_date')} -> {settled.get('actual_date')}" if settled else "-"
    full_history_rows = [
        ["\u904b\u7b97\u6bcd\u9ad4", f"{analysis.get('draw_count', 0)} \u7b46", "\u5168\u6b77\u53f2\u8cc7\u6599\u5eab", "\u672c\u671f\u9810\u6e2c\u8207\u56de\u6e2c\u90fd\u4f7f\u7528\u5b8c\u6574\u8cc7\u6599\u8868"],
        ["\u8cc7\u6599\u7bc4\u570d", esc(history_status), f"\u6700\u4f4e\u9580\u6abb {history_info.get('required_minimum', '-')}", "\u7981\u6b62\u53ea\u7528\u8fd1\u5e7e\u671f\u4ee3\u66ff\u5168\u6b77\u53f2"],
        ["\u6700\u65b0\u958b\u734e", esc(latest_draw_date), mark_numbers(latest.get("numbers"), latest.get("numbers")), esc(freshness.get("latest_source") or latest.get("source") or "-")],
        ["\u4e0a\u671f\u6aa2\u8a0e\u9396\u5b9a", esc(review_pair), "\u5df2\u5c0d\u6700\u65b0\u958b\u734e\u65e5" if latest_review_ok else "\u7981\u6b62\u820a\u671f\u9802\u66ff", esc(settled.get("review_source", "-") if settled else "\u5c1a\u7121\u6700\u65b0\u7d50\u7b97")],
        ["\u4e0b\u671f\u9810\u6e2c", esc(analysis.get("target_draw_date")), esc(target_tw_time), "\u53f0\u7063\u6642\u9593\u986f\u793a"],
        ["\u56de\u6e2c\u6458\u8981", f"{backtest.get('rounds', 0)} \u671f", f"\u524d\u5341\u5e73\u5747 {backtest.get('top10_avg_hits', '-')}", f"\u524d\u5341\u4e94\u5e73\u5747 {backtest.get('top15_avg_hits', '-')}"]
    ]
    important_dates = table(
        ["\u9805\u76ee", "\u65e5\u671f", "\u72c0\u614b", "\u8aaa\u660e"],
        [
            ["\u5831\u8868\u7522\u751f", esc(analysis.get("generated_at_taiwan")), "\u5df2\u7522\u751f", "\u672c\u6b21\u904b\u7b97\u6642\u9593"],
            ["\u6700\u65b0\u958b\u734e\u65e5", esc(latest_draw_date), esc(fresh_text), f"\u53f0\u7063\u53ef\u66f4\u65b0 {esc(latest_tw_time)}"],
            ["\u4e0b\u671f\u9810\u6e2c\u6642\u9593", esc(target_tw_time), esc(release_text), f"\u52a0\u5dde\u958b\u734e\u65e5 {esc(analysis.get('target_draw_date'))}"],
            ["\u4e0a\u671f\u6aa2\u8a0e", esc(settled.get("actual_date", "-") if settled else "-"), "\u5df2\u7cbe\u6e96\u5c0d\u61c9\u6700\u65b0\u958b\u734e" if latest_review_ok else "\u5f85\u88dc\u6700\u65b0\u56de\u6e2c", "\u4e0d\u51c6\u62ff\u820a\u671f\u6aa2\u8a0e\u9802\u66ff"],
        ],
    )
    if settled:
        settled_block = f'''
        <section class="band notice">
          <h2>\u4e0a\u671f\u547d\u4e2d\u6aa2\u8a0e\u6458\u8981</h2>
          <p>\u9810\u6e2c\u4f9d\u64da\uff1a{esc(settled.get('based_on_date'))} -> \u5be6\u969b\u958b\u734e\uff1a{esc(settled.get('actual_date'))}</p>
          <p>\u5be6\u969b\u958b\u734e\uff1a{mark_numbers(settled.get('actual_numbers'), settled.get('actual_numbers'))}</p>
          <p>\u524d\u4e94 / \u524d\u5341 / \u524d\u5341\u4e94\uff1a{settled.get('top5_hits')} / {settled.get('top10_hits')} / {settled.get('top15_hits')}\uff1b\u547d\u4e2d\u865f\uff1a{mark_numbers(settled.get('hit_numbers'), settled.get('actual_numbers')) or '-'}</p>
          <p>\u672a\u6355\u6349\u865f\uff1a{fmt_numbers(settled.get('missed_actual_numbers', [])) or '-'}</p>
          <p>\u6aa2\u8a0e\u4f86\u6e90\uff1a{esc(settled.get('review_source', '-'))}</p>
        </section>'''
    else:
        settled_block = f'''
        <section class="band notice">
          <h2>\u4e0a\u671f\u547d\u4e2d\u6aa2\u8a0e\u6458\u8981</h2>
          <p>\u6700\u65b0\u958b\u734e\u65e5 {esc(latest_draw_date)} \u5c1a\u7121\u5c0d\u61c9\u9810\u6e2c\u7d50\u7b97\uff0c\u5df2\u7981\u6b62\u7528\u820a\u671f\u6aa2\u8a0e\u9802\u66ff\uff1b\u7cfb\u7d71\u9700\u88dc\u6700\u65b0\u56de\u6e2c\u5f8c\u624d\u767c\u5e03\u6aa2\u8a0e\u3002</p>
        </section>'''
    content = f'<section class="band"><h2>\u91cd\u8981\u65e5\u671f\u5100\u8868\u677f</h2>{important_dates}</section>'
    content += f'<section class="band notice"><h2>\u5168\u6b77\u53f2\u8cc7\u6599\u5eab\u904b\u7b97\u8b49\u660e</h2>{table(["\u9805\u76ee", "\u7d50\u679c", "\u4f86\u6e90", "\u8655\u7406"], full_history_rows)}</section>'
    content += explicit_action_block(analysis)
    content += avoid_focus_block(analysis)
    content += model_backtest_focus_block(analysis)
    content += f'<section class="band"><h2>\u6bcf\u671f\u91cd\u65b0\u904b\u7b97\u8b49\u660e</h2>{table(["\u9805\u76ee", "\u7d50\u679c", "\u8aaa\u660e"], strict_recalculation_rows(analysis))}</section>'
    content += f'<section class="band notice"><h2>\u6efe\u52d5\u5f0f\u4fee\u6b63\u6458\u8981</h2>{table(["\u985e\u5225", "\u6aa2\u8a0e\u5167\u5bb9", "\u8abf\u6574\u52d5\u4f5c", "\u4f9d\u64da", "\u72c0\u614b"], rolling_adjustment_rows(analysis))}</section>'
    content += f'<section class="band chapter"><h2>\u4e0a\u671f\u672a\u547d\u4e2d\u6aa2\u8a0e\u8207\u4fee\u6b63\u5340</h2><p>\u672c\u5340\u53ea\u8655\u7406\u4e0a\u671f\u7d50\u679c\u3001\u672a\u547d\u4e2d\u539f\u56e0\u3001\u964d\u6b0a\u8207\u6efe\u52d5\u4fee\u6b63\uff0c\u4e0d\u6df7\u5165\u672c\u671f\u9810\u6e2c\u3002</p></section>'
    content += settled_block
    if settled:
        content += f'<section class="band"><h2>\u4e0a\u671f\u5be6\u969b\u958b\u734e\u9010\u865f\u6aa2\u8a0e</h2>{table(["\u865f\u78bc", "\u72c0\u614b", "\u5019\u9078\u6392\u540d", "\u547d\u4e2d\u4f86\u6e90\u95dc\u806f\u89e3\u6790"], actual_review_rows(settled))}</section>'
        content += f'<section class="band"><h2>\u4e0a\u671f\u6b63\u5f0f\u9810\u6e2c\u9010\u865f\u6aa2\u8a0e</h2>{table(["\u6392\u540d", "\u865f\u78bc", "\u7d50\u679c", "\u4fe1\u5fc3", "\u907a\u6f0f", "\u4f86\u6e90", "\u4fee\u6b63\u52d5\u4f5c"], candidate_review_rows(settled))}</section>'
        content += f'<section class="band"><h2>\u4e0a\u671f\u5f37\u724c\u7d44\u6210\u6557\u6aa2\u8a0e</h2>{table(["\u5f37\u724c", "\u539f\u9810\u6e2c", "\u76ee\u6a19", "\u5be6\u969b", "\u7d50\u679c", "\u547d\u4e2d\u865f", "\u672a\u547d\u4e2d\u865f"], pack_review_rows(settled))}</section>'
        content += f'<section class="band"><h2>\u4e0a\u671f\u7406\u7531\u6210\u6557\u7d71\u8a08</h2>{table(["\u4f86\u6e90\u7406\u7531", "\u547d\u4e2d", "\u672a\u547d\u4e2d", "\u6d89\u53ca\u865f\u78bc", "\u4fee\u6b63\u65b9\u5411"], candidate_reason_stats(settled))}</section>'
    content += f'<section class="band notice"><h2>\u672c\u6708\u4f4e\u547d\u4e2d\u7e3d\u6aa2\u8a0e\u8207\u4fee\u6b63</h2>{table(["\u9805\u76ee", "\u6578\u503c", "\u5224\u8b80", "\u72c0\u614b"], monthly_review_rows(analysis))}{table(["\u985e\u5225", "\u5167\u5bb9", "\u7ba1\u5236", "\u72c0\u614b"], monthly_best_plan_rows(analysis))}</section>'
    return page(title, subtitle, content), md, build_history_html(snapshots)


def split_prediction_review(report_html):
    if 'data-compact-report="true"' in report_html:
        def panel_inner(panel_id):
            marker = f'<section id="{panel_id}"'
            start = report_html.find(marker)
            if start < 0:
                return ""
            open_end = report_html.find(">", start)
            next_start = report_html.find('<section id="', open_end + 1)
            main_end = report_html.find("</main>", open_end + 1)
            end = next_start if next_start > 0 else main_end
            return report_html[open_end + 1:end].rsplit("</section>", 1)[0]

        head_start = report_html.find("<head>")
        head_end = report_html.find("</head>") + len("</head>")
        head = report_html[head_start:head_end] if head_start >= 0 and head_end > len("</head>") else ""
        header_start = report_html.find("<header>")
        header_end = report_html.find("</header>") + len("</header>")
        header = report_html[header_start:header_end] if header_start >= 0 and header_end > len("</header>") else ""
        nav_prediction = '<nav class="tabs"><a class="active" href="prediction.html">下期預測</a><a href="review.html">上期檢討</a><a href="latest_battle_report.html">完整戰報</a></nav>'
        nav_review = '<nav class="tabs"><a href="prediction.html">下期預測</a><a class="active" href="review.html">上期檢討</a><a href="latest_battle_report.html">完整戰報</a></nav>'
        prediction = panel_inner("prediction")
        review = panel_inner("review")
        prediction_html = f'<!doctype html><html lang="zh-Hant" data-compact-report="true">{head}<body>{header}<main>{nav_prediction}{prediction}</main></body></html>'
        review_html = f'<!doctype html><html lang="zh-Hant" data-compact-report="true">{head}<body>{header}<main>{nav_review}{review}</main></body></html>'
        prediction_html = prediction_html.replace("<title>天天樂 精算預測戰報</title>", "<title>天天樂 下期預測</title>", 1).replace("<h1>天天樂 精算預測戰報</h1>", "<h1>天天樂 下期預測</h1>", 1)
        review_html = review_html.replace("<title>天天樂 精算預測戰報</title>", "<title>天天樂 上期檢討</title>", 1).replace("<h1>天天樂 精算預測戰報</h1>", "<h1>天天樂 上期檢討</h1>", 1)
        return prediction_html, review_html

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
    prediction_inner = re.sub(r"<tr><td>[^<]*未命中[^<]*</td>.*?</tr>", "", prediction_inner, flags=re.S)
    review_inner = inner[split_at:]
    review_inner = review_inner.split(f'<section class="band"><h2>{u("\\u539f\\u59cb\\u6230\\u5831")}</h2>', 1)[0]
    nav = (
        '<nav class="tabs">'
        f'<a href="index.html">{u("\\u9996\\u9801")}</a>'
        f'<a class="active" href="prediction.html">{u("\\u4e0b\\u671f\\u9810\\u6e2c")}</a>'
        f'<a href="review.html">{u("\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e")}</a>'
        '</nav>'
    )
    review_nav = (
        '<nav class="tabs">'
        f'<a href="index.html">{u("\\u9996\\u9801")}</a>'
        f'<a href="prediction.html">{u("\\u4e0b\\u671f\\u9810\\u6e2c")}</a>'
        f'<a class="active" href="review.html">{u("\\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e")}</a>'
        '</nav>'
    )
    prediction_html = report_html[:inner_start] + nav + prediction_inner + report_html[end:]
    review_html = report_html[:inner_start] + review_nav + review_inner + report_html[end:]
    prediction_html = prediction_html.replace(
        f"<h1>{u('\\u5929\\u5929\\u6a02 \\u958b\\u734e\\u9810\\u6e2c\\u6230\\u5831')}</h1>",
        f"<h1>{u('\\u5929\\u5929\\u6a02 \\u4e0b\\u671f\\u9810\\u6e2c\\u5c08\\u9801')}</h1>",
        1,
    ).replace(
        f"<title>{u('\\u5929\\u5929\\u6a02 \\u958b\\u734e\\u9810\\u6e2c\\u6230\\u5831')}</title>",
        f"<title>{u('\\u5929\\u5929\\u6a02 \\u4e0b\\u671f\\u9810\\u6e2c')}</title>",
        1,
    )
    review_html = review_html.replace(
        f"<h1>{u('\\u5929\\u5929\\u6a02 \\u958b\\u734e\\u9810\\u6e2c\\u6230\\u5831')}</h1>",
        f"<h1>{u('\\u5929\\u5929\\u6a02 \\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e')}</h1>",
        1,
    ).replace(
        f"<title>{u('\\u5929\\u5929\\u6a02 \\u958b\\u734e\\u9810\\u6e2c\\u6230\\u5831')}</title>",
        f"<title>{u('\\u5929\\u5929\\u6a02 \\u4e0a\\u671f\\u672a\\u547d\\u4e2d\\u6aa2\\u8a0e')}</title>",
        1,
    )
    return prediction_html, review_html


def save_reports():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_html, report_md, history_html = build_report()
    analysis = load_json(ANALYSIS_JSON)
    latest = (analysis.get("latest_draw") or {}).get("draw_date")
    with sqlite3.connect(DB_PATH) as conn:
        settled = latest_settled_prediction_for_actual_date(conn, latest) or latest_settled_snapshot(snapshot_rows(conn), latest)
    low_probability_html = localize_visible_html(build_low_probability_compact_report(analysis, settled))
    tabbed_report_html = localize_visible_html(report_html if 'data-compact-report="true"' in report_html else apply_latest_battle_tabs(report_html))
    prediction_html, review_html = split_prediction_review(report_html)
    prediction_html = localize_visible_html(prediction_html)
    review_html = localize_visible_html(review_html)
    report_md = localize_plain_text(report_md)
    history_html = localize_visible_html(history_html)
    MAIN_HTML.write_text(tabbed_report_html, encoding="utf-8")
    LATEST_HTML.write_text(tabbed_report_html, encoding="utf-8")
    DASHBOARD_HTML.write_text(tabbed_report_html, encoding="utf-8")
    PREDICTION_HTML.write_text(prediction_html, encoding="utf-8")
    REVIEW_HTML.write_text(review_html, encoding="utf-8")
    LOW_PROBABILITY_HTML.write_text(low_probability_html, encoding="utf-8")
    MAIN_MD.write_text(report_md, encoding="utf-8")
    HISTORY_HTML.write_text(history_html, encoding="utf-8")
    for source, aliases in {
        MAIN_HTML: ["天天樂完整戰報.html", "最新完整戰報.html"],
        LATEST_HTML: ["天天樂最新戰報.html"],
        DASHBOARD_HTML: ["天天樂儀表板.html"],
        PREDICTION_HTML: ["下期預測.html", "天天樂下期預測.html"],
        REVIEW_HTML: ["上期未命中檢討.html", "天天樂上期未命中檢討.html"],
        LOW_PROBABILITY_HTML: ["天天樂低機率精準暫避.html", "低機率精準暫避.html"],
        MAIN_MD: ["最新戰報.md", "天天樂最新戰報.md"],
        HISTORY_HTML: ["預測歷史對比.html", "天天樂預測歷史對比.html"],
    }.items():
        for alias in aliases:
            write_alias(source, alias)
    return MAIN_HTML


if __name__ == "__main__":
    print(save_reports())



