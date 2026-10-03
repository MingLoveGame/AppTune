# Intent Contract Benchmark

A reproducible benchmark for extracting a performance objective and explicit
constraints from an operator description. The repository includes 72 labeled
English examples, a frozen lexical rule baseline, the extraction prompt, response
parsing and validation, and evaluation tools.

The implementation uses Python 3.9 or later and the standard library. Run the
commands below from the repository root. No installation is required.

## Quick start

```bash
python -m intentbench validate-data
python -m intentbench run-rule --output outputs/rule_predictions.jsonl
python -m intentbench evaluate --predictions outputs/rule_predictions.jsonl --output outputs/rule_summary.json
python -m unittest discover -s tests -v
```

These commands validate the release, run the deterministic rule parser on all
72 inputs, compute the scores, and run the tests. Output files are written under
`outputs/`, which is ignored by Git.

## Repository layout

```text
data/
  cases.json               72 descriptions, reference contracts, and rationales
  inputs.json              The same cases with only identifiers and descriptions
  manifest.json            Dataset, prompt, and complete-request hashes
prompts/
  extract_contract.txt     Extraction instructions used to construct requests
intentbench/               Rule parser, response parser, validator, and CLI
examples/
  rule_adapter.py          Local demonstration of the command-adapter interface
results/
  rule_summary.json        Recomputed reference scores for the frozen rules
tests/                     Behavioral and integrity tests
DATASET.md                 Schema, strata, units, authorship, and limitations
LICENSE                    MIT license
```

## Dataset

There are six strata with 12 examples each: explicit objectives, semantic
paraphrases, diagnostic distractors, additional hard constraints, insufficient
or unsupported goals, and conflicts with explicit priority. There are 54
resolvable cases and 18 cases requiring abstention. Each of the six supported
metric bindings appears in nine resolvable cases.

The descriptions and reference labels are agent-authored synthetic examples,
frozen before inference. They are intended to test semantic extraction in a
controlled setting. See [DATASET.md](DATASET.md) for the complete specification.

Use `data/inputs.json` when building requests. It contains only `id` and `text`.
The gold labels and rationales in `data/cases.json` are used during evaluation.
Keep the published labels fixed when comparing methods.

## Rule baseline

The `Rule` method is a frozen, conservative lexical parser. It recognizes
specific phrases for six metrics, extracts known constraint patterns, and
handles selected explicit primary/current-objective markers before generic
metric matching. It resolves a goal only when the selected text has a recognized
optimization cue, exactly one recognized metric, and no recognized conflict.
Otherwise, it abstains while retaining any constraints it extracted.

The implementation preserves the original parser's behavior. It does not use
application names or runtime telemetry to infer a goal. Its limited vocabulary
and handling of phrasing are part of the baseline rather than tuned after
observing the released cases.

| Metric | Correct / eligible | Percentage |
| --- | ---: | ---: |
| Target binding | 14 / 54 | 25.9% |
| Abstention status | 17 / 18 | 94.4% |
| Objective decision | 31 / 72 | 43.1% |
| Exact constraint map | 10 / 72 | 13.9% |
| Exact five-field contract | 4 / 72 | 5.6% |

| Stratum | Exact contracts |
| --- | ---: |
| Explicit objectives | 2 / 12 |
| Semantic paraphrases | 0 / 12 |
| Diagnostic distractors | 1 / 12 |
| Additional hard constraints | 0 / 12 |
| Insufficient/unsupported goals | 1 / 12 |
| Conflicts and priority | 0 / 12 |

The high abstention-status score does not imply complete constraint retention:
only eight of the 17 correct rule abstentions also retain both required
durability and barrier settings. The baseline's behavior should not be
generalized to all possible rule systems.

## Prompt construction

`prompts/extract_contract.txt` contains the extraction instructions. Each request
is constructed as follows:

```python
request = prompt.rstrip() + "\n\nOperator description:\n" + case["text"]
```

The text defines the seven output fields, supported metrics, priority handling,
abstention conditions, constraints, and verbatim evidence requirement. The
prompt body and the 72 assembled requests preserve the evaluated request text;
their hashes are included in the manifest.

Build the requests without invoking any inference service:

```bash
python -m intentbench build-requests --output outputs/requests.jsonl
```

Use an independent context for every case, return one final response per
request, and retain failed attempts. Do not add gold labels or repair a failed
answer. Record the inference configuration and any protocol changes with each
new experiment.

## Running a command adapter

`run-command` provides a transport-neutral interface. For each input it launches
the supplied command as a fresh subprocess, sends the complete request through
standard input, and captures standard output as the raw response. The command
must print only the final response to standard output; use standard error for
diagnostics. Commands run without a shell, and each case receives one attempt.

The included local example executes the same rule baseline through this
interface:

```bash
python -m intentbench run-command --output outputs/adapter_predictions.jsonl -- python examples/rule_adapter.py
python -m intentbench evaluate --predictions outputs/adapter_predictions.jsonl --output outputs/adapter_summary.json
```

For an external inference system, replace the example with your own adapter.
The adapter is responsible for establishing an independent context and applying
the intended generation settings. A fresh subprocess alone does not guarantee
fresh remote context. Keep credentials in your local environment.

## Parsing responses

To import responses produced elsewhere, prepare a JSONL file with one record
per attempted case:

```json
{"case_id":"T001","raw_output":"{\"status\":\"abstain\",\"category\":null,\"metric\":null,\"direction\":null,\"constraints\":{},\"evidence\":\"\",\"reason\":\"Example response.\"}","request_error":null}
```

This record demonstrates the transport format; its example response is not a
valid contract for the case. `raw_output` is the untouched response string.
Use `null` with a nonempty `request_error` for a failed request. An optional
`input_sha256` must match the corresponding input text.

```bash
python -m intentbench parse-responses --responses outputs/responses.jsonl --output outputs/parsed.jsonl
python -m intentbench evaluate --predictions outputs/parsed.jsonl --output outputs/summary.json
```

Parsing follows the original `json.loads` behavior. It does not remove code
fences, extract JSON from surrounding prose, retry, or repair an answer.
Syntactically valid arrays, scalars, and `null` can decode successfully but fail
the contract validator. Standard-library decoding accepts duplicate keys with
the last value taking precedence, and accepts non-finite numeric tokens;
separate validation rejects invalid numeric constraints. Parsing is therefore
distinct from contract acceptance.

The validator checks the seven-field schema, supported metric bindings,
null target fields on abstention, allowed constraint keys, required durability
and barrier settings, positive finite numeric bounds, evidence as an exact
input substring, and the reason's type. These checks do not read reference
labels and do not establish that every stated bound was correctly extracted.

## Evaluation

Scores use the complete dataset with fixed eligibility rules:

- **Target binding:** correct resolved status, category, metric, and direction
  over all 54 reference-resolved cases.
- **Abstention status:** correct abstention status over the 18 reference-abstain
  cases, independently of constraint validity.
- **Objective decision:** target-binding successes plus abstention-status
  successes, over all 72 cases.
- **Exact constraint map:** equality of the complete constraint dictionary,
  over all 72 cases.
- **Exact five-field contract:** equality of status, category, metric, direction,
  and constraints, over all 72 cases. Evidence and reason wording are excluded.

Guard acceptance is reported separately from exact matching. Scores are
descriptive counts on the authored cases, not estimates of storage performance.
Missing records become explicit failed responses and remain in the denominator.
Duplicate identifiers, unknown identifiers, and mismatched input hashes are
rejected. The evaluator reparses raw responses instead of trusting a supplied
`parsed` field. Request and parse failures cannot receive correct scores.

## Reproducibility and contributions

Use a new output directory for each experiment, preserve raw responses, and
report all failures. State any changes to the prompt, inference configuration,
parser, or scoring rules. Do not merge repeat runs into the primary 72-case
denominator. Dataset changes should be versioned separately from new results.

Run the test suite before proposing code changes. A change to the frozen rule
algorithm should be introduced as a separate method so the reference scores
remain reproducible.

## License

Code, data, prompts, and documentation are provided under the
[MIT License](LICENSE).
