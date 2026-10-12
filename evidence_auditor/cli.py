import argparse
import json
import sys
import zipfile
from .audit import audit_package, resolve_citations
from .grading import grade
from .schema import ScenarioError, read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit local SOP evidence and score observable action traces.")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("package")
    scoring = sub.add_parser("grade")
    for name in ("world", "trace", "rubric"):
        scoring.add_argument(name)
    citations = sub.add_parser("citations")
    citations.add_argument("world")
    citations.add_argument("citations")
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            result = audit_package(args.package)
            failed = result["errors"] > 0
        elif args.command == "grade":
            result = grade(read_json(args.world), read_json(args.trace), read_json(args.rubric))
            failed = not result["passed"]
        else:
            rows = resolve_citations(read_json(args.world), read_json(args.citations))
            result, failed = {"citations": rows}, any(not r["valid"] for r in rows)
        print(json.dumps(result, indent=2))
        return int(failed)
    except (ScenarioError, OSError, ValueError, TypeError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
