#!/usr/bin/env python3
"""Validate firewall-lab company manifests against schema/company.schema.json.

Stdlib only — no jsonschema, no PyYAML. Implements the subset of JSON Schema
draft-07 the company schema uses (type, required, additionalProperties, enum,
const, pattern, minItems, minLength, minimum, maximum, $ref, oneOf, default).

Usage:
    python3 firewall-lab/scripts/validate.py                 # all companies
    python3 firewall-lab/scripts/validate.py acme-academy    # one company
Exit code is non-zero if any company fails.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "company.schema.json"
COMPANIES = ROOT / "companies"
# /firewall/<slug>/ is a company page; these paths are the dashboard's own.
RESERVED_SLUGS = ("device", "devices")


def load(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


class Validator:
    def __init__(self, schema: dict):
        self.schema = schema
        self.defs = schema.get("definitions", {})
        self.errors: list[str] = []

    def resolve(self, node: dict) -> dict:
        ref = node.get("$ref")
        if ref and ref.startswith("#/definitions/"):
            return self.defs[ref.split("/")[-1]]
        return node

    def check(self, node: dict, value, path: str):
        node = self.resolve(node)

        if "oneOf" in node:
            matches = 0
            for sub in node["oneOf"]:
                probe = Validator(self.schema)
                probe.check(sub, value, path)
                if not probe.errors:
                    matches += 1
            if matches != 1:
                self.errors.append(f"{path}: must match exactly one allowed form (matched {matches})")
            return

        if "const" in node and value != node["const"]:
            self.errors.append(f"{path}: must equal {node['const']!r}, got {value!r}")
            return

        if "enum" in node and value not in node["enum"]:
            self.errors.append(f"{path}: {value!r} not in {node['enum']}")
            return

        t = node.get("type")
        if t and not self._type_ok(t, value):
            self.errors.append(f"{path}: expected {t}, got {type(value).__name__}")
            return

        if t == "object" or (t is None and isinstance(value, dict) and "properties" in node):
            self._object(node, value, path)
        elif t == "array":
            self._array(node, value, path)
        elif t == "string":
            self._string(node, value, path)
        elif t in ("integer", "number"):
            self._number(node, value, path)

    def _type_ok(self, t: str, value) -> bool:
        if t == "object":
            return isinstance(value, dict)
        if t == "array":
            return isinstance(value, list)
        if t == "string":
            return isinstance(value, str)
        if t == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if t == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if t == "boolean":
            return isinstance(value, bool)
        return True

    def _object(self, node: dict, value: dict, path: str):
        props = node.get("properties", {})
        for req in node.get("required", []):
            if req not in value:
                self.errors.append(f"{path}: missing required field {req!r}")
        if node.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    self.errors.append(f"{path}: unknown field {key!r}")
        for key, sub in props.items():
            if key in value:
                self.check(sub, value[key], f"{path}.{key}" if path else key)

    def _array(self, node: dict, value: list, path: str):
        if "minItems" in node and len(value) < node["minItems"]:
            self.errors.append(f"{path}: needs at least {node['minItems']} item(s), got {len(value)}")
        item_schema = node.get("items")
        if item_schema:
            for i, item in enumerate(value):
                self.check(item_schema, item, f"{path}[{i}]")

    def _string(self, node: dict, value: str, path: str):
        if "minLength" in node and len(value) < node["minLength"]:
            self.errors.append(f"{path}: shorter than {node['minLength']} chars")
        pat = node.get("pattern")
        if pat and not re.search(pat, value):
            self.errors.append(f"{path}: {value!r} does not match /{pat}/")

    def _number(self, node: dict, value, path: str):
        if "minimum" in node and value < node["minimum"]:
            self.errors.append(f"{path}: {value} < minimum {node['minimum']}")
        if "maximum" in node and value > node["maximum"]:
            self.errors.append(f"{path}: {value} > maximum {node['maximum']}")


def validate_company(folder: Path, schema: dict) -> list[str]:
    manifest = folder / "company.json"
    if not manifest.exists():
        return [f"{folder.name}: no company.json"]
    try:
        data = load(manifest)
    except json.JSONDecodeError as exc:
        return [f"{folder.name}: invalid JSON — {exc}"]

    v = Validator(schema)
    v.check(schema, data, "")
    errors = list(v.errors)

    # Cross-checks the schema cannot express.
    if folder.name in RESERVED_SLUGS:
        errors.append(f"folder name {folder.name!r} is taken by a Firewall Lab page; pick another slug")
    if data.get("slug") != folder.name:
        errors.append(f"slug {data.get('slug')!r} must equal folder name {folder.name!r}")
    for b in data.get("branches", []) if isinstance(data.get("branches"), list) else []:
        for fw in b.get("firewalls", []) if isinstance(b.get("firewalls"), list) else []:
            if isinstance(fw.get("alternatives"), list) and isinstance(fw.get("chosen"), dict):
                total = len(fw["alternatives"]) + 1
                if total < 5:
                    errors.append(
                        f"branch {b.get('id')} / {fw.get('segment')}: top-5 expected "
                        f"(chosen + {len(fw['alternatives'])} alternatives = {total})"
                    )
    return errors


def main(argv: list[str]) -> int:
    schema = load(SCHEMA_PATH)
    targets = (
        [COMPANIES / name for name in argv]
        if argv
        else sorted(p for p in COMPANIES.iterdir() if p.is_dir())
    )
    failed = 0
    for folder in targets:
        errors = validate_company(folder, schema)
        if errors:
            failed += 1
            print(f"✗ {folder.name}")
            for e in errors:
                print(f"    {e}")
        else:
            print(f"✓ {folder.name}")
    print()
    if failed:
        print(f"{failed} company/companies failed validation.")
        return 1
    print("All companies valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
