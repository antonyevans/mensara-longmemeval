"""Offline LongMemEval-S dev loop against a brain-core checkout (WSL).

Per question: copy the test box template repository, add the haystack as imported
conversation-history files in the reader's personal recalls zone, regenerate zone maps
with the product CLI, then ask a fresh Codex reader (same model, effort, tool allowlist
and served standing rule as the live run) through the real MCP server over stdio, and
grade with the unchanged official answer-check prompt. Development use only: the live
test box run remains the qualification path.

  python3 run_dev.py --core <brain-core worktree> --qids <json list> --out <dir> [-j 6]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = "data/longmemeval_s_cleaned.json"
DEV = Path("OPERATOR-RUN-DIR/lme95-dev")
TEMPLATE = Path.home() / "lme95/template"
VENV_PY = "BRAIN-CORE-VENV/bin/python"
H = "MEMBER-A-HASH"
PRINCIPAL = "user:MEMBER-A-SUBJECT"
ZONES = ",".join([
    "areas", "charter", "decisions", "inbox", "outputs", "people", f"personal-practice-{H}",
    f"personal-recalls-{H}", "practice", "principles", "reviews", "skills", "world-model",
])
HIST = f"22-memory/recalls/{H}/history"
DISABLE = ["apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
           "computer_use", "memories", "shell_tool", "unified_exec", "view_image",
           "sleep_tool", "skill_search"]

sys.path.insert(0, str(HERE))
from lme_render import render  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rubric", DEV.parent / "lme-guided-s100-20261014-01/official-rubric-function.py")
rubric = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rubric)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kw)


def gw(core, repo, *args):
    env = {**os.environ, "PYTHONPATH": f"{core}/src"}
    return sh([VENV_PY, "-m", "brain_gateway.cli", "--repo", str(repo), *args], env=env, timeout=600)


def build_repo(core, work: Path, row, extra_cli=(), digests=False):
    repo = work / "repo"
    shutil.copytree(TEMPLATE, repo, symlinks=True)
    r = gw(core, repo, "init-keys")
    assert r.returncode == 0, r.stderr[-500:]
    (repo / HIST).mkdir(parents=True, exist_ok=True)
    rows = sorted(zip(row["haystack_session_ids"], row["haystack_dates"], row["haystack_sessions"]),
                  key=lambda x: x[1])
    for slot, (_sid, date, turns) in enumerate(rows):
        (repo / HIST / f"session-{slot:03d}.md").write_text(render(slot, date, turns), encoding="utf-8")
    sh(["git", "-C", str(repo), "add", "-A"])
    sh(["git", "-C", str(repo), "-c", "user.email=lme@local", "-c", "user.name=lme",
        "commit", "-qm", "Import timestamped conversation history"])
    if digests:
        env = {**os.environ, "PYTHONPATH": f"{core}/src"}
        r = sh([VENV_PY, str(HERE / "prefill_cache.py"), str(repo), HIST], env=env, timeout=300)
        if r.returncode:
            raise RuntimeError(f"prefill: {r.stderr[-800:]}")
        extra_cli = [("derive-history", "--offline"), *extra_cli]
    for args in (*extra_cli, ("reindex-zone-maps", "--all")):
        r = gw(core, repo, *args)
        if r.returncode:
            raise RuntimeError(f"{args}: {r.stderr[-800:]}")
    r = gw(core, repo, "grant", "--to", PRINCIPAL, "--zones", ZONES, "--read", "--expires", "7d")
    assert r.returncode == 0, r.stderr[-500:]
    (work / "token").write_text(r.stdout.strip().split()[-1], encoding="utf-8")
    return repo


def codex_home(work: Path, rule: bool):
    home = work / "codex-home"
    home.mkdir()
    os.symlink(Path.home() / ".codex/auth.json", home / "auth.json")
    if rule:
        shutil.copy(DEV / "standing-rule.md", home / "AGENTS.md")
    (home / "config.toml").write_text("", encoding="utf-8")
    return home


def run_codex(home, prompt, *, model, effort, mcp=None, timeout=420):
    cmd = ["timeout", "--signal=TERM", "--kill-after=10s", f"{timeout}s", "codex", "exec",
           "--ephemeral", "--json", "--skip-git-repo-check", "--sandbox", "read-only",
           "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-c", 'web_search="disabled"']
    for f in DISABLE:
        cmd += ["--disable", f]
    env = {**os.environ, "CODEX_HOME": str(home)}
    if mcp:
        cmd += ["-c", f'mcp_servers.mind.url="{mcp["url"]}"',
                "-c", 'mcp_servers.mind.bearer_token_env_var="LME_MIND_TOKEN"',
                "-c", "mcp_servers.mind.startup_timeout_sec=120",
                "-c", 'mcp_servers.mind.enabled_tools=["orient","read","query","list_zones","list_files"]']
        env["LME_MIND_TOKEN"] = mcp["token"]
    cmd += ["-C", str(home), "-"]
    t0 = time.time()
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", env=env)
    events = []
    for line in p.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    msgs = [e["item"]["text"] for e in events
            if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
    calls = [{"tool": e["item"].get("tool"), "args": e["item"].get("arguments")} for e in events
             if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "mcp_tool_call"]
    usage = [e.get("usage") for e in events if e.get("type") == "turn.completed"]
    tools = sum(1 for e in events if e.get("type") == "item.completed"
                and e.get("item", {}).get("type") not in {"agent_message", "reasoning"})
    errors = [json.dumps(e)[:500] for e in events
              if e.get("type") in {"error", "turn.failed"} or e.get("item", {}).get("type") == "error"]
    return {"answer": msgs[-1] if msgs else "", "calls": calls, "exit": p.returncode,
            "seconds": round(time.time() - t0, 1), "usage": usage, "stderr": p.stderr[-1500:],
            "events": events, "completed": bool(usage), "tool_items": tools, "errors": errors}


JUDGE_ATTEMPTS = 3


def judge(row, answer: str, work: Path, diag_dir: Path) -> dict:
    """Grade one saved answer with the unchanged official prompt.

    A verdict counts only from a clean run: exit 0, a completed turn, no tool items and a
    yes/no label. Anything else is retried, and every attempt's diagnostics are kept, so a
    judge failure is reported as unscored instead of being silently recorded as wrong.
    """
    qid = row["question_id"]
    prompt = rubric.get_anscheck_prompt(row["question_type"], row["question"], row["answer"],
                                        answer, abstention=qid.endswith("_abs"))
    diag_dir.mkdir(parents=True, exist_ok=True)
    last = ""
    for attempt in range(1, JUDGE_ATTEMPTS + 1):
        home_dir = work / f"judge-{attempt}"
        shutil.rmtree(home_dir, ignore_errors=True)
        home_dir.mkdir(parents=True)
        try:
            res = run_codex(codex_home(home_dir, rule=False), prompt, model="gpt-6-sol",
                            effort="high", timeout=180)
        finally:
            shutil.rmtree(home_dir, ignore_errors=True)
        label = re.sub(r"[^a-z]", "", res["answer"].strip().lower())
        verdict = "yes" if label.startswith("yes") else "no" if label.startswith("no") else None
        valid = (res["exit"] == 0 and res["completed"] and not res["tool_items"]
                 and verdict is not None)
        last = (f"exit={res['exit']} completed={res['completed']} tools={res['tool_items']} "
                f"raw={res['answer'][:60]!r} errors={len(res['errors'])}")
        (diag_dir / f"{qid}.attempt-{attempt}.json").write_text(json.dumps({
            "qid": qid, "attempt": attempt, "valid": valid, "verdict": verdict,
            "exit": res["exit"], "completed": res["completed"], "tool_items": res["tool_items"],
            "answer": res["answer"][:400], "errors": res["errors"], "stderr": res["stderr"],
            "usage": res["usage"], "seconds": res["seconds"],
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        }, indent=1), encoding="utf-8")
        if valid:
            return {"verdict": verdict, "raw": res["answer"][:40], "attempts": attempt}
        time.sleep(5 * attempt)
    return {"verdict": None, "raw": "", "attempts": JUDGE_ATTEMPTS, "error": last}


def record_grade(rec: dict, graded: dict) -> dict:
    """Attach a judge result; None means unscored, never wrong."""
    rec["correct"] = None if graded["verdict"] is None else graded["verdict"] == "yes"
    rec["judge_raw"] = graded["raw"]
    rec["judge_attempts"] = graded["attempts"]
    rec.pop("judge_error", None)
    if graded["verdict"] is None:
        rec["judge_error"] = graded["error"]
    return rec


def regrade_if_unscored(row, rec_path: Path, out: Path) -> dict:
    """Resume: a saved answer keeps its grade; only a missing grade is judged again."""
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if rec.get("correct") is not None:
        return rec
    work = Path("/tmp/lme95-regrade") / out.name / rec["qid"]
    try:
        record_grade(rec, judge(row, rec["answer"], work, out / "judge-diagnostics"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    rec_path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def status(rec: dict) -> str:
    return "UNSCORED" if rec["correct"] is None else "OK " if rec["correct"] else "BAD"


def free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_up(port: int, proc, limit: float = 180.0) -> None:
    import socket
    deadline = time.time() + limit
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"mind server exited {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("mind server did not start")


def one(core, row, out: Path, args):
    qid = row["question_id"]
    rec_path = out / f"{qid}.json"
    if rec_path.exists():
        return regrade_if_unscored(row, rec_path, out)
    work = Path("/tmp/lme95-run") / out.name / qid
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        repo = build_repo(core, work, row, extra_cli=[tuple(a.split()) for a in args.extra_cli],
                          digests=args.digests)
        home = codex_home(work, rule=True)
        prompt = f"Current Date: {row['question_date']}\nQuestion: {row['question']}\n"
        mind = {"orient", "query", "read", "list_files", "list_zones"}
        port = free_port()
        server = subprocess.Popen([VENV_PY, str(HERE / "http_mind.py"), str(repo), str(port)],
                                  env={**os.environ, "PYTHONPATH": f"{core}/src"},
                                  stdout=subprocess.DEVNULL, stderr=open(work / "server.log", "w"))
        try:
            wait_up(port, server)
            token = (work / "token").read_text(encoding="utf-8").strip()
            for attempt in range(3):
                # A reader that never reached a Mind tool is a harness fault, not an answer.
                reader = run_codex(home, prompt, model=args.reader_model, effort=args.reader_effort,
                                   mcp={"url": f"http://127.0.0.1:{port}/mcp", "token": token})
                if any(c["tool"] in mind for c in reader["calls"]):
                    break
        finally:
            server.terminate()
            server.wait(timeout=30)
        reader["infra_retries"] = attempt
        (out / "traces").mkdir(exist_ok=True)
        (out / "traces" / f"{qid}.jsonl").write_text(
            "\n".join(json.dumps(e) for e in reader["events"]), encoding="utf-8")
        if reader["exit"] or not reader["answer"].strip():
            # A crashed or silent reader is a harness fault: keep it visible, never grade it.
            raise RuntimeError(f"reader exit={reader['exit']} answer_chars={len(reader['answer'])} "
                               f"stderr={reader['stderr'][-600:]}")
        abst = qid.endswith("_abs")
        graded = judge(row, reader["answer"], work, out / "judge-diagnostics")
        rec = {"qid": qid, "type": row["question_type"], "abstention": abst,
               "answer": reader["answer"], "calls": reader["calls"], "seconds": reader["seconds"],
               "reader_exit": reader["exit"], "usage": reader["usage"], "infra_retries": reader["infra_retries"],
               "mind_calls": sum(c["tool"] in mind for c in reader["calls"]),
               "reader_stderr": reader["stderr"] if reader["exit"] else ""}
        record_grade(rec, graded)
        rec_path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        (out / f"{qid}.error.txt").unlink(missing_ok=True)
        return rec
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True)
    ap.add_argument("--qids", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("-j", type=int, default=6)
    ap.add_argument("--reader-model", default="gpt-6.1-sol")
    ap.add_argument("--reader-effort", default="medium")
    ap.add_argument("--extra-cli", action="append", default=[],
                    help="extra brain-gateway CLI step after import, e.g. 'derive-history'")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--digests", action="store_true",
                    help="prefill the product digest cache and run derive-history --offline")
    args = ap.parse_args()
    data = {r["question_id"]: r for r in json.load(open(DATASET, encoding="utf-8"))}
    qids = json.load(open(args.qids, encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps({
        "core": args.core, "core_head": sh(["git", "-C", args.core, "rev-parse", "HEAD"]).stdout.strip(),
        "core_dirty": bool(sh(["git", "-C", args.core, "status", "--porcelain", "src"]).stdout.strip()),
        "reader": [args.reader_model, args.reader_effort], "extra_cli": args.extra_cli,
        "digests": args.digests,
        "started": dt.datetime.now(dt.timezone.utc).isoformat(), "n": len(qids)}, indent=1))
    results = []
    with cf.ThreadPoolExecutor(args.j) as ex:
        futs = {ex.submit(one, args.core, data[q], out, args): q for q in qids}
        for f in cf.as_completed(futs):
            q = futs[f]
            try:
                r = f.result()
                results.append(r)
                print(f"{q} {r['type']:28s} {status(r)} {r['seconds']}s calls={len(r['calls'])}", flush=True)
            except Exception as e:  # keep going; record the failure
                print(f"{q} ERROR {str(e)[:300]}", flush=True)
                (out / f"{q}.error.txt").write_text(str(e), encoding="utf-8")
    by = {}
    scored = [r for r in results if r["correct"] is not None]
    for r in scored:
        b = by.setdefault(r["type"], [0, 0])
        b[0] += r["correct"]
        b[1] += 1
    summary = {"correct": sum(r["correct"] for r in scored), "scored": len(scored),
               "unscored": sorted(r["qid"] for r in results if r["correct"] is None),
               "errors": sorted(p.name[:-10] for p in out.glob("*.error.txt")),
               "by_type": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())}}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
