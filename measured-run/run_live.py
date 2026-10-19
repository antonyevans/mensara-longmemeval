"""Drive LongMemEval-S questions through the live test box (WSL).

One lane per native member profile (each member's history lives in their own personal
recalls zone, so lanes do not see each other). Records match run_dev.py so summaries compare.

  python3 run_live.py --qids <json> --out <dir> [--lanes a] [--digests [--core <worktree>] | --model-digest]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import queue
import shutil
import subprocess
import time
from pathlib import Path

import run_dev
from lme_render import render

HOST = "root@TEST-BOX"
SSH = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-i", str(Path.home() / ".ssh/DEPLOY_KEY")]
LANES = {
    "a": {"user": "member-a",
          "history": "22-memory/recalls/MEMBER-A-HASH/history"},
    "b": {"user": "member-b",
          "history": "22-memory/recalls/MEMBER-B-HASH/history"},
}
DIGESTS = Path.home() / "lme95/digest-cache"
HERE = Path(__file__).resolve().parent


def job_for(row, lane, args):
    rows = sorted(zip(row["haystack_session_ids"], row["haystack_dates"], row["haystack_sessions"]),
                  key=lambda x: x[1])
    sessions, digests = [], {}
    for slot, (_sid, date, turns) in enumerate(rows):
        text = render(slot, date, turns)
        sessions.append({"name": f"session-{slot:03d}.md", "content": text})
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cached = DIGESTS / f"{sha}-v1.json"
        if args.digests and cached.exists():
            digests[sha] = json.loads(cached.read_text(encoding="utf-8"))["observations"]
    consolidated = None
    if args.digests and args.core:
        import consolidation
        consolidation.use_core(args.core)
        _request, name, _ = consolidation.request_for(
            [(f"{LANES[lane]['history']}/{s['name']}", s["content"]) for s in sessions])
        output = consolidation.cached_output(name)
        consolidated = {"name": name, "output": output} if output else None
    return {"history": LANES[lane]["history"], "user": LANES[lane]["user"], "sessions": sessions,
            "digests": digests or None, "consolidation": consolidated,
            "model_digest": args.model_digest,
            "prompt": f"Current Date: {row['question_date']}\nQuestion: {row['question']}\n",
            "effort": args.reader_effort}


def remote(job, tag):
    local = Path("/tmp") / f"lme-live-{tag}.json"
    local.write_text(json.dumps(job), encoding="utf-8")
    for src, dst in ((local, f"/root/lme95/{tag}.json"), (HERE / "live_case.py", "/root/lme95/live_case.py")):
        r = subprocess.run(["scp", "-q", *SSH, str(src), f"{HOST}:{dst}"], capture_output=True, text=True,
                           timeout=300)
        if r.returncode:
            raise RuntimeError("scp: " + r.stderr[-300:])
    r = subprocess.run(["ssh", *SSH, HOST, f"python3 /root/lme95/live_case.py /root/lme95/{tag}.json; rc=$?; "
                        f"rm -f /root/lme95/{tag}.json; exit $rc"], capture_output=True, text=True, timeout=4000,
                       stdin=subprocess.DEVNULL)
    local.unlink(missing_ok=True)
    if r.returncode or not r.stdout.strip():
        raise RuntimeError(f"remote rc={r.returncode}: " + r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def one(row, lane, out: Path, args):
    qid = row["question_id"]
    rec_path = out / f"{qid}.json"
    if rec_path.exists():
        return run_dev.regrade_if_unscored(row, rec_path, out)
    res = remote(job_for(row, lane, args), f"{lane}-{qid}")
    ev = res.pop("events")
    msgs = [e["item"]["text"] for e in ev if e.get("type") == "item.completed"
            and e.get("item", {}).get("type") == "agent_message"]
    calls = [{"tool": e["item"].get("tool"), "args": e["item"].get("arguments")} for e in ev
             if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "mcp_tool_call"]
    answer = msgs[-1] if msgs else ""
    (out / "traces").mkdir(exist_ok=True)
    (out / "traces" / f"{qid}.jsonl").write_text("\n".join(json.dumps(e) for e in ev), encoding="utf-8")
    if res["reader_exit"] or not answer.strip():
        # A crashed or silent reader is a harness fault: keep it visible, never grade it.
        raise RuntimeError(f"reader exit={res['reader_exit']} answer_chars={len(answer)} "
                           f"stderr={res['reader_stderr'][-600:]}")
    work = Path("/tmp/lme95-live-judge") / qid
    try:
        graded = run_dev.judge(row, answer, work, out / "judge-diagnostics")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    mind = {"orient", "query", "read", "list_files", "list_zones"}
    rec = {"qid": qid, "type": row["question_type"], "abstention": qid.endswith("_abs"), "lane": lane,
           "answer": answer,
           "calls": calls, "mind_calls": sum(c["tool"] in mind for c in calls),
           "seconds": res["timing"].get("reader", 0) - res["timing"].get("maps", 0),
           "timing": res["timing"], "timeline": res["timeline"], "timeline_bytes": res["timeline_bytes"],
           "consolidated": res.get("consolidated"),
           "derive_out": res["derive_out"], "reader_exit": res["reader_exit"],
           "reader_stderr": res["reader_stderr"] if res["reader_exit"] else ""}
    run_dev.record_grade(rec, graded)
    rec_path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    (out / f"{qid}.error.txt").unlink(missing_ok=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lanes", default="a")
    ap.add_argument("--digests", action="store_true", help="prefill box digest cache from precomputed")
    ap.add_argument("--model-digest", action="store_true", help="let derive-history call the box model")
    ap.add_argument("--reader-effort", default="medium")
    ap.add_argument("--core", help="brain-core worktree matching the box build; with --digests, "
                    "also prefill precomputed cross-session consolidations")
    args = ap.parse_args()
    data = {r["question_id"]: r for r in json.load(open(run_dev.DATASET, encoding="utf-8"))}
    qids = json.load(open(args.qids, encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ssh", *SSH, HOST, "mkdir -p -m 700 /root/lme95"], check=True, stdin=subprocess.DEVNULL)
    lanes = queue.Queue()
    for lane in args.lanes.split(","):
        lanes.put(lane)

    def task(q):
        lane = lanes.get()
        try:
            return one(data[q], lane, out, args)
        finally:
            lanes.put(lane)

    with cf.ThreadPoolExecutor(len(args.lanes.split(","))) as ex:
        futs = {ex.submit(task, q): q for q in qids}
        for f in cf.as_completed(futs):
            q = futs[f]
            try:
                r = f.result()
                print(f"{q} {r['type']:28s} {run_dev.status(r)} timing={r['timing']} "
                      f"timeline={r['timeline']} calls={len(r['calls'])}", flush=True)
            except Exception as e:  # noqa: BLE001 - record and continue
                print(f"{q} ERROR {str(e)[:400]}", flush=True)
                (out / f"{q}.error.txt").write_text(str(e), encoding="utf-8")
    time.sleep(0)


if __name__ == "__main__":
    main()
