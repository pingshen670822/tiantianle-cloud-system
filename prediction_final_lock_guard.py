from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
TAIWAN = timezone(timedelta(hours=8))

ANALYSIS_PATHS = [
    REPORTS / "latest_analysis.json",
    SITE / "latest_analysis.json",
    SITE / "data" / "latest_analysis.json",
    SITE / "reports" / "latest_analysis.json",
]

LOCK_PATHS = [
    ROOT / "prediction_final_lock.json",
    REPORTS / "prediction_final_lock.json",
    SITE / "prediction_final_lock.json",
    SITE / "reports" / "prediction_final_lock.json",
]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_numbers(values: Any, limit: int | None = None) -> list[int]:
    output: list[int] = []
    for value in values or []:
        number = safe_int(value)
        if 1 <= number <= 39 and number not in output:
            output.append(number)
        if limit and len(output) >= limit:
            break
    return output


def read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def analysis_lock_key(analysis: dict[str, Any]) -> dict[str, Any]:
    latest = analysis.get("latest_draw") or {}
    return {
        "latest_draw_date": str(latest.get("draw_date") or "")[:10],
        "latest_numbers": sorted(safe_numbers(latest.get("numbers") or [], limit=5)),
        "target_draw_date": str(analysis.get("target_draw_date") or "")[:10],
        "target_taiwan_time": str(analysis.get("prediction_draw_taiwan_time") or ""),
    }


def lock_matches_analysis(lock: dict[str, Any], analysis: dict[str, Any]) -> bool:
    lock_key = lock.get("lock_key") or {}
    current_key = analysis_lock_key(analysis)
    if not lock_key:
        return False
    return all(lock_key.get(key) == current_key.get(key) for key in ["latest_draw_date", "target_draw_date"])


def lock_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    embedded = analysis.get("prediction_final_lock") or {}
    if embedded.get("final_single") is not None and lock_matches_analysis(embedded, analysis):
        return embedded
    if embedded.get("final_single") is not None and not embedded.get("lock_key"):
        embedded["lock_key"] = analysis_lock_key(analysis)
        return embedded
    for path in LOCK_PATHS:
        lock = read_json(path)
        if lock.get("final_single") is not None and lock_matches_analysis(lock, analysis):
            return lock
    return {}


def reorder_candidates(items: Any, final_single: int, final_top9: list[int]) -> list[Any]:
    if not isinstance(items, list):
        return []
    order = {number: idx for idx, number in enumerate([final_single] + [n for n in final_top9 if n != final_single])}

    def sort_key(item: Any) -> tuple[int, int]:
        if isinstance(item, dict):
            number = safe_int(item.get("number"))
            old_rank = safe_int(item.get("rank"), 999)
        else:
            number = safe_int(item)
            old_rank = 999
        return (order.get(number, 999), old_rank)

    reordered = sorted(items, key=sort_key)
    for idx, item in enumerate(reordered, start=1):
        if isinstance(item, dict):
            item["rank"] = idx
            if safe_int(item.get("number")) == final_single:
                item["final_lock_selected"] = True
                item["final_lock_reason"] = "同一期定版鎖強制同步"
    return reordered


def apply_to_payload(analysis: dict[str, Any], write_files: bool = False) -> dict[str, Any]:
    lock = lock_from_analysis(analysis)
    if not lock:
        return analysis
    final_single = safe_int(lock.get("final_single"))
    if not 1 <= final_single <= 39:
        return analysis
    final_top9 = safe_numbers(lock.get("final_top9") or [], limit=9)
    if final_single not in final_top9:
        final_top9 = [final_single] + [number for number in final_top9 if number != final_single]
    final_top9 = final_top9[:9] or [final_single]

    prediction = analysis.setdefault("prediction", {})
    prediction["strongest"] = [final_single]
    prediction["top1"] = [final_single]
    prediction["top2"] = final_top9[:2]
    prediction["top3"] = final_top9[:3]
    prediction["top5"] = final_top9[:5]
    prediction["top9"] = final_top9
    prediction["top10"] = final_top9[:10]
    prediction["top15"] = final_top9[:15]
    prediction["high_confidence_watch"] = final_top9
    prediction["final_locked_top1"] = [final_single]
    prediction["final_locked_top9"] = final_top9

    gate = analysis.setdefault("strict_prediction_gate", {})
    gate["status"] = "定版鎖強制同步"
    gate["qualified_numbers"] = final_top9
    gate["qualified_count"] = len(final_top9)
    gate["top9_count"] = len(final_top9)
    gate["top15_count"] = len(final_top9)
    gate["final_single"] = final_single
    gate["final_lock_enforced_at_taiwan"] = datetime.now(TAIWAN).isoformat(timespec="seconds")

    super_single = analysis.setdefault("super_single_decision", {})
    super_single["number"] = final_single
    super_single["numbers"] = [final_single]
    super_single["unique"] = True
    super_single["pool_size"] = 1
    super_single["locked_final"] = True
    super_single["status"] = "定版鎖唯一輸出"
    super_single["target_draw_date"] = (lock.get("lock_key") or {}).get("target_draw_date")
    super_single["target_taiwan_time"] = (lock.get("lock_key") or {}).get("target_taiwan_time")

    ultimate = analysis.setdefault("ultimate_super_single_engine", {})
    ultimate["selected_number"] = final_single
    ultimate["locked_final"] = True
    ultimate["status"] = "定版鎖唯一輸出"
    ultimate["target_draw_date"] = (lock.get("lock_key") or {}).get("target_draw_date")
    ultimate["target_taiwan_time"] = (lock.get("lock_key") or {}).get("target_taiwan_time")

    packs = analysis.setdefault("strong_packs", {})
    for key, numbers in {
        "strong_single": [final_single],
        "two_hit_one": final_top9[:2],
        "three_hit_two": final_top9[:3],
        "five_hit_two": final_top9[:5],
        "nine_hit_three": final_top9[:9],
    }.items():
        pack = packs.setdefault(key, {})
        pack["numbers"] = numbers
        pack["final_lock_enforced"] = True

    for name in ["official_candidates", "candidates"]:
        if name in analysis:
            analysis[name] = reorder_candidates(analysis.get(name), final_single, final_top9)

    normalized_lock = {
        **lock,
        "lock_key": lock.get("lock_key") or analysis_lock_key(analysis),
        "final_single": final_single,
        "final_top9": final_top9,
        "active": True,
        "guard_enforced_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        "policy": lock.get("policy") or "same_latest_draw_and_same_target_can_publish_only_one_final_prediction",
    }
    analysis["prediction_final_lock"] = normalized_lock

    if write_files:
        for path in ANALYSIS_PATHS:
            write_json(path, analysis)
        for path in LOCK_PATHS:
            write_json(path, normalized_lock)
    return analysis


def main() -> None:
    analysis = read_json(REPORTS / "latest_analysis.json")
    before = {
        "top1": (analysis.get("prediction") or {}).get("top1"),
        "super_single": (analysis.get("super_single_decision") or {}).get("number"),
        "lock": (analysis.get("prediction_final_lock") or {}).get("final_single"),
    }
    analysis = apply_to_payload(analysis, write_files=True)
    tenfold = {}
    try:
        import tenfold_validation_gate

        tenfold = tenfold_validation_gate.apply_to_files(render_report=False)
        analysis = read_json(REPORTS / "latest_analysis.json")
    except Exception as exc:
        print(json.dumps({"tenfold_validation_warning": str(exc)}, ensure_ascii=False))
    try:
        import tiantianle_ironlaw_report

        tiantianle_ironlaw_report.save_reports()
    except Exception as exc:
        print(json.dumps({"report_render_warning": str(exc)}, ensure_ascii=False))
    try:
        import top9_evaluation_report

        top9_evaluation_report.main()
    except Exception as exc:
        print(json.dumps({"top9_evaluation_warning": str(exc)}, ensure_ascii=False))
    after = {
        "top1": (analysis.get("prediction") or {}).get("top1"),
        "super_single": (analysis.get("super_single_decision") or {}).get("number"),
        "lock": (analysis.get("prediction_final_lock") or {}).get("final_single"),
        "tenfold_status": tenfold.get("status"),
        "tenfold_passed": tenfold.get("passed_count"),
        "pack_pool": tenfold.get("verified_pack_pool"),
    }
    print(json.dumps({"status": "ok", "before": before, "after": after}, ensure_ascii=False))


if __name__ == "__main__":
    main()
