"""Apply only policy-accepted events to an in-memory workflow state."""
from .schema import timestamp, validate_trace, validate_world


def evidence_satisfies(record, requirement, actors, at):
    if record["type"] != requirement["type"] or timestamp(record["at"]) > at:
        return False
    if "role" in requirement and requirement["role"] not in actors[record["actor_id"]]["roles"]:
        return False
    for key, expected in requirement.get("body", {}).items():
        actual = record["body"].get(key)
        if key not in record["body"] or type(actual) is not type(expected) or actual != expected:
            return False
    return True


def simulate(world, trace):
    validate_world(world)
    validate_trace(trace, world)
    actors = {a["id"]: a for a in world["actors"]}
    records = {r["id"]: r for r in world["records"]}
    states = dict(world["workflow"]["initial_states"])
    completed, decisions = {}, []
    for event in trace["events"]:
        target, action = event["target_id"], event["action"]
        before, at = states[target], timestamp(event["at"])
        rule = next((r for r in world["workflow"]["transitions"] if r["action"] == action and r["from"] == before), None)
        reasons, used = [], []
        if rule is None:
            reasons.append("no transition for action and current state")
        else:
            if rule["role"] not in actors[event["actor_id"]]["roles"]:
                reasons.append(f"actor requires role {rule['role']}")
            for required in rule.get("requires_actions", []):
                if required not in completed.get(target, set()):
                    reasons.append(f"missing earlier accepted action: {required}")
            if "deadline" in rule and at > timestamp(rule["deadline"]):
                reasons.append("action is after the deadline")
            for requirement in rule.get("evidence", []):
                candidates = [i for i in event.get("evidence_ids", [])
                              if evidence_satisfies(records[i], requirement, actors, at)]
                if not candidates:
                    reasons.append(f"missing qualifying evidence: {requirement['type']}")
                else:
                    used.extend(candidates)
        accepted = not reasons
        if accepted:
            states[target] = rule["to"]
            completed.setdefault(target, set()).add(action)
        decisions.append({
            "event_id": event["id"], "action": action, "target_id": target, "actor_id": event["actor_id"],
            "accepted": accepted, "state_before": before, "state_after": states[target],
            "clause": rule["clause"] if rule else None, "reasons": reasons,
            "used_evidence_ids": sorted(set(used)) if accepted else [],
        })
    return {"scenario_id": world["scenario_id"], "decisions": decisions, "final_states": states,
            "accepted": sum(d["accepted"] for d in decisions),
            "rejected": sum(not d["accepted"] for d in decisions)}
