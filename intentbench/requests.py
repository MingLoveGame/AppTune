"""Construct label-free prompts and optionally call a user-supplied adapter."""

import datetime
import subprocess
import time

from .contracts import positive_finite_number
from .dataset import text_hash


def compose_prompt(prompt, text):
    return prompt.rstrip() + "\n\nOperator description:\n" + text


def build_requests(inputs, prompt):
    return [
        {"case_id": case["id"], "input_sha256": text_hash(case["text"]),
         "full_prompt_sha256": text_hash(compose_prompt(prompt, case["text"])),
         "prompt": compose_prompt(prompt, case["text"])}
        for case in inputs
    ]


def _decode_partial(value):
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def invoke_adapter(requests, command, timeout=240):
    """Yield one recorded attempt per input, with a fresh subprocess and no retry."""
    if not command or not all(isinstance(part, str) for part in command):
        raise ValueError("An adapter command is required after --")
    if not positive_finite_number(timeout):
        raise ValueError("Timeout must be positive and finite")
    for request in requests:
        record = {key: request[key] for key in ("case_id", "input_sha256", "full_prompt_sha256")}
        record.update(request_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      raw_output="", stderr="", returncode=None, timed_out=False, request_error=None)
        start = time.perf_counter()
        try:
            # Bytes avoid platform newline translation. The adapter must return UTF-8.
            completed = subprocess.run(command, input=request["prompt"].encode("utf-8"),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=timeout, shell=False, check=False)
            record["returncode"] = completed.returncode
            record["stderr"] = completed.stderr.decode("utf-8", errors="replace")
            try:
                record["raw_output"] = completed.stdout.decode("utf-8")
            except UnicodeDecodeError:
                record["raw_output"] = completed.stdout.decode("utf-8", errors="replace")
                record["request_error"] = "response_encoding_error"
            if completed.returncode != 0:
                record["request_error"] = "request_exit_failure"
        except subprocess.TimeoutExpired as exc:
            record.update(timed_out=True, request_error="request_timeout",
                          raw_output=_decode_partial(exc.stdout), stderr=_decode_partial(exc.stderr))
        except OSError as exc:
            record["request_error"] = type(exc).__name__ + ": " + str(exc)
        record["latency_s"] = time.perf_counter() - start
        yield record
