import math
from collections import Counter, defaultdict
import os
from datetime import datetime, timedelta
from itertools import combinations


NUMBER_MIN = 1
NUMBER_MAX = 39
DRAW_SIZE = 5
BASE_PROBABILITY = DRAW_SIZE / NUMBER_MAX
EXPECTED_GAP = NUMBER_MAX / DRAW_SIZE
POSITIVE_EDGE_CORE_FEATURES = (
    "bayesian_posterior",
    "distribution_balance",
    "freq_300",
    "omission",
    "regime_gap_bridge",
    "similar_draw_knn",
    "omission_phase_rebound",
)


def zone_label(number):
    if number <= 10:
        return "01-10"
    if number <= 20:
        return "11-20"
    if number <= 30:
        return "21-30"
    return "31-39"


def normalize(values):
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return {key: 0.0 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def rank_values(values):
    return sorted(range(NUMBER_MIN, NUMBER_MAX + 1), key=lambda n: (values.get(n, 0), -n), reverse=True)


def frequency(draws):
    counter = Counter()
    for draw in draws:
        counter.update(draw["numbers"])
    return counter


def omission(draws):
    last_seen = {n: None for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for idx, draw in enumerate(draws):
        for number in draw["numbers"]:
            last_seen[number] = idx
    last_index = len(draws) - 1
    return {
        number: (last_index - last_seen[number] if last_seen[number] is not None else len(draws))
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }


def binomial_zscore(count, draws_count):
    expected = draws_count * BASE_PROBABILITY
    variance = max(draws_count * BASE_PROBABILITY * (1 - BASE_PROBABILITY), 1e-9)
    return (count - expected) / math.sqrt(variance)


def ewma_frequency(draws, half_life):
    scores = {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    decay_base = 0.5 ** (1 / half_life)
    for age, draw in enumerate(reversed(draws)):
        weight = decay_base ** age
        for number in draw["numbers"]:
            scores[number] += weight
    return scores


def next_draw_date(date_text):
    current = datetime.strptime(date_text, "%Y-%m-%d").date()
    return (current + timedelta(days=1)).isoformat()


def normalize_number(value):
    value = abs(int(value))
    if value == 0:
        return NUMBER_MAX
    return ((value - 1) % NUMBER_MAX) + 1


def date_numbers(date_text):
    date_value = datetime.strptime(date_text, "%Y-%m-%d")
    roc_year = date_value.year - 1911
    raw = [
        roc_year,
        date_value.month,
        date_value.day,
        int(f"{date_value.month}{date_value.day:02d}"),
        sum(int(ch) for ch in date_value.strftime("%Y%m%d")),
        roc_year + date_value.month,
        roc_year + date_value.day,
        date_value.month + date_value.day,
    ]
    result = []
    for value in raw:
        number = normalize_number(value)
        if number not in result:
            result.append(number)
    return result


def transition_scores(draws):
    latest_numbers = set(draws[-1]["numbers"])
    transition = Counter()
    source_map = defaultdict(Counter)
    for idx in range(len(draws) - 1):
        current = set(draws[idx]["numbers"])
        next_numbers = draws[idx + 1]["numbers"]
        anchors = latest_numbers & current
        if not anchors:
            continue
        for anchor in anchors:
            source_map[anchor].update(next_numbers)
        transition.update(next_numbers)
    return normalize({n: transition.get(n, 0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}), source_map


def markov_chain_scores(draws, window=1800):
    subset = draws[-window:] if len(draws) > window else draws
    latest = set(draws[-1]["numbers"])
    scores = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    if len(subset) < 3:
        return scores
    target_total = Counter()
    source_total = Counter()
    transition_total = defaultdict(Counter)
    for idx in range(len(subset) - 1):
        current = set(subset[idx]["numbers"])
        following = set(subset[idx + 1]["numbers"])
        target_total.update(following)
        for source in current:
            source_total[source] += 1
            transition_total[source].update(following)
    transitions = max(len(subset) - 1, 1)
    for source in latest:
        support = source_total.get(source, 0)
        if support < 12:
            continue
        for target in range(NUMBER_MIN, NUMBER_MAX + 1):
            conditional = transition_total[source].get(target, 0) / support
            baseline = target_total.get(target, 0) / transitions
            lift = conditional - baseline
            if lift > 0:
                scores[target] += lift
    return normalize(scores)


def time_series_scores(draws, window=240):
    subset = draws[-window:] if len(draws) > window else draws
    scores = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        fast = 0.0
        slow = 0.0
        for age, draw in enumerate(reversed(subset)):
            hit = 1.0 if number in draw["numbers"] else 0.0
            fast += hit * (0.5 ** (age / 18))
            slow += hit * (0.5 ** (age / 72))
        trend = fast - slow * 0.42
        scores[number] = trend
    return normalize(scores)


def neural_network_scores(draws):
    freq20 = normalize({n: frequency(draws[-20:]).get(n, 0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)})
    freq100 = normalize({n: frequency(draws[-100:]).get(n, 0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)})
    gaps = omission(draws)
    gap_score = normalize({n: math.log1p(gaps[n]) for n in gaps})
    markov = markov_chain_scores(draws, window=900)
    series = time_series_scores(draws, window=180)
    latest = set(draws[-1]["numbers"])
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        x = (
            freq20[number] * 0.58
            + freq100[number] * 0.72
            + gap_score[number] * 0.64
            + markov[number] * 0.82
            + series[number] * 0.74
            - (0.85 if number in latest else 0.0)
        )
        values[number] = 1.0 / (1.0 + math.exp(-(x - 1.15)))
    return normalize(values)


def validated_dependency_scores(draws, window=1800):
    subset = draws[-window:] if len(draws) > window else draws
    latest_numbers = sorted(set(draws[-1]["numbers"]))
    score = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    hypotheses = []
    fold_size = max(2, len(subset) // 3)
    segments = [
        subset[:fold_size + 1],
        subset[fold_size:max(fold_size + 2, fold_size * 2 + 1)],
        subset[max(0, fold_size * 2):],
    ]

    def segment_stat(segment, source, target):
        support = 0
        hits = 0
        target_total = 0
        transitions = max(len(segment) - 1, 1)
        for idx in range(len(segment) - 1):
            current = set(segment[idx]["numbers"])
            following = set(segment[idx + 1]["numbers"])
            if target in following:
                target_total += 1
            if source in current:
                support += 1
                if target in following:
                    hits += 1
        conditional = hits / support if support else 0.0
        baseline = target_total / transitions if transitions else BASE_PROBABILITY
        lift = conditional / baseline if baseline else 0.0
        standard_error = math.sqrt(max(baseline * (1 - baseline) / support, 1e-9)) if support else 1.0
        z_value = (conditional - baseline) / standard_error if support else 0.0
        p_value = 0.5 * math.erfc(z_value / math.sqrt(2))
        return support, hits, conditional, baseline, lift, z_value, p_value

    for source in latest_numbers:
        for target in range(NUMBER_MIN, NUMBER_MAX + 1):
            stats = [segment_stat(segment, source, target) for segment in segments]
            if all(item[0] >= 18 and item[4] >= 1.03 and item[5] > 0 for item in stats):
                hypotheses.append({
                    "source": source,
                    "target": target,
                    "stats": stats,
                    "p_value": max(item[6] for item in stats),
                    "conservative_lift": min(item[4] for item in stats),
                })

    links = []
    ordered = sorted(hypotheses, key=lambda item: item["p_value"])
    test_count = max(len(latest_numbers) * NUMBER_MAX, 1)
    accepted = []
    for rank, item in enumerate(ordered, 1):
        if item["p_value"] <= 0.10 * rank / test_count:
            accepted.append(item)
    for item in accepted:
        stats = item["stats"]
        conservative_lift = item["conservative_lift"]
        score[item["target"]] += min(conservative_lift - 1, 0.75)
        links.append({
            "source": item["source"],
            "target": item["target"],
            "fold_support": [fold[0] for fold in stats],
            "fold_hits": [fold[1] for fold in stats],
            "fold_lift": [round(fold[4], 3) for fold in stats],
            "fold_z": [round(fold[5], 3) for fold in stats],
            "p_value": round(item["p_value"], 6),
            "fdr_q": 0.10,
            "conservative_lift": round(conservative_lift, 3),
        })
    links.sort(key=lambda item: (item["conservative_lift"], min(item["fold_support"])), reverse=True)
    return normalize(score), links


def lag_dependency_profile(draws, max_lag=5, window=1800):
    subset = draws[-window:] if len(draws) > window else draws
    profile = []
    expected_overlap = DRAW_SIZE * DRAW_SIZE / NUMBER_MAX
    for lag in range(1, max_lag + 1):
        overlaps = []
        for idx in range(lag, len(subset)):
            overlaps.append(len(set(subset[idx]["numbers"]) & set(subset[idx - lag]["numbers"])))
        average = sum(overlaps) / len(overlaps) if overlaps else 0.0
        profile.append({
            "lag": lag,
            "samples": len(overlaps),
            "average_overlap": round(average, 4),
            "random_expectation": round(expected_overlap, 4),
            "edge": round(average - expected_overlap, 4),
        })
    return profile


def pair_scores(draws):
    latest_numbers = set(draws[-1]["numbers"])
    pair_counter = Counter()
    for draw in draws[-300:]:
        for pair in combinations(sorted(draw["numbers"]), 2):
            pair_counter[pair] += 1
    scores = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        scores[number] = sum(pair_counter.get(tuple(sorted((number, anchor))), 0) for anchor in latest_numbers)
    return normalize(scores)


def tail_zone_scores(draws):
    tail = Counter()
    zone = Counter()
    for draw in draws[-80:]:
        for number in draw["numbers"]:
            tail[number % 10] += 1
            zone[zone_label(number)] += 1
    tail_norm = normalize({n: tail.get(n, 0) for n in range(10)})
    zone_norm = normalize({label: zone.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]})
    return {
        number: (tail_norm[number % 10] + zone_norm[zone_label(number)]) / 2
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }


def repeat_guard(draws, window=720):
    baseline = BASE_PROBABILITY
    latest_numbers = set(draws[-1]["numbers"])
    start = max(0, len(draws) - window - 1)
    guard = {}
    for number in latest_numbers:
        sample = 0
        repeated = 0
        for idx in range(start, len(draws) - 1):
            if number in draws[idx]["numbers"]:
                sample += 1
                if number in draws[idx + 1]["numbers"]:
                    repeated += 1
        rate = repeated / sample if sample else 0.0
        historical_support = sample >= 30 and rate >= baseline * 1.18
        guard[number] = {
            "sample": sample,
            "repeat_hits": repeated,
            "repeat_rate": round(rate, 4),
            "baseline": round(baseline, 4),
            "historical_support": historical_support,
            "passed": historical_support,
            "decision": "qualified_repeat_allowed" if historical_support else "repeat_gate_failed",
        }
    return guard


def failed_number_set(review):
    if not review or review.get("severity") != "critical":
        return set()
    settled = review.get("last_settled", {})
    failed = set((settled.get("candidate_numbers") or [])[:15])
    for pack in (settled.get("strong_pack_hits") or {}).values():
        if not pack.get("passed"):
            failed.update(pack.get("numbers", []))
    failed -= set(settled.get("actual_numbers") or [])
    return {n for n in failed if NUMBER_MIN <= n <= NUMBER_MAX}


def previous_prediction_set(review, limit=15):
    if not review or not review.get("has_review"):
        return set()
    settled = review.get("last_settled", {})
    return {
        n for n in (settled.get("candidate_numbers") or [])[:limit]
        if NUMBER_MIN <= n <= NUMBER_MAX
    }


def previous_prediction_guard(number, values, review):
    if number not in previous_prediction_set(review):
        return None
    strong_conditions = [
        values.get("omission", 0) >= 0.85,
        values.get("pair", 0) >= 0.85,
        values.get("tail_zone", 0) >= 0.85,
        values.get("freq_50", 0) >= 0.85,
        values.get("freq_100", 0) >= 0.85,
        values.get("ewma_slow", 0) >= 0.85,
    ]
    validated_dependency = values.get("validated_dependency", 0) >= 0.7
    recovery_signal = values.get("missed_hit_recovery", 0) * 0.55 + values.get("rank_error_correction", 0) * 0.45
    strong_count = sum(strong_conditions)
    passed = (
        (validated_dependency and strong_count >= 2)
        or strong_count >= 3
        or (recovery_signal >= 0.62 and strong_count >= 1)
    )
    return {
        "passed": passed,
        "decision": "validated_reentry" if passed else "soft_penalty_reentry",
        "validated_dependency": validated_dependency,
        "strong_condition_count": strong_count,
        "required_strong_conditions": 2,
        "recovery_signal": round(recovery_signal, 4),
    }


def cycle_timing_scores(omissions):
    values = {}
    for number, gap in omissions.items():
        distance = abs(gap - EXPECTED_GAP) / max(EXPECTED_GAP, 1)
        moderate_overdue = 0.16 if EXPECTED_GAP * 0.9 <= gap <= EXPECTED_GAP * 2.8 else 0.0
        extreme_penalty = 0.18 if gap > EXPECTED_GAP * 5 else 0.0
        values[number] = max(0.0, math.exp(-distance) + moderate_overdue - extreme_penalty)
    return normalize(values)


def trend_alignment_scores(ewma_fast, ewma_slow, time_series_score):
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        balanced_trend = min(ewma_fast[number], ewma_slow[number])
        values[number] = balanced_trend * 0.52 + time_series_score[number] * 0.48
    return normalize(values)


def cross_model_consensus_scores(model_scores):
    votes = {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for scores in model_scores:
        ranked = rank_values(scores)
        for rank, number in enumerate(ranked[:18], 1):
            if rank <= 5:
                votes[number] += 1.0
            elif rank <= 10:
                votes[number] += 0.64
            else:
                votes[number] += 0.34
            votes[number] += max(0.0, scores.get(number, 0.0)) * 0.18
    return normalize(votes)


def bayesian_posterior_scores(draws, window=720):
    subset = draws[-window:] if len(draws) > window else draws
    counts = frequency(subset)
    draws_count = max(len(subset), 1)
    prior_strength = 24
    prior_hits = BASE_PROBABILITY * prior_strength
    posterior = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        mean = (counts.get(number, 0) + prior_hits) / (draws_count + prior_strength)
        shrink = mean / BASE_PROBABILITY if BASE_PROBABILITY else 0
        posterior[number] = max(0.0, min(2.0, shrink))
    return normalize(posterior)


def monte_carlo_stability_scores(model_scores, simulations=240):
    ranked_models = [rank_values(scores)[:15] for scores in model_scores]
    votes = Counter()
    for step in range(simulations):
        for index, ranked in enumerate(ranked_models):
            rotation = (step + index * 3) % max(len(ranked), 1)
            pool = ranked[rotation:] + ranked[:rotation]
            for rank, number in enumerate(pool[:9], 1):
                votes[number] += max(0.05, 1.0 - rank * 0.085)
    return normalize({number: votes.get(number, 0.0) for number in range(NUMBER_MIN, NUMBER_MAX + 1)})


def distribution_balance_scores(draws):
    recent = draws[-120:] if len(draws) >= 120 else draws
    zone_counts = Counter()
    tail_counts = Counter()
    for draw in recent:
        for number in draw["numbers"]:
            zone_counts[zone_label(number)] += 1
            tail_counts[number % 10] += 1
    zone_norm = normalize({label: zone_counts.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]})
    tail_norm = normalize({tail: tail_counts.get(tail, 0) for tail in range(10)})
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        zone_pressure = 1 - zone_norm[zone_label(number)]
        tail_pressure = 1 - tail_norm[number % 10]
        values[number] = zone_pressure * 0.54 + tail_pressure * 0.46
    return normalize(values)


def draw_profile(numbers):
    ordered = sorted(numbers)
    zones = Counter(zone_label(number) for number in ordered)
    return {
        "odd": sum(number % 2 for number in ordered),
        "big": sum(1 for number in ordered if number >= 20),
        "zones": [zones.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]],
        "sum_bucket": sum(ordered) // 12,
        "span_bucket": (ordered[-1] - ordered[0]) // 5,
        "tail_diversity": len({number % 10 for number in ordered}),
    }


def profile_similarity(left, right):
    zone_gap = sum(abs(a - b) for a, b in zip(left["zones"], right["zones"])) / 10
    gap = (
        abs(left["odd"] - right["odd"]) / 5 * 0.20
        + abs(left["big"] - right["big"]) / 5 * 0.18
        + zone_gap * 0.26
        + abs(left["sum_bucket"] - right["sum_bucket"]) / 16 * 0.18
        + abs(left["span_bucket"] - right["span_bucket"]) / 8 * 0.12
        + abs(left["tail_diversity"] - right["tail_diversity"]) / 5 * 0.06
    )
    return max(0.0, 1.0 - gap)


def shape_follow_scores(draws, lookback=1500):
    if len(draws) < 80:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_profile = draw_profile(draws[-1]["numbers"])
    values = Counter()
    start = max(0, len(draws) - lookback - 1)
    for idx in range(start, len(draws) - 1):
        similarity = profile_similarity(draw_profile(draws[idx]["numbers"]), latest_profile)
        if similarity < 0.52:
            continue
        weight = similarity ** 2
        for number in draws[idx + 1]["numbers"]:
            values[number] += weight
    return normalize({n: values.get(n, 0.0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)})


def zone_parity_pressure_scores(draws, lookback=720):
    if len(draws) < 80:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_profile = draw_profile(draws[-1]["numbers"])
    zone_votes = Counter()
    parity_votes = Counter()
    start = max(0, len(draws) - lookback - 1)
    for idx in range(start, len(draws) - 1):
        similarity = profile_similarity(draw_profile(draws[idx]["numbers"]), latest_profile)
        if similarity < 0.48:
            continue
        for number in draws[idx + 1]["numbers"]:
            zone_votes[zone_label(number)] += similarity
            parity_votes[number % 2] += similarity
    zone_norm = normalize({label: zone_votes.get(label, 0.0) for label in ["01-10", "11-20", "21-30", "31-39"]})
    parity_norm = normalize({parity: parity_votes.get(parity, 0.0) for parity in [0, 1]})
    return normalize({
        number: zone_norm[zone_label(number)] * 0.58 + parity_norm[number % 2] * 0.42
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    })


def regime_gap_bridge_scores(draws, lookback=1800):
    if len(draws) < 120:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_profile = draw_profile(draws[-1]["numbers"])
    latest_set = set(draws[-1]["numbers"])
    recent = draws[-90:] if len(draws) >= 90 else draws
    zone_counts = Counter()
    tail_counts = Counter()
    for draw in recent:
        for number in draw["numbers"]:
            zone_counts[zone_label(number)] += 1
            tail_counts[number % 10] += 1
    zone_pressure = normalize({label: 1.0 / max(zone_counts.get(label, 0), 1) for label in ["01-10", "11-20", "21-30", "31-39"]})
    tail_pressure = normalize({tail: 1.0 / max(tail_counts.get(tail, 0), 1) for tail in range(10)})
    omissions = omission(draws)
    omission_norm = normalize({n: math.log1p(omissions[n]) for n in omissions})
    transition_votes = Counter()
    start = max(0, len(draws) - lookback - 1)
    for idx in range(start, len(draws) - 1):
        profile = draw_profile(draws[idx]["numbers"])
        similarity = profile_similarity(profile, latest_profile)
        if similarity < 0.44:
            continue
        current_set = set(draws[idx]["numbers"])
        weight = similarity ** 1.65
        for number in draws[idx + 1]["numbers"]:
            repeat_adjust = -0.10 if number in current_set else 0.12
            transition_votes[number] += weight * (1.0 + repeat_adjust)
    transition_norm = normalize({n: transition_votes.get(n, 0.0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)})
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        latest_neighbor = 1.0 if any(abs(number - anchor) <= 2 for anchor in latest_set) else 0.0
        repeat_penalty = 0.16 if number in latest_set else 0.0
        values[number] = (
            transition_norm[number] * 0.44
            + zone_pressure[zone_label(number)] * 0.20
            + tail_pressure[number % 10] * 0.15
            + omission_norm[number] * 0.14
            + latest_neighbor * 0.07
            - repeat_penalty
        )
    return normalize(values)


def jaccard_similarity(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def similar_draw_knn_scores(draws, lookback=2400, neighbors=120):
    if len(draws) < 180:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_set = set(draws[-1]["numbers"])
    latest_profile = draw_profile(draws[-1]["numbers"])
    start = max(0, len(draws) - lookback - 1)
    matches = []
    span = max(len(draws) - start, 1)
    for idx in range(start, len(draws) - 1):
        current_set = set(draws[idx]["numbers"])
        profile_score = profile_similarity(draw_profile(draws[idx]["numbers"]), latest_profile)
        set_score = jaccard_similarity(current_set, latest_set)
        neighbor_score = sum(
            1 for number in current_set if any(abs(number - anchor) <= 2 for anchor in latest_set)
        ) / DRAW_SIZE
        similarity = profile_score * 0.48 + set_score * 0.34 + neighbor_score * 0.18
        if similarity < 0.42:
            continue
        recency = 0.82 + 0.24 * ((idx - start + 1) / span)
        matches.append((similarity * similarity * recency, idx))
    matches.sort(reverse=True)
    votes = Counter()
    for rank, (weight, idx) in enumerate(matches[:neighbors], 1):
        rank_weight = weight * (1.0 - min(rank, neighbors) / (neighbors * 1.75))
        current_set = set(draws[idx]["numbers"])
        for number in draws[idx + 1]["numbers"]:
            repeat_bias = 0.90 if number in current_set else 1.08
            latest_repeat_penalty = 0.82 if number in latest_set else 1.0
            votes[number] += rank_weight * repeat_bias * latest_repeat_penalty
    return normalize({n: votes.get(n, 0.0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)})


def omission_phase_bucket(gap):
    if gap <= 1:
        return "fresh"
    if gap <= 4:
        return "short"
    if gap <= 8:
        return "normal"
    if gap <= 15:
        return "ready"
    if gap <= 28:
        return "overdue"
    return "extreme"


def omission_phase_rebound_scores(draws, lookback=1200):
    if len(draws) < 160:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    current_gaps = omission(draws)
    current_bucket = {number: omission_phase_bucket(gap) for number, gap in current_gaps.items()}
    start = max(0, len(draws) - lookback - 1)
    last_seen = {n: None for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    opportunities = Counter()
    hits = Counter()
    for idx, draw in enumerate(draws[:-1]):
        for number in draw["numbers"]:
            last_seen[number] = idx
        if idx < start:
            continue
        next_numbers = set(draws[idx + 1]["numbers"])
        recency = 0.82 + 0.24 * ((idx - start + 1) / max(len(draws) - start, 1))
        for number in range(NUMBER_MIN, NUMBER_MAX + 1):
            gap = idx - last_seen[number] if last_seen[number] is not None else idx + 1
            if omission_phase_bucket(gap) != current_bucket[number]:
                continue
            opportunities[number] += recency
            if number in next_numbers:
                hits[number] += recency
    values = {}
    gap_norm = normalize({n: math.log1p(current_gaps[n]) for n in current_gaps})
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        support = opportunities.get(number, 0.0)
        phase_rate = (hits.get(number, 0.0) + BASE_PROBABILITY * 10) / (support + 10)
        lift = phase_rate - BASE_PROBABILITY
        support_weight = min(1.0, math.log1p(support) / math.log1p(lookback))
        overdue_bonus = 0.08 if current_bucket[number] in {"ready", "overdue"} else 0.0
        extreme_penalty = 0.08 if current_bucket[number] == "extreme" else 0.0
        values[number] = max(0.0, lift) * 4.2 * support_weight + gap_norm[number] * 0.28 + overdue_bonus - extreme_penalty
    return normalize(values)


def missed_hit_recovery_scores(review):
    if not review or not review.get("has_review"):
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    settled = review.get("last_settled", {})
    actual = set(settled.get("actual_numbers") or [])
    predicted = set((settled.get("candidate_numbers") or [])[:15])
    missed_actual = {n for n in actual - predicted if NUMBER_MIN <= n <= NUMBER_MAX}
    if not missed_actual:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    values = {}
    missed_tails = {n % 10 for n in missed_actual}
    missed_zones = {zone_label(n) for n in missed_actual}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        score = 0.0
        if number % 10 in missed_tails:
            score += 0.42
        if zone_label(number) in missed_zones:
            score += 0.34
        if any(1 <= abs(number - anchor) <= 2 for anchor in missed_actual):
            score += 0.24
        values[number] = score
    return normalize(values)


def rolling_adjustment_data(review):
    if not review or not review.get("has_review"):
        return {}
    if review.get("rolling_adjustment"):
        return review.get("rolling_adjustment") or {}

    summary = review.get("rolling_summary") or {}
    recent_settled = review.get("recent_settled") or []
    if not summary and not recent_settled:
        return {}

    def count_map_items(mapping, key_name, value_name, limit=15):
        items = []
        for key, value in (mapping or {}).items():
            try:
                key_value = int(key)
            except (TypeError, ValueError):
                key_value = key
            items.append({key_name: key_value, value_name: int(value or 0)})
        return sorted(items, key=lambda item: item[value_name], reverse=True)[:limit]

    missed_actual_numbers = Counter()
    missed_actual_tails = Counter()
    missed_actual_zones = Counter()
    late_hit_numbers = Counter()
    for settled in recent_settled:
        actual = {int(n) for n in settled.get("actual_numbers", []) if NUMBER_MIN <= int(n) <= NUMBER_MAX}
        candidates = [int(n) for n in settled.get("candidate_numbers", []) if NUMBER_MIN <= int(n) <= NUMBER_MAX]
        top10 = set(candidates[:10])
        top15_tail = set(candidates[10:15])
        for number in actual - top10:
            missed_actual_numbers[number] += 1
            missed_actual_tails[number % 10] += 1
            missed_actual_zones[zone_label(number)] += 1
        for number in actual & top15_tail:
            late_hit_numbers[number] += 1

    top5_avg = float(summary.get("avg_top5_hits", 0) or 0)
    top10_avg = float(summary.get("avg_top10_hits", 0) or 0)
    top15_avg = float(summary.get("avg_top15_hits", 0) or 0)
    recent_performance = {
        "last5_top5_avg": top5_avg,
        "last5_top10_avg": top10_avg,
        "last5_top15_avg": top15_avg,
        "recent_slump": bool(top10_avg < 1.8 or top5_avg < 0.8),
        "critical_slump": bool(top10_avg < 1.4 or top15_avg < 1.8 or summary.get("weak_top10_count", 0) >= 3),
    }

    monthly = review.get("monthly_review") or {}
    monthly_failed = {
        int(number): 3
        for number in monthly.get("monthly_failed_numbers", [])
        if isinstance(number, int) or str(number).isdigit()
    }
    monthly_late_hits = {
        int(item.get("number")): int(item.get("count", 0) or 0)
        for item in monthly.get("monthly_late_hit_numbers", [])
        if item.get("number")
    }
    monthly_missed_actual = {
        int(item.get("number")): int(item.get("count", 0) or 0)
        for item in monthly.get("monthly_missed_actual_numbers", [])
        if item.get("number")
    }
    repeated_failed = Counter()
    repeated_failed.update({
        int(item["number"]): int(item["miss_count"])
        for item in count_map_items(summary.get("failed_number_counts"), "number", "miss_count", 15)
        if isinstance(item.get("number"), int)
    })
    repeated_failed.update(monthly_failed)
    late_hit_numbers.update(monthly_late_hits)
    missed_actual_numbers.update(monthly_missed_actual)
    converted = {
        "sample_size": int(summary.get("sample_size", len(recent_settled)) or 0),
        "policy": "converted_from_main_rolling_summary_with_monthly_precision_guard",
        "penalized_reasons": [
            {
                "reason": reason,
                "miss": int(miss or 0),
                "hit": int((summary.get("hit_reason_counts") or {}).get(reason, 0) or 0),
            }
            for reason, miss in (summary.get("missed_reason_counts") or {}).items()
        ][:12],
        "boosted_reasons": [
            {
                "reason": reason,
                "hit": int(hit or 0),
                "miss": int((summary.get("missed_reason_counts") or {}).get(reason, 0) or 0),
                "late_hit_count": int(late_hit_numbers.get(number, 0)) if isinstance(reason, int) else 0,
            }
            for reason, hit in (summary.get("hit_reason_counts") or {}).items()
        ][:12],
        "repeated_failed_numbers": [{"number": n, "miss_count": c} for n, c in repeated_failed.most_common(15)],
        "late_hit_numbers": [{"number": n, "late_hit_count": c} for n, c in late_hit_numbers.most_common(12)],
        "missed_actual_numbers": [{"number": n, "missed_count": c} for n, c in missed_actual_numbers.most_common(15)],
        "missed_actual_tails": [{"tail": n, "missed_count": c} for n, c in missed_actual_tails.most_common(10)],
        "missed_actual_zones": [{"zone": n, "missed_count": c} for n, c in missed_actual_zones.most_common()],
        "recent_performance": recent_performance,
        "monthly_pack_stats": monthly.get("pack_summary", {}),
        "monthly_best_rolling_plan": monthly.get("best_rolling_plan", {}),
    }
    return converted


def rank_error_correction_scores(review):
    if not review or not review.get("has_review"):
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    rolling = rolling_adjustment_data(review)
    late_hits = {
        int(item.get("number")): int(item.get("late_hit_count", 0))
        for item in rolling.get("late_hit_numbers", [])
        if item.get("number")
    }
    repeated_misses = {
        int(item.get("number")): int(item.get("miss_count", 0))
        for item in rolling.get("repeated_failed_numbers", [])
        if item.get("number")
    }
    missed_actual = {
        int(item.get("number")): int(item.get("missed_count", 0))
        for item in rolling.get("missed_actual_numbers", [])
        if item.get("number")
    }
    missed_actual_tails = {
        int(item.get("tail")): int(item.get("missed_count", 0))
        for item in rolling.get("missed_actual_tails", [])
        if item.get("tail") is not None
    }
    missed_actual_zones = {
        str(item.get("zone")): int(item.get("missed_count", 0))
        for item in rolling.get("missed_actual_zones", [])
        if item.get("zone")
    }
    recent = rolling.get("recent_performance", {})
    slump_multiplier = 1.35 if recent.get("critical_slump") else 1.18 if recent.get("recent_slump") else 1.0
    settled = review.get("last_settled", {})
    actual = {int(n) for n in settled.get("actual_numbers", []) if NUMBER_MIN <= int(n) <= NUMBER_MAX}
    top10 = {
        int(n)
        for n in (settled.get("candidate_numbers") or [])[:10]
        if NUMBER_MIN <= int(n) <= NUMBER_MAX
    }
    last_top10_misses = actual - top10
    late_tails = {number % 10 for number in late_hits}
    late_zones = {zone_label(number) for number in late_hits}
    missed_tails = {number % 10 for number in last_top10_misses}
    missed_zones = {zone_label(number) for number in last_top10_misses}
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        score = 0.0
        if number in late_hits:
            score += min(1.0, late_hits[number] / 5) * 0.85
        if number in missed_actual:
            score += min(1.0, missed_actual[number] / 5) * 0.72
        if number in last_top10_misses:
            score += 0.42
        if number % 10 in late_tails:
            score += 0.16
        if zone_label(number) in late_zones:
            score += 0.12
        if number % 10 in missed_tails:
            score += 0.18
        if zone_label(number) in missed_zones:
            score += 0.12
        if number % 10 in missed_actual_tails:
            score += min(0.32, missed_actual_tails[number % 10] * 0.055)
        if zone_label(number) in missed_actual_zones:
            score += min(0.24, missed_actual_zones[zone_label(number)] * 0.035)
        if any(1 <= abs(number - anchor) <= 2 for anchor in late_hits):
            score += 0.14
        if any(1 <= abs(number - anchor) <= 2 for anchor in missed_actual):
            score += 0.14
        if any(1 <= abs(number - anchor) <= 2 for anchor in last_top10_misses):
            score += 0.12
        if number in repeated_misses:
            score -= min(0.72, repeated_misses[number] * 0.16)
        values[number] = score * slump_multiplier
    return normalize(values)


def slump_mode(review):
    recent = rolling_adjustment_data(review).get("recent_performance", {})
    if recent.get("critical_slump"):
        return "critical"
    if recent.get("recent_slump"):
        return "warning"
    return "normal"


def build_feature_matrix(draws, review=None, include_dependency=True):
    windows = [5, 10, 20, 50, 100, 300]
    feature_scores = {n: defaultdict(float) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    window_scores = {}

    for window in windows:
        subset = draws[-window:] if len(draws) >= window else draws
        freq = frequency(subset)
        zscores = {n: binomial_zscore(freq.get(n, 0), len(subset)) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
        normalized = normalize(zscores)
        window_scores[window] = normalized
        for number, value in normalized.items():
            feature_scores[number][f"freq_{window}"] = value

    ewma_fast = normalize(ewma_frequency(draws[-160:], 16))
    ewma_slow = normalize(ewma_frequency(draws[-360:], 60))
    omissions = omission(draws)
    omission_score = normalize({n: math.log1p(omissions[n]) / math.log1p(EXPECTED_GAP * 4) for n in omissions})
    transition_score, _ = transition_scores(draws)
    dependency_score = validated_dependency_scores(draws)[0] if include_dependency else {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    markov_score = markov_chain_scores(draws)
    time_series_score = time_series_scores(draws)
    neural_score = neural_network_scores(draws)
    pair_score = pair_scores(draws)
    tail_zone = tail_zone_scores(draws)
    cycle_timing = cycle_timing_scores(omissions)
    trend_alignment = trend_alignment_scores(ewma_fast, ewma_slow, time_series_score)
    bayesian_posterior = bayesian_posterior_scores(draws)
    distribution_balance = distribution_balance_scores(draws)
    shape_follow = shape_follow_scores(draws)
    zone_parity_pressure = zone_parity_pressure_scores(draws)
    regime_gap_bridge = regime_gap_bridge_scores(draws)
    similar_draw_knn = similar_draw_knn_scores(draws)
    omission_phase_rebound = omission_phase_rebound_scores(draws)
    missed_hit_recovery = missed_hit_recovery_scores(review)
    rank_error_correction = rank_error_correction_scores(review)
    cross_consensus = cross_model_consensus_scores([
        window_scores[20],
        window_scores[50],
        window_scores[100],
        omission_score,
        transition_score,
        dependency_score,
        markov_score,
        time_series_score,
        neural_score,
        pair_score,
        tail_zone,
        cycle_timing,
        trend_alignment,
        bayesian_posterior,
        distribution_balance,
        shape_follow,
        zone_parity_pressure,
        regime_gap_bridge,
        similar_draw_knn,
        omission_phase_rebound,
        missed_hit_recovery,
        rank_error_correction,
    ])
    monte_carlo_stability = monte_carlo_stability_scores([
        cross_consensus,
        markov_score,
        time_series_score,
        neural_score,
        pair_score,
        bayesian_posterior,
        distribution_balance,
        shape_follow,
        zone_parity_pressure,
        regime_gap_bridge,
        similar_draw_knn,
        omission_phase_rebound,
        rank_error_correction,
    ])
    next_date = next_draw_date(draws[-1]["draw_date"])
    date_set = set(date_numbers(next_date))
    date_score = {n: (1.0 if n in date_set else 0.0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_set = set(draws[-1]["numbers"])

    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        feature_scores[number]["ewma_fast"] = ewma_fast[number]
        feature_scores[number]["ewma_slow"] = ewma_slow[number]
        feature_scores[number]["omission"] = omission_score[number]
        feature_scores[number]["transition"] = transition_score[number]
        feature_scores[number]["validated_dependency"] = dependency_score[number]
        feature_scores[number]["markov_chain"] = markov_score[number]
        feature_scores[number]["time_series"] = time_series_score[number]
        feature_scores[number]["neural_network"] = neural_score[number]
        feature_scores[number]["pair"] = pair_score[number]
        feature_scores[number]["tail_zone"] = tail_zone[number]
        feature_scores[number]["cycle_timing"] = cycle_timing[number]
        feature_scores[number]["trend_alignment"] = trend_alignment[number]
        feature_scores[number]["cross_consensus"] = cross_consensus[number]
        feature_scores[number]["bayesian_posterior"] = bayesian_posterior[number]
        feature_scores[number]["monte_carlo_stability"] = monte_carlo_stability[number]
        feature_scores[number]["distribution_balance"] = distribution_balance[number]
        feature_scores[number]["shape_follow"] = shape_follow[number]
        feature_scores[number]["zone_parity_pressure"] = zone_parity_pressure[number]
        feature_scores[number]["regime_gap_bridge"] = regime_gap_bridge[number]
        feature_scores[number]["similar_draw_knn"] = similar_draw_knn[number]
        feature_scores[number]["omission_phase_rebound"] = omission_phase_rebound[number]
        feature_scores[number]["missed_hit_recovery"] = missed_hit_recovery[number]
        feature_scores[number]["rank_error_correction"] = rank_error_correction[number]
        feature_scores[number]["date"] = date_score[number]
        feature_scores[number]["repeat"] = 1.0 if number in latest_set else 0.0
        feature_scores[number]["neighbor"] = 1.0 if any(abs(number - anchor) == 1 for anchor in latest_set) else 0.0
        feature_scores[number]["positive_edge_core"] = sum(
            feature_scores[number].get(name, 0.0) for name in POSITIVE_EDGE_CORE_FEATURES
        ) / len(POSITIVE_EDGE_CORE_FEATURES)

    return feature_scores


def industrial_weights(review=None):
    weights = {
        "freq_5": 0.025,
        "freq_10": 0.045,
        "freq_20": 0.078,
        "freq_50": 0.112,
        "freq_100": 0.118,
        "freq_300": 0.055,
        "ewma_fast": 0.052,
        "ewma_slow": 0.072,
        "omission": 0.112,
        "transition": 0.064,
        "validated_dependency": 0.062,
        "markov_chain": 0.055,
        "time_series": 0.044,
        "neural_network": 0.052,
        "pair": 0.082,
        "tail_zone": 0.078,
        "cycle_timing": 0.052,
        "trend_alignment": 0.058,
        "cross_consensus": 0.098,
        "bayesian_posterior": 0.052,
        "monte_carlo_stability": 0.064,
        "distribution_balance": 0.046,
        "shape_follow": 0.072,
        "zone_parity_pressure": 0.062,
        "regime_gap_bridge": 0.086,
        "similar_draw_knn": 0.074,
        "omission_phase_rebound": 0.068,
        "missed_hit_recovery": 0.054,
        "rank_error_correction": 0.075,
        "positive_edge_core": 0.18,
        "date": 0.025,
        "repeat": 0.015,
        "neighbor": 0.025,
    }
    if review and review.get("severity") == "critical":
        weights.update(
            {
                "freq_5": 0.01,
                "freq_10": 0.02,
                "freq_20": 0.06,
                "transition": 0.045,
                "markov_chain": 0.04,
                "time_series": 0.04,
                "neural_network": 0.045,
                "cross_consensus": 0.072,
                "cycle_timing": 0.052,
                "trend_alignment": 0.052,
                "bayesian_posterior": 0.072,
                "monte_carlo_stability": 0.058,
                "distribution_balance": 0.084,
                "shape_follow": 0.052,
                "zone_parity_pressure": 0.096,
                "regime_gap_bridge": 0.172,
                "similar_draw_knn": 0.142,
                "omission_phase_rebound": 0.136,
                "missed_hit_recovery": 0.128,
                "rank_error_correction": 0.162,
                "positive_edge_core": 0.28,
                "repeat": 0.005,
                "neighbor": 0.01,
                "freq_50": 0.142,
                "freq_100": 0.13,
                "omission": 0.185,
                "tail_zone": 0.138,
                "pair": 0.132,
            }
        )
    mode = slump_mode(review)
    if mode in {"warning", "critical"}:
        intensity = 1.0 if mode == "warning" else 1.35
        for key in ["freq_5", "freq_10", "date", "repeat", "time_series", "neural_network", "cross_consensus", "shape_follow", "trend_alignment"]:
            if key in weights:
                weights[key] *= 0.74 if mode == "warning" else 0.58
        for key in [
            "rank_error_correction",
            "positive_edge_core",
            "missed_hit_recovery",
            "omission",
            "bayesian_posterior",
            "validated_dependency",
            "distribution_balance",
            "regime_gap_bridge",
            "similar_draw_knn",
            "omission_phase_rebound",
            "pair",
            "zone_parity_pressure",
        ]:
            if key in weights:
                weights[key] *= 1.0 + 0.34 * intensity
    total = sum(weights.values()) or 1
    return {key: value / total for key, value in weights.items()}


MODEL_SOURCE_LABELS = {
    "freq_5": "\u8fd15\u671f\u71b1\u5ea6",
    "freq_10": "\u8fd110\u671f\u71b1\u5ea6",
    "freq_20": "\u8fd120\u671f\u71b1\u5ea6",
    "freq_50": "\u8fd150\u671f\u71b1\u5ea6",
    "freq_100": "\u8fd1100\u671f\u71b1\u5ea6",
    "freq_300": "\u8fd1300\u671f\u7a69\u5b9a",
    "ewma_fast": "\u5feb\u901f\u52a0\u6b0a\u8da8\u52e2",
    "ewma_slow": "\u6162\u901f\u52a0\u6b0a\u8da8\u52e2",
    "omission": "\u907a\u6f0f\u9031\u671f",
    "transition": "\u62d6\u724c\u8f49\u79fb",
    "validated_dependency": "\u6a23\u672c\u5916\u9023\u52d5",
    "markov_chain": "\u99ac\u53ef\u592b",
    "time_series": "\u6642\u9593\u5e8f\u5217",
    "neural_network": "\u795e\u7d93\u7db2\u8def",
    "pair": "\u5171\u73fe\u914d\u5c0d",
    "tail_zone": "\u5c3e\u6578\u5340\u9593",
    "cycle_timing": "\u9031\u671f\u4f4d\u7f6e",
    "trend_alignment": "\u5feb\u6162\u8da8\u52e2\u4e00\u81f4",
    "cross_consensus": "\u591a\u6a21\u578b\u5171\u8b58",
    "bayesian_posterior": "\u8c9d\u6c0f\u4fdd\u5b88\u6821\u6e96",
    "monte_carlo_stability": "\u8499\u5730\u5361\u7f85\u7a69\u5b9a",
    "distribution_balance": "\u5206\u5e03\u5e73\u8861",
    "shape_follow": "\u724c\u578b\u76f8\u4f3c\u8ddf\u96a8",
    "zone_parity_pressure": "\u5340\u9593\u5947\u5076\u58d3\u529b",
    "regime_gap_bridge": "\u578b\u614b\u7f3a\u53e3\u6a4b\u63a5",
    "similar_draw_knn": "\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130",
    "omission_phase_rebound": "\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48",
    "missed_hit_recovery": "\u6f0f\u547d\u4e2d\u56de\u6536",
    "rank_error_correction": "\u6392\u540d\u932f\u4f4d\u4fee\u6b63",
    "positive_edge_core": "\u6b63\u908a\u969b\u6838\u5fc3",
    "date": "\u65e5\u671f\u724c",
    "repeat": "\u9023\u838a\u56de\u6e2c",
    "neighbor": "\u9130\u865f\u9023\u52d5",
}


def conservative_probability_percent(score):
    baseline_percent = BASE_PROBABILITY * 100
    calibrated = baseline_percent * (0.72 + max(0.0, min(score, 1.0)) * 0.74)
    return round(max(0.0, min(38.0, calibrated)), 2)


def number_model_sources(values, weights, limit=8):
    rows = []
    for name, weight in weights.items():
        value = values.get(name, 0.0)
        contribution = value * weight
        if value >= 0.42 or contribution >= 0.018:
            rows.append({
                "model": name,
                "label": MODEL_SOURCE_LABELS.get(name, name),
                "signal": round(value, 4),
                "weight": round(weight, 5),
                "contribution": round(contribution, 5),
            })
    rows.sort(key=lambda item: (item["contribution"], item["signal"]), reverse=True)
    return rows[:limit]


def number_cross_validation(values):
    checks = [
        ("multi_model_consensus", "\u591a\u6a21\u578b\u5171\u8b58", values.get("cross_consensus", 0) >= 0.58),
        ("monte_carlo_stability", "\u8499\u5730\u5361\u7f85\u7a69\u5b9a", values.get("monte_carlo_stability", 0) >= 0.58),
        ("bayesian_calibration", "\u8c9d\u6c0f\u6821\u6e96", values.get("bayesian_posterior", 0) >= 0.52),
        ("trend_alignment", "\u8da8\u52e2\u4e00\u81f4", values.get("trend_alignment", 0) >= 0.52),
        ("cycle_timing", "\u9031\u671f\u4f4d\u7f6e", values.get("cycle_timing", 0) >= 0.52),
        ("distribution_balance", "\u5206\u5e03\u5e73\u8861", values.get("distribution_balance", 0) >= 0.52),
        ("shape_follow", "\u724c\u578b\u76f8\u4f3c\u8ddf\u96a8", values.get("shape_follow", 0) >= 0.52),
        ("zone_parity_pressure", "\u5340\u9593\u5947\u5076\u58d3\u529b", values.get("zone_parity_pressure", 0) >= 0.52),
        ("regime_gap_bridge", "\u578b\u614b\u7f3a\u53e3\u6a4b\u63a5", values.get("regime_gap_bridge", 0) >= 0.52),
        ("similar_draw_knn", "\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130", values.get("similar_draw_knn", 0) >= 0.52),
        ("omission_phase_rebound", "\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48", values.get("omission_phase_rebound", 0) >= 0.52),
        ("missed_hit_recovery", "\u6f0f\u547d\u4e2d\u56de\u6536", values.get("missed_hit_recovery", 0) >= 0.52),
        ("rank_error_correction", "\u6392\u540d\u932f\u4f4d\u4fee\u6b63", values.get("rank_error_correction", 0) >= 0.52),
        ("positive_edge_core", "\u6b63\u908a\u969b\u6838\u5fc3", values.get("positive_edge_core", 0) >= 0.58),
    ]
    passed = [{"key": key, "label": label} for key, label, ok in checks if ok]
    failed = [{"key": key, "label": label} for key, label, ok in checks if not ok]
    return {
        "passed_count": len(passed),
        "total_count": len(checks),
        "passed": passed,
        "failed": failed,
        "status": "passed" if len(passed) >= 4 else "watch",
    }


def clamp(value, low, high):
    return max(low, min(high, value))


def practical_maturity_score(
    number,
    values,
    normalized_score,
    reasons,
    review,
    repeated_failed_numbers=None,
    late_hit_numbers=None,
    missed_actual_numbers=None,
    penalized_reasons=None,
):
    repeated_failed_numbers = repeated_failed_numbers or set()
    late_hit_numbers = late_hit_numbers or set()
    missed_actual_numbers = missed_actual_numbers or set()
    penalized_reasons = penalized_reasons or set()
    cross = number_cross_validation(values)
    passed = int(cross.get("passed_count", 0) or 0)
    reason_set = set(reasons or [])
    score = 38.0
    score += clamp(normalized_score, 0.0, 1.0) * 22.0
    score += min(24.0, passed * 2.35)
    score += values.get("cross_consensus", 0.0) * 4.5
    score += values.get("monte_carlo_stability", 0.0) * 4.0
    score += values.get("bayesian_posterior", 0.0) * 3.5
    score += values.get("positive_edge_core", 0.0) * 5.5
    score += values.get("distribution_balance", 0.0) * 3.0

    weak_overlap = reason_set & penalized_reasons
    score -= min(18.0, len(weak_overlap) * 6.0)
    if number in repeated_failed_numbers and number not in missed_actual_numbers and number not in late_hit_numbers:
        score -= 16.0

    prev_guard = previous_prediction_guard(number, values, review)
    if prev_guard and prev_guard.get("passed"):
        score += 4.0
    elif prev_guard and not prev_guard.get("passed"):
        score -= 10.0

    if number in missed_actual_numbers and (values.get("rank_error_correction", 0) >= 0.4 or values.get("missed_hit_recovery", 0) >= 0.5):
        score += 8.0
    if number in late_hit_numbers:
        score += 5.0
    if passed <= 2:
        score -= 10.0

    score = round(clamp(score, 0.0, 100.0), 1)
    if score >= 82:
        tier = "mature"
        multiplier = 1.08
    elif score >= 70:
        tier = "usable_watch"
        multiplier = 1.0
    elif score >= 58:
        tier = "research_only"
        multiplier = 0.82
    else:
        tier = "blocked_low_maturity"
        multiplier = 0.48
    return {
        "score": score,
        "tier": tier,
        "ranking_multiplier": multiplier,
        "cross_validation_passed": passed,
        "weak_reason_overlap": sorted(weak_overlap),
        "repeated_failed_penalty": number in repeated_failed_numbers,
        "recovery_bonus": number in missed_actual_numbers or number in late_hit_numbers,
    }


def adaptive_feature_weights(draws, review=None, rounds=360):
    base_weights = industrial_weights(review)
    if len(draws) < 160:
        return base_weights, {
            "status": "insufficient_data",
            "rounds": 0,
            "method": "fallback_base_weights",
        }
    feature_names = list(base_weights)
    stats = {
        name: {
            "rounds": 0,
            "top5_hits": 0,
            "top10_hits": 0,
            "top15_hits": 0,
            "recent_rounds": 0,
            "recent_top5_hits": 0,
            "recent_top10_hits": 0,
            "recent_top15_hits": 0,
        }
        for name in feature_names
    }
    start = max(120, len(draws) - rounds - 1)
    recent_start = max(start, len(draws) - 91)
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        features = build_feature_matrix(train, review=None, include_dependency=False)
        for name in feature_names:
            ranked = sorted(
                range(NUMBER_MIN, NUMBER_MAX + 1),
                key=lambda number: (features[number].get(name, 0.0), -number),
                reverse=True,
            )
            stats[name]["rounds"] += 1
            top5_hits = len(set(ranked[:5]) & actual)
            top10_hits = len(set(ranked[:10]) & actual)
            top15_hits = len(set(ranked[:15]) & actual)
            stats[name]["top5_hits"] += top5_hits
            stats[name]["top10_hits"] += top10_hits
            stats[name]["top15_hits"] += top15_hits
            if idx >= recent_start:
                stats[name]["recent_rounds"] += 1
                stats[name]["recent_top5_hits"] += top5_hits
                stats[name]["recent_top10_hits"] += top10_hits
                stats[name]["recent_top15_hits"] += top15_hits

    baseline = {
        5: DRAW_SIZE * 5 / NUMBER_MAX,
        10: DRAW_SIZE * 10 / NUMBER_MAX,
        15: DRAW_SIZE * 15 / NUMBER_MAX,
    }
    multipliers = {}
    feature_report = {}
    for name, item in stats.items():
        rounds_done = item["rounds"] or 1
        top5_avg = item["top5_hits"] / rounds_done
        top10_avg = item["top10_hits"] / rounds_done
        top15_avg = item["top15_hits"] / rounds_done
        recent_rounds = item["recent_rounds"] or 1
        recent_top5_avg = item["recent_top5_hits"] / recent_rounds
        recent_top10_avg = item["recent_top10_hits"] / recent_rounds
        recent_top15_avg = item["recent_top15_hits"] / recent_rounds
        full_edge = (
            (top5_avg - baseline[5]) * 0.48
            + (top10_avg - baseline[10]) * 0.34
            + (top15_avg - baseline[15]) * 0.18
        )
        recent_edge = (
            (recent_top5_avg - baseline[5]) * 0.42
            + (recent_top10_avg - baseline[10]) * 0.43
            + (recent_top15_avg - baseline[15]) * 0.15
        )
        edge = full_edge * 0.35 + recent_edge * 0.65
        if recent_edge < -0.08 and full_edge <= 0:
            multiplier = 0.08
        elif edge < -0.05:
            multiplier = 0.18
        elif edge < -0.015:
            multiplier = 0.35
        elif edge < 0:
            multiplier = 0.58
        elif recent_edge > 0.06 and full_edge > 0:
            multiplier = min(2.25, 1.0 + edge * 4.2)
        else:
            multiplier = min(1.85, 1.0 + edge * 2.4)
        multipliers[name] = multiplier
        feature_report[name] = {
            "rounds": item["rounds"],
            "recent_rounds": item["recent_rounds"],
            "top5_avg_hits": round(top5_avg, 3),
            "top10_avg_hits": round(top10_avg, 3),
            "top15_avg_hits": round(top15_avg, 3),
            "recent_top5_avg_hits": round(recent_top5_avg, 3),
            "recent_top10_avg_hits": round(recent_top10_avg, 3),
            "recent_top15_avg_hits": round(recent_top15_avg, 3),
            "full_weighted_edge": round(full_edge, 4),
            "recent_weighted_edge": round(recent_edge, 4),
            "weighted_edge": round(edge, 4),
            "multiplier": round(multiplier, 3),
        }
    adjusted = {name: base_weights[name] * multipliers[name] for name in feature_names}
    total = sum(adjusted.values()) or 1
    calibrated = {name: adjusted[name] / total for name in feature_names}
    ranked_features = sorted(feature_report.items(), key=lambda pair: pair[1]["weighted_edge"], reverse=True)
    return calibrated, {
        "status": "evaluated",
        "method": "recent_90_and_long_walk_forward_feature_weight_calibration",
        "rounds": max((item["rounds"] for item in stats.values()), default=0),
        "top_boosted_features": [
            {"feature": name, **report}
            for name, report in ranked_features[:6]
        ],
        "top_penalized_features": [
            {"feature": name, **report}
            for name, report in ranked_features[-6:]
        ],
        "base_weights": {name: round(value, 5) for name, value in base_weights.items()},
        "calibrated_weights": {name: round(value, 5) for name, value in calibrated.items()},
    }


def score_numbers(draws, review=None, include_dependency=True, weights_override=None):
    features = build_feature_matrix(draws, review, include_dependency=include_dependency)
    weights = weights_override or industrial_weights(review)
    failed = failed_number_set(review)
    rolling = rolling_adjustment_data(review)
    penalized_reasons = {item.get("reason") for item in rolling.get("penalized_reasons", [])}
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    repeated_failed_numbers = {int(item.get("number")) for item in rolling.get("repeated_failed_numbers", []) if item.get("number")}
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    missed_actual_numbers = {int(item.get("number")) for item in rolling.get("missed_actual_numbers", []) if item.get("number")}
    missed_actual_tails = {int(item.get("tail")) for item in rolling.get("missed_actual_tails", []) if item.get("tail") is not None}
    missed_actual_zones = {str(item.get("zone")) for item in rolling.get("missed_actual_zones", []) if item.get("zone")}
    mode = slump_mode(review)
    latest_set = set(draws[-1]["numbers"])
    repeat_policy = repeat_guard(draws)
    score = {}
    reasons = defaultdict(list)

    for number, values in features.items():
        raw = sum(values.get(name, 0) * weight for name, weight in weights.items())
        core_blend = 0.62 if mode == "critical" else 0.52 if mode == "warning" else 0.46
        raw = raw * (1.0 - core_blend) + values.get("positive_edge_core", 0.0) * core_blend
        previous_policy = previous_prediction_guard(number, values, review)
        if previous_policy and not previous_policy["passed"]:
            raw *= 0.66 if mode == "critical" else 0.74
            reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u8edf\u964d\u6b0a\u91cd\u65b0\u9a57\u8b49")
        elif previous_policy and previous_policy["passed"]:
            raw *= 0.96
            reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u901a\u904e\u56de\u6536\u91cd\u9a57")
        if number in failed:
            raw *= 0.58 if mode == "critical" else 0.68
            reasons[number].append("\u4e0a\u671f\u5931\u6557\u6838\u5fc3\u865f\u78bc\u8edf\u98a8\u63a7")
        if values["omission"] >= 0.7:
            reasons[number].append("\u907a\u6f0f\u88dc\u511f")
        if values["pair"] >= 0.7:
            reasons[number].append("\u5171\u73fe\u95dc\u806f")
        if values["validated_dependency"] >= 0.7:
            reasons[number].append("\u6a23\u672c\u5916\u9023\u52d5")
        if values["markov_chain"] >= 0.7:
            reasons[number].append("\u99ac\u53ef\u592b\u8f49\u79fb")
        if values["time_series"] >= 0.7:
            reasons[number].append("\u6642\u9593\u5e8f\u5217\u52d5\u80fd")
        if values["neural_network"] >= 0.7:
            reasons[number].append("\u795e\u7d93\u7db2\u8def\u7d9c\u5408")
        if values["tail_zone"] >= 0.7:
            reasons[number].append("\u5c3e\u6578\u5340\u9593")
        if values["cross_consensus"] >= 0.7:
            reasons[number].append("\u591a\u6a21\u578b\u5171\u8b58")
        if values["cycle_timing"] >= 0.7:
            reasons[number].append("\u9031\u671f\u4f4d\u7f6e")
        if values["trend_alignment"] >= 0.7:
            reasons[number].append("\u5feb\u6162\u8da8\u52e2\u4e00\u81f4")
        if values["bayesian_posterior"] >= 0.7:
            reasons[number].append("\u8c9d\u6c0f\u4fdd\u5b88\u6821\u6e96")
        if values["monte_carlo_stability"] >= 0.7:
            reasons[number].append("\u8499\u5730\u5361\u7f85\u7a69\u5b9a")
        if values["distribution_balance"] >= 0.7:
            reasons[number].append("\u5206\u5e03\u5e73\u8861\u98a8\u63a7")
        if values["shape_follow"] >= 0.7:
            reasons[number].append("\u724c\u578b\u76f8\u4f3c\u8ddf\u96a8")
        if values["zone_parity_pressure"] >= 0.7:
            reasons[number].append("\u5340\u9593\u5947\u5076\u58d3\u529b")
        if values["regime_gap_bridge"] >= 0.7:
            reasons[number].append("\u578b\u614b\u7f3a\u53e3\u6a4b\u63a5")
        if values["similar_draw_knn"] >= 0.7:
            reasons[number].append("\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130")
        if values["omission_phase_rebound"] >= 0.7:
            reasons[number].append("\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48")
        if values["missed_hit_recovery"] >= 0.7:
            reasons[number].append("\u6f0f\u547d\u4e2d\u56de\u6536")
        if values["rank_error_correction"] >= 0.7:
            reasons[number].append("\u6392\u540d\u932f\u4f4d\u4fee\u6b63")
        if values["positive_edge_core"] >= 0.66:
            reasons[number].append("\u6b63\u908a\u969b\u6838\u5fc3")
        if values["freq_50"] >= 0.7 or values["freq_100"] >= 0.7:
            reasons[number].append("\u4e2d\u671f\u7a69\u5b9a")
        if values["date"] > 0:
            reasons[number].append("\u65e5\u671f\u724c")
        if number in latest_set:
            policy = repeat_policy.get(number, {})
            if policy.get("passed"):
                raw *= 0.78
                reasons[number].append("\u9023\u838a\u5408\u683c\u9a57\u7b97")
            else:
                raw *= 0.36
                reasons[number].append("\u9023\u838a\u5b88\u9580\u672a\u901a\u904e")
        reason_set = set(reasons[number])
        if number in repeated_failed_numbers:
            raw *= 0.72 if mode == "critical" else 0.8 if mode == "warning" else 0.86
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u9023\u7e8c\u672a\u547d\u4e2d\u964d\u6b0a")
        if number in late_hit_numbers and values["rank_error_correction"] >= 0.55:
            raw *= 1.42 if mode == "critical" else 1.26 if mode == "warning" else 1.16
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u5f8c\u6bb5\u547d\u4e2d\u524d\u79fb")
        recovery_signal = (
            values["rank_error_correction"] * 0.46
            + values["missed_hit_recovery"] * 0.34
            + values["omission"] * 0.12
            + values["distribution_balance"] * 0.08
        )
        if number in missed_actual_numbers and (values["rank_error_correction"] >= 0.4 or values["missed_hit_recovery"] >= 0.5):
            raw *= 1.58 if mode == "critical" else 1.24
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u6f0f\u6293\u5be6\u958b\u865f\u88dc\u4f4d")
        elif (number % 10 in missed_actual_tails or zone_label(number) in missed_actual_zones) and mode in {"warning", "critical"}:
            raw *= 1.24 if mode == "critical" else 1.13
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u6f0f\u6293\u5c3e\u6578\u5340\u9593\u88dc\u4f4d")
        if mode == "critical" and recovery_signal >= 0.62 and number not in failed:
            raw *= 1.18 + min(0.22, recovery_signal * 0.18)
            reasons[number].append("\u5f37\u5236\u5931\u8aa4\u5f8c\u9006\u5411\u56de\u6536")
        if reason_set & penalized_reasons:
            raw *= 0.58 if mode == "critical" else 0.76 if mode == "warning" else 0.84
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u672a\u547d\u4e2d\u4f86\u6e90\u964d\u6b0a")
        if reason_set & boosted_reasons:
            raw *= 1.32 if mode == "critical" else 1.18 if mode == "warning" else 1.12
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u547d\u4e2d\u4f86\u6e90\u5347\u6b0a")
        score[number] = raw

    normalized_score = normalize(score)
    maturity = {}
    maturity_adjusted = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        maturity[number] = practical_maturity_score(
            number,
            features[number],
            normalized_score[number],
            reasons[number],
            review,
            repeated_failed_numbers=repeated_failed_numbers,
            late_hit_numbers=late_hit_numbers,
            missed_actual_numbers=missed_actual_numbers,
            penalized_reasons=penalized_reasons,
        )
        if maturity[number]["tier"] == "blocked_low_maturity":
            maturity_adjusted[number] = -1.0 + normalized_score[number] * 0.05
            reasons[number].append("\u5be6\u6230\u6210\u719f\u5ea6\u4e0d\u8db3\u964d\u6b0a")
        elif maturity[number]["tier"] == "mature":
            maturity_adjusted[number] = normalized_score[number] * maturity[number]["ranking_multiplier"]
            reasons[number].append("\u5be6\u6230\u6210\u719f\u5ea6\u901a\u904e")
        else:
            maturity_adjusted[number] = normalized_score[number] * maturity[number]["ranking_multiplier"]
    normalized_score = normalize(maturity_adjusted)
    omissions = omission(draws)
    ranked = rank_values(normalized_score)
    candidates = []
    for rank, number in enumerate(ranked, 1):
        model_sources = number_model_sources(features[number], weights)
        cross_validation = number_cross_validation(features[number])
        candidates.append(
            {
                "number": number,
                "rank": rank,
                "score": round(normalized_score[number], 4),
                "confidence_index": round(50 + normalized_score[number] * 49, 1),
                "model_probability_percent": conservative_probability_percent(normalized_score[number]),
                "omission": omissions[number],
                "repeat_guard": repeat_policy.get(number),
                "previous_prediction_guard": previous_prediction_guard(number, features[number], review),
                "model_sources": model_sources,
                "source_model_count": len(model_sources),
                "cross_validation": cross_validation,
                "practical_maturity": maturity[number],
                "reasons": reasons[number][:4] or ["\u5de5\u696d\u7d1a\u7d9c\u5408\u5206\u6578"],
            }
        )
    return candidates, weights


def diversity_penalty(selected, candidate):
    penalty = 0.0
    if any(n % 10 == candidate % 10 for n in selected):
        penalty += 0.06
    if sum(1 for n in selected if zone_label(n) == zone_label(candidate)) >= 2:
        penalty += 0.08
    if any(abs(n - candidate) == 1 for n in selected):
        penalty += 0.035
    return penalty


def optimized_group(candidates, size, review=None):
    score_map = {item["number"]: item["score"] for item in candidates}
    item_map = {item["number"]: item for item in candidates}
    failed = failed_number_set(review)
    selected = []
    pool = [item["number"] for item in candidates[:30]]
    while len(selected) < size and pool:
        best = max(
            pool,
            key=lambda n: score_map[n] - diversity_penalty(selected, n) - item_soft_risk_penalty(item_map[n], failed),
        )
        selected.append(best)
        pool.remove(best)
    return sorted(selected)


def item_soft_risk_penalty(item, failed=None):
    failed = failed or set()
    penalty = 0.0
    number = item["number"]
    if number in failed:
        penalty += 0.08
    guard = item.get("previous_prediction_guard")
    if guard and not guard.get("passed"):
        penalty += 0.055
    repeat = item.get("repeat_guard")
    if repeat and not repeat.get("passed"):
        penalty += 0.06
    if item.get("stability_count", 0) == 0:
        penalty += 0.035
    return penalty


def strong_single_group(candidates, review=None):
    rolling = rolling_adjustment_data(review)
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    repeated_failed_numbers = {int(item.get("number")) for item in rolling.get("repeated_failed_numbers", []) if item.get("number")}
    scan_limit = 18 if slump_mode(review) == "critical" else 12
    for item in candidates[:scan_limit]:
        number = item["number"]
        reasons = set(item.get("reasons", []))
        guard = item.get("previous_prediction_guard")
        if number in repeated_failed_numbers and item.get("score", 0) < 0.88:
            continue
        score = item.get("score", 0)
        confidence = item.get("confidence_index", 0)
        stability = item.get("stability_count", 0)
        boosted = bool(reasons & boosted_reasons)
        if score >= 0.9 and confidence >= 94 and not (guard and not guard.get("passed") and stability < 3):
            return [number]
        if score >= 0.84 and confidence >= 90 and (stability >= 3 or boosted or (guard and guard.get("passed"))):
            return [number]
    return []


def single_precision_group(candidates, review=None):
    failed = failed_number_set(review)
    rolling = rolling_adjustment_data(review)
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    ranked = []
    for item in candidates[:18]:
        number = item["number"]
        guard = item.get("previous_prediction_guard")
        reasons = set(item.get("reasons", []))
        precision_score = (
            item.get("score", 0) * 0.58
            + ((item.get("confidence_index", 50) - 50) / 49) * 0.22
            + min(item.get("stability_count", 0), 5) * 0.028
            + (0.045 if reasons & boosted_reasons else 0)
            + (0.035 if number in late_hit_numbers else 0)
            - item_soft_risk_penalty(item, failed)
        )
        ranked.append((precision_score, item))
    ranked.sort(key=lambda pair: (pair[0], pair[1].get("score", 0), pair[1].get("confidence_index", 0), -pair[1]["number"]), reverse=True)
    return [ranked[0][1]["number"]] if ranked else []


def five_hit_two_group(candidates, review=None):
    failed = failed_number_set(review)
    selected = []
    pool = sorted(
        candidates[:24],
        key=lambda item: (item.get("score", 0) - item_soft_risk_penalty(item, failed), item.get("stability_count", 0), -item["number"]),
        reverse=True,
    )
    for item in pool:
        if len(selected) >= 5:
            break
        number = item["number"]
        if sum(1 for selected_number in selected if zone_label(selected_number) == zone_label(number)) >= 2:
            continue
        if sum(1 for selected_number in selected if selected_number % 10 == number % 10) >= 2:
            continue
        selected.append(number)
    if len(selected) < 5:
        for item in pool:
            if item["number"] not in selected:
                selected.append(item["number"])
            if len(selected) >= 5:
                break
    return sorted(selected[:5])


def nine_hit_three_group(candidates, review=None):
    failed = failed_number_set(review)
    rolling = rolling_adjustment_data(review)
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    score_map = {item["number"]: item["score"] for item in candidates}
    pool = [
        item["number"] for item in candidates[:32]
    ]
    item_map = {item["number"]: item for item in candidates}
    selected = []
    while len(selected) < 9 and pool:
        best = max(
            pool,
            key=lambda number: (
                score_map[number]
                + (0.08 if number in late_hit_numbers else 0)
                - diversity_penalty(selected, number) * 1.35
                - item_soft_risk_penalty(item_map[number], failed)
                - (0.08 if sum(1 for n in selected if zone_label(n) == zone_label(number)) >= 3 else 0)
            ),
        )
        selected.append(best)
        pool.remove(best)
    return sorted(selected[:9])


def top_rank_group(candidates, size, review=None):
    failed = failed_number_set(review)
    ranked = sorted(
        candidates,
        key=lambda item: (item.get("score", 0) - item_soft_risk_penalty(item, failed), item.get("stability_count", 0), -item["number"]),
        reverse=True,
    )
    selected = []
    for item in ranked:
        number = item["number"]
        selected.append(number)
        if len(selected) >= size:
            break
    return sorted(selected)


def stability_group(candidates, size, review=None):
    failed = failed_number_set(review)
    ranked = sorted(
        candidates[:24],
        key=lambda item: (
            item.get("stability_count", 0),
            item.get("score", 0),
            item.get("confidence_index", 0),
            -item["number"],
        ),
        reverse=True,
    )
    selected = []
    for item in ranked:
        number = item["number"]
        selected.append(number)
        if len(selected) >= size:
            break
    return sorted(selected)


def paircover_group(candidates, size, review=None):
    selected = []
    pool = candidates[:24]
    while len(selected) < size and pool:
        best = None
        best_value = -999.0
        for item in pool:
            number = item["number"]
            if number in selected:
                continue
            maturity = item.get("practical_maturity") or {}
            cross = item.get("cross_validation") or {}
            diversity = 0.0
            if selected:
                diversity += sum(1 for other in selected if zone_label(other) != zone_label(number)) * 0.08
                diversity += sum(1 for other in selected if other % 10 != number % 10) * 0.04
            value = (
                item.get("score", 0)
                + item.get("stability_count", 0) * 0.045
                + (maturity.get("score", 0) or 0) * 0.0038
                + (cross.get("passed_count", 0) or 0) * 0.012
                + diversity
            )
            if maturity.get("tier") == "blocked_low_maturity":
                value -= 1.0
            if value > best_value:
                best_value = value
                best = number
        if best is None:
            break
        selected.append(best)
    if len(selected) < size:
        for item in candidates:
            number = item["number"]
            if number not in selected:
                selected.append(number)
            if len(selected) >= size:
                break
    return sorted(selected)


def group_by_variant(key, candidates, review=None, variant=None):
    if variant == "paircover":
        size_by_key = {"strong_single": 1, "two_hit_one": 2, "three_hit_two": 3, "five_hit_two": 5, "nine_hit_three": 9}
        return paircover_group(candidates, size_by_key.get(key, 5), review)
    if key == "strong_single":
        if variant == "single_precision":
            return single_precision_group(candidates, review)
        if variant == "top_rank":
            return top_rank_group(candidates, 1, review)
        if variant == "stability":
            return stability_group(candidates, 1, review)
        return strong_single_group(candidates, review)
    if key == "five_hit_two":
        if variant == "top_rank":
            return top_rank_group(candidates, 5, review)
        if variant == "stability":
            return stability_group(candidates, 5, review)
        return five_hit_two_group(candidates, review)
    if key == "nine_hit_three":
        if variant == "top_rank":
            return top_rank_group(candidates, 9, review)
        if variant == "stability":
            return stability_group(candidates, 9, review)
        return nine_hit_three_group(candidates, review)
    size_by_key = {"two_hit_one": 2, "three_hit_two": 3}
    return optimized_group(candidates, size_by_key.get(key, 5), review)


def precision_micro_candidate_score(item, review=None):
    confidence = float(item.get("confidence_index", item.get("score", 0)) or 0)
    if 0 < confidence <= 1:
        confidence *= 100
    probability = float(item.get("model_probability_percent", 0) or 0)
    stability = int(item.get("stability_count", 0) or 0)
    cross = item.get("cross_validation") or {}
    cross_total = max(1, int(cross.get("total_count", 0) or 0))
    cross_passed = int(cross.get("passed_count", 0) or 0)
    maturity = item.get("practical_maturity") or {}
    maturity_score = float(maturity.get("score", 0) or 0)
    frontload = float(item.get("top9_frontload_score", 0) or 0)
    base_score = float(item.get("score", 0) or 0)
    reasons = set(item.get("reasons") or [])
    rolling = rolling_adjustment_data(review)
    boosted_reasons = {row.get("reason") for row in rolling.get("boosted_reasons", []) if row.get("reason")}
    penalized_reasons = {row.get("reason") for row in rolling.get("penalized_reasons", []) if row.get("reason")}
    repeated_failed_numbers = {int(row.get("number")) for row in rolling.get("repeated_failed_numbers", []) if row.get("number")}
    late_hit_numbers = {int(row.get("number")) for row in rolling.get("late_hit_numbers", []) if row.get("number")}
    missed_actual_numbers = {int(row.get("number")) for row in rolling.get("missed_actual_numbers", []) if row.get("number")}
    number = int(item.get("number"))

    score = 0.0
    score += clamp((confidence - 50) / 49, 0.0, 1.0) * 24
    score += clamp(probability / 18.5, 0.0, 1.0) * 15
    score += clamp(stability / 5, 0.0, 1.0) * 15
    score += clamp(cross_passed / cross_total, 0.0, 1.0) * 18
    score += clamp(maturity_score / 82, 0.0, 1.0) * 13
    score += clamp(frontload, 0.0, 1.0) * 8
    score += clamp(base_score, 0.0, 1.0) * 7

    if reasons & boosted_reasons:
        score += 2.4
    if number in late_hit_numbers:
        score += 2.0
    if number in missed_actual_numbers:
        score += 1.6
    if item.get("top9_core"):
        score += 1.2

    guard = item.get("previous_prediction_guard") or {}
    repeat = item.get("repeat_guard") or {}
    tier = str(maturity.get("tier", ""))
    if guard and not guard.get("passed"):
        score -= 7.5
    if repeat and not repeat.get("passed"):
        score -= 6.5
    if tier == "blocked_low_maturity":
        score -= 14
    elif tier == "research_only":
        score -= 4
    if reasons & penalized_reasons:
        score -= min(10.0, len(reasons & penalized_reasons) * 4.0)
    if number in repeated_failed_numbers and number not in late_hit_numbers and number not in missed_actual_numbers:
        score -= 8.0
    if item_soft_risk_penalty(item, failed_number_set(review)) >= 0.1:
        score -= 2.5
    if int(item.get("rank", 99) or 99) > 9:
        score -= 20
    return round(clamp(score, 0.0, 100.0), 2)


PRECISION_VARIANT_LABELS = {
    "ensemble_precision": "\u7d9c\u5408\u7cbe\u7b97",
    "raw_score": "\u539f\u59cb\u7d9c\u5408\u5206",
    "cross_validation": "\u4ea4\u53c9\u9a57\u8b49\u512a\u5148",
    "maturity": "\u5be6\u6230\u6210\u719f\u5ea6\u512a\u5148",
    "frontload": "\u524d\u4e5d\u540d\u524d\u79fb",
    "omission_recovery": "\u907a\u6f0f\u56de\u6536",
    "tail_zone_balance": "\u5c3e\u6578\u5340\u9593\u5e73\u8861",
    "regime_gap_bridge": "\u578b\u614b\u7f3a\u53e3\u6a4b\u63a5",
    "similar_history_knn": "\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130",
    "omission_phase": "\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48",
    "failure_corrector": "\u4e0a\u671f\u5931\u8aa4\u4fee\u6b63",
}


def precision_source_signal(item, names):
    sources = item.get("model_sources") or []
    score = 0.0
    for source in sources:
        if source.get("model") in names:
            score = max(score, float(source.get("signal", 0) or 0), float(source.get("contribution", 0) or 0) * 16)
    return score


def precision_variant_item_score(item, variant, review=None):
    maturity = item.get("practical_maturity") or {}
    cross = item.get("cross_validation") or {}
    cross_total = max(1, int(cross.get("total_count", 0) or 0))
    cross_norm = clamp(int(cross.get("passed_count", 0) or 0) / cross_total, 0.0, 1.0)
    maturity_norm = clamp(float(maturity.get("score", 0) or 0) / 100, 0.0, 1.0)
    stability_norm = clamp(int(item.get("stability_count", 0) or 0) / 5, 0.0, 1.0)
    base = float(item.get("score", 0) or 0)
    frontload = float(item.get("top9_frontload_score", 0) or 0)
    omission_norm = clamp(int(item.get("omission", 0) or 0) / 18, 0.0, 1.0)
    precision_norm = precision_micro_candidate_score(item, review) / 100
    rolling = rolling_adjustment_data(review)
    late_hit_numbers = {int(row.get("number")) for row in rolling.get("late_hit_numbers", []) if row.get("number")}
    missed_actual_numbers = {int(row.get("number")) for row in rolling.get("missed_actual_numbers", []) if row.get("number")}
    repeated_failed_numbers = {int(row.get("number")) for row in rolling.get("repeated_failed_numbers", []) if row.get("number")}
    number = int(item.get("number"))

    if variant == "raw_score":
        value = base * 0.78 + stability_norm * 0.12 + cross_norm * 0.10
    elif variant == "cross_validation":
        value = cross_norm * 0.48 + base * 0.24 + stability_norm * 0.16 + maturity_norm * 0.12
    elif variant == "maturity":
        value = maturity_norm * 0.45 + cross_norm * 0.20 + base * 0.22 + stability_norm * 0.13
    elif variant == "frontload":
        value = frontload * 0.50 + base * 0.25 + cross_norm * 0.15 + maturity_norm * 0.10
    elif variant == "omission_recovery":
        recovery_signal = precision_source_signal(item, {"omission", "missed_hit_recovery", "rank_error_correction"})
        value = omission_norm * 0.32 + recovery_signal * 0.25 + base * 0.18 + cross_norm * 0.15 + maturity_norm * 0.10
    elif variant == "tail_zone_balance":
        balance_signal = precision_source_signal(item, {"tail_zone", "distribution_balance", "zone_parity_pressure"})
        value = balance_signal * 0.40 + cross_norm * 0.22 + base * 0.18 + maturity_norm * 0.12 + stability_norm * 0.08
    elif variant == "regime_gap_bridge":
        bridge_signal = precision_source_signal(item, {"regime_gap_bridge", "shape_follow", "zone_parity_pressure", "omission"})
        value = bridge_signal * 0.44 + precision_norm * 0.20 + cross_norm * 0.16 + maturity_norm * 0.10 + frontload * 0.10
    elif variant == "similar_history_knn":
        similar_signal = precision_source_signal(item, {"similar_draw_knn", "regime_gap_bridge", "shape_follow", "markov_chain"})
        value = similar_signal * 0.46 + frontload * 0.18 + cross_norm * 0.16 + precision_norm * 0.12 + maturity_norm * 0.08
    elif variant == "omission_phase":
        phase_signal = precision_source_signal(item, {"omission_phase_rebound", "omission", "cycle_timing", "bayesian_posterior"})
        value = phase_signal * 0.42 + omission_norm * 0.22 + cross_norm * 0.14 + precision_norm * 0.12 + maturity_norm * 0.10
    elif variant == "failure_corrector":
        recovery = 0.0
        if number in late_hit_numbers:
            recovery += 0.16
        if number in missed_actual_numbers:
            recovery += 0.12
        if number in repeated_failed_numbers:
            recovery -= 0.22
        value = precision_norm * 0.38 + cross_norm * 0.20 + maturity_norm * 0.15 + frontload * 0.15 + recovery + base * 0.12
    else:
        value = precision_norm * 0.50 + cross_norm * 0.16 + maturity_norm * 0.14 + stability_norm * 0.10 + frontload * 0.10

    if str(maturity.get("tier", "")) == "blocked_low_maturity":
        value -= 0.24
    return round(clamp(value, -1.0, 1.35), 5)


def precision_variant_combo_score(numbers, item_map, variant, review=None):
    if not numbers:
        return -999
    values = [precision_variant_item_score(item_map[number], variant, review) for number in numbers]
    tails = [number % 10 for number in numbers]
    zones = [zone_label(number) for number in numbers]
    parity_count = Counter(number % 2 for number in numbers)
    duplicate_tail_penalty = (len(tails) - len(set(tails))) * 0.045
    zone_penalty = max(0, max((zones.count(label) for label in set(zones)), default=0) - 2) * 0.055
    parity_penalty = max(0, max(parity_count.values(), default=0) - 2) * 0.035
    floor_bonus = min(values) * 0.18
    avg_value = sum(values) / len(values)
    return round(avg_value * 0.82 + floor_bonus - duplicate_tail_penalty - zone_penalty - parity_penalty, 5)


def precision_variant_numbers(candidates, size, variant, review=None):
    pool = [
        item for item in candidates[:9]
        if item.get("number") is not None and item.get("top9_core", int(item.get("rank", 99) or 99) <= 9)
    ]
    if len(pool) < size:
        return []
    item_map = {int(item["number"]): item for item in pool}
    if size == 1:
        best = max(
            pool,
            key=lambda item: (
                precision_variant_item_score(item, variant, review),
                float(item.get("score", 0) or 0),
                -int(item["number"]),
            ),
        )
        return [int(best["number"])]
    best_combo = max(
        combinations(item_map, size),
        key=lambda combo: (
            precision_variant_combo_score(combo, item_map, variant, review),
            sum(precision_micro_candidate_score(item_map[number], review) for number in combo),
            -sum(combo),
        ),
    )
    return sorted(best_combo)


def precision_model_tournament(draws, review=None, weights_override=None, rounds=None):
    if len(draws) < 160:
        return {
            "status": "insufficient_data",
            "rounds": 0,
            "selected_models": {},
            "message": "history is not enough for precision model tournament",
        }
    if rounds is None:
        raw_rounds = os.environ.get("TIANTIANLE_PRECISION_TOURNAMENT_ROUNDS") or os.environ.get("TIANTIANLE_GROUP_BACKTEST_MID") or "120"
        try:
            rounds = int(raw_rounds)
        except (TypeError, ValueError):
            rounds = 120
    rounds = max(30, min(int(rounds), 180))
    variants = list(PRECISION_VARIANT_LABELS)
    specs = {
        "single": {"size": 1, "goal": 1, "target": "1_hit_1"},
        "two": {"size": 2, "goal": 1, "target": "2_hit_1_to_2"},
        "three": {"size": 3, "goal": 1, "target": "3_hit_1_to_3"},
    }
    stats = {
        target: {
            variant: {"rounds": 0, "hits": 0, "passes": 0, "zero_hits": 0, "history": []}
            for variant in variants
        }
        for target in specs
    }
    start = max(120, len(draws) - rounds - 1)
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        historical_candidates, _ = score_numbers(train, None, include_dependency=False, weights_override=weights_override)
        historical_candidates, _ = top9_frontload_candidates(historical_candidates, None)
        for target, spec in specs.items():
            for variant in variants:
                numbers = precision_variant_numbers(historical_candidates, spec["size"], variant, None)
                hits = len(set(numbers) & actual)
                row = stats[target][variant]
                row["rounds"] += 1
                row["hits"] += hits
                row["passes"] += 1 if hits >= spec["goal"] else 0
                row["zero_hits"] += 1 if hits == 0 else 0
                row["history"].append(hits)

    selected_models = {}
    variant_results = {}
    for target, spec in specs.items():
        random_success = pack_probability(spec["size"], spec["goal"]).get("probability", 0)
        random_avg_hits = DRAW_SIZE * spec["size"] / NUMBER_MAX
        variant_results[target] = {}
        for variant, row in stats[target].items():
            rounds_done = row["rounds"] or 1
            history = row["history"]
            windows = {}
            for window in [30, 60, 120]:
                sample = history[-window:]
                sample_rounds = len(sample)
                sample_passes = sum(1 for hits in sample if hits >= spec["goal"])
                sample_hits = sum(sample)
                sample_zero = sum(1 for hits in sample if hits == 0)
                windows[str(window)] = {
                    "rounds": sample_rounds,
                    "pass_rate": round(sample_passes / sample_rounds, 3) if sample_rounds else 0,
                    "avg_hits": round(sample_hits / sample_rounds, 3) if sample_rounds else 0,
                    "zero_hit_rate": round(sample_zero / sample_rounds, 3) if sample_rounds else 0,
                }
            pass_rate = row["passes"] / rounds_done
            avg_hits = row["hits"] / rounds_done
            zero_rate = row["zero_hits"] / rounds_done
            recent_30 = windows["30"]
            recent_60 = windows["60"]
            recent_120 = windows["120"]
            score = (
                recent_30["pass_rate"] * 0.36
                + recent_60["pass_rate"] * 0.30
                + recent_120["pass_rate"] * 0.16
                + pass_rate * 0.08
                + clamp((recent_60["avg_hits"] - random_avg_hits) + 0.45, 0.0, 1.2) * 0.08
                - recent_30["zero_hit_rate"] * 0.10
            )
            eliminated = (
                recent_30["rounds"] >= 20
                and recent_60["rounds"] >= 30
                and recent_30["pass_rate"] < random_success * 0.72
                and recent_60["pass_rate"] < random_success * 0.86
            )
            status = "eliminated_recent_underperform" if eliminated else (
                "eligible" if recent_60["pass_rate"] >= random_success and recent_60["avg_hits"] >= random_avg_hits else "watch_only"
            )
            variant_results[target][variant] = {
                "label": PRECISION_VARIANT_LABELS[variant],
                "rounds": row["rounds"],
                "pass_rate": round(pass_rate, 3),
                "avg_hits": round(avg_hits, 3),
                "zero_hit_rate": round(zero_rate, 3),
                "random_success_probability": round(random_success, 3),
                "random_avg_hits": round(random_avg_hits, 3),
                "edge_vs_random": round(pass_rate - random_success, 3),
                "avg_hits_edge_vs_random": round(avg_hits - random_avg_hits, 3),
                "windows": windows,
                "selection_score": round(score, 4),
                "status": status,
            }
        best_variant, best_result = max(
            variant_results[target].items(),
            key=lambda pair: (
                0 if pair[1]["status"] == "eliminated_recent_underperform" else 1,
                pair[1]["selection_score"],
                pair[1]["windows"]["60"]["pass_rate"],
                pair[1]["avg_hits"],
                -pair[1]["zero_hit_rate"],
            ),
        )
        selected_models[target] = {
            "target": spec["target"],
            "size": spec["size"],
            "goal": spec["goal"],
            "selected_variant": best_variant,
            "selected_label": PRECISION_VARIANT_LABELS[best_variant],
            "status": best_result["status"],
            "selection_score": best_result["selection_score"],
            "recent_30": best_result["windows"]["30"],
            "recent_60": best_result["windows"]["60"],
            "recent_120": best_result["windows"]["120"],
            "random_success_probability": best_result["random_success_probability"],
            "random_avg_hits": best_result["random_avg_hits"],
            "action": "use_selected_model" if best_result["status"] != "eliminated_recent_underperform" else "force_watch_only",
        }
    return {
        "status": "evaluated",
        "version": "precision_tournament_v20260625",
        "rounds": max((row["rounds"] for target in stats.values() for row in target.values()), default=0),
        "windows": [30, 60, 120],
        "policy": "recent 30/60/120 settled performance selects 1, 2 and 3-number precision models; underperforming variants are eliminated",
        "selected_models": selected_models,
        "variant_results": variant_results,
    }


def precision_micro_models(candidates, review=None, governance=None, tournament=None):
    pool = [
        item for item in candidates[:9]
        if item.get("number") is not None and item.get("top9_core", int(item.get("rank", 99) or 99) <= 9)
    ]
    scored = sorted(
        [
            {
                "number": int(item["number"]),
                "score": precision_micro_candidate_score(item, review),
                "item": item,
            }
            for item in pool
        ],
        key=lambda row: (row["score"], float(row["item"].get("score", 0) or 0), -row["number"]),
        reverse=True,
    )
    score_map = {row["number"]: row["score"] for row in scored}
    item_map = {row["number"]: row["item"] for row in scored}
    failed = failed_number_set(review)

    def combo_score(numbers):
        if not numbers:
            return 0
        values = [score_map[number] for number in numbers]
        tails = [number % 10 for number in numbers]
        zones = [zone_label(number) for number in numbers]
        parity_count = Counter(number % 2 for number in numbers)
        duplicate_tail_penalty = (len(tails) - len(set(tails))) * 2.8
        zone_penalty = max(0, max((zones.count(label) for label in set(zones)), default=0) - 2) * 2.5
        parity_penalty = max(0, max(parity_count.values(), default=0) - 2) * 1.8
        failed_penalty = sum(1 for number in numbers if number in failed) * 2.2
        stability = sum(min(int(item_map[number].get("stability_count", 0) or 0), 5) for number in numbers) / len(numbers)
        cross_passed = sum(
            int((item_map[number].get("cross_validation") or {}).get("passed_count", 0) or 0)
            for number in numbers
        ) / len(numbers)
        maturity = sum(
            float((item_map[number].get("practical_maturity") or {}).get("score", 0) or 0)
            for number in numbers
        ) / len(numbers)
        score = (
            (sum(values) / len(values)) * 0.58
            + min(values) * 0.20
            + stability * 1.1
            + cross_passed * 0.85
            + clamp(maturity / 100, 0.0, 1.0) * 6
        )
        return round(score - duplicate_tail_penalty - zone_penalty - parity_penalty - failed_penalty, 2)

    selected_models = (tournament or {}).get("selected_models") or {}

    def best_combo(size, target_key):
        if len(score_map) < size:
            return {
                "numbers": [],
                "score": 0,
                "status": "withheld_no_top9_pool",
                "reason": "top9 precision pool is not enough",
            }
        selected = selected_models.get(target_key) or {}
        variant = selected.get("selected_variant") or "ensemble_precision"
        variant_numbers = precision_variant_numbers(candidates, size, variant, review)
        if variant_numbers:
            score = combo_score(variant_numbers) if size > 1 else score_map.get(variant_numbers[0], 0)
            status = "high_confidence_watch" if score >= 76 and selected.get("status") != "eliminated_recent_underperform" else "precision_watch"
            return {
                "numbers": sorted(variant_numbers),
                "score": round(score, 2),
                "status": status,
                "single_scores": {str(number): score_map.get(number, 0) for number in sorted(variant_numbers)},
                "rule": "top9_only_live_recomputed_precision_micro_model_with_30_60_120_tournament",
                "selected_model": variant,
                "selected_model_label": selected.get("selected_label", PRECISION_VARIANT_LABELS.get(variant, variant)),
                "recent_30": selected.get("recent_30", {}),
                "recent_60": selected.get("recent_60", {}),
                "recent_120": selected.get("recent_120", {}),
                "random_success_probability": selected.get("random_success_probability"),
                "high_confidence_note": "highlight_when_score_over_76_but_no_lottery_guarantee",
            }
        if size == 1:
            row = max(scored, key=lambda item: (item["score"], float(item["item"].get("score", 0) or 0), -item["number"]))
            numbers = [row["number"]]
            score = row["score"]
        else:
            best = max(
                (
                    {"numbers": list(combo), "score": combo_score(combo)}
                    for combo in combinations(score_map, size)
                ),
                key=lambda row: (row["score"], sum(score_map[n] for n in row["numbers"]), -sum(row["numbers"])),
            )
            numbers = best["numbers"]
            score = best["score"]
        return {
            "numbers": sorted(numbers),
            "score": round(score, 2),
            "status": "high_confidence_watch" if score >= 76 else "precision_watch",
            "single_scores": {str(number): score_map.get(number, 0) for number in sorted(numbers)},
            "rule": "top9_only_live_recomputed_precision_micro_model",
            "selected_model": "fallback_ensemble_precision",
            "selected_model_label": "\u5099\u63f4\u7d9c\u5408\u7cbe\u7b97",
            "high_confidence_note": "highlight_when_score_over_76_but_no_lottery_guarantee",
        }

    result = {
        "version": "precision_micro_v20260625",
        "policy": "Top9-only precision micro model; recomputed every run; 30/60/120 settled tournament selects the active model; Top10-15 cannot be promoted into high-confidence display",
        "per_draw_recompute": True,
        "top9_pool": [row["number"] for row in scored],
        "single": best_combo(1, "single"),
        "two": best_combo(2, "two"),
        "three": best_combo(3, "three"),
        "ranked": scored,
        "model_tournament": tournament or {},
        "governance": {
            "source": "industrial_engine_candidates_after_top9_frontload",
            "release_light": (governance or {}).get("release_light"),
            "research_release_light": (governance or {}).get("research_release_light"),
            "settlement": "stored_as_precision_micro_packs_for_next_draw_review",
        },
    }
    result["single"]["target"] = "1_hit_1"
    result["two"]["target"] = "2_hit_1_to_2"
    result["three"]["target"] = "3_hit_1_to_3"
    return result


def attach_precision_micro_packs(packs, precision_micro, candidates):
    score_map = {item["number"]: item.get("score", 0) for item in candidates}

    def micro_pack(model_key, name, goal):
        item = precision_micro.get(model_key) or {}
        numbers = sorted(int(number) for number in (item.get("numbers") or []))
        if not numbers:
            return empty_pack(name, goal, "precision micro model did not produce a top9-qualified pack")
        avg_score = sum(score_map.get(number, 0) for number in numbers) / len(numbers)
        return {
            "name": name,
            "hit_goal": goal,
            "hit_goal_max": len(numbers),
            "numbers": numbers,
            "score_sum": round(sum(score_map.get(number, 0) for number in numbers), 4),
            "avg_score": round(avg_score, 4),
            "precision_score": item.get("score", 0),
            "status": item.get("status", "precision_watch"),
            "official_release": False,
            "withheld_reason": "precision micro pack is highlighted and settled, but never presented as guaranteed",
            "theoretical_probability": pack_probability(len(numbers), goal),
            "zones": Counter(zone_label(number) for number in numbers),
            "tails": Counter(number % 10 for number in numbers),
            "governance": {
                "policy": precision_micro.get("policy"),
                "version": precision_micro.get("version"),
                "target": item.get("target"),
                "rule": item.get("rule"),
                "selected_model": item.get("selected_model"),
                "selected_model_label": item.get("selected_model_label"),
                "recent_30": item.get("recent_30"),
                "recent_60": item.get("recent_60"),
                "recent_120": item.get("recent_120"),
                "random_success_probability": item.get("random_success_probability"),
                "high_confidence_note": item.get("high_confidence_note"),
            },
        }

    packs["precision_single"] = micro_pack("single", "\u7cbe\u7b97\u7368\u96bb1\u4e2d1", 1)
    packs["precision_two_hit_one"] = micro_pack("two", "\u7cbe\u7b972\u4e2d1~2", 1)
    packs["precision_three_hit_one"] = micro_pack("three", "\u7cbe\u7b973\u4e2d1~3", 1)
    return packs


def top10_promotion_audit(candidates, review=None):
    rolling = rolling_adjustment_data(review)
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    promotions = []
    for rank, item in enumerate(candidates[10:15], 11):
        reasons = set(item.get("reasons", []))
        should_promote = bool(reasons & boosted_reasons) or item["number"] in late_hit_numbers or item.get("stability_count", 0) >= 4
        if should_promote:
            promotions.append(
                {
                    "number": item["number"],
                    "current_rank": rank,
                    "score": item.get("score"),
                    "confidence_index": item.get("confidence_index"),
                    "stability_count": item.get("stability_count", 0),
                    "reasons": item.get("reasons", []),
                    "action": "promote_watch_to_top10_boundary",
                }
            )
    return {
        "policy": "promote_11_to_15_when_late_hit_or_boosted_reason_is_detected",
        "promotion_candidates": promotions,
        "promotion_count": len(promotions),
    }


def top9_frontload_candidates(candidates, review=None):
    if not candidates:
        return [], {
            "policy": "top9_high_confidence_frontload",
            "status": "empty_candidates",
            "top9_numbers": [],
            "reserve_10_15_numbers": [],
            "promoted_to_top9": [],
            "demoted_from_top9": [],
        }

    rolling = rolling_adjustment_data(review)
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", []) if item.get("reason")}
    late_hit_counts = {
        int(item.get("number")): int(item.get("late_hit_count", 0) or 0)
        for item in rolling.get("late_hit_numbers", [])
        if item.get("number")
    }
    missed_actual_counts = {
        int(item.get("number")): int(item.get("missed_count", 0) or 0)
        for item in rolling.get("missed_actual_numbers", [])
        if item.get("number")
    }
    failed = failed_number_set(review)
    mode = slump_mode(review)
    original = {int(item["number"]): dict(item) for item in candidates}
    original_rank = {int(item["number"]): idx for idx, item in enumerate(candidates, 1)}
    raw_frontload = {}

    for idx, item in enumerate(candidates, 1):
        number = int(item["number"])
        reasons = set(item.get("reasons", []))
        confidence = item.get("confidence_index", 0)
        if 0 < confidence <= 1:
            confidence *= 100
        confidence_norm = clamp((confidence - 50) / 49, 0.0, 1.0)
        stability_norm = clamp(item.get("stability_count", 0) / 5, 0.0, 1.0)
        maturity = item.get("practical_maturity") or {}
        maturity_norm = clamp(float(maturity.get("score", 0) or 0) / 100, 0.0, 1.0)
        cross = item.get("cross_validation") or {}
        cross_total = max(1, int(cross.get("total_count", 0) or 0))
        cross_norm = clamp(int(cross.get("passed_count", 0) or 0) / cross_total, 0.0, 1.0)
        rank_anchor = clamp((len(candidates) - idx + 1) / max(len(candidates), 1), 0.0, 1.0)
        front_score = (
            item.get("score", 0) * 0.46
            + confidence_norm * 0.15
            + stability_norm * 0.13
            + maturity_norm * 0.10
            + cross_norm * 0.09
            + rank_anchor * 0.07
        )

        if idx <= 9:
            front_score += 0.025
        elif 10 <= idx <= 15:
            front_score += 0.025
            if number in late_hit_counts:
                front_score += 0.105 + min(0.075, late_hit_counts[number] * 0.025)
            if number in missed_actual_counts:
                front_score += 0.075 + min(0.06, missed_actual_counts[number] * 0.02)
            if reasons & boosted_reasons:
                front_score += 0.065
            if item.get("stability_count", 0) >= 3:
                front_score += 0.035
            if float(maturity.get("score", 0) or 0) >= 70:
                front_score += 0.025
        else:
            if number in late_hit_counts:
                front_score += 0.045
            if number in missed_actual_counts:
                front_score += 0.035

        risk = item_soft_risk_penalty(item, failed)
        if number in failed and number not in late_hit_counts and number not in missed_actual_counts:
            risk += 0.045
        front_score -= risk * (1.2 if mode == "critical" else 1.0)
        raw_frontload[number] = front_score

    normalized_frontload = normalize(raw_frontload)
    ranked_numbers = sorted(
        normalized_frontload,
        key=lambda number: (
            normalized_frontload[number],
            original[number].get("score", 0),
            original[number].get("confidence_index", 0),
            -number,
        ),
        reverse=True,
    )
    top9_numbers = set(ranked_numbers[:9])
    previous_top9 = {int(item["number"]) for item in candidates[:9]}
    promoted = []
    demoted = []
    adjusted = []

    for new_rank, number in enumerate(ranked_numbers, 1):
        item = dict(original[number])
        old_rank = original_rank[number]
        front_score = normalized_frontload[number]
        old_score = float(item.get("score", 0) or 0)
        blended_score = clamp(old_score * 0.48 + front_score * 0.52, 0.0, 1.0)
        if new_rank <= 9 and old_rank > 9:
            blended_score = clamp(max(blended_score, old_score + 0.035), 0.0, 1.0)
        elif new_rank > 9 and old_rank <= 9:
            blended_score = clamp(blended_score - 0.025, 0.0, 1.0)

        reasons = list(item.get("reasons", []))
        if new_rank <= 9:
            if old_rank > 9:
                promoted.append(
                    {
                        "number": number,
                        "from_rank": old_rank,
                        "to_rank": new_rank,
                        "frontload_score": round(front_score, 4),
                        "late_hit_count": late_hit_counts.get(number, 0),
                        "missed_actual_count": missed_actual_counts.get(number, 0),
                    }
                )
                reasons.insert(0, "\u0054\u006f\u0070\u0039\u524d\u79fb\u6821\u6e96")
            elif "\u0054\u006f\u0070\u0039\u6838\u5fc3\u4fdd\u7559" not in reasons:
                reasons.append("\u0054\u006f\u0070\u0039\u6838\u5fc3\u4fdd\u7559")
            action = "top9_core"
        else:
            if old_rank <= 9:
                demoted.append(
                    {
                        "number": number,
                        "from_rank": old_rank,
                        "to_rank": new_rank,
                        "frontload_score": round(front_score, 4),
                    }
                )
                reasons.insert(0, "\u0054\u006f\u0070\u0039\u672a\u904e\u95dc\u964d\u81f3\u5099\u67e5")
            elif 10 <= new_rank <= 15 and "\u0054\u006f\u0070\u0031\u0030\u002d\u0031\u0035\u5099\u67e5" not in reasons:
                reasons.append("\u0054\u006f\u0070\u0031\u0030\u002d\u0031\u0035\u5099\u67e5")
            action = "reserve_10_15" if new_rank <= 15 else "reserve_only"

        item["pre_top9_rank"] = old_rank
        item["rank"] = new_rank
        item["top9_core"] = bool(number in top9_numbers)
        item["top9_frontload_score"] = round(front_score, 4)
        item["top9_frontload_action"] = action
        item["score"] = round(blended_score, 4)
        item["confidence_index"] = round(50 + blended_score * 49, 1)
        item["model_probability_percent"] = conservative_probability_percent(blended_score)
        item["reasons"] = reasons[:5]
        adjusted.append(item)

    return adjusted, {
        "policy": "top9_high_confidence_frontload",
        "status": "active",
        "rule": "high confidence display and pack priority are compressed into ranks 1-9; ranks 10-15 are reserve only",
        "top9_numbers": [item["number"] for item in adjusted[:9]],
        "reserve_10_15_numbers": [item["number"] for item in adjusted[9:15]],
        "promoted_to_top9": promoted,
        "demoted_from_top9": demoted,
        "late_hit_numbers_used": [
            {"number": number, "late_hit_count": count}
            for number, count in sorted(late_hit_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:12]
        ],
    }


def empty_pack(name, goal, reason):
    return {
        "name": name,
        "hit_goal": goal,
        "numbers": [],
        "score_sum": 0,
        "avg_score": 0,
        "status": "withheld",
        "withheld_reason": reason,
        "theoretical_probability": pack_probability(0, goal),
        "zones": {},
        "tails": {},
    }


def watch_pack(name, goal, numbers, score_map, reason):
    if not numbers:
        return empty_pack(name, goal, reason)
    probability = pack_probability(len(numbers), goal)
    return {
        "name": name,
        "hit_goal": goal,
        "numbers": sorted(numbers),
        "score_sum": round(sum(score_map[n] for n in numbers), 4),
        "avg_score": round(sum(score_map[n] for n in numbers) / len(numbers), 4),
        "status": "research_prediction",
        "official_release": False,
        "withheld_reason": reason,
        "release_note": "daily research prediction is always provided, but official confidence gate did not pass",
        "theoretical_probability": probability,
        "zones": Counter(zone_label(n) for n in numbers),
        "tails": Counter(n % 10 for n in numbers),
        "governance": {},
    }


def pack_recent_governance(draws, rounds=None, weights_override=None):
    if rounds is None:
        rounds = runtime_rounds("TIANTIANLE_PACK_GOVERNANCE_ROUNDS", 60)
    else:
        rounds = max(30, min(720, int(rounds)))
    if len(draws) < 150:
        return {
            "status": "insufficient_data",
            "rounds": 0,
            "release_light": "red",
            "message": "historical sample is not enough for strict pack release",
            "pack_stats": {},
        }

    pack_specs = {
        "strong_single": {"size": 1, "goal": 1, "min_pass_rate": 0.20, "min_avg_hits": 0.20, "min_edge": 0.05},
        "two_hit_one": {"size": 2, "goal": 1, "min_pass_rate": 0.32, "min_avg_hits": 0.32, "min_edge": 0.05},
        "three_hit_two": {"size": 3, "goal": 2, "min_pass_rate": 0.08, "min_avg_hits": 0.42, "min_edge": 0.035},
        "five_hit_two": {"size": 5, "goal": 2, "min_pass_rate": 0.16, "min_avg_hits": 0.78, "min_edge": 0.045},
        "nine_hit_three": {"size": 9, "goal": 3, "min_pass_rate": 0.12, "min_avg_hits": 1.28, "min_edge": 0.04},
    }
    pack_variants = {
        "strong_single": ["single_precision", "dedicated", "top_rank", "stability", "paircover"],
        "two_hit_one": ["dedicated", "top_rank", "stability", "paircover"],
        "three_hit_two": ["dedicated", "top_rank", "stability", "paircover"],
        "five_hit_two": ["dedicated", "top_rank", "stability", "paircover"],
        "nine_hit_three": ["dedicated", "top_rank", "stability", "paircover"],
    }
    start = max(120, len(draws) - rounds - 1)
    research_allowed_count = 0
    stats = {
        key: {
            variant: {"rounds": 0, "passes": 0, "hits": 0, "zero_hits": 0, "hit_history": []}
            for variant in pack_variants.get(key, ["dedicated"])
        }
        for key in pack_specs
    }

    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        historical_candidates, _ = score_numbers(train, None, include_dependency=False, weights_override=weights_override)
        for key, spec in pack_specs.items():
            for variant in stats[key]:
                numbers = group_by_variant(key, historical_candidates, None, variant)
                hits = len(set(numbers) & actual)
                stats[key][variant]["rounds"] += 1
                stats[key][variant]["hits"] += hits
                stats[key][variant]["passes"] += 1 if hits >= spec["goal"] else 0
                stats[key][variant]["zero_hits"] += 1 if hits == 0 else 0
                stats[key][variant]["hit_history"].append(hits)

    pack_stats = {}
    allowed_count = 0
    for key, spec in pack_specs.items():
        variant_results = {}
        for variant, item in stats[key].items():
            rounds_done = item["rounds"] or 1
            pass_rate = item["passes"] / rounds_done
            avg_hits = item["hits"] / rounds_done
            zero_rate = item["zero_hits"] / rounds_done
            hit_history = item.get("hit_history", [])
            window_stats = {}
            for window in [60, 120, 360]:
                sample = hit_history[-window:]
                sample_rounds = len(sample)
                sample_passes = sum(1 for hits in sample if hits >= spec["goal"])
                sample_hits = sum(sample)
                sample_zero = sum(1 for hits in sample if hits == 0)
                window_stats[str(window)] = {
                    "rounds": sample_rounds,
                    "pass_rate": round(sample_passes / sample_rounds, 3) if sample_rounds else 0,
                    "avg_hits": round(sample_hits / sample_rounds, 3) if sample_rounds else 0,
                    "zero_hit_rate": round(sample_zero / sample_rounds, 3) if sample_rounds else 0,
                }
            variant_results[variant] = {
                "rounds": item["rounds"],
                "pass_rate": round(pass_rate, 3),
                "avg_hits": round(avg_hits, 3),
                "zero_hit_rate": round(zero_rate, 3),
                "windows": window_stats,
            }
        best_variant, best_result = max(
            variant_results.items(),
            key=lambda pair: (
                pair[1]["pass_rate"],
                pair[1]["avg_hits"],
                pair[1]["windows"]["120"]["avg_hits"],
                pair[1]["windows"]["60"]["avg_hits"],
                -pair[1]["zero_hit_rate"],
            ),
        )
        pass_rate = best_result["pass_rate"]
        avg_hits = best_result["avg_hits"]
        zero_rate = best_result["zero_hit_rate"]
        random_success = pack_probability(spec["size"], spec["goal"]).get("probability", 0)
        random_avg_hits = DRAW_SIZE * spec["size"] / NUMBER_MAX
        required_pass_rate = max(spec["min_pass_rate"], random_success + spec.get("min_edge", 0))
        windows = best_result.get("windows", {})
        recent_windows_passed = all(
            windows.get(str(window), {}).get("rounds", 0) >= min(window, 30)
            and windows.get(str(window), {}).get("pass_rate", 0) >= required_pass_rate
            and windows.get(str(window), {}).get("avg_hits", 0) >= spec["min_avg_hits"]
            for window in [60, 120]
        )
        passed = pass_rate >= required_pass_rate and avg_hits >= spec["min_avg_hits"] and recent_windows_passed
        research_windows_passed = all(
            windows.get(str(window), {}).get("rounds", 0) >= min(window, 30)
            and (
                windows.get(str(window), {}).get("pass_rate", 0) >= random_success * 0.75
                or windows.get(str(window), {}).get("avg_hits", 0) >= random_avg_hits * 1.05
            )
            and windows.get(str(window), {}).get("avg_hits", 0) >= random_avg_hits * 0.95
            for window in [60, 120]
        )
        research_passed = pass_rate >= random_success and avg_hits >= random_avg_hits and research_windows_passed
        allowed_count += 1 if passed else 0
        research_allowed_count += 1 if research_passed else 0
        pack_stats[key] = {
            "rounds": best_result["rounds"],
            "goal": spec["goal"],
            "size": spec["size"],
            "pass_rate": pass_rate,
            "avg_hits": avg_hits,
            "zero_hit_rate": zero_rate,
            "random_success_probability": round(random_success, 3),
            "random_avg_hits": round(random_avg_hits, 3),
            "required_pass_rate": round(required_pass_rate, 3),
            "pass_rate_edge_vs_random": round(pass_rate - random_success, 3),
            "avg_hits_edge_vs_random": round(avg_hits - random_avg_hits, 3),
            "min_pass_rate": spec["min_pass_rate"],
            "min_avg_hits": spec["min_avg_hits"],
            "recent_windows_passed": recent_windows_passed,
            "research_windows_passed": research_windows_passed,
            "research_passed": research_passed,
            "windows": windows,
            "passed": passed,
            "best_variant": best_variant,
            "variant_results": variant_results,
        }

    release_light = "green" if allowed_count >= 4 else "yellow" if allowed_count >= 2 else "red"
    research_release_light = "green" if research_allowed_count >= 4 else "yellow" if research_allowed_count >= 2 else "red"
    governance_rounds = max((item.get("rounds", 0) for item in pack_stats.values()), default=0)
    return {
        "status": "evaluated",
        "rounds": governance_rounds,
        "release_light": release_light,
        "allowed_pack_count": allowed_count,
        "research_release_light": research_release_light,
        "research_allowed_pack_count": research_allowed_count,
        "pack_stats": pack_stats,
        "message": "strict walk-forward governance with daily variant tournament; lower confidence packs are still output as research predictions",
    }


def strict_candidate_pool(candidates, min_score=0.64, min_confidence=81.0, min_stability=1, min_maturity=58.0):
    return [
        item for item in candidates
        if item.get("score", 0) >= min_score
        and item.get("confidence_index", 0) >= min_confidence
        and item.get("stability_count", 0) >= min_stability
        and item.get("practical_maturity", {}).get("score", 100) >= min_maturity
    ]


def strong_packs(candidates, review=None, governance=None):
    score_map = {item["number"]: item["score"] for item in candidates}
    candidate_map = {item["number"]: item for item in candidates}
    strict_pool = strict_candidate_pool(candidates)
    qualified_numbers = {item["number"] for item in strict_pool}
    governance = governance or {"pack_stats": {}}
    pack_stats = governance.get("pack_stats", {})
    monthly_stats = rolling_adjustment_data(review).get("monthly_pack_stats", {}) if review else {}

    def maturity_score(number):
        return candidate_map.get(number, {}).get("practical_maturity", {}).get("score", 0)

    def attach_maturity(pack_obj, numbers, key, min_maturity):
        values = [maturity_score(number) for number in numbers if number in candidate_map]
        avg_maturity = round(sum(values) / len(values), 1) if values else 0
        pack_obj["maturity"] = {
            "avg_score": avg_maturity,
            "min_required": min_maturity,
            "passed": bool(values) and avg_maturity >= min_maturity,
            "tiers": Counter(candidate_map[number].get("practical_maturity", {}).get("tier", "unknown") for number in numbers if number in candidate_map),
        }
        pack_obj["maturity_governance"] = {
            "policy": "practical_maturity_gate",
            "pack_key": key,
            "reason": "recent live prediction quality, cross validation, repeated failure and recovery signals",
        }
        return pack_obj

    def pack(name, goal, numbers):
        if not numbers:
            return empty_pack(name, goal, "no candidate passed strict confidence gate")
        probability = pack_probability(len(numbers), goal)
        avg_score = sum(score_map[n] for n in numbers) / len(numbers)
        return {
            "name": name,
            "hit_goal": goal,
            "numbers": numbers,
            "score_sum": round(sum(score_map[n] for n in numbers), 4),
            "avg_score": round(avg_score, 4),
            "status": "released",
            "official_release": True,
            "theoretical_probability": probability,
            "zones": Counter(zone_label(n) for n in numbers),
            "tails": Counter(n % 10 for n in numbers),
            "governance": {},
        }

    def complete_pack_numbers(key, numbers, size):
        selected = []
        for number in numbers or []:
            if number not in selected:
                selected.append(number)
        if len(selected) >= size:
            return sorted(selected[:size])
        if key == "nine_hit_three":
            pool = candidates[:9]
        else:
            pool = candidates[: max(size, 12)]
        for item in pool:
            number = item["number"]
            if number not in selected:
                selected.append(number)
            if len(selected) >= size:
                break
        return sorted(selected[:size])

    specs = {
        "strong_single": ("\u6700\u5f37\u55ae\u652f", 1, 1, 0.78, 1, 82.0),
        "two_hit_one": ("\u6700\u5f372\u4e2d1", 1, 2, 0.76, 2, 76.0),
        "three_hit_two": ("\u6700\u5f373\u4e2d2~3", 2, 3, 0.78, 2, 78.0),
        "five_hit_two": ("\u6700\u5f375\u4e2d2", 2, 5, 0.68, 1, 72.0),
        "nine_hit_three": ("\u6700\u5f379\u4e2d3", 3, 9, 0.62, 0, 68.0),
    }
    packs = {}
    for key, (name, goal, size, min_avg_score, min_stability, min_maturity) in specs.items():
        recent_stat = pack_stats.get(key, {})
        variant = recent_stat.get("best_variant", "dedicated")
        allowed_pool = [
            item for item in candidates[:30]
            if item.get("practical_maturity", {}).get("score", 0) >= min_maturity
            and (
                item["number"] in qualified_numbers
                or (
                    item.get("score", 0) >= min_avg_score
                    and item.get("stability_count", 0) >= min_stability
                )
            )
        ]
        if len(allowed_pool) < size:
            fallback_floor = min(58.0, min_maturity)
            fallback_pool = [
                item for item in candidates[: max(size, 18)]
                if item.get("practical_maturity", {}).get("score", 0) >= fallback_floor
            ] or candidates[: max(size, 12)]
            fallback_numbers = group_by_variant(key, fallback_pool, review, variant)
            if len(fallback_numbers) < size and fallback_pool:
                fallback_numbers = top_rank_group(fallback_pool, size, review)
            fallback_numbers = complete_pack_numbers(key, fallback_numbers, size)
            packs[key] = attach_maturity(watch_pack(name, goal, fallback_numbers, score_map, "strict confidence and maturity pool failed; output as daily research prediction"), fallback_numbers, key, min_maturity)
            packs[key]["governance"] = recent_stat
            packs[key]["monthly_governance"] = monthly_stats.get(key, {})
            continue
        numbers = group_by_variant(key, allowed_pool, review, variant)
        if not numbers and allowed_pool:
            numbers = [allowed_pool[0]["number"]] if size == 1 else optimized_group(allowed_pool, size, review)
        numbers = complete_pack_numbers(key, numbers, size)
        avg_score = sum(score_map[n] for n in numbers) / len(numbers) if numbers else 0
        monthly_stat = monthly_stats.get(key, {})
        monthly_blocked = bool(monthly_stat) and monthly_stat.get("status") == "strict_downshift"
        avg_maturity = sum(maturity_score(n) for n in numbers) / len(numbers) if numbers else 0
        weak_numbers = [
            n for n in numbers
            if candidate_map[n].get("previous_prediction_guard") and not candidate_map[n]["previous_prediction_guard"].get("passed")
        ]
        if monthly_blocked:
            packs[key] = watch_pack(name, goal, numbers, score_map, "monthly settled predictions did not pass precision gate; output as daily research prediction")
        elif recent_stat and not recent_stat.get("passed"):
            packs[key] = watch_pack(name, goal, numbers, score_map, "recent walk-forward pack performance did not pass official gate; output as daily research prediction")
        elif avg_maturity < min_maturity:
            packs[key] = watch_pack(name, goal, numbers, score_map, "practical maturity gate did not pass; output as daily research prediction")
        elif avg_score < min_avg_score:
            packs[key] = watch_pack(name, goal, numbers, score_map, "average score is below strict release threshold; output as daily research prediction")
        elif weak_numbers:
            packs[key] = watch_pack(name, goal, numbers, score_map, "contains previous prediction re-entry numbers that failed the strict gate; output as daily research prediction")
        else:
            packs[key] = pack(name, goal, sorted(numbers))
        packs[key] = attach_maturity(packs[key], packs[key].get("numbers", numbers), key, min_maturity)
        packs[key]["governance"] = recent_stat
        packs[key]["monthly_governance"] = monthly_stat

    wheel = build_covering_wheel(packs["nine_hit_three"].get("numbers", []), ticket_size=5, cover_size=3, max_tickets=12)
    packs["nine_hit_three"]["wheel_tickets"] = wheel["tickets"]
    packs["nine_hit_three"]["wheel_coverage"] = wheel["coverage"]
    return packs


def practical_maturity_summary(candidates):
    def maturity_score(item):
        return float((item.get("practical_maturity") or {}).get("score", 0) or 0)

    def avg(items):
        return round(sum(maturity_score(item) for item in items) / len(items), 1) if items else 0.0

    top10 = candidates[:10]
    top15 = candidates[:15]
    tier_counts = Counter(
        (item.get("practical_maturity") or {}).get("tier", "unknown")
        for item in top10
    )
    mature_or_usable = sum(
        1
        for item in top10
        if (item.get("practical_maturity") or {}).get("tier") in {"mature", "usable_watch"}
    )
    low_maturity = sum(
        1
        for item in top10
        if (item.get("practical_maturity") or {}).get("tier") == "blocked_low_maturity"
    )
    top10_avg = avg(top10)
    status = "passed" if top10_avg >= 70.0 and mature_or_usable >= 5 and low_maturity == 0 else "watch_only"
    return {
        "policy": "live_prediction_practical_maturity_governor",
        "status": status,
        "top10_avg_maturity": top10_avg,
        "top15_avg_maturity": avg(top15),
        "top10_mature_or_usable_count": mature_or_usable,
        "top10_blocked_low_maturity_count": low_maturity,
        "top10_tier_counts": dict(tier_counts),
        "required": "top10_avg_maturity>=70, mature_or_usable>=5, blocked_low_maturity=0",
        "action": "official_release_allowed" if status == "passed" else "force_watch_only_and_re_rank",
        "top10_numbers": [
            {
                "number": item.get("number"),
                "maturity": maturity_score(item),
                "tier": (item.get("practical_maturity") or {}).get("tier", "unknown"),
                "cross_validation_passed": (item.get("practical_maturity") or {}).get("cross_validation_passed", 0),
            }
            for item in top10
        ],
    }


def combinations_count(n, r):
    if r < 0 or r > n:
        return 0
    return math.comb(n, r)


def pack_probability(pool_size, hit_goal):
    total = combinations_count(NUMBER_MAX, DRAW_SIZE)
    favorable = 0
    for hits in range(hit_goal, min(pool_size, DRAW_SIZE) + 1):
        favorable += combinations_count(pool_size, hits) * combinations_count(NUMBER_MAX - pool_size, DRAW_SIZE - hits)
    return {
        "hit_goal": hit_goal,
        "pool_size": pool_size,
        "probability": round(favorable / total, 6) if total else 0,
        "odds_1_in": round(total / favorable, 2) if favorable else None,
    }


def draw_signature(draw):
    numbers = sorted(draw["numbers"])
    odd = sum(1 for number in numbers if number % 2)
    small = sum(1 for number in numbers if number <= 19)
    zones = Counter(zone_label(number) for number in numbers)
    tails = Counter(number % 10 for number in numbers)
    return {
        "sum": sum(numbers),
        "odd_even": f"{odd}:{DRAW_SIZE - odd}",
        "small_big": f"{small}:{DRAW_SIZE - small}",
        "zones": dict(zones),
        "tails": dict(tails),
        "span": numbers[-1] - numbers[0],
        "consecutive_pairs": sum(1 for left, right in zip(numbers, numbers[1:]) if right - left == 1),
    }


def regime_analysis(draws):
    latest = draw_signature(draws[-1])
    recent = [draw_signature(draw) for draw in draws[-50:]]
    sums = [item["sum"] for item in recent]
    spans = [item["span"] for item in recent]
    latest_sum_z = zscore(latest["sum"], sums)
    latest_span_z = zscore(latest["span"], spans)
    messages = []
    if abs(latest_sum_z) >= 1.5:
        messages.append("\u548c\u503c\u504f\u96e2\u8fd150\u671f\u5e38\u614b")
    if abs(latest_span_z) >= 1.5:
        messages.append("\u8de8\u5ea6\u504f\u96e2\u8fd150\u671f\u5e38\u614b")
    if latest["consecutive_pairs"] >= 2:
        messages.append("\u9023\u865f\u504f\u591a")
    if not messages:
        messages.append("\u672a\u898b\u660e\u986f\u7570\u5e38\u578b\u614b")
    return {
        "latest_signature": latest,
        "sum_zscore": round(latest_sum_z, 3),
        "span_zscore": round(latest_span_z, 3),
        "messages": messages,
    }


def zscore(value, values):
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / max(len(values) - 1, 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (value - mean) / std


def model_audit(backtest_result, review=None):
    top10 = backtest_result.get("top10_avg_hits", 0)
    random_expectation = backtest_result.get("random_top10_expectation", DRAW_SIZE * 10 / NUMBER_MAX)
    edge = top10 - random_expectation
    if review and review.get("severity") == "critical":
        risk = "\u9ad8"
        verdict = "\u6700\u8fd1\u771f\u5be6\u9810\u6e2c\u51fa\u73fe\u91cd\u5927\u5931\u6557\uff0c\u5df2\u555f\u7528\u5931\u6557\u9694\u96e2\u8207\u5206\u6563\u6a21\u5f0f"
    elif edge > 0.08:
        risk = "\u4e2d"
        verdict = "\u56de\u6e2c\u7565\u512a\u65bc\u96a8\u6a5f\uff0c\u4f46\u4ecd\u9700\u6301\u7e8c\u8ffd\u8e64\u771f\u5be6\u7e3e\u6548"
    else:
        risk = "\u9ad8"
        verdict = "\u56de\u6e2c\u512a\u52e2\u5f88\u5c0f\uff0c\u4e0d\u53ef\u904e\u5ea6\u653e\u5927\u4fe1\u5fc3"
    return {
        "risk_level": risk,
        "edge_vs_random": round(edge, 4),
        "verdict": verdict,
    }


def prediction_gap_diagnosis(draws, candidates, precision_tournament, pack_governance, weight_calibration, backtest_result, validated_links, review=None):
    missing = []
    actions = []
    action_labels = {
        "boost_regime_gap_bridge": "\u52a0\u6b0a\u578b\u614b\u7f3a\u53e3\u6a4b\u63a5",
        "tighten_pack_tournament": "\u6536\u7dca\u5f37\u724c\u5c0f\u7d44\u7af6\u8cfd",
        "precision_watch_gate": "\u5c0f\u7d44\u672a\u904e\u95dc\u6539\u5217\u89c0\u5bdf",
        "reduce_dependency_overtrust": "\u964d\u4f4e\u9023\u52d5\u904e\u5ea6\u4f9d\u8cf4",
        "rebalance_top9_pool": "\u91cd\u5e73\u8861\u524d\u4e5d\u540d\u5340\u9593\u8207\u5c3e\u6578",
        "force_failure_feedback": "\u5f37\u5236\u5957\u7528\u4e0a\u671f\u5931\u8aa4\u56de\u994b",
        "boost_similarity_knn": "\u555f\u7528\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130\u88dc\u5f37",
        "boost_omission_phase": "\u555f\u7528\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48\u88dc\u5f37",
        "keep_current_tournament": "\u7dad\u6301\u73fe\u884c\u6efe\u52d5\u7af6\u8cfd",
    }
    pack_labels = {
        "strong_single": "\u5f37\u7368",
        "two_hit_one": "\u4e8c\u4e2d\u4e00",
        "three_hit_two": "\u4e09\u4e2d\u4e8c",
        "five_hit_two": "\u4e94\u4e2d\u4e8c",
        "nine_hit_three": "\u4e5d\u4e2d\u4e09",
    }

    def add_gap(category, evidence, impact, fix, action):
        missing.append({
            "category": category,
            "evidence": evidence,
            "impact": impact,
            "fix": fix,
        })
        actions.append(action)

    random_top10 = backtest_result.get("random_top10_expectation", DRAW_SIZE * 10 / NUMBER_MAX)
    top10_avg = backtest_result.get("top10_avg_hits", 0)
    top10_edge = top10_avg - random_top10
    if top10_edge < 0.08:
        add_gap(
            "\u524d\u5341\u540d\u908a\u969b\u4e0d\u8db3",
            f"Top10 {round(top10_avg, 3)} / \u96a8\u6a5f {round(random_top10, 3)} / edge {round(top10_edge, 4)}",
            "\u9ad8\u6a5f\u7387\u865f\u5bb9\u6613\u843d\u5728Top10\u4ee5\u5f8c",
            "\u555f\u7528\u578b\u614b\u7f3a\u53e3\u6a4b\u63a5\u3001\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130\u3001\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48\uff0c\u5c07\u4e0a\u671f\u724c\u578b\u8207\u6b77\u53f2\u540c\u76f8\u4f4d\u4e0b\u671f\u547d\u4e2d\u7d71\u8a08\u5408\u4f75\u52a0\u6b0a",
            "boost_regime_gap_bridge",
        )
        actions.extend(["boost_similarity_knn", "boost_omission_phase"])

    pack_stats = (pack_governance or {}).get("pack_stats", {})
    for key, item in pack_stats.items():
        size = int(item.get("size", 0) or 0)
        if size not in {1, 2, 3, 5, 9}:
            continue
        edge_avg = float(item.get("avg_hits_edge_vs_random", 0) or 0)
        edge_pass = float(item.get("pass_rate_edge_vs_random", 0) or 0)
        if not item.get("research_passed") or edge_avg < 0.05 or edge_pass < -0.02:
            pack_name = pack_labels.get(key, key)
            add_gap(
                "\u5f37\u724c\u5be6\u6230\u9580\u6abb\u672a\u7a69",
                f"{pack_name}: \u901a\u904e\u512a\u52e2 {round(edge_pass, 3)} / \u5e73\u5747\u547d\u4e2d\u512a\u52e2 {round(edge_avg, 3)} / \u96f6\u547d\u4e2d {item.get('zero_hit_rate', '-')}",
                "\u5f37\u724c\u6703\u56e0\u8fd1\u671f\u843d\u7a7a\u800c\u88ab\u964d\u7d1a\u6216\u9700\u8981\u8f49\u63db\u7b56\u7565",
                "\u4fdd\u7559\u5c0f\u7d44\u7af6\u8cfd\uff0c\u5c0d\u5f31\u52e2\u7d44\u555f\u7528\u9580\u6abb\u964d\u7d1a\u8207\u578b\u614b\u6a4b\u63a5\u5019\u9078",
                "tighten_pack_tournament",
            )

    selected = (precision_tournament or {}).get("selected_models", {})
    for target, item in selected.items():
        recent60 = item.get("recent_60") or {}
        pass_rate = float(recent60.get("pass_rate", 0) or 0)
        random_success = float(item.get("random_success_probability", 0) or 0)
        zero_rate = float(recent60.get("zero_hit_rate", 0) or 0)
        if pass_rate < random_success + 0.035 or zero_rate > 0.72:
            add_gap(
                "\u5c0f\u7d44\u7cbe\u7b97\u8fd1\u671f\u7a69\u5b9a\u5ea6\u4e0d\u8db3",
                f"{target}: 60\u671f\u901a\u904e {round(pass_rate, 3)} / \u96a8\u6a5f {round(random_success, 3)} / \u96f6\u547d\u4e2d {round(zero_rate, 3)}",
                "\u7368\u96bb\u30012\u78bc\u30013\u78bc\u6703\u51fa\u73fe\u9ad8\u5206\u4f46\u672a\u7a69\u5b9a\u7684\u60c5\u6cc1",
                "\u628a\u672a\u904e\u7684\u5c0f\u7d44\u7dad\u6301watch_only\uff0c\u4e26\u8b93\u578b\u614b\u7f3a\u53e3\u6a21\u578b\u53c3\u8207\u4e0b\u671f\u7af6\u8cfd",
                "precision_watch_gate",
            )

    if len(validated_links or []) < 3:
        add_gap(
            "\u6a23\u672c\u5916\u9023\u52d5\u4e0d\u8db3",
            f"\u901a\u904eFDR\u9023\u52d5 {len(validated_links or [])}",
            "\u4e0a\u671f\u865f\u78bc\u5c0d\u4e0b\u671f\u7684\u62d6\u724c\u652f\u6490\u504f\u5f31",
            "\u5c07\u9023\u52d5\u6a21\u578b\u4fdd\u5b88\u964d\u6b0a\uff0c\u6539\u7528\u5340\u9593\u7f3a\u53e3\u3001\u578b\u614b\u76f8\u4f3c\u8207\u907a\u6f0f\u56de\u6536\u88dc\u4f4d",
            "reduce_dependency_overtrust",
        )

    model_source_counts = Counter()
    for item in (candidates or [])[:9]:
        for source in item.get("model_sources") or []:
            model_source_counts[source.get("model")] += 1
    if model_source_counts.get("similar_draw_knn", 0) < 2:
        add_gap(
            "\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130\u8a0a\u865f\u4e0d\u8db3",
            f"Top9\u4e2d\u8fd1\u9130\u8a0a\u865f {model_source_counts.get('similar_draw_knn', 0)}",
            "\u6700\u50cf\u7684\u6b77\u53f2\u724c\u672a\u80fd\u652f\u6490\u8db3\u5920\u591a\u524d\u4e5d\u540d",
            "\u5df2\u8b93\u8fd1\u9130\u6a21\u578b\u9032\u5165\u7af6\u8cfd\uff0c\u82e5\u56de\u6e2c\u512a\u65bc\u96a8\u6a5f\u6703\u81ea\u52d5\u589e\u6b0a",
            "boost_similarity_knn",
        )
    if model_source_counts.get("omission_phase_rebound", 0) < 2:
        add_gap(
            "\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48\u8a0a\u865f\u4e0d\u8db3",
            f"Top9\u4e2d\u76f8\u4f4d\u8a0a\u865f {model_source_counts.get('omission_phase_rebound', 0)}",
            "\u907a\u6f0f\u9031\u671f\u6a21\u578b\u672a\u80fd\u5c07\u6709\u6548\u865f\u78bc\u63a8\u5165\u524d\u4e5d\u540d",
            "\u5df2\u5c07\u6bcf\u9846\u865f\u78bc\u7576\u524d\u907a\u6f0f\u6876\u8207\u6b77\u53f2\u540c\u6876\u4e0b\u671f\u547d\u4e2d\u7387\u5408\u4f75\u904b\u7b97",
            "boost_omission_phase",
        )

    top9 = [int(item.get("number")) for item in (candidates or [])[:9] if item.get("number") is not None]
    zone_counts = Counter(zone_label(number) for number in top9)
    tail_counts = Counter(number % 10 for number in top9)
    if zone_counts and (max(zone_counts.values()) >= 4 or max(tail_counts.values()) >= 3):
        add_gap(
            "\u5019\u9078\u6c60\u96c6\u4e2d\u5ea6\u904e\u9ad8",
            f"Top9\u5340\u9593 {dict(zone_counts)} / \u5c3e\u6578 {dict(tail_counts)}",
            "\u9ad8\u5206\u865f\u904e\u5ea6\u64e0\u5728\u540c\u5340\u6216\u540c\u5c3e\uff0c\u5bb9\u6613\u8b93\u547d\u4e2d\u5206\u6563\u5230Top10-15",
            "\u57289\u78bc\u5167\u52a0\u5165\u5340\u9593\u8207\u5c3e\u6578\u5206\u6563\u60e9\u7f70\uff0c\u4e26\u628a\u5f8c\u6bb5\u9ad8\u8a0a\u865f\u62c9\u56deTop9\u7af6\u722d",
            "rebalance_top9_pool",
        )

    if review and review.get("severity") in {"warning", "critical"}:
        add_gap(
            "\u8fd1\u671f\u5be6\u6230\u5931\u8aa4\u9700\u5f37\u5236\u56de\u994b",
            f"severity {review.get('severity')} / actions {len(review.get('actions') or [])}",
            "\u5982\u679c\u4e0a\u671f\u5931\u8aa4\u672a\u88ab\u5438\u6536\uff0c\u4e0b\u671f\u5bb9\u6613\u91cd\u8907\u540c\u6a23\u7d50\u69cb",
            "\u5df2\u5c07\u672a\u547d\u4e2d\u7406\u7531\u3001\u5f8c\u6bb5\u547d\u4e2d\u865f\u3001\u91cd\u8907\u843d\u7a7a\u865f\u7d0d\u5165\u6efe\u52d5\u8abf\u6574",
            "force_failure_feedback",
        )

    status = "ok" if not missing else "needs_strengthening"
    if not actions:
        actions.append("keep_current_tournament")
    return {
        "status": status,
        "status_label": "\u9700\u7e7c\u7e8c\u88dc\u5f37" if status != "ok" else "\u7d50\u69cb\u6b63\u5e38",
        "new_model_key": "regime_gap_bridge",
        "new_model_keys": ["regime_gap_bridge", "similar_draw_knn", "omission_phase_rebound"],
        "new_model_added": "\u578b\u614b\u7f3a\u53e3\u6a4b\u63a5\u3001\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130\u3001\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48",
        "missing_elements": missing,
        "active_actions": sorted(set(actions)),
        "active_action_labels": [action_labels.get(action, action) for action in sorted(set(actions))],
        "top_boosted_features": (weight_calibration or {}).get("top_boosted_features", [])[:6],
        "top_penalized_features": (weight_calibration or {}).get("top_penalized_features", [])[:6],
        "top9_numbers": top9,
        "message": "\u7cfb\u7d71\u5df2\u628a\u547d\u4e2d\u4e0d\u8db3\u554f\u984c\u62c6\u6210\u53ef\u56de\u6e2c\u3001\u53ef\u964d\u6b0a\u3001\u53ef\u7af6\u8cfd\u7684\u9805\u76ee",
    }


def build_covering_wheel(numbers, ticket_size=5, cover_size=3, max_tickets=12):
    numbers = sorted(numbers)
    target_subsets = {tuple(combo) for combo in combinations(numbers, cover_size)}
    ticket_pool = []
    for ticket in combinations(numbers, ticket_size):
        covered = {tuple(combo) for combo in combinations(ticket, cover_size)}
        ticket_pool.append({"ticket": ticket, "covered": covered})

    selected = []
    covered_total = set()
    while ticket_pool and len(selected) < max_tickets and covered_total != target_subsets:
        best = max(
            ticket_pool,
            key=lambda item: (len(item["covered"] - covered_total), balanced_ticket_score(item["ticket"])),
        )
        if not (best["covered"] - covered_total):
            break
        selected.append(list(best["ticket"]))
        covered_total.update(best["covered"])
        ticket_pool.remove(best)

    return {
        "tickets": selected,
        "coverage": {
            "covered": len(covered_total),
            "total": len(target_subsets),
            "rate": round(len(covered_total) / len(target_subsets), 4) if target_subsets else 0,
        },
    }


def balanced_ticket_score(ticket):
    zones = Counter(zone_label(number) for number in ticket)
    tails = Counter(number % 10 for number in ticket)
    zone_penalty = sum(max(0, count - 2) for count in zones.values())
    tail_penalty = sum(max(0, count - 1) for count in tails.values())
    span = max(ticket) - min(ticket)
    return span / NUMBER_MAX - zone_penalty * 0.2 - tail_penalty * 0.1


def runtime_rounds(name, default, minimum=30, maximum=720):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def industrial_backtest(draws, rounds=None, weights_override=None):
    rounds = runtime_rounds("TIANTIANLE_INDUSTRIAL_BACKTEST_ROUNDS", 120) if rounds is None else rounds
    if len(draws) < 140:
        return {"rounds": 0, "top10_avg_hits": 0, "top15_avg_hits": 0}
    start = max(120, len(draws) - rounds - 1)
    top10_hits = 0
    top15_hits = 0
    total = 0
    hit_history = []
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        candidates, _ = score_numbers(train, None, include_dependency=False, weights_override=weights_override)
        ranked = [item["number"] for item in candidates]
        round_top10 = len(set(ranked[:10]) & actual)
        round_top15 = len(set(ranked[:15]) & actual)
        top10_hits += round_top10
        top15_hits += round_top15
        hit_history.append({"top10": round_top10, "top15": round_top15})
        total += 1
    random_top10 = DRAW_SIZE * 10 / NUMBER_MAX
    rolling = {}
    for window in [60, 120, 360]:
        sample = hit_history[-window:]
        rolling[str(window)] = {
            "rounds": len(sample),
            "top10_avg_hits": round(sum(item["top10"] for item in sample) / len(sample), 3) if sample else 0,
            "top15_avg_hits": round(sum(item["top15"] for item in sample) / len(sample), 3) if sample else 0,
            "top10_edge_vs_random": round(
                sum(item["top10"] for item in sample) / len(sample) - random_top10, 4
            ) if sample else 0,
        }
    return {
        "rounds": total,
        "top10_avg_hits": round(top10_hits / total, 3) if total else 0,
        "top15_avg_hits": round(top15_hits / total, 3) if total else 0,
        "random_top10_expectation": round(random_top10, 3),
        "rolling_windows": rolling,
    }


def advanced_model_summary(draws):
    models = {
        "markov_chain": markov_chain_scores(draws),
        "time_series": time_series_scores(draws),
        "neural_network": neural_network_scores(draws),
        "similar_draw_knn": similar_draw_knn_scores(draws),
        "omission_phase_rebound": omission_phase_rebound_scores(draws),
    }
    labels = {
        "markov_chain": "\u99ac\u53ef\u592b\u93c8",
        "time_series": "\u6642\u9593\u5e8f\u5217",
        "neural_network": "\u795e\u7d93\u7db2\u8def",
        "similar_draw_knn": "\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130",
        "omission_phase_rebound": "\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48",
    }
    rows = []
    vote = Counter()
    for key, scores in models.items():
        ranked = rank_values(scores)[:10]
        vote.update(ranked[:8])
        rows.append({
            "model": key,
            "name": labels[key],
            "top10": ranked,
            "method": {
                "markov_chain": "\u4f9d\u4e0a\u671f\u865f\u78bc\u5efa\u7acb\u72c0\u614b\u8f49\u79fb\u77e9\u9663",
                "time_series": "\u4ee5\u5feb\u6162 EWMA \u8ffd\u8e64\u865f\u78bc\u52d5\u80fd",
                "neural_network": "\u4ee5\u983b\u7387\u3001\u907a\u6f0f\u3001\u8f49\u79fb\u8207\u52d5\u80fd\u505a\u975e\u7dda\u6027\u7d9c\u5408",
                "similar_draw_knn": "\u627e\u51fa\u8207\u6700\u65b0\u724c\u578b\u3001\u865f\u7d44\u3001\u9130\u865f\u6700\u76f8\u4f3c\u7684\u6b77\u53f2\u724c\uff0c\u7d71\u8a08\u5176\u4e0b\u4e00\u671f",
                "omission_phase_rebound": "\u4ee5\u6bcf\u9846\u865f\u78bc\u7576\u524d\u907a\u6f0f\u76f8\u4f4d\u5c0d\u7167\u6b77\u53f2\u540c\u76f8\u4f4d\u4e0b\u4e00\u671f\u547d\u4e2d\u7387",
            }[key],
        })
    consensus = [number for number, _ in vote.most_common(12)]
    return {
        "models": rows,
        "consensus_top12": consensus,
        "warning": "\u9032\u968e\u6a21\u578b\u53ea\u80fd\u63d0\u4f9b\u8f14\u52a9\u8a55\u5206\uff0c\u5fc5\u9808\u901a\u904e\u56de\u6e2c\u8207\u767c\u5e03\u9580\u6abb\u624d\u80fd\u9032\u5165\u4e3b\u63a8",
    }


def advanced_model_backtest(draws, rounds=None):
    rounds = runtime_rounds("TIANTIANLE_ADVANCED_BACKTEST_ROUNDS", 80) if rounds is None else rounds
    if len(draws) < 140:
        return {"rounds": 0}
    model_names = ["markov_chain", "time_series", "neural_network", "similar_draw_knn", "omission_phase_rebound"]
    totals = {name: {"top10_hits": 0, "rounds": 0} for name in model_names}
    start = max(120, len(draws) - rounds - 1)
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        actual = set(draws[idx + 1]["numbers"])
        scores_by_model = {
            "markov_chain": markov_chain_scores(train),
            "time_series": time_series_scores(train),
            "neural_network": neural_network_scores(train),
            "similar_draw_knn": similar_draw_knn_scores(train),
            "omission_phase_rebound": omission_phase_rebound_scores(train),
        }
        for name, scores in scores_by_model.items():
            top10 = set(rank_values(scores)[:10])
            totals[name]["top10_hits"] += len(top10 & actual)
            totals[name]["rounds"] += 1
    random_top10 = DRAW_SIZE * 10 / NUMBER_MAX
    result = {}
    for name, data in totals.items():
        rounds_done = data["rounds"]
        avg_hits = data["top10_hits"] / rounds_done if rounds_done else 0
        result[name] = {
            "rounds": rounds_done,
            "top10_avg_hits": round(avg_hits, 3),
            "top10_edge_vs_random": round(avg_hits - random_top10, 4),
        }
    return {
        "rounds": max(item["rounds"] for item in result.values()) if result else 0,
        "random_top10_expectation": round(random_top10, 3),
        "models": result,
    }


def stability_consensus(draws, base_candidates, review=None):
    snapshots = []
    for cut in [0, 1, 2, 3, 5]:
        if len(draws) - cut < 140:
            continue
        if cut == 0:
            ranked = [item["number"] for item in base_candidates]
        else:
            ranked = [item["number"] for item in score_numbers(draws[:-cut], review)[0]]
        snapshots.append(ranked[:15])
    counts = Counter(number for ranking in snapshots for number in ranking)
    base_score = {item["number"]: item["score"] for item in base_candidates}
    latest_set = set(draws[-1]["numbers"])
    denominator = max(len(snapshots), 1)
    combined = {
        number: base_score[number] * 0.62 + (counts.get(number, 0) / denominator) * 0.38
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }
    previous_blocked = {
        item["number"] for item in base_candidates
        if item.get("previous_prediction_guard") and not item["previous_prediction_guard"].get("passed")
    }
    ranked = sorted(
        range(NUMBER_MIN, NUMBER_MAX + 1),
        key=lambda number: (
            number not in previous_blocked,
            number not in latest_set,
            combined[number],
            -number,
        ),
        reverse=True,
    )
    original = {item["number"]: item for item in base_candidates}
    stable_candidates = []
    for number in ranked:
        item = dict(original[number])
        item["stability_count"] = counts.get(number, 0)
        item["stability_rate"] = round(counts.get(number, 0) / denominator, 3)
        item["score"] = round(combined[number], 4)
        item["confidence_index"] = round(50 + min(combined[number], 1) * 49, 1)
        if item["stability_rate"] >= 0.8:
            item["reasons"] = (item.get("reasons", []) + ["\u7a69\u5b9a\u5171\u8b58"])[:4]
        stable_candidates.append(item)
    top10_retention = sum(1 for number in ranked[:10] if counts.get(number, 0) >= max(1, math.ceil(denominator * 0.6))) / 10
    return stable_candidates, {
        "snapshots": len(snapshots),
        "top10_retention": round(top10_retention, 3),
        "consensus_counts": {str(number): counts.get(number, 0) for number in ranked[:15]},
    }


def unlikely_number_analysis(draws, candidates, stability, review=None, limit=12):
    features = build_feature_matrix(draws, review, include_dependency=False)
    score_map = {item["number"]: item["score"] for item in candidates}
    rank_map = {item["number"]: index + 1 for index, item in enumerate(candidates)}
    stability_counts = {int(number): count for number, count in stability.get("consensus_counts", {}).items()}
    latest_set = set(draws[-1]["numbers"])
    previous_blocked = {
        item["number"] for item in candidates
        if item.get("previous_prediction_guard") and not item["previous_prediction_guard"].get("passed")
    }
    failed = failed_number_set(review)
    repeat_policy = repeat_guard(draws)
    rows = []
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        values = features[number]
        weak_signal_count = sum(
            1 for key in ["freq_20", "freq_50", "freq_100", "ewma_slow", "pair", "tail_zone", "validated_dependency"]
            if values.get(key, 0) < 0.35
        )
        penalty = 0.0
        reasons = []
        if number in previous_blocked:
            penalty += 0.32
            reasons.append("\u6628\u65e5\u9810\u6e2c\u865f\u672a\u9054\u6975\u5f37\u91cd\u5165\u9580\u6abb")
        if number in failed:
            penalty += 0.25
            reasons.append("\u4e0a\u671f\u5931\u6557\u865f\u78bc\u9694\u96e2")
        if number in latest_set:
            if repeat_policy.get(number, {}).get("historical_support"):
                penalty += 0.08
                reasons.append("\u9023\u838a\u5408\u683c\u4f46\u4fdd\u5b88\u98a8\u63a7")
            else:
                penalty += 0.28
                reasons.append("\u9023\u838a\u5b88\u9580\u672a\u901a\u904e")
        if stability_counts.get(number, 0) == 0:
            penalty += 0.16
            reasons.append("\u64fe\u52d5\u6a21\u578b\u7121\u7a69\u5b9a\u5171\u8b58")
        if weak_signal_count >= 5:
            penalty += 0.20
            reasons.append("\u77ed\u4e2d\u9577\u671f\u8207\u95dc\u806f\u6307\u6a19\u504f\u5f31")
        if rank_map.get(number, 99) > 24:
            penalty += 0.15
            reasons.append("Top24\u5916")
        appearance_risk = max(0.0, min(1.0, score_map.get(number, 0.0)))
        avoid_score = max(0.0, min(1.0, (1 - appearance_risk) * 0.48 + penalty))
        if not reasons:
            reasons.append("\u7d9c\u5408\u8a55\u5206\u504f\u5f31")
        rows.append(
            {
                "number": number,
                "avoid_score": round(avoid_score, 4),
                "appearance_score": round(appearance_risk, 4),
                "candidate_rank": rank_map.get(number),
                "stability_count": stability_counts.get(number, 0),
                "weak_signal_count": weak_signal_count,
                "reasons": reasons[:4],
                "warning": "\u4f4e\u6a5f\u7387\u4e0d\u4ee3\u8868\u4e0d\u6703\u958b\u51fa",
            }
        )
    rows.sort(key=lambda item: (item["avoid_score"], item["number"]), reverse=True)
    return {
        "method": "inverse_signal_risk_filter",
        "warning": "\u6b64\u5340\u70ba\u98a8\u63a7\u907f\u958b\u89c0\u5bdf\uff0c\u4e0d\u662f\u7d55\u5c0d\u4e0d\u958b\u4fdd\u8b49",
        "numbers": rows[:limit],
    }


def unlikely_backtest(draws, rounds=None, avoid_size=10):
    rounds = runtime_rounds("TIANTIANLE_UNLIKELY_BACKTEST_ROUNDS", 80) if rounds is None else rounds
    if len(draws) < 140:
        return {"rounds": 0}
    start = max(120, len(draws) - rounds - 1)
    total = 0
    accidental_hits = 0
    zero_hit_rounds = 0
    for idx in range(start, len(draws) - 1):
        train = draws[: idx + 1]
        base_candidates, _ = score_numbers(train, None, include_dependency=False)
        stable = {"consensus_counts": {}}
        avoid = unlikely_number_analysis(train, base_candidates, stable, None, limit=avoid_size)["numbers"]
        avoid_numbers = {item["number"] for item in avoid}
        actual = set(draws[idx + 1]["numbers"])
        hits = len(avoid_numbers & actual)
        accidental_hits += hits
        zero_hit_rounds += 1 if hits == 0 else 0
        total += 1
    random_expectation = DRAW_SIZE * avoid_size / NUMBER_MAX
    return {
        "rounds": total,
        "avoid_size": avoid_size,
        "avg_accidental_hits": round(accidental_hits / total, 3) if total else 0,
        "random_expectation": round(random_expectation, 3),
        "edge_vs_random": round(accidental_hits / total - random_expectation, 4) if total else 0,
        "zero_hit_rate": round(zero_hit_rounds / total, 3) if total else 0,
    }


def compute_industrial_analysis(draws, review=None):
    weights, weight_calibration = adaptive_feature_weights(draws, review)
    base_candidates, weights = score_numbers(draws, review, weights_override=weights)
    candidates, stability = stability_consensus(draws, base_candidates, review)
    candidates, top9_frontload_audit = top9_frontload_candidates(candidates, review)
    pack_governance = pack_recent_governance(draws, weights_override=weights)
    precision_tournament = precision_model_tournament(draws, review, weights_override=weights)
    precision_micro = precision_micro_models(candidates, review, pack_governance, precision_tournament)
    packs = strong_packs(candidates, review, pack_governance)
    packs = attach_precision_micro_packs(packs, precision_micro, candidates)
    maturity = practical_maturity_summary(candidates)
    audit = industrial_backtest(draws, weights_override=weights)
    advanced_models = advanced_model_summary(draws)
    advanced_backtest = advanced_model_backtest(draws)
    _, validated_links = validated_dependency_scores(draws)
    lag_profile = lag_dependency_profile(draws)
    edge = audit.get("top10_avg_hits", 0) - audit.get("random_top10_expectation", DRAW_SIZE * 10 / NUMBER_MAX)
    rolling = audit.get("rolling_windows", {})
    recent_edges = [rolling.get(str(window), {}).get("top10_edge_vs_random", -1) for window in [60, 120]]
    recent_passed = all(value >= 0 for value in recent_edges)
    pack_stats = pack_governance.get("pack_stats", {})
    main_target_passed = (
        pack_stats.get("five_hit_two", {}).get("passed", False)
        and pack_stats.get("nine_hit_three", {}).get("passed", False)
    )
    research_main_targets_passed = (
        pack_stats.get("five_hit_two", {}).get("research_passed", False)
        and pack_stats.get("nine_hit_three", {}).get("research_passed", False)
    )
    pack_release_passed = pack_governance.get("release_light") in {"green", "yellow"} and main_target_passed
    research_release_passed = pack_governance.get("research_release_light") in {"green", "yellow"} and research_main_targets_passed
    maturity_passed = maturity.get("status") == "passed"
    if stability["top10_retention"] >= 0.6 and edge >= 0 and recent_passed and pack_release_passed and maturity_passed:
        release_status = "official"
    elif stability["top10_retention"] >= 0.6 and edge >= 0 and recent_passed and research_release_passed and maturity_passed:
        release_status = "verified_research_complete"
    else:
        release_status = "watch_only"
    previous = previous_prediction_set(review)
    top9_overlap = sorted(previous & {item["number"] for item in candidates[:9]})
    top10_overlap = sorted(previous & {item["number"] for item in candidates[:10]})
    top15_overlap = sorted(previous & {item["number"] for item in candidates[:15]})
    reentry_passed = sorted(
        item["number"] for item in candidates
        if item.get("previous_prediction_guard") and item["previous_prediction_guard"].get("passed")
    )
    unlikely = unlikely_number_analysis(draws, candidates, stability, review)
    promotion_audit = top10_promotion_audit(candidates, review)
    audit_summary = model_audit(audit, review)
    gap_diagnosis = prediction_gap_diagnosis(
        draws,
        candidates,
        precision_tournament,
        pack_governance,
        weight_calibration,
        audit,
        validated_links,
        review,
    )
    return {
        "engine_version": "industrial_v9_knn_phase_rebound_diagnosis",
        "leakage_guard": True,
        "repeat_guard": repeat_guard(draws),
        "previous_prediction_guard": {
            "policy": "soft_penalty_previous_top15_with_recovery_revalidation",
            "previous_top15": sorted(previous),
            "reentry_passed": reentry_passed,
            "current_top9_overlap": top9_overlap,
            "current_top10_overlap": top10_overlap,
            "current_top15_overlap": top15_overlap,
            "top9_overlap_rate": round(len(top9_overlap) / 9, 3),
            "top10_overlap_rate": round(len(top10_overlap) / 10, 3),
            "top15_overlap_rate": round(len(top15_overlap) / 15, 3),
        },
        "stability_consensus": stability,
        "adaptive_weight_calibration": weight_calibration,
        "top9_frontload_audit": top9_frontload_audit,
        "top10_promotion_audit": promotion_audit,
        "dependency_analysis": {
            "method": "three_fold_conditional_lift_with_fdr",
            "validated_links": validated_links[:30],
            "validated_link_count": len(validated_links),
            "lag_profile": lag_profile,
            "warning": "\u95dc\u806f\u4e0d\u7b49\u65bc\u56e0\u679c\uff0c\u53ea\u5141\u8a31\u901a\u904e\u5206\u6bb5\u9a57\u8b49\u7684\u9023\u52d5\u9032\u5165\u6a21\u578b",
        },
        "release_gate": {
            "status": release_status,
            "precision_governor_release_light": pack_governance.get("release_light"),
            "precision_governor_allowed_pack_count": pack_governance.get("allowed_pack_count"),
            "research_release_light": pack_governance.get("research_release_light"),
            "research_allowed_pack_count": pack_governance.get("research_allowed_pack_count"),
            "practical_maturity_required": maturity.get("required"),
            "practical_maturity_status": maturity.get("status"),
            "practical_maturity_passed": maturity_passed,
            "top10_avg_maturity": maturity.get("top10_avg_maturity"),
            "main_targets_required": ["five_hit_two", "nine_hit_three"],
            "main_targets_passed": main_target_passed,
            "research_main_targets_passed": research_main_targets_passed,
            "top10_retention_required": 0.6,
            "backtest_edge_required": 0,
            "actual_backtest_edge": round(edge, 4),
            "recent_windows_required": [60, 120],
            "recent_edges": recent_edges,
            "recent_performance_passed": recent_passed,
        },
        "weights": {key: round(value, 4) for key, value in weights.items()},
        "backtest": audit,
        "advanced_models": advanced_models,
        "advanced_model_backtest": advanced_backtest,
        "unlikely_number_analysis": unlikely,
        "unlikely_backtest": unlikely_backtest(draws),
        "precision_governor": pack_governance,
        "precision_model_tournament": precision_tournament,
        "prediction_gap_diagnosis": gap_diagnosis,
        "precision_micro_models": precision_micro,
        "practical_maturity": maturity,
        "model_audit": audit_summary,
        "regime_analysis": regime_analysis(draws),
        "candidates": candidates,
        "strong_prediction_packs": packs,
    }
