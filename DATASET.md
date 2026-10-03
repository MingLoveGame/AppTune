# Dataset specification

The benchmark contains 72 English operator descriptions and authored reference
contracts. The case identifiers are `T001` through `T072`. All case records,
including input text, labels, evidence, reasons, and authoring rationales, are
preserved from the frozen test set. Release metadata is stored separately from
the case payload.

## Origin and scope

The cases were authored by an agent from the output interface specification.
The author had no access to the evaluated prompts, predictions, prior examples,
or scoring implementation. Reference labels represent normative expectations
and were frozen before inference. The examples are synthetic scenarios rather
than sampled production requests.

The number 72 refers to examples. The interface supports six metric bindings
across four objective categories. It contains 54 resolvable examples and 18
examples that require abstention. Each supported metric has nine resolvable
examples.

## Strata

| Identifier | Purpose | Resolved | Abstain | Total |
| --- | --- | ---: | ---: | ---: |
| `explicit` | Explicitly stated performance objectives | 12 | 0 | 12 |
| `label_masked` | Semantic descriptions without canonical metric labels | 12 | 0 | 12 |
| `distractor` | Diagnostic, historical, or secondary metrics around a primary goal | 12 | 0 | 12 |
| `constrained` | Performance objectives with additional hard bounds | 12 | 0 | 12 |
| `insufficient` | Missing, underspecified, deferred, or unsupported objectives | 0 | 12 | 12 |
| `conflict_priority` | Equal-priority conflicts and explicit priority selection | 6 | 6 | 12 |
| **Total** | | **54** | **18** | **72** |

The first four strata each contain two examples per metric. The final stratum
contains one resolvable example per metric and six equal-priority conflicts.

## Record format

`data/cases.json` contains a `cases` array. Each record has these fields:

| Field | Meaning |
| --- | --- |
| `id` | Stable case identifier |
| `group` | Stratum identifier |
| `text` | Operator description supplied to an extractor |
| `gold` | Authored reference output |
| `rationale` | Explanation of the reference interpretation |

`data/inputs.json` contains the same identifiers and descriptions, with only
`id` and `text` in each record. Use this file for inference. Reference labels
are joined only during evaluation.

## Output contract

A response is one JSON object with exactly seven fields:

```json
{
  "status": "resolved",
  "category": "throughput",
  "metric": "tps",
  "direction": "max",
  "constraints": {"durability": "sync", "barriers": "on"},
  "evidence": "maximize transaction throughput, measured as completed transactions per second",
  "reason": "The stated objective maximizes completed transactions per second."
}
```

The example's evidence is a verbatim substring of case `T001`. Valid metric
bindings are:

| Category | Metric | Direction | Measurement |
| --- | --- | --- | --- |
| `throughput` | `tps` | `max` | Completed transactions per second |
| `throughput` | `ops_s` | `max` | Operations or requests per second |
| `tail_latency` | `p95_ms` | `min` | 95th-percentile request latency, milliseconds |
| `tail_latency` | `p99_ms` | `min` | 99th-percentile request latency, milliseconds |
| `completion_time` | `completion_s` | `min` | Duration of a fixed job, seconds |
| `stability` | `throughput_cv` | `min` | Standard deviation divided by mean throughput in fixed one-second windows |

For `status="abstain"`, `category`, `metric`, and `direction` are all `null`.
Explicit constraints must still be retained. Abstention applies to unsupported
or ambiguous objectives, including equal-priority objectives without a rule
for selecting a single target. Diagnostic metrics and hard bounds do not
replace an explicitly selected primary objective.

Evidence must be a nonempty exact substring of the input. It may support the
operative objective or the reason for abstention; it need not repeat every
constraint. A short reason explains the decision.

## Constraints and units

| Key | Meaning |
| --- | --- |
| `durability` | `"sync"` for synchronous durability |
| `barriers` | `"on"` for enabled write barriers |
| `commit_max_s` | Maximum commit interval, seconds |
| `p95_max_ms` | Maximum P95 latency, milliseconds |
| `p99_max_ms` | Maximum P99 latency, milliseconds |
| `throughput_min` | Explicit minimum transaction or operation rate |
| `cv_max` | Maximum throughput coefficient of variation |

All descriptions explicitly require synchronous durability and enabled write
barriers, including descriptions requiring abstention. Other keys are present
only when the description states the corresponding bound. Numeric values are
JSON numbers rather than strings or booleans. Conversions use only explicitly
stated seconds/milliseconds relationships.

The count semantics of `throughput_min` come from the description. The interface
does not include a separate unit field, so these bounds cannot be combined
across cases without reading their transaction/operation semantics.

## Interpretation limits

This is a controlled semantic extraction benchmark. It does not measure
configuration execution, data recovery, storage performance, or deployment
reliability. Uniform durability/barrier requirements leave behavior on absent
constraints untested. The authored scenarios cannot establish accuracy on
production traffic. The lexical baseline is deliberately conservative and
does not represent the strongest possible rule system.

## Integrity and versioning

`data/manifest.json` stores hashes for the released files, the canonical case
payload, and every complete request. The complete request is the prompt with
trailing whitespace removed, followed by two newlines, `Operator description:`,
one newline, and the unchanged case text. All 72 complete-request hashes were
checked against the preserved request records during export.

Keep released examples and labels unchanged when adding experiments. Corrections
or new cases should receive a new dataset version and an explicit change record.

The data, prompt, code, and documentation are distributed under the repository's
[MIT License](LICENSE).
