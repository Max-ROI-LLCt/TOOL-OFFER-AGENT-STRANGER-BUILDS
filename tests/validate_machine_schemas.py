"""Validate actual controlled gateway JSON responses against published schemas."""
import json
from pathlib import Path
import sys
from jsonschema import Draft202012Validator


if __name__ == "__main__":
    specification = json.loads((Path(__file__).parents[1] / "site/public/openapi.json").read_text())
    cases = json.load(sys.stdin)
    for case in cases:
        schema = specification["paths"]["/api/machine/" + case["tool"]]["post"]["responses"][str(case["status"])]["content"]["application/json"]["schema"]
        Draft202012Validator({**schema, "components": specification["components"]}).validate(case["body"])
    print("Validated", len(cases), "actual controlled responses")
