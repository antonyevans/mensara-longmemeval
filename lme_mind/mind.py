"""Import, wait for and clear one question's conversation history in the owner's Mind.

Everything goes through the owner's normal MCP tools. Session files are written with
`propose_write`; the Mind's own history timer (every five minutes) then writes the dated
digest and timeline with the Mind's own model connection. Deletes never auto-apply in a
Mind, so clearing proposes them and the signed-in owner approves its own card.

The harness only ever deletes files it imported itself (recorded in a ledger in the run
folder) and the timeline pages the Mind derived from them. It refuses to start if the history
folder holds anything else, unless the caller names that folder in --wipe-existing-history.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .mcp import Mind, MindError

# A proposal carries at most 20 files and 1 MiB (the Mind's airlock limits).
BATCH_FILES = 20
BATCH_BYTES = 900_000
GENERATED = {"_index.md", "_summary.md"}
DERIVED = "derived from imported conversation history"
HISTORY = re.compile(r"22-memory/recalls/[0-9a-f]{64}/history")


class Ledger:
    """Paths this harness imported, kept in the run folder so a resumed run can clear them."""

    def __init__(self, run: Path):
        self.path = run / ".imported-paths.json"
        self.paths = set(json.loads(self.path.read_text(encoding="utf-8"))) if self.path.exists() else set()

    def save(self) -> None:
        self.path.write_text(json.dumps(sorted(self.paths), indent=0), encoding="utf-8")


def history_dir(mind: Mind, override: str | None = None) -> str:
    """The caller's personal recalls folder + /history, found from orient."""
    if override:
        if not HISTORY.fullmatch(override.rstrip("/")):
            raise MindError("--history-dir must be a personal history folder: 22-memory/recalls/<id>/history")
        return override.rstrip("/")
    o = mind.tool("orient")
    personal = {z.removeprefix("personal-recalls-")
                for z in (o.get("purposes") or {}).get("recalls", []) if z.startswith("personal-recalls-")}
    profile = re.search(r"/personal/([0-9a-f]{64})/", ((o.get("you") or {}).get("profile") or {}).get("path", ""))
    if profile and profile.group(1) in personal:
        personal = {profile.group(1)}
    if len(personal) != 1:
        raise MindError("could not tell which personal recalls folder is yours; pass --history-dir")
    return f"22-memory/recalls/{personal.pop()}/history"


def standing_rule(mind: Mind) -> str:
    """The Mind's served standing rule, installed as the reader's project instructions."""
    return mind.tool("orient")["snippet"]


def _approve_held(mind: Mind, proposal_id: str, timeout: float = 3600.0) -> None:
    """Approve our own held proposal; if this sign-in may not, wait for someone who can."""
    card = None
    for _ in range(40):
        cards = mind.tool("list_review_queue", limit=50).get("cards") or []
        card = next((c for c in cards if c.get("proposal_id") == proposal_id), None)
        if card:
            break
        time.sleep(3)
    if card is None:
        raise MindError(f"held proposal {proposal_id} has no review card")
    try:
        mind.tool("act", action="queue.answer", item_id=card["id"], answer='{"decision": "approve"}')
        return
    except MindError:
        print(f"  waiting for an owner to approve review card {card['id']} ({card.get('summary', '')[:80]})",
              flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mind.tool("get_proposal", proposal_id=proposal_id).get("status") != "held":
            return
        time.sleep(15)
    raise MindError(f"review card {card['id']} was not approved within {timeout:.0f}s")


def _propose(mind: Mind, changes: list[dict], why: str) -> None:
    res = mind.tool("propose_write", changes=changes, rationale=why)
    if res.get("status") != "applied":
        _approve_held(mind, res["proposal_id"])


def files(mind: Mind, folder: str) -> list[dict]:
    listed = mind.tool("list_files", dir=folder, memory_view="evidence").get("files") or []
    return [f for f in listed if f["path"].rsplit("/", 1)[-1] not in GENERATED]


def _ours(f: dict, ledger: Ledger) -> bool:
    return f["path"] in ledger.paths or (f.get("memory") or {}).get("source") == DERIVED


def preflight(mind: Mind, folder: str, ledger: Ledger, wipe: str | None) -> None:
    """Refuse to touch a history folder that holds anything this harness did not import."""
    foreign = [f["path"] for f in files(mind, folder) if not _ours(f, ledger)]
    if not foreign:
        return
    if wipe and wipe.rstrip("/") == folder:
        ledger.paths.update(foreign)  # the caller named this folder: its contents may go
        ledger.save()
        return
    raise SystemExit(
        f"{folder} already holds {len(foreign)} file(s) this harness did not import, for example "
        f"{foreign[0]}.\nEach question replaces the folder's contents, so running here would delete "
        f"them. Use a new, empty Mind, or pass --wipe-existing-history {folder} to delete them.")


def clear(mind: Mind, folder: str, ledger: Ledger, timeout: float = 300.0) -> None:
    """Delete what this harness imported and the pages the Mind derived from it."""
    present = [f for f in files(mind, folder) if _ours(f, ledger)]
    for i in range(0, len(present), BATCH_FILES):
        _propose(mind, [{"op": "delete", "path": f["path"], "base_sha": f["memory"]["revision"]}
                        for f in present[i:i + BATCH_FILES]],
                 "LongMemEval harness: clear the previous question's imported history")
    deadline = time.time() + timeout
    while [f for f in files(mind, folder) if _ours(f, ledger)]:
        if time.time() > deadline:
            raise MindError(f"history folder {folder} did not clear")
        time.sleep(5)
    ledger.paths.clear()
    ledger.save()


def import_sessions(mind: Mind, folder: str, sessions: list[tuple[str, str]], ledger: Ledger) -> None:
    batch, size = [], 0

    def send():
        # Record before proposing, so a crash mid-import still leaves the files clearable.
        ledger.paths.update(c["path"] for c in batch)
        ledger.save()
        _propose(mind, batch, "LongMemEval harness: import timestamped conversation history")

    for name, content in sessions:
        if batch and (len(batch) == BATCH_FILES or size + len(content.encode("utf-8")) > BATCH_BYTES):
            send()
            batch, size = [], 0
        batch.append({"op": "create", "path": f"{folder}/{name}", "content": content})
        size += len(content.encode("utf-8"))
    if batch:
        send()


def wait_for_timeline(mind: Mind, folder: str, count: int, timeout: float) -> float:
    """Block until the Mind's timeline indexes all ``count`` sessions; return seconds waited."""
    t0 = time.time()
    want = f"derived_from_count: {count}"
    while time.time() - t0 < timeout:
        try:
            head = mind.tool("read", path=f"{folder}/timeline.md", mode="head")
            text = head.get("content", "")
        except MindError:
            text = ""
        if want in text:
            return round(time.time() - t0, 1)
        time.sleep(20)
    raise MindError(f"timeline did not index {count} sessions within {timeout:.0f}s")
