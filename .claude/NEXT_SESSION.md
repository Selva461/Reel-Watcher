# Next session: start here

Read, in this order (about 10 minutes): `CLAUDE.md`, `docs/PROJECT_CONTINUATION.md`, then this file. The design documents `docs/design/S4-backup-restore.md` and `docs/design/A1-R4-retry-and-schema.md` are for the tasks listed below. Then VERIFY the live state, do not trust any file over the repository: `git fetch --all`, the open PR list, the default branch head and version, the latest GitHub Actions runs.

## What was true when this was written (2026-11-16, about 04:00 UTC)
- Default branch `ccr-d0c0b070-bdpssy` at `cf5d8ca`, app 1.3.11 / versionCode 18. Merged since the last record: #39 (docs), #38 (the agent team in `.claude/agents/`), #41 (CI runs tests once, flaky UI tests fixed).
- Open and waiting for the owner: PR #37 (Task 4, all checks green, device checks E13-E19), PR #40 (R5: manual-only release publishing; only the owner merges), PR #33 (Task 2b, refresh and renumber, device checks E9-E11).
- Agents in flight (check `git ls-remote --heads origin`): R4-1 `test/r4-1-upgrade-fixtures` (tests only), P2 `performance/p2-search-index-related`, then P3 from `wip/p3-watchlist-index`. They stopped once at the 5-hour usage limit; resume, do not restart.

## Do this (in order)
1. Open the PR list. For each of #37, #38, #33: re-check status; do not redo finished work.
2. If the P2, P3, R3 branches exist: open one PR each, get the checks green, get an independent Opus review (`independent-reviewer`), fix Critical and High findings. R3 changes only CI and tests, so it may be merged under the standing conditions.
3. Release rule: a PR that changes `android/app-shell/**` OR `.github/workflows/android-apk.yml` publishes a public release when merged (CI; the workflow is in its own push paths, so even a Dependabot bump of it publishes). The owner said not to publish automatically. So such PRs are verified and LEFT READY, not merged, until the owner decides (see "UNRESOLVED CONFLICT" in `docs/PROJECT_CONTINUATION.md` section 12). Propose "R5": make the publish step of `android-apk.yml` manual-only; the owner merges that one.
4. Next unblocked task that publishes nothing: R4-1 (upgrade fixtures and round-trip tests, tests only), see `docs/design/A1-R4-retry-and-schema.md`.
5. Keep `docs/PROJECT_CONTINUATION.md` and this file current after every PR.

## Do not
- Do not repeat P1, the topic-key fix, Task 4's implementation or its reviews, the agent team setup, or the S4 and A1/R4 designs (done).
- Do not merge with a failing check, an open Critical or High finding, a missing required device check, or a version conflict. Do not publish a release. Do not delete or replace user data. Do not touch `AGENTS.md` or `README.md` unless the owner says so. Do not claim a test, review or device check that did not happen.
- Do not start a dependent task before its prerequisite is merged. One task per PR.

## Tools and team
Lead agent coordinates; specialists are in `.claude/agents/` once PR #38 is merged (restart the session once after that so Claude Code sees the new folder): Opus for architecture, data integrity, security, independent review; Sonnet for implementation, tests, performance. Subagents never merge, publish or touch GitHub.
