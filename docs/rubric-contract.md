# Rubric and source contract

Use `criteria` as a nonempty array and optional integer `pass_percent` from 0 to 100, default 100. Each criterion requires unique nonempty `id`, supported `kind`, existing `target_id` and existing SOP `clause`. Optional `weight` is an integer from 1 to 100, default 1; `required` is boolean, default false.

All kinds except `final_state` require a known `action`. `final_state` requires a known `state`. `action_before` additionally requires `before_action`. `evidence_used` requires an existing `evidence_id`.

Optional `actor_id` restricts action observations to that existing actor. Final-state observations still use the actual target state. Use an actor scope for an absence criterion when another role is permitted to perform the action.

Grading first validates the world, rubric and complete trace, then reruns the policy simulator. Extra claimed `accepted` values on trace events have no effect. Accepted prerequisites and qualifying evidence are target-scoped through explicit workflow rules. Criteria cannot inspect facts that are absent from this contract.

Clause citations tie criteria to source text; they do not prove that the author encoded that clause correctly. Review the SOP prose, JSON gates and rubric together. The tool does not assess human understanding or derive accounting, legal or procedural judgments from text.

The independent scenario contract uses actors, records, clauses, workflow transitions and declared absences. All evidence is dated at or before the snapshot clock. Trace events occur at or after that clock, in supplied chronological order. Rejected events do not advance states. Evidence body values and types must agree exactly.

Raw world audits do not verify companion files that were not supplied. Directory and ZIP audits require `world.json`, `SOP.md`, `budget.json`, per-service projections and a complete `checksums.json` inventory. The convenience `scenario.zip` is ignored when auditing an unpacked directory.
