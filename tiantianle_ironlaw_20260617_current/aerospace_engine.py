import hashlib
import json
import math
import random
from collections import Counter


NUMBER_MIN = 1
NUMBER_MAX = 39
DRAW_SIZE = 5


def canonical_draws(draws):
    return [
        {
            "period": int(draw["period"]),
            "draw_date": str(draw["draw_date"]),
            "numbers": sorted(int(number) for number in draw["numbers"]),
        }
        for draw in draws
    ]


def data_fingerprint(draws):
    payload = json.dumps(canonical_draws(draws), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def input_invariant_audit(draws):
    failures = []
    previous_period = None
    previous_date = None
    seen_periods = set()
    for index, draw in enumerate(draws):
        period = int(draw["period"])
        draw_date = str(draw["draw_date"])
        numbers = [int(number) for number in draw["numbers"]]
        if period in seen_periods:
            failures.append(f"duplicate_period:{period}")
        seen_periods.add(period)
        if len(numbers) != DRAW_SIZE or len(set(numbers)) != DRAW_SIZE:
            failures.append(f"invalid_draw_size_or_duplicate:{period}")
        if any(number < NUMBER_MIN or number > NUMBER_MAX for number in numbers):
            failures.append(f"number_out_of_range:{period}")
        if numbers != sorted(numbers):
            failures.append(f"numbers_not_sorted:{period}")
        if previous_period is not None and period <= previous_period:
            failures.append(f"period_not_increasing:{period}")
        if previous_date is not None and draw_date < previous_date:
            failures.append(f"date_not_increasing:{period}")
        previous_period = period
        previous_date = draw_date
        if len(failures) >= 30:
            break
    return {
        "passed": not failures,
        "checked_draws": len(draws),
        "failure_count": len(failures),
        "failures": failures,
    }


def distribution(draws):
    counter = Counter()
    for draw in draws:
        counter.update(draw["numbers"])
    total = max(sum(counter.values()), 1)
    return {number: counter.get(number, 0) / total for number in range(NUMBER_MIN, NUMBER_MAX + 1)}


def drift_audit(draws):
    recent = distribution(draws[-50:])
    baseline = distribution(draws[-300:-50] if len(draws) >= 300 else draws[:-50])
    total_variation = 0.5 * sum(abs(recent[number] - baseline[number]) for number in recent)
    status = "stable" if total_variation < 0.16 else ("watch" if total_variation < 0.24 else "high_drift")
    return {
        "method": "total_variation_recent50_vs_prior250",
        "total_variation": round(total_variation, 4),
        "status": status,
        "warning": "Distribution drift is a model-risk signal, not proof of a predictable pattern.",
    }


def rank_map(numbers):
    return {number: index + 1 for index, number in enumerate(numbers)}


def redundant_channel_audit(industrial):
    primary = [item["number"] for item in industrial.get("candidates", [])[:10]]
    models = industrial.get("advanced_models", {}).get("models", [])
    channels = {"primary_industrial": primary}
    votes = Counter(primary)
    for model in models:
        name = model.get("model") or model.get("name") or "unknown"
        top10 = [int(number) for number in model.get("top10", [])[:10]]
        channels[name] = top10
        votes.update(top10)
    consensus = [number for number, _ in sorted(votes.items(), key=lambda item: (-item[1], item[0]))[:12]]
    secondary = consensus[:10]
    overlap = sorted(set(primary) & set(secondary))
    jaccard = len(overlap) / max(len(set(primary) | set(secondary)), 1)
    return {
        "channels": channels,
        "primary_top10": primary,
        "secondary_consensus_top10": secondary,
        "overlap": overlap,
        "overlap_count": len(overlap),
        "jaccard": round(jaccard, 4),
        "status": "agree" if len(overlap) >= 6 else ("watch" if len(overlap) >= 4 else "diverge"),
    }


def uncertainty_audit(industrial, seed, simulations=1200):
    candidates = industrial.get("candidates", [])
    if not candidates:
        return {"simulations": 0, "status": "failed", "top10_retention": 0}
    rng = random.Random(seed)
    top_pool = candidates[:25]
    counts = Counter()
    base_rank = rank_map([item["number"] for item in candidates])
    for _ in range(simulations):
        perturbed = []
        for item in top_pool:
            stability = float(item.get("stability_rate", 0))
            noise_scale = 0.035 + (1 - stability) * 0.08
            perturbed.append((float(item.get("score", 0)) + rng.gauss(0, noise_scale), item["number"]))
        perturbed.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        counts.update(number for _, number in perturbed[:10])
    rows = [
        {
            "number": number,
            "base_rank": base_rank.get(number),
            "top10_rate": round(counts[number] / simulations, 4),
        }
        for number in sorted(counts, key=lambda number: (-counts[number], number))[:15]
    ]
    primary_top10 = [item["number"] for item in candidates[:10]]
    retained = sum(1 for number in primary_top10 if counts[number] / simulations >= 0.60)
    retention = retained / 10
    return {
        "method": "deterministic_score_perturbation_monte_carlo",
        "simulations": simulations,
        "seed": seed,
        "top10_retention": round(retention, 3),
        "status": "stable" if retention >= 0.7 else ("watch" if retention >= 0.5 else "unstable"),
        "numbers": rows,
    }


def output_fingerprint(industrial):
    payload = {
        "candidates": industrial.get("candidates", []),
        "strong_prediction_packs": industrial.get("strong_prediction_packs", {}),
        "weights": industrial.get("weights", {}),
        "release_gate": industrial.get("release_gate", {}),
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def compute_aerospace_assurance(draws, industrial):
    input_hash = data_fingerprint(draws)
    invariants = input_invariant_audit(draws)
    redundant = redundant_channel_audit(industrial)
    drift = drift_audit(draws)
    seed = int(input_hash[:16], 16)
    uncertainty = uncertainty_audit(industrial, seed)
    critical_failures = []
    if not invariants["passed"]:
        critical_failures.append("input_invariant_failure")
    if len(draws) < 300:
        critical_failures.append("insufficient_long_horizon_data")
    if critical_failures:
        release_status = "blocked"
    elif redundant["status"] == "diverge" or uncertainty["status"] == "unstable" or drift["status"] == "high_drift":
        release_status = "watch_only"
    else:
        release_status = "verified"
    assurance_score = 100
    assurance_score -= min(invariants["failure_count"] * 25, 100)
    assurance_score -= 18 if redundant["status"] == "diverge" else (8 if redundant["status"] == "watch" else 0)
    assurance_score -= 18 if uncertainty["status"] == "unstable" else (8 if uncertainty["status"] == "watch" else 0)
    assurance_score -= 15 if drift["status"] == "high_drift" else (6 if drift["status"] == "watch" else 0)
    return {
        "engine_version": "aerospace_assurance_v1",
        "principle": "fail_closed_redundant_verified_deterministic",
        "input_fingerprint_sha256": input_hash,
        "output_fingerprint_sha256": output_fingerprint(industrial),
        "input_invariants": invariants,
        "redundant_channel_audit": redundant,
        "uncertainty_audit": uncertainty,
        "drift_audit": drift,
        "release_assurance": {
            "status": release_status,
            "assurance_score": max(0, assurance_score),
            "critical_failures": critical_failures,
            "meaning": "Reliability assurance only; it does not guarantee lottery prediction accuracy.",
        },
    }
