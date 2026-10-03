"""Associate untouched responses with fixed inputs and retain missing attempts."""

import json
from pathlib import Path

from .contracts import guard, parse_last_message
from .dataset import text_hash


def read_jsonl(path):
    records = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid JSONL record on line %d: %s" % (line_number, exc)) from exc
        if type(value) is not dict:
            raise ValueError("Each JSONL record must be an object; line %d" % line_number)
        records.append(value)
    return records


def write_jsonl(path, records):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
            handle.flush()


def write_json(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def parse_records(inputs, records):
    """Reject ambiguous joins; materialize missing rows and recompute parsing."""
    by_id = {case["id"]: case for case in inputs}
    if len(by_id) != len(inputs):
        raise ValueError("Duplicate input IDs")
    received = {}
    for record in records:
        if type(record) is not dict:
            raise ValueError("Response records must be objects")
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or case_id not in by_id:
            raise ValueError("Unknown or missing response case_id")
        if case_id in received:
            raise ValueError("Duplicate response case_id: " + case_id)
        if record.get("request_error") is not None and not isinstance(record["request_error"], str):
            raise ValueError("request_error must be null or a string for " + case_id)
        failed_without_answer = record.get("raw_output") is None and bool(record.get("request_error"))
        if "raw_output" not in record or (not isinstance(record["raw_output"], str) and not failed_without_answer):
            raise ValueError("raw_output must be a string, or null with a nonempty request_error, for " + case_id)
        expected_hash = text_hash(by_id[case_id]["text"])
        if "input_sha256" in record and record["input_sha256"] != expected_hash:
            raise ValueError("Input hash mismatch for " + case_id)
        received[case_id] = record
    parsed_records = []
    for case in inputs:
        source = received.get(case["id"])
        if source is None:
            result = {"case_id": case["id"], "raw_output": "", "request_error": "missing_response"}
        else:
            result = dict(source)
        result["input_sha256"] = text_hash(case["text"])
        result.setdefault("request_error", None)
        if result.get("timed_out") and not result["request_error"]:
            result["request_error"] = "request_timeout"
        if result.get("returncode") not in (None, 0) and not result["request_error"]:
            result["request_error"] = "request_exit_failure"
        parsed, error = parse_last_message(result["raw_output"])
        result["parsed"] = parsed
        result["parse_error"] = error
        result["guard_failures"] = guard(parsed, case["text"])
        parsed_records.append(result)
    return parsed_records
