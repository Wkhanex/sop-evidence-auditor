---
name: audit-sop-evidence
description: Audit local SOP worlds and packages, resolve exact evidence citations and score action traces using observable criteria. Use for quality review, package consistency, evidence checks, rubric validation or workflow-run assessment.
---

# Audit SOP evidence

Read [the review contract](references/contract.md). Keep review read-only. Separate structural findings from judgment about the SOP author's rules.

1. Resolve the world or package and run `python <skill-directory>/scripts/run.py audit <package>`.
2. Report errors and warnings with their source IDs. Do not merge similar people or remove repeated records without evidence.
3. When citations are supplied, run `python <skill-directory>/scripts/run.py citations <world-json> <citations-json>`.
4. When a trace and rubric are supplied, run `python <skill-directory>/scripts/run.py grade <world-json> <trace-json> <rubric-json>`.
5. Report the score, required failures, governing clauses and supporting event IDs. State which policy judgments are outside the encoded contract.

Treat exit 1 as completed review with failed checks. Treat exit 2 as invalid input or an operational failure. Do not disable a required criterion to make a run pass. Do not trust acceptance flags embedded in a trace.
