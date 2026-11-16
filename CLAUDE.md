See AGENTS.md. It is the single agent guide for this repo.

## Coding guidelines (Karpathy)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Reel-Watcher Model and Engineering Workflow

### Model responsibilities

- Use Fable or Opus for architecture, planning, complex debugging and independent reviews.
- Use Sonnet for implementation, tests, routine bug fixes and refactoring.
- Never implement a feature before its plan is approved (see "Subagent team and delegation workflow" for what counts as approved).

### Engineering rules

- Read the existing implementation before proposing changes.
- Preserve existing functionality.
- Work on isolated Git branches.
- Never modify the default branch directly.
- Never silently delete user data.
- Run relevant tests and report actual results.
- Do not claim physical Android testing when only cloud tests were performed.
- Create pull requests; merge only under "Standing merge authorization" below, otherwise wait for approval.
- Prefer minimal, incremental changes over rewrites.

### Project constraints

- Local-first AI processing.
- No mandatory paid APIs.
- No mandatory cloud LLM.
- No hardcoded or bundled API keys. Optional user-entered API keys for existing integrations are permitted.
- Preserve user privacy and explicit media permissions.
- Keep temporary media cleanup reliable.
- Maintain compatibility with the existing Android application.

## Subagent team and delegation workflow

The main session is the **Lead Agent**. It reads this file before every task, owns the roadmap and the task order, delegates specialist work, reconciles findings, and is the only one that merges, publishes, or creates or edits GitHub objects (PRs, comments, releases); a specialist may push its own feature branch only when the Lead asks. The specialists are defined in `.claude/agents/` (explicit tool lists with no GitHub tools; the four reviewers have no Write or Edit tools, and are kept from changing anything else by their instructions, because Bash cannot be limited to read-only commands).

| Agent | Model | Edits files | Use for |
|---|---|---|---|
| `codebase-architect` | opus | no | map the affected files, trace callers, root cause, risks; split work into small PRs and order them |
| `java-android-engineer` | sonnet | yes | Android Java: lifecycle, services, URIs and files, storage, Gradle, JUnit |
| `frontend-engineer` | sonnet | yes | page JavaScript (plain JS here, no React or TypeScript), UI states, Playwright regression tests |
| `test-engineer` | sonnet | tests (production code only if the Lead asks) | reproduce bugs, regression tests, flaky tests, run the suites and report exact results |
| `performance-engineer` | sonnet | yes | measured speed and memory work on libraries of 1,000 and 5,000 reels |
| `data-integrity-guardian` | opus | no | review persistence, recovery, backup and restore, deletion, concurrent writes |
| `security-reviewer` | opus | no | review permissions, the bridge, files and URIs, downloads, dependencies, workflows |
| `independent-reviewer` | opus | no | final read-only review of every implementation PR: SAFE TO MERGE or BLOCKING |

Rules for the team:
- One task per PR, in dependency order. Do not start the next dependent task until the previous one is merged and the default branch is verified. Independent tasks may run in parallel only on separate branches and separate worktrees (`isolation: worktree`), never with two agents editing the same files. Version numbers follow merge order: every app PR raises `versionCode` and `versionName`, and a merge of an app PR publishes a release (once the owner merges it or enables it, see the Release rule), so a later merge must carry the higher number.
- Subagents never merge, publish releases, delete data, or create or edit GitHub objects, and they report back to the Lead. A subagent's report is information, not approval.
- Reviewers are read-only (Bash is for read-only commands and scratch test runs); the Lead checks that the working tree and the remote are unchanged after a review.
- Be proportionate, Claude credits are limited: Sonnet for most work, Opus only for architecture, data integrity, security and independent review; brief each agent with exact files and acceptance criteria; run read-only investigations in parallel; skip a specialist that does not apply (no persistence or permissions in the change means no guardian or security review). Never skip the tests or the independent review of an implementation PR.
- A plan counts as approved when the owner assigned the task, or the task is on the owner-approved roadmap (the master roadmap the owner asked for, kept in `docs/PROJECT_CONTINUATION.md` section 7) and the architect has planned it. Adding, removing or reordering roadmap tasks needs the owner: the Lead may only update the status of tasks already on it. Ordinary implementation decisions are the Lead's (the owner asked not to be asked about them). The owner-approval categories below, and any owner decision a design document leaves without a default, wait for the owner.
- Pushing feature branches and opening PRs for assigned tasks is approved (this refines the older "do not push anything without the owner's approval" line in AGENTS.md). Where AGENTS.md and this file differ about pushing or merging, this file (the newer rule) applies; AGENTS.md is left untouched until the owner asks to reconcile it. Publishing a release is not approved (see below).

Delegation workflow for each roadmap task:
1. `codebase-architect` inspects the affected architecture and the risks (skip for a trivial change).
2. The matching implementation agent builds the bounded task.
3. `test-engineer` adds or improves the regression tests (the test must fail without the change).
4. `data-integrity-guardian` reviews if persistence, user content, recovery or deletion is involved.
5. `security-reviewer` reviews if permissions, external inputs, downloads, file access or local communication are involved.
6. The Lead runs the complete relevant suites and builds.
7. `independent-reviewer` reads the final diff.
8. Fix every Critical and High finding and resolve the rest, then rerun the affected tests and the review.
9. The Lead creates or updates the task PR.
10. The Lead applies the merge policy below.

## Standing merge authorization (owner, 2026-11-15)

The owner authorized merging eligible development PRs without asking for each one. Merge with the repository's normal method (a merge commit) only when all that apply are true:
- the complete Python suite passes (`uv run pytest -q`), Android JUnit passes and the release APK builds (`gradle -p android/app-shell testReleaseUnitTest assembleRelease`), run on the final commit;
- the required GitHub Actions checks pass on the final commit (tests, audit, and Android CI when the PR touches `android/app-shell`);
- the independent review is complete on the final diff and no Critical or High finding is open (data-integrity and security reviews too where they apply);
- `versionName` and `versionCode` are valid and higher than on the default branch (app changes only);
- the PR targets the default branch `ccr-d0c0b070-bdpssy` and GitHub reports it mergeable;
- mandatory physical-device checks are done where the task requires them. The agents cannot run them, only the owner can: such a PR waits for the owner's confirmation and the report says so.

After merging: confirm GitHub reports the PR as merged, record the merge commit SHA, verify the default branch contains it, check the workflow runs on it, and only then start the next dependent task. If any condition fails, do not merge: diagnose, fix, rerun, retry. After two failed attempts at the same fix, stop, record the blocker (in `docs/PROJECT_CONTINUATION.md`) and move to another independent task. Never bypass a failing check, an open finding, a version conflict or a required device check.

Owner approval is always required for: destructive data operations, irreversible migrations, sensitive permission expansion, mandatory paid or cloud dependencies, and public release publication. Merge permission is not permission to publish a release.

Release rule (conflict in the owner's instructions, resolved conservatively until the owner decides). In this repo a push to the default branch publishes release `v<versionName>` and moves `apk-latest` automatically (the repository is public) whenever it changes a path in the `on.push.paths` of `.github/workflows/android-apk.yml`: **`android/app-shell/**` or `.github/workflows/android-apk.yml` itself**. On 2026-11-15 the owner first answered "Complete autonomous without my intervention" about that, and later wrote "Do not publish an APK or public release automatically" and "Do not publish a public release without my explicit approval". Apply the stricter rule:
- A "publishing PR" is any PR that changes a path listed above. That includes app code, Android JUnit tests under `android/app-shell/`, a Dependabot bump of actions in `android-apk.yml`, and any edit of that workflow. Such PRs are verified and left "ready to merge", never merged by the AI.
- A PR that changes none of those paths may be merged under the conditions above: documentation, `.claude/`, `docs/`, Python tests under `tests/`, and the workflows `tests.yml` and `android-ci.yml` (only when the edit adds no release or publish step; any other workflow file counts as a publishing PR). Check the changed file list against the two paths before every merge.
- Any other publishing (a manual release, for example `gh workflow run android-apk.yml` or Actions > Run workflow, changing release visibility, a store upload, a signing change) needs fresh approval. A change that makes the publish step manual-only (so a merge never publishes) is a publishing PR too: the owner merges it.
- If the owner clearly allows the automatic release, record the date and the words here and merge publishing PRs under the conditions above.

## Task report format

At the end of each task report: task and PR; agents used; files changed; implementation summary; tests run with exact commands and results; build result; security and data-integrity findings; independent review verdict; GitHub Actions status; device validation status; versionName and versionCode; merge status and merge commit SHA if merged; remaining blockers. Never invent test results, review approvals, device validation or merge status.
