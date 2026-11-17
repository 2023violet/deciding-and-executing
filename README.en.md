> **Status: v5.0.0 local candidate, not a stable release.** Paired real-agent behavior evaluations haven't been run. What changed in each version and how far it was verified is in the [CHANGELOG](CHANGELOG.md); past reviews and validation records are in [docs/history/](docs/history/) (Chinese).

# deciding-and-executing · From decision to delivery to a clean repo

[简体中文](README.md) | **English**

> Two companion Agent Skills that carry a piece of work from *thinking it through*, to *getting it done*, to *leaving the repo clean*.
> **deciding-and-executing** owns the work itself: set direction → plan → execute step by step → review and retrospect → close and archive.
> **closing-out** owns the repository's knowledge: when a stretch of work ends, it brings the README, docs, rule files and decision records back in line with the code.
> Scripts guard the gates, and they only claim what they can actually verify. What they can verify, they enforce. What they can't (for example, "did a human really approve this?"), they say so plainly and hand off to the host's approval mechanism.

![version](https://img.shields.io/badge/version-5.0.0--candidate-blue) ![spec](https://img.shields.io/badge/Agent%20Skills-open%20spec-green) ![platforms](https://img.shields.io/badge/Claude%20Code%20%7C%20Codex%20%7C%20claude.ai-supported-purple) ![python](https://img.shields.io/badge/python-3.8%2B%20stdlib%20only-yellow) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

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
- [Upgrading from 4.2](#upgrading-from-42)
- [Upgrading from 4.1](#upgrading-from-41)
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
| A step with a verification command (`verify_argv` / `verify_cmd`) is done only when the command runs and passes right then; no text can substitute | Whether file evidence is truthful → human review |
| When the code changes, old command evidence expires and must be re-run before review | Whether docs still describe behavior correctly → source fact-checking |
| After the failure limit, the step becomes `needs_replan` and can't continue unless the plan changes; a verify command that still fails after the code changed is counted by the script, not self-reported | A host in bypass mode skips everything → don't use it on important projects |
| A review verdict is tied to the code and plan; either changing voids it | Changes to git-ignored files → not in the code fingerprint; steps that depend on them need separate evidence |
| Deletion only touches a marked workspace inside the project that contains only known files and is committed to git | Deliberately forging both state.json and the event log → the script guards against carelessness and casual edits, not deliberate tampering |

**Three layers of authorization:**
1. **Script.** Two-step confirmation prevents one-shot mistakes and confirmations of content that has since changed.
2. **Process.** The agent must show you the preview and wait for your reply before confirming.
3. **Host.** Claude Code `permissions.ask` or Codex `prompt` rules. This is the only layer that brings a real human in.

High-risk work must configure layer 3. See [permissions.md](skills/deciding-and-executing/references/permissions.md).

## Quick start

### 1. Install

| Platform | Install | Invoke |
|---|---|---|
| Claude Code (plugin) | `claude plugin marketplace add 2023violet/deciding-and-executing`, then `claude plugin install deciding-and-executing@deciding-and-executing-mkt` | Automatic, or `/deciding-and-executing:deciding-and-executing` |
| Any skills-capable agent (Skills CLI) | `npx skills add 2023violet/deciding-and-executing` (`-a codex` / `-a claude-code` picks the host, `-g` installs for the user) | Automatic |
| Claude Code (personal) | `cp -r skills/* ~/.claude/skills/` | Automatic, or `/deciding-and-executing`, `/closing-out` |
| Claude Code (team) | Copy into the repo's `.claude/skills/` and commit | Same |
| Codex CLI / IDE, ChatGPT desktop | `cp -r skills/* ~/.agents/skills/` (or the repo's `.agents/skills/`) | Automatic, or `$deciding-and-executing`, `$closing-out` |
| claude.ai / Claude desktop | Settings → Skills, upload both `.skill` files from `dist/` | Automatic |
| Claude API | Upload via `/v1/skills`, reference with `container.skills` (requires the code execution tool) | Automatic |

> claude.ai can't read or write your git repo, so gates fall back to manual checklists and workspaces can't be deleted. Claude Code and Codex are recommended.
>
> The plugin and Skills CLI installs follow the official docs but haven't been tested in a clean environment yet; use `cp` if unsure. The plugin ships no session hook; turn one on yourself per [permissions.md](skills/deciding-and-executing/references/permissions.md).

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
| "Where did we leave off?" (new session) | ③ | `status` gives the stage and `next.cmd`; with the session hook on, `status --brief` is already in context; use `handoff` to hand the work to someone else |
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

On the standard tier, `gate AB` confirms gates A and B at once and `closeout` does 5A and 5B in one step; the high-risk tier still confirms them separately.

Changing the decision card's goal, success criteria, non-goals, key assumptions (except their status column), stop-loss, verdict or max fails invalidates gates A and B. Changing the plan's name, `first_step`, `if_then` or a step's structure invalidates gate B. Until you re-confirm, execution commands are refused.

**Step state machine.** `todo → in_progress → implemented → done`, plus `blocked` and `needs_replan`. A `done` step can't be moved back directly; use `reopen`, which archives the old evidence and voids the review. `needs_replan` is cleared only by `replan`.

**`de.py` commands**: the full command table and how to invoke the script (Claude Code, other hosts, Windows) are maintained only in [SKILL.md section 4](skills/deciding-and-executing/SKILL.md) (Chinese), or run `de.py --help`. The everyday ones are `init`, `status`, `gate AB` (or separate `gate A` / `gate B`), `step`, `verify --all`, `coverage`, `review`, `closeout` and `purge`. Commands that need confirmation first return only a `token` and a `preview`; after the user agrees, rerun with `--confirm`.

**Next action, handoff and the session hook:** every command's JSON carries `next = {cmd, why}`; `cmd` is the next legal action, ready to run, so the agent doesn't have to read the references to know what to do, and commands that need your consent are marked `needs_user`. `handoff` prints a read-only handoff in which each step's evidence freshness is derived by the script, not narrated. `status --brief` prints at most 15 lines of plain text for a session-start hook and nothing when there's no workspace.

**Automatic failure counting:** when the same verify command failed last time and fails again after the code changed, the script counts one failed fix attempt. The first failure is a baseline and reruns on unchanged code don't count. Steps without a verify command still use `fail`.

**Evidence rules for `done`:**
- **Step has a verification command:** the script runs it on the spot. Prefer `verify_argv` (an argument array, no shell, same behavior on every OS); use `verify_cmd` (system shell) only when you need pipes or redirection. It counts only if it exits 0 and the code didn't change while it ran.
- **Otherwise:** `--artifact FILE`, recorded with its hash.
- **Standard tier only:** `--evidence TEXT` is accepted but recorded as unverified, and flagged separately in status, review and the decision record.
- **High-risk tier:** text evidence is rejected.

Artifact evidence is re-checked (path, hash, code fingerprint) by `review --verdict pass` and a completed `archive`. The **code fingerprint** covers tracked git changes plus the contents of untracked files (32 MiB per file, 128 MiB total), but **not git-ignored files**. Evidence is only as good as the verification command's coverage of the real requirement.

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
| `rule-refs` | `@imports`, paths, or `npm` / `make` / `just` commands in rule files that don't exist |
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
| `.decision/plan.json` | While active | Plan structure (steps, criteria, verification commands, dependencies), written by the agent |
| `.decision/state.json` | While active | Status, evidence, gate records, review verdict; written only by the script |
| `.decision/events.jsonl` | While active | Append-only machine log, including a digest of every state.json write, so an interrupted write or an edit outside the script is detected |
| `.decision/progress.md` | While active | Human-readable progress and to-dos |
| `.decision/retro.md` | While active | Retro and where each lesson goes |
| `.decision/independent-review.md` | ④ (optional) | Independent review report; `review --independent-report` records its hash |
| `.decision/closeout-*.{json,md}` | 5B | Audit result and report for the knowledge sync |
| `docs/decisions/YYYY-MM-DD-name.md` | Permanent | Decision record: the *why*, plus evidence types, review verdict and the sync report |

## Repository layout

```
.
├── README.md / README.en.md
├── CHANGELOG.md                   Single source for versions, verification results and test counts
├── LICENSE
├── .claude-plugin/                Claude Code plugin and marketplace manifests (publishes skills/ as one plugin)
├── skills/                        ← The only thing you install
│   ├── deciding-and-executing/   SKILL.md, references/ (five stages, permissions, example, prompts, evidence),
│   │                              scripts/de.py, assets/ (templates), agents/openai.yaml
│   └── closing-out/              SKILL.md, references/ (routing, placement, example),
│                                  scripts/audit.py, assets/report.md, agents/openai.yaml
├── dist/                          Packaged .skill files (release_check verifies they match skills/)
├── experimental/                  Experimental third skill independent-verification (not installed by default; see README-完整交付说明.md)
├── docs/
│   ├── 教程-如何制作高质量Skill.md  Guide to building high-quality skills (Chinese)
│   ├── Skill-愿景与演进路线.md      Vision and roadmap (Chinese)
│   └── history/                    Review responses and validation records per version (historical, Chinese, not updated)
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

- **Agent-level behavior hasn't been independently evaluated.** The regression tests prove the scripts behave correctly. Whether an agent actually shows you the preview before confirming can only be measured by behavior evals, and those haven't been run on a real agent yet. Unit tests can't show that triggering, approval or long-task benefits hold in Claude Code or Codex.
- **Two-step confirmation can't prove a human confirmed.** If an agent breaks the process and confirms by itself, the script can't tell. That layer relies on host approval rules, which match command text and are not a security boundary.
- **Static audit doesn't understand meaning.** Whether docs describe behavior correctly needs source fact-checking.
- **Command checks cover the npm family, Make and just only.** Poetry, Cargo, Go and others aren't validated yet; a new task runner is one line in `RUNNERS` in audit.py.
- **macOS untested; Windows has regression tests only.** The regression suite passes on Linux and Windows (on Windows the symlink cases are skipped for lack of privilege; see the CHANGELOG). Host approval rules, the session hook and the read-only `allowed-tools` in SKILL.md haven't been tested on any platform.
- **Non-git projects get less.** There's no way to tell whether evidence matches the current code, and workspaces can't be deleted.

## FAQ

**Does everything go through the process?** No — see the tier table. A ten-minute fix gets no process.

**The script runs commands from plan.json — is that safe?** It only runs the steps' verification commands, and each command is listed in the `gate B` preview for you to approve. If anyone edits a command afterwards, gate B is invalidated and the script refuses to run it.

**Will closing-out delete my files?** No. The audit is read-only; deletions are only proposed.

**Will it change my agent memory?** Not by default.

**Why not use someone else's cleanup skill?** You can; the ideas overlap. closing-out shares one interface and set of conventions with deciding-and-executing, and moves more of the checking into a script.

## Upgrading from 4.2

In-progress workspaces need no migration and existing gate approvals stay valid. What changes for you:
- **`next` is now an object** `{cmd, why[, needs_user]}` on every command, not a sentence. Scripts or prompts that read it as a string need updating.
- **`current_step` in `status` respects dependencies and blocked steps**: in progress first, then implemented-but-unverified, then todo steps whose dependencies are done. It no longer points at a step whose dependencies are unfinished.
- **Verify-command failures are counted automatically** (rules above). Steps that used to rely on a manual `fail` may escalate sooner.
- **The session hook command is now `de.py status --brief`**, with no `test -f` guard; see permissions.md.
- `review` accepts `--independent-report` to link an independent review report.

## Upgrading from 4.1

In-progress workspaces need no manual migration. From 4.2, status, evidence and gate records live in `.decision/state.json`; the next write command moves them out of `plan.json`, and existing gate approvals stay valid. After that, `status`, `evidence` and similar fields in `plan.json` are ignored.

## Upgrading from 3.x

4.0.0 has breaking changes. To migrate an in-progress 3.x workspace:
1. **Decision card:** start the verdict with 做 / 改后做 / 放弃 (do / do-with-changes / abandon). Number the success criteria. Rewrite the stop-loss as three lines: trigger state / deadline / action.
2. **Plan:** add `covers` to each step, and `verify_argv` (or `verify_cmd`) where a command can verify it.
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
