#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full-history formula layer for Tiantianle."""

import math
import os
from collections import Counter, defaultdict
from itertools import combinations

NUMBER_MIN = 1
NUMBER_MAX = 39
DRAW_SIZE = 5
RANDOM_EXPECTATIONS = {
    1: DRAW_SIZE * 1 / NUMBER_MAX,
    2: DRAW_SIZE * 2 / NUMBER_MAX,
    3: DRAW_SIZE * 3 / NUMBER_MAX,
    5: DRAW_SIZE * 5 / NUMBER_MAX,
    9: DRAW_SIZE * 9 / NUMBER_MAX,
    10: DRAW_SIZE * 10 / NUMBER_MAX,
    15: DRAW_SIZE * 15 / NUMBER_MAX,
}
MODEL_LABELS = {
    "multi_window_frequency": "多週期頻率",
    "trend_break": "趨勢轉折",
    "gap_phase": "遺漏相位",
    "pair_lift": "拖牌關聯",
    "shape_follow": "牌型跟隨",
    "tail_zone_balance": "尾數區間平衡",
    "sum_band_neighbor": "和值鄰近",
    "repeat_validation": "連莊驗證",
}
RESEARCH_NOTES = [
    {
        "name": "超幾何隨機基準",
        "url": "https://arxiv.org/abs/0806.4595",
        "use": "用五取三十九不放回抽樣建立隨機期望，所有回測先跟隨機基準比較。",
    },
    {
        "name": "組合覆蓋設計",
        "url": "https://arxiv.org/abs/2603.24170",
        "use": "用覆蓋與組合分散概念檢查九碼核心，不讓號碼集中在單一區間或尾數。",
    },
]


def runtime_rounds(name="TIANTIANLE_FORMULA_BACKTEST_ROUNDS", default=90, minimum=30, maximum=360):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def normalize(values):
    if not values:
        return {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def rank_values(values):
    return sorted(range(NUMBER_MIN, NUMBER_MAX + 1), key=lambda n: (values.get(n, 0.0), -n), reverse=True)


def number_zone(number):
    if number <= 10:
        return "01-10"
    if number <= 20:
        return "11-20"
    if number <= 30:
        return "21-30"
    return "31-39"


def frequency(draws):
    counter = Counter()
    for draw in draws:
        counter.update(int(number) for number in draw["numbers"])
    return counter


def current_gaps(draws):
    last_seen = {number: None for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for index, draw in enumerate(draws):
        for number in draw["numbers"]:
            last_seen[int(number)] = index
    latest_index = len(draws) - 1
    return {
        number: (latest_index - last_seen[number] if last_seen[number] is not None else len(draws))
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }


def draw_profile(numbers):
    ordered = sorted(int(number) for number in numbers)
    zones = Counter(number_zone(number) for number in ordered)
    tails = {number % 10 for number in ordered}
    return {
        "odd": sum(number % 2 for number in ordered),
        "big": sum(1 for number in ordered if number >= 20),
        "sum": sum(ordered),
        "span": ordered[-1] - ordered[0],
        "tail_diversity": len(tails),
        "zones": [zones.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]],
    }


def profile_similarity(left, right):
    zone_gap = sum(abs(a - b) for a, b in zip(left["zones"], right["zones"])) / 10
    score = 1.0
    score -= abs(left["odd"] - right["odd"]) / 5 * 0.15
    score -= abs(left["big"] - right["big"]) / 5 * 0.14
    score -= abs(left["sum"] - right["sum"]) / 120 * 0.22
    score -= abs(left["span"] - right["span"]) / 38 * 0.16
    score -= abs(left["tail_diversity"] - right["tail_diversity"]) / 5 * 0.09
    score -= zone_gap * 0.24
    return max(0.0, score)


def multi_window_frequency_scores(draws):
    windows = [(20, 0.24), (60, 0.26), (180, 0.22), (720, 0.16), (len(draws), 0.12)]
    values = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for window, weight in windows:
        subset = draws[-window:] if len(draws) >= window else draws
        counts = frequency(subset)
        normalized = normalize({number: counts.get(number, 0) for number in range(NUMBER_MIN, NUMBER_MAX + 1)})
        for number in values:
            values[number] += normalized[number] * weight
    return normalize(values)


def trend_break_scores(draws):
    values = {}
    fast = frequency(draws[-25:] if len(draws) >= 25 else draws)
    mid = frequency(draws[-120:] if len(draws) >= 120 else draws)
    slow = frequency(draws[-720:] if len(draws) >= 720 else draws)
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        fast_rate = fast.get(number, 0) / max(1, min(25, len(draws)))
        mid_rate = mid.get(number, 0) / max(1, min(120, len(draws)))
        slow_rate = slow.get(number, 0) / max(1, min(720, len(draws)))
        values[number] = max(0.0, fast_rate * 0.50 + mid_rate * 0.35 - slow_rate * 0.12)
    return normalize(values)


def gap_phase_scores(draws):
    gaps = current_gaps(draws)
    expected_gap = NUMBER_MAX / DRAW_SIZE
    values = {}
    for number, gap in gaps.items():
        sweet_spot = math.exp(-abs(gap - expected_gap * 1.35) / max(expected_gap * 1.55, 1))
        fresh_penalty = 0.26 if gap <= 1 else 0.12 if gap <= 3 else 0.0
        old_penalty = 0.22 if gap >= expected_gap * 5.5 else 0.0
        values[number] = max(0.0, sweet_spot - fresh_penalty - old_penalty)
    return normalize(values)


def pair_lift_scores(draws, window=1800):
    if len(draws) < 40:
        return {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    subset = draws[-window:] if len(draws) >= window else draws
    latest = set(int(number) for number in draws[-1]["numbers"])
    target_total = Counter()
    source_total = Counter()
    link_total = defaultdict(Counter)
    transitions = max(len(subset) - 1, 1)
    for index in range(len(subset) - 1):
        current = set(int(number) for number in subset[index]["numbers"])
        following = set(int(number) for number in subset[index + 1]["numbers"])
        target_total.update(following)
        for source in current:
            source_total[source] += 1
            link_total[source].update(following)
    values = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for source in latest:
        support = source_total.get(source, 0)
        if support < 20:
            continue
        for target in range(NUMBER_MIN, NUMBER_MAX + 1):
            baseline = target_total.get(target, 0) / transitions
            conditional = link_total[source].get(target, 0) / support
            lift = conditional - baseline
            if lift > 0:
                values[target] += lift * min(1.0, support / 180)
    return normalize(values)


def shape_follow_scores(draws, window=1800):
    if len(draws) < 80:
        return {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    subset = draws[-window:] if len(draws) >= window else draws
    latest_profile = draw_profile(draws[-1]["numbers"])
    votes = Counter()
    for index in range(len(subset) - 1):
        similarity = profile_similarity(draw_profile(subset[index]["numbers"]), latest_profile)
        if similarity < 0.55:
            continue
        for number in subset[index + 1]["numbers"]:
            votes[int(number)] += similarity ** 2
    return normalize({number: votes.get(number, 0.0) for number in range(NUMBER_MIN, NUMBER_MAX + 1)})


def tail_zone_balance_scores(draws):
    recent = draws[-160:] if len(draws) >= 160 else draws
    tail_counts = Counter()
    zone_counts = Counter()
    for draw in recent:
        for number in draw["numbers"]:
            number = int(number)
            tail_counts[number % 10] += 1
            zone_counts[number_zone(number)] += 1
    tail_pressure = normalize({tail: -tail_counts.get(tail, 0) for tail in range(10)})
    zone_pressure = normalize({zone: -zone_counts.get(zone, 0) for zone in ["01-10", "11-20", "21-30", "31-39"]})
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        values[number] = tail_pressure[number % 10] * 0.48 + zone_pressure[number_zone(number)] * 0.52
    return normalize(values)


def sum_band_neighbor_scores(draws, window=1500):
    if len(draws) < 80:
        return {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    subset = draws[-window:] if len(draws) >= window else draws
    latest_sum = sum(int(number) for number in draws[-1]["numbers"])
    values = Counter()
    for index in range(len(subset) - 1):
        current_numbers = set(int(number) for number in subset[index]["numbers"])
        distance = abs(sum(current_numbers) - latest_sum)
        if distance > 32:
            continue
        weight = math.exp(-distance / 18)
        for number in subset[index + 1]["numbers"]:
            number = int(number)
            values[number] += weight * (1.15 if any(abs(number - anchor) <= 2 for anchor in current_numbers) else 1.0)
    return normalize({number: values.get(number, 0.0) for number in range(NUMBER_MIN, NUMBER_MAX + 1)})


def repeat_validation_scores(draws, window=1200):
    subset = draws[-window:] if len(draws) >= window else draws
    latest = set(int(number) for number in draws[-1]["numbers"])
    values = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    baseline = DRAW_SIZE / NUMBER_MAX
    for number in latest:
        sample = repeats = 0
        for index in range(len(subset) - 1):
            if number in subset[index]["numbers"]:
                sample += 1
                repeats += 1 if number in subset[index + 1]["numbers"] else 0
        if sample >= 25:
            values[number] = max(0.0, ((repeats / sample) - baseline) / baseline)
    return normalize(values)


def model_suite(draws):
    return {
        "multi_window_frequency": multi_window_frequency_scores(draws),
        "trend_break": trend_break_scores(draws),
        "gap_phase": gap_phase_scores(draws),
        "pair_lift": pair_lift_scores(draws),
        "shape_follow": shape_follow_scores(draws),
        "tail_zone_balance": tail_zone_balance_scores(draws),
        "sum_band_neighbor": sum_band_neighbor_scores(draws),
        "repeat_validation": repeat_validation_scores(draws),
    }


def combine_models(models, weights):
    total_weight = sum(weights.get(name, 0.0) for name in models) or 1.0
    values = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for name, scores in models.items():
        weight = weights.get(name, 0.0) / total_weight
        for number in values:
            values[number] += scores.get(number, 0.0) * weight
    return normalize(values)


def positive_edge_weights(backtest):
    models = backtest.get("models") or {}
    source_weights = backtest.get("weights") or {}
    adjusted = {}
    positive_count = 0
    for name in MODEL_LABELS:
        edge = float((models.get(name) or {}).get("top9_edge_vs_random", 0.0) or 0.0)
        base = float(source_weights.get(name, 1 / max(1, len(MODEL_LABELS))) or 0.0)
        if edge >= 0:
            positive_count += 1
            adjusted[name] = base * (1.0 + min(0.55, edge * 2.0))
        elif edge > -0.05:
            adjusted[name] = base * 0.18
        else:
            adjusted[name] = base * 0.04
    if positive_count == 0:
        adjusted = {name: float(source_weights.get(name, 0.0) or 0.0) for name in MODEL_LABELS}
    total = sum(adjusted.values()) or 1.0
    return {name: round(value / total, 4) for name, value in adjusted.items()}, positive_count


def apply_recent_repeat_firewall(draws, ensemble, models):
    latest = set(int(number) for number in draws[-1]["numbers"])
    repeat_scores = models.get("repeat_validation") or {}
    guarded = dict(ensemble)
    blocked = []
    allowed = []
    for number in latest:
        repeat_score = repeat_scores.get(number, 0.0)
        if repeat_score >= 0.92:
            guarded[number] *= 0.76
            allowed.append(number)
        else:
            guarded[number] *= 0.18
            blocked.append(number)
    return normalize(guarded), {
        "policy": "剛開出號禁止硬推；連莊必須通過高門檻歷史連莊驗證。",
        "latest_numbers": sorted(latest),
        "repeat_allowed": sorted(allowed),
        "repeat_blocked": sorted(blocked),
    }


def rolling_model_backtest(draws, rounds=None):
    rounds = runtime_rounds() if rounds is None else max(20, min(360, int(rounds)))
    if len(draws) < 140:
        return {"rounds": 0, "random_expectation": RANDOM_EXPECTATIONS, "models": {}, "ensemble": {}, "weights": {}}
    start = max(120, len(draws) - rounds - 1)
    totals = {name: {"rounds": 0, "top3_hits": 0, "top5_hits": 0, "top9_hits": 0, "zero_top9": 0} for name in MODEL_LABELS}
    ensemble_hits = {"rounds": 0, "top5_hits": 0, "top9_hits": 0}
    for index in range(start, len(draws) - 1):
        train = draws[: index + 1]
        actual = set(int(number) for number in draws[index + 1]["numbers"])
        models = model_suite(train)
        ensemble = combine_models(models, {name: 1.0 for name in models})
        for name, scores in models.items():
            ranked = rank_values(scores)
            top9_hits = len(set(ranked[:9]) & actual)
            totals[name]["rounds"] += 1
            totals[name]["top3_hits"] += len(set(ranked[:3]) & actual)
            totals[name]["top5_hits"] += len(set(ranked[:5]) & actual)
            totals[name]["top9_hits"] += top9_hits
            totals[name]["zero_top9"] += 1 if top9_hits == 0 else 0
        ranked_ensemble = rank_values(ensemble)
        ensemble_hits["rounds"] += 1
        ensemble_hits["top5_hits"] += len(set(ranked_ensemble[:5]) & actual)
        ensemble_hits["top9_hits"] += len(set(ranked_ensemble[:9]) & actual)
    model_rows = {}
    raw_weights = {}
    random_top9 = RANDOM_EXPECTATIONS[9]
    random_top5 = RANDOM_EXPECTATIONS[5]
    for name, data in totals.items():
        rounds_done = data["rounds"] or 1
        top3_avg = data["top3_hits"] / rounds_done
        top5_avg = data["top5_hits"] / rounds_done
        top9_avg = data["top9_hits"] / rounds_done
        edge = top9_avg - random_top9
        precision_edge = top5_avg - random_top5
        raw_weight = 0.18 + max(0.0, edge) * 1.25 + max(0.0, precision_edge) * 0.75
        if edge < -0.08:
            raw_weight *= 0.45
        elif edge < 0:
            raw_weight *= 0.72
        raw_weights[name] = raw_weight
        model_rows[name] = {
            "label": MODEL_LABELS[name],
            "rounds": data["rounds"],
            "top3_avg_hits": round(top3_avg, 3),
            "top5_avg_hits": round(top5_avg, 3),
            "top9_avg_hits": round(top9_avg, 3),
            "top9_edge_vs_random": round(edge, 4),
            "zero_top9_rate": round(data["zero_top9"] / rounds_done, 3),
            "status": "升權" if edge >= 0 else "降權",
        }
    weight_sum = sum(raw_weights.values()) or 1.0
    weights = {name: round(value / weight_sum, 4) for name, value in raw_weights.items()}
    ensemble_rounds = ensemble_hits["rounds"] or 1
    ensemble_top9 = ensemble_hits["top9_hits"] / ensemble_rounds
    return {
        "rounds": ensemble_hits["rounds"],
        "random_expectation": {str(key): round(value, 3) for key, value in RANDOM_EXPECTATIONS.items()},
        "models": model_rows,
        "weights": weights,
        "ensemble": {
            "top5_avg_hits": round(ensemble_hits["top5_hits"] / ensemble_rounds, 3),
            "top9_avg_hits": round(ensemble_top9, 3),
            "top9_edge_vs_random": round(ensemble_top9 - random_top9, 4),
        },
    }


def number_explanations(number, models, weights, max_items=4):
    ranked = []
    for name, scores in models.items():
        score = scores.get(number, 0.0)
        if score >= 0.62:
            ranked.append((score * weights.get(name, 0.0), name, score))
    ranked.sort(reverse=True)
    return [
        {"model": name, "label": MODEL_LABELS.get(name, name), "score": round(score, 3), "weight": weights.get(name, 0.0)}
        for _, name, score in ranked[:max_items]
    ]


def coverage_design(numbers):
    ordered = [int(number) for number in numbers[:9]]
    zones = Counter(number_zone(number) for number in ordered)
    tails = Counter(number % 10 for number in ordered)
    tail_collision = sum(max(0, count - 1) for count in tails.values())
    zone_collision = sum(max(0, count - 3) for count in zones.values())
    coverage_score = max(0.0, 1.0 - tail_collision * 0.055 - zone_collision * 0.09)
    tickets = []
    if len(ordered) >= 9:
        for combo in combinations(ordered, 5):
            if len(tickets) >= 10:
                break
            combo_zones = Counter(number_zone(number) for number in combo)
            combo_tails = {number % 10 for number in combo}
            if max(combo_zones.values()) <= 2 and len(combo_tails) >= 4:
                tickets.append(list(combo))
    return {
        "top9": ordered,
        "zone_balance": dict(zones),
        "tail_balance": dict(tails),
        "pair_count": math.comb(len(ordered), 2) if len(ordered) >= 2 else 0,
        "coverage_score": round(coverage_score, 3),
        "wheel_tickets": tickets[:6],
        "method": "九碼核心做區間、尾數與五碼輪組覆蓋檢查。",
    }


def _recent_pressure(draws, lookback=10):
    recent = list((draws or [])[-lookback:])
    number_counts = Counter()
    tail_counts = Counter()
    zone_counts = Counter()
    for draw in recent:
        for number in draw.get("numbers", []):
            number = int(number)
            number_counts[number] += 1
            tail_counts[number % 10] += 1
            zone_counts[number_zone(number)] += 1
    latest_numbers = {int(number) for number in (recent[-1].get("numbers", []) if recent else [])}
    return number_counts, tail_counts, zone_counts, latest_numbers


def _review_recovery_numbers(review):
    review = review or {}
    monthly = review.get("monthly_review") or {}
    rolling = review.get("rolling_summary") or {}
    missed = set()
    late = set()
    for item in monthly.get("monthly_missed_actual_numbers", []):
        if item.get("number"):
            missed.add(int(item["number"]))
    for item in monthly.get("monthly_late_hit_numbers", []):
        if item.get("number"):
            late.add(int(item["number"]))
    hit_counts = rolling.get("hit_number_counts") or {}
    for number, count in hit_counts.items():
        if int(count or 0) >= 1:
            late.add(int(number))
    return missed, late


def avoid_analysis(ensemble, models, candidates=None, draws=None, review=None):
    rank_map = {}
    for index, item in enumerate(candidates or [], 1):
        try:
            rank_map[int(item.get("number"))] = int(item.get("rank") or index)
        except Exception:
            pass
    recent_counts, recent_tails, recent_zones, latest_numbers = _recent_pressure(draws)
    missed_actual, late_hits = _review_recovery_numbers(review)
    rows = []
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        weak_models = sum(1 for scores in models.values() if scores.get(number, 0.0) < 0.34)
        appearance = ensemble.get(number, 0.0)
        avoid_score = (1.0 - appearance) * 0.68 + min(1.0, weak_models / max(1, len(models))) * 0.32
        if rank_map.get(number, 99) <= 9:
            avoid_score *= 0.72
        recent_risk = min(1.0, recent_counts.get(number, 0) / 2.0)
        tail_risk = min(1.0, recent_tails.get(number % 10, 0) / 8.0)
        zone_risk = min(1.0, recent_zones.get(number_zone(number), 0) / 12.0)
        recovery_risk = 1.0 if number in missed_actual or number in late_hits else 0.0
        if number in latest_numbers:
            recent_risk = max(recent_risk, 0.85)
        avoid_score -= recent_risk * 0.34 + tail_risk * 0.10 + zone_risk * 0.08 + recovery_risk * 0.38
        avoid_score = max(0.0, min(1.0, avoid_score))
        reasons = []
        if weak_models >= 5:
            reasons.append("多數公式偏弱")
        if rank_map.get(number, 99) > 20:
            reasons.append("候選排序後段")
        if appearance < 0.30:
            reasons.append("綜合出現分偏低")
        if recent_risk >= 0.5 or recovery_risk:
            reasons.append("近期實開或漏抓復活風險，禁止列入核心低機率")
        if not reasons:
            reasons.append("未達主推門檻")
        blocked = bool(recent_risk >= 0.5 or recovery_risk or rank_map.get(number, 99) <= 15)
        rows.append({
            "number": number,
            "avoid_score": round(avoid_score, 4),
            "appearance_score": round(appearance, 4),
            "candidate_rank": rank_map.get(number),
            "stability_count": 0,
            "weak_signal_count": weak_models,
            "recent_hit_risk": round(recent_risk, 4),
            "recovery_risk": round(recovery_risk, 4),
            "avoid_blocked_by_recent_hit_risk": blocked,
            "reasons": reasons,
        })
    rows.sort(key=lambda item: (item["avoid_score"], -item["number"]), reverse=True)
    strict_rows = [item for item in rows if not item.get("avoid_blocked_by_recent_hit_risk")]
    strict_rows.extend(item for item in rows if item.get("avoid_blocked_by_recent_hit_risk"))
    return {"method": "公式反向弱訊號加近期實開封鎖", "warning": "低機率暫避為風控排序，不是絕對不開保證；每期開獎後重新驗證。", "numbers": strict_rows[:15]}

def compute_formula_engine_analysis(draws, review=None, candidates=None, rounds=None):
    models = model_suite(draws)
    backtest = rolling_model_backtest(draws, rounds=rounds)
    weights, positive_model_count = positive_edge_weights(backtest)
    ensemble = combine_models(models, weights)
    ensemble, repeat_firewall = apply_recent_repeat_firewall(draws, ensemble, models)
    ranked = rank_values(ensemble)
    explanations = {str(number): number_explanations(number, models, weights) for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    positive_counts = {str(number): sum(1 for scores in models.values() if scores.get(number, 0.0) >= 0.62) for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    top_rows = []
    for rank, number in enumerate(ranked[:15], 1):
        top_rows.append({
            "rank": rank,
            "number": number,
            "score": round(ensemble[number], 4),
            "positive_model_count": positive_counts[str(number)],
            "reasons": [item["label"] for item in explanations[str(number)][:4]] or ["綜合公式"],
        })
    edge = (backtest.get("ensemble") or {}).get("top9_edge_vs_random", 0.0)
    if edge >= 0.04 and positive_model_count >= 3:
        status = "可升權"
    elif positive_model_count >= 1:
        status = "正值模型風控"
    else:
        status = "只做風控降權"
    return {
        "version": "formula_engine_v20260703_positive_edge_firewall_strict_repeat",
        "status": status,
        "no_future_leakage": True,
        "research_notes": RESEARCH_NOTES,
        "model_labels": MODEL_LABELS,
        "random_baseline": {str(key): round(value, 3) for key, value in RANDOM_EXPECTATIONS.items()},
        "backtest": backtest,
        "weights": weights,
        "positive_model_count": positive_model_count,
        "repeat_firewall": repeat_firewall,
        "ensemble_scores": {str(number): round(ensemble[number], 6) for number in range(NUMBER_MIN, NUMBER_MAX + 1)},
        "ensemble_top15": top_rows,
        "candidate_explanations": explanations,
        "positive_model_counts": positive_counts,
        "coverage_design": coverage_design(ranked[:9]),
        "avoid_analysis": avoid_analysis(ensemble, models, candidates, draws, review),
    }


def blend_formula_into_candidates(candidates, formula):
    if not formula or not candidates:
        return candidates
    scores = {int(number): float(score) for number, score in (formula.get("ensemble_scores") or {}).items()}
    explanations = formula.get("candidate_explanations") or {}
    positive_counts = {int(number): int(count) for number, count in (formula.get("positive_model_counts") or {}).items()}
    status = formula.get("status")
    edge = ((formula.get("backtest") or {}).get("ensemble") or {}).get("top9_edge_vs_random", 0.0)
    if status == "可升權" and edge >= 0.04:
        blend_weight = 0.30
    elif edge >= 0:
        blend_weight = 0.16
    elif status == "正值模型風控":
        blend_weight = 0.08
    else:
        blend_weight = 0.04
    rows = []
    for item in candidates:
        row = dict(item)
        number = int(row.get("number"))
        original_score = float(row.get("score") or 0.0)
        formula_score = scores.get(number, 0.0)
        support = positive_counts.get(number, 0)
        penalty = 0.08 if formula_score < 0.24 and support <= 1 else 0.0
        bonus = min(0.07, support * 0.010) if edge >= 0 else min(0.018, support * 0.003)
        row["score_before_formula_engine"] = round(original_score, 6)
        row["score"] = round(max(0.0, original_score * (1 - blend_weight) + formula_score * blend_weight + bonus - penalty), 6)
        row["formula_engine"] = {
            "score": round(formula_score, 4),
            "positive_model_count": support,
            "blend_weight": round(blend_weight, 3),
            "status": status,
            "top_reasons": explanations.get(str(number), [])[:4],
        }
        labels = [entry.get("label") for entry in explanations.get(str(number), [])[:3] if entry.get("label")]
        reason = "公式引擎" + ("：" + "、".join(labels) if labels else "驗證")
        reasons = list(row.get("reasons") or [])
        if support >= 3:
            reasons.insert(0, reason)
        elif penalty:
            reasons.insert(0, "公式引擎弱訊號降權")
        row["reasons"] = list(dict.fromkeys(reasons))[:6]
        rows.append(row)
    rows.sort(key=lambda item: (float(item.get("score") or 0.0), float(item.get("confidence_index") or 0.0), -int(item["number"])), reverse=True)
    high = max(float(item.get("score") or 0.0) for item in rows) if rows else 0.0
    low = min(float(item.get("score") or 0.0) for item in rows) if rows else 0.0
    for rank, row in enumerate(rows, 1):
        normalized = 0.0 if high == low else (float(row.get("score") or 0.0) - low) / (high - low)
        row["rank"] = rank
        row["top9_core"] = rank <= 9
        row["score"] = round(normalized, 4)
        row["confidence_index"] = round(50 + normalized * 49, 1)
        row["model_probability_percent"] = round(max(1.0, min(28.0, (row["confidence_index"] - 50) / 49 * 25)), 2)
    return rows
