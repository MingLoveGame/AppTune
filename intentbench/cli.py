"""Command-line entry points; no network services are selected or contacted."""

import argparse
import json
import sys
from pathlib import Path

from .dataset import ROOT, load_cases, load_inputs, text_hash
from .evaluation import evaluate
from .integrity import validate_release
from .requests import build_requests, invoke_adapter
from .responses import parse_records, read_jsonl, write_json, write_jsonl
from .rule import infer


def parser():
    root = argparse.ArgumentParser(description="Validate, run, parse, and evaluate the 72-case intent contract benchmark.")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("validate-data", help="Verify the released dataset, prompt, and integrity manifest")
    rule = commands.add_parser("run-rule", help="Run the frozen lexical baseline on all label-free inputs")
    rule.add_argument("--inputs", type=Path, default=ROOT / "data" / "inputs.json")
    rule.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("build-requests", help="Write complete label-free prompts as JSONL")
    build.add_argument("--inputs", type=Path, default=ROOT / "data" / "inputs.json")
    build.add_argument("--prompt", type=Path, default=ROOT / "prompts" / "extract_contract.txt")
    build.add_argument("--output", type=Path, required=True)
    parse = commands.add_parser("parse-responses", help="Parse raw JSON answers without repair and mark missing attempts")
    parse.add_argument("--inputs", type=Path, default=ROOT / "data" / "inputs.json")
    parse.add_argument("--responses", type=Path, required=True)
    parse.add_argument("--output", type=Path, required=True)
    score = commands.add_parser("evaluate", help="Score all cases, keeping failed attempts in the denominator")
    score.add_argument("--cases", type=Path, default=ROOT / "data" / "cases.json")
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    run = commands.add_parser("run-command", help="Call a user-supplied stdin/stdout adapter once per case")
    run.add_argument("--inputs", type=Path, default=ROOT / "data" / "inputs.json")
    run.add_argument("--prompt", type=Path, default=ROOT / "prompts" / "extract_contract.txt")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--timeout", type=float, default=240)
    run.add_argument("adapter", nargs=argparse.REMAINDER, help="-- followed by adapter command and arguments")
    return root


def _report(value):
    print(json.dumps(value, ensure_ascii=True, indent=2))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "validate-data":
            _report(validate_release())
        elif args.command == "evaluate":
            result = evaluate(load_cases(args.cases), read_jsonl(args.predictions))
            write_json(args.output, result)
            _report(result["overall"])
        else:
            inputs = load_inputs(args.inputs)
            if args.command == "run-rule":
                records = [{"case_id": case["id"], "raw_output": json.dumps(infer(case["text"]), ensure_ascii=True),
                            "request_error": None, "input_sha256": text_hash(case["text"])} for case in inputs]
                write_jsonl(args.output, parse_records(inputs, records))
                _report({"cases": len(records), "output": str(args.output)})
            elif args.command == "parse-responses":
                records = parse_records(inputs, read_jsonl(args.responses))
                write_jsonl(args.output, records)
                _report({"cases": len(records), "missing_responses": sum(record["request_error"] == "missing_response" for record in records),
                         "parse_failures": sum(record["parse_error"] is not None for record in records), "output": str(args.output)})
            else:
                prompt = args.prompt.read_text(encoding="utf-8")
                requests = build_requests(inputs, prompt)
                if args.command == "build-requests":
                    write_jsonl(args.output, requests)
                else:
                    command = args.adapter[1:] if args.adapter[:1] == ["--"] else args.adapter
                    write_jsonl(args.output, invoke_adapter(requests, command, args.timeout))
                _report({"cases": len(requests), "output": str(args.output)})
    except (OSError, ValueError, TypeError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 2
    return 0
