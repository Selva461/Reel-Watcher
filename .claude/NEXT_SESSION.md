# Next session: start here

Read, in this order (about 10 minutes): `CLAUDE.md`, `docs/PROJECT_CONTINUATION.md`, then this file. The design documents `docs/design/S4-backup-restore.md` and `docs/design/A1-R4-retry-and-schema.md` are for the tasks listed below. Then VERIFY the live state, do not trust any file over the repository: `git fetch --all`, the open PR list, the default branch head and version, the latest GitHub Actions runs.

## What was true when this was written (2026-11-17, about 08:40 UTC)
- Default branch `ccr-d0c0b070-bdpssy` at `f313e2d` or newer, app 1.3.11 / versionCode 18, nothing published since v1.3.11. Merged since the last record: #49 (Python lock bump), #50 (setup-uv v10.2.0).
- Open and waiting for the owner (all publishing PRs, never merged by the AI): #37 Task 4 (device checks E13-E19), #44 P2 (E20), #47 P3 (E21), #48 R4-2 (E22-E24), #40 R5 (manual-only publishing; only the owner merges), #33 Task 2b (refresh and renumber). Stack order #37, #44, #47, #48, then A1, S4-1.
- In flight (check `git ls-remote --heads origin` and the worktrees under the session scratchpad): A1 `stabilize/a1-retry-cap` (1.3.16/23), S4-1 `stabilize/s4-1-backup-core` (1.3.17/24), the PC web settings race `fix/webapp-settings-race` (no publishing path: PR, Opus review, may merge), R4-2 closing. The 5-hour usage limit stopped the agents twice: push a WIP checkpoint, then resume with SendMessage, do not restart. Fable agents need usage credits: use Opus or Sonnet.
- Designs in `docs/design/`: S4, A1/R4, 5a/5b, A2.

## Do this (in order)
1. Open the PR list. For each of #37, #44, #40, #33: re-check status; do not redo finished work.
2. If the P3 branch (`performance/p3-watchlist-index`) exists and its agent has reported: open its PR (stacked on #44), get the checks green, get an independent Opus review (`independent-reviewer`), fix Critical and High findings, leave it READY. P2 is PR #44, R3 and R4-1 are merged.
3. Release rule: a PR that changes `android/app-shell/**` OR `.github/workflows/android-apk.yml` publishes a public release when merged (CI; the workflow is in its own push paths, so even a Dependabot bump of it publishes). The owner said not to publish automatically. So such PRs are verified and LEFT READY, not merged, until the owner decides (see "UNRESOLVED CONFLICT" in `docs/PROJECT_CONTINUATION.md` section 12). R5 (PR #40) makes the publish step manual-only; the owner merges that one.
4. Next roadmap task: R4-2 (`schema_version` and the "newer library" rule), see `docs/design/A1-R4-retry-and-schema.md`; its prerequisite R4-1 is merged. It changes app code, so stack it on the P3 branch (1.3.15 / 22), add a data-integrity review, and leave it READY.
5. Keep `docs/PROJECT_CONTINUATION.md` and this file current after every PR.

## Do not
- Do not repeat P1, the topic-key fix, Task 4's implementation or its reviews, the agent team setup, or the S4 and A1/R4 designs (done).
- Do not merge with a failing check, an open Critical or High finding, a missing required device check, or a version conflict. Do not publish a release. Do not delete or replace user data. Do not touch `AGENTS.md` or `README.md` unless the owner says so. Do not claim a test, review or device check that did not happen.
- Do not start a dependent task before its prerequisite is merged. One task per PR.

## Tools and team
Lead agent coordinates; specialists are in `.claude/agents/` once PR #38 is merged (restart the session once after that so Claude Code sees the new folder): Opus for architecture, data integrity, security, independent review; Sonnet for implementation, tests, performance. Subagents never merge, publish or touch GitHub.
