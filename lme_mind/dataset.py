"""LongMemEval-S questions and the session files the harness imports for each one."""

from __future__ import annotations

import hashlib
import json
import random
import urllib.request
from pathlib import Path

# The cleaned release used for the published run (sha256 d6f21ea9…c442).
URL = ("https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/"
       "longmemeval_s_cleaned.json")
SHA256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"


def load(path: str | None) -> dict[str, dict]:
    """Question rows by id; downloads the cleaned S file to data/ when no path is given."""
    target = Path(path) if path else Path("data/longmemeval_s_cleaned.json")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {URL}")
        urllib.request.urlretrieve(URL, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != SHA256:
            target.unlink()
            raise SystemExit(f"downloaded dataset has sha256 {digest}, expected {SHA256}")
    rows = json.loads(target.read_text(encoding="utf-8"))
    return {r["question_id"]: r for r in rows}


def select(rows: dict, qids_file: str | None, sample: int | None, seed: int) -> list[str]:
    """All ids, the ids in a JSON list file, or a sample stratified by question type."""
    if qids_file:
        return json.loads(Path(qids_file).read_text(encoding="utf-8"))
    ids = sorted(rows)
    if not sample:
        return ids
    by_type: dict[str, list[str]] = {}
    for q in ids:
        by_type.setdefault(rows[q]["question_type"], []).append(q)
    rng, picked = random.Random(seed), []
    for kind in sorted(by_type):
        group = by_type[kind]
        picked += rng.sample(group, max(1, round(sample * len(group) / len(ids))))
    return sorted(picked)


def render(slot: int, date: str, turns: list[dict]) -> str:
    """One session as a Markdown file, byte-identical to the published run's import."""
    created = date.split(" ")[0].replace("/", "-")
    head = (
        "---\npromotion: approved\nstatus: active\n"
        f'created: "{created}"\nsource: "imported conversation history"\n'
        'importance: "medium"\nttl: "never"\nprotected: false\n'
        f'tags: ["conversation-history"]\nsource_session_slot: {slot}\n---\n\n'
        f"# Imported conversation session {slot:03d}\n\nOriginal session time: {date}\n"
    )
    body = "".join(
        "**" + t["role"] + ":**\n\n" + t["content"].replace("\r\n", "\n") + "\n\n" for t in turns
    )
    return head + "\n" + body.rstrip() + "\n"


def sessions(row: dict) -> list[tuple[str, str]]:
    """``[(file name, content)]`` in date order, as the published run imported them."""
    ordered = sorted(zip(row["haystack_session_ids"], row["haystack_dates"], row["haystack_sessions"]),
                     key=lambda x: x[1])
    return [(f"session-{slot:03d}.md", render(slot, date, turns))
            for slot, (_sid, date, turns) in enumerate(ordered)]


def prompt(row: dict) -> str:
    return f"Current Date: {row['question_date']}\nQuestion: {row['question']}\n"
