# SOP Evidence Auditor

Audit local SOP scenario packages, resolve exact evidence citations, and grade action traces against observable criteria. Decisions are recomputed from the supplied policy gates rather than trusting a run's claimed success flags.

## Quick start

Python 3.11+; no third-party runtime dependencies.

```bash
python -m pip install -e .
evidence-auditor audit examples/world.json
evidence-auditor citations examples/world.json examples/citations.json
evidence-auditor grade examples/world.json examples/good-trace.json examples/rubric.json
evidence-auditor grade examples/world.json examples/bad-trace.json examples/rubric.json
```

Use `python -m evidence_auditor` from a checkout without installing. The good trace scores `100.00%` and passes. The bad trace scores `28.57%`, fails required criteria, and intentionally returns exit code `1`.

## Package audit

`audit` accepts a world JSON, a scenario directory, or a ZIP produced by SOP Scenario Studio. A raw world JSON receives structural and record checks; a complete package also receives projection, budget, SOP and checksum checks.

| Check | Interpretation |
| --- | --- |
| IDs, links, roles, states, offset timestamps | Invalid structure is an error |
| Future evidence and contradictory declared absences | Invalid snapshot is an error |
| Service projections, record budget, SOP export | Differences from `world.json` are errors |
| Checksum inventory and SHA-256 values | Missing or changed package bytes are errors |
| Reviewer filenames or credential markers in the world | Distribution issue requiring inspection |
| Similar actor names and identical record bodies | Warnings for review, not automatic identity merges |

ZIPs are read without extraction. Unsafe paths, symlinks, duplicate case-insensitive names, encrypted members and excessive sizes/compression ratios are rejected. The limits are 500 members, 20 MiB total uncompressed bytes and a maximum per-member ratio of 500.

```bash
evidence-auditor audit ../sop-scenario-studio/output/demo
evidence-auditor audit ../sop-scenario-studio/output/demo/scenario.zip
```

Hashes detect changes relative to the author-provided inventory; an author able to alter both files and inventory can still rewrite a package.

## Observable grading

Every criterion cites an existing SOP clause and workflow target, has an integer weight, and may be required.

| Kind | Observation |
| --- | --- |
| `accepted_action` | At least one qualifying action was accepted |
| `rejected_action` | At least one specified action was rejected |
| `final_state` | Recomputed target state equals the required value |
| `action_before` | Each accepted later action has an earlier accepted prerequisite |
| `action_absent` | The trace contains no attempt at the action, including rejected attempts |
| `evidence_used` | An accepted action used a specific qualifying evidence record |

The result includes supporting event IDs, earned and possible weights, a percentage and failed required criteria. Passing requires both the percentage threshold and every required criterion. Percentage display is rounded to two decimals; the threshold uses the exact weight ratio.

The grader does not evaluate hidden reasoning, natural-language judgment, actual email contents or live application state. The workflow rules must encode the policy being assessed. [Rubric contract](docs/rubric-contract.md).

## Citations

Each citation declares a `source_id` and a nonempty exact `quote`. Sources are SOP clause text or canonical JSON record bodies. Matching is case-sensitive, with no fuzzy substitution. Missing sources and absent quoted substrings fail the check.

## Codex skill

Portable and Codex-compatible manifests make this a skills-only plugin. Install the Python package before copying `skills/audit-sop-evidence` into a supported skills location, or retain the complete repository as the local plugin source.

Use `$audit-sop-evidence` with the package and, when available, a trace and rubric. The wrapper runs without installation from a checkout:

```bash
python skills/audit-sop-evidence/scripts/run.py audit examples/world.json
```

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q evidence_auditor tests skills
```

CI runs tests and examples on Python 3.11, 3.12 and 3.13. Exit codes: `0` pass/no audit errors, `1` completed audit/grade/citation check failed, `2` invalid input or operational error. Warnings alone do not fail an audit.

[Reference notes](docs/reference-notes.md). MIT license.
