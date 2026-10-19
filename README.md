# LongMemEval on a Mensara Mind

A Mensara Mind answered **472 of the 500 LongMemEval-S questions correctly (94.4%, 95%
interval 92.0–96.1%)** in a run on 16 and 17 October 2026. This repository has every answer we
graded, the scripts that produced the number, and a harness you can run against a Mind of your
own.

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) (Wu et al., ICLR 2025) tests whether
an assistant can answer questions about a long history of past conversations: about 115,000
tokens and 48 sessions per question. It asks for facts the user mentioned once, facts that
changed, counts and totals across sessions, dates and intervals, and preferences, and it checks
that the assistant says so when the history has no answer.

| Question type | Correct | Accuracy |
|---|---:|---:|
| Single-session (what the user said, what the assistant said, preferences) | 152 / 156 | 97.4% |
| Knowledge update | 77 / 78 | 98.7% |
| Temporal reasoning | 125 / 133 | 94.0% |
| Multi-session (counting and totals across sessions) | 118 / 133 | 88.7% |
| **All 500** | **472 / 500** | **94.4%** |

The 30 abstention questions, spread across those types, scored 28 / 30.

Read these caveats before you compare this with anything:

1. **The judge was `gpt-6-sol`, not GPT-4o.** We used the official grading prompt, unchanged,
   but not the paper's judge model. Our answers are in
   [`results/2026-10-17-m36/hypotheses.jsonl`](results/2026-10-17-m36/hypotheses.jsonl), in the
   official evaluator's format, so you can grade them with GPT-4o yourself (below).
2. **We improved the product while studying this benchmark.** 431 of the 500 questions were
   used in that work in some way. The 69 that never were scored 68 / 69 (98.6%); it is a small
   sample, and we chose the split.
3. **One run.** Reader and judge vary from run to run.

The full write-up, with every miss, is in [RESULTS.md](RESULTS.md).

## How it works

Each question's past sessions go into a Mind as dated files. The Mind's history feature writes a
dated digest of each session, a timeline, and a list of the latest value of each fact and the
user's preferences, using the Mind's own model connection. A fresh agent with no memory of its
own then gets the question and five read-only Mind tools, and nothing else: no web, no shell.
Its only instructions are the standing rule every Mind offers its users. The official prompt
grades the answer.

Nothing in the Mind or in the agent's instructions was written for this benchmark. The same
history feature handles any conversation history imported into a Mind.

## Grade our answers yourself

Needs Python 3.10 or later and an OpenAI API key; no Mind and no other dependency.

```bash
git clone https://github.com/antonyevans/mensara-longmemeval && cd mensara-longmemeval
export OPENAI_API_KEY=sk-...
python -m lme_mind judge --answers results/2026-10-17-m36/hypotheses.jsonl \
  --judge openai:gpt-4o-2024-08-06 --out gpt4o-grades.jsonl
```

This downloads the dataset (about 280 MB) from Hugging Face on first use, checks its hash, and
makes 500 calls with the official prompt at temperature 0. Or use the official evaluator: from
`src/evaluation/` in a LongMemEval checkout, run
`python3 evaluate_qa.py gpt-4o <path>/hypotheses.jsonl <path>/longmemeval_s_cleaned.json`.

## Run it on your own Mind

You need:

- **A Mensara Mind you own, on release 0.20.6 or later.** Use a new, empty Mind: the agent can
  read everything you can, so anything else in it can leak into answers. (Sign-up is not open
  yet; we are working with a small founding group. [Join the waitlist](https://app.mensara.ai/#waitlist).)
- **A model connection on the Mind.** The Mind makes the session digests with it: one call per
  session, about 48 per question, plus one call for the cross-session summary. Digests are cached
  by content, so rerunning a question costs nothing extra.
- **The Codex CLI**, signed in (`codex login`), for the reader. The published run used
  `gpt-6.1-sol` at medium effort. A Claude Code reader is included (`--reader claude
  --reader-model <model>`) but was not used for the published numbers.
- **A judge**: `OPENAI_API_KEY` for GPT-4o, or `--judge codex:gpt-6-sol` to use the Codex CLI as
  we did.

Then sign in once, as the Mind's owner, and run:

```bash
python -m lme_mind login --mind-url https://<your-mind>/mcp
python -m lme_mind run --mind-url https://<your-mind>/mcp --out runs/first --sample 30
python -m lme_mind summary runs/first --untuned results/2026-10-17-m36/untouched-question-ids.json
```

`login` opens your browser for the same sign-in Codex and Claude use, and keeps the tokens in
`~/.mensara-longmemeval/`, readable only by you. (A personal access token from the Mind's
`mint_owner_token` tool is not enough: the Mind treats its writes as lower trust and holds every
one for approval.)

For each question the harness:

1. clears your personal history folder (`22-memory/recalls/<you>/history/`). A Mind never
   applies a delete silently, so the harness proposes the deletes and approves its own review
   card;
2. imports the question's sessions with `propose_write`, up to 20 files per proposal;
3. waits for the Mind's history timer (every five minutes) to write a timeline covering every
   session;
4. asks a fresh reader the question, with your Mind's standing rule as its instructions;
5. grades the answer and saves a record in `runs/<name>/<question_id>.json`, with the reader's
   full trace in `traces/`.

It is resumable: run the same command again and it skips answered questions and grades only the
ones left unscored. A reader that never opens the Mind is run again, up to three times; the last
attempt is graded either way. A question where the harness itself fails is left as
`<question_id>.error.txt`, counted under `harness_errors` in the summary and kept out of the score.

**How long it takes.** We tested the harness on two of the smallest histories (38 and 39
sessions): about 10 to 15 minutes a question, most of it waiting for the Mind to make the
digests. Expect a 30-question sample to take most of a day and all 500 several days.

**How this differs from our run.** Our run imported sessions as root on a staging server and made
the digests ahead of time with the Mind's own digest instructions, so 500 questions finished in a
day. The harness here uses only what a Mind's owner has: MCP and the Mind's own history timer.
Your numbers can differ because of your model connection, and because the guidance a Mind serves
its agents has been revised since our run. [`measured-run/`](measured-run/README.md) has the
exact scripts we ran and every difference.

## Repository

| Path | What it is |
|---|---|
| [RESULTS.md](RESULTS.md) | Full results, method, misses and limits |
| [`results/2026-10-17-m36/`](results/2026-10-17-m36/) | All 500 answers, verdicts, miss diagnoses and the summary |
| [`lme_mind/`](lme_mind/) | The harness: standard-library Python, no dependencies |
| [`measured-run/`](measured-run/README.md) | The scripts that produced the published number |
| [`tests/`](tests/) | Offline tests: `python -m unittest discover -s tests -t .` |

The grading prompt in `lme_mind/rubric.py` is copied unchanged from LongMemEval (MIT licence,
Copyright (c) 2024 Di Wu); a test checks it against the original. Everything else here is MIT
licensed; see [LICENSE](LICENSE).

Mensara is built by Xanadu Labs LLC. Questions and corrections: open an issue.
