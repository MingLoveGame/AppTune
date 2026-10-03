"""Regression tests for benchmark integrity, parsing, gating, and denominators."""

import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

from intentbench.contracts import evidence_checks, guard, parse_last_message, policy_checks, schema_checks
from intentbench.dataset import ROOT, load_cases, load_inputs, load_json, validate_cases, validate_inputs
from intentbench.evaluation import evaluate, fraction
from intentbench.integrity import validate_release
from intentbench.requests import build_requests, compose_prompt, invoke_adapter
from intentbench.responses import parse_records, read_jsonl, write_jsonl
from intentbench.rule import infer


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.text = "Maximize transactions per second. Keep synchronous durability and write barriers enabled."
        self.contract = {
            "status": "resolved", "category": "throughput", "metric": "tps", "direction": "max",
            "constraints": {"durability": "sync", "barriers": "on"},
            "evidence": "Maximize transactions per second", "reason": "An explicit objective.",
        }

    def test_unmodified_json_success(self):
        self.assertEqual(parse_last_message(json.dumps(self.contract)), (self.contract, None))
        self.assertEqual(guard(self.contract, self.text), [])

    def test_parser_does_not_repair_fences_or_prose(self):
        for raw in ("", "```json\n{}\n```", "Answer: {}", "{} trailing", '{"status":'):
            with self.subTest(raw=raw):
                parsed, error = parse_last_message(raw)
                self.assertIsNone(parsed)
                self.assertTrue(error.startswith("JSONDecodeError:"))

    def test_non_object_json_parses_but_fails_schema(self):
        for raw in ("[]", "null", "3", "true", '"answer"'):
            with self.subTest(raw=raw):
                parsed, error = parse_last_message(raw)
                self.assertIsNone(error)
                self.assertEqual(guard(parsed, self.text), ["invalid_json_object"])

    def test_duplicate_keys_preserve_decoder_semantics(self):
        parsed, error = parse_last_message('{"status":"resolved","status":"abstain"}')
        self.assertIsNone(error)
        self.assertEqual(parsed["status"], "abstain")

    def test_nonfinite_parse_is_distinct_from_guard(self):
        parsed, error = parse_last_message('{"bound":NaN,"upper":Infinity}')
        self.assertIsNone(error)
        self.assertTrue(math.isnan(parsed["bound"]))
        self.assertTrue(math.isinf(parsed["upper"]))
        for bound in (float("nan"), float("inf"), -float("inf"), 0, -1, True, "5", None):
            with self.subTest(bound=bound):
                proposal = copy.deepcopy(self.contract)
                proposal["constraints"]["p95_max_ms"] = bound
                self.assertIn("numeric_constraint_type_or_range", schema_checks(proposal))

    def test_positive_numeric_bounds_and_large_integer(self):
        for bound in (1, 0.001, 10 ** 400):
            proposal = copy.deepcopy(self.contract)
            proposal["constraints"]["commit_max_s"] = bound
            self.assertEqual(guard(proposal, self.text), [])

    def test_evidence_must_be_nonempty_exact_substring(self):
        for evidence in ("", "maximize transactions per second", "invented", None, ["Maximize"]):
            with self.subTest(evidence=evidence):
                proposal = dict(self.contract, evidence=evidence)
                self.assertEqual(evidence_checks(proposal, self.text), ["ungrounded_evidence"])

    def test_mandatory_policy_is_separate_from_schema(self):
        proposal = copy.deepcopy(self.contract)
        del proposal["constraints"]["barriers"]
        self.assertEqual(schema_checks(proposal), [])
        self.assertEqual(policy_checks(proposal), ["mandatory_independent_safety_policy"])

    def test_bad_bindings_and_unhashable_fields_do_not_crash(self):
        for key, value, failure in (
            ("metric", [], "metric_registry"), ("status", {}, "status"),
            ("direction", "min", "metric_binding"), ("reason", 3, "reason_type"),
            ("constraints", [], "constraint_object"),
        ):
            with self.subTest(key=key):
                self.assertIn(failure, guard(dict(self.contract, **{key: value}), self.text))

    def test_abstention_fields_and_extra_constraints(self):
        proposal = dict(self.contract, status="abstain")
        self.assertIn("abstain_fields", guard(proposal, self.text))
        proposal.update(category=None, metric=None, direction=None)
        self.assertEqual(guard(proposal, self.text), [])
        proposal["constraints"] = dict(proposal["constraints"], unknown=1)
        self.assertIn("unknown_constraints", guard(proposal, self.text))


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.data = load_json(ROOT / "data" / "cases.json")
        self.inputs = load_inputs()

    def test_release_integrity(self):
        result = validate_release()
        self.assertEqual(result["cases"], 72)
        self.assertEqual(result["gold_statuses"], {"resolved": 54, "abstain": 18})
        self.assertEqual(result["integrity"]["requests_verified"], 72)

    def test_duplicate_or_missing_case_ids_fail(self):
        data = copy.deepcopy(self.data)
        data["cases"][1]["id"] = data["cases"][0]["id"]
        with self.assertRaisesRegex(ValueError, "unique, ordered"):
            validate_cases(data)
        with self.assertRaisesRegex(ValueError, "unique, ordered"):
            validate_inputs({"cases": self.inputs[:-1]})

    def test_inputs_may_not_expose_labels(self):
        inputs = copy.deepcopy(self.inputs)
        inputs[0]["gold"] = {}
        with self.assertRaisesRegex(ValueError, "only id and text"):
            validate_inputs({"cases": inputs})

    def test_input_text_drift_fails(self):
        inputs = copy.deepcopy(self.inputs)
        inputs[0]["text"] += " Changed input."
        with self.assertRaisesRegex(ValueError, "differ"):
            validate_cases(self.data, inputs)

    def test_invalid_gold_evidence_fails(self):
        data = copy.deepcopy(self.data)
        data["cases"][0]["gold"]["evidence"] = "Not in this input."
        with self.assertRaisesRegex(ValueError, "Invalid gold contract"):
            validate_cases(data)

    def test_invalid_group_counts_fail(self):
        data = copy.deepcopy(self.data)
        data["cases"][0]["group"] = "distractor"
        with self.assertRaisesRegex(ValueError, "six strata"):
            validate_cases(data)

    def test_request_construction_preserves_text_and_spacing(self):
        self.assertEqual(compose_prompt("Instructions.\n\n", "Body."), "Instructions.\n\nOperator description:\nBody.")
        records = build_requests(self.inputs, "Instructions.")
        self.assertEqual(len(records), 72)
        self.assertEqual(set(records[0]), {"case_id", "input_sha256", "full_prompt_sha256", "prompt"})
        self.assertTrue(records[0]["prompt"].endswith(self.inputs[0]["text"]))


class ResponseAndScoreTests(unittest.TestCase):
    def setUp(self):
        self.cases = load_cases()
        self.inputs = load_inputs()
        self.records = [{"case_id": case["id"], "raw_output": json.dumps(case["gold"])} for case in self.cases]

    def test_full_gold_scores_fixed_denominators(self):
        result = evaluate(self.cases, self.records)
        metrics = result["overall"]["metrics"]
        self.assertEqual(metrics["target_binding"], fraction(54, 54))
        self.assertEqual(metrics["abstain_status"], fraction(18, 18))
        self.assertEqual(metrics["exact_contract"], fraction(72, 72))
        self.assertIsNone(result["by_group"]["explicit"]["metrics"]["abstain_status"]["value"])
        self.assertIsNone(result["by_group"]["insufficient"]["metrics"]["target_binding"]["value"])

    def test_missing_responses_remain_in_denominator(self):
        result = evaluate(self.cases, self.records[1:])
        self.assertEqual(result["overall"]["metrics"]["exact_contract"], fraction(71, 72))
        self.assertEqual(result["overall"]["metrics"]["target_binding"], fraction(53, 54))
        self.assertEqual(result["overall"]["counts"]["missing_response"], 1)
        self.assertTrue(result["details"][0]["request_failure"])

    def test_request_failure_cannot_score_residual_output(self):
        self.records[0]["request_error"] = "request_timeout"
        self.records[48]["request_error"] = "request_exit_failure"
        metrics = evaluate(self.cases, self.records)["overall"]["metrics"]
        self.assertEqual(metrics["target_binding"], fraction(53, 54))
        self.assertEqual(metrics["abstain_status"], fraction(17, 18))
        self.assertEqual(metrics["exact_contract"], fraction(70, 72))

    def test_failed_request_may_retain_a_null_answer(self):
        self.records[0].update(raw_output=None, request_error="request_timeout")
        parsed = parse_records(self.inputs, self.records)
        self.assertIsNone(parsed[0]["raw_output"])
        self.assertTrue(parsed[0]["parse_error"].startswith("TypeError:"))
        self.assertEqual(evaluate(self.cases, parsed)["overall"]["metrics"]["exact_contract"], fraction(71, 72))
        self.records[0]["request_error"] = None
        with self.assertRaisesRegex(ValueError, "nonempty request_error"):
            parse_records(self.inputs, self.records)

    def test_failed_transport_metadata_is_not_ignored(self):
        self.records[0]["returncode"] = 2
        self.records[1]["timed_out"] = True
        counts = evaluate(self.cases, self.records)["overall"]["counts"]
        self.assertEqual(counts["request_failure"], 2)
        self.assertEqual(counts["exact_contract"], 70)

    def test_raw_answer_overrides_stale_parsed_cache(self):
        self.records[0]["raw_output"] = "{broken"
        self.records[0]["parsed"] = self.cases[0]["gold"]
        self.records[0]["parse_error"] = None
        result = evaluate(self.cases, self.records)
        self.assertEqual(result["overall"]["metrics"]["exact_contract"], fraction(71, 72))
        self.assertEqual(result["overall"]["counts"]["parse_failure"], 1)

    def test_array_answer_has_zero_score_without_parse_error(self):
        self.records[0]["raw_output"] = "[]"
        result = evaluate(self.cases, self.records)
        self.assertEqual(result["overall"]["counts"]["parse_failure"], 0)
        self.assertEqual(result["overall"]["counts"]["invalid_object"], 1)
        self.assertEqual(result["overall"]["metrics"]["exact_contract"], fraction(71, 72))

    def test_duplicate_unknown_and_hash_mismatch_are_errors(self):
        with self.assertRaisesRegex(ValueError, "Duplicate response"):
            parse_records(self.inputs, self.records + self.records[:1])
        with self.assertRaisesRegex(ValueError, "Unknown"):
            parse_records(self.inputs, [{"case_id": "T999", "raw_output": "{}"}])
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            parse_records(self.inputs, [dict(self.records[0], input_sha256="wrong")])

    def test_evidence_failures_do_not_redefine_frozen_field_score(self):
        contract = copy.deepcopy(self.cases[0]["gold"])
        contract["evidence"] = "Not grounded."
        self.records[0]["raw_output"] = json.dumps(contract)
        result = evaluate(self.cases, self.records)
        self.assertEqual(result["overall"]["metrics"]["exact_contract"], fraction(72, 72))
        self.assertEqual(result["overall"]["metrics"]["structural_pass"], fraction(71, 72))

    def test_frozen_rule_baseline_regression(self):
        records = [{"case_id": case["id"], "raw_output": json.dumps(infer(case["text"]))} for case in self.cases]
        result = evaluate(self.cases, records)
        metrics = result["overall"]["metrics"]
        self.assertEqual(metrics["target_binding"], fraction(14, 54))
        self.assertEqual(metrics["abstain_status"], fraction(17, 18))
        self.assertEqual(metrics["exact_contract"], fraction(4, 72))
        self.assertEqual(metrics["exact_constraints"], fraction(10, 72))
        self.assertEqual(metrics["structural_pass"], fraction(22, 72))
        self.assertEqual(metrics["valid_correct_abstention"], fraction(8, 18))
        self.assertEqual([item["metrics"]["exact_contract"]["numerator"] for item in result["by_group"].values()], [2, 0, 1, 0, 1, 0])

    def test_jsonl_rejects_malformed_transport_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.jsonl"
            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be an object"):
                read_jsonl(path)
            path.write_text("{broken\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 1"):
                read_jsonl(path)
            write_jsonl(path, self.records)
            self.assertEqual(read_jsonl(path), self.records)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.requests = build_requests([{"id": "T001", "text": "An input."}], "An instruction.")

    def test_generic_adapter_preserves_exact_stdout(self):
        command = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"]
        record = list(invoke_adapter(self.requests, command, 5))[0]
        self.assertEqual(record["raw_output"], self.requests[0]["prompt"])
        self.assertIsNone(record["request_error"])
        self.assertEqual(record["returncode"], 0)

    def test_adapter_exit_failure_retains_output(self):
        command = [sys.executable, "-c", "import sys; print('{}'); sys.exit(3)"]
        record = list(invoke_adapter(self.requests, command, 5))[0]
        self.assertEqual(record["request_error"], "request_exit_failure")
        self.assertEqual(record["raw_output"].strip(), "{}")

    def test_adapter_timeout_records_failed_attempt(self):
        command = [sys.executable, "-c", "import time; time.sleep(5)"]
        record = list(invoke_adapter(self.requests, command, 0.1))[0]
        self.assertTrue(record["timed_out"])
        self.assertEqual(record["request_error"], "request_timeout")

    def test_invalid_timeout_or_command_rejected(self):
        with self.assertRaisesRegex(ValueError, "required"):
            list(invoke_adapter(self.requests, [], 1))
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.assertRaisesRegex(ValueError, "positive and finite"):
                list(invoke_adapter(self.requests, [sys.executable], timeout))


if __name__ == "__main__":
    unittest.main()
