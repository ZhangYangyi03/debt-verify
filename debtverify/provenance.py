"""What produced which number.

Every printed figure in this project is a function of data/zambia_2023.json and
of the code that reads it.  That makes the manifest the load-bearing artefact:
without it, "the verifier found 65 unsupported decisions" is a sentence, and
with it, it is a claim a reader can check by editing one byte.

The manifest is a SHA-256 over the data file plus the code files that touch it.
`verify_manifest` recomputes and compares.  The test suite edits one number and
asserts the manifest notices -- because a manifest that never rejects anything
is decoration.
"""
from __future__ import annotations
import hashlib
import json
import os
from typing import Dict, List

CODE_FILES = ["dsl.py", "vintage.py", "conformal.py", "verifier.py",
              "verifier2.py", "complexity.py", "nowcast.py", "cli.py"]


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()


def code_manifest() -> Dict[str, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    return {c: _sha256(os.path.join(here, c)) for c in CODE_FILES
            if os.path.exists(os.path.join(here, c))}


def manifest(data_path: str) -> Dict[str, object]:
    return {
        "data": os.path.basename(data_path),
        "sha256": _sha256(data_path),
        "bytes": os.path.getsize(data_path),
        "code": code_manifest(),
    }


def verify_manifest(data_path: str, m: Dict[str, object]) -> bool:
    """True only if every hash still matches, data and code alike."""
    try:
        if _sha256(data_path) != m.get("sha256"):
            return False
        cur = code_manifest()
        for k, v in (m.get("code") or {}).items():
            if cur.get(k) != v:
                return False
    except (OSError, TypeError):
        return False
    return True


def tamper(data_path: str, m: Dict[str, object], delta: float = 0.1) -> bool:
    """Edit one number in the data file and report whether it is now detected.

    Returns True only if the edit happened AND went undetected -- which is the
    failure the test asserts cannot occur.
    """
    raw = json.load(open(data_path, encoding="utf-8"))
    series = raw.get("series") or {}
    done = False
    for ind, cells in series.items():
        for k, v in cells.items():
            cells[k] = float(v) + delta
            done = True
            break
        if done:
            break
    if not done:
        return False
    tmp = data_path + ".tampered.tmp"
    json.dump(raw, open(tmp, "w", encoding="utf-8"))
    try:
        still_ok = verify_manifest(tmp, m)
    finally:
        os.remove(tmp)
    return still_ok
