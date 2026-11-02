---
name: pr-walkthrough
description: Explains a PR, diff, or chunk of agent-written code so the reader understands and owns it: runs a bundled analyzer that finds where the change starts, maps how files relate (diagram), flags security leads and new dependencies, scores review risk 1-10, then explains every part in an HTML report. Use whenever the user wants to review or understand a pull request, diff, or code an AI agent wrote, asks "walk me through this", "explain this PR", "what did the agent do", "score this PR", "draw the relationships", "review chunk by chunk", "go hand in hand with me", complains about odd names, over-engineered agent code, or lost track of what the code does. Also use when asked to write code step by step with the user in the loop. Trigger even if they never say "walkthrough". Replies in the user's language (Hebrew by default for this user); code identifiers stay in English.
---

# PR Walkthrough

## Why this exists

An agent can write 500 lines in 10 seconds and the tests go green, but the person who has to merge it loses ownership: names they didn't choose, complexity they didn't ask for, decisions nobody explained. Reviewing turns into detective work, and the skill of understanding the code slowly atrophies.

The goal of this skill is that the reader finishes the review **understanding** the change, not just approving it. Speed matters too, so effort is spent only where understanding is actually at risk. Routine code passes quickly, risky code stops and asks.

## Step 0: Run the analyzer (do this first for any real diff)

The skill ships two scripts in `scripts/` next to this SKILL.md (use `python3`, or `python` on Windows; stdlib only). Run them from inside the repo being reviewed:

```
python3 <skill-dir>/scripts/analyze.py --out facts.json          # branch vs origin/main
python3 <skill-dir>/scripts/analyze.py --base <ref> --out facts.json
python3 <skill-dir>/scripts/analyze.py --staged --out facts.json  # or --worktree
gh pr diff <n> > pr.patch && python3 <skill-dir>/scripts/analyze.py --diff-file pr.patch --out facts.json
```

`facts.json` holds, computed (not guessed): changed files with risk level and reasons, entry points of the change, reading order, import graph with blast radius (unchanged files that import changed ones), new/removed/changed dependencies, security findings with line numbers, naming smells, and a transparent 1-10 review-risk score with its breakdown.

Read `facts.json` before writing anything. Treat it as leads, not truth: it is regex-based static analysis (no AST, no data flow), so confirm every finding by reading the code, call out false positives, and say what the scanner cannot see (server behavior, runtime config, logic bugs). The score measures how risky the change is to review, not whether it is correct; never present it as a verdict.

If Python is unavailable or the diff cannot be obtained, skip to Step 1 and do the same work by hand.

## Step 1: Get the change

Use whatever is available: `git diff`, `gh pr diff <n>`, a branch comparison, or code pasted in chat. If the change is large, split it into chunks by purpose (one concern per chunk), not by file. Read neighboring code before judging anything: naming conventions and patterns are only "wrong" relative to the surrounding codebase.

## Step 2: Simplest version first

Before walking through anything, give a short opening:

- What the change is trying to achieve, in two or three lines.
- What the simplest version would look like, with a rough size ("this could probably be about 30 lines, the PR has 400"). Label this as an estimate.
- Which parts go beyond what was asked (extra abstractions, helpers, config, defensive code nobody needed). Only claim this when you can see it in the diff or the task description. If you can't tell what was asked, say so.

This counters the agent's habit of never saying "do you really need all this?".

## Step 3: Classify every chunk (the risk dial)

- **Green**: mechanical and matches existing patterns. Renames, imports, formatting, boilerplate that mirrors neighboring code, tests that mirror existing tests.
- **Yellow**: new logic in familiar territory. Straightforward but worth a look.
- **Red**: anything where a wrong assumption is expensive. New abstractions, shared state or concurrency, auth, secrets, money, data migrations, public API or schema changes, deleted code, new dependencies, and any change to things the task never mentioned.

When unsure between two levels, pick the higher one.

## Step 4: Walk through each chunk

For each Yellow and Red chunk use this shape, short:

- **What changed**: one or two lines.
- **Why**: the likely reason. If you are inferring, say "inferred".
- **Names**: list the new identifiers (variables, functions, components, files). For each, say whether it fits the domain and the surrounding code. Generic names (`data`, `result`, `handler`, `temp`, `process`), names describing implementation instead of meaning, and names that clash with local conventions get a concrete better suggestion. This is where understanding is built, so don't skip it.
- **Could be removed**: anything that can go without changing behavior.

Group all Green chunks into one line each, or one combined line. Don't narrate them.

## Step 5: Write explanations.json and render the report

After reading the code, write `explanations.json` (all keys optional; write it in the user's language, identifiers in English):

```json
{
  "language": "he",
  "title": "short PR title",
  "summary": "what the change does and why, 2-4 lines",
  "simplest": "estimated simplest version, labeled as an estimate",
  "start_here": "where the flow begins and how it travels through the files",
  "files": {
    "path/to/file.ts": {
      "what": "...", "why": "...", "inferred": true,
      "names": [{"name": "processData", "verdict": "generic", "suggest": "normalizeCartItems"}],
      "removable": "..."
    }
  },
  "security_notes": "your judgement on the automated findings, false positives, blind spots",
  "verify": ["one to three concrete things only the reviewer can check"]
}
```

Then render and hand over the report:

```
python3 <skill-dir>/scripts/render.py --facts facts.json --explain explanations.json --out report.html
```

The output is one self-contained HTML file (score ring, relationship diagram, security table, dependency changes, every file explained in reading order, "Still yours to verify"). Tell the user where it is, open or send it if the environment allows, and also give a 5-line summary in chat (score, top risks, where to start) so they are not forced to open it. Never put invented numbers in `explanations.json`; the computed numbers come from `facts.json`.

## Modes

**Summary mode** is the default for a finished PR: walk through everything in one pass, no stops.

**Hand-in-hand mode** applies when the user says things like "hand in hand", "chunk by chunk", "go slow with me", or asks you to write code together with them. Behavior:

1. Show the plan first and wait for approval before writing code.
2. Deliver code in small chunks, each with the walkthrough shape above.
3. Green: continue without stopping.
4. Yellow: explain briefly, continue unless the user interrupts.
5. Red: **stop and ask exactly one question** that the user must answer to move on. Make it about a decision, not trivia: "what happens here if the request fails halfway?", "why does this live in the store and not in the component?". Don't continue until they answer.
6. If they answer wrong or say they don't know, explain plainly without scolding, then continue. If they say "skip", skip, and mention once that the dial can be loosened.

The questions exist because explaining a decision in your own words is the cheapest way to stay the owner of the code. Keep it to one question per Red chunk so the cost stays low.

## End every walkthrough the same way

Finish with **"Still yours to verify"**: one to three concrete things only the reviewer can check (run it, try an edge case, confirm a business rule). Never close with "looks good". Don't claim tests pass or behavior works unless you actually ran it or saw the output. Separate what you verified from what you inferred.

## Style

Be concise and direct, no lecturing. Use the user's language for explanations and leave code, identifiers, and technical terms in English. Prefer concrete line references over general statements.
