# Independent Verification v0.2.0 — Candidate Evaluation Package

**Status: `LOCAL_CANDIDATE_READY_FOR_EXTERNAL_AGENT_EVALUATION`** (not a stable third core Skill).

This package builds on v0.1.0 without altering the frozen `deciding-and-executing v4.1.0` or `closing-out v2.0.1` baselines. It provides an independent, default read-only review procedure for code, UI and documentation, plus an explicit Stage 4 vs standalone-review experiment. There are no claims of actual Agent superiority.

## Contents

- `skill/independent-verification/` — candidate source, static triage script, protocol, examples and Codex metadata.
- `cases/` — three **synthetic**, deliberately flawed artifacts; not representative of broad real tasks.
- `tests/` — static checker, contract, safety, and comparison scoring tests.
- `EVALUATION/` — 6-run paired benchmark plan, scorer, operator-only gold issues, record schema.
- `results/` — real local static-check JSON and test/validation logs.
- `R1_SMOKE_OPERATOR.md` — preserved R1 exploratory 9-run operator instructions (still not run).
- `PILOT_ENGINEERING_REPORT.md` — current engineering findings, facts and evidence limits.

## Installation

For isolated testing, copy the **whole** `skill/independent-verification/` directory to `.agents/skills/independent-verification` for Codex or `.claude/skills/independent-verification` for Claude Code. Do not include `EVALUATION/operator_only` in any Agent workspace and do not install the candidate globally or into the frozen R1 experiments.

## Running the actual local static checks

From the extracted project root:

```bash
python skill/independent-verification/scripts/review_checks.py --root cases/code --contract cases/code/contract.json
python skill/independent-verification/scripts/review_checks.py --root cases/ui --contract cases/ui/contract.json
python skill/independent-verification/scripts/review_checks.py --root cases/docs --contract cases/docs/contract.json
python -m unittest discover -s tests -v
python EVALUATION/score_paired.py --operator-dir EVALUATION/operator_only --records-dir EVALUATION/records
```

Exit codes: `0` static probes pass **only**, `1` blocked, `2` invalid contract, `3` incomplete. `0` never grants release approval. The checker does not execute inspected project code. It does not prove behavioral security, runtime accessibility, document semantics, or human consent.

**Experimental comparator:** The scoreboard will report `INSUFFICIENT_PAIRED_DATA` until real Agent transcripts/independent judge records for both Stage4 and independent-review arms are supplied. See `EVALUATION/PAIRED_PROTOCOL.md`. The original R1 45-run experiment remains untouched.

## Important limitations

- Provenance data in a JSON contract is not cryptographically authenticated or checked against an external requirements authority.
- Only enumerated paths and criteria are inspected; a complete-looking checklist may omit the most important user requirement.
- Static UI and Markdown checks are heuristics, not browser or full Markdown checks.
- Root snapshot covers the recorded probes, not an entire Git repository; rerun for changed targets.
- Real Claude Code/Codex behavioral success and safety approval have **not** been measured by this package.
