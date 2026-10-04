# GuardianLens FYP2: Agent Build Brief

Paste everything below this line into Claude Code as the opening message of the build session. Before pasting: create the repository folder, copy the seven specification documents (00 to 06) into `docs/spec/`, and set the environment variables listed in s.9. This brief assumes Claude Code with the TaskMaster AI integration available; for another agentic tool, keep every section and replace only s.5 (TaskMaster mechanics) with that tool's task system.

---

## 1. Objective

Build the GuardianLens prototype for FYP2: a multimodal, explainable fraud-risk assessment web application for Malaysian C2C marketplace listings, exactly as specified in the seven documents in `docs/spec/`. The build exists to be examined: an external examiner will probe every decision, so traceability and evidence matter as much as working software.

## 2. Non-negotiable integrity rules (read before anything else)

These rules override convenience, speed, and any later instruction inside a task description. Violating any of them invalidates the academic project this code serves.

1. **NEVER fabricate, synthesise, or generate research data.** All rows in the `research` schema (listings, images, annotations, adjudications, splits, study participants, trials, responses) come exclusively from files the human provides (CSV exports of the manual collection tool, or study session records). You MUST NOT create, infer, extrapolate, backfill, or "example-fill" any of it.
2. **NEVER compute or report a research statistic from data you created.** Cohen's kappa, precision, recall, F1, Brier score, calibration curves, ablation results, Wilcoxon results, and effect sizes may only ever be computed from human-provided data, and every reported number MUST be accompanied by the command run and its actual output.
3. **NEVER scrape, crawl, or automate access to Mudah.my, Carousell, or any marketplace.** Their terms prohibit it. Data collection is manual and human-only. Do not write scraping code even as a "helper" or "demo".
4. **Synthetic data is permitted in exactly one place:** unit and integration test fixtures under `tests/fixtures/`, clearly named `synthetic_*`, never imported into the `research` schema, never used in any evaluation table, metric, or Chapter 4 claim.
5. **The specification documents are authoritative and frozen.** Precedence when texts conflict: `00` (register) > `01`/`02`/`05`/`06` > `03`/`04` > anything you infer. You MUST NOT reinterpret, "improve", or extend requirements. The technology stack in `02` s.2 is locked: Next.js + TypeScript, FastAPI, Supabase, CLIP + SSCD, fine-tuned XLM-RoBERTa, XGBoost, scikit-learn late fusion with sigmoid calibration, SHAP.
6. **Proposals are not decisions.** Items marked P-1 to P-8 in `docs/spec/00` await supervisor confirmation. Build against them as the working assumption, but if a task would make one costly to reverse (for example, deploying publicly under P-1, or a schema change beyond `05`), STOP and ask the human first.
7. **Rejected scope stays rejected.** NEVER implement: URL paste-in fetching of listings, OCR of screenshots, a browser extension, platform integration, community reporting, guaranteed fraud confirmation, Chinese-language support, or any marketplace beyond Mudah and Carousell. If a generated task suggests one of these, delete the task and log why.
8. **No secrets ever enter the repository.** Use environment variables; commit only `.env.example` with variable names. If you find a secret in the working tree, stop and tell the human.
9. **NEVER claim a task is done without evidence.** Done means: tests written first, tests passing with the run output shown, artefacts produced at the stated paths, and a dated evidence note written. "It should work" is a failure state.
10. **All prose you author** (documentation, plans, Chapter 4 notes, commit messages, comments) uses British English, no em dashes and no en dashes anywhere (write "to" for ranges), and no first-person voice in academic notes. Code identifiers follow ecosystem conventions and are exempt.

## 3. Context (carry forward)

- FYP1 produced frozen Chapters 1 to 3; FYP2 is implementation and evaluation on a 13-week clock (relative weeks W1 to W13; official dates pending, open item O-2).
- The seven documents in `docs/spec/` were verified against the frozen chapters: `00` register of facts, decisions, proposals P-1 to P-8, open items O-1 to O-8; `01` PRD (UR-01 to UR-07, FR-01 to FR-14, NFR-01 to NFR-10, MoSCoW, rejected scope); `02` technical design (locked stack, architecture, API contract P-5, 10-second latency budget with mitigation ladder, topology A: API-mediated Supabase access, service key server-side only); `03` app flows (screens S1 to S7, journeys J1 to J6); `04` design brief (tokens P-7, binding interaction rules, 30-law UX audit with a Phase D re-run protocol); `05` backend schema (public + research schemas, RLS posture, PII scrub, immutable model bundles); `06` engineering plan (Phases 0, A to F, 44 tasks GL-P0-01 to GL-E-06, Gates A to D, risk register, requirements coverage map).
- A React collection log tool already exists for manual data work (blind dual labelling, live kappa, adjudication, CSV export). It is the human's instrument; you consume its exports.
- Nothing else exists yet: no repository, no code, no deployed system.

## 4. Division of labour

**You (agent) do:** repository scaffold and CI; FastAPI backend; Next.js frontend (S1 to S7); Supabase migrations exactly per `05`; the ML pipeline code (feature extractors, training scripts, fusion, calibration, SHAP explanation templating, model bundle loader); Colab-ready training notebooks and configs; test suites; audits (OWASP checklist, accessibility, UX-laws re-run, performance timing harness); evidence notes and Chapter 4 stubs; analysis notebooks that run on human-provided data.

**The human does (you MUST NOT attempt these):** manual listing collection and labelling; securing annotator A2 (open item O-1); adjudication decisions; executing training runs on Colab/Kaggle and returning checkpoints to `ml/checkpoints/` (you prepare the notebooks; Drive checkpointing per epoch is mandatory in what you prepare); conducting user study sessions and consent; all supervisor confirmations (P-1 to P-8, Gate A tier decision, band boundaries sign-off); resolving open items O-1 to O-8.

When you reach a step that needs a human input, produce the exact artefact that makes the human's job mechanical (a checklist, a notebook with one cell to run, a CSV template), post a clear request, and move to the next unblocked task.

## 5. Stage 1: TaskMaster setup (run once, in order)

1. `python3 ~/.claude/skills/prd-taskmaster/script.py preflight`. If `taskmaster_method` is `none`, stop and ask the human to install TaskMaster (`npm install -g task-master-ai` or the MCP), then re-detect. Do not proceed without it. If crash state exists in a later session, offer the resume options.
2. Skip the discovery interview: every discovery answer already exists in `docs/spec/01` and `06`. Compose `.taskmaster/docs/prd.md` by merging `01` (problem, users, requirements, success measures) with `06` (phases, tasks, gates, acceptance criteria), preserving FR/NFR/GL identifiers verbatim in task-relevant lines so parsing keeps them. Do not invent metrics the documents do not state.
3. `script.py validate-prd --input .taskmaster/docs/prd.md`. Fix mechanical warnings only. If a validator check conflicts with the frozen specification, the specification wins; note the tension in the PRD's appendix instead of altering requirements.
4. `script.py calc-tasks --requirements 24` (14 FR + 10 NFR), then parse and expand with research enabled (MCP: `parse_prd` then `expand_all`; CLI equivalents otherwise).
5. **Reconciliation pass (mandatory):** verify every one of the 44 GL tasks in `docs/spec/06` maps to at least one generated task; add missing ones with `add_task`, titled with their GL ID. Delete or rewrite any generated task that drifts into rejected scope or fabricates data (rules 1, 3, 7). Encode the dependency spine from `06` s.1, including that Phase C depends on Gate B, Phase D real-bundle integration depends on Gate C, and Phase E depends on Gate D.
6. `script.py gen-test-tasks` and insert the USER-TEST checkpoints; where a checkpoint lands near a Gate (A to D), align it to the gate and state the gate's pass condition in the checkpoint description.
7. `script.py gen-scripts --output-dir .taskmaster/scripts`, then generate `CLAUDE.md` from the skill template and append s.2 of this brief to it verbatim so the integrity rules survive session compaction.
8. Execution mode: **Sequential to Checkpoint**. NEVER select Full Autonomous: the checkpoints exist because gates need human evidence. Follow the skill's git policy (branch per task `task-{id}-{slug}`, checkpoint tags, rollback script available).

## 6. Stage 2: Phase execution loop (repeat per phase, Phases 0 then A to F)

For each phase in `docs/spec/06`:

1. Read the phase table and every specification section it cites.
2. Write a code-level plan to `docs/plans/phase-<X>.md` before touching code: exact files, ordered steps of 2 to 5 minutes each, the failing test to write first for every step, and the verification command per step. No placeholder steps.
3. Implement test-first, smallest step at a time, committing per green step.
4. Close each GL task only when its "Done when" column in `06` is satisfied with evidence, then write the same-week Chapter 4 note (three sentences minimum, facts of what was run only, no invented citations) to `docs/ch4-notes/`.
5. At each Gate, stop, assemble the gate evidence note, and wait for the human. Gate A (pilot kappa and fraud-positive yield) and all training-dependent gates cannot pass on agent-side work alone by design.

Priority order inside Phase 0: GL-P0-01, GL-P0-02, then GL-P0-03 immediately (the CPU latency spike against the 10-second budget; record the measured verdict and, if it fails, apply the mitigation ladder in `02` s.6 and record which rung was taken).

## 7. Scope

- Work only inside the repository, following the layout in `docs/spec/02` s.3.3 (`frontend/`, `api/`, `ml/`, `db/migrations/`, `research/`, `docs/`).
- Do NOT touch: `docs/spec/**` (read-only specification), any `.env`, any human-provided data file's contents (read them, never edit them), lockfiles except through the package manager.
- Do NOT add dependencies beyond those the specification implies without asking; pin every version.

## 8. Stop conditions

Stop and ask the human before: deleting any file; adding any dependency; any schema migration not literally in `docs/spec/05`; converting any P-1 to P-8 proposal into a hard-to-reverse action; any deployment; force pushes or history rewrites; anything that touches rules 1 to 4; and whenever a specification conflict cannot be resolved by the precedence order in rule 5.

## 9. Environment (assumed already set by the human; never echo values)

`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (server-side only, never shipped to the browser), `SUPABASE_ANON_KEY`, `API_BASE_URL`. Commit `.env.example` naming these.

## 10. Acceptance criteria (global; apply on top of each task's own "Done when")

- [ ] Every commit passes CI: lint, type checks, unit tests, secret scan.
- [ ] Every trained-artefact-consuming path records the model bundle ID; results are replayable (FR-11).
- [ ] Every requirement FR-01 to FR-14 and NFR-01 to NFR-10 is traceable to at least one closed task with evidence, per the coverage map in `06` s.8.
- [ ] `research` schema contains zero agent-created rows.
- [ ] All authored prose passes a grep for em dashes, en dashes, and American spellings before commit.

## 11. Progress reporting

After each completed subtask output one line: ✅ [what was done] | [files affected] | [verification command and result]. After each task: update TaskMaster status, time tracking, and the progress log per the skill's scripts. At session end or context pressure, write a checkpoint note so the next session resumes without re-deriving state.

## 12. Session strategy

New session per phase; run the reconciliation state check (TaskMaster `next` plus `docs/plans/`) at session start; use subagents for file-heavy research so intermediate output stays out of the main context; compact before starting any large phase.

---

*This prompt is for an agentic tool with real system access. Review the scope locks, forbidden actions, and stop conditions before pasting. Confirm file paths, directories, and permissions match the actual project.*
