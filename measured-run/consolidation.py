"""Rebuild the exact cross-session consolidation request derive-history makes (dev loop only).

Needs the brain-core source on sys.path (PYTHONPATH=<core>/src or --core). The request is
built from the same pieces the product uses: session time from the imported file, the cached
digest, the interval-date check and timeline order. Its cache file name is the product's
content address, so a precomputed output can be dropped straight into a repository's cache.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

CACHE = Path.home() / "lme95/consolidate-cache"
DIGESTS = Path.home() / "lme95/digest-cache"


def use_core(core: str | None) -> None:
    if core:
        sys.path.insert(0, str(Path(core) / "src"))


def digest_for(text: str) -> list[str]:
    pre = DIGESTS / f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}-v1.json"
    if not pre.exists():
        return []
    return json.loads(pre.read_text(encoding="utf-8"))["observations"]


def entries_for(files: list[tuple[str, str]]):
    """``files`` is ``[(repo-relative path, exact file text)]`` for one history folder."""
    from brain_gateway.history.dates import check_dates
    from brain_gateway.history.digest import TimelineEntry, ordered, session_time
    from brain_gateway.memory.metadata import parse as metadata
    entries = []
    for rel, text in files:
        fm, body, _ = metadata(text)
        stamp = session_time(body, fm)
        entries.append(TimelineEntry(rel, stamp, check_dates(digest_for(text), text, stamp)))
    return ordered(entries)


def request_for(files):
    """``(request, cache file name, entries)``; request is None when nothing to consolidate."""
    from brain_gateway.history import consolidate
    from brain_gateway.history.cache import consolidation_path
    entries = entries_for(files)
    request = consolidate.build_request(entries)
    name = consolidation_path(Path("/"), request).name if request else None
    return request, name, entries


def cached_output(name: str | None) -> str | None:
    if not name or not (CACHE / name).exists():
        return None
    return json.loads((CACHE / name).read_text(encoding="utf-8"))["output"]
