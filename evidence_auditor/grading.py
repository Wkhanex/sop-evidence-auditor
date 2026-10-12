"""Weighted rubric scoring over recomputed, observable policy decisions."""
from decimal import Decimal, localcontext
from .schema import ScenarioError, validate_world
from .simulation import simulate

KINDS = {"accepted_action", "rejected_action", "final_state", "action_before", "action_absent", "evidence_used"}


def validate_rubric(rubric, world):
    if not isinstance(rubric, dict) or not isinstance(rubric.get("criteria"), list) or not rubric["criteria"]:
        raise ScenarioError("rubric requires a nonempty criteria list")
    threshold = rubric.get("pass_percent", 100)
    if type(threshold) is not int or not 0 <= threshold <= 100:
        raise ScenarioError("pass_percent must be an integer from 0 to 100")
    clauses = {c["id"] for c in world["clauses"]}
    actions = {r["action"] for r in world["workflow"]["transitions"]}
    evidence = {r["id"] for r in world["records"]}
    actors = {a["id"] for a in world["actors"]}
    ids = set()
    for item in rubric["criteria"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] or item["id"] in ids:
            raise ScenarioError("criterion IDs must be unique nonempty strings")
        ids.add(item["id"])
        if item.get("kind") not in KINDS or item.get("clause") not in clauses:
            raise ScenarioError("criterion kind or SOP clause is unknown")
        if type(item.get("weight", 1)) is not int or not 1 <= item.get("weight", 1) <= 100:
            raise ScenarioError("criterion weight must be an integer between 1 and 100")
        if type(item.get("required", False)) is not bool:
            raise ScenarioError("criterion required flag must be boolean")
        if item.get("target_id") not in world["workflow"]["initial_states"]:
            raise ScenarioError("criterion requires an existing target_id")
        if "actor_id" in item and item["actor_id"] not in actors:
            raise ScenarioError("criterion actor_id is unknown")
        if item["kind"] == "final_state":
            states = {r["to"] for r in world["workflow"]["transitions"]} | {r["from"] for r in world["workflow"]["transitions"]}
            if item.get("state") not in states | set(world["workflow"]["initial_states"].values()):
                raise ScenarioError("criterion final state is unknown")
        elif item.get("action") not in actions:
            raise ScenarioError("criterion action is unknown")
        if item["kind"] == "action_before" and item.get("before_action") not in actions:
            raise ScenarioError("before_action is unknown")
        if item["kind"] == "evidence_used" and item.get("evidence_id") not in evidence:
            raise ScenarioError("criterion evidence ID is unknown")
    return rubric


def grade(world, trace, rubric):
    validate_world(world)
    validate_rubric(rubric, world)
    simulation = simulate(world, trace)
    decisions = simulation["decisions"]
    rows = []
    for criterion in rubric["criteria"]:
        relevant = [d for d in decisions if d["target_id"] == criterion["target_id"]
                    and ("actor_id" not in criterion or d["actor_id"] == criterion["actor_id"])]
        matching = [d for d in relevant if d["action"] == criterion.get("action")]
        accepted = [d for d in matching if d["accepted"]]
        kind = criterion["kind"]
        if kind == "accepted_action":
            met, supporting = bool(accepted), accepted or matching
            observation = f"{len(accepted)} accepted {criterion['action']} action(s)"
        elif kind == "rejected_action":
            supporting = [d for d in matching if not d["accepted"]]
            met = bool(supporting)
            observation = f"{len(supporting)} rejected {criterion['action']} action(s)"
        elif kind == "action_absent":
            met, supporting = not matching, matching
            observation = f"{len(matching)} attempt(s) at {criterion['action']}; expected none"
        elif kind == "final_state":
            met = simulation["final_states"][criterion["target_id"]] == criterion["state"]
            supporting = [d for d in relevant if d["accepted"]]
            observation = f"final state {simulation['final_states'][criterion['target_id']]}; expected {criterion['state']}"
        elif kind == "evidence_used":
            supporting = [d for d in accepted if criterion["evidence_id"] in d["used_evidence_ids"]]
            met = bool(supporting)
            observation = f"{len(supporting)} accepted action(s) used {criterion['evidence_id']}"
        else:
            # Every accepted occurrence of the later action needs an earlier accepted prerequisite.
            later = [i for i, d in enumerate(relevant) if d["accepted"] and d["action"] == criterion["before_action"]]
            earlier = [i for i, d in enumerate(relevant) if d["accepted"] and d["action"] == criterion["action"]]
            met = bool(later) and bool(earlier) and all(any(e < l for e in earlier) for l in later)
            supporting = [d for d in relevant if d["accepted"] and d["action"] in {criterion["action"], criterion["before_action"]}]
            observation = f"{len(earlier)} accepted {criterion['action']}; {len(later)} accepted {criterion['before_action']}; required order {'established' if met else 'not established'}"
        rows.append({"id": criterion["id"], "kind": kind, "clause": criterion["clause"], "met": met,
                     "weight": criterion.get("weight", 1), "required": criterion.get("required", False),
                     "supporting_event_ids": [d["event_id"] for d in supporting],
                     "observation": observation})
    earned, possible = sum(r["weight"] for r in rows if r["met"]), sum(r["weight"] for r in rows)
    required_failed = [r["id"] for r in rows if r["required"] and not r["met"]]
    with localcontext() as context:
        context.prec = 40
        percent = str((Decimal(earned) * 100 / Decimal(possible)).quantize(Decimal("0.01")))
    passed = not required_failed and earned * 100 >= rubric.get("pass_percent", 100) * possible
    return {"scenario_id": world["scenario_id"], "passed": passed, "earned_weight": earned,
            "possible_weight": possible, "percent": percent, "required_failed": required_failed,
            "criteria": rows, "simulation": simulation}
