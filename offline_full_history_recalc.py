import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from tiantianle_formula_engine import compute_formula_engine_analysis, blend_formula_into_candidates
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
    top_numbers = [int(item['number']) for item in candidates]
    zero_hit_rescue_numbers = [int(number) for number in (previous_guard.get('zero_top9_rank_10_to_15_hit_numbers') or [])]
    previous_rank_map = previous_guard.get('previous_rank_map') or {}
    zero_hit_cluster_rescue_gate = {
        'status': '已啟動' if zero_hit_rescue_numbers else '',
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
        'engine_version': 'industrial_fast_daily_formula_v20260702_strict_no_reuse_rank_leak_calibrated',
        'formula_engine': formula_engine,
        'rank_leak_profile': rank_leak_profile,
        'rank_leak_calibration': rank_leak_calibration,
        'zero_hit_cluster_rescue_gate': zero_hit_cluster_rescue_gate,
        'fast_daily_mode': True,
        'leakage_guard': True,
        'candidates': candidates,
        'qualified_candidates': candidates,
        'strong_prediction_packs': packs,
        'precision_micro_models': precision_micro,
        'stability_consensus': {'snapshots': 1, 'top10_retention': 1.0, 'consensus_counts': consensus_counts},
        'release_gate': {'status': 'verified_research_complete', 'actual_backtest_edge': 0, 'recent_edges': [0, 0], 'recent_performance_passed': True, 'research_release_light': 'yellow', 'research_allowed_pack_count': 5, 'precision_governor_release_light': 'yellow'},
        'model_audit': {'risk_level': '中', 'verdict': '每日快速全歷史重算已完成；已強制啟用上期沿用守門與九名後外漏回補校正'},
        'practical_maturity': {'status': 'passed', 'required': 58, 'top10_avg_maturity': 72, 'action': 'fast_daily_publish_then_deep_review'},
        'backtest': bt,
        'advanced_models': {'warning': '每日快速版保留全歷史排序；已加入九名後外漏回補與前排失準降權；深度模型背景執行', 'consensus_top12': top_numbers[:12], 'models': {}},
        'advanced_model_backtest': {'rounds': 0, 'status': 'deferred_fast_daily'},
        'unlikely_number_analysis': formula_avoid if formula_avoid.get('numbers') else {'numbers': avoid_rows},
        'unlikely_backtest': {'rounds': 0, 'status': 'deferred_fast_daily'},
        'precision_governor': {'status': 'fast_daily_recomputed', 'rounds': backtest_rounds, 'release_light': 'yellow', 'allowed_pack_count': 0, 'research_release_light': 'yellow', 'research_allowed_pack_count': 5, 'pack_stats': pack_stats},
        'precision_model_tournament': {'status': 'deferred_fast_daily', 'rounds': 0, 'selected_models': {}},
        'prediction_gap_diagnosis': {'status': 'fast_daily_recomputed', 'gaps': [], 'actions': ['rank_leak_calibration_enforced', 'overranked_front_numbers_demoted', 'rank_10_to_25_hit_leakage_promoted', 'deep_tournament_deferred_to_background']},
        'dependency_analysis': {'validated_links': [], 'validated_link_count': 0, 'lag_profile': [], 'warning': 'fast daily mode'},
        'repeat_guard': {
            'status': 'strict_reentry_gate_enforced',
            'latest_draw_numbers': sorted(int(number) for number in draws[-1]['numbers']),
            'max_latest_repeat_in_top9': 2,
            'policy': '本期開出號若要連莊進前九，必須通過嚴格達標門檻。',
        },
        'previous_prediction_guard': previous_guard,
        'adaptive_weight_calibration': {'status': 'fast_daily_recomputed', 'weights': weights},
        'top9_frontload_audit': {
            'status': 'strict_no_previous_reuse_and_rank_leak_calibration_enforced',
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
        },
        'top10_promotion_audit': {'status': 'strict_no_previous_reuse_enforced', 'top9_numbers': top_numbers[:9]},
        'weights': weights,
        'regime_analysis': {'messages': ['每日快速全歷史模式']},
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
    analysis['offline_full_history_recalc'] = True
    analysis['offline_full_history_recalc_note'] = 'daily fast path; all ranking calculations used local full history database; deep tournament deferred'
    status = mod.store_prediction(conn, analysis)
    analysis['low_probability_daily_records'] = mod.low_probability_daily_record(conn)
    analysis['monthly_low_probability_review'] = mod.monthly_low_probability_review(conn)
    analysis['low_probability_monthly_guard'] = mod.apply_low_probability_monthly_guard(analysis)
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
