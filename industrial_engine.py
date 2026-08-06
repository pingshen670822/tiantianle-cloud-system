import math
from collections import Counter, defaultdict
import os
from datetime import datetime, timedelta
from itertools import combinations
from tiantianle_formula_engine import compute_formula_engine_analysis, blend_formula_into_candidates


NUMBER_MIN = 1
NUMBER_MAX = 39
DRAW_SIZE = 5
BASE_PROBABILITY = DRAW_SIZE / NUMBER_MAX
EXPECTED_GAP = NUMBER_MAX / DRAW_SIZE
WALK_FORWARD_SIGNATURE_CACHE = {}
POSITIVE_EDGE_CORE_FEATURES = (
    "full_history_anchor",
    "bayesian_posterior",
    "distribution_balance",
    "freq_all",
    "freq_720",
    "freq_300",
    "omission",
    "regime_gap_bridge",
    "similar_draw_knn",
    "omission_phase_rebound",
    "rank_window_drift_correction",
    "effective_hit_front_shift",
    "low_probability_error_recovery",
    "walk_forward_hit_signature",
    "external_method_consensus",
)


def realtime_timing_enabled():
    return os.environ.get("TIANTIANLE_RUN_MODE") == "realtime"


def timing_log(message):
    if not realtime_timing_enabled():
        return
    try:
        path = os.path.join(os.path.dirname(__file__), "reports", "model_timing.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{stamp} 工業引擎 {message}\n")
    except OSError:
        pass


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


def full_history_anchor_scores(draws):
    """Full-history anchor: keeps ranking grounded in the entire database."""
    if not draws:
        return {number: 0.0 for number in range(NUMBER_MIN, NUMBER_MAX + 1)}
    full_freq = frequency(draws)
    full_z = normalize({
        number: binomial_zscore(full_freq.get(number, 0), len(draws))
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    })
    midpoint = max(1, len(draws) // 2)
    first = draws[:midpoint]
    second = draws[midpoint:] or draws
    first_freq = frequency(first)
    second_freq = frequency(second)
    first_rate = {
        number: first_freq.get(number, 0) / max(1, len(first))
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }
    second_rate = {
        number: second_freq.get(number, 0) / max(1, len(second))
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    }
    stability = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        gap = abs(first_rate[number] - second_rate[number])
        baseline = max(BASE_PROBABILITY, (first_rate[number] + second_rate[number]) / 2)
        stability[number] = max(0.0, 1.0 - gap / max(baseline, 1e-9))
    stability_norm = normalize(stability)
    return normalize({
        number: full_z[number] * 0.62 + stability_norm[number] * 0.38
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    })


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

    def valid_number(value):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if NUMBER_MIN <= number <= NUMBER_MAX else None

    settled = review.get("last_settled", {})
    failed = {
        number
        for number in (valid_number(value) for value in (settled.get("candidate_numbers") or [])[:15])
        if number is not None
    }
    for pack in (settled.get("strong_pack_hits") or {}).values():
        if not pack.get("passed"):
            failed.update(
                number
                for number in (valid_number(value) for value in pack.get("numbers", []))
                if number is not None
            )

    failed.update(
        number
        for number in (valid_number(value) for value in review.get("rolling_failed_numbers", []))
        if number is not None
    )
    rolling = rolling_adjustment_data(review)
    for key in ("repeated_failed_numbers", "last2_failed_top10_numbers"):
        failed.update(
            number
            for number in (valid_number(item.get("number")) for item in rolling.get(key, []))
            if number is not None
        )

    actual_numbers = {
        number
        for number in (valid_number(value) for value in (settled.get("actual_numbers") or []))
        if number is not None
    }
    failed -= actual_numbers
    return failed


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


def low_probability_error_recovery_payload(review):
    if not review or not review.get("has_review"):
        return {}
    payload = review.get("low_probability_error_recovery") or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def low_probability_error_number_map(review):
    payload = low_probability_error_recovery_payload(review)
    rows = payload.get("frequent_numbers") or []
    mapped = {}
    for item in rows:
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if NUMBER_MIN <= number <= NUMBER_MAX:
            mapped[number] = item
    return mapped


def low_probability_error_recovery_scores(review):
    payload = low_probability_error_recovery_payload(review)
    if not payload or not payload.get("active"):
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}

    values = {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    tail_pressure = Counter()
    zone_pressure = Counter()
    for item in payload.get("frequent_numbers") or []:
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if not NUMBER_MIN <= number <= NUMBER_MAX:
            continue
        count = int(item.get("count", 0) or 0)
        recent_count = int(item.get("recent_count", 0) or 0)
        weighted = float(item.get("weighted_score", 0.0) or 0.0)
        five_hits = int(item.get("five_miss_hits", 0) or 0)
        ten_hits = int(item.get("ten_miss_hits", 0) or 0)
        fifteen_hits = int(item.get("fifteen_miss_hits", 0) or 0)
        score = (
            min(1.0, weighted / 3.2) * 0.46
            + min(1.0, count / 4.0) * 0.22
            + min(1.0, recent_count / 2.0) * 0.18
            + min(1.0, (five_hits * 1.6 + ten_hits * 1.15 + fifteen_hits) / 5.0) * 0.22
        )
        values[number] += score
        tail_pressure[number % 10] += max(1, recent_count) + five_hits
        zone_pressure[zone_label(number)] += max(1, recent_count) + ten_hits

    hard_blocked = payload.get("hard_block_low_probability_numbers") or []
    for number in hard_blocked:
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        if NUMBER_MIN <= number <= NUMBER_MAX:
            values[number] += 0.36

    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        if tail_pressure.get(number % 10):
            values[number] += min(0.18, tail_pressure[number % 10] * 0.025)
        if zone_pressure.get(zone_label(number)):
            values[number] += min(0.14, zone_pressure[zone_label(number)] * 0.018)
    return normalize(values)


def multi_horizon_ema_scores(draws):
    short = normalize(ewma_frequency(draws[-300:] if len(draws) >= 300 else draws, 8))
    medium = normalize(ewma_frequency(draws[-900:] if len(draws) >= 900 else draws, 26))
    long = normalize(ewma_frequency(draws[-1800:] if len(draws) >= 1800 else draws, 78))
    return normalize({
        number: short[number] * 0.34 + medium[number] * 0.36 + long[number] * 0.30
        for number in range(NUMBER_MIN, NUMBER_MAX + 1)
    })


def gap_timing_grid_scores(draws, window=1800):
    subset = draws[-window:] if len(draws) > window else draws
    if len(subset) < 60:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    gaps = {n: int(round(EXPECTED_GAP)) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    seen = defaultdict(int)
    hits = defaultdict(int)
    global_seen = Counter()
    global_hits = Counter()
    for draw in subset:
        drawn = {int(n) for n in draw["numbers"]}
        for number in range(NUMBER_MIN, NUMBER_MAX + 1):
            bucket = min(40, int(gaps[number]))
            seen[(number, bucket)] += 1
            global_seen[bucket] += 1
            if number in drawn:
                hits[(number, bucket)] += 1
                global_hits[bucket] += 1
        for number in range(NUMBER_MIN, NUMBER_MAX + 1):
            gaps[number] = 0 if number in drawn else gaps[number] + 1

    current_gaps = omission(draws)
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        bucket = min(40, int(current_gaps[number]))
        specific_seen = 0
        specific_hits = 0
        bucket_seen = 0
        bucket_hits = 0
        for near in range(max(0, bucket - 2), min(40, bucket + 2) + 1):
            specific_seen += seen.get((number, near), 0)
            specific_hits += hits.get((number, near), 0)
            bucket_seen += global_seen.get(near, 0)
            bucket_hits += global_hits.get(near, 0)
        specific_rate = (specific_hits + BASE_PROBABILITY * 4) / max(specific_seen + 4, 1)
        bucket_rate = (bucket_hits + BASE_PROBABILITY * 24) / max(bucket_seen + 24, 1)
        support = min(1.0, specific_seen / 18.0)
        values[number] = max(0.0, specific_rate - BASE_PROBABILITY) * support * 0.72 + max(0.0, bucket_rate - BASE_PROBABILITY) * 0.28
    return normalize(values)


def companion_network_scores(draws, review=None, window=1800):
    subset = draws[-window:] if len(draws) > window else draws
    if len(subset) < 30:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    pair_counter = Counter()
    number_counter = Counter()
    for draw in subset:
        numbers = sorted(int(n) for n in draw["numbers"])
        number_counter.update(numbers)
        for pair in combinations(numbers, 2):
            pair_counter[pair] += 1

    rolling = rolling_adjustment_data(review)
    low_errors = set(low_probability_error_number_map(review))
    anchor_weights = defaultdict(float)
    for number in draws[-1]["numbers"]:
        anchor_weights[int(number)] += 0.72
    for key, weight in [
        ("missed_actual_numbers", 1.18),
        ("late_hit_numbers", 1.08),
        ("last2_missed_actual_numbers", 1.26),
    ]:
        for item in rolling.get(key, []):
            try:
                number = int(item.get("number"))
            except (TypeError, ValueError):
                continue
            if NUMBER_MIN <= number <= NUMBER_MAX:
                anchor_weights[number] += weight
    for number in low_errors:
        anchor_weights[number] += 1.35
    if not anchor_weights:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}

    total_draws = max(len(subset), 1)
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        baseline = number_counter.get(number, 0) / total_draws
        score = 0.0
        for anchor, weight in anchor_weights.items():
            if anchor == number:
                continue
            support = number_counter.get(anchor, 0)
            if support < 12:
                continue
            pair_count = pair_counter.get(tuple(sorted((number, anchor))), 0)
            edge = pair_count / support - baseline
            if edge > 0:
                score += weight * (edge + min(0.18, pair_count / 120.0))
        values[number] = score
    return normalize(values)


def structure_template_scores(draws, window=360):
    recent = draws[-window:] if len(draws) > window else draws
    if not recent:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    odd_counter = Counter()
    big_counter = Counter()
    zone_totals = Counter()
    tail_totals = Counter()
    for draw in recent:
        numbers = [int(n) for n in draw["numbers"]]
        odd_counter[sum(number % 2 for number in numbers)] += 1
        big_counter[sum(1 for number in numbers if number >= 20)] += 1
        zone_totals.update(zone_label(number) for number in numbers)
        tail_totals.update(number % 10 for number in numbers)

    total = max(len(recent), 1)
    odd_weight = {
        1: sum(count for odd, count in odd_counter.items() if odd >= 3) / total,
        0: sum(count for odd, count in odd_counter.items() if odd <= 2) / total,
    }
    big_weight = {
        1: sum(count for big, count in big_counter.items() if big >= 3) / total,
        0: sum(count for big, count in big_counter.items() if big <= 2) / total,
    }
    zone_share = normalize({label: zone_totals.get(label, 0) for label in ["01-10", "11-20", "21-30", "31-39"]})
    tail_pressure = normalize({tail: tail_totals.get(tail, 0) for tail in range(10)})
    latest_zones = Counter(zone_label(number) for number in draws[-1]["numbers"])
    average_zone_need = {label: zone_totals.get(label, 0) / total for label in ["01-10", "11-20", "21-30", "31-39"]}
    zone_gap = normalize({
        label: max(0.0, average_zone_need[label] - latest_zones.get(label, 0))
        for label in ["01-10", "11-20", "21-30", "31-39"]
    })
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        zone = zone_label(number)
        values[number] = (
            odd_weight[number % 2] * 0.24
            + big_weight[1 if number >= 20 else 0] * 0.20
            + (zone_share[zone] * 0.48 + zone_gap[zone] * 0.52) * 0.38
            + (1.0 - tail_pressure[number % 10]) * 0.18
        )
    return normalize(values)


def walk_forward_hit_signature_scores(draws, window=1800):
    if len(draws) < 80:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    run_mode = os.environ.get("TIANTIANLE_RUN_MODE", "standard")
    if run_mode == "deep":
        window = min(int(window), 1200)
    elif run_mode == "realtime":
        window = min(int(window), 360)
    else:
        window = min(int(window), 720)
    latest = draws[-1] if draws else {}
    cache_key = (
        len(draws),
        str(latest.get("draw_date", "")),
        tuple(int(number) for number in latest.get("numbers", []) if NUMBER_MIN <= int(number) <= NUMBER_MAX),
        int(window),
    )
    cached = WALK_FORWARD_SIGNATURE_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    draw_numbers = [
        [int(number) for number in draw.get("numbers", []) if NUMBER_MIN <= int(number) <= NUMBER_MAX]
        for draw in draws
    ]
    start = max(40, len(draw_numbers) - int(window) - 1)
    end = len(draw_numbers) - 2
    if end <= start:
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}

    def count_bucket(count, span):
        expected = max(0.1, span * BASE_PROBABILITY)
        ratio = count / expected
        if ratio >= 1.55:
            return "hot"
        if ratio >= 1.12:
            return "warm"
        if ratio >= 0.72:
            return "normal"
        if ratio >= 0.34:
            return "cold"
        return "silent"

    def gap_bucket(gap):
        if gap <= 1:
            return "repeat"
        if gap <= 3:
            return "near"
        if gap <= 7:
            return "normal"
        if gap <= 14:
            return "due"
        if gap <= 28:
            return "deep"
        return "extreme"

    def tokens_for(number, idx, last_seen, freq30, freq120, latest):
        last = last_seen.get(number)
        gap = idx + 1 if last is None else max(0, idx - last)
        gap_key = gap_bucket(gap)
        zone = zone_label(number)
        tail = number % 10
        near_anchor = any(abs(number - anchor) <= 2 for anchor in latest)
        return [
            f"gap:{gap_key}",
            f"freq30:{count_bucket(freq30.get(number, 0), 30)}",
            f"freq120:{count_bucket(freq120.get(number, 0), 120)}",
            f"zone:{zone}",
            f"tail:{tail}",
            f"parity:{number % 2}",
            f"size:{'big' if number >= 20 else 'small'}",
            f"neighbor2:{1 if near_anchor else 0}",
            f"repeat:{1 if number in latest else 0}",
            f"zone_gap:{zone}:{gap_key}",
            f"tail_gap:{tail}:{gap_key}",
        ]

    last_seen = {n: None for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    for idx in range(0, start + 1):
        for number in draw_numbers[idx]:
            last_seen[number] = idx

    freq30 = Counter()
    queue30 = []
    for idx in range(max(0, start - 29), start + 1):
        queue30.append(draw_numbers[idx])
        freq30.update(draw_numbers[idx])

    freq120 = Counter()
    queue120 = []
    for idx in range(max(0, start - 119), start + 1):
        queue120.append(draw_numbers[idx])
        freq120.update(draw_numbers[idx])

    token_seen = defaultdict(float)
    token_hit = defaultdict(float)
    number_seen = defaultdict(float)
    number_hit = defaultdict(float)
    total_seen = 0.0
    total_hit = 0.0
    span = max(1, end - start + 1)

    for idx in range(start, end + 1):
        latest = set(draw_numbers[idx])
        actual_next = set(draw_numbers[idx + 1])
        recency_weight = 0.45 + 0.55 * ((idx - start + 1) / span)
        for number in range(NUMBER_MIN, NUMBER_MAX + 1):
            hit = number in actual_next
            number_seen[number] += recency_weight
            total_seen += recency_weight
            if hit:
                number_hit[number] += recency_weight
                total_hit += recency_weight
            for token in tokens_for(number, idx, last_seen, freq30, freq120, latest):
                token_seen[token] += recency_weight
                if hit:
                    token_hit[token] += recency_weight

        added = draw_numbers[idx + 1]
        queue30.append(added)
        freq30.update(added)
        if len(queue30) > 30:
            removed = queue30.pop(0)
            for number in removed:
                freq30[number] -= 1
                if freq30[number] <= 0:
                    del freq30[number]
        queue120.append(added)
        freq120.update(added)
        if len(queue120) > 120:
            removed = queue120.pop(0)
            for number in removed:
                freq120[number] -= 1
                if freq120[number] <= 0:
                    del freq120[number]
        for number in added:
            last_seen[number] = idx + 1

    global_rate = (total_hit + BASE_PROBABILITY * 60) / (total_seen + 60)
    current_idx = len(draw_numbers) - 1
    latest = set(draw_numbers[-1])
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        token_values = []
        for token in tokens_for(number, current_idx, last_seen, freq30, freq120, latest):
            seen = token_seen.get(token, 0.0)
            rate = (token_hit.get(token, 0.0) + global_rate * 18) / (seen + 18)
            token_values.append(clamp(rate / max(global_rate, 0.0001), 0.35, 2.45))
        token_lift = sum(token_values) / max(1, len(token_values))
        direct_rate = (number_hit[number] + global_rate * 45) / (number_seen[number] + 45)
        last = last_seen.get(number)
        current_gap = current_idx + 1 if last is None else max(0, current_idx - last)
        due_pressure = clamp(current_gap / (EXPECTED_GAP * 2.4), 0.0, 1.0)
        values[number] = (
            clamp((token_lift - 0.55) / 1.65, 0.0, 1.0) * 0.58
            + clamp(direct_rate / max(global_rate * 1.45, 0.0001), 0.0, 1.0) * 0.26
            + due_pressure * 0.16
        )
    normalized = normalize(values)
    WALK_FORWARD_SIGNATURE_CACHE[cache_key] = dict(normalized)
    if len(WALK_FORWARD_SIGNATURE_CACHE) > 160:
        WALK_FORWARD_SIGNATURE_CACHE.pop(next(iter(WALK_FORWARD_SIGNATURE_CACHE)))
    return normalized


def external_method_consensus_scores(draws, review=None, walk_forward=None):
    bayes = bayesian_posterior_scores(draws, window=1800)
    ema = multi_horizon_ema_scores(draws)
    timing = gap_timing_grid_scores(draws)
    companion = companion_network_scores(draws, review)
    structure = structure_template_scores(draws)
    low_error = low_probability_error_recovery_scores(review)
    walk_forward = walk_forward or walk_forward_hit_signature_scores(draws)
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        values[number] = (
            bayes[number] * 0.16
            + ema[number] * 0.16
            + timing[number] * 0.14
            + companion[number] * 0.15
            + structure[number] * 0.09
            + low_error[number] * 0.15
            + walk_forward[number] * 0.25
        )
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
    last_two = list(recent_settled[:2])
    last2_top10 = [int(item.get("top10_hits", 0) or 0) for item in last_two]
    last2_top15 = [int(item.get("top15_hits", 0) or 0) for item in last_two]
    last2_missed_actual = Counter()
    last2_failed_top10 = Counter()
    for settled in last_two:
        actual = {int(n) for n in settled.get("actual_numbers", []) if NUMBER_MIN <= int(n) <= NUMBER_MAX}
        candidates = [int(n) for n in settled.get("candidate_numbers", []) if NUMBER_MIN <= int(n) <= NUMBER_MAX]
        top10 = set(candidates[:10])
        for number in actual - top10:
            last2_missed_actual[number] += 1
        for number in top10 - actual:
            last2_failed_top10[number] += 1
    two_draw_low_hit = bool(len(last2_top10) >= 2 and all(value <= 1 for value in last2_top10))
    recent_performance = {
        "last5_top5_avg": top5_avg,
        "last5_top10_avg": top10_avg,
        "last5_top15_avg": top15_avg,
        "last2_top10_avg": round(sum(last2_top10) / len(last2_top10), 3) if last2_top10 else 0,
        "last2_top15_avg": round(sum(last2_top15) / len(last2_top15), 3) if last2_top15 else 0,
        "two_draw_low_hit": two_draw_low_hit,
        "recent_slump": bool(top10_avg < 1.8 or top5_avg < 0.8),
        "critical_slump": bool(two_draw_low_hit or top10_avg < 1.4 or top15_avg < 1.8 or summary.get("weak_top10_count", 0) >= 3),
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
        "last2_missed_actual_numbers": [{"number": n, "missed_count": c} for n, c in last2_missed_actual.most_common(15)],
        "last2_failed_top10_numbers": [{"number": n, "miss_count": c} for n, c in last2_failed_top10.most_common(15)],
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


def rank_window_drift_diagnosis(review):
    if not review or not review.get("has_review"):
        return {
            "status": "無資料",
            "active": False,
            "pressure": 0.0,
            "front_rebuild_required": False,
            "message": "尚無結算資料可檢查排名錯位",
        }

    rolling = rolling_adjustment_data(review)
    recent = rolling.get("recent_performance") or {}
    monthly = review.get("monthly_review") or {}
    recent_settled = review.get("recent_settled") or []

    last5_top10 = float(recent.get("last5_top10_avg", 0) or 0)
    last5_top15 = float(recent.get("last5_top15_avg", 0) or 0)
    last5_gap = round(last5_top15 - last5_top10, 3)
    monthly_top10 = float(monthly.get("avg_top10_hits", 0) or 0)
    monthly_top15 = float(monthly.get("avg_top15_hits", 0) or 0)
    monthly_gap = round(monthly_top15 - monthly_top10, 3)

    bucket_hits = Counter()
    exact_late_hits = Counter()
    missed_top10 = Counter()
    failed_top9 = Counter()
    late_tails = Counter()
    late_zones = Counter()
    for settled in recent_settled[:12]:
        actual = {
            int(number)
            for number in (settled.get("actual_numbers") or [])
            if NUMBER_MIN <= int(number) <= NUMBER_MAX
        }
        candidates = [
            int(number)
            for number in (settled.get("candidate_numbers") or [])
            if NUMBER_MIN <= int(number) <= NUMBER_MAX
        ]
        ranges = [
            ("前五", candidates[:5]),
            ("第六到第九", candidates[5:9]),
            ("第十到第十五", candidates[9:15]),
            ("第十六到第二十四", candidates[15:24]),
        ]
        for label, numbers in ranges:
            hits = set(numbers) & actual
            if hits:
                bucket_hits[label] += len(hits)
        for number in set(candidates[9:15]) & actual:
            exact_late_hits[number] += 1
            late_tails[number % 10] += 1
            late_zones[zone_label(number)] += 1
        for number in actual - set(candidates[:10]):
            missed_top10[number] += 1
        for number in set(candidates[:9]) - actual:
            failed_top9[number] += 1

    front_gap_active = (last5_gap >= 0.55 and last5_top10 < 1.9) or (monthly_gap >= 0.55 and monthly_top10 < 1.75)
    late_layer_active = bucket_hits.get("第十到第十五", 0) >= max(3, bucket_hits.get("前五", 0))
    active = bool(front_gap_active or late_layer_active)
    pressure = 0.0
    if active:
        pressure = 1.0
        pressure += min(0.45, max(0.0, last5_gap) * 0.28)
        pressure += min(0.35, max(0.0, monthly_gap) * 0.22)
        pressure += 0.25 if recent.get("critical_slump") else 0.12 if recent.get("recent_slump") else 0.0
        pressure = round(clamp(pressure, 0.85, 1.85), 3)

    reserve_slots = 3 if active and (last5_gap >= 0.75 or bucket_hits.get("第十到第十五", 0) >= 5) else 2 if active else 0
    return {
        "status": "啟動" if active else "觀察",
        "active": active,
        "front_rebuild_required": active,
        "pressure": pressure,
        "reserve_slots": reserve_slots,
        "last5_top10_avg": round(last5_top10, 3),
        "last5_top15_avg": round(last5_top15, 3),
        "last5_top15_minus_top10": last5_gap,
        "monthly_top10_avg": round(monthly_top10, 3),
        "monthly_top15_avg": round(monthly_top15, 3),
        "monthly_top15_minus_top10": monthly_gap,
        "bucket_hits": dict(bucket_hits),
        "late_hit_numbers": [{"number": n, "count": c} for n, c in exact_late_hits.most_common(12)],
        "missed_top10_numbers": [{"number": n, "count": c} for n, c in missed_top10.most_common(12)],
        "failed_top9_numbers": [{"number": n, "count": c} for n, c in failed_top9.most_common(12)],
        "late_hit_tails": [{"tail": n, "count": c} for n, c in late_tails.most_common(10)],
        "late_hit_zones": [{"zone": n, "count": c} for n, c in late_zones.most_common()],
        "message": "前十五命中明顯高於前十，啟動排名錯位修正與第十到十五名有效訊號前移。" if active else "前九與前十五差距尚未觸發硬修正。",
    }


def rank_window_drift_scores(review):
    diagnosis = rank_window_drift_diagnosis(review)
    if not diagnosis.get("active"):
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}

    rolling = rolling_adjustment_data(review)
    repeated_failed = {
        int(item.get("number")): int(item.get("miss_count", 0) or 0)
        for item in rolling.get("repeated_failed_numbers", [])
        if item.get("number")
    }
    late_hits = {
        int(item.get("number")): int(item.get("count", 0) or 0)
        for item in diagnosis.get("late_hit_numbers", [])
        if item.get("number")
    }
    missed_top10 = {
        int(item.get("number")): int(item.get("count", 0) or 0)
        for item in diagnosis.get("missed_top10_numbers", [])
        if item.get("number")
    }
    late_tails = {
        int(item.get("tail")): int(item.get("count", 0) or 0)
        for item in diagnosis.get("late_hit_tails", [])
        if item.get("tail") is not None
    }
    late_zones = {
        str(item.get("zone")): int(item.get("count", 0) or 0)
        for item in diagnosis.get("late_hit_zones", [])
        if item.get("zone")
    }
    last2_missed = {
        int(item.get("number")): int(item.get("missed_count", 0) or 0)
        for item in rolling.get("last2_missed_actual_numbers", [])
        if item.get("number")
    }
    pressure = float(diagnosis.get("pressure", 1.0) or 1.0)
    anchor_numbers = set(late_hits) | set(missed_top10)

    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        score = 0.0
        if number in late_hits:
            score += min(0.95, 0.34 + late_hits[number] * 0.22)
        if number in missed_top10:
            score += min(0.82, 0.24 + missed_top10[number] * 0.18)
        if number in last2_missed:
            score += min(0.45, 0.20 + last2_missed[number] * 0.10)
        if number % 10 in late_tails:
            score += min(0.30, 0.08 + late_tails[number % 10] * 0.045)
        if zone_label(number) in late_zones:
            score += min(0.24, 0.06 + late_zones[zone_label(number)] * 0.035)
        if any(1 <= abs(number - anchor) <= 2 for anchor in anchor_numbers):
            score += 0.16
        if number in repeated_failed and number not in late_hits and number not in missed_top10 and number not in last2_missed:
            score -= min(0.62, 0.10 + repeated_failed[number] * 0.055)
        values[number] = score * pressure
    return normalize(values)


def effective_hit_front_shift_scores(review):
    if not review or not review.get("has_review"):
        return {n: 0.0 for n in range(NUMBER_MIN, NUMBER_MAX + 1)}

    recent_settled = review.get("recent_settled") or []
    rolling = rolling_adjustment_data(review)
    recent = rolling.get("recent_performance") or {}
    actual_late = Counter()
    actual_deep = Counter()
    missed_any = Counter()
    failed_front = Counter()
    hit_tails = Counter()
    hit_zones = Counter()
    deep_tails = Counter()
    deep_zones = Counter()

    for settled in recent_settled[:18]:
        actual = {
            int(number)
            for number in (settled.get("actual_numbers") or [])
            if NUMBER_MIN <= int(number) <= NUMBER_MAX
        }
        candidates = [
            int(number)
            for number in (settled.get("candidate_numbers") or [])
            if NUMBER_MIN <= int(number) <= NUMBER_MAX
        ]
        rank = {number: idx + 1 for idx, number in enumerate(candidates)}
        for number in actual:
            position = rank.get(number, 99)
            if 10 <= position <= 15:
                actual_late[number] += 1
                hit_tails[number % 10] += 1
                hit_zones[zone_label(number)] += 1
            elif 16 <= position <= 24:
                actual_deep[number] += 1
                deep_tails[number % 10] += 1
                deep_zones[zone_label(number)] += 1
            elif position > 24:
                missed_any[number] += 1
        for number in set(candidates[:9]) - actual:
            failed_front[number] += 1

    for item in rolling.get("late_hit_numbers", []) or []:
        number = item.get("number")
        if number:
            actual_late[int(number)] += int(item.get("late_hit_count", 0) or item.get("count", 0) or 0)
    for item in rolling.get("missed_actual_numbers", []) or []:
        number = item.get("number")
        if number:
            missed_any[int(number)] += int(item.get("missed_count", 0) or item.get("count", 0) or 0)

    pressure = 1.0
    if recent.get("critical_slump"):
        pressure = 1.7
    elif recent.get("recent_slump"):
        pressure = 1.35
    anchors = set(actual_late) | set(actual_deep) | set(missed_any)
    values = {}
    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        score = 0.0
        if number in actual_late:
            score += min(1.10, 0.48 + actual_late[number] * 0.25)
        if number in actual_deep:
            score += min(0.78, 0.30 + actual_deep[number] * 0.18)
        if number in missed_any:
            score += min(0.58, 0.20 + missed_any[number] * 0.12)
        if number % 10 in hit_tails:
            score += min(0.34, 0.09 + hit_tails[number % 10] * 0.05)
        if zone_label(number) in hit_zones:
            score += min(0.28, 0.08 + hit_zones[zone_label(number)] * 0.04)
        if number % 10 in deep_tails:
            score += min(0.20, 0.05 + deep_tails[number % 10] * 0.035)
        if zone_label(number) in deep_zones:
            score += min(0.16, 0.04 + deep_zones[zone_label(number)] * 0.025)
        if any(1 <= abs(number - anchor) <= 2 for anchor in anchors):
            score += 0.15
        if number in failed_front and number not in actual_late and number not in actual_deep and number not in missed_any:
            score -= min(0.86, 0.16 + failed_front[number] * 0.10)
        values[number] = score * pressure
    return normalize(values)


def post9_hit_leak_audit(review):
    if not review or not review.get("has_review"):
        return {
            "status": "無資料",
            "active": False,
            "message": "尚無上期結算資料可檢查九名後命中外漏",
        }
    recent_settled = review.get("recent_settled") or []
    buckets = Counter()
    leaked_numbers = Counter()
    failed_top9 = Counter()
    details = []
    checked = 0
    for settled in recent_settled[:12]:
        actual = [
            int(number)
            for number in (settled.get("actual_numbers") or [])
            if NUMBER_MIN <= int(number) <= NUMBER_MAX
        ]
        candidates = [
            int(number)
            for number in (settled.get("candidate_numbers") or [])
            if NUMBER_MIN <= int(number) <= NUMBER_MAX
        ]
        if not actual or not candidates:
            continue
        checked += 1
        rank = {number: idx + 1 for idx, number in enumerate(candidates)}
        actual_set = set(actual)
        for number in actual:
            position = rank.get(number)
            if position is None:
                bucket = "未進候選"
            elif position <= 5:
                bucket = "第一到第五"
            elif position <= 9:
                bucket = "第六到第九"
            elif position <= 15:
                bucket = "第十到第十五"
                leaked_numbers[number] += 1
            elif position <= 24:
                bucket = "第十六到第二十四"
                leaked_numbers[number] += 1
            else:
                bucket = "第二十五以後"
                leaked_numbers[number] += 1
            buckets[bucket] += 1
            details.append(
                {
                    "actual_date": settled.get("actual_date"),
                    "number": number,
                    "rank": position,
                    "bucket": bucket,
                }
            )
        for number in set(candidates[:9]) - actual_set:
            failed_top9[number] += 1

    post9_hits = (
        buckets.get("第十到第十五", 0)
        + buckets.get("第十六到第二十四", 0)
        + buckets.get("第二十五以後", 0)
        + buckets.get("未進候選", 0)
    )
    front9_hits = buckets.get("第一到第五", 0) + buckets.get("第六到第九", 0)
    active = checked > 0 and (post9_hits >= max(3, front9_hits) or buckets.get("第十到第十五", 0) >= 3)
    return {
        "status": "啟動" if active else "觀察",
        "active": active,
        "checked_periods": checked,
        "front9_hits": front9_hits,
        "post9_hits": post9_hits,
        "bucket_hits": dict(buckets),
        "leaked_numbers": [{"number": n, "count": c} for n, c in leaked_numbers.most_common(15)],
        "failed_top9_numbers": [{"number": n, "count": c} for n, c in failed_top9.most_common(15)],
        "recent_details": details[:36],
        "front_shift_required": active,
        "message": "九名後命中外漏已啟動強制前移修正" if active else "九名後外漏未達強制修正門檻",
    }


def slump_mode(review):
    recent = rolling_adjustment_data(review).get("recent_performance", {})
    if recent.get("critical_slump"):
        return "critical"
    if recent.get("recent_slump"):
        return "warning"
    return "normal"


def slump_recovery_weight_shift(review):
    rolling = rolling_adjustment_data(review)
    recent = rolling.get("recent_performance") or {}
    mode = slump_mode(review)
    if mode == "normal":
        return {
            "status": "未啟動",
            "mode": mode,
            "reason": "近期命中未觸發低迷重整",
            "boosted_features": [],
            "reduced_features": [],
        }
    intensity = 1.0 if mode == "warning" else 1.45
    boosted = [
        "full_history_anchor",
        "freq_all",
        "freq_720",
        "freq_1800",
        "rank_window_drift_correction",
        "effective_hit_front_shift",
        "rank_error_correction",
        "missed_hit_recovery",
        "low_probability_error_recovery",
        "walk_forward_hit_signature",
        "omission_phase_rebound",
        "similar_draw_knn",
        "regime_gap_bridge",
        "distribution_balance",
        "positive_edge_core",
    ]
    reduced = [
        "freq_5",
        "freq_10",
        "date",
        "repeat",
        "time_series",
        "neural_network",
        "transition",
        "shape_follow",
        "trend_alignment",
    ]
    return {
        "status": "已啟動",
        "mode": mode,
        "intensity": round(intensity, 2),
        "recent_top10_avg": recent.get("last5_top10_avg"),
        "recent_top15_avg": recent.get("last5_top15_avg"),
        "last2_top10_avg": recent.get("last2_top10_avg"),
        "reason": "近期命中低於基準，改用全歷史錨點、錯位修正、漏抓回收與遺漏相位作主軸。",
        "boosted_features": boosted,
        "reduced_features": reduced,
    }


def build_feature_matrix(draws, review=None, include_dependency=True):
    windows = [5, 10, 20, 50, 100, 300, 720, 1800]
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

    full_freq = frequency(draws)
    freq_all = normalize({
        n: binomial_zscore(full_freq.get(n, 0), len(draws))
        for n in range(NUMBER_MIN, NUMBER_MAX + 1)
    })
    full_history_anchor = full_history_anchor_scores(draws)
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
    rank_window_drift_correction = rank_window_drift_scores(review)
    effective_hit_front_shift = effective_hit_front_shift_scores(review)
    low_probability_error_recovery = low_probability_error_recovery_scores(review)
    if include_dependency:
        walk_window = int(os.environ.get("TIANTIANLE_WALK_FORWARD_WINDOW", "540"))
    else:
        walk_window = int(os.environ.get("TIANTIANLE_WALK_FORWARD_BACKTEST_WINDOW", "120"))
    walk_forward_hit_signature = walk_forward_hit_signature_scores(draws, window=walk_window)
    external_method_consensus = external_method_consensus_scores(draws, review, walk_forward_hit_signature)
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
        rank_window_drift_correction,
        effective_hit_front_shift,
        low_probability_error_recovery,
        walk_forward_hit_signature,
        external_method_consensus,
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
        rank_window_drift_correction,
        effective_hit_front_shift,
        low_probability_error_recovery,
        walk_forward_hit_signature,
        external_method_consensus,
    ])
    next_date = next_draw_date(draws[-1]["draw_date"])
    date_set = set(date_numbers(next_date))
    date_score = {n: (1.0 if n in date_set else 0.0) for n in range(NUMBER_MIN, NUMBER_MAX + 1)}
    latest_set = set(draws[-1]["numbers"])

    for number in range(NUMBER_MIN, NUMBER_MAX + 1):
        feature_scores[number]["ewma_fast"] = ewma_fast[number]
        feature_scores[number]["ewma_slow"] = ewma_slow[number]
        feature_scores[number]["freq_all"] = freq_all[number]
        feature_scores[number]["full_history_anchor"] = full_history_anchor[number]
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
        feature_scores[number]["rank_window_drift_correction"] = rank_window_drift_correction[number]
        feature_scores[number]["effective_hit_front_shift"] = effective_hit_front_shift[number]
        feature_scores[number]["low_probability_error_recovery"] = low_probability_error_recovery[number]
        feature_scores[number]["walk_forward_hit_signature"] = walk_forward_hit_signature[number]
        feature_scores[number]["external_method_consensus"] = external_method_consensus[number]
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
        "freq_10": 0.035,
        "freq_20": 0.064,
        "freq_50": 0.104,
        "freq_100": 0.112,
        "freq_300": 0.07,
        "freq_720": 0.084,
        "freq_1800": 0.076,
        "freq_all": 0.092,
        "full_history_anchor": 0.14,
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
        "rank_window_drift_correction": 0.064,
        "effective_hit_front_shift": 0.072,
        "low_probability_error_recovery": 0.086,
        "walk_forward_hit_signature": 0.125,
        "external_method_consensus": 0.104,
        "positive_edge_core": 0.18,
        "date": 0.025,
        "repeat": 0.015,
        "neighbor": 0.025,
    }
    if review and review.get("severity") == "critical":
        weights.update(
            {
                "freq_5": 0.01,
                "freq_10": 0.016,
                "freq_20": 0.048,
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
                "rank_window_drift_correction": 0.154,
                "effective_hit_front_shift": 0.182,
                "low_probability_error_recovery": 0.205,
                "walk_forward_hit_signature": 0.24,
                "external_method_consensus": 0.225,
                "positive_edge_core": 0.28,
                "repeat": 0.005,
                "neighbor": 0.01,
                "freq_50": 0.124,
                "freq_100": 0.13,
                "freq_300": 0.102,
                "freq_720": 0.128,
                "freq_1800": 0.118,
                "freq_all": 0.15,
                "full_history_anchor": 0.24,
                "omission": 0.185,
                "tail_zone": 0.138,
                "pair": 0.132,
            }
        )
    mode = slump_mode(review)
    if mode in {"warning", "critical"}:
        intensity = 1.0 if mode == "warning" else 1.35
        for key in ["freq_5", "freq_10", "date", "repeat", "time_series", "neural_network", "cross_consensus", "shape_follow", "trend_alignment", "transition"]:
            if key in weights:
                weights[key] *= 0.68 if mode == "warning" else 0.48
        for key in [
            "rank_error_correction",
            "rank_window_drift_correction",
            "effective_hit_front_shift",
            "low_probability_error_recovery",
            "walk_forward_hit_signature",
            "external_method_consensus",
            "positive_edge_core",
            "full_history_anchor",
            "freq_all",
            "freq_720",
            "freq_1800",
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
                weights[key] *= 1.0 + 0.46 * intensity
        if mode == "critical":
            for key in ["full_history_anchor", "freq_all", "rank_window_drift_correction", "effective_hit_front_shift", "low_probability_error_recovery", "walk_forward_hit_signature", "external_method_consensus", "missed_hit_recovery", "omission_phase_rebound"]:
                if key in weights:
                    weights[key] *= 1.18
    total = sum(weights.values()) or 1
    return {key: value / total for key, value in weights.items()}


MODEL_SOURCE_LABELS = {
    "freq_5": "\u8fd15\u671f\u71b1\u5ea6",
    "freq_10": "\u8fd110\u671f\u71b1\u5ea6",
    "freq_20": "\u8fd120\u671f\u71b1\u5ea6",
    "freq_50": "\u8fd150\u671f\u71b1\u5ea6",
    "freq_100": "\u8fd1100\u671f\u71b1\u5ea6",
    "freq_300": "\u8fd1300\u671f\u7a69\u5b9a",
    "freq_720": "\u8fd1720\u671f\u9577\u7dda",
    "freq_1800": "\u8fd11800\u671f\u9577\u7dda",
    "freq_all": "\u5168\u6b77\u53f2\u983b\u7387",
    "full_history_anchor": "\u5168\u6b77\u53f2\u9328\u9ede",
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
    "rank_window_drift_correction": "\u524d\u4e5d\u8207\u524d\u5341\u4e94\u932f\u4f4d\u4fee\u6b63",
    "effective_hit_front_shift": "\u6709\u6548\u547d\u4e2d\u524d\u79fb",
    "low_probability_error_recovery": "\u4f4e\u6a5f\u7387\u8aa4\u958b\u56de\u6536",
    "walk_forward_hit_signature": "\u6efe\u52d5\u547d\u4e2d\u6307\u7d0b",
    "external_method_consensus": "\u5916\u90e8\u65b9\u6cd5\u5171\u8b58\u6821\u6b63",
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
        ("rank_window_drift_correction", "\u524d\u4e5d\u8207\u524d\u5341\u4e94\u932f\u4f4d\u4fee\u6b63", values.get("rank_window_drift_correction", 0) >= 0.52),
        ("effective_hit_front_shift", "\u6709\u6548\u547d\u4e2d\u524d\u79fb", values.get("effective_hit_front_shift", 0) >= 0.52),
        ("low_probability_error_recovery", "\u4f4e\u6a5f\u7387\u8aa4\u958b\u56de\u6536", values.get("low_probability_error_recovery", 0) >= 0.50),
        ("walk_forward_hit_signature", "\u6efe\u52d5\u547d\u4e2d\u6307\u7d0b", values.get("walk_forward_hit_signature", 0) >= 0.54),
        ("external_method_consensus", "\u5916\u90e8\u65b9\u6cd5\u5171\u8b58", values.get("external_method_consensus", 0) >= 0.54),
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
    score += values.get("rank_window_drift_correction", 0.0) * 4.2
    score += values.get("effective_hit_front_shift", 0.0) * 5.4
    score += values.get("low_probability_error_recovery", 0.0) * 6.6
    score += values.get("walk_forward_hit_signature", 0.0) * 5.8
    score += values.get("external_method_consensus", 0.0) * 5.2
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

    if number in missed_actual_numbers and (
        values.get("rank_error_correction", 0) >= 0.4
        or values.get("missed_hit_recovery", 0) >= 0.5
        or values.get("rank_window_drift_correction", 0) >= 0.5
        or values.get("effective_hit_front_shift", 0) >= 0.48
        or values.get("low_probability_error_recovery", 0) >= 0.5
        or values.get("walk_forward_hit_signature", 0) >= 0.55
        or values.get("external_method_consensus", 0) >= 0.58
    ):
        score += 10.0
    if values.get("low_probability_error_recovery", 0) >= 0.58:
        score += 8.0
    if values.get("external_method_consensus", 0) >= 0.62:
        score += 5.0
    if values.get("walk_forward_hit_signature", 0) >= 0.62:
        score += 5.0
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
    if realtime_timing_enabled():
        shift = slump_recovery_weight_shift(review)
        return base_weights, {
            "status": "realtime_slump_reweighted" if shift.get("status") == "已啟動" else "realtime_fast_path",
            "rounds": 0,
            "method": "full_history_anchor_with_slump_recovery_shift_and_walk_forward_signature",
            "reason": shift.get("reason") or "即時更新禁止跑重型權重回測，午後完整模式才執行深度權重校正。",
            "slump_recovery_weight_shift": shift,
            "top_boosted_features": [{"feature": name, "reason": "低迷重整升權"} for name in shift.get("boosted_features", [])[:8]],
            "top_penalized_features": [{"feature": name, "reason": "近期失準降權"} for name in shift.get("reduced_features", [])[:8]],
            "base_weights": {name: round(value, 5) for name, value in base_weights.items()},
            "calibrated_weights": {name: round(value, 5) for name, value in base_weights.items()},
        }
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
    last2_missed_actual_numbers = {int(item.get("number")) for item in rolling.get("last2_missed_actual_numbers", []) if item.get("number")}
    last2_failed_top10_numbers = {int(item.get("number")) for item in rolling.get("last2_failed_top10_numbers", []) if item.get("number")}
    missed_actual_tails = {int(item.get("tail")) for item in rolling.get("missed_actual_tails", []) if item.get("tail") is not None}
    missed_actual_zones = {str(item.get("zone")) for item in rolling.get("missed_actual_zones", []) if item.get("zone")}
    low_error_numbers = set(low_probability_error_number_map(review))
    mode = slump_mode(review)
    emergency_low_hit = bool((rolling.get("recent_performance") or {}).get("two_draw_low_hit"))
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
            raw *= 0.54 if emergency_low_hit else 0.66 if mode == "critical" else 0.74
            reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u8edf\u964d\u6b0a\u91cd\u65b0\u9a57\u8b49")
        elif previous_policy and previous_policy["passed"]:
            raw *= 0.96
            reasons[number].append("\u6628\u65e5\u9810\u6e2c\u865f\u901a\u904e\u56de\u6536\u91cd\u9a57")
        if number in failed:
            raw *= 0.42 if emergency_low_hit else 0.58 if mode == "critical" else 0.68
            reasons[number].append("\u4e0a\u671f\u5931\u6557\u6838\u5fc3\u865f\u78bc\u8edf\u98a8\u63a7")
        if emergency_low_hit and number in last2_failed_top10_numbers and number not in last2_missed_actual_numbers and number not in late_hit_numbers:
            raw *= 0.50
            reasons[number].append("\u9023\u7e8c\u4f4e\u547d\u4e2d\u5931\u6557\u524d\u5341\u91cd\u964d\u6b0a")
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
        if values["rank_window_drift_correction"] >= 0.7:
            reasons[number].append("\u524d\u4e5d\u8207\u524d\u5341\u4e94\u932f\u4f4d\u4fee\u6b63")
        if values["effective_hit_front_shift"] >= 0.7:
            reasons[number].append("\u6709\u6548\u547d\u4e2d\u524d\u79fb")
        if values["low_probability_error_recovery"] >= 0.62:
            reasons[number].append("\u4f4e\u6a5f\u7387\u8aa4\u958b\u56de\u6536")
        if values["walk_forward_hit_signature"] >= 0.66:
            reasons[number].append("\u6efe\u52d5\u547d\u4e2d\u6307\u7d0b")
        if values["external_method_consensus"] >= 0.62:
            reasons[number].append("\u5916\u90e8\u65b9\u6cd5\u5171\u8b58\u6821\u6b63")
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
            raw *= 0.55 if emergency_low_hit else 0.72 if mode == "critical" else 0.8 if mode == "warning" else 0.86
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u9023\u7e8c\u672a\u547d\u4e2d\u964d\u6b0a")
        if number in late_hit_numbers and values["rank_error_correction"] >= 0.55:
            raw *= 1.42 if mode == "critical" else 1.26 if mode == "warning" else 1.16
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u5f8c\u6bb5\u547d\u4e2d\u524d\u79fb")
        recovery_signal = (
            values["rank_error_correction"] * 0.32
            + values["rank_window_drift_correction"] * 0.24
            + values["effective_hit_front_shift"] * 0.28
            + values["low_probability_error_recovery"] * 0.34
            + values["walk_forward_hit_signature"] * 0.24
            + values["external_method_consensus"] * 0.26
            + values["missed_hit_recovery"] * 0.20
            + values["omission"] * 0.08
            + values["distribution_balance"] * 0.06
        )
        if number in low_error_numbers and values["low_probability_error_recovery"] >= 0.46:
            raw *= 2.35 if emergency_low_hit else 2.05 if mode == "critical" else 1.45
            reasons[number].append("\u4f4e\u6a5f\u7387\u8aa4\u958b\u865f\u78bc\u5f37\u5236\u56de\u6536")
        if values["external_method_consensus"] >= 0.70 and number not in latest_set:
            raw *= 1.34 if mode == "critical" else 1.22 if mode == "warning" else 1.12
            reasons[number].append("\u5916\u90e8\u7d71\u8a08\u6a21\u5f0f\u524d\u79fb")
        if mode == "critical" and values["walk_forward_hit_signature"] >= 0.66 and number not in latest_set:
            raw *= 1.28
            reasons[number].append("\u5168\u6b77\u53f2\u6efe\u52d5\u56de\u653e\u524d\u79fb")
        if emergency_low_hit and number in last2_missed_actual_numbers and number not in latest_set:
            raw *= 1.36
            reasons[number].append("\u9023\u7e8c\u4f4e\u547d\u4e2d\u6f0f\u6293\u865f\u5f37\u5236\u56de\u6536")
        if number in missed_actual_numbers and (
            values["rank_error_correction"] >= 0.4
            or values["missed_hit_recovery"] >= 0.5
            or values["rank_window_drift_correction"] >= 0.45
            or values["effective_hit_front_shift"] >= 0.45
        ):
            raw *= 2.05 if emergency_low_hit else 1.72 if mode == "critical" else 1.30
            reasons[number].append("\u6efe\u52d5\u6aa2\u8a0e\u6f0f\u6293\u5be6\u958b\u865f\u88dc\u4f4d")
        elif values["effective_hit_front_shift"] >= 0.62 and number not in latest_set:
            raw *= 1.52 if emergency_low_hit else 1.38 if mode == "critical" else 1.18
            reasons[number].append("\u6709\u6548\u547d\u4e2d\u524d\u79fb\u88dc\u5f37")
        elif values["rank_window_drift_correction"] >= 0.68 and number not in latest_set:
            raw *= 1.38 if emergency_low_hit else 1.26 if mode == "critical" else 1.14
            reasons[number].append("\u524d\u4e5d\u8207\u524d\u5341\u4e94\u932f\u4f4d\u88dc\u5f37")
        elif (number % 10 in missed_actual_tails or zone_label(number) in missed_actual_zones) and mode in {"warning", "critical"}:
            raw *= 1.34 if emergency_low_hit else 1.24 if mode == "critical" else 1.13
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
                "feature_signals": {
                    "rank_error_correction": round(features[number].get("rank_error_correction", 0.0), 4),
                    "rank_window_drift_correction": round(features[number].get("rank_window_drift_correction", 0.0), 4),
                    "effective_hit_front_shift": round(features[number].get("effective_hit_front_shift", 0.0), 4),
                    "low_probability_error_recovery": round(features[number].get("low_probability_error_recovery", 0.0), 4),
                    "walk_forward_hit_signature": round(features[number].get("walk_forward_hit_signature", 0.0), 4),
                    "external_method_consensus": round(features[number].get("external_method_consensus", 0.0), 4),
                    "missed_hit_recovery": round(features[number].get("missed_hit_recovery", 0.0), 4),
                    "omission_phase_rebound": round(features[number].get("omission_phase_rebound", 0.0), 4),
                    "positive_edge_core": round(features[number].get("positive_edge_core", 0.0), 4),
                },
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


def top9_diversity_rebalanced_order(ranked_numbers, score_map, candidate_items, review=None):
    if len(ranked_numbers) <= 9:
        return ranked_numbers, {
            "status": "skipped",
            "reason": "candidate_count_not_enough",
            "promoted_by_diversity": [],
            "demoted_by_diversity": [],
        }
    candidate_items = candidate_items or {}
    drift = rank_window_drift_diagnosis(review)
    drift_scores = rank_window_drift_scores(review) if drift.get("active") else {}
    effective_scores = effective_hit_front_shift_scores(review)
    pool_size = 24 if drift.get("active") else 18
    pool = list(ranked_numbers[:pool_size])
    original_top9 = set(ranked_numbers[:9])
    selected = []
    failed = failed_number_set(review)
    mode = slump_mode(review)
    max_zone = 3
    max_tail = 2

    def selection_penalty(number):
        zone_count = sum(1 for selected_number in selected if zone_label(selected_number) == zone_label(number))
        tail_count = sum(1 for selected_number in selected if selected_number % 10 == number % 10)
        adjacent_count = sum(1 for selected_number in selected if abs(selected_number - number) == 1)
        penalty = 0.0
        if zone_count >= max_zone:
            penalty += 0.18 if mode == "critical" else 0.14
        elif zone_count == max_zone - 1:
            penalty += 0.055
        if tail_count >= max_tail:
            penalty += 0.14 if mode == "critical" else 0.10
        elif tail_count == max_tail - 1:
            penalty += 0.035
        penalty += adjacent_count * 0.025
        penalty += item_soft_risk_penalty(candidate_items.get(number, {"number": number}), failed) * 0.65
        return penalty

    while len(selected) < 9 and pool:
        def front_shift_signal(number):
            feature_signals = (candidate_items.get(number, {}) or {}).get("feature_signals") or {}
            return max(
                float(feature_signals.get("effective_hit_front_shift", 0.0) or 0.0),
                float(effective_scores.get(number, 0.0) or 0.0),
            )

        best = max(
            pool,
            key=lambda number: (
                float(score_map.get(number, 0.0) or 0.0)
                + float(drift_scores.get(number, 0.0) or 0.0) * (0.16 if drift.get("active") else 0.0)
                + front_shift_signal(number) * (0.22 if drift.get("active") or mode == "critical" else 0.11)
                + float(((candidate_items.get(number, {}) or {}).get("feature_signals") or {}).get("walk_forward_hit_signature", 0.0) or 0.0) * (0.14 if mode == "critical" else 0.07)
                - selection_penalty(number)
                + (0.004 if number in original_top9 and mode != "critical" else 0.0),
                float(score_map.get(number, 0.0) or 0.0),
                -number,
            ),
        )
        selected.append(best)
        pool.remove(best)

    ordered_top9 = selected + [number for number in ranked_numbers if number not in selected][: max(0, 9 - len(selected))]
    ordered_top9 = ordered_top9[:9]
    ordered_top9_set = set(ordered_top9)
    final_order = ordered_top9 + [number for number in ranked_numbers if number not in ordered_top9_set]
    final_top9 = set(ordered_top9)
    promoted = sorted(final_top9 - original_top9)
    demoted = sorted(original_top9 - final_top9)
    return final_order, {
        "status": "active",
        "policy": "前九名內加入區間、尾數、鄰號與失敗風險重平衡，避免高訊號集中後命中落到第十到第十五名。",
        "original_top9": ranked_numbers[:9],
        "rebalanced_top9": ordered_top9,
        "promoted_by_diversity": promoted,
        "demoted_by_diversity": demoted,
        "zone_counts": dict(Counter(zone_label(number) for number in ordered_top9)),
        "tail_counts": dict(Counter(number % 10 for number in ordered_top9)),
        "rank_window_drift": drift,
        "effective_hit_front_shift_active": max(effective_scores.values(), default=0.0) >= 0.55,
        "effective_hit_front_shift_promoted": sorted(
            number for number in promoted if effective_scores.get(number, 0.0) >= 0.45
        ),
    }


def strong_single_group(candidates, review=None):
    rolling = rolling_adjustment_data(review)
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    repeated_failed_numbers = {int(item.get("number")) for item in rolling.get("repeated_failed_numbers", []) if item.get("number")}
    scan_limit = 18 if slump_mode(review) == "critical" else 12
    drift_active = rank_window_drift_diagnosis(review).get("active")
    ranked_items = sorted(
        candidates[:scan_limit],
        key=lambda item: (
            float(item.get("score", 0) or 0)
            + float((item.get("feature_signals") or {}).get("rank_window_drift_correction", 0) or 0) * (0.18 if drift_active else 0.08)
            + float((item.get("feature_signals") or {}).get("walk_forward_hit_signature", 0) or 0) * (0.15 if slump_mode(review) == "critical" else 0.08)
            + int(item.get("stability_count", 0) or 0) * 0.012
            + int((item.get("cross_validation") or {}).get("passed_count", 0) or 0) * 0.008
            - item_soft_risk_penalty(item, repeated_failed_numbers),
            -int(item["number"]),
        ),
        reverse=True,
    )
    for item in ranked_items:
        number = item["number"]
        reasons = set(item.get("reasons", []))
        guard = item.get("previous_prediction_guard")
        drift_score = float((item.get("feature_signals") or {}).get("rank_window_drift_correction", 0) or 0)
        walk_score = float((item.get("feature_signals") or {}).get("walk_forward_hit_signature", 0) or 0)
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
        if drift_active and drift_score >= 0.7 and score >= 0.62 and confidence >= 80 and stability >= 2:
            return [number]
        if walk_score >= 0.72 and score >= 0.62 and confidence >= 80 and stability >= 2:
            return [number]
    return []


def single_precision_group(candidates, review=None):
    failed = failed_number_set(review)
    rolling = rolling_adjustment_data(review)
    boosted_reasons = {item.get("reason") for item in rolling.get("boosted_reasons", [])}
    late_hit_numbers = {int(item.get("number")) for item in rolling.get("late_hit_numbers", []) if item.get("number")}
    drift_active = rank_window_drift_diagnosis(review).get("active")
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
            + float((item.get("feature_signals") or {}).get("rank_window_drift_correction", 0) or 0) * (0.10 if drift_active else 0.04)
            + float((item.get("feature_signals") or {}).get("walk_forward_hit_signature", 0) or 0) * (0.10 if slump_mode(review) == "critical" else 0.05)
            - item_soft_risk_penalty(item, failed)
        )
        ranked.append((precision_score, item))
    ranked.sort(key=lambda pair: (pair[0], pair[1].get("score", 0), pair[1].get("confidence_index", 0), -pair[1]["number"]), reverse=True)
    return [ranked[0][1]["number"]] if ranked else []


def five_hit_two_group(candidates, review=None):
    failed = failed_number_set(review)
    drift_active = rank_window_drift_diagnosis(review).get("active")
    selected = []
    pool = sorted(
        candidates[:24],
        key=lambda item: (
            item.get("score", 0)
            + float((item.get("feature_signals") or {}).get("rank_window_drift_correction", 0) or 0) * (0.12 if drift_active else 0.04)
            + float((item.get("feature_signals") or {}).get("walk_forward_hit_signature", 0) or 0) * (0.10 if slump_mode(review) == "critical" else 0.04)
            - item_soft_risk_penalty(item, failed),
            item.get("stability_count", 0),
            -item["number"],
        ),
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
    drift_active = rank_window_drift_diagnosis(review).get("active")
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
                + float((item_map[number].get("feature_signals") or {}).get("rank_window_drift_correction", 0) or 0) * (0.14 if drift_active else 0.05)
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
    drift_active = rank_window_drift_diagnosis(review).get("active")
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
                + float((item.get("feature_signals") or {}).get("rank_window_drift_correction", 0) or 0) * (0.12 if drift_active else 0.04)
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
    "walk_forward_signature": "\u6efe\u52d5\u547d\u4e2d\u6307\u7d0b",
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
    elif variant == "walk_forward_signature":
        walk_signal = max(
            precision_source_signal(item, {"walk_forward_hit_signature"}),
            float((item.get("feature_signals") or {}).get("walk_forward_hit_signature", 0) or 0),
        )
        value = walk_signal * 0.46 + precision_norm * 0.18 + cross_norm * 0.14 + maturity_norm * 0.12 + frontload * 0.10
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
        and (item.get("entry_validation") or {}).get("passed_for_main", True)
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
        "policy": "前九專用精算小牌模型；每次重新運算；依30/60/120期結算競賽選擇作用模型；第十至十五名不得升格高信心",
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
    last2_missed_actual_counts = {
        int(item.get("number")): int(item.get("missed_count", 0) or 0)
        for item in rolling.get("last2_missed_actual_numbers", [])
        if item.get("number")
    }
    last2_failed_top10_counts = {
        int(item.get("number")): int(item.get("miss_count", 0) or 0)
        for item in rolling.get("last2_failed_top10_numbers", [])
        if item.get("number")
    }
    failed = failed_number_set(review)
    mode = slump_mode(review)
    emergency_low_hit = bool((rolling.get("recent_performance") or {}).get("two_draw_low_hit"))
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
        feature_signals = item.get("feature_signals") or {}
        effective_shift = float(feature_signals.get("effective_hit_front_shift", 0) or 0)
        drift_shift = float(feature_signals.get("rank_window_drift_correction", 0) or 0)
        walk_forward_shift = float(feature_signals.get("walk_forward_hit_signature", 0) or 0)
        rank_anchor = clamp((len(candidates) - idx + 1) / max(len(candidates), 1), 0.0, 1.0)
        front_score = (
            item.get("score", 0) * 0.46
            + confidence_norm * 0.15
            + stability_norm * 0.13
            + maturity_norm * 0.10
            + cross_norm * 0.09
            + rank_anchor * 0.07
            + effective_shift * (0.18 if mode == "critical" else 0.12)
            + drift_shift * (0.10 if mode == "critical" else 0.06)
            + walk_forward_shift * (0.16 if mode == "critical" else 0.09)
        )

        if idx <= 9:
            front_score += 0.025
        elif 10 <= idx <= 15:
            front_score += 0.065 if mode == "critical" else 0.045
            if number in late_hit_counts:
                front_score += 0.20 + min(0.15, late_hit_counts[number] * 0.045)
            if number in missed_actual_counts:
                front_score += 0.17 + min(0.12, missed_actual_counts[number] * 0.04)
            if emergency_low_hit and number in last2_missed_actual_counts:
                front_score += 0.18 + min(0.12, last2_missed_actual_counts[number] * 0.055)
            if reasons & boosted_reasons:
                front_score += 0.065
            if item.get("stability_count", 0) >= 3:
                front_score += 0.035
            if float(maturity.get("score", 0) or 0) >= 70:
                front_score += 0.025
        else:
            if number in late_hit_counts:
                front_score += 0.11
            if number in missed_actual_counts:
                front_score += 0.10
            if emergency_low_hit and number in last2_missed_actual_counts:
                front_score += 0.16
            if effective_shift >= 0.70:
                front_score += 0.10
            if walk_forward_shift >= 0.68:
                front_score += 0.12

        risk = item_soft_risk_penalty(item, failed)
        if number in failed and number not in late_hit_counts and number not in missed_actual_counts:
            risk += 0.045
        if emergency_low_hit and number in last2_failed_top10_counts and number not in last2_missed_actual_counts:
            risk += 0.14
        front_score -= risk * (1.45 if emergency_low_hit else 1.2 if mode == "critical" else 1.0)
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
    pre_diversity_top9 = ranked_numbers[:9]
    ranked_numbers, diversity_audit = top9_diversity_rebalanced_order(
        ranked_numbers,
        normalized_frontload,
        original,
        review,
    )
    top9_numbers = set(ranked_numbers[:9])
    previous_top9 = {int(item["number"]) for item in candidates[:9]}
    diversity_promoted = set(diversity_audit.get("promoted_by_diversity", []))
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
            if number in diversity_promoted:
                reasons.insert(0, "\u524d\u4e5d\u5340\u9593\u5c3e\u6578\u91cd\u5e73\u8861")
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
                reasons.insert(0, "\u524d\u4e5d\u524d\u79fb\u6821\u6e96")
            elif "\u524d\u4e5d\u6838\u5fc3\u4fdd\u7559" not in reasons:
                reasons.append("\u524d\u4e5d\u6838\u5fc3\u4fdd\u7559")
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
                reasons.insert(0, "\u524d\u4e5d\u672a\u904e\u95dc\u964d\u81f3\u5099\u67e5")
            elif 10 <= new_rank <= 15 and "\u7b2c\u5341\u81f3\u7b2c\u5341\u4e94\u5099\u67e5" not in reasons:
                reasons.append("\u7b2c\u5341\u81f3\u7b2c\u5341\u4e94\u5099\u67e5")
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
        "pre_diversity_top9": pre_diversity_top9,
        "top9_numbers": [item["number"] for item in adjusted[:9]],
        "reserve_10_15_numbers": [item["number"] for item in adjusted[9:15]],
        "promoted_to_top9": promoted,
        "demoted_from_top9": demoted,
        "diversity_rebalance": diversity_audit,
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
    entry_allowed_numbers = {
        int(item["number"])
        for item in candidates
        if (item.get("entry_validation") or {}).get("passed_for_main", item.get("top9_core", False))
    }
    strict_pool = [
        item for item in strict_candidate_pool(candidates)
        if int(item["number"]) in entry_allowed_numbers
    ]
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
            pool = [item for item in candidates[:9] if int(item["number"]) in entry_allowed_numbers]
        else:
            pool = [item for item in candidates[: max(size, 12)] if int(item["number"]) in entry_allowed_numbers]
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
            if int(item["number"]) in entry_allowed_numbers
            and item.get("practical_maturity", {}).get("score", 0) >= min_maturity
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
                if int(item["number"]) in entry_allowed_numbers
                and item.get("practical_maturity", {}).get("score", 0) >= fallback_floor
            ]
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
        "boost_rank_window_drift": "\u52a0\u6b0a\u524d\u4e5d\u8207\u524d\u5341\u4e94\u932f\u4f4d\u4fee\u6b63",
        "boost_effective_hit_front_shift": "加權有效命中前移",
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
            f"\u524d\u5341 {round(top10_avg, 3)} / \u96a8\u6a5f {round(random_top10, 3)} / \u512a\u52e2 {round(top10_edge, 4)}",
            "\u9ad8\u6a5f\u7387\u865f\u5bb9\u6613\u843d\u5728\u524d\u5341\u4ee5\u5f8c",
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

    drift = rank_window_drift_diagnosis(review)
    post9_leak = post9_hit_leak_audit(review)
    if drift.get("active"):
        add_gap(
            "\u524d\u4e5d\u8207\u524d\u5341\u4e94\u6392\u540d\u932f\u4f4d",
            f"\u8fd1\u4e94\u671f\u524d\u5341\u4e94\u8207\u524d\u5341\u5dee {drift.get('last5_top15_minus_top10')} / \u6708\u7d71\u8a08 {drift.get('monthly_top15_minus_top10')}",
            "\u4e3b\u63a8\u865f\u904e\u65bc\u4fdd\u5b88\uff0c\u6709\u6548\u547d\u4e2d\u5e38\u843d\u5230\u7b2c10\u523015\u540d",
            "\u5df2\u65b0\u589e\u932f\u4f4d\u4fee\u6b63\u7279\u5fb5\uff0c\u5c07\u5f8c\u6bb5\u88dc\u4e2d\u3001\u6f0f\u6293\u5c3e\u6578\u3001\u5340\u9593\u8207\u76f8\u9130\u62d6\u724c\u63a8\u9032\u524d\u4e5d\u7af6\u8cfd",
            "boost_rank_window_drift",
        )
    if post9_leak.get("active"):
        add_gap(
            "九名後命中外漏",
            f"近{post9_leak.get('checked_periods', 0)}期前九命中 {post9_leak.get('front9_hits', 0)} / 九名後命中 {post9_leak.get('post9_hits', 0)}",
            "有效命中被壓到第十名以後，前九精準度會被拖低",
            "已新增有效命中前移模型，每期把第十到第二十四名的實際命中證據重新拉回前九競賽",
            "boost_effective_hit_front_shift",
        )

    model_source_counts = Counter()
    for item in (candidates or [])[:9]:
        for source in item.get("model_sources") or []:
            model_source_counts[source.get("model")] += 1
    if model_source_counts.get("similar_draw_knn", 0) < 2:
        add_gap(
            "\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130\u8a0a\u865f\u4e0d\u8db3",
            f"\u524d\u4e5d\u4e2d\u8fd1\u9130\u8a0a\u865f {model_source_counts.get('similar_draw_knn', 0)}",
            "\u6700\u50cf\u7684\u6b77\u53f2\u724c\u672a\u80fd\u652f\u6490\u8db3\u5920\u591a\u524d\u4e5d\u540d",
            "\u5df2\u8b93\u8fd1\u9130\u6a21\u578b\u9032\u5165\u7af6\u8cfd\uff0c\u82e5\u56de\u6e2c\u512a\u65bc\u96a8\u6a5f\u6703\u81ea\u52d5\u589e\u6b0a",
            "boost_similarity_knn",
        )
    if model_source_counts.get("omission_phase_rebound", 0) < 2:
        add_gap(
            "\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48\u8a0a\u865f\u4e0d\u8db3",
            f"\u524d\u4e5d\u4e2d\u76f8\u4f4d\u8a0a\u865f {model_source_counts.get('omission_phase_rebound', 0)}",
            "\u907a\u6f0f\u9031\u671f\u6a21\u578b\u672a\u80fd\u5c07\u6709\u6548\u865f\u78bc\u63a8\u5165\u524d\u4e5d\u540d",
            "\u5df2\u5c07\u6bcf\u9846\u865f\u78bc\u7576\u524d\u907a\u6f0f\u6876\u8207\u6b77\u53f2\u540c\u6876\u4e0b\u671f\u547d\u4e2d\u7387\u5408\u4f75\u904b\u7b97",
            "boost_omission_phase",
        )
    if drift.get("active") and model_source_counts.get("rank_window_drift_correction", 0) < 2:
        add_gap(
            "\u932f\u4f4d\u4fee\u6b63\u8a0a\u865f\u4ecd\u4e0d\u8db3",
            f"\u524d\u4e5d\u4e2d\u932f\u4f4d\u8a0a\u865f {model_source_counts.get('rank_window_drift_correction', 0)}",
            "\u7b2c10\u523015\u540d\u88dc\u4e2d\u8a0a\u865f\u9084\u6c92\u6709\u8db3\u5920\u63a8\u9032\u4e3b\u63a8",
            "\u63d0\u9ad8\u932f\u4f4d\u4fee\u6b63\u6b0a\u91cd\u8207\u5f37\u5236\u56de\u6536\u540d\u984d\uff0c\u4f46\u525b\u958b\u51fa\u865f\u4ecd\u9700\u7d93\u904e\u9632\u5446",
            "boost_rank_window_drift",
        )
    if post9_leak.get("active") and model_source_counts.get("effective_hit_front_shift", 0) < 2:
        add_gap(
            "有效命中前移訊號不足",
            f"前九中有效命中前移訊號 {model_source_counts.get('effective_hit_front_shift', 0)}",
            "已確認第九名後有命中外漏，但前九尚未充分吸收前移證據",
            "提高有效命中前移權重、放寬第十到第二十四名回收名額，並保留防火牆避免上期號碼直接回鍋",
            "boost_effective_hit_front_shift",
        )

    top9 = [int(item.get("number")) for item in (candidates or [])[:9] if item.get("number") is not None]
    zone_counts = Counter(zone_label(number) for number in top9)
    tail_counts = Counter(number % 10 for number in top9)
    if zone_counts and (max(zone_counts.values()) >= 4 or max(tail_counts.values()) >= 3):
        add_gap(
            "\u5019\u9078\u6c60\u96c6\u4e2d\u5ea6\u904e\u9ad8",
            f"\u524d\u4e5d\u5340\u9593 {dict(zone_counts)} / \u5c3e\u6578 {dict(tail_counts)}",
            "\u9ad8\u5206\u865f\u904e\u5ea6\u64e0\u5728\u540c\u5340\u6216\u540c\u5c3e\uff0c\u5bb9\u6613\u8b93\u547d\u4e2d\u5206\u6563\u5230\u7b2c\u5341\u81f3\u7b2c\u5341\u4e94",
            "\u57289\u78bc\u5167\u52a0\u5165\u5340\u9593\u8207\u5c3e\u6578\u5206\u6563\u61f2\u7f70\uff0c\u4e26\u628a\u5f8c\u6bb5\u9ad8\u8a0a\u865f\u62c9\u56de\u524d\u4e5d\u7af6\u722d",
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
        "new_model_keys": ["regime_gap_bridge", "similar_draw_knn", "omission_phase_rebound", "rank_window_drift_correction", "effective_hit_front_shift"],
        "new_model_added": "\u578b\u614b\u7f3a\u53e3\u6a4b\u63a5\u3001\u76f8\u4f3c\u6b77\u53f2\u8fd1\u9130\u3001\u907a\u6f0f\u76f8\u4f4d\u56de\u5f48\u3001\u524d\u4e5d\u8207\u524d\u5341\u4e94\u932f\u4f4d\u4fee\u6b63、有效命中前移",
        "missing_elements": missing,
        "active_actions": sorted(set(actions)),
        "active_action_labels": [action_labels.get(action, action) for action in sorted(set(actions))],
        "top_boosted_features": (weight_calibration or {}).get("top_boosted_features", [])[:6],
        "top_penalized_features": (weight_calibration or {}).get("top_penalized_features", [])[:6],
        "top9_numbers": top9,
        "rank_window_drift_correction": drift,
        "post9_hit_leak_audit": post9_leak,
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


def _recent_avoid_risk_profile(draws, review=None, lookback=10):
    recent = list((draws or [])[-lookback:])
    number_counts = Counter()
    tail_counts = Counter()
    zone_counts = Counter()
    for draw in recent:
        for number in draw.get("numbers", []):
            number = int(number)
            number_counts[number] += 1
            tail_counts[number % 10] += 1
            zone_counts[zone_label(number)] += 1
    latest_numbers = {int(number) for number in (recent[-1].get("numbers", []) if recent else [])}
    review = review or {}
    monthly = review.get("monthly_review") or {}
    rolling = review.get("rolling_summary") or {}
    missed_actual = set()
    late_hit = set()
    for item in monthly.get("monthly_missed_actual_numbers", []):
        if item.get("number"):
            missed_actual.add(int(item["number"]))
    for item in monthly.get("monthly_late_hit_numbers", []):
        if item.get("number"):
            late_hit.add(int(item["number"]))
    for number, count in (rolling.get("hit_number_counts") or {}).items():
        if int(count or 0) >= 1:
            late_hit.add(int(number))
    low_error = set(low_probability_error_number_map(review))
    return {
        "number_counts": number_counts,
        "tail_counts": tail_counts,
        "zone_counts": zone_counts,
        "latest_numbers": latest_numbers,
        "missed_actual": missed_actual,
        "late_hit": late_hit,
        "low_probability_error": low_error,
    }


def unlikely_number_analysis(draws, candidates, stability, review=None, limit=12):
    features = build_feature_matrix(draws, review, include_dependency=False)
    score_map = {item["number"]: item["score"] for item in candidates}
    rank_map = {item["number"]: index + 1 for index, item in enumerate(candidates)}
    stability_counts = {int(number): count for number, count in stability.get("consensus_counts", {}).items()}
    latest_set = set(draws[-1]["numbers"])
    pressure = _recent_avoid_risk_profile(draws, review)
    recovery_numbers = set(pressure["missed_actual"]) | set(pressure["late_hit"]) | set(pressure["low_probability_error"])
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
        recent_risk = min(1.0, pressure["number_counts"].get(number, 0) / 2.0)
        tail_risk = min(1.0, pressure["tail_counts"].get(number % 10, 0) / 8.0)
        zone_risk = min(1.0, pressure["zone_counts"].get(zone_label(number), 0) / 12.0)
        recovery_risk = 1.0 if number in recovery_numbers else 0.0
        low_probability_error_risk = values.get("low_probability_error_recovery", 0.0)
        positive_signal_risk = max(
            values.get("positive_edge_core", 0),
            values.get("rank_error_correction", 0),
            values.get("missed_hit_recovery", 0),
            values.get("omission_phase_rebound", 0),
            values.get("similar_draw_knn", 0),
            low_probability_error_risk,
        )
        if number in pressure["latest_numbers"]:
            recent_risk = max(recent_risk, 0.9)
            reasons.append("近期實開號封鎖低機率核心")
        if number in previous_blocked and number not in recovery_numbers and recent_risk < 0.5:
            penalty += 0.18
            reasons.append("昨日預測號未達重入門檻")
        if number in failed and number not in recovery_numbers and recent_risk < 0.5:
            penalty += 0.12
            reasons.append("上期失敗號碼保守隔離")
        if number in latest_set:
            if repeat_policy.get(number, {}).get("historical_support"):
                reasons.append("連莊有歷史支撐，不列核心低機率")
            else:
                reasons.append("剛開出號不列核心低機率")
        if stability_counts.get(number, 0) == 0 and recent_risk < 0.5 and not recovery_risk:
            penalty += 0.10
            reasons.append("擾動模型無穩定共識")
        if weak_signal_count >= 5 and recent_risk < 0.5 and not recovery_risk:
            penalty += 0.14
            reasons.append("短中長期與關聯指標偏弱")
        if rank_map.get(number, 99) > 24 and recent_risk < 0.5 and not recovery_risk:
            penalty += 0.10
            reasons.append("第二十四名外")
        appearance_risk = max(0.0, min(1.0, score_map.get(number, 0.0)))
        avoid_score = (
            (1 - appearance_risk) * 0.34
            + min(1.0, weak_signal_count / 7.0) * 0.18
            + penalty
            - recent_risk * 0.38
            - tail_risk * 0.08
            - zone_risk * 0.06
            - recovery_risk * 0.44
            - low_probability_error_risk * 0.42
            - positive_signal_risk * 0.24
        )
        if rank_map.get(number, 99) <= 9:
            avoid_score -= 0.28
        elif rank_map.get(number, 99) <= 15:
            avoid_score -= 0.18
        avoid_score = max(0.0, min(1.0, avoid_score))
        blocked_by_hit_risk = bool(
            recent_risk >= 0.5
            or recovery_risk
            or low_probability_error_risk >= 0.42
            or positive_signal_risk >= 0.62
            or rank_map.get(number, 99) <= 15
        )
        if blocked_by_hit_risk:
            reasons.append("開出風險過高，已移出低機率核心")
        if low_probability_error_risk >= 0.42:
            reasons.append("低機率誤開回收封鎖")
        if not reasons:
            reasons.append("綜合評分偏弱")
        rows.append(
            {
                "number": number,
                "avoid_score": round(avoid_score, 4),
                "appearance_score": round(appearance_risk, 4),
                "candidate_rank": rank_map.get(number),
                "stability_count": stability_counts.get(number, 0),
                "weak_signal_count": weak_signal_count,
                "recent_hit_risk": round(recent_risk, 4),
                "tail_hit_risk": round(tail_risk, 4),
                "zone_hit_risk": round(zone_risk, 4),
                "recovery_risk": round(recovery_risk, 4),
                "low_probability_error_risk": round(low_probability_error_risk, 4),
                "positive_signal_risk": round(positive_signal_risk, 4),
                "avoid_blocked_by_recent_hit_risk": blocked_by_hit_risk,
                "reasons": reasons[:5],
                "warning": "低機率不代表不會開出",
            }
        )
    rows.sort(key=lambda item: (item["avoid_score"], item["number"]), reverse=True)
    strict_rows = [item for item in rows if not item.get("avoid_blocked_by_recent_hit_risk")]
    strict_rows.extend(item for item in rows if item.get("avoid_blocked_by_recent_hit_risk"))
    return {
        "method": "inverse_signal_risk_filter_recent_hit_blocked",
        "warning": "此區為風控避開觀察，不是絕對不開保證",
        "numbers": strict_rows[:limit],
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


def apply_recent_draw_hard_firewall(candidates, draws, formula_engine=None):
    if not candidates or not draws:
        return candidates, {"status": "skipped", "reason": "no_candidates_or_draws"}
    latest_draw = draws[-1]
    latest_numbers = {int(number) for number in latest_draw.get("numbers", [])}
    repeat_firewall = (formula_engine or {}).get("repeat_firewall") or {}
    formula_status = (formula_engine or {}).get("status")
    formula_edge = float((((formula_engine or {}).get("backtest") or {}).get("ensemble") or {}).get("top9_edge_vs_random", -1.0) or -1.0)
    repeat_allowed = {int(number) for number in repeat_firewall.get("repeat_allowed", [])}
    if realtime_timing_enabled():
        strict_allowed = set()
    else:
        strict_allowed = repeat_allowed if formula_status == "可升權" and formula_edge >= 0.08 else set()
    adjusted = []
    blocked = []
    allowed = []
    for item in candidates:
        row = dict(item)
        number = int(row["number"])
        if number in latest_numbers and number not in strict_allowed:
            row["_recent_firewall_blocked"] = True
            row["score"] = round(float(row.get("score", 0.0) or 0.0) * 0.05, 6)
            row["confidence_index"] = round(min(float(row.get("confidence_index", 0.0) or 0.0), 58.0), 3)
            row["top9_core"] = False
            reason = "剛開出號未通過連莊硬驗證，禁止進入九碼主推"
            reasons = list(row.get("reasons") or [])
            if reason not in reasons:
                reasons.insert(0, reason)
            row["reasons"] = reasons[:8]
            row["recent_draw_firewall"] = {
                "blocked": True,
                "reason": reason,
                "latest_draw_date": latest_draw.get("date"),
            }
            blocked.append(number)
        elif number in latest_numbers:
            row["_recent_firewall_blocked"] = False
            row["recent_draw_firewall"] = {
                "blocked": False,
                "reason": "連莊通過公式正值與回測硬驗證",
                "latest_draw_date": latest_draw.get("date"),
            }
            allowed.append(number)
        else:
            row["_recent_firewall_blocked"] = False
        adjusted.append(row)
    adjusted.sort(
        key=lambda row: (
            0 if row.get("_recent_firewall_blocked") else 1,
            float(row.get("score", 0.0) or 0.0),
            float(row.get("confidence_index", 0.0) or 0.0),
            -int(row["number"]),
        ),
        reverse=True,
    )
    for rank, row in enumerate(adjusted, 1):
        blocked_row = bool(row.pop("_recent_firewall_blocked", False))
        row["rank"] = rank
        row["top9_core"] = rank <= 9 and not blocked_row
    return adjusted, {
        "status": "enforced",
        "policy": "即時版上一期剛開出號一律不得進入九碼主推；完整深算版也必須通過更高正值回測才准連莊。",
        "latest_draw_date": latest_draw.get("date"),
        "latest_numbers": sorted(latest_numbers),
        "blocked_numbers": sorted(blocked),
        "allowed_numbers": sorted(allowed),
        "formula_status": formula_status,
        "formula_edge": round(formula_edge, 4),
    }


def apply_recent_failure_hard_front_gate(candidates, review=None, front_limit=9):
    if not candidates:
        return candidates, {"status": "skipped", "reason": "no_candidates"}
    review = review or {}
    rolling = rolling_adjustment_data(review)
    failed = set(failed_number_set(review))
    repeated_failed = {
        int(item.get("number"))
        for item in rolling.get("repeated_failed_numbers", [])
        if item.get("number")
    }
    last2_failed_top10 = {
        int(item.get("number"))
        for item in rolling.get("last2_failed_top10_numbers", [])
        if item.get("number")
    }
    previous = set(previous_prediction_set(review))
    adjusted = []
    blocked = []
    revalidated = []
    for item in candidates:
        row = dict(item)
        number = int(row["number"])
        previous_guard = row.get("previous_prediction_guard") or {}
        cross = row.get("cross_validation") or {}
        maturity = row.get("practical_maturity") or {}
        maturity_score = float(maturity.get("score", 0.0) or 0.0)
        cross_passed = int(cross.get("passed_count", 0) or 0)
        reasons = list(row.get("reasons") or [])
        model_names = {source.get("model") for source in row.get("model_sources", [])}
        block_reasons = []
        if number in failed:
            block_reasons.append("近期失準號")
        if number in repeated_failed:
            block_reasons.append("連續落空號")
        if number in last2_failed_top10:
            block_reasons.append("近兩期前十落空號")
        if number in previous and previous_guard and not previous_guard.get("passed"):
            block_reasons.append("上期預測回鍋未過")

        strong_full_history = (
            "full_history_anchor" in model_names
            or "freq_all" in model_names
            or "freq_720" in model_names
            or "freq_1800" in model_names
        )
        recovery_signal = (
            "rank_error_correction" in model_names
            or "missed_hit_recovery" in model_names
            or "regime_gap_bridge" in model_names
        )
        reentry_allowed = (
            bool(block_reasons)
            and maturity_score >= 82.0
            and cross_passed >= 7
            and strong_full_history
            and recovery_signal
            and not (previous_guard and not previous_guard.get("passed"))
        )
        if block_reasons and not reentry_allowed:
            row["_recent_failure_front_blocked"] = True
            row["score"] = round(float(row.get("score", 0.0) or 0.0) * 0.38, 6)
            row["confidence_index"] = round(min(float(row.get("confidence_index", 0.0) or 0.0), 64.0), 3)
            row["top9_core"] = False
            reason_text = "近期失準硬守門未通過，禁止進入九碼核心"
            if reason_text not in reasons:
                reasons.insert(0, reason_text)
            row["reasons"] = reasons[:8]
            blocked.append({"number": number, "reasons": block_reasons})
        else:
            row["_recent_failure_front_blocked"] = False
            if block_reasons and reentry_allowed:
                reason_text = "近期失準號已通過全歷史與成熟度重驗"
                if reason_text not in reasons:
                    reasons.insert(0, reason_text)
                row["reasons"] = reasons[:8]
                revalidated.append({"number": number, "reasons": block_reasons})
        row["recent_failure_front_gate"] = {
            "blocked": bool(block_reasons and not reentry_allowed),
            "revalidated": bool(block_reasons and reentry_allowed),
            "reasons": block_reasons,
            "required": "成熟度82以上、交叉驗算7項以上、全歷史支撐、回收訊號同時成立",
        }
        adjusted.append(row)
    adjusted.sort(
        key=lambda row: (
            0 if row.get("_recent_failure_front_blocked") else 1,
            float(row.get("score", 0.0) or 0.0),
            float(row.get("confidence_index", 0.0) or 0.0),
            -int(row["number"]),
        ),
        reverse=True,
    )
    for rank, row in enumerate(adjusted, 1):
        blocked_row = bool(row.pop("_recent_failure_front_blocked", False))
        row["rank"] = rank
        row["top9_core"] = rank <= front_limit and not blocked_row
    return adjusted, {
        "status": "enforced",
        "policy": "近期失準、連續落空、上期回鍋未過號碼不得進入九碼核心，除非完成全歷史與成熟度重驗。",
        "front_limit": front_limit,
        "blocked_numbers": [item["number"] for item in blocked],
        "blocked_detail": blocked,
        "revalidated_numbers": [item["number"] for item in revalidated],
        "revalidated_detail": revalidated,
    }


def multi_model_correction_weights(review=None):
    rolling = rolling_adjustment_data(review)
    recent = rolling.get("recent_performance") or {}
    leak_active = bool(post9_hit_leak_audit(review).get("active"))
    critical = bool(
        review
        and (
            review.get("severity") == "critical"
            or recent.get("critical_slump")
            or float(recent.get("last5_top10_avg", 99) or 99) < 1.4
            or float(recent.get("last5_top15_avg", 99) or 99) < 1.8
        )
    )
    if critical or leak_active:
        weights = {
            "failure_corrector": 0.18,
            "walk_forward_signature": 0.15,
            "omission_recovery": 0.16,
            "regime_gap_bridge": 0.12,
            "similar_history_knn": 0.10,
            "omission_phase": 0.10,
            "cross_validation": 0.11,
            "maturity": 0.09,
            "tail_zone_balance": 0.06,
            "raw_score": 0.02,
            "frontload": 0.01,
        }
    else:
        weights = {
            "cross_validation": 0.16,
            "maturity": 0.14,
            "walk_forward_signature": 0.12,
            "omission_recovery": 0.13,
            "regime_gap_bridge": 0.11,
            "similar_history_knn": 0.10,
            "omission_phase": 0.09,
            "failure_corrector": 0.09,
            "tail_zone_balance": 0.08,
            "raw_score": 0.04,
            "frontload": 0.01,
        }
    total = sum(weights.values()) or 1.0
    return {name: value / total for name, value in weights.items()}, critical


def correction_count_map(rows, count_key):
    output = {}
    for item in rows or []:
        number = item.get("number")
        if number is None:
            continue
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        output[number] = max(output.get(number, 0), int(item.get(count_key, 0) or 0))
    return output


def apply_multi_model_correction_tournament(candidates, review=None, front_limit=9):
    if not candidates:
        return candidates, {"status": "略過", "reason": "沒有候選號"}

    review = review or {}
    rolling = rolling_adjustment_data(review)
    recent = rolling.get("recent_performance") or {}
    drift_diagnosis = rank_window_drift_diagnosis(review)
    drift_active = bool(drift_diagnosis.get("active"))
    post9_leak = post9_hit_leak_audit(review)
    leak_active = bool(post9_leak.get("active"))
    variant_weights, critical = multi_model_correction_weights(review)
    variants = list(variant_weights)
    original_rank = {int(item["number"]): idx for idx, item in enumerate(candidates, 1)}
    failed = failed_number_set(review)
    previous = previous_prediction_set(review)
    latest_actual = {
        int(number)
        for number in (review.get("last_settled") or {}).get("actual_numbers", [])
        if NUMBER_MIN <= int(number) <= NUMBER_MAX
    }
    last_candidates = [
        int(number)
        for number in (review.get("last_settled") or {}).get("candidate_numbers", [])
        if NUMBER_MIN <= int(number) <= NUMBER_MAX
    ]
    last_failed_top9 = set(last_candidates[:9]) - latest_actual
    repeated_failed = correction_count_map(rolling.get("repeated_failed_numbers"), "miss_count")
    late_hit_counts = correction_count_map(rolling.get("late_hit_numbers"), "late_hit_count")
    missed_actual_counts = correction_count_map(rolling.get("missed_actual_numbers"), "missed_count")
    last2_missed_counts = correction_count_map(rolling.get("last2_missed_actual_numbers"), "missed_count")
    last2_failed_top10 = correction_count_map(rolling.get("last2_failed_top10_numbers"), "miss_count")

    variant_scores = {
        variant: {
            int(item["number"]): precision_variant_item_score(item, variant, review)
            for item in candidates
        }
        for variant in variants
    }
    variant_rank_points = {}
    total_candidates = max(1, len(candidates))
    for variant, scores in variant_scores.items():
        ranked = sorted(scores, key=lambda number: (scores[number], -number), reverse=True)
        variant_rank_points[variant] = {
            number: 1.0 - ((idx - 1) / total_candidates)
            for idx, number in enumerate(ranked, 1)
        }

    adjusted = []
    for item in candidates:
        row = dict(item)
        number = int(row["number"])
        maturity = row.get("practical_maturity") or {}
        cross = row.get("cross_validation") or {}
        cross_total = max(1, int(cross.get("total_count", 0) or 0))
        cross_norm = clamp(int(cross.get("passed_count", 0) or 0) / cross_total, 0.0, 1.0)
        maturity_norm = clamp(float(maturity.get("score", 0) or 0) / 100, 0.0, 1.0)
        stability_norm = clamp(int(row.get("stability_count", 0) or 0) / 5, 0.0, 1.0)
        base = clamp(float(row.get("score", 0) or 0), 0.0, 1.0)

        consensus = 0.0
        model_detail = []
        for variant in variants:
            score = clamp(variant_scores[variant].get(number, 0.0), -0.35, 1.0)
            rank_point = variant_rank_points[variant].get(number, 0.0)
            value = clamp(score, 0.0, 1.0) * 0.66 + rank_point * 0.34
            consensus += variant_weights[variant] * value
            model_detail.append(
                {
                    "model": variant,
                    "label": PRECISION_VARIANT_LABELS.get(variant, variant),
                    "score": round(score, 4),
                    "rank_point": round(rank_point, 4),
                    "weight": round(variant_weights[variant], 4),
                    "weighted": round(variant_weights[variant] * value, 4),
                }
            )

        recovery_bonus = 0.0
        recovery_reasons = []
        feature_signals = row.get("feature_signals") or {}
        drift_signal = float(feature_signals.get("rank_window_drift_correction", 0) or 0)
        effective_signal = float(feature_signals.get("effective_hit_front_shift", 0) or 0)
        walk_signal = float(feature_signals.get("walk_forward_hit_signature", 0) or 0)
        external_signal = float(feature_signals.get("external_method_consensus", 0) or 0)
        if number in late_hit_counts:
            bonus = min(0.11, 0.045 + late_hit_counts[number] * 0.018)
            recovery_bonus += bonus
            recovery_reasons.append("第十到第十五名命中回收")
        if number in missed_actual_counts:
            bonus = min(0.12, 0.035 + missed_actual_counts[number] * 0.014)
            recovery_bonus += bonus
            recovery_reasons.append("漏抓實開號月度回收")
        if number in last2_missed_counts:
            bonus = min(0.10, 0.055 + last2_missed_counts[number] * 0.022)
            recovery_bonus += bonus
            recovery_reasons.append("近兩期漏抓立即補位")
        if drift_active and drift_signal >= 0.52 and number not in latest_actual:
            bonus = min(0.17, 0.055 + drift_signal * 0.12)
            recovery_bonus += bonus
            recovery_reasons.append("前九與前十五錯位修正")
        if (leak_active or critical) and effective_signal >= 0.50 and number not in latest_actual:
            bonus = min(0.18, 0.055 + effective_signal * 0.13)
            recovery_bonus += bonus
            recovery_reasons.append("有效命中前移")
        if (leak_active or critical) and walk_signal >= 0.56 and number not in latest_actual:
            bonus = min(0.19, 0.05 + walk_signal * 0.14)
            recovery_bonus += bonus
            recovery_reasons.append("滾動命中指紋前移")
        if (leak_active or critical) and external_signal >= 0.58 and number not in latest_actual:
            bonus = min(0.16, 0.045 + external_signal * 0.12)
            recovery_bonus += bonus
            recovery_reasons.append("外部方法共識前移")

        failure_penalty = 0.0
        penalty_reasons = []
        if number in failed:
            failure_penalty += 0.08
            penalty_reasons.append("近期落空降權")
        if number in repeated_failed:
            failure_penalty += min(0.24, 0.09 + repeated_failed[number] * 0.008)
            penalty_reasons.append("連續落空淘汰")
        if number in last_failed_top9:
            failure_penalty += 0.16 if drift_active else 0.10
            penalty_reasons.append("上期前九落空隔離")
        if number in last2_failed_top10:
            failure_penalty += min(0.24 if drift_active else 0.16, 0.07 + last2_failed_top10[number] * 0.035)
            penalty_reasons.append("近兩期前十落空")
        if number in previous and row.get("previous_prediction_guard") and not row["previous_prediction_guard"].get("passed"):
            failure_penalty += 0.08
            penalty_reasons.append("上期回鍋未重驗")

        firewall = row.get("recent_draw_firewall") or {}
        firewall_blocked = bool(firewall.get("blocked"))
        firewall_penalty = 0.50 if firewall_blocked else 0.0
        if firewall_blocked:
            penalty_reasons.append("剛開出號硬防火牆")
        failure_front = row.get("recent_failure_front_gate") or {}
        failure_front_blocked = bool(failure_front.get("blocked"))
        if failure_front_blocked:
            failure_penalty += 0.28
            penalty_reasons.append("近期失準守門未過")

        if recovery_reasons and not firewall_blocked:
            failure_penalty *= 0.55

        corrected = (
            base * (0.18 if critical else 0.26)
            + consensus * (0.56 if critical else 0.48)
            + maturity_norm * 0.10
            + cross_norm * 0.08
            + stability_norm * 0.08
            + walk_signal * (0.08 if critical else 0.04)
            + recovery_bonus
            - failure_penalty
            - firewall_penalty
        )
        if int(cross.get("passed_count", 0) or 0) < 4 and float(maturity.get("score", 0) or 0) < 70:
            corrected = min(corrected, 0.68)
            penalty_reasons.append("交叉驗算與成熟度不足限高")
        corrected = round(clamp(corrected, 0.0, 1.0), 5)

        reasons = list(row.get("reasons") or [])
        insert_reason = "失準後多模型競賽重排" if critical else "多模型競賽校正"
        if insert_reason not in reasons:
            reasons.insert(0, insert_reason)
        for reason in recovery_reasons + penalty_reasons:
            if reason not in reasons:
                reasons.append(reason)
        row["reasons"] = reasons[:8]
        row["multi_model_correction"] = {
            "status": "已執行",
            "corrected_score": corrected,
            "base_score": round(base, 5),
            "consensus_score": round(consensus, 5),
            "recovery_bonus": round(recovery_bonus, 5),
            "failure_penalty": round(failure_penalty, 5),
            "firewall_penalty": round(firewall_penalty, 5),
            "effective_hit_front_shift": round(effective_signal, 4),
            "walk_forward_hit_signature": round(walk_signal, 4),
            "external_method_consensus": round(external_signal, 4),
            "rank_window_drift_signal": round(drift_signal, 4),
            "recovery_reasons": recovery_reasons,
            "penalty_reasons": penalty_reasons,
            "model_detail": sorted(model_detail, key=lambda detail: detail["weighted"], reverse=True)[:5],
        }
        sources = list(row.get("model_sources") or [])
        sources.insert(
            0,
            {
                "model": "multi_model_correction",
                "label": "多模型競賽校正",
                "signal": corrected,
                "weight": 1.0,
                "contribution": corrected,
            },
        )
        row["model_sources"] = sources[:9]
        row["score"] = corrected
        row["confidence_index"] = round(50 + corrected * 49, 1)
        row["model_probability_percent"] = conservative_probability_percent(corrected)
        row["_correction_blocked"] = firewall_blocked or failure_front_blocked or corrected <= 0.08
        row["_reserve_recovery"] = bool(
            10 <= original_rank.get(number, 99) <= (24 if (leak_active or effective_signal >= 0.45 or walk_signal >= 0.56) else 18 if drift_active else 15)
            and recovery_reasons
            and not row["_correction_blocked"]
            and float(maturity.get("score", 0) or 0) >= (48 if (leak_active or effective_signal >= 0.45 or walk_signal >= 0.56) else 54 if drift_active else 58)
        )
        adjusted.append(row)

    adjusted.sort(
        key=lambda row: (
            0 if row.get("_correction_blocked") else 1,
            float(row.get("score", 0) or 0),
            float(row.get("confidence_index", 0) or 0),
            int((row.get("cross_validation") or {}).get("passed_count", 0) or 0),
            -int(row["number"]),
        ),
        reverse=True,
    )

    forced_promoted = []
    if critical:
        front = adjusted[:front_limit]
        reserve = [
            row
            for row in adjusted[front_limit:]
            if row.get("_reserve_recovery") and int(row["number"]) not in {int(item["number"]) for item in front}
        ]
        max_promotions = int(drift_diagnosis.get("reserve_slots", 0) or 0) if (drift_active or leak_active) else 2
        max_promotions = max(3 if leak_active else 2, min(4, max_promotions))
        for promoted in reserve[:max_promotions]:
            removable = [
                row for row in front
                if not (row.get("multi_model_correction") or {}).get("recovery_reasons")
                and original_rank.get(int(row["number"]), 99) <= 9
            ]
            if not removable:
                break
            weakest = min(removable, key=lambda row: (float(row.get("score", 0) or 0), -original_rank.get(int(row["number"]), 99)))
            allowed_gap = 0.18 if leak_active else 0.14 if drift_active else 0.05
            if float(promoted.get("score", 0) or 0) + allowed_gap < float(weakest.get("score", 0) or 0):
                continue
            front[front.index(weakest)] = promoted
            forced_promoted.append({"number": int(promoted["number"]), "replaced": int(weakest["number"])})
        if forced_promoted:
            front_numbers = {int(row["number"]) for row in front}
            adjusted = front + [row for row in adjusted if int(row["number"]) not in front_numbers]

    for rank, row in enumerate(adjusted, 1):
        blocked = bool(row.pop("_correction_blocked", False))
        row.pop("_reserve_recovery", None)
        row["rank"] = rank
        row["top9_core"] = rank <= front_limit and not blocked
        if rank <= front_limit and not blocked:
            reasons = list(row.get("reasons") or [])
            if "九碼核心重排通過" not in reasons:
                reasons.append("九碼核心重排通過")
            row["reasons"] = reasons[:8]

    old_top9 = {number for number, rank in original_rank.items() if rank <= front_limit}
    new_top9 = {int(item["number"]) for item in adjusted[:front_limit]}
    return adjusted, {
        "status": "已執行",
        "policy": "原排序達標不足時立即啟動多模型競賽，弱模型降權、漏抓與後段命中模型前移、剛開出與連續落空號硬隔離。",
        "critical_mode": critical,
        "recent_top10_avg": recent.get("last5_top10_avg"),
        "recent_top15_avg": recent.get("last5_top15_avg"),
        "variant_weights": {PRECISION_VARIANT_LABELS.get(name, name): round(value, 4) for name, value in variant_weights.items()},
        "old_top9": sorted(old_top9),
        "new_top9": [int(item["number"]) for item in adjusted[:front_limit]],
        "promoted_to_top9": sorted(new_top9 - old_top9),
        "demoted_from_top9": sorted(old_top9 - new_top9),
        "forced_reserve_recovery": forced_promoted,
        "rank_window_drift_correction": drift_diagnosis,
        "post9_hit_leak_audit": post9_leak,
        "blocked_numbers": [
            int(item["number"])
            for item in adjusted
            if (item.get("recent_draw_firewall") or {}).get("blocked")
            or (item.get("recent_failure_front_gate") or {}).get("blocked")
        ][:15],
        "message": "排序已完成自動換模型校正，後續強牌與戰報全部使用本次重排結果。",
    }


def apply_full_system_entry_gate(
    candidates,
    draws,
    review=None,
    backtest_result=None,
    pack_governance=None,
    precision_tournament=None,
    correction=None,
    front_limit=9,
):
    if not candidates:
        return candidates, {"status": "略過", "reason": "沒有候選號"}

    review = review or {}
    backtest_result = backtest_result or {}
    pack_governance = pack_governance or {}
    precision_tournament = precision_tournament or {}
    correction = correction or {}

    top10_avg = float(backtest_result.get("top10_avg_hits", 0) or 0)
    random_top10 = float(backtest_result.get("random_top10_expectation", DRAW_SIZE * 10 / NUMBER_MAX) or 0)
    edge = top10_avg - random_top10
    top15_avg = float(backtest_result.get("top15_avg_hits", 0) or 0)
    random_top15 = DRAW_SIZE * 15 / NUMBER_MAX
    top15_edge = top15_avg - random_top15
    rounds = int(backtest_result.get("rounds", 0) or 0)
    rolling = backtest_result.get("rolling_windows") or {}
    window_edges = []
    for window in ("60", "120"):
        value = (rolling.get(window) or {}).get("top10_edge_vs_random")
        if value is not None:
            window_edges.append(float(value))

    global_checks = {
        "全歷史主回測": {
            "passed": rounds >= 20 and edge >= 0,
            "evidence": f"回測 {rounds} 輪，前十平均 {round(top10_avg, 3)}，隨機基準 {round(random_top10, 3)}，優勢 {round(edge, 4)}",
        },
        "近況分段回測": {
            "passed": bool(window_edges) and all(value >= 0 for value in window_edges),
            "evidence": "、".join(f"{round(value, 4)}" for value in window_edges) or "沒有分段資料",
        },
        "多模型校正": {
            "passed": correction.get("status") == "已執行",
            "evidence": correction.get("message", "多模型校正未寫入"),
        },
        "強牌治理": {
            "passed": pack_governance.get("status") in {"evaluated", "已檢核"} or bool(pack_governance.get("pack_stats")),
            "evidence": f"可用組數 {pack_governance.get('allowed_pack_count', 0)}，研究組數 {pack_governance.get('research_allowed_pack_count', 0)}",
        },
        "精算小牌競賽": {
            "passed": precision_tournament.get("status") in {"evaluated", "已檢核"} or bool(precision_tournament.get("selected_models")),
            "evidence": f"回測輪數 {precision_tournament.get('rounds', 0)}",
        },
    }
    strict_global_passed = all(item["passed"] for item in global_checks.values())
    mode = slump_mode(review)
    drift = rank_window_drift_diagnosis(review)
    post9_leak = post9_hit_leak_audit(review)
    leak_active = bool(post9_leak.get("active"))
    window_recovery_ok = bool(window_edges) and min(window_edges) >= -0.22
    system_prerequisites_passed = all(
        global_checks[name]["passed"]
        for name in ["多模型校正", "強牌治理", "精算小牌競賽"]
    )
    slump_recovery_ready = (
        mode in {"warning", "critical"}
        and system_prerequisites_passed
        and rounds >= 20
        and edge >= -0.18
        and window_recovery_ok
        and (
            top15_edge >= -0.10
            or bool(drift.get("active"))
            or leak_active
            or (top15_avg - top10_avg) >= 0.45
        )
    )
    global_checks["低迷重整放行"] = {
        "passed": slump_recovery_ready,
        "evidence": (
            f"模式 {mode}，前十優勢 {round(edge, 4)}，前十五優勢 {round(top15_edge, 4)}，"
            f"錯位修正 {'啟動' if drift.get('active') else '未啟動'}，"
            f"九名後外漏 {'啟動' if leak_active else '觀察'}"
        ),
    }
    global_passed = strict_global_passed
    global_ready = strict_global_passed or slump_recovery_ready

    latest_actual = {
        int(number)
        for number in (review.get("last_settled") or {}).get("actual_numbers", [])
        if NUMBER_MIN <= int(number) <= NUMBER_MAX
    }
    failed = failed_number_set(review)
    previous = previous_prediction_set(review)

    adjusted = []
    for original_index, item in enumerate(candidates, 1):
        row = dict(item)
        number = int(row["number"])
        correction_detail = row.get("multi_model_correction") or {}
        model_detail = correction_detail.get("model_detail") or []
        cross = row.get("cross_validation") or {}
        maturity = row.get("practical_maturity") or {}
        firewall = row.get("recent_draw_firewall") or {}
        failure_front = row.get("recent_failure_front_gate") or {}
        previous_guard = row.get("previous_prediction_guard") or {}

        score = float(row.get("score", 0) or 0)
        confidence = float(row.get("confidence_index", 0) or 0)
        stability = int(row.get("stability_count", 0) or 0)
        cross_passed = int(cross.get("passed_count", 0) or 0)
        maturity_score = float(maturity.get("score", 0) or 0)
        model_count = len(model_detail)
        recovery_count = len(correction_detail.get("recovery_reasons") or [])
        penalty_count = len(correction_detail.get("penalty_reasons") or [])
        feature_signals = row.get("feature_signals") or {}
        drift_signal = float(feature_signals.get("rank_window_drift_correction", 0) or 0)
        effective_signal = float(feature_signals.get("effective_hit_front_shift", 0) or 0)
        walk_signal = float(feature_signals.get("walk_forward_hit_signature", 0) or 0)
        external_signal = float(feature_signals.get("external_method_consensus", 0) or 0)
        hard_blocked = bool(firewall.get("blocked")) or bool(failure_front.get("blocked"))
        reentry_ok = not previous_guard.get("reentry_required") or bool(previous_guard.get("reentry_passed"))
        not_unverified_repeat = number not in previous or reentry_ok
        not_latest_repeat = number not in latest_actual or bool((row.get("repeat_guard") or {}).get("passed"))

        checks = [
            ("全歷史回測或低迷重整達標", global_checks["全歷史主回測"]["passed"] or slump_recovery_ready),
            ("近況回測或錯位重整達標", global_checks["近況分段回測"]["passed"] or slump_recovery_ready),
            ("多模型校正完成", correction_detail.get("status") == "已執行" and model_count >= 3),
            ("強牌治理完成", global_checks["強牌治理"]["passed"]),
            ("精算小牌回測完成", global_checks["精算小牌競賽"]["passed"]),
            ("剛開出防火牆通過", not bool(firewall.get("blocked")) and not_latest_repeat),
            ("近期失準守門通過", not bool(failure_front.get("blocked"))),
            ("上期預測重驗通過", not_unverified_repeat),
        ]
        core_checks = checks + [
            ("分數核心門檻", score >= 0.60),
            ("信心核心門檻", confidence >= 82),
            ("交叉驗算核心門檻", cross_passed >= 3),
            ("穩定核心門檻", stability >= 3),
            ("成熟核心門檻", maturity_score >= 58),
        ]
        main_revalidation_passed = (
            not bool(failure_front.get("blocked"))
            or (
                score >= 0.38
                and confidence >= 68
                and cross_passed >= 5
                and maturity_score >= 60
                and stability >= 1
            )
            or (
                score >= 0.41
                and confidence >= 70
                and cross_passed >= 4
                and maturity_score >= 68
            )
        )
        coverage_base_checks = [
            item for item in checks
            if item[0] != "近期失準守門通過"
        ] + [
            ("近期失準主列重驗", main_revalidation_passed),
        ]
        coverage_checks = coverage_base_checks + [
            ("分數補位門檻", score >= 0.34),
            ("信心補位門檻", confidence >= 66),
            ("多模組補位門檻", model_count >= 3),
            ("穩定補位門檻", stability >= 1),
            ("交叉或回收證據", cross_passed >= 1 or recovery_count >= 1 or drift_signal >= 0.52 or effective_signal >= 0.50 or walk_signal >= 0.56 or external_signal >= 0.58 or stability >= 2),
        ]
        reserve_failure_revalidated = (
            not bool(failure_front.get("blocked"))
            or (cross_passed >= 4 and (maturity_score >= 44 or stability >= 3))
            or (score >= 0.08 and stability >= 3 and maturity_score >= 45)
        )
        reserve_signal_passed = (
            score >= 0.08
            and confidence >= 54
            and (cross_passed >= 1 or stability >= 2 or maturity_score >= 45 or drift_signal >= 0.52 or effective_signal >= 0.48 or walk_signal >= 0.54 or external_signal >= 0.56)
        ) or (
            cross_passed >= 4
            and maturity_score >= 44
        )
        reserve_base_checks = [
            item for item in checks
            if item[0] != "近期失準守門通過"
        ] + [
            ("近期失準備查重驗", reserve_failure_revalidated),
        ]
        reserve_checks = reserve_base_checks + [
            ("備查分數或強驗算門檻", reserve_signal_passed),
            ("備查信心門檻", confidence >= 54 or cross_passed >= 4),
            ("備查觀察證據", cross_passed >= 1 or maturity_score >= 44 or stability >= 2 or recovery_count >= 1 or drift_signal >= 0.52 or effective_signal >= 0.48 or walk_signal >= 0.54 or external_signal >= 0.56),
        ]

        slump_recovery_item_passed = (
            slump_recovery_ready
            and score >= 0.30
            and confidence >= 62
            and model_count >= 3
            and stability >= 1
            and (cross_passed >= 1 or recovery_count >= 1 or drift_signal >= 0.48 or effective_signal >= 0.45 or walk_signal >= 0.54 or external_signal >= 0.56 or maturity_score >= 58)
            and not bool(firewall.get("blocked"))
            and not bool(failure_front.get("blocked"))
        )

        core_passed = global_ready and not hard_blocked and all(passed for _, passed in core_checks)
        coverage_passed = (
            global_ready
            and not bool(firewall.get("blocked"))
            and (all(passed for _, passed in coverage_checks) or slump_recovery_item_passed)
        )
        reserve_passed = (
            global_ready
            and not bool(firewall.get("blocked"))
            and (all(passed for _, passed in reserve_checks) or slump_recovery_item_passed)
        )

        if core_passed:
            tier = "核心通過" if strict_global_passed else "低迷重整主列通過"
            tier_order = 3 if strict_global_passed else 2
            passed_for_main = True
            high_confidence_allowed = strict_global_passed
        elif coverage_passed:
            if slump_recovery_item_passed and not strict_global_passed:
                tier = "低迷重整主列通過"
            else:
                tier = "主列重驗通過" if bool(failure_front.get("blocked")) else "主列補位通過"
            tier_order = 2
            passed_for_main = True
            high_confidence_allowed = False
        elif reserve_passed:
            tier = "備查重驗通過" if bool(failure_front.get("blocked")) else "備查通過"
            tier_order = 1
            passed_for_main = False
            high_confidence_allowed = False
        else:
            tier = "未達標不列入"
            tier_order = 0
            passed_for_main = False
            high_confidence_allowed = False

        if tier == "核心通過":
            validation_checks = core_checks
        elif tier in {"主列補位通過", "主列重驗通過", "低迷重整主列通過"}:
            validation_checks = coverage_checks
        elif tier in {"備查通過", "備查重驗通過"}:
            validation_checks = reserve_checks
        else:
            validation_checks = core_checks
        failed_checks = [name for name, passed in validation_checks if not passed]
        evidence = {
            "分數": round(score, 5),
            "信心": round(confidence, 1),
            "交叉驗算": f"{cross_passed}/{cross.get('total_count', '-')}",
            "穩定層數": stability,
            "成熟度": round(maturity_score, 1),
            "多模型數": model_count,
            "回收證據": recovery_count,
            "降權證據": penalty_count,
            "錯位修正": round(drift_signal, 4),
            "有效命中前移": round(effective_signal, 4),
            "滾動命中指紋": round(walk_signal, 4),
            "外部方法共識": round(external_signal, 4),
            "低迷重整": slump_recovery_item_passed,
        }
        row["entry_validation"] = {
            "status": tier,
            "status_label": tier,
            "passed_for_main": passed_for_main,
            "high_confidence_allowed": high_confidence_allowed,
            "tier_order": tier_order,
            "global_passed": global_passed,
            "global_ready": global_ready,
            "slump_recovery_ready": slump_recovery_ready,
            "global_checks": global_checks,
            "evidence": evidence,
            "failed_checks": failed_checks[:8],
            "policy": "每顆號碼必須通過全歷史回測、近況回測、多模型校正、強牌治理、精算小牌競賽、剛開出防火牆、近期失準守門與上期重驗，才可列入前九主列。",
        }
        reasons = list(row.get("reasons") or [])
        if passed_for_main:
            marker = "全系統主列放行通過"
        elif reserve_passed:
            marker = "全系統備查通過不列主推"
        else:
            marker = "未達全系統主列門降觀察"
        if marker not in reasons:
            reasons.insert(0, marker)
        row["reasons"] = reasons[:9]
        row["_entry_tier_order"] = tier_order
        row["_entry_original_index"] = original_index
        adjusted.append(row)

    adjusted.sort(
        key=lambda row: (
            int(row.get("_entry_tier_order", 0) or 0),
            float(row.get("score", 0) or 0),
            float(row.get("confidence_index", 0) or 0),
            int(row.get("stability_count", 0) or 0),
            int((row.get("cross_validation") or {}).get("passed_count", 0) or 0),
            -int(row["number"]),
        ),
        reverse=True,
    )

    for rank, row in enumerate(adjusted, 1):
        row.pop("_entry_tier_order", None)
        row.pop("_entry_original_index", None)
        validation = row.get("entry_validation") or {}
        passed_main = bool(validation.get("passed_for_main")) and rank <= front_limit
        row["rank"] = rank
        row["top9_core"] = passed_main
        validation["top9_released"] = passed_main
        if passed_main:
            reasons = list(row.get("reasons") or [])
            if "全系統前九列入" not in reasons:
                reasons.append("全系統前九列入")
            row["reasons"] = reasons[:9]
        row["entry_validation"] = validation

    main_numbers = [int(item["number"]) for item in adjusted[:front_limit] if (item.get("entry_validation") or {}).get("passed_for_main")]
    core_numbers = [
        int(item["number"])
        for item in adjusted
        if (item.get("entry_validation") or {}).get("status") == "核心通過"
    ][:front_limit]
    coverage_numbers = [
        int(item["number"])
        for item in adjusted
        if (item.get("entry_validation") or {}).get("status") in {"主列補位通過", "主列重驗通過"}
    ][:front_limit]
    reserve_numbers = [
        int(item["number"])
        for item in adjusted
        if (item.get("entry_validation") or {}).get("status") in {"備查通過", "備查重驗通過"}
    ][:15]
    blocked_numbers = [
        int(item["number"])
        for item in adjusted
        if not (item.get("entry_validation") or {}).get("passed_for_main")
        and (item.get("entry_validation") or {}).get("status") not in {"備查通過", "備查重驗通過"}
    ][:15]

    status = "已執行" if len(main_numbers) >= front_limit and global_ready else "未達主列滿額"
    return adjusted, {
        "status": status,
        "policy": "必須多模組全系統檢測與回測達標才可列入前九主列；未過者只能備查或觀察，強牌不得使用。",
        "front_limit": front_limit,
        "global_passed": global_passed,
        "global_ready": global_ready,
        "slump_recovery_ready": slump_recovery_ready,
        "slump_recovery_mode": mode,
        "slump_recovery_policy": "近期命中低迷時，若全歷史資料、校正流程與錯位修正已完成，允許列為低迷重整主列；不得標示為正式保證。",
        "post9_hit_leak_audit": post9_leak,
        "global_checks": global_checks,
        "main_count": len(main_numbers),
        "main_numbers": main_numbers,
        "core_passed_numbers": core_numbers,
        "coverage_passed_numbers": coverage_numbers,
        "reserve_numbers": reserve_numbers,
        "blocked_numbers": blocked_numbers,
        "failed_numbers_from_previous_review": sorted(failed),
        "previous_prediction_numbers": sorted(previous),
        "message": "主列放行門已套用於候選排序、強牌組合、精算小牌與戰報顯示。",
    }


def apply_slump_emergency_front_rebuild(candidates, draws, review=None, front_limit=9):
    if not candidates:
        return candidates, {"status": "略過", "reason": "沒有候選號"}
    review = review or {}
    rolling = rolling_adjustment_data(review)
    recent = rolling.get("recent_performance") or {}
    leak_audit = post9_hit_leak_audit(review)
    mode = slump_mode(review)
    critical = bool(
        mode == "critical"
        or leak_audit.get("active")
        or float(recent.get("last5_top10_avg", 99) or 99) < 1.35
        or float(recent.get("last5_top15_avg", 99) or 99) < 1.75
    )
    if not critical:
        return candidates, {
            "status": "略過",
            "reason": "近期未觸發嚴重失準前九重建",
            "old_top9": [int(item["number"]) for item in candidates[:front_limit]],
            "new_top9": [int(item["number"]) for item in candidates[:front_limit]],
        }

    original_rank = {int(item["number"]): idx for idx, item in enumerate(candidates, 1)}
    old_top9 = [int(item["number"]) for item in candidates[:front_limit]]
    latest_actual = {
        int(number)
        for number in (review.get("last_settled") or {}).get("actual_numbers", [])
        if NUMBER_MIN <= int(number) <= NUMBER_MAX
    }
    failed = failed_number_set(review)
    previous = previous_prediction_set(review)
    repeated_failed = correction_count_map(rolling.get("repeated_failed_numbers"), "miss_count")
    late_hit_counts = correction_count_map(rolling.get("late_hit_numbers"), "late_hit_count")
    missed_actual_counts = correction_count_map(rolling.get("missed_actual_numbers"), "missed_count")
    last2_missed_counts = correction_count_map(rolling.get("last2_missed_actual_numbers"), "missed_count")
    low_error_numbers = set(low_probability_error_number_map(review))

    adjusted = []
    for item in candidates:
        row = dict(item)
        number = int(row["number"])
        feature_signals = row.get("feature_signals") or {}
        validation = dict(row.get("entry_validation") or {})
        correction = row.get("multi_model_correction") or {}
        cross = row.get("cross_validation") or {}
        maturity = row.get("practical_maturity") or {}
        firewall = row.get("recent_draw_firewall") or {}
        failure_front = row.get("recent_failure_front_gate") or {}
        previous_guard = row.get("previous_prediction_guard") or {}

        base = clamp(float(row.get("score", 0) or 0), 0.0, 1.0)
        confidence_norm = clamp((float(row.get("confidence_index", 50) or 50) - 50) / 49, 0.0, 1.0)
        cross_norm = clamp(int(cross.get("passed_count", 0) or 0) / max(1, int(cross.get("total_count", 1) or 1)), 0.0, 1.0)
        maturity_norm = clamp(float(maturity.get("score", 0) or 0) / 100, 0.0, 1.0)
        stability_norm = clamp(int(row.get("stability_count", 0) or 0) / 5, 0.0, 1.0)
        drift = float(feature_signals.get("rank_window_drift_correction", 0) or 0)
        effective = float(feature_signals.get("effective_hit_front_shift", 0) or 0)
        low_error = float(feature_signals.get("low_probability_error_recovery", 0) or 0)
        walk = float(feature_signals.get("walk_forward_hit_signature", 0) or 0)
        external = float(feature_signals.get("external_method_consensus", 0) or 0)
        omission_phase = float(feature_signals.get("omission_phase_rebound", 0) or 0)
        positive_core = float(feature_signals.get("positive_edge_core", 0) or 0)
        recovery_reasons = correction.get("recovery_reasons") or []

        emergency_score = (
            base * 0.18
            + confidence_norm * 0.07
            + cross_norm * 0.08
            + maturity_norm * 0.08
            + stability_norm * 0.06
            + walk * 0.21
            + effective * 0.16
            + drift * 0.12
            + low_error * 0.12
            + external * 0.11
            + omission_phase * 0.06
            + positive_core * 0.08
        )
        if number in late_hit_counts:
            emergency_score += min(0.16, 0.07 + late_hit_counts[number] * 0.025)
        if number in missed_actual_counts:
            emergency_score += min(0.15, 0.055 + missed_actual_counts[number] * 0.022)
        if number in last2_missed_counts:
            emergency_score += min(0.13, 0.07 + last2_missed_counts[number] * 0.03)
        if number in low_error_numbers:
            emergency_score += 0.12
        if recovery_reasons:
            emergency_score += min(0.10, len(recovery_reasons) * 0.035)

        firewall_blocked = bool(firewall.get("blocked"))
        repeat_blocked = number in latest_actual and not bool((row.get("repeat_guard") or {}).get("passed"))
        failure_blocked = bool(failure_front.get("blocked"))
        if number in failed and number not in late_hit_counts and number not in missed_actual_counts:
            emergency_score -= 0.12
        if number in repeated_failed and walk < 0.62 and effective < 0.56:
            emergency_score -= min(0.22, 0.08 + repeated_failed[number] * 0.018)
        if number in previous and previous_guard and not previous_guard.get("passed") and walk < 0.62:
            emergency_score -= 0.09
        if failure_blocked and walk < 0.60 and effective < 0.55:
            emergency_score -= 0.16
        if firewall_blocked or repeat_blocked:
            emergency_score -= 0.65

        emergency_score = round(clamp(emergency_score, 0.0, 1.0), 5)
        row["slump_emergency_rebuild_score"] = emergency_score
        row["_slump_emergency_blocked"] = firewall_blocked or repeat_blocked or emergency_score <= 0.05
        row["_slump_emergency_eligible"] = bool(
            not row["_slump_emergency_blocked"]
            and (
                validation.get("passed_for_main")
                or validation.get("status") in {"備查通過", "備查重驗通過", "主列補位通過", "主列重驗通過", "低迷重整主列通過"}
                or (
                    emergency_score >= 0.44
                    and (cross_norm >= 0.08 or maturity_norm >= 0.45 or walk >= 0.56 or effective >= 0.52)
                )
            )
        )
        sources = list(row.get("model_sources") or [])
        sources.insert(0, {
            "model": "slump_emergency_rebuild",
            "label": "失準急救前九重建",
            "signal": emergency_score,
            "weight": 1.0,
            "contribution": emergency_score,
        })
        row["model_sources"] = sources[:9]
        adjusted.append(row)

    adjusted.sort(
        key=lambda row: (
            1 if row.get("_slump_emergency_eligible") else 0,
            float(row.get("slump_emergency_rebuild_score", 0) or 0),
            float(row.get("score", 0) or 0),
            int((row.get("cross_validation") or {}).get("passed_count", 0) or 0),
            -int(row["number"]),
        ),
        reverse=True,
    )

    for rank, row in enumerate(adjusted, 1):
        number = int(row["number"])
        eligible = bool(row.pop("_slump_emergency_eligible", False))
        blocked = bool(row.pop("_slump_emergency_blocked", False))
        validation = dict(row.get("entry_validation") or {})
        row["rank"] = rank
        row["top9_core"] = bool(rank <= front_limit and eligible and not blocked)
        if row["top9_core"]:
            validation.update({
                "status": "失準急救主列通過" if validation.get("status") != "核心通過" else validation.get("status"),
                "status_label": "失準急救主列通過" if validation.get("status") != "核心通過" else validation.get("status_label", "核心通過"),
                "passed_for_main": True,
                "top9_released": True,
                "high_confidence_allowed": False,
                "slump_emergency_rebuild": True,
            })
            reasons = list(row.get("reasons") or [])
            for reason in ["失準急救前九重建", "全歷史滾動回放重驗"]:
                if reason not in reasons:
                    reasons.insert(0, reason)
            row["reasons"] = reasons[:9]
        else:
            validation["top9_released"] = False
        evidence = dict(validation.get("evidence") or {})
        evidence["失準急救分"] = row.get("slump_emergency_rebuild_score")
        validation["evidence"] = evidence
        row["entry_validation"] = validation

    new_top9 = [int(item["number"]) for item in adjusted[:front_limit]]
    return adjusted, {
        "status": "已執行",
        "policy": "嚴重失準或九名後外漏時，使用全歷史滾動回放、漏抓回收、後段命中回收與低機誤開回收重建前九。",
        "critical_mode": critical,
        "recent_top10_avg": recent.get("last5_top10_avg"),
        "recent_top15_avg": recent.get("last5_top15_avg"),
        "old_top9": old_top9,
        "new_top9": new_top9,
        "promoted_to_top9": sorted(set(new_top9) - set(old_top9)),
        "demoted_from_top9": sorted(set(old_top9) - set(new_top9)),
        "top_scores": [
            {
                "number": int(item["number"]),
                "score": item.get("slump_emergency_rebuild_score"),
                "walk_forward": (item.get("feature_signals") or {}).get("walk_forward_hit_signature"),
                "effective_front": (item.get("feature_signals") or {}).get("effective_hit_front_shift"),
            }
            for item in adjusted[:15]
        ],
        "message": "前九已依失準急救模型重新排序，後續強牌與戰報使用本結果。",
    }


def build_post_draw_error_correction_protocol(candidates, review=None, correction=None, gate=None, pack_governance=None):
    review = review or {}
    correction = correction or {}
    gate = gate or {}
    pack_governance = pack_governance or {}
    rolling = rolling_adjustment_data(review)
    settled = review.get("last_settled") or {}
    actual_numbers = [
        int(number)
        for number in settled.get("actual_numbers", [])
        if NUMBER_MIN <= int(number) <= NUMBER_MAX
    ]
    candidate_numbers = [
        int(number)
        for number in settled.get("candidate_numbers", [])
        if NUMBER_MIN <= int(number) <= NUMBER_MAX
    ]
    actual_set = set(actual_numbers)
    top9 = set(candidate_numbers[:9])
    top15 = set(candidate_numbers[:15])
    missed_top9 = sorted(actual_set - top9)
    missed_top15 = sorted(actual_set - top15)
    failed_top9 = sorted(top9 - actual_set)
    failed_top15 = sorted(top15 - actual_set)

    strong_pack_hits = settled.get("strong_pack_hits") or {}
    pack_failures = []
    for key, pack in strong_pack_hits.items():
        if not pack.get("passed"):
            pack_failures.append(
                {
                    "pack": key,
                    "numbers": pack.get("numbers") or [],
                    "hits": int(pack.get("hits", 0) or 0),
                    "action": "降權並改由本期多模型重新競賽",
                }
            )

    governance_rows = []
    for key, item in (pack_governance.get("pack_stats") or {}).items():
        governance_rows.append(
            {
                "pack": key,
                "best_variant": item.get("best_variant"),
                "passed": bool(item.get("passed")),
                "research_passed": bool(item.get("research_passed")),
                "avg_hits": item.get("avg_hits"),
                "pass_rate": item.get("pass_rate"),
                "action": "保留" if item.get("passed") or item.get("research_passed") else "降權觀察",
            }
        )

    module_actions = [
        {
            "module": "前九主列排序",
            "problem": f"上期前九落空 {len(failed_top9)} 顆，漏抓 {len(missed_top9)} 顆",
            "numbers": {"落空": failed_top9, "漏抓": missed_top9},
            "action": "落空號降權，漏抓號進入回收模型與主列重驗",
        },
        {
            "module": "第十到十五備查回收",
            "problem": f"上期前十五落空 {len(failed_top15)} 顆，前十五漏抓 {len(missed_top15)} 顆",
            "numbers": {"落空": failed_top15, "漏抓": missed_top15},
            "action": "備查命中模型保留，漏抓模型提高回收權重",
        },
        {
            "module": "強牌組合",
            "problem": f"未達標強牌 {len(pack_failures)} 組",
            "numbers": {"失準組合": pack_failures[:5]},
            "action": "未達標組合不升正式高信心，下一期重新選模型",
        },
        {
            "module": "多模型競賽",
            "problem": "每期開獎後重新計算模型權重",
            "numbers": correction.get("variant_weights") or {},
            "action": "弱模型降權，漏抓與後段命中模型加權",
        },
        {
            "module": "全系統主列放行",
            "problem": f"主列通過 {gate.get('main_count', 0)} 顆",
            "numbers": gate.get("main_numbers") or [],
            "action": "未通過放行門者只能備查或觀察，不能包裝主推",
        },
    ]
    return {
        "status": "已執行" if review.get("has_review") else "首次或無上期可檢討",
        "version": "post_draw_error_correction_v20260722",
        "per_draw_recompute_required": True,
        "rolling_adjustment_required": True,
        "rolling_recomputed": bool(rolling),
        "previous_prediction_reuse_forbidden": True,
        "fake_data_guard": {
            "status": "啟用",
            "requires_latest_draw": bool(actual_numbers),
            "requires_settled_review": bool(review.get("has_review")),
            "requires_full_system_gate": gate.get("status") == "已執行",
            "requires_no_previous_prediction_reuse": True,
        },
        "last_settled": {
            "based_on_date": settled.get("based_on_date"),
            "actual_date": settled.get("actual_date"),
            "actual_numbers": actual_numbers,
            "candidate_numbers": candidate_numbers[:15],
            "top5_hits": settled.get("top5_hits"),
            "top10_hits": settled.get("top10_hits"),
            "top15_hits": settled.get("top15_hits"),
        },
        "missed_actual_numbers": missed_top9,
        "missed_actual_top15_numbers": missed_top15,
        "failed_top9_numbers": failed_top9,
        "failed_top15_numbers": failed_top15,
        "repeated_failed_numbers": rolling.get("repeated_failed_numbers", [])[:15],
        "late_hit_numbers": rolling.get("late_hit_numbers", [])[:15],
        "last2_missed_actual_numbers": rolling.get("last2_missed_actual_numbers", [])[:15],
        "penalized_reasons": rolling.get("penalized_reasons", [])[:12],
        "boosted_reasons": rolling.get("boosted_reasons", [])[:12],
        "pack_failures": pack_failures,
        "pack_governance": governance_rows,
        "module_actions": module_actions,
        "message": "每期開獎後必須先檢討落空、漏抓、強牌失準與模型權重，再重新排序與重新放行。",
    }


def ensure_verified_strong_single_pack(packs, candidates, review=None):
    packs = packs or {}
    review = review or {}
    latest_actual = {
        int(number)
        for number in (review.get("last_settled") or {}).get("actual_numbers", [])
        if NUMBER_MIN <= int(number) <= NUMBER_MAX
    }
    candidate_map = {int(item["number"]): item for item in candidates if item.get("number") is not None}
    eligible = [
        item for item in candidates[:9]
        if (item.get("entry_validation") or {}).get("passed_for_main")
        and (
            int(item["number"]) not in latest_actual
            or bool((item.get("repeat_guard") or {}).get("passed"))
            or bool((item.get("previous_prediction_guard") or {}).get("reentry_passed"))
        )
    ]

    def single_score(item):
        entry = item.get("entry_validation") or {}
        cross = item.get("cross_validation") or {}
        maturity = item.get("practical_maturity") or {}
        correction = item.get("multi_model_correction") or {}
        return (
            float(item.get("score", 0) or 0) * 100
            + float(item.get("confidence_index", 0) or 0) * 0.35
            + int(item.get("stability_count", 0) or 0) * 4.5
            + int(cross.get("passed_count", 0) or 0) * 3.2
            + float(maturity.get("score", 0) or 0) * 0.22
            + (8 if entry.get("status") == "核心通過" else 0)
            + (5 if correction.get("status") == "已執行" else 0)
        )

    selected = None
    existing = packs.get("strong_single") or {}
    existing_numbers = [
        int(number)
        for number in existing.get("numbers", [])
        if NUMBER_MIN <= int(number) <= NUMBER_MAX
    ]
    if existing_numbers:
        candidate = candidate_map.get(existing_numbers[0])
        if candidate and candidate in eligible:
            selected = candidate
    if selected is None and eligible:
        selected = max(eligible, key=lambda item: (single_score(item), float(item.get("score", 0) or 0), -int(item["number"])))

    if selected is None:
        validation = {
            "status": "未通過",
            "reason": "前九主列沒有可用獨支候選，禁止假造號碼",
            "must_output_single": True,
            "fake_data_guard": "已阻擋",
        }
        packs["strong_single"] = empty_pack("最強獨隻1中1", 1, "前九主列沒有通過獨支驗證")
        packs["strong_single"]["strong_single_validation"] = validation
        return packs, validation

    number = int(selected["number"])
    cross = selected.get("cross_validation") or {}
    maturity = selected.get("practical_maturity") or {}
    entry = selected.get("entry_validation") or {}
    correction = selected.get("multi_model_correction") or {}
    latest_reuse = number in latest_actual
    latest_reuse_allowed = (not latest_reuse) or bool((selected.get("repeat_guard") or {}).get("passed")) or bool((selected.get("previous_prediction_guard") or {}).get("reentry_passed"))
    validation_checks = [
        ("主列放行", bool(entry.get("passed_for_main"))),
        ("非上期開獎忽弄", latest_reuse_allowed),
        ("多模型重算", correction.get("status") == "已執行"),
        ("交叉驗算", int(cross.get("passed_count", 0) or 0) >= 3),
        ("成熟度", float(maturity.get("score", 0) or 0) >= 58),
        ("信心分數", float(selected.get("confidence_index", 0) or 0) >= 68),
    ]
    failed_checks = [name for name, passed in validation_checks if not passed]
    validation = {
        "status": "已驗證" if not failed_checks else "觀察輸出",
        "number": number,
        "must_output_single": True,
        "fake_data_guard": "通過" if not failed_checks else "僅觀察，不得標示高信心",
        "latest_draw_reuse": latest_reuse,
        "latest_draw_reuse_allowed": latest_reuse_allowed,
        "score": round(single_score(selected), 2),
        "candidate_score": selected.get("score"),
        "confidence_index": selected.get("confidence_index"),
        "cross_validation": f"{cross.get('passed_count', '-')}/{cross.get('total_count', '-')}",
        "maturity_score": maturity.get("score"),
        "entry_status": entry.get("status"),
        "failed_checks": failed_checks,
        "evidence": [
            "全系統主列放行",
            "多模型校正完成",
            "交叉驗算與成熟度檢查",
            "上期開獎號防呆",
            "每期重新運算，不沿用上期預測",
        ],
    }
    score_map = {int(item["number"]): float(item.get("score", 0) or 0) for item in candidates}
    current = packs.get("strong_single") or {}
    if current.get("numbers") != [number]:
        packs["strong_single"] = watch_pack("最強獨隻1中1", 1, [number], score_map, "最強獨支由全系統放行門重新選出")
    packs["strong_single"]["numbers"] = [number]
    packs["strong_single"]["must_output_single"] = True
    packs["strong_single"]["strong_single_validation"] = validation
    packs["strong_single"]["validation_status"] = validation["status"]
    packs["strong_single"]["official_release"] = bool(current.get("official_release")) and validation["status"] == "已驗證"
    return packs, validation


def compute_industrial_analysis(draws, review=None):
    timing_log("開始")
    timing_log("自適應權重開始")
    weights, weight_calibration = adaptive_feature_weights(draws, review)
    timing_log("主評分開始")
    base_candidates, weights = score_numbers(draws, review, weights_override=weights)
    timing_log("公式引擎開始")
    formula_engine = compute_formula_engine_analysis(draws, review, base_candidates)
    timing_log("公式融合開始")
    base_candidates = blend_formula_into_candidates(base_candidates, formula_engine)
    timing_log("穩定共識開始")
    candidates, stability = stability_consensus(draws, base_candidates, review)
    timing_log("九碼前置校正開始")
    candidates, top9_frontload_audit = top9_frontload_candidates(candidates, review)
    timing_log("剛開出號硬防火牆開始")
    candidates, recent_draw_firewall = apply_recent_draw_hard_firewall(candidates, draws, formula_engine)
    timing_log("近期失準硬守門開始")
    candidates, recent_failure_front_gate = apply_recent_failure_hard_front_gate(candidates, review)
    timing_log("多模型競賽校正開始")
    candidates, multi_model_correction = apply_multi_model_correction_tournament(candidates, review)
    timing_log("強牌治理開始")
    pack_governance = pack_recent_governance(draws, weights_override=weights)
    timing_log("精算小牌競賽開始")
    precision_tournament = precision_model_tournament(draws, review, weights_override=weights)
    timing_log("主回測開始")
    audit = industrial_backtest(draws, weights_override=weights)
    timing_log("全系統主列放行開始")
    candidates, full_system_entry_gate = apply_full_system_entry_gate(
        candidates,
        draws,
        review,
        audit,
        pack_governance,
        precision_tournament,
        multi_model_correction,
    )
    timing_log("失準急救前九重建開始")
    candidates, slump_emergency_front_rebuild = apply_slump_emergency_front_rebuild(
        candidates,
        draws,
        review,
    )
    timing_log("精算小牌組合開始")
    precision_micro = precision_micro_models(candidates, review, pack_governance, precision_tournament)
    timing_log("強牌組合開始")
    packs = strong_packs(candidates, review, pack_governance)
    packs = attach_precision_micro_packs(packs, precision_micro, candidates)
    packs, strong_single_validation = ensure_verified_strong_single_pack(packs, candidates, review)
    timing_log("錯誤模組滾動修正協議開始")
    post_draw_error_correction = build_post_draw_error_correction_protocol(
        candidates,
        review,
        multi_model_correction,
        full_system_entry_gate,
        pack_governance,
    )
    timing_log("成熟度開始")
    maturity = practical_maturity_summary(candidates)
    timing_log("進階模型摘要開始")
    advanced_models = advanced_model_summary(draws)
    timing_log("進階模型回測開始")
    advanced_backtest = advanced_model_backtest(draws)
    timing_log("相依性驗證開始")
    _, validated_links = validated_dependency_scores(draws)
    timing_log("延遲相依性開始")
    lag_profile = lag_dependency_profile(draws)
    edge = audit.get("top10_avg_hits", 0) - audit.get("random_top10_expectation", DRAW_SIZE * 10 / NUMBER_MAX)
    rolling = audit.get("rolling_windows", {})
    recent_edges = [rolling.get(str(window), {}).get("top10_edge_vs_random", -1) for window in [60, 120]]
    recent_passed = all(value >= 0 for value in recent_edges)
    pack_stats = pack_governance.get("pack_stats", {})
    five_stat = pack_stats.get("five_hit_two", {})
    nine_stat = pack_stats.get("nine_hit_three", {})
    nine_hit_two_floor_passed = (
        float(nine_stat.get("avg_hits", 0) or 0) >= 2.0
        or float(nine_stat.get("research_avg_hits", 0) or 0) >= 2.0
        or bool(nine_stat.get("passed", False))
        or bool(nine_stat.get("research_passed", False))
    )
    main_target_passed = (
        five_stat.get("passed", False)
        and nine_hit_two_floor_passed
    )
    research_main_targets_passed = (
        five_stat.get("research_passed", False)
        and nine_hit_two_floor_passed
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
    formula_avoid = (formula_engine.get("avoid_analysis") or {}) if formula_engine else {}
    timing_log("低機率分析開始")
    unlikely = formula_avoid if formula_avoid.get("numbers") else unlikely_number_analysis(draws, candidates, stability, review)
    timing_log("晉級稽核開始")
    promotion_audit = top10_promotion_audit(candidates, review)
    audit_summary = model_audit(audit, review)
    rank_window_drift = rank_window_drift_diagnosis(review)
    post9_leak = post9_hit_leak_audit(review)
    timing_log("落差診斷開始")
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
    timing_log("完成")
    return {
        "engine_version": "industrial_v27_slump_emergency_rebuild_20260806",
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
        "recent_draw_firewall": recent_draw_firewall,
        "recent_failure_front_gate": recent_failure_front_gate,
        "multi_model_correction": multi_model_correction,
        "slump_emergency_front_rebuild": slump_emergency_front_rebuild,
        "rank_window_drift_correction": rank_window_drift,
        "post9_hit_leak_audit": post9_leak,
        "low_probability_error_recovery": low_probability_error_recovery_payload(review),
        "full_system_entry_gate": full_system_entry_gate,
        "post_draw_error_correction": post_draw_error_correction,
        "strong_single_validation": strong_single_validation,
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
            "ironlaw_targets": {
                "strong_single": "1中1必須輸出並驗算",
                "five_hit_two": "5中2為基本底線，5中3為強標",
                "nine_hit_two_floor": "9中2為最低標準",
                "nine_hit_three": "9中3為強化目標",
            },
            "main_targets_required": ["strong_single", "five_hit_two", "nine_hit_two_floor"],
            "nine_hit_two_floor_passed": nine_hit_two_floor_passed,
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
        "formula_engine": formula_engine,
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
        "qualified_candidates": candidates,
        "main_released_candidates": [
            item for item in candidates[:9]
            if (item.get("entry_validation") or {}).get("passed_for_main")
        ],
        "strong_prediction_packs": packs,
    }
