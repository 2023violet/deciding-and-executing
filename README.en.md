# deciding-and-executing · From decision to delivery to a clean repo

[简体中文](README.md) | **English**

> Two companion Agent Skills that carry a piece of work from *thinking it through*, to *getting it done*, to *leaving the repo clean*.
> **deciding-and-executing** owns the work itself: set direction → plan → execute step by step → review and retrospect → close and archive.
> **closing-out** owns the repository's knowledge: when a stretch of work ends, it brings the README, docs, rule files and decision records back in line with the code.
> Scripts guard the gates, and they only claim what they can actually verify. What they can verify, they enforce. What they can't (for example, "did a human really approve this?"), they say so plainly and hand off to the host's approval mechanism.

![version](https://img.shields.io/badge/version-4.0.1-blue) ![spec](https://img.shields.io/badge/Agent%20Skills-open%20spec-green) ![platforms](https://img.shields.io/badge/Claude%20Code%20%7C%20Codex%20%7C%20claude.ai-supported-purple) ![python](https://img.shields.io/badge/python-3.8%2B%20stdlib%20only-yellow) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

> **Language note:** the skills' instructions, templates and script messages are in Simplified Chinese. Claude and GPT models read them fine and reply in your language.

---

## Contents

- [The problem](#the-problem)
- [Two skills, one pipeline](#two-skills-one-pipeline)
- [What the scripts guarantee — and what they don't](#what-the-scripts-guarantee--and-what-they-dont)
- [Quick start](#quick-start)
- [Examples](#examples)
- [deciding-and-executing in detail](#deciding-and-executing-in-detail)
- [closing-out in detail](#closing-out-in-detail)
- [Files that appear in your project](#files-that-appear-in-your-project)
- [Repository layout](#repository-layout)
- [Development and testing](#development-and-testing)
- [Design principles and evidence](#design-principles-and-evidence)
- [Known limitations](#known-limitations)
- [FAQ](#faq)
- [Upgrading from 3.x](#upgrading-from-3x)
- [Contributing](#contributing)
- [License and acknowledgements](#license-and-acknowledgements)

---

## The problem

| Failure mode | What it looks like | Handled by |
|---|---|---|
| **Premature convergence** | The model goes along with your idea and hands you a satisfying conclusion nobody has tested | deciding-and-executing ① |
| **Thinking without doing** | The direction gets debated in depth, then execution starts from scratch | ② Plan |
| **Declaring done without being done** | "The code is written" is treated as "it works", with no evidence or with test results from an older version | ③④: command evidence is tied to a code fingerprint |
| **Blind retries** | The same failing step gets "one more try" again and again | After the failure limit, the script blocks the step until the plan changes |
| **Restarting at the first error** | One deploy error turns into a debate about the whole project | Two escalation levels; only the part that broke is reworked |
| **Not cleaning up** | Stale commands in the README, rule files pointing at deleted folders, working files the next agent mistakes for current goals | ⑤ Close-out + closing-out |

## Two skills, one pipeline

```
                           deciding-and-executing (the work)
① Direction ─A─► ② Plan ─B─► ③ Execute ─C─► ④ Review & retro ─D─► ⑤ 5A archive → 5B knowledge sync → 5C delete workspace
      ▲             ▲           │                                             │
      └─ Level 2 ───┴─ Level 1 ─┘                                             ▼
                                                         closing-out (the repo's knowledge)
                         audit → fact diff → route → subtract, then add → re-check → layered report → clean up once confirmed
```

| | deciding-and-executing | closing-out |
|---|---|---|
| Scope | One piece of work: decision, plan, execution, retro, closure | The whole repo: docs, rule files, decision records, leftover files |
| When | Starting something costly to redo | A stretch of work ends; milestones, releases, handoffs; after renames or removals |
| Script | `de.py`: gates, state machine, evidence, escalation, archive, delete | `audit.py`: read-only static audit |
| Standalone? | Yes (without closing-out, 5B falls back to a manual checklist and `sync` is unavailable) | Yes (works on any repo) |

The two skills hand off at 5B. After closing-out prepares the report, `de.py sync --report .decision/closeout-report.md` runs the installed audit script **during that invocation**, saves the result inside the workspace, and checks completeness, zero static errors and the current code fingerprint. Previously supplied audit JSON is never treated as proof of execution. Archiving (5A) on its own does not close the work.

## What the scripts guarantee — and what they don't

| Guaranteed (enforced by script) | Not guaranteed (stated, handed to something else) |
|---|---|
| Execution can't start until gate B has passed, and an approved plan that is then edited must be re-approved | Whether a confirmation token came from a human or the agent → host approval rules |
| A step with a `verify_cmd` is done only when the command runs and passes right then; no text can substitute | Whether file evidence is truthful → human review |
| When the code changes, old command evidence expires and must be re-run before review | Whether docs still describe behavior correctly → source fact-checking |
| After the failure limit, the step becomes `needs_replan` and can't continue unless the plan changes | A host in bypass mode skips everything → don't use it on important projects |
| A review verdict is tied to the code and plan; either changing voids it | |
| Deletion only touches a marked workspace inside the project that contains only known files and is committed to git | |

**Three layers of authorization:**
1. **Script.** Two-step confirmation prevents one-shot mistakes and confirmations of content that has since changed.
2. **Process.** The agent must show you the preview and wait for your reply before confirming.
3. **Host.** Claude Code `permissions.ask` or Codex `prompt` rules. This is the only layer that brings a real human in.

High-risk work must configure layer 3. See [permissions.md](skills/deciding-and-executing/references/permissions.md).

## Quick start

### 1. Install

| Platform | Install | Invoke |
|---|---|---|
| Claude Code (personal) | `cp -r skills/* ~/.claude/skills/` | Automatic, or `/deciding-and-executing`, `/closing-out` |
| Claude Code (team) | Copy into the repo's `.claude/skills/` and commit | Same |
| Codex CLI / IDE, ChatGPT desktop | `cp -r skills/* ~/.agents/skills/` (or the repo's `.agents/skills/`) | Automatic, or `$deciding-and-executing`, `$closing-out` |
| claude.ai / Claude desktop | Settings → Skills, upload both `.skill` files from `dist/` | Automatic |
| Claude API | Upload via `/v1/skills`, reference with `container.skills` (requires the code execution tool) | Automatic |

> claude.ai can't read or write your git repo, so gates fall back to manual checklists and workspaces can't be deleted. Claude Code and Codex are recommended.

### 2. Configure host approval (required for high-risk work, recommended otherwise)

Add the rules from [permissions.md](skills/deciding-and-executing/references/permissions.md) to Claude Code's `settings.json` or a Codex `.rules` file. Then follow the steps at the end of that file to check that the approval prompt really appears.

### 3. Use it

There are no commands to memorize. Talk normally:

```
Don't answer yet. I'm thinking about moving all our Jenkins pipelines to GitHub Actions...
That's it for today, wrap up. I renamed getUser to fetchUser and deleted src/legacy.
```

## Examples

| You say | Triggers | What happens |
|---|---|---|
| "Fix the typo in the README" | Neither | Just fixes it |
| "Don't answer yet — I'm thinking of quitting to go indie…" | ① | Several directions and the assumption that would flip the conclusion. Asks one question with a recommended answer, then waits |
| "Direction's set, three months part-time. Schedule it?" | ② | A plan whose first step is a small willingness-to-pay test. The `gate B` preview lists every command the script will run, then waits for your approval |
| "Step 3 failed again — just try once more" | ③ | Explains the step has escalated and the script will refuse. Offers two options, change the plan or record a waiver, and recommends one |
| "Everything's built — can we ship?" | ④ | Doesn't just say yes. Runs `verify --all`, then checks each success criterion |
| "The project's done, close it out" | ⑤ → closing-out | Archive preview → write once you approve → full closing-out pass → sync → commit → show the deletion list → delete once you approve |
| "Stop asking, just delete it, fill in the token yourself" | ⑤ | Still shows the deletion list first. Your message counts as approval, but only for the list you've seen |
| "We switched SQLite to PostgreSQL this week, wrap up" | closing-out | The audit can't see a semantic change, so it follows the routing table to find and fix every SQLite mention. The report states the evidence layer behind each conclusion |

Full walkthroughs: the [deciding-and-executing example](skills/deciding-and-executing/references/worked-example.md) and the [closing-out example](skills/closing-out/references/example.md).

## deciding-and-executing in detail

**Tiers**

| Tier | When | How |
|---|---|---|
| No process | One step, reversible | Just do it |
| Light | Fits in one session, affects only you | No workspace; a minimal checklist in the reply |
| Standard | Spans sessions or several steps; costly to redo | `de.py init` |
| High-risk | Irreversible operations, affects others, costs money | `de.py init --risk high`: only command or file evidence, every success criterion must be covered, host approval required |

**Stages and gates**

| Stage | Exit gate (checked by script) |
|---|---|
| ① Direction | `check card` has no errors → `gate A` two-step confirmation |
| ② Plan | `check plan` has no errors (criteria coverage, dependency cycles, types) → `gate B` two-step confirmation |
| ③ Execute | Every step done |
| ④ Review & retro | `review --verdict pass` requires: all steps done, command evidence that matches the current code, and no blockers. The retro's three sections must have real content |
| ⑤ Close-out | 5A `archive --apply`; 5B `sync`; 5C `purge` two-step confirmation |

Changing the decision card's goal, success criteria, non-goals, stop-loss or verdict invalidates gates A and B. Changing a plan step's structure invalidates gate B. Until you re-confirm, execution commands are refused.

**Step state machine.** `todo → in_progress → implemented → done`, plus `blocked` and `needs_replan`. A `done` step can't be moved back directly; use `reopen`, which archives the old evidence and voids the review. `needs_replan` is cleared only by `replan`.

**`de.py` commands** (call the script by its full path inside the skill folder; any subdirectory of the project uses the same workspace)

| Command | What it does |
|---|---|
| `init [--name] [--risk standard\|high]` | Creates the workspace. Never overwrites an existing one and refuses a non-empty unknown directory |
| `check card` / `check plan` | Validate only |
| `gate A` / `gate B` [`--confirm TOKEN`] | Two-step gate confirmation |
| `status` | Stage, gates, current step, stale evidence, text-only evidence, escalations, event-log consistency |
| `step ID --status S [--evidence TEXT \| --artifact FILE] [--hours H]` | State transition; see evidence rules below |
| `verify ID` / `verify --all` | The script runs `verify_cmd` and records the exit code, an output digest and the code fingerprint |
| `fail ID --note` | Records a failure; at the limit the step becomes `needs_replan` |
| `replan ID --note [--waive REASON --confirm]` | Clears escalation. The step must have changed, or a waiver is recorded with two-step confirmation |
| `reopen ID --reason` | Redo a finished step |
| `review --verdict pass\|fix\|fail [--blocker …] [--confirm]` | Records the review verdict |
| `archive [--outcome 完成\|止损\|放弃] [--apply]` | Writes the decision record (completed / stop-loss / abandoned). Deletes nothing |
| `sync --report` (`--audit-json` optional, fixed workspace output only) | Runs a fresh static audit, then records the knowledge sync |
| `purge [--confirm TOKEN]` | Deletes the workspace |
| `show` | Prints the plan table |

**Evidence rules for `done`:**
- **Step has a `verify_cmd`:** the script runs it on the spot. It counts only if it exits 0 and the code didn't change while it ran.
- **Otherwise:** `--artifact FILE`, recorded with its hash.
- **Standard tier only:** `--evidence TEXT` is accepted but recorded as unverified, and flagged separately in status, review and the decision record.
- **High-risk tier:** text evidence is rejected.

Exit codes: `0` success; `1` check failed; `2` usage or data error; `3` refused by a gate or confirmation needed (returns `token` and `preview`).

## closing-out in detail

**Three principles.** Each fact has exactly one authoritative home. Subtract before adding, and rewrite in place. Evidence changes status; memory and old docs are only leads.

**Two modes.** Light: end of every session, covering only what this session changed. Full: milestones, releases, handoffs, and after renames or removals.

**Seven steps.** Audit → fact diff → route by change type → subtract, then add → re-check (you must re-audit after editing) → layered report (deletions are only proposed) → once you confirm, clean up and audit again.

**Reports must state their evidence layer:** static audit, change-impact analysis, source fact-checking, or runtime verification. Different layers don't share one "pass".

**`audit.py`** (read-only)

```bash
python3 scripts/audit.py [--root .] [--base main] [--rename OLD=NEW ...] [--exclude 'glob' ...] [--max-findings 200]
```

| Check | What it finds |
|---|---|
| `rules-chain` | A directory's effective rule chain (one AGENTS file per level, repo root down to that directory) exceeds Codex's default 32 KiB; CLAUDE.md and AGENTS.md coexist without an import; CLAUDE.md over 200 lines; an AGENTS.override.md exists; CLAUDE.local.md isn't gitignored |
| `rule-refs` | `@imports`, paths, or `npm` / `make` commands in rule files that don't exist |
| `doc-commands` | Commands in the README and docs that don't exist |
| `dead-links` | Relative links to missing files (code blocks and inline code are ignored) |
| `stale-names` | Leftovers of `--rename` names. Skips history files and correctly handles a new name that is a prefix of the old one, or the reverse |
| `duplicate-lines` | The same long sentence in several documents |
| `residue` | Plan drafts, debug scripts, old copies, untracked files, including names with spaces, quotes or non-ASCII characters |
| `decision` | Decision workspace state. Workspace contents are excluded from doc checks and from the fingerprint |

The output includes `complete` (false if truncated), `evidence_level: "static"`, `limits` (what the audit can't see) and `fingerprint`. Exit codes: `0` no errors and output complete; `1` errors or truncated; `2` usage error.

## Files that appear in your project

| File | Lifetime | Contents |
|---|---|---|
| `.decision/.de-workspace` | While active | Workspace marker; deletion only acts on marked directories |
| `.decision/decision-card.md` | While active | Verdict, goal, numbered success criteria, non-goals, numbered assumptions, structured stop-loss |
| `.decision/plan.json` | While active | Steps, gate records, evidence, review verdict |
| `.decision/events.jsonl` | While active | Append-only machine log. The event is written before the plan, so an interrupted write is detected |
| `.decision/progress.md` | While active | Human-readable progress and to-dos |
| `.decision/retro.md` | While active | Retro and where each lesson goes |
| `.decision/closeout-*.{json,md}` | 5B | Audit result and report for the knowledge sync |
| `docs/decisions/YYYY-MM-DD-name.md` | Permanent | Decision record: the *why*, plus evidence types, review verdict and the sync report |

## Repository layout

```
.
├── README.md / README.en.md
├── CHANGELOG.md                   Single source for versions, verification results and test counts
├── LICENSE
├── skills/                        ← The only thing you install
│   ├── deciding-and-executing/   SKILL.md, references/ (five stages, permissions, example, prompts, evidence),
│   │                              scripts/de.py, assets/ (templates), agents/openai.yaml
│   └── closing-out/              SKILL.md, references/ (routing, placement, example),
│                                  scripts/audit.py, assets/report.md, agents/openai.yaml
├── dist/                          Packaged .skill files (release_check verifies they match skills/)
├── docs/
│   ├── 内审报告-v4.0.0.md          Point-by-point response to the external review, plus self-audit findings (Chinese)
│   └── 教程-如何制作高质量Skill.md  Guide to building high-quality skills (Chinese)
└── dev/                           release_check.py, validate_skill.py, run_trigger_eval.sh,
                                   tests/ (hermetic regression + adversarial), evals/<skill>/, eval-runs/
```

## Development and testing

```bash
python3 dev/release_check.py                       # everything: structure, tests, dist consistency, CHANGELOG, self-audit
python3 -m unittest discover -s dev/tests     # tests only
bash dev/run_trigger_eval.sh closing-out dev/evals/closing-out/trigger_evals.json 3   # trigger rate (Claude Code + jq)
bash dev/evals/closing-out/make_fixture.sh /tmp/fixture-co                            # closing-out fixture repo
```

The tests spawn many git subprocesses, so a full run takes tens of seconds; exact figures are in [CHANGELOG.md](CHANGELOG.md). They are isolated from your global git config (signing, hooks, editor).

**Three layers, accepted separately:**
1. **Static compliance:** `validate_skill`.
2. **Tool behavior:** the regression tests.
3. **Agent compliance:** the behavior and trigger evals in `dev/evals`, which must be run in Claude Code.

The CHANGELOG's "Verification" section says which layers the current version has completed.

**When you change a skill:**
1. Run it on real tasks and read the full transcripts.
2. Add a gotcha each time you correct the model.
3. For script changes, write a failing test first.
4. Run `release_check.py`.
5. Bump the version and update the CHANGELOG.
6. Run closing-out on this repo.

## Design principles and evidence

| Principle | Basis |
|---|---|
| In-conversation self-critique is only a draft; prefer external evidence | Huang et al., ICLR 2024 |
| Counter sycophancy; confidence needs reasons | Sharma et al., ICLR 2024 |
| One step at a time, state outside the model, no evidence means not done | Anthropic Engineering, *Effective harnesses for long-running agents* |
| Evidence tied to code version; three authorization layers; escalation is a hard stop | External engineering review (see the internal audit report); Claude Code permission docs; Codex rules docs |
| If-then contingencies | Gollwitzer & Sheeran meta-analysis |
| Stop-loss = trigger state + deadline + action | Annie Duke's kill criteria, *Quit* |
| AGENTS.md as single rule source, imported by CLAUDE.md; rule chains computed per directory | Claude Code memory docs; Codex AGENTS.md docs |
| Decision records separate from current-state docs | Common ADR practice |

Full rationale: [evidence.md](skills/deciding-and-executing/references/evidence.md).

## Known limitations

- **Agent-level behavior hasn't been independently evaluated.** The regression tests prove the scripts behave correctly. Whether an agent actually shows you the preview before confirming can only be measured by behavior evals, and those haven't been run on a real agent yet.
- **Two-step confirmation can't prove a human confirmed.** If an agent breaks the process and confirms by itself, the script can't tell. That layer relies on host approval rules, which match command text and are not a security boundary.
- **Static audit doesn't understand meaning.** Whether docs describe behavior correctly needs source fact-checking.
- **Command checks cover npm and Make only.** Poetry, Cargo, Go and others aren't validated yet.
- **Tested on Linux only.** Path and symlink handling is written to be portable, but Windows and macOS are unverified.
- **Non-git projects get less.** There's no way to tell whether evidence matches the current code, and workspaces can't be deleted.

## FAQ

**Does everything go through the process?** No — see the tier table. A ten-minute fix gets no process.

**The script runs commands from plan.json — is that safe?** It only runs `verify_cmd`, and each command is listed in the `gate B` preview for you to approve. If anyone edits a command afterwards, gate B is invalidated and the script refuses to run it.

**Will closing-out delete my files?** No. The audit is read-only; deletions are only proposed.

**Will it change my agent memory?** Not by default.

**Why not use someone else's cleanup skill?** You can; the ideas overlap. closing-out shares one interface and set of conventions with deciding-and-executing, and moves more of the checking into a script.

## Upgrading from 3.x

4.0.0 has breaking changes. To migrate an in-progress 3.x workspace:
1. **Decision card:** start the verdict with 做 / 改后做 / 放弃 (do / do-with-changes / abandon). Number the success criteria. Rewrite the stop-loss as three lines: trigger state / deadline / action.
2. **Plan:** add `covers` to each step, and `verify_cmd` where a command can verify it.
3. **Marker:** create a `.de-workspace` marker in the workspace, or `init` a new one and move the content over.
4. **Gates:** run `gate A` and then `gate B` to re-confirm.
5. **Close-out:** `archive --remove-workspace` is gone; use `archive --apply` → `sync` → `purge`.

## Contributing

Most valuable:
- Real failure cases; they become gotchas.
- Near-miss trigger queries.
- Agent behavior-eval results.
- Command checks for more ecosystems in `audit.py`.
- Windows and macOS runs.

Run `python3 dev/release_check.py` before submitting.

## License and acknowledgements

Released under the [MIT License](LICENSE). The methodology draws on several sources:
- Official skill docs from Anthropic and OpenAI.
- The [Agent Skills open specification](https://agentskills.io).
- Lessons shared by the Claude Code team.
- Open-source skill libraries including [anthropics/skills](https://github.com/anthropics/skills), [openai/skills](https://github.com/openai/skills), [obra/superpowers](https://github.com/obra/superpowers) and [KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills).

Most of the 4.0.0 changes came from an external engineering review. The full source list is in [the guide](docs/教程-如何制作高质量Skill.md).
