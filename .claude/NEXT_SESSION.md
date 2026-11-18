# Next session: start here

Read, in this order (about 10 minutes): `CLAUDE.md`, `docs/PROJECT_CONTINUATION.md`, then this file. The design documents `docs/design/S4-backup-restore.md` and `docs/design/A1-R4-retry-and-schema.md` are for the tasks listed below. Then VERIFY the live state, do not trust any file over the repository: `git fetch --all`, the open PR list, the default branch head and version, the latest GitHub Actions runs.

## What was true when this was written (2026-11-18, about 20:00 UTC)
- Default branch `ccr-d0c0b070-bdpssy` at `c166615` or newer, app 1.3.11 / versionCode 18, nothing published since v1.3.11.
- Waiting for the owner (all publishing PRs, never merged by the AI), merge order #37, #44, #47, #48, #53 (A1), #52 (S4-1), #56 (5a-1), #57 (A2-1), #58 (S4-2), #33 (Task 2b, refreshed onto #58, last of that line), then #67 (S4-3 restore, stacked on #33) and #66 (A2-2, stacked on #57); also #40 (R5, only the owner). Section 3 of `docs/PROJECT_CONTINUATION.md` has the table, versions and review results.
- Process rules: at most 2 agents at a time, one combined Opus review per ordinary PR, agents push WIP checkpoints, the hourly autopilot timer resumes work after a usage-limit reset (agents stopped by a 429 are resumed with SendMessage, never restarted; Fable agents need usage credits, use Opus or Sonnet). Read the PR head SHA from the PR before merging, never type one.
- Designs in `docs/design/`: S4, A1/R4, 5a/5b, A2. Done from them: R4-1, R4-2, A1, S4-1, S4-2, S4-3, 5a-1, A2-1, A2-2 (and Task 2b refreshed). In progress: A2-3.

## Do this (in order)
1. Open the PR list and the agent list; do not redo finished work. Check A2-3 (`stabilize/a2-3-existing-models`, stacked on #66 at `a7ef556`): the implementer's report (resume it with SendMessage and `scratchpad/a23/STATE.md` if it was stopped), one combined Opus review, fixes, PR body; leave READY.
2. Next roadmap task: after A2-3, S4-4 (list the files set aside), 5b (owner approval first), P4, A3, K1, U1-U4.
3. Release rule: a PR that changes `android/app-shell/**` OR `.github/workflows/android-apk.yml` publishes a public release when merged; such PRs are verified and LEFT READY, never merged, until the owner decides (see section 12 of `docs/PROJECT_CONTINUATION.md`). R5 (#40) makes publishing manual; only the owner merges it.
4. Keep `docs/PROJECT_CONTINUATION.md` and this file current after every work block (one docs PR per block).

## Do not
- Do not repeat P1, the topic-key fix, Task 4's implementation or its reviews, the agent team setup, or the S4 and A1/R4 designs (done).
- Do not merge with a failing check, an open Critical or High finding, a missing required device check, or a version conflict. Do not publish a release. Do not delete or replace user data. Do not touch `AGENTS.md` or `README.md` unless the owner says so. Do not claim a test, review or device check that did not happen.
- Do not start a dependent task before its prerequisite is merged. One task per PR.

## Tools and team
Lead agent coordinates; specialists are in `.claude/agents/` once PR #38 is merged (restart the session once after that so Claude Code sees the new folder): Opus for architecture, data integrity, security, independent review; Sonnet for implementation, tests, performance. Subagents never merge, publish or touch GitHub.
