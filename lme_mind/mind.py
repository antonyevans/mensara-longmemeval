"""Import, wait for and clear one question's conversation history in the owner's Mind.

Everything goes through the owner's normal MCP tools. Session files are written with
`propose_write`; the Mind's own history timer (every five minutes) then writes the dated
digest and timeline with the Mind's own model connection. Deletes never auto-apply in a
Mind, so clearing proposes them and the owner's token approves its own card.
"""

from __future__ import annotations

import re
import time

from .mcp import Mind, MindError

# A proposal carries at most 20 files and 1 MiB (the Mind's airlock limits).
BATCH_FILES = 20
BATCH_BYTES = 900_000
GENERATED = {"_index.md", "_summary.md"}


def history_dir(mind: Mind, override: str | None = None) -> str:
    """The caller's personal recalls folder + /history, found from orient."""
    if override:
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


def clear(mind: Mind, folder: str, timeout: float = 300.0) -> None:
    """Delete every source and derived page in the history folder."""
    present = files(mind, folder)
    for i in range(0, len(present), BATCH_FILES):
        _propose(mind, [{"op": "delete", "path": f["path"], "base_sha": f["memory"]["revision"]}
                        for f in present[i:i + BATCH_FILES]],
                 "LongMemEval harness: clear the previous question's imported history")
    deadline = time.time() + timeout
    while files(mind, folder):
        if time.time() > deadline:
            raise MindError(f"history folder {folder} did not clear")
        time.sleep(5)


def import_sessions(mind: Mind, folder: str, sessions: list[tuple[str, str]]) -> None:
    batch, size = [], 0
    for name, content in sessions:
        if batch and (len(batch) == BATCH_FILES or size + len(content.encode("utf-8")) > BATCH_BYTES):
            _propose(mind, batch, "LongMemEval harness: import timestamped conversation history")
            batch, size = [], 0
        batch.append({"op": "create", "path": f"{folder}/{name}", "content": content})
        size += len(content.encode("utf-8"))
    if batch:
        _propose(mind, batch, "LongMemEval harness: import timestamped conversation history")


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
