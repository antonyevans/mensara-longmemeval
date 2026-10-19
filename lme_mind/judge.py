"""Grade one answer with the official prompt.

`openai:<model>` is the benchmark's canonical judge (the paper uses gpt-4o-2024-08-06,
temperature 0) and needs OPENAI_API_KEY. `codex:<model>` runs the same prompt through the
Codex CLI on a ChatGPT subscription; the published run used `codex:gpt-6-sol` at high effort.
A judge run that fails or gives no yes/no label is retried and, failing that, left unscored
(None), never counted as wrong.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request

from .codexhome import codex_home
from .rubric import get_anscheck_prompt


def prompt_for(row: dict, hypothesis: str) -> str:
    qid = row["question_id"]
    return get_anscheck_prompt(row["question_type"], row["question"], row["answer"], hypothesis,
                               abstention="_abs" in qid)


def _openai(prompt: str, model: str) -> str:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "n": 1, "temperature": 0, "max_tokens": 10}
    req = urllib.request.Request(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
        json.dumps(body).encode("utf-8"),
        {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def _codex(prompt: str, model: str, effort: str = "high") -> str:
    with codex_home("lme-judge-") as home:
        cmd = ["codex", "exec", "--ephemeral", "--json", "--skip-git-repo-check", "--sandbox",
               "read-only", "-m", model, "-c", f'model_reasoning_effort="{effort}"',
               "-c", 'web_search="disabled"', "-C", str(home), "-"]
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "CODEX_HOME": str(home)}, timeout=240)
        events = []
        for line in p.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        items = [e["item"] for e in events if e.get("type") == "item.completed"]
        if p.returncode or any(i.get("type") not in {"agent_message", "reasoning"} for i in items):
            raise RuntimeError(f"codex judge exit={p.returncode} {p.stderr[-300:]}")
        texts = [i["text"] for i in items if i.get("type") == "agent_message"]
        return texts[-1] if texts else ""


def judge(row: dict, hypothesis: str, spec: str, attempts: int = 3) -> dict:
    provider, _, model = spec.partition(":")
    prompt = prompt_for(row, hypothesis)
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            raw = _openai(prompt, model) if provider == "openai" else _codex(prompt, model)
        except Exception as exc:  # noqa: BLE001 - retried, then reported as unscored
            last = str(exc)[:300]
            time.sleep(5 * attempt)
            continue
        if provider == "openai":
            # The official evaluator's own rule.
            return {"correct": "yes" in raw.lower(), "judge_raw": raw, "judge": spec}
        label = re.sub(r"[^a-z]", "", raw.strip().lower())
        if label.startswith(("yes", "no")):
            return {"correct": label.startswith("yes"), "judge_raw": raw[:40], "judge": spec}
        last = f"no yes/no label: {raw[:60]!r}"
    return {"correct": None, "judge_raw": "", "judge": spec, "judge_error": last}
