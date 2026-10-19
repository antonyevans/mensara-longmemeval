"""Ask a fresh, read-only agent the question, with only the Mind's read tools available.

The published run used the Codex CLI (`gpt-6.1-sol`, medium effort). A Claude Code reader
is offered for people who use Claude; it was not used in the published run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

READ_TOOLS = ["orient", "read", "query", "list_zones", "list_files"]
# Codex features switched off in the published run, so the reader can only use the Mind.
CODEX_DISABLE = ["apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
                 "computer_use", "memories", "shell_tool", "unified_exec", "view_image",
                 "sleep_tool", "skill_search"]


def codex(prompt: str, rule: str, url: str, token: str, model: str, effort: str,
          timeout: int = 420, disable: list[str] | None = None) -> dict:
    home = Path(tempfile.mkdtemp(prefix="lme-reader-"))
    try:
        auth = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
        if auth.exists():
            shutil.copy(auth, home / "auth.json")
        (home / "AGENTS.md").write_text(rule, encoding="utf-8")
        (home / "config.toml").write_text("", encoding="utf-8")
        cmd = ["codex", "exec", "--ephemeral", "--json", "--skip-git-repo-check",
               "--sandbox", "read-only", "-m", model,
               "-c", f'model_reasoning_effort="{effort}"', "-c", 'web_search="disabled"']
        for feature in CODEX_DISABLE if disable is None else disable:
            cmd += ["--disable", feature]
        cmd += ["-c", f'mcp_servers.mind.url="{url}"',
                "-c", 'mcp_servers.mind.bearer_token_env_var="LME_MIND_TOKEN"',
                "-c", "mcp_servers.mind.startup_timeout_sec=120",
                "-c", "mcp_servers.mind.enabled_tools=" + json.dumps(READ_TOOLS),
                "-C", str(home), "-"]
        env = {**os.environ, "CODEX_HOME": str(home), "LME_MIND_TOKEN": token}
        t0 = time.time()
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           env=env, timeout=timeout + 30)
        events = []
        for line in p.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        done = [e["item"] for e in events if e.get("type") == "item.completed"]
        answers = [i["text"] for i in done if i.get("type") == "agent_message"]
        calls = [i.get("tool") for i in done if i.get("type") == "mcp_tool_call"]
        return {"answer": answers[-1] if answers else "", "tools": calls, "exit": p.returncode,
                "seconds": round(time.time() - t0, 1), "stderr": p.stderr[-1500:], "events": events}
    finally:
        shutil.rmtree(home, ignore_errors=True)


def claude(prompt: str, rule: str, url: str, token: str, model: str, effort: str,
           timeout: int = 420, disable=None) -> dict:
    work = Path(tempfile.mkdtemp(prefix="lme-reader-"))
    try:
        (work / "CLAUDE.md").write_text(rule, encoding="utf-8")
        config = {"mcpServers": {"mind": {"type": "http", "url": url,
                                          "headers": {"Authorization": f"Bearer {token}"}}}}
        (work / "mcp.json").write_text(json.dumps(config), encoding="utf-8")
        allowed = ",".join(f"mcp__mind__{t}" for t in READ_TOOLS)
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", model,
               "--mcp-config", str(work / "mcp.json"), "--strict-mcp-config",
               "--allowedTools", allowed, "--disallowedTools",
               "Bash,Edit,Write,WebFetch,WebSearch,Task,NotebookEdit"]
        t0 = time.time()
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           cwd=work, timeout=timeout + 30)
        events, calls, answer = [], [], ""
        for line in p.stdout.splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            events.append(e)
            for block in (e.get("message") or {}).get("content", []) if e.get("type") == "assistant" else []:
                if block.get("type") == "tool_use":
                    calls.append(block["name"].removeprefix("mcp__mind__"))
            if e.get("type") == "result":
                answer = e.get("result") or ""
        return {"answer": answer, "tools": calls, "exit": p.returncode,
                "seconds": round(time.time() - t0, 1), "stderr": p.stderr[-1500:], "events": events}
    finally:
        shutil.rmtree(work, ignore_errors=True)


READERS = {"codex": codex, "claude": claude}
