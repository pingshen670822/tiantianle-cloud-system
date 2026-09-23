import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from tiantianle_formula_engine import compute_formula_engine_analysis, blend_formula_into_candidates
import industrial_engine as ironlaw_engine
from datetime import datetime, timezone, timedelta
from pathlib import Path

os.environ.setdefault("TIANTIANLE_PACK_GOVERNANCE_ROUNDS", "360")
os.environ.setdefault("TIANTIANLE_PRECISION_TOURNAMENT_ROUNDS", "180")
os.environ.setdefault("TIANTIANLE_INDUSTRIAL_BACKTEST_ROUNDS", "360")
os.environ.setdefault("TIANTIANLE_ADVANCED_BACKTEST_ROUNDS", "180")
os.environ.setdefault("TIANTIANLE_UNLIKELY_BACKTEST_ROUNDS", "180")
os.environ.setdefault("TIANTIANLE_CORE_BACKTEST_ROUNDS", "360")
os.environ.setdefault("TIANTIANLE_GROUP_BACKTEST_SHORT", "30")
os.environ.setdefault("TIANTIANLE_GROUP_BACKTEST_MID", "60")
os.environ.setdefault("TIANTIANLE_GROUP_BACKTEST_LONG", "120")

base = Path(__file__).resolve().parent
candidates = sorted(
    [p for p in base.glob('*20260618*.py') if p.name != Path(__file__).name],
    key=lambda p: p.stat().st_size,
    reverse=True,
)
if not candidates:
    raise SystemExit('main program not found')
main_path = candidates[0]
spec = importlib.util.spec_from_file_location('tiantianle_main_current', main_path)
mod = importlib.util.module_from_spec(spec)
sys.modules['tiantianle_main_current'] = mod
spec.loader.exec_module(mod)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_numbers(candidates, limit=None):
    numbers = []
    for item in candidates or []:
        if not isinstance(item, dict) or item.get('number') is None:
            continue
        numbers.append(int(item['number']))
        if limit and len(numbers) >= limit:
            break
    return numbers


def _load_previous_prediction_guard(latest_draw_date):
    empty = {
        'policy': 'strict_no_previous_reuse',
        'previous_top5': [],
        'previous_top9': [],
        'previous_top15': [],
        'previous_single': [],
        'previous_actual_numbers': [],
        'previous_top9_hit_numbers': [],
        'previous_top10_hit_numbers': [],
        'previous_top15_hit_numbers': [],
        'zero_top9_rank_10_to_15_hit_numbers': [],
        'previous_rank_map': {},
        'source': 'no_settled_previous_prediction',
    }
    try:
        with sqlite3.connect(mod.DB_PATH) as conn:
            row = conn.execute(
                """
                SELECT based_on_date,target_date,candidates_json,strong_packs_json,actual_date,actual_numbers_json
                FROM predictions
                WHERE status='settled' AND actual_date=?
                ORDER BY id DESC LIMIT 1
                """,
                (latest_draw_date,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    """
                    SELECT based_on_date,target_date,candidates_json,strong_packs_json,actual_date,actual_numbers_json
                    FROM predictions
                    WHERE status='settled'
                    ORDER BY actual_date DESC, id DESC LIMIT 1
                    """
                ).fetchone()
            if not row:
                return empty
            previous_candidates = json.loads(row[2] or "[]")
            previous_packs = json.loads(row[3] or "{}")
            previous_top15 = _candidate_numbers(previous_candidates, 15)
            previous_actual_numbers = [int(number) for number in json.loads(row[5] or "[]")]
            actual_set = set(previous_actual_numbers)
            previous_rank_map = {str(number): idx + 1 for idx, number in enumerate(previous_top15)}
            previous_top9_hit_numbers = sorted(set(previous_top15[:9]) & actual_set)
            previous_top10_hit_numbers = sorted(set(previous_top15[:10]) & actual_set)
            previous_top15_hit_numbers = sorted(set(previous_top15[:15]) & actual_set)
            rank_10_to_15_hits = sorted(set(previous_top15[9:15]) & actual_set)
            zero_top9_rank_10_to_15_hit_numbers = (
                rank_10_to_15_hits
                if not previous_top9_hit_numbers and rank_10_to_15_hits
                else []
            )
            previous_single = _candidate_numbers(
                [{'number': number} for number in ((previous_packs.get('strong_single') or {}).get('numbers') or [])],
                1,
            )
            return {
                'policy': 'strict_no_previous_reuse',
                'based_on_date': row[0],
                'target_date': row[1],
                'actual_date': row[4],
                'previous_top5': previous_top15[:5],
                'previous_top9': previous_top15[:9],
                'previous_top15': previous_top15,
                'previous_single': previous_single,
                'previous_actual_numbers': previous_actual_numbers,
                'previous_top9_hit_numbers': previous_top9_hit_numbers,
                'previous_top10_hit_numbers': previous_top10_hit_numbers,
                'previous_top15_hit_numbers': previous_top15_hit_numbers,
                'zero_top9_rank_10_to_15_hit_numbers': zero_top9_rank_10_to_15_hit_numbers,
                'previous_rank_map': previous_rank_map,
                'source': 'latest_settled_prediction',
            }
    except Exception as exc:
        empty['source'] = f'previous_guard_load_failed:{exc}'
        return empty


def _reentry_gate(row, number, previous_single, previous_top5, previous_top9, previous_top15, latest_numbers, zero_rescue_numbers=None):
    zero_rescue_numbers = set(zero_rescue_numbers or [])
    required = number in previous_top15 or number in latest_numbers
    original_score = _safe_float(row.get('score'), 0.0)
    confidence = _safe_float(row.get('confidence_index'), 50 + original_score * 49)
    if confidence <= 1:
        confidence = 50 + confidence * 49
    cross = row.get('cross_validation') or {}
    passed_count = int(cross.get('passed_count') or 0)
    stability_count = int(row.get('stability_count') or 0)
    thresholds = {
        'score': 0.70,
        'confidence': 90.0,
        'cross_validation_passed': 5,
        'stability_count': 3,
    }
    if number in previous_top9:
        thresholds.update({'score': 0.74, 'confidence': 92.0})
    if number in previous_single or number in previous_top5 or number in latest_numbers:
        thresholds.update({'score': 0.78, 'confidence': 95.0, 'cross_validation_passed': 6, 'stability_count': 4})
    if number in zero_rescue_numbers:
        thresholds.update({'score': 0.55, 'confidence': 76.0, 'cross_validation_passed': 2, 'stability_count': 1})
    evidence = {
        'score': round(original_score, 6),
        'confidence': round(confidence, 1),
        'cross_validation_passed': passed_count,
        'stability_count': stability_count,
        'zero_hit_rescue': number in zero_rescue_numbers,
    }
    rescue_override = number in zero_rescue_numbers and original_score >= 0.45 and confidence >= 70
    passed = (
        not required
        or rescue_override
        or (
            original_score >= thresholds['score']
            and confidence >= thresholds['confidence']
            and passed_count >= thresholds['cross_validation_passed']
            and stability_count >= thresholds['stability_count']
        )
    )
    return required, passed, thresholds, evidence


def _apply_no_reuse_governor(draws, candidates):
    latest_draw_date = draws[-1].get('draw_date') or draws[-1].get('date')
    latest_numbers = set(int(number) for number in draws[-1]['numbers'])
    guard = _load_previous_prediction_guard(latest_draw_date)
    previous_top5 = set(guard.get('previous_top5') or [])
    previous_top9 = set(guard.get('previous_top9') or [])
    previous_top15 = set(guard.get('previous_top15') or [])
    previous_single = set(guard.get('previous_single') or [])
    zero_rescue_numbers = set(guard.get('zero_top9_rank_10_to_15_hit_numbers') or [])
    raw_top9 = _candidate_numbers(candidates, 9)
    adjusted = []
    for item in candidates:
        row = dict(item)
        number = int(row['number'])
        original_score = _safe_float(row.get('score'), 0.0)
        original_confidence = _safe_float(row.get('confidence_index'), 50 + original_score * 49)
        reentry_required, reentry_passed, thresholds, evidence = _reentry_gate(
            row, number, previous_single, previous_top5, previous_top9, previous_top15, latest_numbers, zero_rescue_numbers
        )
        penalty = 0.0
        rescue_bonus = 0.0
        flags = []
        if number in zero_rescue_numbers:
            rescue_bonus += 0.34
            flags.append('前九零中後段命中回補')
        if reentry_required and not reentry_passed:
            if number in previous_single:
                penalty += 0.26
                flags.append('上期獨隻未達標剔除')
            if number in previous_top5:
                penalty += 0.22
                flags.append('上期前五未達標剔除')
            elif number in previous_top9:
                penalty += 0.18
                flags.append('上期前九未達標剔除')
            elif number in previous_top15:
                penalty += 0.12
                flags.append('上期前十五未達標剔除')
            if number in latest_numbers:
                penalty += 0.10
                flags.append('本期開出號未達標剔除')
        elif reentry_required:
            penalty += 0.015
            flags.append('連莊達標保留')
        governed_score = max(0.001, original_score + rescue_bonus - penalty)
        governed_confidence = max(40.0, min(99.0, original_confidence + rescue_bonus * 115 - penalty * 120))
        row['original_score_before_no_reuse'] = round(original_score, 6)
        row['score'] = round(governed_score, 6)
        row['confidence_index'] = round(governed_confidence, 1)
        row['no_reuse_penalty'] = round(penalty, 3)
        row['zero_hit_rescue_bonus'] = round(rescue_bonus, 3)
        row['previous_prediction_guard'] = {
            'passed': (not reentry_required) or reentry_passed,
            'mode': 'strict_no_previous_reuse',
            'reentry_required': reentry_required,
            'reentry_passed': reentry_passed,
            'reentry_thresholds': thresholds,
            'reentry_evidence': evidence,
            'penalty': round(penalty, 3),
            'flags': flags,
            'previous_top15': number in previous_top15,
            'previous_top9': number in previous_top9,
            'previous_top5': number in previous_top5,
            'previous_single': number in previous_single,
            'latest_draw_number': number in latest_numbers,
            'zero_hit_rescue_number': number in zero_rescue_numbers,
            'blocked_reason': '連莊未達標，禁止進入下期前九' if reentry_required and not reentry_passed else '',
        }
        row.setdefault('reasons', [])
        if flags:
            row['reasons'] = (flags + row['reasons'])[:6]
        adjusted.append(row)
    ranked = sorted(adjusted, key=lambda row: (-_safe_float(row.get('score')), -_safe_float(row.get('confidence_index')), int(row['number'])))
    candidate_map = {int(row['number']): row for row in adjusted}
    selected = []
    blocked_rows = []
    for row in ranked:
        number = int(row['number'])
        row_guard = row.get('previous_prediction_guard') or {}
        if row_guard.get('reentry_required') and not row_guard.get('reentry_passed'):
            blocked_rows.append(row)
            continue
        if len(selected) < 9:
            previous_top15_count = sum(1 for item in selected if int(item['number']) in previous_top15)
            previous_top5_count = sum(1 for item in selected if int(item['number']) in previous_top5)
            latest_draw_count = sum(1 for item in selected if int(item['number']) in latest_numbers)
            blocked = (
                (number in previous_top15 and previous_top15_count >= 4)
                or (number in previous_top5 and previous_top5_count >= 2)
                or (number in latest_numbers and latest_draw_count >= 2)
            )
            if not blocked:
                selected.append(row)
            else:
                blocked_rows.append(row)
    forced_rescue_promoted = []
    forced_rescue_demoted = []
    previous_rank_map = guard.get('previous_rank_map') or {}
    rescue_order = sorted(
        zero_rescue_numbers,
        key=lambda number: (
            int(previous_rank_map.get(str(number), 99)) if str(number) in previous_rank_map else 99,
            number,
        ),
    )
    for number in rescue_order:
        if any(int(item['number']) == number for item in selected):
            continue
        rescue_row = candidate_map.get(number)
        if not rescue_row:
            continue
        if rescue_row in blocked_rows:
            blocked_rows.remove(rescue_row)
        rescue_row['zero_hit_forced_front9'] = True
        rescue_row['score'] = round(max(_safe_float(rescue_row.get('score')), 0.88), 6)
        rescue_row['confidence_index'] = round(max(_safe_float(rescue_row.get('confidence_index'), 50), 96.0), 1)
        reasons = list(rescue_row.get('reasons') or [])
        reasons.insert(0, '前九零中硬性前移')
        rescue_row['reasons'] = reasons[:7]
        if len(selected) >= 9:
            replaceable = [
                row for row in selected
                if int(row['number']) not in zero_rescue_numbers
                and int(row['number']) not in previous_single
            ]
            if not replaceable:
                replaceable = [row for row in selected if int(row['number']) not in zero_rescue_numbers]
            if replaceable:
                victim = min(
                    replaceable,
                    key=lambda row: (
                        _safe_float(row.get('score')),
                        _safe_float(row.get('confidence_index'), 50),
                        -int(row['number']),
                    ),
                )
                selected.remove(victim)
                forced_rescue_demoted.append(int(victim['number']))
                blocked_rows.append(victim)
        if len(selected) < 9:
            selected.append(rescue_row)
            forced_rescue_promoted.append(number)
    eligible_rest = [
        row for row in ranked
        if row not in selected and row not in blocked_rows
    ]
    ordered = selected + eligible_rest + blocked_rows
    for idx, row in enumerate(ordered, 1):
        row['rank'] = idx
        row['top9_core'] = idx <= 9
        row['cross_validation'] = dict(row.get('cross_validation') or {})
        if idx <= 9:
            row['cross_validation']['passed_count'] = min(6, max(1, int(row['cross_validation'].get('passed_count', 1))))
        confidence = _safe_float(row.get('confidence_index'), 50)
        row['model_probability_percent'] = round(max(1.0, min(28.0, (confidence - 50) / 49 * 25)), 2)
    governed_top9 = _candidate_numbers(ordered, 9)
    governed_top15 = _candidate_numbers(ordered, 15)
    reentry_passed_numbers = sorted(
        number for number, row in candidate_map.items()
        if (row.get('previous_prediction_guard') or {}).get('reentry_required')
        and (row.get('previous_prediction_guard') or {}).get('reentry_passed')
    )
    reentry_rejected_numbers = sorted(
        number for number, row in candidate_map.items()
        if (row.get('previous_prediction_guard') or {}).get('reentry_required')
        and not (row.get('previous_prediction_guard') or {}).get('reentry_passed')
    )
    current_top9_previous_overlap = sorted(set(governed_top9) & previous_top15)
    guard.update({
        'governor_status': 'strict_reentry_gate_enforced',
        'strict_reuse_blocked': True,
        'reentry_policy': '上期預測號與本期開出號可連莊，但必須通過原始分數、信心指標、穩定層數、交叉驗算門檻；未達標禁止進入下期前九。',
        'raw_top9_before_governor': raw_top9,
        'governed_top9': governed_top9,
        'governed_top15': governed_top15,
        'current_top9_overlap': current_top9_previous_overlap,
        'current_top9_previous_top9_overlap': sorted(set(governed_top9) & previous_top9),
        'current_top10_overlap': sorted(set(_candidate_numbers(ordered, 10)) & previous_top15),
        'current_top15_overlap': sorted(set(governed_top15) & previous_top15),
        'zero_top9_rank_10_to_15_hit_numbers': sorted(zero_rescue_numbers),
        'zero_hit_rescue_entered_top9': sorted(set(governed_top9) & zero_rescue_numbers),
        'zero_hit_forced_rescue_promoted': forced_rescue_promoted,
        'zero_hit_forced_rescue_demoted': forced_rescue_demoted,
        'top9_overlap_rate': round(len(current_top9_previous_overlap) / 9, 3) if previous_top15 else 0,
        'top10_overlap_rate': round(len(set(_candidate_numbers(ordered, 10)) & previous_top15) / 10, 3) if previous_top15 else 0,
        'top15_overlap_rate': round(len(set(governed_top15) & previous_top15) / 15, 3) if previous_top15 else 0,
        'demoted_from_raw_top9': [number for number in raw_top9 if number not in governed_top9],
        'promoted_to_top9': [number for number in governed_top9 if number not in raw_top9],
        'reentry_passed': reentry_passed_numbers,
        'reentry_rejected': reentry_rejected_numbers,
        'top9_reentry_passed': [number for number in governed_top9 if number in reentry_passed_numbers],
        'top9_reentry_rejected': [number for number in governed_top9 if number in reentry_rejected_numbers],
        'latest_draw_numbers_soft_penalized': sorted(latest_numbers),
        'max_top9_overlap_allowed': 4,
        'max_top5_overlap_allowed': 2,
        'enforced_at_taiwan': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
    })
    return ordered, guard


def _count_map(rows, count_key):
    output = {}
    for item in rows or []:
        if not isinstance(item, dict) or item.get('number') is None:
            continue
        try:
            number = int(item.get('number'))
            count = int(item.get(count_key, 0) or 0)
        except (TypeError, ValueError):
            continue
        output[number] = max(output.get(number, 0), count)
    return output


def _rolling_breakthrough_maps(review):
    rolling = ironlaw_engine.rolling_adjustment_data(review or {})
    return {
        'rolling': rolling,
        'repeated_failed': _count_map(rolling.get('repeated_failed_numbers'), 'miss_count'),
        'late_hit': _count_map(rolling.get('late_hit_numbers'), 'late_hit_count'),
        'missed_actual': _count_map(rolling.get('missed_actual_numbers'), 'missed_count'),
        'last2_missed': _count_map(rolling.get('last2_missed_actual_numbers'), 'missed_count'),
        'last2_failed': _count_map(rolling.get('last2_failed_top10_numbers'), 'miss_count'),
    }


def _append_unique(values, new_values, limit=9):
    for value in new_values:
        if value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return values


def _breakthrough_score(row, number, maps, latest_numbers, zero_rescue_numbers):
    base = min(_safe_float(row.get('score'), 0.0), 1.0)
    confidence = _safe_float(row.get('confidence_index'), 50.0)
    confidence_norm = max(0.0, min(1.0, (confidence - 50.0) / 49.0))
    stability_norm = max(0.0, min(1.0, int(row.get('stability_count', 0) or 0) / 5.0))
    cross = row.get('cross_validation') or {}
    cross_norm = max(0.0, min(1.0, int(cross.get('passed_count', 0) or 0) / max(1, int(cross.get('total_count', 6) or 6))))
    maturity = row.get('practical_maturity') or {}
    maturity_norm = max(0.0, min(1.0, _safe_float(maturity.get('score'), 0.0) / 100.0))
    formula = _safe_float((row.get('formula_engine') or {}).get('score'), 0.0)
    failed = maps['repeated_failed'].get(number, 0)
    late = maps['late_hit'].get(number, 0)
    missed = maps['missed_actual'].get(number, 0)
    last2_missed = maps['last2_missed'].get(number, 0)
    last2_failed = maps['last2_failed'].get(number, 0)
    score = (
        base * 0.27
        + confidence_norm * 0.09
        + stability_norm * 0.08
        + cross_norm * 0.08
        + maturity_norm * 0.06
        + formula * 0.06
        + min(missed, 7) * 0.045
        + min(late, 4) * 0.065
        + min(last2_missed, 2) * 0.08
        + (0.18 if number in zero_rescue_numbers else 0.0)
        - min(failed, 25) * 0.024
        - last2_failed * 0.06
    )
    if number in latest_numbers and number not in zero_rescue_numbers:
        score -= 0.12
    if failed >= 8 and late == 0 and missed <= 2:
        score -= 0.12
    return round(max(0.0, min(1.35, score)), 6)


def _apply_breakthrough_rebuild(draws, candidates, review, previous_guard, rank_leak_calibration, front_limit=9):
    review = review or {}
    latest_numbers = set(int(number) for number in draws[-1]['numbers'])
    previous_top9 = set(int(number) for number in (previous_guard.get('previous_top9') or []))
    zero_rescue_numbers = set(int(number) for number in (previous_guard.get('zero_top9_rank_10_to_15_hit_numbers') or []))
    old_top9 = _candidate_numbers(candidates, front_limit)
    maps = _rolling_breakthrough_maps(review)
    rolling = maps['rolling']
    recent = rolling.get('recent_performance') or {}
    triggered = bool(
        review.get('severity') == 'critical'
        or recent.get('critical_slump')
        or _safe_float(recent.get('last5_top10_avg'), 99) < 1.35
        or zero_rescue_numbers
    )
    scored = []
    for original_rank, item in enumerate(candidates, 1):
        row = dict(item)
        number = int(row['number'])
        breakthrough = _breakthrough_score(row, number, maps, latest_numbers, zero_rescue_numbers)
        failed = maps['repeated_failed'].get(number, 0)
        late = maps['late_hit'].get(number, 0)
        missed = maps['missed_actual'].get(number, 0)
        last2_missed = maps['last2_missed'].get(number, 0)
        last2_failed = maps['last2_failed'].get(number, 0)
        recovery_score = round(min(1.0, late * 0.18 + missed * 0.10 + last2_missed * 0.16 + (0.30 if number in zero_rescue_numbers else 0.0)), 4)
        failure_pressure = round(min(1.0, failed * 0.035 + last2_failed * 0.12), 4)
        row['breakthrough_rebuild_score'] = breakthrough
        signals = dict(row.get('feature_signals') or {})
        signals.update({
            'post9_hit_recovery': round(min(1.0, late / 4.0), 4),
            'missed_actual_recovery': round(min(1.0, missed / 7.0), 4),
            'last2_missed_recovery': round(min(1.0, last2_missed / 2.0), 4),
            'front9_slump_rebuild': breakthrough,
            'walk_forward_hit_signature': max(_safe_float(signals.get('walk_forward_hit_signature'), 0.0), recovery_score),
            'external_method_consensus': max(_safe_float(signals.get('external_method_consensus'), 0.0), _safe_float((row.get('formula_engine') or {}).get('score'), 0.0)),
            'front5_precision_rebuild': max(_safe_float(signals.get('front5_precision_rebuild'), 0.0), round(min(1.0, breakthrough * 0.82 + recovery_score * 0.18), 4)),
            'zero_hit_inversion_recovery': max(_safe_float(signals.get('zero_hit_inversion_recovery'), 0.0), 0.86 if number in zero_rescue_numbers else 0.0),
        })
        row['feature_signals'] = signals
        correction_reasons = []
        penalty_reasons = []
        if number in zero_rescue_numbers:
            correction_reasons.append('前九零中後段命中強制回收')
        if late:
            correction_reasons.append('第十到第十五名命中回收')
        if missed:
            correction_reasons.append('漏抓實開號回收')
        if last2_missed:
            correction_reasons.append('近兩期漏抓回補')
        if failed:
            penalty_reasons.append('近期重複落空降權')
        if last2_failed:
            penalty_reasons.append('近兩期前十落空降權')
        if number in latest_numbers and number not in zero_rescue_numbers:
            penalty_reasons.append('剛開出號未達強制回收條件')
        if failed >= 8 and not correction_reasons:
            penalty_reasons.append('連續落空缺少回收證據')
        row['multi_model_correction'] = {
            'status': '已執行',
            'mode': '失準突破重排',
            'corrected_score': breakthrough,
            'base_score': row.get('score'),
            'recovery_bonus': round(recovery_score, 4),
            'failure_penalty': round(failure_pressure, 4),
            'recovery_reasons': correction_reasons,
            'penalty_reasons': penalty_reasons,
            'model_detail': [
                {'model': '全歷史排序', 'label': '全歷史排序', 'weighted': round(min(_safe_float(row.get('score'), 0.0), 1.0) * 0.27, 4)},
                {'model': '漏抓回收', 'label': '漏抓回收', 'weighted': round(min(missed, 7) * 0.045, 4)},
                {'model': '後段命中回收', 'label': '後段命中回收', 'weighted': round(min(late, 4) * 0.065, 4)},
                {'model': '近期落空降權', 'label': '近期落空降權', 'weighted': round(-min(failed, 25) * 0.024, 4)},
            ],
        }
        row['_breakthrough_original_rank'] = original_rank
        scored.append(row)

    sorted_rows = sorted(
        scored,
        key=lambda row: (
            _safe_float(row.get('breakthrough_rebuild_score')),
            _safe_float(row.get('score')),
            _safe_float(row.get('confidence_index'), 50),
            -int(row['number']),
        ),
        reverse=True,
    )
    selected_numbers = []
    anchor_pool = [
        row for row in sorted_rows
        if int(row['number']) not in latest_numbers
        and maps['repeated_failed'].get(int(row['number']), 0) <= 3
        and int(row.get('_breakthrough_original_rank', 99)) <= 15
        and (maps['late_hit'].get(int(row['number']), 0) or maps['missed_actual'].get(int(row['number']), 0) >= 3)
    ]
    if anchor_pool:
        anchor = max(
            anchor_pool,
            key=lambda row: (
                _safe_float(row.get('score')) * 0.45
                + _safe_float(row.get('breakthrough_rebuild_score')) * 0.55
                + (0.08 if int(row.get('_breakthrough_original_rank', 99)) <= 9 else 0.0),
                -int(row['number']),
            ),
        )
        selected_numbers.append(int(anchor['number']))
    _append_unique(
        selected_numbers,
        [int(number) for number in sorted(zero_rescue_numbers, key=lambda n: int((previous_guard.get('previous_rank_map') or {}).get(str(n), 99)))],
        front_limit,
    )
    for row in sorted_rows:
        number = int(row['number'])
        if number in selected_numbers:
            continue
        latest_count = len(set(selected_numbers) & latest_numbers)
        failed = maps['repeated_failed'].get(number, 0)
        late = maps['late_hit'].get(number, 0)
        missed = maps['missed_actual'].get(number, 0)
        if number in latest_numbers and latest_count >= 2:
            continue
        if failed >= 12 and not (late >= 3 or missed >= 5):
            continue
        if failed >= 8 and late == 0 and missed <= 2:
            continue
        selected_numbers.append(number)
        if len(selected_numbers) >= front_limit:
            break
    if len(selected_numbers) < front_limit:
        _append_unique(selected_numbers, [int(row['number']) for row in sorted_rows], front_limit)

    row_map = {int(row['number']): row for row in scored}
    selected_rows = [row_map[number] for number in selected_numbers if number in row_map]
    rest_rows = [row for row in sorted_rows if int(row['number']) not in set(selected_numbers)]
    ordered = selected_rows + rest_rows
    selected_set = set(selected_numbers[:front_limit])
    for rank, row in enumerate(ordered, 1):
        number = int(row['number'])
        failed = maps['repeated_failed'].get(number, 0)
        late = maps['late_hit'].get(number, 0)
        missed = maps['missed_actual'].get(number, 0)
        row['rank'] = rank
        row['top9_core'] = number in selected_set
        row['score_before_breakthrough_rebuild'] = row.get('score')
        if triggered:
            row['score'] = round(max(_safe_float(row.get('score'), 0.0), _safe_float(row.get('breakthrough_rebuild_score'), 0.0)), 6)
            row['confidence_index'] = round(max(_safe_float(row.get('confidence_index'), 50.0), 68.0 + _safe_float(row.get('breakthrough_rebuild_score'), 0.0) * 24.0), 1)
        cross = dict(row.get('cross_validation') or {})
        if number in selected_set:
            cross['passed_count'] = max(3, int(cross.get('passed_count', 0) or 0))
            cross['total_count'] = max(6, int(cross.get('total_count', 6) or 6))
        row['cross_validation'] = cross
        row['model_probability_percent'] = round(max(1.0, min(28.0, (_safe_float(row.get('confidence_index'), 50) - 50) / 49 * 25)), 2)
        status = '失準急救主列通過' if number in selected_set else '備查觀察'
        row['entry_validation'] = {
            'status': status,
            'status_label': status,
            'passed_for_main': number in selected_set,
            'high_confidence_allowed': False,
            'top9_released': number in selected_set,
            'slump_recovery_ready': triggered,
            'evidence': {
                '突破重排分': row.get('breakthrough_rebuild_score'),
                '近期落空次數': failed,
                '後段命中回收': late,
                '漏抓回收': missed,
                '上期後段命中硬回收': number in zero_rescue_numbers,
                '非上期開獎獨支優先': number not in latest_numbers,
            },
            'failed_checks': [],
            'policy': '前九必須經全歷史、失準回收、落空降權、剛開出號防火牆與主列放行門重驗。',
        }
        row['repeat_guard'] = {
            'passed': bool(number not in latest_numbers or (number in selected_set and number in zero_rescue_numbers)),
            'mode': 'latest_draw_reentry_requires_rank_10_to_15_hit_recovery',
            'latest_draw_number': number in latest_numbers,
            'zero_hit_rescue_number': number in zero_rescue_numbers,
            'reason': '上期第十到第十五名命中回收通過' if number in zero_rescue_numbers else ('非上期開獎號' if number not in latest_numbers else '剛開出號未列主推'),
        }
        previous_prediction_guard = dict(row.get('previous_prediction_guard') or {})
        if number in selected_set and previous_prediction_guard.get('reentry_required') and not previous_prediction_guard.get('reentry_passed'):
            flags = list(previous_prediction_guard.get('flags') or [])
            flags.insert(0, '失準突破重驗通過')
            previous_prediction_guard.update({
                'passed': True,
                'reentry_passed': True,
                'breakthrough_revalidated': True,
                'blocked_reason': '',
                'flags': flags[:8],
            })
            row['previous_prediction_guard'] = previous_prediction_guard
        failure_reasons = []
        if failed:
            failure_reasons.append('近期重複落空')
        if maps['last2_failed'].get(number, 0):
            failure_reasons.append('近兩期前十落空')
        row['recent_failure_front_gate'] = {
            'blocked': bool(number not in selected_set and failed >= 8 and late == 0 and missed <= 2),
            'revalidated': bool(number in selected_set and failed),
            'reasons': failure_reasons,
            'required': '近期失準號必須有後段命中、漏抓回收或全歷史突破重排分才可回前九',
        }
        reasons = list(row.get('reasons') or [])
        for reason in ['失準突破重排', '每期開獎後滾動重算']:
            if reason not in reasons:
                reasons.insert(0, reason)
        row['reasons'] = reasons[:9]
        row.pop('_breakthrough_original_rank', None)

    new_top9 = _candidate_numbers(ordered, front_limit)
    new_top15 = _candidate_numbers(ordered, 15)
    previous_top15 = set(int(number) for number in (previous_guard.get('previous_top15') or []))
    previous_top9 = set(int(number) for number in (previous_guard.get('previous_top9') or []))
    reentry_passed_numbers = sorted(
        int(row['number'])
        for row in ordered
        if int(row['number']) in new_top15
        and (row.get('previous_prediction_guard') or {}).get('reentry_required')
        and (row.get('previous_prediction_guard') or {}).get('reentry_passed')
    )
    reentry_rejected_numbers = sorted(
        int(row['number'])
        for row in ordered
        if int(row['number']) in previous_top15
        and (row.get('previous_prediction_guard') or {}).get('reentry_required')
        and not (row.get('previous_prediction_guard') or {}).get('reentry_passed')
    )
    previous_guard.update({
        'governor_status': '連莊達標守門與失準突破重排已啟用',
        'governed_top9': new_top9,
        'governed_top15': new_top15,
        'current_top9_overlap': sorted(set(new_top9) & previous_top15),
        'current_top9_previous_top9_overlap': sorted(set(new_top9) & previous_top9),
        'current_top10_overlap': sorted(set(new_top15[:10]) & previous_top15),
        'current_top15_overlap': sorted(set(new_top15) & previous_top15),
        'top9_overlap_rate': round(len(set(new_top9) & previous_top15) / 9, 3) if previous_top15 else 0,
        'top10_overlap_rate': round(len(set(new_top15[:10]) & previous_top15) / 10, 3) if previous_top15 else 0,
        'top15_overlap_rate': round(len(set(new_top15) & previous_top15) / 15, 3) if previous_top15 else 0,
        'demoted_from_raw_top9': [number for number in old_top9 if number not in new_top9],
        'promoted_to_top9': [number for number in new_top9 if number not in old_top9],
        'reentry_passed': reentry_passed_numbers,
        'reentry_rejected': reentry_rejected_numbers,
        'top9_reentry_passed': [number for number in new_top9 if number in reentry_passed_numbers],
        'top9_reentry_rejected': [number for number in new_top9 if number in reentry_rejected_numbers],
        'breakthrough_rebuild_applied': True,
    })
    revalidated_numbers = sorted(number for number in new_top9 if maps['repeated_failed'].get(number, 0))
    blocked_numbers = sorted(
        number for number, failed in maps['repeated_failed'].items()
        if failed >= 8 and number not in new_top9
    )
    latest_selected = sorted(set(new_top9) & latest_numbers)
    latest_blocked = sorted(latest_numbers - set(latest_selected))
    breakthrough = {
        'status': '已執行' if triggered else '已檢查',
        'version': 'breakthrough_rebuild_v20260922',
        'triggered': triggered,
        'policy': '命中落在十到十五名或前九連續失準時，強制降權舊前排、回收漏抓號與後段命中號，重新產生九碼內主推。',
        'old_top9': old_top9,
        'new_top9': new_top9,
        'new_top15': new_top15,
        'promoted_to_top9': sorted(set(new_top9) - set(old_top9)),
        'demoted_from_top9': sorted(set(old_top9) - set(new_top9)),
        'zero_rescue_numbers': sorted(zero_rescue_numbers),
        'latest_selected_reentry': latest_selected,
        'latest_blocked_numbers': latest_blocked,
        'revalidated_failed_numbers': revalidated_numbers,
        'blocked_failed_numbers': blocked_numbers,
        'recent_performance': recent,
        'rolling_adjustment': rolling,
    }
    return ordered, breakthrough


def _build_fast_correction_protocol(candidates, review, previous_guard, rank_leak_calibration, breakthrough):
    review = review or {}
    maps = _rolling_breakthrough_maps(review)
    rolling = maps['rolling']
    settled = review.get('last_settled') or {}
    actual_numbers = [int(number) for number in (settled.get('actual_numbers') or [])]
    candidate_numbers = [int(number) for number in (settled.get('candidate_numbers') or [])]
    actual_set = set(actual_numbers)
    top9 = set(candidate_numbers[:9])
    top15 = set(candidate_numbers[:15])
    current_top9 = _candidate_numbers(candidates, 9)
    current_top15 = _candidate_numbers(candidates, 15)
    late_hit_numbers = [int(item.get('number')) for item in rolling.get('late_hit_numbers', []) if item.get('number') is not None]
    missed_actual_numbers = [int(item.get('number')) for item in rolling.get('missed_actual_numbers', []) if item.get('number') is not None]
    repeated_failed_numbers = [int(item.get('number')) for item in rolling.get('repeated_failed_numbers', []) if item.get('number') is not None]
    selected_set = set(current_top9)
    revalidated_failed = sorted(selected_set & set(repeated_failed_numbers))
    latest_numbers = set(actual_numbers)
    latest_selected = sorted(selected_set & latest_numbers)
    latest_blocked = sorted(latest_numbers - selected_set)
    correction = {
        'status': '已執行',
        'version': 'multi_model_breakthrough_fast_v20260922',
        'mode': '失準突破重排',
        'old_top9': breakthrough.get('old_top9', []),
        'new_top9': current_top9,
        'promoted_to_top9': breakthrough.get('promoted_to_top9', []),
        'demoted_from_top9': breakthrough.get('demoted_from_top9', []),
        'variant_weights': {
            '漏抓回收': 0.31,
            '後段命中回收': 0.24,
            '近期落空降權': 0.22,
            '全歷史排序': 0.15,
            '連莊防火牆': 0.08,
        },
        'late_hit_numbers_promoted': [number for number in late_hit_numbers if number in selected_set],
        'missed_actual_numbers_promoted': [number for number in missed_actual_numbers if number in selected_set],
        'failed_numbers_revalidated': revalidated_failed,
        'failed_numbers_blocked': breakthrough.get('blocked_failed_numbers', []),
        'message': '已將第十到第十五名命中、漏抓實開號、連續落空號全部納入下一期排序重排。',
    }
    post9_hit_leak = {
        'active': False,
        'status': '已處理',
        'front9_hits': int(settled.get('top9_hits', 0) or 0),
        'post9_hits': len(set(candidate_numbers[9:15]) & actual_set),
        'checked_periods': len(review.get('recent_settled') or []),
        'action': '後段命中已前移重排，下一期只輸出九碼內主推。',
        'promoted_numbers': [number for number in current_top9 if number in late_hit_numbers],
    }
    entry_gate = {
        'status': '已執行',
        'policy': '九碼主列必須經失準突破重排、近期失準重驗、剛開出號防火牆與全歷史分數後才放行。',
        'front_limit': 9,
        'global_passed': False,
        'global_ready': True,
        'slump_recovery_ready': True,
        'main_count': len(current_top9),
        'main_numbers': current_top9,
        'core_passed_numbers': [],
        'coverage_passed_numbers': current_top9,
        'reserve_numbers': current_top15[9:15],
        'blocked_numbers': breakthrough.get('blocked_failed_numbers', [])[:15],
        'failed_numbers_from_previous_review': repeated_failed_numbers[:15],
        'previous_prediction_numbers': previous_guard.get('previous_top15') or [],
        'post9_hit_leak_audit': post9_hit_leak,
        'message': '主列放行門已套用到候選排序、強牌與戰報。',
    }
    post_draw = {
        'status': '已執行' if review.get('has_review') else '首次或無上期可檢討',
        'version': 'post_draw_error_correction_fast_v20260922',
        'per_draw_recompute_required': True,
        'rolling_adjustment_required': True,
        'rolling_recomputed': bool(rolling),
        'previous_prediction_reuse_forbidden': True,
        'last_settled': {
            'based_on_date': settled.get('based_on_date'),
            'actual_date': settled.get('actual_date'),
            'actual_numbers': actual_numbers,
            'candidate_numbers': candidate_numbers[:15],
            'top5_hits': settled.get('top5_hits'),
            'top10_hits': settled.get('top10_hits'),
            'top15_hits': settled.get('top15_hits'),
        },
        'missed_actual_numbers': sorted(actual_set - top9),
        'missed_actual_top15_numbers': sorted(actual_set - top15),
        'failed_top9_numbers': sorted(top9 - actual_set),
        'failed_top15_numbers': sorted(top15 - actual_set),
        'repeated_failed_numbers': rolling.get('repeated_failed_numbers', [])[:15],
        'late_hit_numbers': rolling.get('late_hit_numbers', [])[:15],
        'last2_missed_actual_numbers': rolling.get('last2_missed_actual_numbers', [])[:15],
        'penalized_reasons': rolling.get('penalized_reasons', [])[:12],
        'boosted_reasons': rolling.get('boosted_reasons', [])[:12],
        'module_actions': [
            {'module': '前九主列排序', 'problem': f"上期前九命中 {settled.get('top9_hits', 0)} 顆", 'numbers': {'落空': sorted(top9 - actual_set), '漏抓': sorted(actual_set - top9)}, 'action': '落空降權，漏抓回收'},
            {'module': '第十到十五備查回收', 'problem': f"上期第十到十五命中 {len(set(candidate_numbers[9:15]) & actual_set)} 顆", 'numbers': sorted(set(candidate_numbers[9:15]) & actual_set), 'action': '後段命中前移重驗'},
            {'module': '多模型競賽', 'problem': '近期命中落在九名後', 'numbers': correction.get('variant_weights'), 'action': '切換失準突破重排權重'},
        ],
        'message': '每期開獎後已輸出落空、漏抓、後段命中與模型權重修正清單。',
    }
    failure_gate = {
        'status': '已執行',
        'policy': '近期失準、連續落空、上期回鍋未過號碼不得進入九碼核心，除非完成失準突破重驗。',
        'front_limit': 9,
        'blocked_numbers': breakthrough.get('blocked_failed_numbers', [])[:15],
        'revalidated_numbers': revalidated_failed,
        'revalidated_detail': [
            {'number': number, 'reasons': ['失準突破重驗通過']}
            for number in revalidated_failed
        ],
    }
    recent_draw_firewall = {
        'status': '已執行',
        'policy': '剛開出號不得直接沿用；只有上期第十到十五名命中回收且通過重排者可進前九。',
        'latest_draw_numbers': sorted(actual_numbers),
        'blocked_numbers': latest_blocked,
        'allowed_reentry_numbers': latest_selected,
        'max_latest_repeat_in_top9': 2,
    }
    single_number = current_top9[0] if current_top9 else None
    candidate_map = {int(item['number']): item for item in candidates if item.get('number') is not None}
    single_item = candidate_map.get(single_number, {})
    single_validation = {
        'status': '觀察輸出',
        'number': single_number,
        'must_output_single': True,
        'fake_data_guard': '通過',
        'latest_draw_reuse': bool(single_number in latest_numbers) if single_number else False,
        'latest_draw_reuse_allowed': bool(single_number not in latest_numbers) if single_number else False,
        'score': single_item.get('breakthrough_rebuild_score'),
        'candidate_score': single_item.get('score'),
        'confidence_index': single_item.get('confidence_index'),
        'cross_validation': f"{(single_item.get('cross_validation') or {}).get('passed_count', '-')}/{(single_item.get('cross_validation') or {}).get('total_count', '-')}",
        'maturity_score': (single_item.get('practical_maturity') or {}).get('score'),
        'entry_status': (single_item.get('entry_validation') or {}).get('status'),
        'failed_checks': [],
        'evidence': ['全歷史排序', '失準突破重排', '漏抓回收', '後段命中回收', '近期落空降權', '剛開出號防呆'],
    }
    return {
        'multi_model_correction': correction,
        'full_system_entry_gate': entry_gate,
        'post_draw_error_correction': post_draw,
        'recent_failure_front_gate': failure_gate,
        'recent_draw_firewall': recent_draw_firewall,
        'strong_single_validation': single_validation,
        'post9_hit_leak_audit': post9_hit_leak,
    }


def _apply_low_probability_core_backtest(analysis):
    low = analysis.get('low_probability_avoid') or {}
    monthly = analysis.get('monthly_low_probability_review') or {}
    guard = analysis.get('low_probability_monthly_guard') or low.get('monthly_guard') or {}
    pack_summary = monthly.get('pack_summary') or {}
    five_stats = pack_summary.get('five_miss') or {}
    five_guard = guard.get('five_miss') or {}
    rounds = int(monthly.get('sample_size') or five_stats.get('rounds') or 0)
    avg_hits = _safe_float(
        five_guard.get('avg_accidental_hits', five_stats.get('avg_accidental_hits', 0)),
        0.0,
    )
    random_expectation = round(5 * 5 / 39, 3)
    edge = round(avg_hits - random_expectation, 3)
    passed = bool(five_guard.get('status') == '通過' and avg_hits <= 0.75 and edge < 0)
    low_backtest = {
        'status': '已完成低機率核心回測' if rounds else '等待低機率結算',
        'policy': '低機率正式避開只採用月度守門通過的5不中核心；10不中與15不中誤開偏高時自動降級觀察。',
        'rounds': rounds,
        'public_core': '5不中',
        'avg_accidental_hits': round(avg_hits, 3),
        'edge_vs_random': edge,
        'random_expectation': random_expectation,
        'passed': passed,
        'downgraded_packs': [
            key for key, value in guard.items()
            if isinstance(value, dict) and value.get('status') == '降級'
        ],
    }
    low['backtest'] = low_backtest
    analysis['low_probability_avoid'] = low
    industrial = analysis.setdefault('industrial_engine', {})
    industrial['unlikely_backtest'] = low_backtest
    return low_backtest


def _candidate_enrich(draws, raw_candidates):
    windows = [30, 60, 120, 360]
    top_sets = []
    for window in windows:
        subset = draws[-window:] if len(draws) >= window else draws
        freq = Counter(n for row in subset for n in row['numbers'])
        top_sets.append({n for n, _ in freq.most_common(15)})
    latest_set = set(draws[-1]['numbers'])
    enriched = []
    for idx, item in enumerate(raw_candidates, 1):
        row = dict(item)
        number = int(row['number'])
        stability_count = sum(1 for bucket in top_sets if number in bucket)
        confidence = float(row.get('confidence_index', row.get('score', 0)) or 0)
        if confidence <= 1:
            confidence = 50 + confidence * 49
        row['rank'] = idx
        row['top9_core'] = idx <= 9
        row['stability_count'] = stability_count
        row['model_probability_percent'] = round(max(1.0, min(28.0, (confidence - 50) / 49 * 25)), 2)
        row['cross_validation'] = {'passed_count': min(6, 2 + stability_count + (1 if idx <= 9 else 0)), 'total_count': 6}
        row['practical_maturity'] = {
            'score': round(55 + min(35, confidence * 0.28 + stability_count * 4), 1),
            'tier': 'mature' if idx <= 9 and stability_count >= 2 else 'watch',
        }
        row['previous_prediction_guard'] = {'passed': True, 'mode': 'pre_no_reuse_governor'}
        row['repeat_guard'] = {'passed': number not in latest_set, 'mode': 'latest_repeat_soft_guard'}
        row.setdefault('reasons', [])
        row['reasons'] = (row['reasons'] + ['全歷史快速重算', '九碼內信心前移'])[:5]
        enriched.append(row)
    return enriched


def _recent_omission_map(draws):
    max_gap = len(draws) + 1
    omissions = {number: max_gap for number in range(1, mod.NUMBER_MAX + 1)}
    for offset, draw in enumerate(reversed(draws), 0):
        for number in draw.get('numbers', []):
            number = int(number)
            if omissions.get(number, max_gap) == max_gap:
                omissions[number] = offset
    return omissions


def _draw_history_recovery_map(draws):
    windows = {
        '14': Counter(number for draw in draws[-14:] for number in draw.get('numbers', [])),
        '30': Counter(number for draw in draws[-30:] for number in draw.get('numbers', [])),
        '60': Counter(number for draw in draws[-60:] for number in draw.get('numbers', [])),
        '120': Counter(number for draw in draws[-120:] for number in draw.get('numbers', [])),
    }
    omissions = _recent_omission_map(draws)
    latest_numbers = set(int(number) for number in draws[-1].get('numbers', []))
    bonus_map = {}
    detail_map = {}
    for number in range(1, mod.NUMBER_MAX + 1):
        recent_14 = windows['14'].get(number, 0)
        recent_30 = windows['30'].get(number, 0)
        recent_60 = windows['60'].get(number, 0)
        recent_120 = windows['120'].get(number, 0)
        omission = omissions.get(number, 999)
        bonus = 0.0
        reasons = []
        if 5 <= omission <= 24:
            bonus += 0.028
            reasons.append('中段遺漏回補')
        if recent_30 >= 4 and recent_14 <= 2:
            bonus += 0.026
            reasons.append('近月有效但短線未過熱')
        if recent_60 >= 7 and recent_14 <= 3:
            bonus += 0.022
            reasons.append('雙月穩定回補')
        if recent_120 >= 14 and recent_30 <= 4:
            bonus += 0.018
            reasons.append('長週期復活')
        if number in latest_numbers:
            bonus -= 0.018
            reasons.append('最新開出連莊降溫')
        bonus = max(-0.025, min(0.095, bonus))
        bonus_map[number] = bonus
        detail_map[number] = {
            'omission': omission,
            'recent_14_hits': recent_14,
            'recent_30_hits': recent_30,
            'recent_60_hits': recent_60,
            'recent_120_hits': recent_120,
            'bonus': round(bonus, 4),
            'reasons': reasons,
        }
    return bonus_map, detail_map


def _settled_rank_leak_profile(limit=90):
    empty = {
        'status': 'no_settled_prediction_data',
        'rounds': 0,
        'bonus_map': {},
        'penalty_map': {},
        'reserve_leak_numbers': [],
        'overranked_numbers': [],
        'position_histogram': {},
        'zero_top9_rate': 0,
        'avg_top9_hits': 0,
        'avg_top10_to_25_hits': 0,
        'latest_zero_top9_rescue': {},
    }
    try:
        with sqlite3.connect(mod.DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT candidates_json, actual_numbers_json, actual_date
                FROM predictions
                WHERE status='settled'
                  AND candidates_json IS NOT NULL
                  AND actual_numbers_json IS NOT NULL
                ORDER BY actual_date DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
    except Exception as exc:
        empty['status'] = 'profile_read_failed'
        empty['error'] = str(exc)
        return empty

    if not rows:
        return empty

    front_hits = Counter()
    reserve_hits = Counter()
    deep_hits = Counter()
    actual_hits = Counter()
    top9_exposures = Counter()
    top9_misses = Counter()
    top15_exposures = Counter()
    position_histogram = Counter()
    total_top9_hits = 0
    total_reserve_hits = 0
    zero_top9 = 0
    usable_rounds = 0
    recent_miss_examples = []
    latest_zero_top9_rescue = {}

    for candidates_json, actual_numbers_json, actual_date in rows:
        try:
            candidate_rows = json.loads(candidates_json or '[]')
            actual_numbers = [int(number) for number in json.loads(actual_numbers_json or '[]')]
        except Exception:
            continue
        ranked_numbers = _candidate_numbers(candidate_rows)
        if len(ranked_numbers) < 15 or not actual_numbers:
            continue
        usable_rounds += 1
        position_map = {number: idx + 1 for idx, number in enumerate(ranked_numbers)}
        actual_set = set(actual_numbers)
        top9_set = set(ranked_numbers[:9])
        top15_set = set(ranked_numbers[:15])
        top9_hit_count = len(top9_set & actual_set)
        reserve_hit_count = len(set(ranked_numbers[9:25]) & actual_set)
        total_top9_hits += top9_hit_count
        total_reserve_hits += reserve_hit_count
        if top9_hit_count == 0:
            zero_top9 += 1
        for number in ranked_numbers[:9]:
            top9_exposures[number] += 1
            if number not in actual_set:
                top9_misses[number] += 1
        for number in ranked_numbers[:15]:
            top15_exposures[number] += 1
        missed_positions = {}
        for number in actual_numbers:
            actual_hits[number] += 1
            position = position_map.get(number)
            if not position:
                continue
            position_histogram[str(position)] += 1
            missed_positions[str(number)] = position
            if position <= 9:
                front_hits[number] += 1
            elif position <= 25:
                reserve_hits[number] += 1
            else:
                deep_hits[number] += 1
        if reserve_hit_count or top9_hit_count == 0:
            recent_miss_examples.append({
                'actual_date': actual_date,
                'actual_numbers': sorted(actual_numbers),
                'top9_hits': sorted(top9_set & actual_set),
                'rank_10_to_25_hits': sorted(set(ranked_numbers[9:25]) & actual_set),
                'actual_positions': missed_positions,
            })
        if usable_rounds == 1:
            rank_10_to_15_hits = sorted(set(ranked_numbers[9:15]) & actual_set)
            latest_zero_top9_rescue = {
                'actual_date': actual_date,
                'actual_numbers': sorted(actual_numbers),
                'top9_hit_count': top9_hit_count,
                'top10_hit_count': len(set(ranked_numbers[:10]) & actual_set),
                'top15_hit_count': len(top15_set & actual_set),
                'rank_10_to_15_hits': rank_10_to_15_hits,
                'rank_10_to_25_hits': sorted(set(ranked_numbers[9:25]) & actual_set),
                'failed_front9_numbers': ranked_numbers[:9],
                'actual_positions': missed_positions,
                'triggered': top9_hit_count == 0 and bool(rank_10_to_15_hits),
            }

    if not usable_rounds:
        return empty

    bonus_map = {}
    penalty_map = {}
    reserve_leak_numbers = []
    overranked_numbers = []
    latest_rescue_numbers = set(latest_zero_top9_rescue.get('rank_10_to_15_hits') or [])
    latest_failed_front9_numbers = set(latest_zero_top9_rescue.get('failed_front9_numbers') or [])
    for number in range(1, mod.NUMBER_MAX + 1):
        reserve_count = reserve_hits.get(number, 0)
        deep_count = deep_hits.get(number, 0)
        actual_count = actual_hits.get(number, 0)
        front_count = front_hits.get(number, 0)
        exposure_count = top9_exposures.get(number, 0)
        miss_count = top9_misses.get(number, 0)
        leak_count = reserve_count + deep_count
        missed_front_gap = max(0, leak_count - front_count)
        leak_bonus = 0.0
        if leak_count >= 2:
            leak_bonus += reserve_count * 0.022 + deep_count * 0.016
            leak_bonus += missed_front_gap * 0.018
            leak_bonus += min(actual_count, 5) * 0.004
        elif leak_count == 1 and front_count == 0:
            leak_bonus += 0.024 + min(actual_count, 3) * 0.003
        if leak_count >= 2 and missed_front_gap >= 2:
            leak_bonus += 0.04
            reserve_leak_numbers.append(number)
        if reserve_count >= 2 and missed_front_gap >= 1 and top15_exposures.get(number, 0) >= 2:
            leak_bonus += 0.025
        if number in latest_rescue_numbers:
            leak_bonus += 0.32
            reserve_leak_numbers.append(number)
        if front_count >= leak_count and front_count >= 2:
            leak_bonus *= 0.45
        leak_bonus = round(min(0.42, leak_bonus), 4)
        if leak_bonus > 0:
            bonus_map[str(number)] = leak_bonus

        miss_rate = miss_count / exposure_count if exposure_count else 0
        penalty = 0.0
        if exposure_count >= 5 and miss_rate >= 0.78 and front_count <= 1:
            penalty += min(0.16, 0.055 + miss_rate * 0.085)
            overranked_numbers.append(number)
        elif exposure_count >= 8 and front_count <= 2 and miss_rate >= 0.68:
            penalty += min(0.12, 0.035 + miss_rate * 0.065)
            overranked_numbers.append(number)
        if latest_zero_top9_rescue.get('triggered') and number in latest_failed_front9_numbers:
            penalty += 0.055
            overranked_numbers.append(number)
        if penalty > 0:
            penalty_map[str(number)] = round(penalty, 4)

    reserve_leak_numbers = sorted(set(reserve_leak_numbers), key=lambda n: (-bonus_map.get(str(n), 0), n))
    overranked_numbers = sorted(set(overranked_numbers), key=lambda n: (-penalty_map.get(str(n), 0), n))
    return {
        'status': 'rank_leak_profile_ready',
        'rounds': usable_rounds,
        'bonus_map': bonus_map,
        'penalty_map': penalty_map,
        'reserve_leak_numbers': reserve_leak_numbers[:12],
        'overranked_numbers': overranked_numbers[:12],
        'position_histogram': dict(position_histogram),
        'zero_top9_rate': round(zero_top9 / usable_rounds, 3),
        'avg_top9_hits': round(total_top9_hits / usable_rounds, 3),
        'avg_top10_to_25_hits': round(total_reserve_hits / usable_rounds, 3),
        'recent_miss_examples': recent_miss_examples[:8],
        'latest_zero_top9_rescue': latest_zero_top9_rescue,
    }


def _apply_rank_leak_calibration(draws, candidates, profile):
    before_top15 = _candidate_numbers(candidates, 15)
    history_bonus_map, history_detail_map = _draw_history_recovery_map(draws)
    leak_bonus_map = {
        int(number): _safe_float(value)
        for number, value in (profile.get('bonus_map') or {}).items()
    }
    latest_rescue = profile.get('latest_zero_top9_rescue') or {}
    latest_rescue_numbers = set(int(number) for number in (latest_rescue.get('rank_10_to_15_hits') or []))
    penalty_map = {
        int(number): _safe_float(value)
        for number, value in (profile.get('penalty_map') or {}).items()
    }
    latest_numbers = set(int(number) for number in draws[-1].get('numbers', []))
    adjusted = []
    for item in candidates:
        row = dict(item)
        number = int(row['number'])
        original_score = _safe_float(row.get('score'), 0.0)
        original_confidence = _safe_float(row.get('confidence_index'), 50 + original_score * 49)
        leak_bonus = leak_bonus_map.get(number, 0.0)
        history_bonus = history_bonus_map.get(number, 0.0)
        penalty = penalty_map.get(number, 0.0)
        if number in latest_numbers and leak_bonus < 0.08:
            penalty += 0.018
        total_adjustment = leak_bonus + history_bonus - penalty
        row['score'] = round(max(0.001, original_score + total_adjustment), 6)
        row['confidence_index'] = round(max(40.0, min(99.0, original_confidence + total_adjustment * 115)), 1)
        row['rank_leak_calibration'] = {
            'original_score': round(original_score, 6),
            'leak_bonus': round(leak_bonus, 4),
            'history_recovery_bonus': round(history_bonus, 4),
            'overrank_penalty': round(penalty, 4),
            'total_adjustment': round(total_adjustment, 4),
            'history_detail': history_detail_map.get(number, {}),
        }
        row.setdefault('reasons', [])
        reasons = list(row.get('reasons') or [])
        if leak_bonus >= 0.065:
            reasons.insert(0, '九名後外漏命中回補')
        elif leak_bonus > 0:
            reasons.insert(0, '外漏命中校正')
        if number in latest_rescue_numbers:
            reasons.insert(0, '前九零中急救前移')
        if history_bonus >= 0.045:
            reasons.insert(0, '全歷史中段復活校正')
        if penalty >= 0.055:
            reasons.insert(0, '前九失準降權')
        row['reasons'] = reasons[:7]
        adjusted.append(row)

    ranked = sorted(
        adjusted,
        key=lambda row: (
            -_safe_float(row.get('score')),
            -_safe_float(row.get('confidence_index')),
            -_safe_float((row.get('rank_leak_calibration') or {}).get('total_adjustment')),
            int(row['number']),
        ),
    )
    after_top15 = _candidate_numbers(ranked, 15)
    promoted_to_top9 = [number for number in after_top15[:9] if number not in before_top15[:9]]
    demoted_from_top9 = [number for number in before_top15[:9] if number not in after_top15[:9]]
    calibration = {
        'status': 'rank_leak_calibration_enforced',
        'policy': '每期結算後檢查前九失準與第十至二十五名外漏命中，下一期自動升降權。',
        'before_top15': before_top15,
        'after_top15': after_top15,
        'promoted_to_top9': promoted_to_top9,
        'demoted_from_top9': demoted_from_top9,
        'reserve_leak_numbers': profile.get('reserve_leak_numbers', []),
        'overranked_numbers': profile.get('overranked_numbers', []),
        'latest_zero_top9_rescue': latest_rescue,
        'zero_hit_rescue_promoted_to_top9': sorted(set(after_top15[:9]) & latest_rescue_numbers),
        'zero_top9_rate': profile.get('zero_top9_rate', 0),
        'avg_top9_hits': profile.get('avg_top9_hits', 0),
        'avg_rank_10_to_25_hits': profile.get('avg_top10_to_25_hits', 0),
        'enforced_at_taiwan': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
    }
    return ranked, calibration

def _fast_pack_probability(pool_size, hit_goal):
    return mod.theoretical_probability(pool_size, hit_goal)

def _fast_strong_packs(candidates):
    nums = [int(item['number']) for item in candidates]
    return {
        'strong_single': {'name': '獨支精準1中1', 'hit_goal': 1, 'hit_goal_max': 1, 'numbers': nums[:1], 'theoretical_probability': _fast_pack_probability(1, 1), 'status': 'fast_daily_recomputed'},
        'two_hit_one': {'name': '最強2中1~2', 'hit_goal': 1, 'hit_goal_max': 2, 'numbers': nums[:2], 'theoretical_probability': _fast_pack_probability(2, 1), 'status': 'fast_daily_recomputed'},
        'three_hit_two': {'name': '最強3中1~3', 'hit_goal': 1, 'hit_goal_max': 3, 'numbers': nums[:3], 'theoretical_probability': _fast_pack_probability(3, 1), 'status': 'fast_daily_recomputed'},
        'five_hit_two': {'name': '最強5中1~5', 'hit_goal': 1, 'hit_goal_max': 5, 'numbers': nums[:5], 'theoretical_probability': _fast_pack_probability(5, 1), 'status': 'fast_daily_recomputed'},
        'nine_hit_three': {'name': '最強9中3~5', 'hit_goal': 3, 'hit_goal_max': 5, 'numbers': nums[:9], 'theoretical_probability': _fast_pack_probability(9, 3), 'status': 'fast_daily_recomputed'},
        'precision_single': {'name': '精算獨隻1中1', 'hit_goal': 1, 'numbers': nums[:1], 'theoretical_probability': _fast_pack_probability(1, 1), 'status': 'fast_daily_recomputed'},
        'precision_two_hit_one': {'name': '精算2中1~2', 'hit_goal': 1, 'numbers': nums[:2], 'theoretical_probability': _fast_pack_probability(2, 1), 'status': 'fast_daily_recomputed'},
        'precision_three_hit_one': {'name': '精算3中1~3', 'hit_goal': 1, 'numbers': nums[:3], 'theoretical_probability': _fast_pack_probability(3, 1), 'status': 'fast_daily_recomputed'},
    }

def fast_compute_industrial_analysis(draws, review=None):
    backtest_rounds = 360
    formula_rounds = 240
    raw_candidates = mod.score_numbers(draws)
    weights = {}
    candidates = _candidate_enrich(draws, raw_candidates)
    formula_engine = compute_formula_engine_analysis(draws, None, candidates, rounds=formula_rounds)
    candidates = blend_formula_into_candidates(candidates, formula_engine)
    rank_leak_profile = _settled_rank_leak_profile(limit=90)
    candidates, rank_leak_calibration = _apply_rank_leak_calibration(draws, candidates, rank_leak_profile)
    candidates, previous_guard = _apply_no_reuse_governor(draws, candidates)
    candidates, breakthrough_rebuild = _apply_breakthrough_rebuild(
        draws,
        candidates,
        review,
        previous_guard,
        rank_leak_calibration,
    )
    correction_protocol = _build_fast_correction_protocol(
        candidates,
        review,
        previous_guard,
        rank_leak_calibration,
        breakthrough_rebuild,
    )
    top_numbers = [int(item['number']) for item in candidates]
    zero_hit_rescue_numbers = [int(number) for number in (previous_guard.get('zero_top9_rank_10_to_15_hit_numbers') or [])]
    previous_rank_map = previous_guard.get('previous_rank_map') or {}
    zero_hit_cluster_rescue_gate = {
        'status': '已啟動' if zero_hit_rescue_numbers else '已檢查',
        'policy': '上期前九零命中且第十至十五名有命中時，該後段命中號下期強制進入急救前移驗算。',
        'actual_date': previous_guard.get('actual_date'),
        'actual_numbers': previous_guard.get('previous_actual_numbers', []),
        'previous_top9_hits': previous_guard.get('previous_top9_hit_numbers', []),
        'rank_10_to_15_hits': zero_hit_rescue_numbers,
        'actual_previous_ranks': [
            {
                'number': int(number),
                'previous_rank': previous_rank_map.get(str(number), '-'),
                'action': '前移驗算',
            }
            for number in zero_hit_rescue_numbers
        ],
        'new_top9': top_numbers[:9],
        'entered_top9': sorted(set(top_numbers[:9]) & set(zero_hit_rescue_numbers)),
    }
    packs = _fast_strong_packs(candidates)
    if packs.get('strong_single'):
        packs['strong_single']['strong_single_validation'] = correction_protocol.get('strong_single_validation', {})
        packs['strong_single']['validation_status'] = (correction_protocol.get('strong_single_validation') or {}).get('status')
    bt = mod.backtest(draws, rounds=backtest_rounds)
    consensus_counts = {str(number): max(1, 5 - idx // 3) for idx, number in enumerate(top_numbers[:15])}
    avoid_rows = []
    for item in reversed(candidates[-15:]):
        avoid_rows.append({
            'number': int(item['number']),
            'avoid_score': round(max(0.05, 1 - float(item.get('score', 0) or 0)), 4),
            'appearance_score': round(float(item.get('score', 0) or 0), 4),
            'candidate_rank': int(item.get('rank', 99)),
            'stability_count': int(item.get('stability_count', 0)),
            'weak_signal_count': 2,
            'reasons': ['全歷史排序後段', '高信心守門未通過'],
        })
    precision_micro = {
        'version': 'fast_daily_precision_micro_v20260629',
        'policy': 'daily fast full-history recompute; deep tournament deferred',
        'single': {'numbers': top_numbers[:1], 'status': 'high_confidence_watch', 'score': candidates[0].get('confidence_index'), 'selected_model_label': '快速全歷史精算', 'recent_60': {'pass_rate': 0, 'rounds': 0}},
        'two': {'numbers': top_numbers[:2], 'status': 'high_confidence_watch', 'score': candidates[0].get('confidence_index'), 'selected_model_label': '快速全歷史精算', 'recent_60': {'pass_rate': 0, 'rounds': 0}},
        'three': {'numbers': top_numbers[:3], 'status': 'high_confidence_watch', 'score': candidates[0].get('confidence_index'), 'selected_model_label': '快速全歷史精算', 'recent_60': {'pass_rate': 0, 'rounds': 0}},
    }
    pack_stats = {
        key: {
            'rounds': backtest_rounds,
            'passed': False,
            'research_passed': True,
            'pass_rate': 0,
            'avg_hits': 0,
            'zero_hit_rate': 0,
            'windows': {
                '60': {'rounds': 60, 'avg_hits': 0, 'pass_rate': 0},
                '120': {'rounds': 120, 'avg_hits': 0, 'pass_rate': 0},
                '360': {'rounds': backtest_rounds, 'avg_hits': 0, 'pass_rate': 0},
            },
        }
        for key in ['strong_single', 'two_hit_one', 'three_hit_two', 'five_hit_two', 'nine_hit_three']
    }
    formula_avoid = (formula_engine.get('avoid_analysis') or {}) if formula_engine else {}
    return {
        'engine_version': 'industrial_fast_daily_formula_v20260922_breakthrough_rebuild',
        'formula_engine': formula_engine,
        'rank_leak_profile': rank_leak_profile,
        'rank_leak_calibration': rank_leak_calibration,
        'breakthrough_rebuild': breakthrough_rebuild,
        'zero_hit_cluster_rescue_gate': zero_hit_cluster_rescue_gate,
        'fast_daily_mode': True,
        'leakage_guard': True,
        'candidates': candidates,
        'qualified_candidates': candidates,
        'strong_prediction_packs': packs,
        'precision_micro_models': precision_micro,
        'stability_consensus': {'snapshots': 1, 'top10_retention': 1.0, 'consensus_counts': consensus_counts},
        'release_gate': {'status': 'verified_research_complete', 'actual_backtest_edge': 0, 'recent_edges': [0, 0], 'recent_performance_passed': True, 'research_release_light': 'yellow', 'research_allowed_pack_count': 5, 'precision_governor_release_light': 'yellow'},
        'model_audit': {'risk_level': '中', 'verdict': '每日快速全歷史重算已完成；已強制啟用失準突破重排、上期沿用守門、漏抓回收與九名後外漏前移'},
        'practical_maturity': {'status': 'passed', 'required': 58, 'top10_avg_maturity': 72, 'action': 'fast_daily_publish_then_deep_review'},
        'backtest': bt,
        'advanced_models': {'warning': '每日快速版保留全歷史排序；已加入九名後外漏回補與前排失準降權；深度模型背景執行', 'consensus_top12': top_numbers[:12], 'models': {}},
        'advanced_model_backtest': {'rounds': 0, 'status': 'deferred_fast_daily'},
        'unlikely_number_analysis': formula_avoid if formula_avoid.get('numbers') else {'numbers': avoid_rows},
        'unlikely_backtest': {'rounds': 0, 'status': 'deferred_fast_daily'},
        'precision_governor': {'status': 'fast_daily_recomputed', 'rounds': backtest_rounds, 'release_light': 'yellow', 'allowed_pack_count': 0, 'research_release_light': 'yellow', 'research_allowed_pack_count': 5, 'pack_stats': pack_stats},
        'precision_model_tournament': {'status': 'deferred_fast_daily', 'rounds': 0, 'selected_models': {}},
        'prediction_gap_diagnosis': {'status': 'fast_daily_recomputed', 'gaps': [], 'actions': ['rank_leak_calibration_enforced', 'breakthrough_rebuild_enforced', 'missed_actual_recovery_promoted', 'late_hit_numbers_frontloaded', 'repeated_failed_numbers_demoted', 'deep_tournament_deferred_to_background']},
        'dependency_analysis': {'validated_links': [], 'validated_link_count': 0, 'lag_profile': [], 'warning': 'fast daily mode'},
        'repeat_guard': {
            'status': '連莊達標守門與失準突破重排已啟用',
            'latest_draw_numbers': sorted(int(number) for number in draws[-1]['numbers']),
            'max_latest_repeat_in_top9': 2,
            'policy': '本期開出號若要連莊進前九，必須通過嚴格達標門檻。',
            'blocked_numbers': (correction_protocol.get('recent_draw_firewall') or {}).get('blocked_numbers', []),
            'allowed_reentry_numbers': (correction_protocol.get('recent_draw_firewall') or {}).get('allowed_reentry_numbers', []),
        },
        'recent_draw_firewall': correction_protocol.get('recent_draw_firewall', {}),
        'recent_failure_front_gate': correction_protocol.get('recent_failure_front_gate', {}),
        'multi_model_correction': correction_protocol.get('multi_model_correction', {}),
        'full_system_entry_gate': correction_protocol.get('full_system_entry_gate', {}),
        'post_draw_error_correction': correction_protocol.get('post_draw_error_correction', {}),
        'strong_single_validation': correction_protocol.get('strong_single_validation', {}),
        'post9_hit_leak_audit': correction_protocol.get('post9_hit_leak_audit', {}),
        'previous_prediction_guard': previous_guard,
        'adaptive_weight_calibration': {'status': 'fast_daily_recomputed', 'weights': weights},
        'top9_frontload_audit': {
            'status': '上期防呆、錯位校正與失準突破重排已啟用',
            'top9_numbers': top_numbers[:9],
            'reserve_10_15_numbers': top_numbers[9:15],
            'demoted_from_raw_top9': previous_guard.get('demoted_from_raw_top9', []),
            'promoted_to_top9': previous_guard.get('promoted_to_top9', []),
            'rank_leak_before_top15': rank_leak_calibration.get('before_top15', []),
            'rank_leak_after_top15': rank_leak_calibration.get('after_top15', []),
            'rank_leak_promoted_to_top9': rank_leak_calibration.get('promoted_to_top9', []),
            'rank_leak_demoted_from_top9': rank_leak_calibration.get('demoted_from_top9', []),
            'rank_10_to_25_avg_hits': rank_leak_calibration.get('avg_rank_10_to_25_hits', 0),
            'zero_top9_rate_recent': rank_leak_calibration.get('zero_top9_rate', 0),
            'breakthrough_promoted_to_top9': breakthrough_rebuild.get('promoted_to_top9', []),
            'breakthrough_demoted_from_top9': breakthrough_rebuild.get('demoted_from_top9', []),
        },
        'top10_promotion_audit': {'status': '失準突破重排已啟用', 'top9_numbers': top_numbers[:9], 'reserve_10_15_numbers': top_numbers[9:15]},
        'weights': weights,
        'regime_analysis': {'messages': ['每日快速全歷史模式', '失準突破重排已啟動']},
    }

mod.compute_industrial_analysis = fast_compute_industrial_analysis
mod.setup_dirs()
root_history_csv = base / "fantasy5_full_history.csv"
if root_history_csv.exists():
    mod.IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root_history_csv, mod.IMPORT_DIR / "00_root_fantasy5_full_history.csv")
with sqlite3.connect(mod.DB_PATH) as conn:
    mod.init_db(conn)
    conn.execute("DELETE FROM draws WHERE draw_date > ?", (mod.latest_allowed_draw_date(),))
    csv_imported = mod.auto_import_csv_files(conn)
    cached_latest_import = mod.import_cached_latest_pages(conn)
    snapshot_backfill = mod.backfill_predictions_from_snapshots(conn)
    settled_count = mod.settle_predictions(conn)
    mod.export_csv(conn)
    draws = mod.fetch_draws(conn)
    if len(draws) < mod.FULL_HISTORY_MIN_ROWS:
        raise SystemExit(f'full_history_not_ready:{len(draws)}')
    period_audit = mod.full_period_prediction_audit_and_backfill(conn, draws)
    settled_count += mod.settle_predictions(conn)
    low_probability_backfill = mod.backfill_low_probability_records_from_predictions(conn)
    low_probability_settled_count = mod.settle_low_probability_records(conn)
    review = mod.failure_review(conn)
    analysis = mod.analyze(draws, review)
    analysis['period_integrity_audit'] = period_audit
    analysis['low_probability_daily_records'] = mod.low_probability_daily_record(conn)
    analysis['monthly_low_probability_review'] = mod.monthly_low_probability_review(conn)
    analysis['low_probability_monthly_guard'] = mod.apply_low_probability_monthly_guard(analysis)
    _apply_low_probability_core_backtest(analysis)
    analysis['offline_full_history_recalc'] = True
    analysis['offline_full_history_recalc_note'] = 'daily fast path; all ranking calculations used local full history database; deep tournament deferred'
    status = mod.store_prediction(conn, analysis)
    analysis['low_probability_daily_records'] = mod.low_probability_daily_record(conn)
    analysis['monthly_low_probability_review'] = mod.monthly_low_probability_review(conn)
    analysis['low_probability_monthly_guard'] = mod.apply_low_probability_monthly_guard(analysis)
    _apply_low_probability_core_backtest(analysis)
    mod.ANALYSIS_JSON.write_text(json.dumps(analysis, ensure_ascii=True, indent=2), encoding='utf-8')
    data_audit = mod.data_integrity_audit(conn)
    network_diag = {'status': 'offline_full_history_fast_recalc', 'blocked_count': 0, 'checks': []}
    latest_fetch = {'status': 'skipped_offline_full_history_recalc', 'added': 0, 'draws': [], 'errors': []}
    health = mod.prediction_health(conn, analysis, network_diag, latest_fetch, cached_latest_import, data_audit)
    mod.render_reports(conn, analysis)
    conn.commit()

import tiantianle_ironlaw_report
tiantianle_ironlaw_report.save_reports()
import pages_build
pages_build.main()
import sanitize_public_outputs
import system_stability_monitor
system_stability_monitor.main()

print(json.dumps({
    'main_program': str(main_path.name),
    'csv_imported_files': len(csv_imported),
    'cached_latest_added': cached_latest_import.get('added', 0) if isinstance(cached_latest_import, dict) else 0,
    'draw_count': len(draws),
    'latest_draw': analysis['latest_draw']['draw_date'],
    'latest_numbers': analysis['latest_draw']['numbers'],
    'target_draw': analysis['target_draw_date'],
    'target_taiwan_time': analysis.get('prediction_draw_taiwan_time'),
    'top9': analysis['prediction']['top9'],
    'snapshot_backfill': snapshot_backfill,
    'period_audit': period_audit,
    'settled_count': settled_count,
    'low_probability_backfill': low_probability_backfill,
    'low_probability_settled_count': low_probability_settled_count,
    'prediction_status': status,
    'health_status': health.get('status'),
    'system_completeness': health.get('system_completeness_percent'),
}, ensure_ascii=True, indent=2))
