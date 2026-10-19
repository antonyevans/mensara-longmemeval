"""Pre-compute cross-session consolidations for the dev loop and live runs (WSL).

For each question, rebuild the exact request derive-history makes for its history (see
consolidation.py), call a subscription model through `codex exec`, keep the output only if
the product's own validator accepts it, and store it under the product's content address.
Resumable: existing outputs are skipped.

  python3 precompute_consolidations.py --core <brain-core worktree> --qids <json> [-j 6]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import consolidation  # noqa: E402
from lme_render import render  # noqa: E402

DATASET = "data/longmemeval_s_cleaned.json"
HIST = "22-memory/recalls/owner/history"


def call(prompt: str, model: str, effort: str, timeout: int = 420) -> str:
    home = Path.home() / "lme95/codex-home-consolidate"
    if not home.exists():
        home.mkdir(parents=True)
        os.symlink(Path.home() / ".codex/auth.json", home / "auth.json")
        (home / "config.toml").write_text("", encoding="utf-8")
    cmd = ["timeout", f"{timeout}s", "codex", "exec", "--ephemeral", "--json", "--skip-git-repo-check",
           "--sandbox", "read-only", "-m", model, "-c", f'model_reasoning_effort="{effort}"',
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


def files_for(row) -> list[tuple[str, str]]:
    rows = sorted(zip(row["haystack_session_ids"], row["haystack_dates"], row["haystack_sessions"]),
                  key=lambda x: x[1])
    return [(f"{HIST}/session-{slot:03d}.md", render(slot, date, turns))
            for slot, (_sid, date, turns) in enumerate(rows)]


def one(qid, row, args):
    from brain_gateway.history import consolidate
    request, name, entries = consolidation.request_for(files_for(row))
    if request is None:
        return qid, "nothing"
    dest = consolidation.CACHE / name
    if dest.exists():
        return qid, "cached"
    prompt = f"{request[0]['content']}\n\n{request[1]['content']}"
    err = ""
    for attempt in range(3):
        try:
            out = call(prompt, args.model, args.effort)
            parsed = consolidate.parse(out, entries)
            if parsed is None:
                raise RuntimeError("output is not usable JSON")
            dest.write_text(json.dumps({"output": out, "model": args.model, "effort": args.effort,
                                        "replacements": len(parsed.replacements),
                                        "preferences": len(parsed.preferences),
                                        "at": time.time()}), encoding="utf-8")
            return qid, f"done r={len(parsed.replacements)} p={len(parsed.preferences)}"
        except Exception as e:  # noqa: BLE001 - retry, then record
            err = str(e)
            time.sleep(5 * (attempt + 1))
    (consolidation.CACHE / f"{name}.error").write_text(err, encoding="utf-8")
    return qid, "error " + err[:120]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True)
    ap.add_argument("--qids", required=True)
    ap.add_argument("--model", default="gpt-6.1-sol")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("-j", type=int, default=6)
    args = ap.parse_args()
    consolidation.use_core(args.core)
    consolidation.CACHE.mkdir(parents=True, exist_ok=True)
    data = {r["question_id"]: r for r in json.load(open(DATASET, encoding="utf-8"))}
    qids = json.load(open(args.qids, encoding="utf-8"))
    with cf.ThreadPoolExecutor(args.j) as ex:
        for qid, status in ex.map(lambda q: one(q, data[q], args), qids):
            print(qid, status, flush=True)


if __name__ == "__main__":
    main()
