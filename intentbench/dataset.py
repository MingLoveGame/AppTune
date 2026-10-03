"""Validate the fixed benchmark and its label-free inference view."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from .contracts import METRICS, NUMERIC_CONSTRAINTS, guard

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ("explicit", "label_masked", "distractor", "constrained", "insufficient", "conflict_priority")
CASE_IDS = ["T%03d" % index for index in range(1, 73)]


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _case_list(data):
    if type(data) is not dict or type(data.get("cases")) is not list:
        raise ValueError("Expected a JSON object containing a cases list")
    return data["cases"]


def validate_inputs(data):
    """Validate exactly 72 ordered label-free records containing only id and text."""
    cases = _case_list(data)
    if any(type(case) is not dict or set(case) != {"id", "text"} for case in cases):
        raise ValueError("Inference inputs must contain only id and text")
    if [case["id"] for case in cases] != CASE_IDS:
        raise ValueError("Expected unique, ordered case IDs T001 through T072")
    if any(not isinstance(case["text"], str) or not case["text"] for case in cases):
        raise ValueError("Each input text must be a nonempty string")
    if len({case["text"] for case in cases}) != 72:
        raise ValueError("Input texts must be unique")
    return cases


def load_inputs(path=None):
    return validate_inputs(load_json(path or ROOT / "data" / "inputs.json"))


def validate_cases(data, inputs=None):
    """Check fixed case counts, gold structure, strata, and optional input equality."""
    cases = _case_list(data)
    required = {"id", "group", "text", "gold", "rationale"}
    if any(type(case) is not dict or set(case) != required for case in cases):
        raise ValueError("Each case requires id, group, text, gold, and rationale")
    validate_inputs({"cases": [{"id": case["id"], "text": case["text"]} for case in cases]})
    for case in cases:
        if not isinstance(case["group"], str) or case["group"] not in GROUPS:
            raise ValueError("Unknown group: " + case["id"])
        if not isinstance(case["rationale"], str) or not case["rationale"]:
            raise ValueError("Missing rationale: " + case["id"])
        failures = guard(case["gold"], case["text"])
        if failures or not case["gold"].get("reason"):
            raise ValueError("Invalid gold contract %s: %s" % (case["id"], failures))
        lowered = case["text"].lower()
        if not all(term in lowered for term in ("barrier", "synchron", "durab")):
            raise ValueError("Missing explicit safety wording: " + case["id"])
        status = case["gold"]["status"]
        if case["group"] == "insufficient" and status != "abstain":
            raise ValueError("Insufficient-information cases must abstain")
        if case["group"] in GROUPS[:4] and status != "resolved":
            raise ValueError("The first four strata must contain resolved cases")
        if case["group"] == "label_masked":
            tokens = ("throughput", "tail_latency", "completion_time", "stability", "tps", "ops_s", "p95", "p99", "completion_s", "throughput_cv", "coefficient of variation")
            if any(token in lowered for token in tokens):
                raise ValueError("Metric label found in label-masked case: " + case["id"])
    groups = Counter(case["group"] for case in cases)
    statuses = Counter(case["gold"]["status"] for case in cases)
    metrics = Counter(case["gold"]["metric"] for case in cases if case["gold"]["status"] == "resolved")
    if groups != Counter({group: 12 for group in GROUPS}):
        raise ValueError("Expected six strata with 12 cases each")
    if statuses != Counter({"resolved": 54, "abstain": 18}):
        raise ValueError("Expected 54 resolved and 18 abstain gold contracts")
    if metrics != Counter({metric: 9 for metric in METRICS}):
        raise ValueError("Expected nine resolved cases for each metric binding")
    for group in GROUPS[:4]:
        actual = Counter(case["gold"]["metric"] for case in cases if case["group"] == group)
        if actual != Counter({metric: 2 for metric in METRICS}):
            raise ValueError("Expected two instances of each metric in " + group)
    if inputs is not None:
        expected = [{"id": case["id"], "text": case["text"]} for case in cases]
        if validate_inputs({"cases": inputs}) != expected:
            raise ValueError("Inference inputs differ from benchmark texts")
    occurrences = Counter(key for case in cases for key in case["gold"]["constraints"] if key in NUMERIC_CONSTRAINTS)
    return {"cases": len(cases), "groups": dict(groups), "gold_statuses": dict(statuses),
            "resolved_metrics": dict(metrics), "additional_constraint_occurrences": dict(occurrences)}


def load_cases(path=None):
    data = load_json(path or ROOT / "data" / "cases.json")
    validate_cases(data)
    return data["cases"]
