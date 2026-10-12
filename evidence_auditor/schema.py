"""Shared interchange contract for local scenarios and observable action traces."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re


class ScenarioError(ValueError):
    pass


def timestamp(value):
    if not isinstance(value, str):
        raise ScenarioError("timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScenarioError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScenarioError("timestamps must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          parse_constant=lambda v: (_ for _ in ()).throw(ScenarioError(f"nonfinite JSON value: {v}")))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ScenarioError(f"invalid JSON: {path}: {exc}") from exc


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _records(items, label):
    if not isinstance(items, list):
        raise ScenarioError(f"{label} must be a list")
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", item["id"]):
            raise ScenarioError(f"{label} records require safe nonempty IDs")
        if item["id"] in result:
            raise ScenarioError(f"duplicate {label} ID: {item['id']}")
        result[item["id"]] = item
    return result


def validate_world(world):
    if not isinstance(world, dict) or type(world.get("schema_version")) is not int or world["schema_version"] != 1:
        raise ScenarioError("world schema_version must be 1")
    if not isinstance(world.get("scenario_id"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", world["scenario_id"]):
        raise ScenarioError("scenario_id must be a lowercase slug")
    clock = timestamp(world.get("clock"))
    actors = _records(world.get("actors"), "actor")
    for actor in actors.values():
        if not isinstance(actor.get("name"), str) or not actor["name"].strip():
            raise ScenarioError("actors require a display name")
        roles = actor.get("roles")
        if not isinstance(roles, list) or not roles or not all(isinstance(r, str) and r for r in roles):
            raise ScenarioError("actor roles must be nonempty strings")
    records = _records(world.get("records"), "record")
    for record in records.values():
        if record.get("actor_id") not in actors:
            raise ScenarioError(f"{record['id']}: unknown actor")
        if not isinstance(record.get("service"), str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", record["service"]):
            raise ScenarioError("record service must be a safe lowercase name")
        if not isinstance(record.get("type"), str) or not record["type"]:
            raise ScenarioError("record type must be a nonempty string")
        if timestamp(record.get("at")) > clock:
            raise ScenarioError(f"{record['id']}: evidence is after the world clock")
        if not isinstance(record.get("body"), dict):
            raise ScenarioError("record body must be an object")
        refs = record.get("refs", [])
        if not isinstance(refs, list) or not all(isinstance(r, str) and r in records for r in refs):
            raise ScenarioError(f"{record['id']}: dangling record reference")
    clauses = _records(world.get("clauses"), "clause")
    if set(clauses) & set(records):
        raise ScenarioError("clause and record IDs must be distinct for citations")
    if not clauses or any(not isinstance(c.get("text"), str) or not c["text"].strip() for c in clauses.values()):
        raise ScenarioError("clauses require nonempty text")
    workflow = world.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("initial_states"), dict):
        raise ScenarioError("workflow requires initial_states")
    for target, state in workflow["initial_states"].items():
        if target not in records or not isinstance(state, str) or not state:
            raise ScenarioError("workflow states require existing targets and nonempty state strings")
    transitions = workflow.get("transitions")
    if not isinstance(transitions, list) or not transitions:
        raise ScenarioError("workflow requires transitions")
    transition_keys = set()
    for rule in transitions:
        if not isinstance(rule, dict) or not all(isinstance(rule.get(k), str) and rule[k] for k in ("action", "from", "to", "role", "clause")):
            raise ScenarioError("transitions require action/from/to/role/clause strings")
        key = (rule["action"], rule["from"])
        if key in transition_keys:
            raise ScenarioError("duplicate action/from transition")
        transition_keys.add(key)
        if rule["clause"] not in clauses:
            raise ScenarioError("transition cites an unknown SOP clause")
        requirements = rule.get("evidence", [])
        if not isinstance(requirements, list):
            raise ScenarioError("transition evidence must be a list")
        for requirement in requirements:
            if not isinstance(requirement, dict) or not isinstance(requirement.get("type"), str) or not requirement["type"]:
                raise ScenarioError("evidence requirements need a type")
            if "body" in requirement and not isinstance(requirement["body"], dict):
                raise ScenarioError("evidence requirement body must be an object")
            if "role" in requirement and not isinstance(requirement["role"], str):
                raise ScenarioError("evidence requirement role must be a string")
        prerequisites = rule.get("requires_actions", [])
        if not isinstance(prerequisites, list) or not all(isinstance(a, str) and a for a in prerequisites):
            raise ScenarioError("requires_actions must be a list of action names")
        if "deadline" in rule:
            timestamp(rule["deadline"])
    action_names = {r["action"] for r in transitions}
    if any(a not in action_names for r in transitions for a in r.get("requires_actions", [])):
        raise ScenarioError("unknown prerequisite action")
    absences = world.get("absences", [])
    if not isinstance(absences, list):
        raise ScenarioError("absences must be a list")
    for absence in absences:
        if not isinstance(absence, dict) or not all(isinstance(absence.get(k), str) and absence[k] for k in ("service", "type", "reason")):
            raise ScenarioError("absences require service/type/reason")
        if any(r["service"] == absence["service"] and r["type"] == absence["type"] for r in records.values()):
            raise ScenarioError("a declared absence contains a record")
    canonical(world)
    return world


def validate_trace(trace, world):
    if not isinstance(trace, dict) or not isinstance(trace.get("events"), list):
        raise ScenarioError("trace requires an events list")
    events = _records(trace["events"], "event")
    actors = {a["id"] for a in world["actors"]}
    records = {r["id"] for r in world["records"]}
    previous = timestamp(world["clock"])
    for event in events.values():
        current = timestamp(event.get("at"))
        if current < previous:
            raise ScenarioError("events must be chronological and not before the world clock")
        previous = current
        if event.get("actor_id") not in actors or event.get("target_id") not in world["workflow"]["initial_states"]:
            raise ScenarioError("event has an unknown actor or workflow target")
        if not isinstance(event.get("action"), str) or not event["action"]:
            raise ScenarioError("event requires an action")
        evidence = event.get("evidence_ids", [])
        if not isinstance(evidence, list) or not all(isinstance(i, str) and i in records for i in evidence) or len(set(evidence)) != len(evidence):
            raise ScenarioError("event contains unknown or duplicate evidence IDs")
    return trace
