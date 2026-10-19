"""Pre-compute per-session history digests for the offline dev loop (WSL).

Calls a cheap subscription model through `codex exec` with the product's digest prompt for
every unique session in the selected questions, keyed by sha256 of the exact session file
bytes the import writes. The product's `derive-history --offline` then renders timelines
from this cache without model calls. Resumable: existing cache entries are skipped.

  python3 precompute_digests.py --qids <json list> [--cache ~/lme95/digest-cache] [-j 10]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lme_render import render  # noqa: E402

DATASET = "data/longmemeval_s_cleaned.json"
PROMPT_VERSION = "1"
SYSTEM = ("You turn one past conversation between a user and an AI assistant into dated memory "
          "observations about the user. Output only bullet lines starting with \"- \". No preamble.")
USER = """Session time: {session_time}

Write the observations a personal assistant would need later to answer questions such as "when did I…", "how many times have I…", "what did I buy/start/finish most recently…", "how long between X and Y…", "what did you recommend for…".

Rules:
1. Record what the USER says about themselves, their life, people, possessions, plans, activities, purchases, numbers, preferences and changes. User statements are authoritative. Questions the user merely asks are not facts about them; record them only as "User asked about …" when the topic itself reveals something personal.
2. One fact or event per line. Keep names, places, titles, brands, quantities, prices, durations and counts exactly as stated.
3. Dates: when the user refers to a time relative to the session ("yesterday", "last weekend", "two weeks ago", "next Friday", "this morning"), append the resolved date in brackets, e.g. "[≈ 2023-01-14 to 2023-01-15]" or "[2023-01-21]". Use the session time as "now". Do not invent dates for vague words like "recently". Events with no stated time are assumed to be "as of {session_date}".
4. State changes explicitly: "User now …, replacing …", "User's count of … is now N".
5. For the assistant's own substantive output that the user may ask about later (recommendations, lists, recipes, names, numbers it gave), add one compact line each, starting "Assistant suggested: …", keeping the distinguishing items in order.
6. Skip pleasantries and generic advice that reveals nothing specific.
7. If the conversation contains nothing about the user, output one line: "- User asked about <topic>; no personal details."

Conversation:
{transcript}"""


def body_of(text: str) -> str:
    return text.split("\n---\n", 1)[1] if text.startswith("---\n") else text


def trim(transcript: str, limit: int = 60000) -> str:
    if len(transcript) <= limit:
        return transcript
    parts = transcript.split("**assistant:**")
    while len("**assistant:**".join(parts)) > limit:
        i = max(range(1, len(parts)), key=lambda k: len(parts[k].split("**user:**")[0]))
        head, *rest = parts[i].split("**user:**", 1)
        parts[i] = head[: max(200, len(head) // 2)] + "\n[assistant text trimmed]\n\n" + (
            ("**user:**" + rest[0]) if rest else "")
    return "**assistant:**".join(parts)


def call(prompt: str, model: str, timeout: int = 180) -> str:
    home = Path.home() / "lme95/codex-home-digest"
    if not home.exists():
        home.mkdir(parents=True)
        os.symlink(Path.home() / ".codex/auth.json", home / "auth.json")
        (home / "config.toml").write_text("", encoding="utf-8")
    cmd = ["timeout", f"{timeout}s", "codex", "exec", "--ephemeral", "--json", "--skip-git-repo-check",
           "--sandbox", "read-only", "-m", model, "-c", 'model_reasoning_effort="low"',
           "-c", 'web_search="disabled"', "--disable", "shell_tool", "-C", str(home), "-"]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "CODEX_HOME": str(home)})
    msgs = []
    for line in p.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message":
            msgs.append(e["item"]["text"])
    if not msgs:
        raise RuntimeError(f"exit {p.returncode}: {p.stderr[-300:]}")
    return msgs[-1]


def one(job, cache: Path, model: str):
    sha, session_time, text = job
    dest = cache / f"{sha}-v{PROMPT_VERSION}.json"
    if dest.exists():
        return "cached"
    date = session_time.split(" ")[0].replace("/", "-")
    user = USER.format(session_time=session_time, session_date=date, transcript=trim(body_of(text)))
    prompt = f"{SYSTEM}\n\n{user}"
    for attempt in range(3):
        try:
            out = call(prompt, model)
            lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("- ")]
            if not lines:
                raise RuntimeError("no bullet lines")
            dest.write_text(json.dumps({"observations": [ln[2:].strip() for ln in lines],
                                        "raw": out, "model": model, "prompt_version": PROMPT_VERSION,
                                        "at": time.time()}), encoding="utf-8")
            return "done"
        except Exception as e:  # noqa: BLE001 - retry, then record
            err = str(e)
            time.sleep(5 * (attempt + 1))
    (cache / f"{sha}.error").write_text(err, encoding="utf-8")
    return "error"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", required=True)
    ap.add_argument("--cache", default=str(Path.home() / "lme95/digest-cache"))
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("-j", type=int, default=10)
    a = ap.parse_args()
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    data = {r["question_id"]: r for r in json.load(open(DATASET, encoding="utf-8"))}
    jobs = {}
    for q in json.load(open(a.qids, encoding="utf-8")):
        row = data[q]
        rows = sorted(zip(row["haystack_session_ids"], row["haystack_dates"], row["haystack_sessions"]),
                      key=lambda x: x[1])
        for slot, (_sid, date, turns) in enumerate(rows):
            text = render(slot, date, turns)
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            jobs.setdefault(sha, (sha, date, text))
    print(f"{len(jobs)} unique session files", flush=True)
    counts = {}
    with cf.ThreadPoolExecutor(a.j) as ex:
        for i, r in enumerate(ex.map(lambda j: one(j, cache, a.model), jobs.values()), 1):
            counts[r] = counts.get(r, 0) + 1
            if i % 100 == 0:
                print(i, counts, flush=True)
    print("final", counts, flush=True)


if __name__ == "__main__":
    main()
