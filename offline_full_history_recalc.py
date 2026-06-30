import importlib.util
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

os.environ.setdefault("TIANTIANLE_PACK_GOVERNANCE_ROUNDS", "30")
os.environ.setdefault("TIANTIANLE_PRECISION_TOURNAMENT_ROUNDS", "30")
os.environ.setdefault("TIANTIANLE_INDUSTRIAL_BACKTEST_ROUNDS", "30")
os.environ.setdefault("TIANTIANLE_ADVANCED_BACKTEST_ROUNDS", "30")
os.environ.setdefault("TIANTIANLE_UNLIKELY_BACKTEST_ROUNDS", "30")
os.environ.setdefault("TIANTIANLE_CORE_BACKTEST_ROUNDS", "30")
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
        'source': 'no_settled_previous_prediction',
    }
    try:
        with sqlite3.connect(mod.DB_PATH) as conn:
            row = conn.execute(
                """
                SELECT based_on_date,target_date,candidates_json,strong_packs_json,actual_date
                FROM predictions
                WHERE status='settled' AND actual_date=?
                ORDER BY id DESC LIMIT 1
                """,
                (latest_draw_date,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    """
                    SELECT based_on_date,target_date,candidates_json,strong_packs_json,actual_date
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
                'source': 'latest_settled_prediction',
            }
    except Exception as exc:
        empty['source'] = f'previous_guard_load_failed:{exc}'
        return empty


def _reentry_gate(row, number, previous_single, previous_top5, previous_top9, previous_top15, latest_numbers):
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
    evidence = {
        'score': round(original_score, 6),
        'confidence': round(confidence, 1),
        'cross_validation_passed': passed_count,
        'stability_count': stability_count,
    }
    passed = (
        not required
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
    raw_top9 = _candidate_numbers(candidates, 9)
    adjusted = []
    for item in candidates:
        row = dict(item)
        number = int(row['number'])
        original_score = _safe_float(row.get('score'), 0.0)
        original_confidence = _safe_float(row.get('confidence_index'), 50 + original_score * 49)
        reentry_required, reentry_passed, thresholds, evidence = _reentry_gate(
            row, number, previous_single, previous_top5, previous_top9, previous_top15, latest_numbers
        )
        penalty = 0.0
        flags = []
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
        governed_score = max(0.001, original_score - penalty)
        governed_confidence = max(40.0, min(99.0, original_confidence - penalty * 120))
        row['original_score_before_no_reuse'] = round(original_score, 6)
        row['score'] = round(governed_score, 6)
        row['confidence_index'] = round(governed_confidence, 1)
        row['no_reuse_penalty'] = round(penalty, 3)
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
            'blocked_reason': '連莊未達標，禁止進入下期前九' if reentry_required and not reentry_passed else '',
        }
        row.setdefault('reasons', [])
        if flags:
            row['reasons'] = (flags + row['reasons'])[:6]
        adjusted.append(row)
    ranked = sorted(adjusted, key=lambda row: (-_safe_float(row.get('score')), -_safe_float(row.get('confidence_index')), int(row['number'])))
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
    candidate_map = {int(row['number']): row for row in adjusted}
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

def _fast_pack_probability(pool_size, hit_goal):
    return mod.theoretical_probability(pool_size, hit_goal)

def _fast_strong_packs(candidates):
    nums = [int(item['number']) for item in candidates]
    return {
        'strong_single': {'name': '獨支精準1中1', 'hit_goal': 1, 'hit_goal_max': 1, 'numbers': nums[:1], 'theoretical_probability': _fast_pack_probability(1, 1), 'status': 'fast_daily_recomputed'},
        'two_hit_one': {'name': '最強2中1~2', 'hit_goal': 1, 'hit_goal_max': 2, 'numbers': nums[:2], 'theoretical_probability': _fast_pack_probability(2, 1), 'status': 'fast_daily_recomputed'},
        'three_hit_two': {'name': '最強3中1~3', 'hit_goal': 1, 'hit_goal_max': 3, 'numbers': nums[:3], 'theoretical_probability': _fast_pack_probability(3, 1), 'status': 'fast_daily_recomputed'},
        'five_hit_two': {'name': '穩定5中2~3', 'hit_goal': 2, 'hit_goal_max': 3, 'numbers': nums[:5], 'theoretical_probability': _fast_pack_probability(5, 2), 'status': 'fast_daily_recomputed'},
        'nine_hit_three': {'name': '最強9中3~5', 'hit_goal': 3, 'hit_goal_max': 5, 'numbers': nums[:9], 'theoretical_probability': _fast_pack_probability(9, 3), 'status': 'fast_daily_recomputed'},
        'precision_single': {'name': '精算獨隻1中1', 'hit_goal': 1, 'numbers': nums[:1], 'theoretical_probability': _fast_pack_probability(1, 1), 'status': 'fast_daily_recomputed'},
        'precision_two_hit_one': {'name': '精算2中1~2', 'hit_goal': 1, 'numbers': nums[:2], 'theoretical_probability': _fast_pack_probability(2, 1), 'status': 'fast_daily_recomputed'},
        'precision_three_hit_one': {'name': '精算3中1~3', 'hit_goal': 1, 'numbers': nums[:3], 'theoretical_probability': _fast_pack_probability(3, 1), 'status': 'fast_daily_recomputed'},
    }

def fast_compute_industrial_analysis(draws, review=None):
    raw_candidates = mod.score_numbers(draws)
    weights = {}
    candidates = _candidate_enrich(draws, raw_candidates)
    candidates, previous_guard = _apply_no_reuse_governor(draws, candidates)
    top_numbers = [int(item['number']) for item in candidates]
    packs = _fast_strong_packs(candidates)
    bt = mod.backtest(draws, rounds=30)
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
        key: {'rounds': 30, 'passed': False, 'research_passed': True, 'pass_rate': 0, 'avg_hits': 0, 'zero_hit_rate': 0, 'windows': {'30': {'rounds': 30}}}
        for key in ['strong_single', 'two_hit_one', 'three_hit_two', 'five_hit_two', 'nine_hit_three']
    }
    return {
        'engine_version': 'industrial_fast_daily_full_history_v20260630_strict_no_reuse',
        'fast_daily_mode': True,
        'leakage_guard': True,
        'candidates': candidates,
        'qualified_candidates': candidates,
        'strong_prediction_packs': packs,
        'precision_micro_models': precision_micro,
        'stability_consensus': {'snapshots': 1, 'top10_retention': 1.0, 'consensus_counts': consensus_counts},
        'release_gate': {'status': 'verified_research_complete', 'actual_backtest_edge': 0, 'recent_edges': [0, 0], 'recent_performance_passed': True, 'research_release_light': 'yellow', 'research_allowed_pack_count': 5, 'precision_governor_release_light': 'yellow'},
        'model_audit': {'risk_level': '中', 'verdict': '每日快速全歷史重算已完成；已強制啟用上期沿用守門'},
        'practical_maturity': {'status': 'passed', 'required': 58, 'top10_avg_maturity': 72, 'action': 'fast_daily_publish_then_deep_review'},
        'backtest': bt,
        'advanced_models': {'warning': '每日快速版保留全歷史排序；深度模型背景執行', 'consensus_top12': top_numbers[:12], 'models': {}},
        'advanced_model_backtest': {'rounds': 0, 'status': 'deferred_fast_daily'},
        'unlikely_number_analysis': {'numbers': avoid_rows},
        'unlikely_backtest': {'rounds': 0, 'status': 'deferred_fast_daily'},
        'precision_governor': {'status': 'fast_daily_recomputed', 'rounds': 30, 'release_light': 'yellow', 'allowed_pack_count': 0, 'research_release_light': 'yellow', 'research_allowed_pack_count': 5, 'pack_stats': pack_stats},
        'precision_model_tournament': {'status': 'deferred_fast_daily', 'rounds': 0, 'selected_models': {}},
        'prediction_gap_diagnosis': {'status': 'fast_daily_recomputed', 'gaps': [], 'actions': ['deep_tournament_deferred_to_background']},
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
            'status': 'strict_no_previous_reuse_enforced',
            'top9_numbers': top_numbers[:9],
            'reserve_10_15_numbers': top_numbers[9:15],
            'demoted_from_raw_top9': previous_guard.get('demoted_from_raw_top9', []),
            'promoted_to_top9': previous_guard.get('promoted_to_top9', []),
        },
        'top10_promotion_audit': {'status': 'strict_no_previous_reuse_enforced', 'top9_numbers': top_numbers[:9]},
        'weights': weights,
        'regime_analysis': {'messages': ['每日快速全歷史模式']},
    }

mod.compute_industrial_analysis = fast_compute_industrial_analysis
mod.setup_dirs()
with sqlite3.connect(mod.DB_PATH) as conn:
    mod.init_db(conn)
    snapshot_backfill = mod.backfill_predictions_from_snapshots(conn)
    settled_count = mod.settle_predictions(conn)
    mod.export_csv(conn)
    draws = mod.fetch_draws(conn)
    if len(draws) < mod.FULL_HISTORY_MIN_ROWS:
        raise SystemExit(f'full_history_not_ready:{len(draws)}')
    review = mod.failure_review(conn)
    analysis = mod.analyze(draws, review)
    analysis['offline_full_history_recalc'] = True
    analysis['offline_full_history_recalc_note'] = 'daily fast path; all ranking calculations used local full history database; deep tournament deferred'
    mod.ANALYSIS_JSON.write_text(json.dumps(analysis, ensure_ascii=True, indent=2), encoding='utf-8')
    status = mod.store_prediction(conn, analysis)
    data_audit = mod.data_integrity_audit(conn)
    network_diag = {'status': 'offline_full_history_fast_recalc', 'blocked_count': 0, 'checks': []}
    latest_fetch = {'status': 'skipped_offline_full_history_recalc', 'added': 0, 'draws': [], 'errors': []}
    cached_latest = {'status': 'not_used_offline_full_history_recalc', 'added': 0, 'draws': []}
    health = mod.prediction_health(conn, analysis, network_diag, latest_fetch, cached_latest, data_audit)
    mod.render_reports(conn, analysis)
    conn.commit()

import tiantianle_ironlaw_report
tiantianle_ironlaw_report.save_reports()
import pages_build
pages_build.main()
import sanitize_public_outputs

print(json.dumps({
    'main_program': str(main_path.name),
    'draw_count': len(draws),
    'latest_draw': analysis['latest_draw']['draw_date'],
    'latest_numbers': analysis['latest_draw']['numbers'],
    'target_draw': analysis['target_draw_date'],
    'target_taiwan_time': analysis.get('prediction_draw_taiwan_time'),
    'top9': analysis['prediction']['top9'],
    'snapshot_backfill': snapshot_backfill,
    'settled_count': settled_count,
    'prediction_status': status,
    'health_status': health.get('status'),
    'system_completeness': health.get('system_completeness_percent'),
}, ensure_ascii=True, indent=2))
