"""Verify released bytes, canonical case content, and every assembled request."""

import hashlib
import json
from pathlib import Path

from .dataset import ROOT, load_inputs, load_json, validate_cases
from .requests import build_requests


def validate_release(root=ROOT):
    root = Path(root).resolve()
    manifest = load_json(root / "data" / "manifest.json")
    required_files = {"data/cases.json", "data/inputs.json", "prompts/extract_contract.txt"}
    if set(manifest.get("files_sha256", {})) != required_files:
        raise ValueError("Manifest must identify all three released input files")
    for relative, expected in manifest["files_sha256"].items():
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("Released file hash mismatch: " + relative)
    data = load_json(root / "data" / "cases.json")
    inputs = load_inputs(root / "data" / "inputs.json")
    summary = validate_cases(data, inputs)
    canonical = json.dumps(data["cases"], ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != manifest.get("case_payload_sha256"):
        raise ValueError("Canonical case payload hash mismatch")
    if manifest.get("sample_count") != len(inputs):
        raise ValueError("Manifest sample count mismatch")
    prompt = (root / "prompts" / "extract_contract.txt").read_text(encoding="utf-8")
    hashes = {record["case_id"]: record["full_prompt_sha256"] for record in build_requests(inputs, prompt)}
    if hashes != manifest.get("request_sha256"):
        raise ValueError("Assembled request hashes differ from the release manifest")
    summary["integrity"] = {"files_verified": len(required_files), "requests_verified": len(hashes),
                            "canonical_case_payload_verified": True}
    return summary
