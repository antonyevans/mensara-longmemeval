"""Run one LongMemEval question on the live test box (executed there as root).

Input JSON (path in argv[1]): {"history": "22-memory/recalls/<hash>/history", "user": "member-a",
"sessions": [{"name", "content"}], "digests": {sha: [observations]} | null,
"model_digest": bool, "prompt": "Current Date: ...\nQuestion: ..."}
Steps: clear the member's history folder (under the repository gate), import every session
with the product write CLI, fill the digest cache (or let derive-history call the box's model
route), run derive-history + zone maps, then ask the member's native Codex reader with the
standing rule and the live tool allowlist. Prints one JSON result line.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path("/opt/brain-gateway/brain")
GW = "/opt/brain-gateway/venv/bin/brain-gateway"
PY = "/opt/brain-gateway/venv/bin/python"
CODEX = "/usr/local/lib/memorytest-codex/bin/codex"
DISABLE = ["apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
           "computer_use", "memories", "shell_tool", "unified_exec", "view_image",
           "sleep_tool", "skill_search"]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 900), **kw)


def clear(history: str) -> None:
    code = (
        "import subprocess,sys\n"
        "from pathlib import Path\n"
        "from brain_gateway.repository_gate import RepositoryGate\n"
        "from brain_gateway.repository_gate_retry import acquire_repository_gate\n"
        f"repo=Path({str(REPO)!r});h={history!r}\n"
        "with acquire_repository_gate(RepositoryGate(repo),mode='exclusive',operation='unlabelled',retries=40,retry_delay_seconds=0.5):\n"
        "  tracked=subprocess.run(['git','-C',str(repo),'ls-files',h],capture_output=True,text=True).stdout.split()\n"
        "  if tracked:\n"
        "    subprocess.run(['git','-C',str(repo),'rm','-q','-r','--',h],check=True)\n"
        "    subprocess.run(['git','-C',str(repo),'commit','-q','-m','LongMemEval dev: clear imported history'],check=True)\n"
        "  for p in (repo/h).glob('*'):\n"
        "    p.unlink()\n"
    )
    r = run([PY, "-c", code])
    if r.returncode:
        raise RuntimeError("clear: " + r.stderr[-800:])


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    t0, timing = time.time(), {}
    work = Path(tempfile.mkdtemp(prefix="lme-live-"))
    clear(job["history"])
    timing["clear"] = round(time.time() - t0, 1)
    if job.get("digests"):
        # Content-addressed product cache, filled before import so the box's own history
        # timer finds every session cached and never starts model calls mid-run.
        code = "\n".join([
            "import json, sys",
            "from pathlib import Path",
            "from brain_gateway.history.cache import cache_path_for_bytes, save_digest",
            f"repo = Path({str(REPO)!r})",
            "for item in json.load(open(sys.argv[1])):",
            "    save_digest(cache_path_for_bytes(repo, item['content'].encode('utf-8')),",
            "                item['obs'], 'gpt-6-luna (precomputed)')",
        ])
        items = [{"content": s["content"], "obs": job["digests"][h]} for s in job["sessions"]
                 for h in [hashlib.sha256(s["content"].encode("utf-8")).hexdigest()]
                 if h in job["digests"]]
        (work / "d.json").write_text(json.dumps(items), encoding="utf-8")
        r = run([PY, "-c", code, str(work / "d.json")])
        if r.returncode:
            raise RuntimeError("digests: " + r.stderr[-600:])
    if job.get("consolidation"):
        # Same content address the box computes, so derive-history finds it and never calls
        # the box model route for it.
        code = "\n".join([
            "import json, sys",
            "from pathlib import Path",
            "from brain_gateway.history.cache import save_consolidation",
            f"repo = Path({str(REPO)!r})",
            "c = json.load(open(sys.argv[1]))",
            "save_consolidation(repo / '.brain-gateway/history-digest' / c['name'], c['output'],",
            "                   'gpt-6.1-sol (precomputed)')",
        ])
        (work / "c.json").write_text(json.dumps(job["consolidation"]), encoding="utf-8")
        r = run([PY, "-c", code, str(work / "c.json")])
        if r.returncode:
            raise RuntimeError("consolidation: " + r.stderr[-600:])
    for s in job["sessions"]:
        src = work / s["name"]
        src.write_text(s["content"], encoding="utf-8")
        r = run([GW, "--repo", str(REPO), "write", f"{job['history']}/{s['name']}", "--file", str(src),
                 "--message", "Import timestamped conversation history"])
        if r.returncode:
            raise RuntimeError(f"write {s['name']}: {r.stderr[-600:]}")
    timing["import"] = round(time.time() - t0, 1)
    derive = [GW, "--repo", str(REPO), "derive-history"] + ([] if job.get("model_digest") else ["--offline"])
    timeline = REPO / job["history"] / "timeline.md"
    derive_out = ""
    for attempt in range(6):
        r = run(derive, timeout=3600)
        derive_out = (r.stdout + r.stderr)[-1500:]
        # Another lane's commit can make a run defer; require a timeline covering all sessions.
        if timeline.exists() and f"derived_from_count: {len(job['sessions'])}" in timeline.read_text(
                encoding="utf-8")[:2000]:
            break
        time.sleep(5)
    timing["derive_attempts"] = attempt + 1
    timing["derive"] = round(time.time() - t0, 1)
    run([GW, "--repo", str(REPO), "reindex-zone-maps"])
    timing["maps"] = round(time.time() - t0, 1)
    cmd = ["timeout", "--signal=TERM", "--kill-after=10s", "420s", CODEX, "exec", "--ephemeral", "--json",
           "--skip-git-repo-check", "--sandbox", "read-only", "-m", job.get("model", "gpt-6.1-sol"),
           "-c", f'model_reasoning_effort="{job.get("effort", "medium")}"', "-c", 'web_search="disabled"']
    for f in DISABLE:
        cmd += ["--disable", f]
    cmd += ["-c", 'mcp_servers.mind.url="https://TEST-BOX/mcp"',
            "-c", 'mcp_servers.mind.enabled_tools=["orient","read","query","list_zones","list_files"]',
            "-C", f"/home/{job['user']}", "-"]
    mind = {"orient", "query", "read", "list_files", "list_zones"}
    for attempt in range(3):
        # A reader that never reached a Mind tool is a client startup fault, not an answer.
        r = subprocess.run(["runuser", "-l", job["user"], "-c", shlex.join(cmd)], input=job["prompt"],
                           capture_output=True, text=True, timeout=500)
        events = []
        for line in r.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        if any(e.get("item", {}).get("tool") in mind for e in events):
            break
    timing["reader"] = round(time.time() - t0, 1)
    timing["reader_attempts"] = attempt + 1
    text = timeline.read_text(encoding="utf-8") if timeline.exists() else ""
    print(json.dumps({"timing": timing, "timeline": timeline.exists(),
                      "consolidated": "## Latest values" in text or "## Preferences" in text,
                      "timeline_bytes": timeline.stat().st_size if timeline.exists() else 0,
                      "derive_out": derive_out, "reader_exit": r.returncode,
                      "reader_stderr": r.stderr[-800:], "events": events}))


if __name__ == "__main__":
    main()
