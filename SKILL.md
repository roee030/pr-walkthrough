---
name: pr-walkthrough
description: Explains a PR, diff, or chunk of agent-written code so the reader actually understands and owns it, instead of rubber-stamping it. Use whenever the user wants to review or understand a pull request, a diff, or code an AI agent wrote, asks "what did the agent do", "walk me through this", "explain this PR", "review this chunk by chunk", "go hand in hand with me", complains about odd variable or function names, about over-engineered or bloated agent code, or says they've lost track of what the code does. Also use when the user asks you to write code step by step with them in the loop. Trigger even if they never say "walkthrough". Replies in the user's language (Hebrew by default for this user), code identifiers stay in English.
---

# PR Walkthrough

## Why this exists

An agent can write 500 lines in 10 seconds and the tests go green, but the person who has to merge it loses ownership: names they didn't choose, complexity they didn't ask for, decisions nobody explained. Reviewing turns into detective work, and the skill of understanding the code slowly atrophies.

The goal of this skill is that the reader finishes the review **understanding** the change, not just approving it. Speed matters too, so effort is spent only where understanding is actually at risk. Routine code passes quickly, risky code stops and asks.

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
