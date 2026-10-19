"""mensara-longmemeval: run LongMemEval-S against a Mensara Mind you own.

  python -m lme_mind run --mind-url https://<you>.mensara.ai/mcp --out runs/r1 --sample 30
  python -m lme_mind judge --answers results/2026-10-17-m36/hypotheses.jsonl --judge openai:gpt-4o-2024-08-06 --out rejudge.jsonl
  python -m lme_mind summary runs/r1

Sign in once first: python -m lme_mind login --mind-url https://<you>.mensara.ai/mcp
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import auth, dataset, judge as judging, mind as minds, reader as readers
from .mcp import Mind
from .summary import harness_errors, load_records, summarize

MIND_TOOLS = set(readers.READ_TOOLS)


def _connect(url: str) -> Mind:
    return Mind(url, lambda force=False: auth.access_token(url, force))


def one(qid: str, row: dict, mind: Mind, folder: str, rule: str, args, out: Path) -> dict:
    sessions = dataset.sessions(row)
    timing, t0 = {}, time.time()
    minds.clear(mind, folder)
    timing["clear"] = round(time.time() - t0, 1)
    minds.import_sessions(mind, folder, sessions)
    timing["import"] = round(time.time() - t0, 1)
    timing["timeline_wait"] = minds.wait_for_timeline(mind, folder, len(sessions), args.timeline_timeout)
    ask = readers.READERS[args.reader]
    for attempt in range(1, 4):
        res = ask(dataset.prompt(row), rule, args.mind_url, auth.access_token(args.mind_url),
                  args.reader_model, args.reader_effort)
        # A reader that never reached the Mind is a client start-up fault, not an answer.
        if MIND_TOOLS & set(res["tools"]):
            break
    timing["reader"] = res["seconds"]
    (out / "traces").mkdir(exist_ok=True)
    (out / "traces" / f"{qid}.jsonl").write_text(
        "\n".join(json.dumps(e) for e in res["events"]), encoding="utf-8")
    if res["exit"] or not res["answer"].strip():
        raise RuntimeError(f"reader exit={res['exit']} chars={len(res['answer'])} {res['stderr'][-400:]}")
    rec = {"question_id": qid, "question_type": row["question_type"], "hypothesis": res["answer"],
           "mind_tool_calls": sum(t in MIND_TOOLS for t in res["tools"]), "tools": res["tools"],
           "reader": f"{args.reader}:{args.reader_model}/{args.reader_effort}",
           "reader_attempts": attempt, "sessions": len(sessions), "timing": timing}
    rec.update(judging.judge(row, res["answer"], args.judge))
    return rec


def cmd_run(args) -> None:
    rows = dataset.load(args.dataset)
    qids = dataset.select(rows, args.qids, args.sample, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    mind = _connect(args.mind_url)
    folder = minds.history_dir(mind, args.history_dir)
    rule = minds.standing_rule(mind)
    print(f"{len(qids)} questions; history folder {folder}", flush=True)
    for i, qid in enumerate(qids, 1):
        path = out / f"{qid}.json"
        if path.exists():
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec.get("correct") is None:  # resume: grade only what is missing
                rec.update(judging.judge(rows[qid], rec["hypothesis"], args.judge))
                path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
            continue
        try:
            rec = one(qid, rows[qid], mind, folder, rule, args, out)
        except Exception as exc:  # noqa: BLE001 - recorded as a harness error, never graded
            (out / f"{qid}.error.txt").write_text(str(exc), encoding="utf-8")
            print(f"[{i}/{len(qids)}] {qid} ERROR {str(exc)[:200]}", flush=True)
            mind = _connect(args.mind_url)
            continue
        path.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
        (out / f"{qid}.error.txt").unlink(missing_ok=True)
        mark = {True: "ok", False: "MISS", None: "UNSCORED"}[rec["correct"]]
        print(f"[{i}/{len(qids)}] {qid} {rec['question_type']:26s} {mark} {rec['timing']}", flush=True)
    if not args.keep_history:
        minds.clear(mind, folder)
    print(json.dumps({**summarize(load_records(out))["ALL"], "harness_errors": len(harness_errors(out))}))


def cmd_judge(args) -> None:
    rows = dataset.load(args.dataset)
    done = {}
    out = Path(args.out)
    if out.exists():
        done = {json.loads(l)["question_id"]: l for l in out.read_text(encoding="utf-8").splitlines() if l}
    with out.open("a", encoding="utf-8") as fh:
        for line in Path(args.answers).read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            qid = entry["question_id"]
            if qid in done:
                continue
            graded = judging.judge(rows[qid], entry["hypothesis"], args.judge)
            fh.write(json.dumps({"question_id": qid, "question_type": rows[qid]["question_type"],
                                 "hypothesis": entry["hypothesis"], **graded}, ensure_ascii=False) + "\n")
            fh.flush()
    records = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l]
    print(json.dumps(summarize(records), indent=1))


def cmd_summary(args) -> None:
    untuned = set(json.loads(Path(args.untuned).read_text())) if args.untuned else None
    out = summarize(load_records(Path(args.run)), untuned)
    out["harness_errors"] = harness_errors(Path(args.run))
    print(json.dumps(out, indent=1))


def cmd_login(args) -> None:
    print(f"signed in; tokens saved to {auth.login(args.mind_url)}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m lme_mind")
    sub = ap.add_subparsers(dest="cmd", required=True)
    li = sub.add_parser("login", help="sign in to your Mind in the browser (once)")
    li.add_argument("--mind-url", required=True, help="https://<your-mind>/mcp")
    li.set_defaults(fn=cmd_login)
    run = sub.add_parser("run", help="import, ask and grade questions against your Mind")
    run.add_argument("--mind-url", required=True, help="https://<your-mind>/mcp")
    run.add_argument("--out", required=True)
    run.add_argument("--dataset", help="path to longmemeval_s_cleaned.json (downloaded if omitted)")
    run.add_argument("--qids", help="JSON list of question ids")
    run.add_argument("--sample", type=int, help="stratified sample of N questions")
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--history-dir", help="override the history folder (default: your personal recalls)")
    run.add_argument("--reader", choices=sorted(readers.READERS), default="codex")
    run.add_argument("--reader-model", default="gpt-6.1-sol")
    run.add_argument("--reader-effort", default="medium")
    run.add_argument("--judge", default="openai:gpt-4o-2024-08-06",
                     help="openai:<model> (canonical) or codex:<model> (published run: codex:gpt-6-sol)")
    run.add_argument("--timeline-timeout", type=float, default=1800)
    run.add_argument("--keep-history", action="store_true", help="leave the last question imported")
    run.set_defaults(fn=cmd_run)
    jd = sub.add_parser("judge", help="grade a hypotheses.jsonl file (for example our published answers)")
    jd.add_argument("--answers", required=True)
    jd.add_argument("--judge", default="openai:gpt-4o-2024-08-06")
    jd.add_argument("--out", required=True)
    jd.add_argument("--dataset")
    jd.set_defaults(fn=cmd_judge)
    sm = sub.add_parser("summary", help="score a run directory")
    sm.add_argument("run")
    sm.add_argument("--untuned", help="JSON list of untuned question ids")
    sm.set_defaults(fn=cmd_summary)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
