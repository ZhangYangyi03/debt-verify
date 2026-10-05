"""One writer per case, enforced rather than hoped for.

A verification run that can be started twice concurrently is a verification run
whose output cannot be attributed to a data state.  Both halves of that failure
are real here: the curve in the README is a function of the vintage file, and a
reader must be able to say which file produced which number.

The guard is deliberately in-process and file-backed.  It is not a distributed
lock and does not claim to be: it stops the mistake that actually happens
(two runs over the same case in one process tree, writing the same output
path), and it says so.
"""
from __future__ import annotations
import json
import os
import time
from typing import Dict

_LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".locks")


def _path(case_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in case_id)
    return os.path.join(_LOCK, safe + ".json")


def assert_single_writer(case_id: str, owner: str, allow_takeover: bool = False
                         ) -> Dict[str, object]:
    """Claim the case, or refuse with the current holder named."""
    os.makedirs(_LOCK, exist_ok=True)
    p = _path(case_id)
    if os.path.exists(p):
        cur = json.load(open(p, encoding="utf-8"))
        if cur.get("owner") != owner and not allow_takeover:
            raise RuntimeError(
                f"case {case_id!r} is already held by {cur.get('owner')!r} "
                f"since {cur.get('since')}")
        cur["owner"] = owner
        cur["since"] = cur.get("since") or time.time()
        cur["reentries"] = int(cur.get("reentries", 0)) + 1
        json.dump(cur, open(p, "w", encoding="utf-8"))
        return cur
    rec = {"case_id": case_id, "owner": owner, "since": time.time(),
           "reentries": 0}
    json.dump(rec, open(p, "w", encoding="utf-8"))
    return rec


def release(case_id: str, owner: str) -> bool:
    p = _path(case_id)
    if not os.path.exists(p):
        return False
    cur = json.load(open(p, encoding="utf-8"))
    if cur.get("owner") != owner:
        return False
    os.remove(p)
    return True
