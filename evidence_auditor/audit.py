"""Read-only package auditing, with bounded ZIP handling and exact citations."""
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile
from .schema import ScenarioError, canonical, read_json, validate_world

MAX_BYTES = 20 * 1024 * 1024
MAX_MEMBERS = 500


def load_members(path):
    path = Path(path)
    members = {}
    if path.is_dir():
        total = 0
        for item in sorted(path.rglob("*")):
            if item.is_symlink():
                raise ScenarioError("package contains a symlink")
            if not item.is_file() or item.name == "scenario.zip":
                continue
            total += item.stat().st_size
            if total > MAX_BYTES or len(members) >= MAX_MEMBERS:
                raise ScenarioError("package exceeds audit size limits")
            members[item.relative_to(path).as_posix()] = item.read_bytes()
        return members
    with zipfile.ZipFile(path) as archive:
        total = 0
        if len(archive.infolist()) > MAX_MEMBERS:
            raise ScenarioError("ZIP has too many members")
        seen = set()
        for info in archive.infolist():
            if info.flag_bits & 1:
                raise ScenarioError("encrypted ZIP members are not supported")
            parts = PurePosixPath(info.filename)
            if parts.is_absolute() or ".." in parts.parts or "\\" in info.filename or parts.as_posix() != info.filename.rstrip("/"):
                raise ScenarioError("ZIP contains an unsafe path")
            if info.filename.casefold() in seen:
                raise ScenarioError("ZIP contains duplicate case-insensitive members")
            seen.add(info.filename.casefold())
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ScenarioError("ZIP contains a symlink")
            total += info.file_size
            if total > MAX_BYTES or info.file_size > 0 and info.file_size / max(info.compress_size, 1) > 500:
                raise ScenarioError("ZIP exceeds audit size or compression limits")
            if not info.is_dir():
                members[info.filename] = archive.read(info)
    return members


def audit_world(world):
    findings = []
    try:
        validate_world(world)
    except (ScenarioError, TypeError, ValueError) as exc:
        return [{"severity": "error", "code": "invalid_world", "source": "world.json", "detail": str(exc)}]
    actors = world["actors"]
    for index, first in enumerate(actors):
        for second in actors[index + 1:]:
            left, right = first["name"].casefold(), second["name"].casefold()
            ratio = SequenceMatcher(None, left, right).ratio()
            if left == right or ratio >= 0.88:
                findings.append({"severity": "warning", "code": "similar_actor_names", "source": "world.json",
                                 "detail": f"{first['id']} ({first['name']}) and {second['id']} ({second['name']}) need identity review"})
    bodies = {}
    for record in world["records"]:
        key = (record["service"], record["type"], canonical(record["body"]))
        if key in bodies:
            findings.append({"severity": "warning", "code": "duplicate_record_content", "source": record["id"],
                             "detail": f"same body as {bodies[key]}; verify that both records are intentional"})
        bodies[key] = record["id"]
    roles = {role for actor in actors for role in actor["roles"]}
    for rule in world["workflow"]["transitions"]:
        if rule["role"] not in roles:
            findings.append({"severity": "warning", "code": "unavailable_actor_role", "source": rule["clause"],
                             "detail": f"no actor has the role for action {rule['action']}"})
    return findings


def _decode(blob):
    return json.loads(blob.decode("utf-8"),
                      parse_constant=lambda v: (_ for _ in ()).throw(ScenarioError(f"nonfinite JSON value: {v}")))


def audit_package(path):
    path = Path(path)
    if path.suffix.lower() == ".json" and path.is_file():
        world, members = read_json(path), None
    else:
        members = load_members(path)
        if "world.json" not in members:
            raise ScenarioError("package must contain world.json at its root")
        world = _decode(members["world.json"])
    findings = audit_world(world)
    if any(f["severity"] == "error" for f in findings) or members is None:
        return {"scenario_id": world.get("scenario_id") if isinstance(world, dict) else None, "findings": findings,
                "errors": sum(f["severity"] == "error" for f in findings), "warnings": sum(f["severity"] == "warning" for f in findings)}

    def add(code, source, detail, severity="error"):
        findings.append({"severity": severity, "code": code, "source": source, "detail": detail})

    expected_services = {}
    for record in world["records"]:
        expected_services.setdefault(record["service"], []).append(record)
    for service, records in expected_services.items():
        name = f"services/{service}.json"
        try:
            if canonical(_decode(members[name])) != canonical({"records": records}):
                add("service_projection_mismatch", name, "service records differ from world.json")
        except (KeyError, ValueError, UnicodeError) as exc:
            add("missing_or_invalid_service", name, str(exc))
    expected_budget = {"actors": len(world["actors"]), "records": len(world["records"]),
                       "by_service": dict(sorted(Counter(r["service"] for r in world["records"]).items())),
                       "declared_absences": world.get("absences", [])}
    try:
        if canonical(_decode(members["budget.json"])) != canonical(expected_budget):
            add("budget_mismatch", "budget.json", "record counts or absences do not agree with the world")
    except (KeyError, ValueError, UnicodeError) as exc:
        add("missing_or_invalid_budget", "budget.json", str(exc))
    expected_sop = "# Standard operating procedure\n\n" + "\n\n".join(f"## {c['id']}\n\n{c['text']}" for c in world["clauses"]) + "\n"
    if members.get("SOP.md") != expected_sop.encode():
        add("sop_projection_mismatch", "SOP.md", "the exported SOP must preserve every clause verbatim")
    try:
        hashes = _decode(members["checksums.json"])
        if not isinstance(hashes, dict) or set(hashes) != set(members) - {"checksums.json"}:
            add("checksum_inventory_mismatch", "checksums.json", "hash inventory must cover exactly the package files")
        if isinstance(hashes, dict):
            for name, digest in hashes.items():
                if name not in members or hashlib.sha256(members[name]).hexdigest() != digest:
                    add("hash_mismatch", name, "SHA-256 does not match stored digest")
    except (KeyError, ValueError, UnicodeError) as exc:
        add("missing_or_invalid_checksums", "checksums.json", str(exc))
    for name, blob in members.items():
        if re.search(r"answer[_-]?key|gold[_-]?answer|grader[_-]?notes|rubric", name, re.I):
            add("reviewer_material_in_world", name, "reviewer artifacts must remain outside the solver world")
        text = blob.decode("utf-8", errors="replace")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}\b", text):
            add("credential_marker", name, "credential-like material detected; inspect before distributing")
    return {"scenario_id": world["scenario_id"], "findings": findings,
            "errors": sum(f["severity"] == "error" for f in findings),
            "warnings": sum(f["severity"] == "warning" for f in findings)}


def resolve_citations(world, citations):
    validate_world(world)
    sources = {c["id"]: c["text"] for c in world["clauses"]}
    sources.update({r["id"]: canonical(r["body"]).decode() for r in world["records"]})
    if not isinstance(citations, list):
        raise ScenarioError("citations must be a list")
    results = []
    for citation in citations:
        if not isinstance(citation, dict) or not all(isinstance(citation.get(k), str) and citation[k].strip() for k in ("source_id", "quote")):
            raise ScenarioError("citations require source_id and a nonempty exact quote")
        source = sources.get(citation["source_id"])
        results.append({**citation, "valid": source is not None and citation["quote"] in source,
                        "reason": "unknown source" if source is None else "exact substring required"})
    return results
