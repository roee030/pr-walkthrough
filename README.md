# pr-walkthrough

**Stop rubber-stamping agent-written PRs. Understand them.**

An agent writes 500 lines in 10 seconds and the tests go green. Then you spend an hour doing detective work: why is it called `processData`, why is there a new abstraction, who asked for this config option? You approve anyway, because the alternative is slow. Over time you stop owning the code you ship.

`pr-walkthrough` is a Claude skill that makes review fast *and* keeps you the owner.

## What you get

One command-line analyzer plus an HTML report, driven by the skill:

- **Where it starts:** entry points of the change and a reading order that follows the imports.
- **Relationship map:** an offline SVG diagram of changed files and the unchanged files that import them (blast radius), colored by risk.
- **Security leads:** hardcoded secrets, SQL built by concatenation, `eval`, XSS sinks, cleartext HTTP, tokens in `AsyncStorage`, disabled TLS, new mobile permissions, and more, each with file and line.
- **Dependencies:** added, removed and version-changed packages from `package.json` / `requirements.txt`.
- **PR score 1-10:** with a visible breakdown (size, security, red files, new deps, missing tests). It measures how risky the change is to *review*, not whether it is correct.
- **Every part explained:** what changed, why (marked "inferred" when guessed), naming review, what could be removed, and a closing "Still yours to verify".

See a sample (synthetic project, Hebrew): [`examples/demo/report.html`](examples/demo/report.html).

The numbers come from `scripts/analyze.py` (Python 3, standard library only). The explanations are written by the agent and rendered by `scripts/render.py`.

> Honest limits: the analysis is regex-based static heuristics, strongest on JS/TS/React Native and decent on Python. It is not an AST, not data-flow analysis, and not a security audit. Treat findings as leads to confirm.

Run it by hand if you like:

```bash
python3 scripts/analyze.py --out facts.json                # current branch vs origin/main
python3 scripts/render.py --facts facts.json --out report.html
```

## How the review itself works

**1. Simplest version first.** Before any walkthrough, it tells you what the change is trying to do, what the simplest version would look like (rough size, labeled as an estimate), and what goes beyond what was asked.

**2. A risk dial for every chunk.**

| Level | Meaning | Treatment |
|---|---|---|
| 🟢 Green | Mechanical, mirrors existing patterns | One line, no narration |
| 🟡 Yellow | New logic in familiar territory | Short explanation |
| 🔴 Red | Expensive to get wrong: new abstractions, shared state, auth, secrets, money, migrations, public API, deletions, new deps, changes nobody asked for | Full walkthrough, and in hand-in-hand mode it **stops and asks you** |

**3. Naming review.** Every new variable, function and file is checked against the domain and the surrounding code. Generic names (`data`, `result`, `handler`) get a concrete better suggestion.

**4. Two modes.**

- **Summary mode** (default): one pass over a finished PR.
- **Hand-in-hand mode**: say "go chunk by chunk with me". The agent shows a plan, writes small chunks, and on every Red chunk asks exactly **one** decision question ("what happens here if the request fails halfway?") before continuing. Explaining a decision in your own words is the cheapest way to stay the owner.

**5. Always ends with "Still yours to verify".** One to three concrete things only you can check. Never "looks good". It won't claim tests pass unless it ran them.

## Install

Claude Code:

```bash
git clone https://github.com/roee030/pr-walkthrough ~/.claude/skills/pr-walkthrough
```

Or download `SKILL.md` and put it in `~/.claude/skills/pr-walkthrough/`.

## Use

```
walk me through this PR
```

```
review the diff on this branch chunk by chunk
```

```
let's build this together, hand in hand
```

It replies in your language; code and identifiers stay in English.

## Why a skill and not a linter

Linters check rules. This checks *understanding*: it raises the things a human reviewer would have to reverse-engineer, and it refuses to let the risky parts go by unexplained.

## Status

Early version. If it misses something or gets annoying on a real PR, open an issue with the diff shape (not the code) and what you expected.

## License

MIT
