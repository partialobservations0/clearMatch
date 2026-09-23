"""Run match.py against every row in data/dataset.json and score it against ground truth.

Usage:
    python3 eval/run_eval.py            # full dataset
    python3 eval/run_eval.py --sample 30  # random stratified-ish sample, for a cheap sanity
                                           # check before spending on the full (paid) run
    python3 eval/run_eval.py --category 20_roster_namesake_collision_trap  # just one category

Outcome classification (see README.md for why this asymmetry matters):
    FALSE_NEGATIVE  -- ground truth is 'match' but the model actively said 'no_match'. This is
                       a SILENT, confidently-wrong miss -- the one error class the product must
                       have zero of.
    MATCH_ROUTED_TO_REVIEW -- ground truth is 'match' but the model said 'uncertain'. This is
                       NOT the same failure as FALSE_NEGATIVE: the model isn't silently wrong,
                       it correctly flagged its own uncertainty and would route to a human in
                       production, so no match is ever silently lost. Tracked separately because
                       conflating it with FALSE_NEGATIVE overstates the product's real risk.
    FALSE_POSITIVE  -- ground truth is 'no_match' but the model said 'match'. Minimize, not zero.
    UNCERTAIN_MISS  -- ground truth is 'uncertain' but the model committed to match/no_match
                       instead of routing to review.
    CORRECT_MATCH_VERDICT -- match/no_match/uncertain verdict agrees with ground truth.
    SENTIMENT_MISMATCH -- verdict was correctly 'match' but sentiment disagrees.
    PIPELINE_ERROR  -- fetch/extract failed before the model was even called. Tracked
                       separately from the model's own judgment -- never silently folded into
                       a pass/fail on the matcher itself.
"""

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from match import match_person, DEFAULT_MODEL
from pipeline import fetch_and_extract

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "dataset.json"

# Sonnet 5 pricing ($/1M tokens) -- used only to estimate real-time spend for the budget guard
# below. If MATCH_MODEL is set to something else, this will misprice; it's a safety margin,
# not a billing reconciliation, so approximate is fine.
PRICE_PER_M_INPUT = {"claude-sonnet-5": 2.00, "claude-opus-5": 5.00, "claude-haiku-4-5": 1.00}
PRICE_PER_M_OUTPUT = {"claude-sonnet-5": 10.00, "claude-opus-5": 25.00, "claude-haiku-4-5": 5.00}


def call_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    price_in = PRICE_PER_M_INPUT.get(model, 3.00)  # conservative fallback if model unrecognized
    price_out = PRICE_PER_M_OUTPUT.get(model, 15.00)
    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out


def classify(row, pipeline_ok, pipeline_error, match_result):
    if not pipeline_ok:
        return "PIPELINE_ERROR"

    gt_match = row["ground_truth_match"]
    pred_match = match_result.match

    if gt_match == "match" and pred_match == "no_match":
        return "FALSE_NEGATIVE"
    if gt_match == "match" and pred_match == "uncertain":
        return "MATCH_ROUTED_TO_REVIEW"
    if gt_match == "no_match" and pred_match == "match":
        return "FALSE_POSITIVE"
    if gt_match == "uncertain" and pred_match != "uncertain":
        return "UNCERTAIN_MISS"
    if gt_match != pred_match:
        # remaining mismatches: e.g. gt no_match, predicted uncertain (safe-ish miss);
        # or gt uncertain, predicted correctly uncertain would already be CORRECT below
        return f"OTHER_MISMATCH ({gt_match}->{pred_match})"

    # verdict agrees -- check sentiment only when a match was expected and predicted
    if gt_match == "match":
        if match_result.sentiment != row["ground_truth_sentiment"]:
            return "SENTIMENT_MISMATCH"
    return "CORRECT"


def run(rows, out_path, max_cost=10.0, model=DEFAULT_MODEL):
    results = []
    counts = Counter()
    spent = 0.0
    budget_stopped = False

    for i, row in enumerate(rows, 1):
        if spent >= max_cost:
            budget_stopped = True
            remaining = len(rows) - len(results)
            print()
            print(f"!!! BUDGET GUARD TRIPPED: spent ${spent:.4f} >= --max-cost ${max_cost:.2f}")
            print(f"!!! Stopping with {remaining} row(s) unprocessed. Writing partial results.")
            print(f"!!! Re-run the same command to continue -- match_cache means already-answered rows are free.")
            break

        fetched = fetch_and_extract(row["article_url"])

        if not fetched.ok:
            outcome = "PIPELINE_ERROR"
            results.append({
                "id": row["id"], "category": row["category"], "outcome": outcome,
                "ground_truth_match": row["ground_truth_match"],
                "predicted_match": None, "predicted_sentiment": None,
                "error": fetched.error,
            })
            counts[outcome] += 1
            print(f"[{i}/{len(rows)}] {outcome:16} {row['id']:20} (fetch failed: {fetched.error})")
            continue

        match_result = match_person(row["input_name"], row["input_dob"], fetched.title, fetched.text, model=model)
        call_price = call_cost(match_result.input_tokens, match_result.output_tokens, model)
        spent += call_price

        if match_result.raw_error:
            outcome = "PIPELINE_ERROR"
            results.append({
                "id": row["id"], "category": row["category"], "outcome": outcome,
                "ground_truth_match": row["ground_truth_match"],
                "predicted_match": None, "predicted_sentiment": None,
                "error": match_result.raw_error,
                "used_api": match_result.used_api,
            })
            counts[outcome] += 1
            print(f"[{i}/{len(rows)}] {outcome:16} {row['id']:20} (model call failed: {match_result.raw_error})")
            continue

        outcome = classify(row, True, None, match_result)
        if not match_result.used_api:
            outcome_label = f"{outcome} (pre-check, no API)"
        else:
            outcome_label = outcome
        results.append({
            "id": row["id"], "category": row["category"], "outcome": outcome,
            "ground_truth_match": row["ground_truth_match"],
            "ground_truth_sentiment": row.get("ground_truth_sentiment"),
            "predicted_match": match_result.match,
            "predicted_sentiment": match_result.sentiment,
            "confidence": match_result.confidence,
            "rationale": match_result.rationale,
            "sentiment_evidence": match_result.sentiment_evidence,
            "used_api": match_result.used_api,
            "known_person_hit": match_result.known_person_hit,
            "known_collisions": match_result.known_collisions,
            "from_cache": match_result.from_cache,
            "call_cost": round(call_price, 6),
        })
        counts[outcome] += 1
        if not match_result.used_api:
            counts["PRE_CHECK_SKIPPED_API"] += 1
        if match_result.from_cache:
            counts["SERVED_FROM_CACHE"] += 1
        flag = "  <-- MUST FIX" if outcome == "FALSE_NEGATIVE" else ("  <-- fix" if outcome == "FALSE_POSITIVE" else "")
        cache_tag = " [cached]" if match_result.from_cache else ""
        print(f"[{i}/{len(rows)}] {outcome_label:30} {row['id']:20}{cache_tag}{flag}  (spent so far: ${spent:.4f})")

        time.sleep(0.2)

    summary = {
        "total": len(results),
        "counts": dict(counts),
        "estimated_cost_usd": round(spent, 4),
        "budget_stopped_early": budget_stopped,
        "rows_not_processed": len(rows) - len(results),
        "false_negatives": [r for r in results if r["outcome"] == "FALSE_NEGATIVE"],
        "match_routed_to_review": [r for r in results if r["outcome"] == "MATCH_ROUTED_TO_REVIEW"],
        "false_positives": [r for r in results if r["outcome"] == "FALSE_POSITIVE"],
        "results": results,
    }

    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print()
    print("=" * 60)
    print(f"Total: {len(results)}")
    for outcome, n in counts.most_common():
        print(f"  {outcome:20} {n}")
    print()
    print(f"FALSE_NEGATIVE count: {counts['FALSE_NEGATIVE']}  <-- product spec requires this to be 0")
    print(f"FALSE_POSITIVE count: {counts['FALSE_POSITIVE']}  <-- minimize")
    skipped = counts.get("PRE_CHECK_SKIPPED_API", 0)
    cached = counts.get("SERVED_FROM_CACHE", 0)
    print(f"API calls skipped by pre-check: {skipped}/{len(results)} ({skipped/len(results):.1%})" if results else "")
    print(f"API calls served from cache (free): {cached}/{len(results)}" if results else "")
    print(f"Estimated cost this run: ${spent:.4f}")
    if budget_stopped:
        print(f"!!! STOPPED EARLY at --max-cost budget. {len(rows) - len(results)} row(s) not processed.")
        print(f"!!! Re-run the same command to pick up where this left off (cached rows are free).")
    print(f"Report written to {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=None, help="random sample size instead of the full dataset")
    parser.add_argument("--category", type=str, default=None, help="only run rows in this category")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default=None)
    parser.add_argument("--max-cost", type=float, default=10.0,
                         help="stop the run (writing partial results) once estimated spend reaches this "
                              "many USD -- a client-side safety net on top of any hard cap you've set in "
                              "the Anthropic Console. Default $10. Re-running the same command afterward "
                              "picks up where it left off for free on any row already served from cache.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    args = parser.parse_args()

    dataset = json.loads(DATASET.read_text())

    if args.category:
        dataset = [r for r in dataset if r["category"] == args.category]

    if args.sample:
        random.seed(args.seed)
        dataset = random.sample(dataset, min(args.sample, len(dataset)))

    out_name = args.out or ("eval_run_full.json" if not args.sample and not args.category else "eval_run_partial.json")
    out_path = ROOT / "results" / out_name

    print(f"Running eval on {len(dataset)} rows -> {out_path}  (budget cap: ${args.max_cost:.2f})")
    run(dataset, out_path, max_cost=args.max_cost, model=args.model)


if __name__ == "__main__":
    main()
