# Next session: start here

Read, in this order (about 10 minutes): `CLAUDE.md`, `docs/PROJECT_CONTINUATION.md`, then this file. The design documents `docs/design/S4-backup-restore.md` and `docs/design/A1-R4-retry-and-schema.md` are for the tasks listed below. Then VERIFY the live state, do not trust any file over the repository: `git fetch --all`, the open PR list, the default branch head and version, the latest GitHub Actions runs.

## What was true when this was written (2026-11-19, about 16:00 UTC)
- Default branch `ccr-d0c0b070-bdpssy` at `5d4ad8e` or newer, app 1.3.11 / versionCode 18, nothing published since v1.3.11.
- Waiting for the owner (all publishing PRs, never merged by the AI), merge order #37, #44, #47, #48, #53 (A1), #52 (S4-1), #56 (5a-1), #57 (A2-1), #58 (S4-2), #33 (Task 2b, refreshed onto #58, last of that line), then #67 (S4-3 restore, stacked on #33), #70 (S4-4, stacked on #67), #66 (A2-2, stacked on #57) and #68 (A2-3, stacked on #66), #75 (A3-2, based on the default branch) and #78 (A3-3, stacked on #75); also #40 (R5, only the owner). Section 3 of `docs/PROJECT_CONTINUATION.md` has the table, versions and review results.
- Process rules: at most 2 agents at a time, one combined Opus review per ordinary PR, agents push WIP checkpoints, the hourly autopilot timer resumes work after a usage-limit reset (agents stopped by a 429 are resumed with SendMessage, never restarted; Fable agents need usage credits, use Opus or Sonnet). Read the PR head SHA from the PR before merging, never type one.
- Designs in `docs/design/`: S4, A1/R4, 5a/5b, A2, P4, A3, K1. Done from them: R4-1, R4-2, A1, S4-1 to S4-4, 5a-1, A2-1 to A2-3, A3-1 (merged, tests only), A3-2 (#75, ready), A3-3 (#78, ready), A3-4 (merged, tests and TESTING.md only) (and Task 2b refreshed). K1 is designed and merged; K2 to K5 are undefined (owner).

## Do this (in order)
1. Open the PR list and the agent list; do not redo finished work. Nothing is waiting for review and no roadmap work is left that the lead may start without the owner. If the owner asks for more, the candidates are U1-U4 designs (docs-only PRs, Opus design first), K1-1 to K1-3 once A1 and R4-2 are merged, 5b after the owner approves the rules, P4 after the owner's device heap check.
2. Owner decisions waiting: the Delete button in S4-4 (#70), the 4,096-token window assumption (#75, #78: the budget never refuses, it only shortens), K2 to K5 (undefined), 5b rules, the A1 circuit breaker, the P4 and A3 defaults, merging #40.
3. Release rule: a PR that changes `android/app-shell/**` OR `.github/workflows/android-apk.yml` publishes a public release when merged; such PRs are verified and LEFT READY, never merged, until the owner decides (see section 12 of `docs/PROJECT_CONTINUATION.md`). R5 (#40) makes publishing manual; only the owner merges it.
4. Keep `docs/PROJECT_CONTINUATION.md` and this file current after every work block (one docs PR per block).

## Do not
- Do not repeat P1, the topic-key fix, Task 4's implementation or its reviews, the agent team setup, or the S4 and A1/R4 designs (done).
- Do not merge with a failing check, an open Critical or High finding, a missing required device check, or a version conflict. Do not publish a release. Do not delete or replace user data. Do not touch `AGENTS.md` or `README.md` unless the owner says so. Do not claim a test, review or device check that did not happen.
- Do not start a dependent task before its prerequisite is merged. One task per PR.

## Tools and team
Lead agent coordinates; specialists are in `.claude/agents/` once PR #38 is merged (restart the session once after that so Claude Code sees the new folder): Opus for architecture, data integrity, security, independent review; Sonnet for implementation, tests, performance. Subagents never merge, publish or touch GitHub.
