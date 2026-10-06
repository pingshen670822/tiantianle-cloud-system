from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
ANALYSIS_PATH = REPORTS / "latest_analysis.json"
DB_PATH = ROOT / "data" / "california_fantasy5.sqlite"
TAIWAN = timezone(timedelta(hours=8))


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_analysis() -> dict[str, Any]:
    return json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))


def write_analysis(analysis: dict[str, Any]) -> None:
    text = json.dumps(analysis, ensure_ascii=True, indent=2)
    ANALYSIS_PATH.write_text(text, encoding="utf-8")
    (SITE / "latest_analysis.json").write_text(text, encoding="utf-8")
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (SITE / "data" / "latest_analysis.json").write_text(text, encoding="utf-8")
    (SITE / "reports").mkdir(parents=True, exist_ok=True)
    (SITE / "reports" / "latest_analysis.json").write_text(text, encoding="utf-8")


def latest_settled_review() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {}
    try:
        with sqlite3.connect(DB_PATH) as con:
            row = con.execute(
                """
                SELECT based_on_date,target_date,actual_date,actual_numbers_json,
                       candidates_json,strong_pack_hits_json,top5_hits,top10_hits,top15_hits
                FROM predictions
                WHERE status='settled'
                ORDER BY actual_date DESC,id DESC
                LIMIT 1
                """
            ).fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    try:
        actual = [int(x) for x in json.loads(row[3] or "[]")]
    except Exception:
        actual = []
    try:
        candidates = json.loads(row[4] or "[]")
    except Exception:
        candidates = []
    candidate_numbers = [safe_int(x.get("number")) for x in candidates if isinstance(x, dict)]
    hit_numbers = sorted(set(candidate_numbers) & set(actual))
    review = []
    for idx, item in enumerate(candidates[:15], start=1):
        if not isinstance(item, dict):
            continue
        number = safe_int(item.get("number"))
        review.append(
            {
                "rank": idx,
                "number": number,
                "hit": number in actual,
                "score": item.get("score"),
                "reasons": item.get("reasons") or [],
            }
        )
    return {
        "based_on_date": row[0],
        "target_date": row[1],
        "actual_date": row[2],
        "actual_period": row[2],
        "actual_numbers": actual,
        "candidate_numbers": candidate_numbers,
        "top5": candidate_numbers[:5],
        "top9": candidate_numbers[:9],
        "top10": candidate_numbers[:10],
        "top15": candidate_numbers[:15],
        "hit_numbers": hit_numbers,
        "top5_hit_numbers": sorted(set(candidate_numbers[:5]) & set(actual)),
        "top9_hit_numbers": sorted(set(candidate_numbers[:9]) & set(actual)),
        "top10_hit_numbers": sorted(set(candidate_numbers[:10]) & set(actual)),
        "top15_hit_numbers": sorted(set(candidate_numbers[:15]) & set(actual)),
        "rank_10_to_15_hit_numbers": sorted(set(candidate_numbers[9:15]) & set(actual)),
        "missed_actual_numbers": sorted(set(actual) - set(candidate_numbers[:15])),
        "candidate_review": review,
        "strong_pack_hits": json.loads(row[5] or "{}") if row[5] else {},
        "top5_hits": row[6],
        "top10_hits": row[7],
        "top15_hits": row[8],
    }


def pack(name: str, numbers: list[int], hit_goal: int, label: str) -> dict[str, Any]:
    return {
        "name": name,
        "hit_goal": hit_goal,
        "hit_goal_max": len(numbers),
        "target_precision_rate": 0.95,
        "goal_label": label,
        "numbers": numbers,
        "score_sum": 0,
        "avg_score": 0,
        "zones": {},
        "tails": {},
        "validation_status": "嚴格門檻全擋後的全歷史備援觀察",
    }


def repair() -> dict[str, Any]:
    analysis = load_analysis()
    prediction = analysis.setdefault("prediction", {})
    if prediction.get("top1") and prediction.get("top9"):
        return {"status": "already_non_empty", "top1": prediction.get("top1"), "top9": prediction.get("top9")}

    candidates = analysis.get("official_candidates") or analysis.get("candidates") or []
    latest_numbers = set(int(n) for n in (analysis.get("latest_draw") or {}).get("numbers") or [])
    clean = []
    seen = set()
    for item in candidates:
        if not isinstance(item, dict) or item.get("number") is None:
            continue
        number = safe_int(item.get("number"))
        if number in seen:
            continue
        seen.add(number)
        if number in latest_numbers:
            continue
        row = dict(item)
        row["no_empty_backup_selected"] = True
        row["no_empty_backup_reason"] = "嚴格門檻全擋，改用全歷史排序與最新開獎排除防呆輸出，避免戰報空白。"
        clean.append(row)
    if len(clean) < 9:
        for item in candidates:
            number = safe_int(item.get("number") if isinstance(item, dict) else item)
            if number and number not in seen:
                clean.append(dict(item, no_empty_backup_selected=True) if isinstance(item, dict) else {"number": number})
                seen.add(number)
            if len(clean) >= 9:
                break
    top = [safe_int(item.get("number")) for item in clean[:15]]
    if not top:
        raise RuntimeError("no candidates available for no-empty repair")

    prediction.update(
        {
            "strongest": top[:1],
            "top1": top[:1],
            "top2": top[:2],
            "top3": top[:3],
            "top5": top[:5],
            "top9": top[:9],
            "top10": top[:10],
            "top15": top[:15],
            "high_confidence_watch": top[:9],
            "recommendation_mode": "全歷史備援觀察",
            "recommendation_message": "最新開獎已更新；嚴格門檻本輪全擋，系統已啟用防空備援，使用全歷史排序、最新開獎排除與防呆檢查輸出下一期觀察牌。",
            "no_empty_repair": True,
            "no_empty_repair_time_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        }
    )
    packs = {
        "strong_single": pack("最強高機率獨隻", top[:1], 1, "1中1"),
        "two_hit_one": pack("最強高機率2中1~2", top[:2], 1, "2中1~2"),
        "three_hit_two": pack("最強高機率3中1~3", top[:3], 1, "3中1~3"),
        "five_hit_two": pack("最強高機率5中1~5", top[:5], 1, "5中1~5"),
        "nine_hit_three": pack("最強高機率9中1~5", top[:9], 1, "9中1~5"),
    }
    analysis["strong_packs"] = {**(analysis.get("strong_packs") or {}), **packs}
    analysis["official_candidates"] = clean + [x for x in candidates if safe_int(x.get("number") if isinstance(x, dict) else 0) not in set(top[:15])]

    selected = top[0]
    selected_candidate = next((item for item in clean if safe_int(item.get("number")) == selected), {})
    analysis["super_single_decision"] = {
        "version": "no_empty_backup_v20261006",
        "title": "最強唯一高機率獨隻",
        "status": "全歷史備援唯一輸出",
        "number": selected,
        "numbers": [selected],
        "unique": True,
        "pool_size": 1,
        "selection_rule": "嚴格門檻全擋時，禁止空白戰報；改用全歷史排序、最新開獎排除、防呆檢查後輸出唯一獨隻。",
        "why_unique": f"{selected:02d} 為本輪全歷史備援排序最高且未出現在最新開獎號碼的號碼。",
        "latest_draw_reuse": selected in latest_numbers,
        "scores": {
            "候選分數": selected_candidate.get("score"),
            "信心指標": selected_candidate.get("confidence_index"),
            "模型機率": selected_candidate.get("model_probability_percent"),
        },
        "created_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
    }
    analysis["ultimate_super_single_engine"] = {
        **(analysis.get("ultimate_super_single_engine") or {}),
        "status": "全歷史備援唯一輸出",
        "selected_number": selected,
        "selected_model": "全歷史防空備援排序",
        "candidate_audit": [
            {
                "number": safe_int(item.get("number")),
                "rank": item.get("rank"),
                "model_rank": idx,
                "model_score": item.get("score"),
                "candidate_support_score": item.get("historical_calibrated_score", item.get("score")),
                "composite_score": item.get("score"),
                "strict_gate": "備援觀察",
            }
            for idx, item in enumerate(clean[:9], start=1)
        ],
        "created_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
    }
    gate = analysis.setdefault("strict_prediction_gate", {})
    gate["status"] = "嚴格門檻全擋，已啟用防空備援"
    gate["qualified_numbers"] = top[:9]
    gate["qualified_count"] = len(top[:9])
    gate["top9_count"] = len(top[:9])
    gate["top15_count"] = len(top[:15])
    gate["no_empty_backup"] = True
    gate["created_at_taiwan"] = datetime.now(TAIWAN).isoformat(timespec="seconds")

    review = latest_settled_review()
    if review:
        failure = analysis.setdefault("failure_review", {})
        failure["has_review"] = True
        failure["last_settled"] = review
    write_analysis(analysis)
    return {
        "status": "repaired",
        "latest_draw": (analysis.get("latest_draw") or {}).get("draw_date"),
        "latest_numbers": (analysis.get("latest_draw") or {}).get("numbers"),
        "target_draw_date": analysis.get("target_draw_date"),
        "target_taiwan_time": analysis.get("prediction_draw_taiwan_time"),
        "top1": prediction.get("top1"),
        "top9": prediction.get("top9"),
    }


if __name__ == "__main__":
    print(json.dumps(repair(), ensure_ascii=False, indent=2))
