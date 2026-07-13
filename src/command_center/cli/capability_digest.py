#!/usr/bin/env python3
"""
capability_digest.py — recompute and verify capability provenance digests.

The capability catalog (configs/capabilities.yaml) records, for tamper-relevant
capabilities, a `digest` over the local artifact each one is backed by. The
Pydantic contract *requires* that digest to be present (digest_required_for);
this module is the other half — it *recomputes* the hash from the artifact on
disk and fails if it has drifted from the recorded value. Together they turn
"declared provenance" into "verified provenance".

Hashing rules (one function, used both to verify and to generate, so the two can
never disagree):
  * `path#dotted.fragment` into a .yaml/.yml/.json file -> hash a canonical JSON
    dump of just that sub-tree, so an unrelated edit elsewhere in the file does
    not trip the digest, and the pin is precise about what it covers.
  * any other local file -> hash the raw file bytes.
  * remote (URL) / opaque (scheme:opaque) refs -> not hashable here; skipped.

Usage:
  python -m command_center.cli.capability_digest            # print computed digests (operator helper)
  python -m command_center.cli.capability_digest --check    # verify; exit 1 on drift
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

from command_center.schemas import CapabilityCatalogConfig
from command_center.schemas.contracts import (
    digest_required_for,
    source_ref_kind,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = "configs/capabilities.yaml"
_STRUCTURED_SUFFIXES = {".yaml", ".yml", ".json"}


def _resolve_fragment(data, fragment: str, source_ref: str):
    """Walk a dotted #fragment (e.g. `tools.github`) into a loaded YAML/JSON doc.
    List indices are addressed by their integer position (`servers.0.name`)."""
    node = data
    for key in fragment.split("."):
        if isinstance(node, dict):
            if key not in node:
                raise KeyError(f"fragment '{fragment}' has no key '{key}' in {source_ref}")
            node = node[key]
        elif isinstance(node, list):
            if not key.isdigit() or int(key) >= len(node):
                raise KeyError(f"fragment '{fragment}' index '{key}' out of range in {source_ref}")
            node = node[int(key)]
        else:
            raise KeyError(f"fragment '{fragment}' cannot descend into '{key}' in {source_ref}")
    return node


def compute_artifact_digest(source_ref: str, root: Path = ROOT) -> str:
    """Return the `sha256:<hex>` digest for a local provenance source_ref.

    Raises ValueError for non-local refs (callers should classify first),
    FileNotFoundError if the artifact is missing, and guards against a ref that
    escapes the repository root.
    """
    if source_ref_kind(source_ref) != "local":
        raise ValueError(f"source_ref {source_ref!r} is not a local artifact; cannot hash")
    base, _, fragment = source_ref.partition("#")
    root = root.resolve()
    path = (root / base).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source_ref {source_ref!r} escapes the repository root") from exc
    if not path.is_file():
        raise FileNotFoundError(f"source_ref {source_ref!r} points at a missing file: {path}")

    if fragment and path.suffix.lower() in _STRUCTURED_SUFFIXES:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        node = _resolve_fragment(loaded, fragment, source_ref)
        payload = json.dumps(
            node, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    else:
        payload = path.read_bytes()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def verify_capability_digests(catalog: CapabilityCatalogConfig, root: Path = ROOT) -> list[str]:
    """Recompute every recorded digest and return drift/error messages (empty = clean).

    The schema already guarantees in-scope local refs *have* a digest; this proves
    each recorded digest still *matches* the artifact on disk. A digest pinned on a
    non-local ref is reported too — it can't be verified and is therefore meaningless.
    """
    problems: list[str] = []
    for entry in catalog.entries:
        for prov in entry.provenance:
            if not prov.digest:
                continue
            kind = source_ref_kind(prov.source_ref)
            if kind != "local":
                problems.append(
                    f"{entry.identifier}: digest pinned on {kind} ref "
                    f"{prov.source_ref!r}, which cannot be verified locally")
                continue
            try:
                actual = compute_artifact_digest(prov.source_ref, root)
            except (FileNotFoundError, ValueError, KeyError) as exc:
                problems.append(f"{entry.identifier}: {exc}")
                continue
            if actual != prov.digest:
                problems.append(
                    f"{entry.identifier}: digest drift for {prov.source_ref!r} "
                    f"(recorded {prov.digest}, actual {actual})")
    return problems


def _load_catalog(root: Path = ROOT) -> CapabilityCatalogConfig:
    data = yaml.safe_load((root / CATALOG_PATH).read_text(encoding="utf-8"))
    return CapabilityCatalogConfig.model_validate(data)


def _print_digests(root: Path = ROOT) -> int:
    """Operator helper: compute and print the digest for every in-scope local
    provenance ref. Reads the raw YAML (not the validated model) so it still works
    while a required digest is missing — i.e. so you can bootstrap a new entry."""
    data = yaml.safe_load((root / CATALOG_PATH).read_text(encoding="utf-8"))
    ok = True
    printed = 0
    for entry in data.get("entries", []):
        if not digest_required_for(entry.get("type", ""), entry.get("risk_tier")):
            continue
        for prov in entry.get("provenance", []):
            ref = prov.get("source_ref", "")
            if source_ref_kind(ref) != "local":
                continue
            try:
                digest = compute_artifact_digest(ref, root)
            except (FileNotFoundError, ValueError, KeyError) as exc:
                print(f"  ERROR  {entry.get('identifier')}  {ref}: {exc}")
                ok = False
                continue
            print(f"  {digest}  {ref}  ({entry.get('identifier')})")
            printed += 1
    if printed == 0 and ok:
        print("  (no in-scope local provenance refs)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        problems = verify_capability_digests(_load_catalog())
        for msg in problems:
            print(f"  DIGEST-DRIFT: {msg}")
        print("capability-digests: PASS" if not problems else "capability-digests: FAIL")
        return 0 if not problems else 1
    return _print_digests()


if __name__ == "__main__":
    sys.exit(main())
