"""Demonstrate the command interface using the local frozen rule baseline.

Read one complete request on standard input and write one response JSON object
on standard output. This example makes no network requests and reads no labels.
"""
from pathlib import Path
import json
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentbench.rule import infer


def main():
    request = sys.stdin.read()
    marker = "\n\nOperator description:\n"
    if marker not in request:
        raise ValueError("Request is missing the operator-description delimiter")
    _, text = request.split(marker, 1)
    print(json.dumps(infer(text), ensure_ascii=True))


if __name__ == "__main__":
    main()
