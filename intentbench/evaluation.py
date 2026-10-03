"""Compute frozen field agreement with failure-inclusive gold denominators."""

from collections import Counter

from .contracts import project
from .responses import parse_records


def fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def score_case(case, record):
    gold = case["gold"]
    prediction = record["parsed"]
    usable = not record.get("request_error") and record["parse_error"] is None and type(prediction) is dict
    resolved = usable and prediction.get("status") == "resolved"
    abstain = usable and prediction.get("status") == "abstain"
    correct_target = bool(resolved and gold["status"] == "resolved" and all(
        prediction.get(key) == gold[key] for key in ("category", "metric", "direction")))
    correct_abstain = bool(abstain and gold["status"] == "abstain")
    structural_pass = usable and not record["guard_failures"]
    return {
        "case_id": case["id"], "group": case["group"], "gold_status": gold["status"],
        "target_binding": correct_target,
        "abstain_status": correct_abstain,
        "objective_decision": correct_target or correct_abstain,
        "exact_contract": bool(usable and project(prediction) == project(gold)),
        "exact_constraints": bool(usable and prediction.get("constraints") == gold["constraints"]),
        "structural_pass": bool(structural_pass),
        "valid_correct_abstention": bool(structural_pass and correct_abstain),
        "declared_resolved": bool(resolved),
        "request_failure": bool(record.get("request_error")),
        "parse_failure": record["parse_error"] is not None,
        "missing_response": record.get("request_error") == "missing_response",
        "invalid_object": type(prediction) is not dict,
        "guard_failures": record["guard_failures"],
    }


def summarize(details):
    total = len(details)
    gold_resolved = sum(item["gold_status"] == "resolved" for item in details)
    gold_abstain = total - gold_resolved
    counts = {key: sum(item[key] for item in details) for key in (
        "target_binding", "abstain_status", "objective_decision", "exact_contract", "exact_constraints",
        "structural_pass", "valid_correct_abstention", "declared_resolved", "request_failure",
        "parse_failure", "missing_response", "invalid_object")}
    return {
        "cases": total, "gold_resolved": gold_resolved, "gold_abstain": gold_abstain,
        "metrics": {
            "target_binding": fraction(counts["target_binding"], gold_resolved),
            "abstain_status": fraction(counts["abstain_status"], gold_abstain),
            "exact_contract": fraction(counts["exact_contract"], total),
            "exact_constraints": fraction(counts["exact_constraints"], total),
            "objective_decision": fraction(counts["objective_decision"], total),
            "structural_pass": fraction(counts["structural_pass"], total),
            "valid_correct_abstention": fraction(counts["valid_correct_abstention"], gold_abstain),
        },
        "counts": counts,
        "guard_failure_counts": dict(Counter(failure for item in details for failure in item["guard_failures"])),
    }


def evaluate(cases, records):
    inputs = [{"id": case["id"], "text": case["text"]} for case in cases]
    parsed = parse_records(inputs, records)
    details = [score_case(case, record) for case, record in zip(cases, parsed)]
    groups = dict.fromkeys(case["group"] for case in cases)
    return {
        "schema_version": "1.0", "scoring_fields": ["status", "category", "metric", "direction", "constraints"],
        "denominator_policy": "All gold cases remain in their respective denominators, including missing and failed attempts.",
        "overall": summarize(details),
        "by_group": {group: summarize([item for item in details if item["group"] == group]) for group in groups},
        "details": details,
    }
