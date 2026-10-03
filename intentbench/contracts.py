"""Parse unmodified answers and check structure without consulting gold labels."""

import json
import math

SCORING_FIELDS = ("status", "category", "metric", "direction", "constraints")
OUTPUT_FIELDS = set(SCORING_FIELDS) | {"evidence", "reason"}
METRICS = {
    "tps": ("throughput", "max"),
    "ops_s": ("throughput", "max"),
    "p95_ms": ("tail_latency", "min"),
    "p99_ms": ("tail_latency", "min"),
    "completion_s": ("completion_time", "min"),
    "throughput_cv": ("stability", "min"),
}
NUMERIC_CONSTRAINTS = {"commit_max_s", "p95_max_ms", "p99_max_ms", "throughput_min", "cv_max"}
CONSTRAINTS = NUMERIC_CONSTRAINTS | {"durability", "barriers"}


def positive_finite_number(value):
    """Reject booleans and non-finite floats, allowing arbitrary-size integers."""
    return (type(value) is int and value > 0) or (type(value) is float and math.isfinite(value) and value > 0)


def parse_last_message(text):
    """Apply json.loads once, preserving its result and error; never repair text."""
    try:
        return json.loads(text), None
    except Exception as exc:
        return None, type(exc).__name__ + ": " + str(exc)


def project(value):
    """Return the five scored fields, excluding evidence and explanation prose."""
    return {key: value.get(key) for key in SCORING_FIELDS} if isinstance(value, dict) else None


def schema_checks(value):
    """Check fields, registered bindings, and positive finite numeric bounds."""
    if type(value) is not dict:
        return ["invalid_json_object"]
    failures = []
    if set(value) != OUTPUT_FIELDS:
        failures.append("outer_schema")
    status = value.get("status")
    if not isinstance(status, str) or status not in {"resolved", "abstain"}:
        failures.append("status")
    if status == "abstain":
        if any(value.get(key) is not None for key in ("category", "metric", "direction")):
            failures.append("abstain_fields")
    elif status == "resolved":
        metric = value.get("metric")
        if not isinstance(metric, str) or metric not in METRICS:
            failures.append("metric_registry")
        elif (value.get("category"), value.get("direction")) != METRICS[metric]:
            failures.append("metric_binding")
    constraints = value.get("constraints")
    if type(constraints) is not dict:
        failures.append("constraint_object")
    else:
        if not set(constraints) <= CONSTRAINTS:
            failures.append("unknown_constraints")
        if any(
            not positive_finite_number(bound)
            for key, bound in constraints.items()
            if key not in {"durability", "barriers"}
        ):
            failures.append("numeric_constraint_type_or_range")
    if not isinstance(value.get("reason"), str):
        failures.append("reason_type")
    return failures


def evidence_checks(value, text):
    """Require a nonempty exact input substring as supporting evidence."""
    if type(value) is not dict:
        return ["invalid_json_object"]
    evidence = value.get("evidence")
    if not isinstance(evidence, str) or not evidence or evidence not in text:
        return ["ungrounded_evidence"]
    return []


def policy_checks(value):
    """Require synchronous durability and enabled write barriers independently."""
    if type(value) is not dict:
        return ["invalid_json_object"]
    constraints = value.get("constraints")
    if type(constraints) is not dict:
        return ["constraint_object"]
    if constraints.get("durability") != "sync" or constraints.get("barriers") != "on":
        return ["mandatory_independent_safety_policy"]
    return []


def guard(value, text):
    """Return unique check failures; this gate neither repairs nor scores answers."""
    return list(dict.fromkeys(schema_checks(value) + evidence_checks(value, text) + policy_checks(value)))
