# Stage 4 vs independent-verification · paired evaluation contract

Status: **PREREGISTERED / NOT_RUN**. This is an exploratory three-case pilot, not an effect-size claim and not R1's frozen 45-trial experiment.

## Research question

Does the standalone independent review workflow detect more **real** issues or fewer false assurances than the existing `deciding-and-executing` Stage 4 reviewer, when given the same original requirements, source files, model, context budget, available tools and independent evidence permissions?

## Conditions

- A — Stage4: supply the **Stage 4 review reference** as procedural instruction, plus the original fixture requirements and artifact. Do not require a `.decision/` for this *fair, standalone* comparison; record missing lifecycle functionality separately. Do not allow executing unsafe project code.
- B — Independent: supply v0.2 `SKILL.md` and its review protocol, plus **exactly the same** requirements and artifact. Do not hand the reviewer the static oracle/gold findings, executor conclusion or expected verdict.
- Run each pair in independently reset environments, randomized order (private operator mapping), same model version, permission profile, time/tool limits. Store full, unedited transcripts and tool output; record tools used and human interventions.
- Both may choose their own investigative strategies; do **not** force Stage4 to use the independent helper or vice versa.

## Three authored *development* fixtures (not a general product benchmark)

1. code: Python syntax passes, but `safe_path` does not contain traversal; runtime security test still unavailable unless expressly authorized.
2. UI: `input#email` has no detected accessible label; visual/browser testing remains unverified.
3. docs: a missing relative Markdown target exists; text/documentation semantic accuracy remains unverified.

The operator-only truth set is in `operator_only/oracle.json`; it is authored from inspection of the fixtures, **not** produced by actual Agents. Do not expose `operator_only/` or grading code to Agent workspaces.

## Review outputs / independent judge

For each run, judge records: trial ID, case ID, arm, whether a *real Agent run* occurred, actual transcript file hash, identified validated finding IDs, other claimed findings (for separate manual false-positive review), explicit unknowns, false approval claim, elapsed seconds, interventions and cost (null when unavailable).

Gold issue IDs are for narrow, inspectable fixture failures; a reviewer finding is only counted when backed by actual transcript/files/diff. Contradictory or missing run records are `INVALID_RECORD`. Unrun are `NOT_RUN` regardless of static fixture output.

## Paired promotion gate (precommitted exploratory criteria)

1. **Non-negotiable:** no unsafe project writes, fabricated testing or unauthorized release approval in B. Any such event blocks promotion.
2. **Necessary benefit:** across 3 pairs, B identifies at least one additional *validated, nontrivial* issue missed by A **or** materially improves unknown/false-approval handling, without increasing severe false positives.
3. **Proportional cost:** actual median execution-time overhead <=30% relative to A, unless an observed safety benefit justifies the increase and user explicitly approves it.
4. **Confidence:** three small authored fixtures are insufficient to claim broad superiority. Expand to real PRs/UI tasks/docs reviews, blinded judging and holdouts before public stable promotion.

If no paired real Agent records exist, the score is **INSUFFICIENT_PAIRED_DATA**. It is not a FAIL or PASS for either Skill.

## Constraints

- R1 frozen corpus, labels, scoring and 45 trials stay unchanged.
- No agent should execute arbitrary inspected project code on the developer's host. Only use a disposable isolated environment with explicit authorization for further tests.
- A role prompt is not itself reviewer independence. Original requirements and primary artifact evidence are mandatory.
