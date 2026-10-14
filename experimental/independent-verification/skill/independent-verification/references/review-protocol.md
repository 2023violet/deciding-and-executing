# Independent review protocol — v0.2.0 candidate

## 1. Independence means evidence, not role-play

Use a separate reviewer/context where available. Provide original requirements, exact revision and target artifact; withhold executor's conclusion until the initial assessment is finished. Reproduce findings from raw files and independently controlled tools, not copied verdicts. Different models alone do not guarantee independent information. If the same executor context is used, disclose that limitation.

## 2. Freeze the source and scope

- Identify where the original acceptance criteria came from; preserve them verbatim when possible.
- Track target commit SHA or file digests outside the review contract; source metadata alone does not authenticate origin or establish repository identity.
- Explicitly list excluded requirements, no-access systems and unavailable modes (GUI, hardware, network).
- Do not let the reviewer author both the decisive acceptance criteria and the evidence without an external check.

## 3. Evidence levels and applicability

| Level | Example | Establishes | Does NOT establish |
|---|---|---|---|
| Static probe | SHA-256, Python parse, heuristic HTML labels | Narrow property of observed bytes | Behavioral security, real accessibility, working UI |
| Authorized test | Tests in isolated environment + exit log | Covered behavior at tested revision | Untested cases / production behavior |
| Runtime observation | Browser, device, integration logs | Observed behavior under those conditions | Universal correctness |
| Independent review | Evidence mapping and reproduced finding | A reasoned human-facing verdict | Absolute certainty or authorization |

## 4. Contract schema and return codes

`review_checks.py` accepts v1 contracts for migration but prefers schema v2:

- `requirements_source`: kind/reference metadata for original source. Metadata is **not** authenticated.
- `requirements`: unique IDs and nonempty criterion text.
- `criteria`: unique check IDs, `requirement_id` pointing to a requirement, and narrow probe. Multiple checks may map to one requirement.
- Each enumerated requirement must be mapped to >=1 check, including an explicit `manual` check for behavior outside the static probe's ability.
- This guarantees only completeness *relative to the provided list*, never the completeness or truth of the source list itself.

Checker process exit codes:

| Code | Meaning |
|---|---|
| `0` | All declared static probes pass; **NOT a release approval** |
| `1` | At least one declared probe failed (`BLOCKED`) |
| `2` | Invalid contract or precondition (`INVALID_CONTRACT`) |
| `3` | Required independent evidence absent (`INCOMPLETE`) |

Both `BLOCKED` and `INCOMPLETE` prohibit a checker-derived success claim. The `observed_probe_snapshot_sha256` hashes the contract and recorded narrow observations only, **not** the full repository. If files change, rerun the check.

## 5. Reviewer verdict (not automatically issued by script)

- `BLOCKED`: confirmed criterion failure, unauthorized changes, or unacceptable safety issue.
- `INCOMPLETE`: essential evidence is not independently available.
- `READY_FOR_HUMAN_DECISION`: required checks independently reviewed; no known blockers; residual risk stated. Authorization remains human/host responsibility.

Never turn missing hardware, unrun tests, missing primary source or static-only proof into a successful production verdict.

## 6. Cross-skill and evaluation rules

Do not edit `.decision/`, Git state, source files or evaluation oracles. For comparative runs, follow `EVALUATION/PAIRED_PROTOCOL.md` in the separate operator kit. Stage 4 and this Skill can both give thoughtful verbal reviews; any measured advantage requires actual paired Agent trials and blinded, independent scoring.
