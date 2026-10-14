from __future__ import annotations

import csv
import html
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

HISTORY_PATHS = [
    ROOT / "fantasy5_full_history.csv",
    ROOT / "data" / "fantasy5_full_history.csv",
    ROOT / "data" / "california_fantasy5.csv",
]

REPORT_PATHS = [
    REPORTS / "latest_tenfold_validation_gate.json",
    SITE / "latest_tenfold_validation_gate.json",
    SITE / "reports" / "latest_tenfold_validation_gate.json",
]

HTML_REPORT_PATHS = [
    REPORTS / "latest_tenfold_validation_gate.html",
    REPORTS / "十重驗證守門.html",
    SITE / "latest_tenfold_validation_gate.html",
    SITE / "reports" / "latest_tenfold_validation_gate.html",
    SITE / "reports" / "十重驗證守門.html",
]


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


def numbers(values: Any, limit: int | None = None) -> list[int]:
    output: list[int] = []
    for value in values or []:
        number = safe_int(value)
        if 1 <= number <= 39 and number not in output:
            output.append(number)
        if limit and len(output) >= limit:
            break
    return output


def fmt_numbers(values: Any) -> str:
    return " ".join(f"{number:02d}" for number in numbers(values))


def read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_date(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text)[:10])
    except Exception:
        return None


def history_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                draw_date = str(raw.get("draw_date") or raw.get("date") or "")[:10]
                nums = numbers([raw.get(f"n{i}") for i in range(1, 6)], limit=5)
                if draw_date and len(nums) == 5:
                    rows.append({"draw_date": draw_date, "numbers": nums, "source": raw.get("source") or ""})
    except Exception:
        return []
    rows.sort(key=lambda item: item["draw_date"])
    return rows


def core_payload(payload: dict[str, Any]) -> dict[str, Any]:
    latest = payload.get("latest_draw") or {}
    prediction = payload.get("prediction") or {}
    super_single = payload.get("super_single_decision") or {}
    ultimate = payload.get("ultimate_super_single_engine") or {}
    lock = payload.get("prediction_final_lock") or {}
    return {
        "generated_at_taiwan": payload.get("generated_at_taiwan") or "",
        "draw_count": safe_int(payload.get("draw_count")),
        "latest_draw_date": str(latest.get("draw_date") or "")[:10],
        "latest_numbers": numbers(latest.get("numbers") or [], limit=5),
        "target_draw_date": str(payload.get("target_draw_date") or "")[:10],
        "target_taiwan_time": str(payload.get("prediction_draw_taiwan_time") or ""),
        "top1": numbers(prediction.get("top1") or [], limit=1),
        "super_single": safe_int(super_single.get("number")),
        "ultimate_single": safe_int(ultimate.get("selected_number")),
        "lock_single": safe_int(lock.get("final_single")),
    }


def same_core(left: dict[str, Any], right: dict[str, Any]) -> bool:
    fields = [
        "draw_count",
        "latest_draw_date",
        "latest_numbers",
        "target_draw_date",
        "target_taiwan_time",
        "top1",
        "super_single",
        "ultimate_single",
        "lock_single",
    ]
    return all(left.get(field) == right.get(field) for field in fields)


def find_candidate(analysis: dict[str, Any], number: int) -> dict[str, Any]:
    for item in analysis.get("official_candidates") or analysis.get("candidates") or []:
        if isinstance(item, dict) and safe_int(item.get("number")) == number:
            return item
    return {}


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str, critical: bool = False) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(passed),
            "detail": detail,
            "critical": bool(critical),
            "status": "通過" if passed else "未通過",
        }
    )


def candidate_pack_checks(item: dict[str, Any], latest_numbers: set[int]) -> dict[str, Any]:
    number = safe_int(item.get("number"))
    previous_guard = item.get("previous_prediction_guard") or {}
    repeat_guard = item.get("repeat_guard") or {}
    cross = item.get("cross_validation") or {}
    maturity = item.get("practical_maturity") or {}
    formula = item.get("formula_engine") or {}
    checks: list[dict[str, Any]] = []
    append_check(checks, "候選資料存在", 1 <= number <= 39, f"候選號 {number:02d}")
    append_check(checks, "最新開獎重複防呆", bool(repeat_guard.get("passed")) and number not in latest_numbers, "避免剛開出號未驗證連莊")
    append_check(checks, "上期沿用防呆", bool(previous_guard.get("passed")), previous_guard.get("mode") or "防止硬搬上期")
    append_check(checks, "交叉驗算", safe_int(cross.get("passed_count")) >= 4 and safe_int(cross.get("total_count")) >= 6, f"{safe_int(cross.get('passed_count'))}/{safe_int(cross.get('total_count'))}")
    append_check(checks, "成熟度", safe_float(maturity.get("score")) >= 78, f"{safe_float(maturity.get('score')):.1f}")
    append_check(checks, "信心指標", safe_float(item.get("confidence_index")) >= 78, f"{safe_float(item.get('confidence_index')):.1f}")
    append_check(checks, "模型保守機率", safe_float(item.get("model_probability_percent")) >= 14.5, f"{safe_float(item.get('model_probability_percent')):.2f}%")
    append_check(checks, "全歷史校準分", safe_float(item.get("historical_calibrated_score")) >= 0.40, f"{safe_float(item.get('historical_calibrated_score')):.3f}")
    append_check(checks, "候選總分", safe_float(item.get("score")) >= 0.58, f"{safe_float(item.get('score')):.3f}")
    append_check(checks, "公式模組支撐", safe_float(formula.get("score")) >= 0.45 or safe_int(formula.get("positive_model_count")) >= 1, f"公式分 {safe_float(formula.get('score')):.3f}")
    append_check(checks, "全歷史模型來源", len(item.get("historical_model_sources") or []) >= 2, f"{len(item.get('historical_model_sources') or [])} 項")
    append_check(checks, "產號理由足量", len(item.get("reasons") or []) >= 3, f"{len(item.get('reasons') or [])} 項")
    append_check(checks, "主列或輔助放行", bool((item.get("entry_validation") or {}).get("passed_for_main")) or safe_float(item.get("confidence_index")) >= 85, "主列通過或高信心輔助放行")
    passed_count = sum(1 for check in checks if check["passed"])
    critical_ok = bool(previous_guard.get("passed")) and bool(repeat_guard.get("passed")) and number not in latest_numbers
    return {
        "number": number,
        "passed_count": passed_count,
        "total_count": len(checks),
        "passed": passed_count >= 10 and critical_ok,
        "critical_ok": critical_ok,
        "checks": checks,
        "score": safe_float(item.get("score")),
        "confidence_index": safe_float(item.get("confidence_index")),
        "rank": safe_int(item.get("rank"), 999),
    }


def verified_pack_pool(analysis: dict[str, Any], selected_number: int) -> list[int]:
    latest_numbers = set(numbers((analysis.get("latest_draw") or {}).get("numbers") or [], limit=5))
    rows = []
    for item in analysis.get("official_candidates") or analysis.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        validation = candidate_pack_checks(item, latest_numbers)
        item["tenfold_pack_validation"] = validation
        if validation["passed"]:
            rows.append(item)
    rows.sort(
        key=lambda item: (
            0 if safe_int(item.get("number")) == selected_number else 1,
            -safe_int((item.get("tenfold_pack_validation") or {}).get("passed_count")),
            -safe_float(item.get("confidence_index")),
            -safe_float(item.get("score")),
            safe_int(item.get("rank"), 999),
        )
    )
    pool = numbers([item.get("number") for item in rows], limit=9)
    if selected_number and selected_number not in pool:
        pool = [selected_number] + pool
    return pool[:9]


def build_gate(analysis: dict[str, Any]) -> dict[str, Any]:
    prediction = analysis.get("prediction") or {}
    latest = analysis.get("latest_draw") or {}
    super_single = analysis.get("super_single_decision") or {}
    ultimate_engine = analysis.get("ultimate_super_single_engine") or {}
    lock = analysis.get("prediction_final_lock") or {}
    strict_gate = analysis.get("strict_prediction_gate") or {}
    strong_packs = analysis.get("strong_packs") or {}

    selected = numbers(prediction.get("top1") or super_single.get("numbers") or [], limit=1)
    selected_number = selected[0] if selected else safe_int(super_single.get("number") or ultimate_engine.get("selected_number") or lock.get("final_single"))
    candidate = find_candidate(analysis, selected_number)
    candidate_ultimate = candidate.get("ultimate_super_single") or {}
    model_backtest = candidate_ultimate.get("model_backtest") or ultimate_engine.get("selected_model_backtest") or {}
    previous_guard = candidate.get("previous_prediction_guard") or {}
    repeat_guard = candidate.get("repeat_guard") or {}
    cross = candidate.get("cross_validation") or {}
    maturity = candidate.get("practical_maturity") or {}
    candidate_strict = candidate.get("strict_prediction_gate") or {}
    latest_numbers = set(numbers(latest.get("numbers") or [], limit=5))

    histories = {str(path.relative_to(ROOT).as_posix()): history_rows(path) for path in HISTORY_PATHS}
    history_latest = {}
    history_count_ok = True
    for name, rows in histories.items():
        history_count_ok = history_count_ok and len(rows) >= 10000
        history_latest[name] = rows[-1] if rows else {}

    analysis_payloads = {str(path.relative_to(ROOT).as_posix()): read_json(path) for path in ANALYSIS_PATHS}
    base_core = core_payload(analysis)
    analysis_sync_ok = all(same_core(base_core, core_payload(payload)) for payload in analysis_payloads.values() if payload)

    latest_date = str(latest.get("draw_date") or "")[:10]
    target_date = str(analysis.get("target_draw_date") or "")[:10]
    latest_dt = parse_date(latest_date)
    target_dt = parse_date(target_date)
    target_after_latest = bool(latest_dt and target_dt and target_dt > latest_dt)
    lock_key = lock.get("lock_key") or {}

    all_history_latest_ok = True
    for item in history_latest.values():
        all_history_latest_ok = (
            all_history_latest_ok
            and item.get("draw_date") == latest_date
            and sorted(numbers(item.get("numbers") or [], limit=5)) == sorted(numbers(latest.get("numbers") or [], limit=5))
        )

    selected_consistency = [
        safe_int((prediction.get("top1") or [0])[0] if prediction.get("top1") else 0),
        safe_int(super_single.get("number")),
        safe_int(ultimate_engine.get("selected_number")),
        safe_int(lock.get("final_single")),
    ]
    strong_single_numbers = numbers((strong_packs.get("strong_single") or {}).get("numbers") or [], limit=1)
    if strong_single_numbers:
        selected_consistency.append(strong_single_numbers[0])

    global_modules = (
        super_single.get("global_fusion_modules")
        or candidate_ultimate.get("feature_breakdown")
        or ultimate_engine.get("selected_feature_breakdown")
        or []
    )
    model_hit_rate = safe_float(model_backtest.get("hit_rate"))
    random_baseline = 5 / 39

    checks: list[dict[str, Any]] = []
    append_check(checks, "全歷史資料庫筆數", history_count_ok, "三份歷史檔皆需一萬期以上", True)
    append_check(checks, "三份歷史資料最新一致", all_history_latest_ok, f"最新開獎 {latest_date} / {fmt_numbers(latest.get('numbers') or [])}", True)
    append_check(checks, "主資料與手機資料同步", analysis_sync_ok, "reports、site、data、site/reports 四份分析檔必須一致", True)
    append_check(checks, "最新與預測日期遞進", target_after_latest, f"最新 {latest_date}，預測 {target_date}", True)
    append_check(
        checks,
        "定版鎖一致",
        safe_int(lock.get("final_single")) == selected_number
        and lock_key.get("latest_draw_date") == latest_date
        and lock_key.get("target_draw_date") == target_date,
        f"定版鎖 {safe_int(lock.get('final_single')):02d} / 本期獨隻 {selected_number:02d}",
        True,
    )
    append_check(
        checks,
        "獨隻唯一一致",
        selected_number > 0 and all(value == selected_number for value in selected_consistency if value),
        "主預測、獨隻決策、終極引擎、定版鎖與強牌獨隻必須同號",
        True,
    )
    append_check(checks, "候選資料存在", bool(candidate), f"候選號 {selected_number:02d} 必須有逐號驗算資料", True)
    append_check(
        checks,
        "嚴格守門通過",
        bool(candidate_strict.get("passed")) and selected_number in numbers(strict_gate.get("qualified_numbers") or []),
        "必須通過嚴格門且列入正式放行號",
        True,
    )
    append_check(checks, "上期預測沿用防呆", bool(previous_guard.get("passed")), previous_guard.get("mode") or "禁止上期預測硬搬")
    append_check(
        checks,
        "最新開獎重複防呆",
        bool(repeat_guard.get("passed")) and selected_number not in latest_numbers,
        "剛開出號未達連莊高標不得直接搶獨隻",
    )
    append_check(
        checks,
        "交叉驗算滿格",
        safe_int(cross.get("passed_count")) >= 6 and safe_int(cross.get("total_count")) >= 6,
        f"{safe_int(cross.get('passed_count'))}/{safe_int(cross.get('total_count'))}",
    )
    append_check(checks, "實戰成熟度通過", safe_float(maturity.get("score")) >= 80, f"成熟度 {safe_float(maturity.get('score')):.1f}")
    append_check(
        checks,
        "全歷史校準分通過",
        safe_float(candidate.get("historical_calibrated_score")) >= 0.40 and safe_float(candidate.get("score")) >= 0.50,
        f"校準 {safe_float(candidate.get('historical_calibrated_score')):.3f} / 總分 {safe_float(candidate.get('score')):.3f}",
    )
    append_check(checks, "多模組融合足量", len(global_modules) >= 8, f"融合模組 {len(global_modules)} 項")
    append_check(
        checks,
        "走步回測足量",
        safe_int(model_backtest.get("rounds")) >= 720,
        f"走步回測 {safe_int(model_backtest.get('rounds'))} 期",
    )
    append_check(
        checks,
        "獨隻模型勝過隨機基準",
        model_hit_rate >= random_baseline,
        f"模型 {model_hit_rate * 100:.2f}% / 基準 {random_baseline * 100:.2f}%",
    )
    low_avoid = set(numbers(prediction.get("low_probability_15_not_hit") or [], limit=15))
    append_check(checks, "低機率暫避衝突檢查", selected_number not in low_avoid, "獨隻不得同時被列入低機率暫避")

    passed_count = sum(1 for item in checks if item["passed"])
    critical_failed = [item["name"] for item in checks if item["critical"] and not item["passed"]]
    minimum_required = 10
    status = "通過" if passed_count >= minimum_required and not critical_failed else "未通過"

    pack_pool = verified_pack_pool(analysis, selected_number)

    return {
        "version": "十重驗證守門_v20261014",
        "checked_at_taiwan": datetime.now(TAIWAN).isoformat(timespec="seconds"),
        "status": status,
        "minimum_required": minimum_required,
        "total_count": len(checks),
        "passed_count": passed_count,
        "failed_count": len(checks) - passed_count,
        "critical_failed": critical_failed,
        "selected_number": selected_number,
        "target_draw_date": target_date,
        "target_taiwan_time": str(analysis.get("prediction_draw_taiwan_time") or ""),
        "latest_draw_date": latest_date,
        "latest_numbers": numbers(latest.get("numbers") or [], limit=5),
        "checks": checks,
        "verified_pack_pool": pack_pool,
        "pack_pool_size": len(pack_pool),
        "history_files": {
            name: {
                "rows": len(rows),
                "latest_draw_date": (rows[-1].get("draw_date") if rows else ""),
                "latest_numbers": (rows[-1].get("numbers") if rows else []),
            }
            for name, rows in histories.items()
        },
        "policy": "必須以全歷史資料庫重新運算，至少十項驗證通過才可出報告與標示高信心。",
    }


def gate_summary_text(gate: dict[str, Any]) -> str:
    return f"十重驗證守門：{gate.get('status')}，通過 {gate.get('passed_count')}/{gate.get('total_count')}，最低門檻 {gate.get('minimum_required')} 項。"


def apply_to_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    gate = build_gate(analysis)
    analysis["tenfold_validation_gate"] = gate
    selected_number = safe_int(gate.get("selected_number"))
    passed = gate.get("status") == "通過"

    prediction = analysis.setdefault("prediction", {})
    target_date = str(analysis.get("target_draw_date") or gate.get("target_draw_date") or "")[:10]
    target_taiwan_time = str(
        analysis.get("prediction_draw_taiwan_time")
        or gate.get("target_taiwan_time")
        or ""
    )
    prediction["prediction_date"] = target_date
    prediction["target_draw_date"] = target_date
    prediction["prediction_taiwan_time"] = target_taiwan_time
    prediction["tenfold_validation_required"] = True
    prediction["tenfold_validation_status"] = gate.get("status")
    prediction["tenfold_validation_passed_count"] = gate.get("passed_count")
    prediction["tenfold_validation_minimum"] = gate.get("minimum_required")
    prediction["tenfold_verified_numbers"] = [selected_number] if passed and selected_number else []
    pack_pool = numbers(gate.get("verified_pack_pool") or [selected_number], limit=9)
    if selected_number and selected_number not in pack_pool:
        pack_pool = [selected_number] + pack_pool
    pack_pool = pack_pool[:9]
    if passed and selected_number:
        prediction["formal_high_confidence"] = [selected_number]
        prediction["high_confidence_watch"] = pack_pool
        prediction["recommendation_mode"] = "十重驗證通過"
        prediction["recommendation_message"] = "本期定版獨隻已通過全歷史十重以上驗證，戰報允許標示高信心。"
    else:
        prediction["formal_high_confidence"] = []
        prediction["recommendation_mode"] = "十重驗證未通過"
        prediction["recommendation_message"] = "十重驗證未達標，不得標示高信心。"
    if passed and pack_pool:
        prediction["top1"] = pack_pool[:1]
        prediction["strongest"] = pack_pool[:1]
        prediction["top2"] = pack_pool[:2]
        prediction["top3"] = pack_pool[:3]
        prediction["top5"] = pack_pool[:5]
        prediction["top9"] = pack_pool[:9]
        prediction["top10"] = pack_pool[:9]
        prediction["top15"] = pack_pool[:9]
        prediction["tenfold_verified_pack_pool"] = pack_pool

    super_single = analysis.setdefault("super_single_decision", {})
    super_single["tenfold_validation"] = {
        "status": gate.get("status"),
        "passed_count": gate.get("passed_count"),
        "total_count": gate.get("total_count"),
        "minimum_required": gate.get("minimum_required"),
        "critical_failed": gate.get("critical_failed") or [],
    }
    if passed:
        super_single["status"] = "十重驗證通過・定版鎖唯一輸出"
    else:
        super_single["status"] = "十重驗證未通過・不得高信心發布"

    summary = gate_summary_text(gate)
    existing = [str(item) for item in (super_single.get("explanation") or []) if not str(item).startswith("十重驗證守門")]
    super_single["explanation"] = [summary] + existing

    strong_single = analysis.setdefault("strong_packs", {}).setdefault("strong_single", {})
    strong_single["tenfold_validation_gate"] = gate
    strong_single["validation_status"] = gate.get("status")
    packs = analysis.setdefault("strong_packs", {})
    if passed and pack_pool:
        pack_defs = {
            "strong_single": ("最強高機率獨隻1中1", 1, 1, pack_pool[:1]),
            "precision_single": ("精算獨支1中1", 1, 1, pack_pool[:1]),
            "two_hit_one": ("最強高機率2中1~2", 1, 2, pack_pool[:2]),
            "precision_two_hit_one": ("精算2中1~2", 1, 2, pack_pool[:2]),
            "three_hit_two": ("最強高機率3中1~3", 1, 3, pack_pool[:3]),
            "precision_three_hit_one": ("精算3中1~3", 1, 3, pack_pool[:3]),
            "five_hit_two": ("最強高機率5中1~5", 1, 5, pack_pool[:5]),
            "nine_hit_three": ("最強高機率9中2以上", 2, 5, pack_pool[:9]),
        }
        for key, (name, hit_goal, hit_goal_max, pack_numbers) in pack_defs.items():
            pack = packs.setdefault(key, {})
            pack.update(
                {
                    "name": name,
                    "numbers": pack_numbers,
                    "hit_goal": hit_goal,
                    "hit_goal_max": hit_goal_max,
                    "pool_size": len(pack_numbers),
                    "expected_pool_size": hit_goal_max,
                    "target_draw_date": target_date,
                    "target_taiwan_time": target_taiwan_time,
                    "status": "十重驗證同步通過",
                    "strict_no_padding": len(pack_numbers) < hit_goal_max,
                    "tenfold_verified": True,
                    "tenfold_validation_status": gate.get("status"),
                }
            )
        for key in ["latest_ironlaw", "decisive_battle_plan"]:
            section = analysis.setdefault(key, {})
            section["primary_single"] = pack_pool[:1]
            section["two_hit_one"] = pack_pool[:2]
            section["three_hit_one"] = pack_pool[:3]
            section["three_hit_two"] = pack_pool[:3]
            section["five_hit_two"] = pack_pool[:5]
            section["nine_hit_three"] = pack_pool[:9]
            section["high_confidence_core"] = pack_pool[:9]
            section["high_confidence_numbers"] = [
                {"number": number, "note": "十重驗證同步通過"}
                for number in pack_pool[:9]
            ]
    return analysis


def write_gate_reports(gate: dict[str, Any]) -> None:
    for path in REPORT_PATHS:
        write_json(path, gate)
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(item.get('name', ''))}</td>"
        f"<td>{html.escape(item.get('status', ''))}</td>"
        f"<td>{html.escape(item.get('detail', ''))}</td>"
        "</tr>"
        for item in gate.get("checks") or []
    )
    body = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>天天樂十重驗證守門</title>
  <style>
    body{{font-family:"Microsoft JhengHei",Arial,sans-serif;background:#f3f4f6;color:#111827;margin:0}}
    header{{background:#0b1220;color:white;padding:20px}}
    main{{max-width:1080px;margin:0 auto;padding:16px}}
    .band{{background:white;border:1px solid #dbe3ee;border-radius:8px;padding:16px;margin-bottom:12px}}
    table{{width:100%;border-collapse:collapse;min-width:760px}}
    th,td{{border-bottom:1px solid #e5e7eb;padding:9px;text-align:left;vertical-align:top}}
    th{{background:#f1f5f9}}
    .ok{{color:#047857;font-weight:900}}
    .bad{{color:#b91c1c;font-weight:900}}
  </style>
</head>
<body>
<header>
  <h1>天天樂十重驗證守門</h1>
  <p>檢查時間：{html.escape(str(gate.get('checked_at_taiwan') or ''))} 台灣時間</p>
</header>
<main>
  <section class="band">
    <h2>驗證結論</h2>
    <p class="{'ok' if gate.get('status') == '通過' else 'bad'}">{html.escape(gate_summary_text(gate))}</p>
    <p>預測目標：{html.escape(str(gate.get('target_draw_date') or ''))} / 台灣開獎 {html.escape(str(gate.get('target_taiwan_time') or ''))}</p>
    <p>定版獨隻：{safe_int(gate.get('selected_number')):02d}</p>
  </section>
  <section class="band">
    <h2>逐項驗證</h2>
    <table><thead><tr><th>驗證項目</th><th>狀態</th><th>細節</th></tr></thead><tbody>{rows}</tbody></table>
  </section>
</main>
</body>
</html>"""
    for path in HTML_REPORT_PATHS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def apply_to_files(render_report: bool = True) -> dict[str, Any]:
    analysis = read_json(REPORTS / "latest_analysis.json")
    if not analysis:
        raise RuntimeError("missing reports/latest_analysis.json")
    analysis = apply_to_payload(analysis)
    for path in ANALYSIS_PATHS:
        write_json(path, analysis)
    gate = analysis.get("tenfold_validation_gate") or {}
    write_gate_reports(gate)
    if render_report:
        try:
            import tiantianle_ironlaw_report

            tiantianle_ironlaw_report.save_reports()
        except Exception as exc:
            print(json.dumps({"report_render_warning": str(exc)}, ensure_ascii=False))
    return gate


def main() -> None:
    gate = apply_to_files(render_report=True)
    print(
        json.dumps(
            {
                "status": gate.get("status"),
                "passed_count": gate.get("passed_count"),
                "total_count": gate.get("total_count"),
                "minimum_required": gate.get("minimum_required"),
                "selected_number": gate.get("selected_number"),
            },
            ensure_ascii=False,
        )
    )
    if gate.get("status") != "通過":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
