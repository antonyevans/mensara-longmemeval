# LongMemEval-S on a Mensara Mind: 472 of 500 (94.4%)

Run on 16 and 17 October 2026. All 500 questions of LongMemEval-S (the cleaned release), graded
with the benchmark's official answer-check prompt. Every answer, verdict and miss diagnosis is
in [`results/2026-10-17-m36/`](results/2026-10-17-m36/).

## Headline

| | Correct | Accuracy | 95% interval (Wilson) |
|---|---:|---:|---:|
| **All 500 questions** | **472 / 500** | **94.4%** | 92.0–96.1% |
| 69 questions never used during development | 68 / 69 | 98.6% | 92.2–99.7% |
| 97 questions outside the development set (the 69, plus 28 used to check the final changes) | 95 / 97 | 97.9% | 92.8–99.4% |
| 403 questions in the development set or studied after earlier runs | 377 / 403 | 93.5% | |
| Abstention (30 questions with no answer in the history; also counted in their types below) | 28 / 30 | 93.3% | 78.7–98.2% |

No harness errors and no unscored answers: every one of the 500 questions has a recorded answer
and a clean verdict. No answer was re-graded by hand.

**The judge was not GPT-4o.** The benchmark's paper grades with `gpt-4o-2024-08-06`. We graded
with OpenAI's `gpt-6-sol` (high reasoning effort) through a ChatGPT subscription, using the
official prompt unchanged. So this is not a like-for-like leaderboard number. Our 500 answers are
in [`hypotheses.jsonl`](results/2026-10-17-m36/hypotheses.jsonl), in the format the official
evaluator reads, so anyone can grade them with GPT-4o themselves:
`python -m lme_mind judge --answers results/2026-10-17-m36/hypotheses.jsonl --out gpt4o.jsonl`.

## By question type

| Type | Correct | Accuracy | 95% interval |
|---|---:|---:|---:|
| single-session-user | 69 / 70 | 98.6% | |
| single-session-assistant | 56 / 56 | 100.0% | 93.6–100% |
| single-session-preference | 27 / 30 | 90.0% | 74.4–96.5% |
| multi-session | 118 / 133 | 88.7% | 82.2–93.0% |
| temporal-reasoning | 125 / 133 | 94.0% | |
| knowledge-update | 77 / 78 | 98.7% | 93.1–99.8% |

Multi-session questions, which need counting or adding things up across many conversations,
remain the hardest.

## What was tested

LongMemEval-S gives each question a history of about 115,000 tokens of past chat sessions
between a user and an assistant (48 sessions at the median), then asks something only that
history can answer. Three real examples: "How much money did I raise for charity in total?",
"How many years will I be when my friend Rachel gets married?" and "Which streaming service did
I start using most recently?".

For each question:

1. The question's sessions were imported into a test member's private folder in a Mensara Mind,
   as dated Markdown files (the exact format is in [`lme_mind/dataset.py`](lme_mind/dataset.py)).
2. The Mind's history feature wrote a dated digest of each session, a timeline of all of them,
   and a cross-session summary of the latest value of each fact and the user's stated
   preferences. This is the same feature that handles any imported conversation history.
3. A fresh agent, with no memory of its own, was given only the date and the question. It ran in
   the Codex CLI (`gpt-6.1-sol`, medium effort), with web search, shell and every other tool
   switched off except five read-only Mind tools (`orient`, `list_zones`, `list_files`, `read`,
   `query`). Its instructions were the Mind's standing rule, the short text a Mind offers every
   user to add to their agent's instructions, plus the operating guidance the Mind serves to every
   agent. Nothing in the instructions was written for this benchmark.
4. The judge compared the agent's final answer with the reference answer.

The agent's operating guidance (protocol 0.4.3 at the time) has been revised since, so a run today
gets slightly different instructions.

The agent called the Mind's tools 11 times and took 43 seconds at the median.

**Software.** A test build of the Mind (0.20.4.91): release 0.20.4 plus the history fixes that
went into the next releases. Release 0.20.6 (18 October) is the first one installed on Minds that
contains all of them; 0.20.5 was published but replaced by 0.20.6 before any Mind installed it.

**How the run differed from normal use.** To keep a 500-question run to about a day, the
per-session digests were made ahead of time with the Mind's own digest instructions through the
Codex CLI (`gpt-6-luna`, low effort), and the cross-session summaries with `gpt-6.1-sol`. They
were placed in the Mind's own cache, and the Mind's own code built the timelines from them. In
normal use a Mind makes these itself with its own model connection, which is what the public
harness does. Sessions were imported with the Mind's write command on the server rather than
through MCP. The exact scripts, and a side-by-side of every difference, are in
[`measured-run/`](measured-run/README.md).

## How we got here, and what that means for the number

We did not start at 94%. Earlier measurements used different samples and, before 16 October,
smaller runs with a different mix of question types, so the rows below are not directly
comparable with each other:

| Date | Sample | Score | What changed before it |
|---|---|---:|---|
| 10 Oct | 50 full-history questions | 70.0% (35 / 50) | Baseline. Across this run and a companion arm of 49 questions given only the sessions that hold the answer, a quarter of agents (25 of 99) answered without opening the Mind, and 16 of those 25 were wrong |
| 14 Oct | 47 full-history questions, with no multi-session, single-session-user, preference or abstention questions | 87.2% (41 / 47) | Agents given the standing rule, so they check the Mind first; no agent skipped the Mind |
| 16 Oct | all 500 | 92.6% (463 / 500) | Keyword search rebuilt (rare words weighted, word stems matched, scored per passage); dated digest and timeline for imported history. 36 of these grades came from a second grading pass after the judge returned empty verdicts |
| 17 Oct | all 500 | 94.4% (472 / 500) | Long timelines split into pages; facts that a later session replaced are marked, and stated preferences are listed across sessions |

Each of those changes is general: search, the history feature and the agent guidance apply to
every Mind, and none of them looks at the question type or contains benchmark-specific text.
But we chose them by studying questions we got wrong, so the score on those questions is
optimistic. That is why we report the split:

- **403 questions** were in the development set of 95 (past failures, multi-session questions and
  a regression set) or were studied after earlier runs. 93.5% correct.
- **97 questions** were kept out of the development set. We then used 28 of them to check the
  final round of changes offline, among them all four that the 16 October run got wrong. 97.9%
  correct.
- **69 questions** were never used in development at all. 68 correct (98.6%). The one miss is a
  consolidation error caused by the final round of changes.

None of these is a sealed hold-out. We picked the split ourselves, and all 500 questions were in
the 16 October run, whose misses we studied. The untouched questions did not score lower than the
rest, which is what we would expect if the changes were general rather than fitted to the
questions we studied, but 69 questions is a small sample (interval 92.2–99.7%).

The 16 October and 17 October runs compare directly (same questions, digests, reader and judge,
different build): 20 earlier misses became correct and 11 earlier correct answers became wrong,
a net gain of 9. Some of the 11 were caused by the change itself: both consolidation errors below
came from the new marking of replaced facts. One rerun cannot separate the rest of the code
change from run-to-run variation in the reader and judge.

## The 28 misses

Every miss, with our diagnosis from the saved answer and the agent's trace. These are our
judgements, not re-grades: all 28 count as wrong.

| Class | Count | What it means |
|---|---:|---|
| Reasoning | 19 | The agent read the right sessions and reached the wrong answer: counted an item twice or missed one, used the wrong time window, mixed someone else's figure into the user's. This class also holds cases where the history and the reference answer disagree (one question asks about jewellery; the history describes a chandelier) |
| Hedging | 3 | The answer was there, but the agent qualified it or asked a question instead of answering |
| Known label error | 3 | The reference answer conflicts with the history. Two are documented upstream by others (`370a8ff4` in [#19](https://github.com/xiaowu0162/LongMemEval/issues/19) and [#41](https://github.com/xiaowu0162/LongMemEval/issues/41); `618f13b2` in [#38](https://github.com/xiaowu0162/LongMemEval/issues/38)); the third, `9a707b81`, is our own judgement |
| Consolidation error | 2 | The Mind's summary marked an older fact as replaced when the two applied in different contexts (a weekday routine and a weekend one; two different ages) |
| Judge strictness | 1 | An answer saying the records did not mention a friend, judged wrong against the reference "No, you did not visit with a friend." |

We also had a class ready for misses where the Mind did not hold or did not surface the answer
(a search or digest gap). By our diagnosis, no miss fell into it. The per-question notes are in [`miss-classifications.json`](results/2026-10-17-m36/miss-classifications.json).

The biggest remaining gain is in counting and adding up across sessions: deciding whether two
mentions are the same event, applying the question's exact time window, and separating what was
planned from what was done. We have not built that yet.

## Limits

- **One run.** Reader and judge both vary from run to run; the 16 to 17 October comparison
  shows answers flipping in both directions.
- **Not the canonical judge** (above). Grade the published answers with GPT-4o to compare with
  numbers that use it.
- **Tuned on the benchmark** (above). The untouched split is small and was chosen by us.
- **Interruptions.** The run was stopped several times by the test computer's Linux subsystem
  shutting down. Each restart skipped questions that already had a graded record, so no answer
  was graded twice, but an attempt that was cut off before saving may have been repeated.
- **A busy server.** Late in the run another test began on the same staging server, so load was
  not constant. The software build did not change.
- **Eight questions without a timeline.** Under contention on the server, the history step gave
  up for eight questions, so they had neither the timeline nor the cross-session summary; the
  agent worked from search and the raw sessions. All eight were answered correctly.

## Files

| File | What it is |
|---|---|
| [`answers.jsonl`](results/2026-10-17-m36/answers.jsonl) | One row per question: the agent's answer, the verdict, the split, tool-call count, time and our miss note |
| [`hypotheses.jsonl`](results/2026-10-17-m36/hypotheses.jsonl) | The same answers in the official evaluator's input format |
| [`outcomes.csv`](results/2026-10-17-m36/outcomes.csv) | One line per question, no answer text |
| [`summary.json`](results/2026-10-17-m36/summary.json) | The numbers above |
| [`miss-classifications.json`](results/2026-10-17-m36/miss-classifications.json) | The 28 diagnoses |
| [`untuned-question-ids.json`](results/2026-10-17-m36/untuned-question-ids.json) | The 97 questions kept out of the development set |
| [`untouched-question-ids.json`](results/2026-10-17-m36/untouched-question-ids.json) | The 69 of those never used in development at all |

The agents' answers cite the Mind files they read, so paths such as
`22-memory/recalls/<id>/history/session-024.md` appear in them; `<id>` identifies a test member
on our staging server.
