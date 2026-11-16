# Reel Shelf: project continuation record

Durable project state for any new Claude session. Written 2026-11-15 around 17:20 UTC and updated 2026-11-16 03:40 UTC from the live repository and GitHub, not from memory. Items marked **[V]** were verified against git or GitHub on that date. **UNKNOWN** and **NEEDS VERIFICATION** mean exactly that: do not treat them as done. Update this file after every completed PR (see "How to keep this file current").

## 1. What the project is

Reel Shelf (repo `Selva461/Reel-Watcher`) is an Android app that keeps the user's saved Instagram reels (and YouTube Shorts), reads them locally, makes notes, and lets the user search them and build a watchlist of titles. Local-first: on-phone models, no mandatory paid or cloud service, no login to Instagram, the user taps in Chrome themselves. `AGENTS.md` is partly stale (it still says "Windows edition"); the Android app is the active product. `README.md` is stale too. Both are deliberately untouched until the owner says to reconcile them.

Architecture [V, from the code and AGENTS.md]:
- **Android shell** `android/app-shell/app/src/main/`: a WebView loads `assets/local/` (plain JavaScript, no build step, no React or TypeScript, CSP forbids inline scripts): `local.js` (screens, run loop, library load and save), `notes.js`, `library.js` (search helpers, topics), `search.js`, `catalog.js` (watchlist), `shots.js` (screenshots), `titles.js`, `verify.js`, `home.js`, `watch.js`. The page talks to Java through `window.RN` (`LocalBridge.java`, about 68 `@JavascriptInterface` methods, trusted only for the built-in page).
- **Java** `java/app/reelshelf/`: `LibraryFile` (reels.json and shots.json: temp file, fsync, `.bak`, lock when unreadable, `.bad-TIME` set-aside, revision), `SharedQueue`, `SettingsPatch`, `LocalBridge`, `MainActivity`, `ShareActivity`, `WorkService`, `NightRun` (the nightly run uses a hidden headless WebView running the same page), `NightlyCheck`, `VerifyJob`, `TitleVerifier`, `TitleMatch`, `WebLookup`, `LocalModel` (LiteRT-LM: Qwen 2.5 1.5B, Gemma 4 E2B/E4B), `ScreenshotReader` (ML Kit OCR, Latin), `ReelVideo`, `SpeechModel` (Vosk, English).
- **Storage** in the app's files folder: `reels.json`, `shots.json`, `verify-results.json`, `models/`, `speech/`, `shot-inbox/`, `video-inbox/`; settings (including optional user-entered TMDB/OMDb keys) and the share queue in SharedPreferences. `allowBackup` is false.
- **Python engine** `src/reel_watcher/` and `webapp/`: the older PC edition (SQLite library). The Android app does not start it. Tests in `tests/` (Python; the "phone harness" drives the page in Chromium with a fake `window.RN`: `tests/test_phone_app.py`) and JUnit 4 in `android/app-shell/app/src/test/`.
- **CI** `.github/workflows/`: `tests.yml` (uv run pytest and pip-audit; on push and pull_request), `android-ci.yml` (JUnit and assembleRelease on PRs that touch `android/app-shell`), `android-apk.yml` (a push to the default branch that touches `android/app-shell/**` builds the APK and PUBLISHES release `v<versionName>` and `apk-latest`; the repository is public).

## 2. Repository state [V, 2026-11-15]

- Default (install) branch: `ccr-d0c0b070-bdpssy`, head **`f6a3f29`** (merge of PR #34).
- App version on default: **versionName 1.3.11, versionCode 18**. Release tags: v1.3.7, v1.3.8, v1.3.10, v1.3.11 (there is no v1.3.9: PR #33 is not merged).
- CI on the default branch: Tests success on f6a3f29 (run 43734081263); Android APK build success for 5cd4fcd (run 43734040483), which published release v1.3.11.
- Main checkout at the time of writing: branch `stabilize/task-4-background-media-copy` at `8e3c275`, clean, in sync with its remote.
- `.claude/worktrees/` holds worktrees of background agents (see section 3). They are not project files and are git-ignored (locally, and by PR #38).

## 3. Open pull requests [V]

| PR | Branch @ head | Version claim | Status and blockers |
|---|---|---|---|
| **#37** Task 4: shared pictures and videos copied in the background, atomically | `stabilize/task-4-background-media-copy` @ `8e3c275` | 1.3.12 / 19 | All GitHub checks green on 8e3c275 (android run 43738527111, test runs 43738527098 and 43738522141, audit). Local: 251 Python, 112 JUnit, assembleRelease OK. Two independent Opus reviews: no blocking findings; all Medium and Low findings fixed (the last two small commits were not re-reviewed). **Blocked: device checks E13-E19 not run (owner only), and merging publishes a release (see section 12).** |
| **#38** Subagent team and delegation rules | `chore/subagent-team` @ `d8a839c` | none (no app change) | 8 agent files + CLAUDE.md sections + `.gitignore` line. Validated by script (8 of 8 valid). Checks were still running when this was written. Publishes nothing. Needs its release wording aligned with section 12 before merge. |
| **#33** Task 2b: nightly run and the app no longer overlap | `stabilize/task-2b-night-run-lifecycle` @ `a0d205e` | 1.3.9 / 16 | Based on the old default (67f8050), versionCode 16 is below the default's 18: it must be refreshed (merge the default into it) and renumbered. Reviewed twice earlier in a previous session (the verdicts are in the PR history: NEEDS VERIFICATION before relying on them). **Blocked: device checks E9, E10, E11 (they exist only on that branch's TESTING.md) are not run.** |
| Dependabot #16, #9, #6, #5, #4, #2, #1 | various | n/a | Not reviewed. #9 (AGP 9.5.0), #5 (setup-gradle 6.x) and #4 (checkout 7.x) are risky major bumps: review before any merge; the workflows pin actions to commit SHAs. |

Background agents (update 2026-11-16 03:40 UTC): the P2, P3, R3 and R4-1 implementation agents and the independent review of #38 all stopped at 2026-11-15 about 17:25 UTC because of the 5-hour Claude usage limit (reset 20:00 UTC). Nothing was merged overnight: the default branch is still `f6a3f29`. Their partial work was NOT complete and NOT reviewed; it is saved, unreviewed, as WIP branches (do not merge them as they are):
- `wip/p2-search-index-related` @ `de509d9`: edits to `library.js` and `notes.js` plus `tests/test_phone_search_scale.py` (search, index, related speed).
- `wip/p3-watchlist-index` @ `cd1f540`: `catalog.js` index plus `tests/test_watchlist_scale.py` and `tests/catalog_before_index.js` (the old code kept as a test reference).
- `wip/r3-single-test-run` @ `27528fc`: `tests.yml` (push only on the default branch) and a `tests/test_app.py` fix for the flaky UI tests.
- R4-1 (upgrade fixtures): the agent died at its first step, nothing saved. The independent review of #38 also did not run.
The agents keep their context and can be resumed with SendMessage; if the container is gone, start from the WIP branches and the briefs in this repo's design documents.

## 4. Recently merged [V]

| PR | What | Merge commit | Merged (UTC) |
|---|---|---|---|
| #34 | Android CI (JUnit and assembleRelease on PRs) | `f6a3f29` | 2026-11-15 16:11 |
| #36 | 1.3.11: a topic link opens the group it counted (unique topic keys); fixed a racy test | `5cd4fcd` | 2026-11-15 16:11 |
| #35 | 1.3.10 (P1): opening a reel no longer works out the topics; chunked, cached topics | `1a9b7f3` | 2026-11-15 15:03 |
| #32 | 1.3.8 (Task 2a): stale saves refused, two-phase share queue, changed-keys-only settings | `67f8050` | 2026-11-13 |
| #31 | 1.3.7 (Task 1): an unreadable library is never overwritten (LibraryFile) | `92c6821` | 2026-11-12 |
| #30 | CLAUDE.md: model and engineering workflow rules | `a84013d` | 2026-11-11 18:44 |

## 5. Completed features and stabilization [V from CHANGELOG.md, code and merged PRs]

Features (see `CHANGELOG.md` for the per-version history, 1.0.0 to 1.3.11): share-sheet link import, Instagram export ZIP import (ZIP64), YouTube Shorts; captions from the public embed page, OCR of covers, video frames plus speech (Vosk), local video files; on-phone notes (Qwen/Gemma) with a filter that drops points the reel does not back up, quick notes without AI, a manual Meta AI flow; BM25 search with typos and synonyms, topics, related reels, Ask with an answer from the on-phone model; watchlist from screenshots with online title checks (TMDB with the user's own key, Wikidata, AniList, Jikan, MangaDex), quotes, products and recipes; nightly run and foreground service with Stop; exports.
Stabilization done: Task 1 (library file protocol), Task 2a (stale-write protection, share queue acknowledgement), Task 3 (Android CI), P1 (topics no longer freeze the app; measured on desktop only), topic key fix.

## 6. Known bugs and technical debt

Verified by measurement or code reading earlier in this project (desktop Chromium or JVM, never a phone):
- **Large-library memory**: `LibraryFile.valid()` and `VerifyJob.run` build a full JSON tree of the library (30-60 MB at 5,000-10,000 reels); a 256 MB-heap JVM ran out of memory at 60 MB. Not measured on a device. (P4)
- **No real backup or restore**: the existing export is lossy and cannot be imported; `allowBackup` is false; uninstall loses everything. (S4, designed)
- **Failed reels are retried forever** (no attempt counter in `needsWork`, `local.js`); the night queue is newest-first so the oldest are starved. (A1, designed)
- **No `schema_version`** in the library files; no rule for a library written by a newer app; only one old-version fixture exists. (R4, designed)
- **Search/related**: about 250-280 ms per search and about 0.7 s per `Notes.related` at 5,000 reels, cold index about 1.8 s in one block. (P2 in progress)
- **Watchlist** `Catalog.findSame` and `verify` rescan the whole list: 5,000 adds take about 24 s. (P3 in progress)
- **Shared-media files are never cleaned up** (`shot-inbox`, `video-inbox`, and Task 4's `share-staging` after a force-stop). (5a, 5b)
- **Model downloads are not hash-checked** and use mutable `resolve/main` URLs; Vosk size is not compared. (A2)
- **Prompt budget**: `Notes.localPrompt` can reach about 20,000 characters against a roughly 4,096-token Qwen context (HYPOTHESIS, NEEDS VERIFICATION). (A3)
- **Video codes** are a 32-bit hash of the file address (`shortHash`): collisions possible.
- **Flaky UI tests** under load: `tests/test_app.py::test_ui_search_language_and_filters`, `test_ui_check_identify_and_read` (race: navigate then act before the page settled). R3 agent investigating.
- `LocalBridge` creates four executors per instance and never shuts them down (Low).
- `onRenderProcessGone` is not handled (a killed WebView renderer takes the app down). Instagram/YouTube access relies on unofficial endpoints.
- The topic link on a reel appears only after the Ask screen has worked the topics out (by design of P1).
- Docs: `AGENTS.md` and `README.md` stale (owner said: not yet).
- Version collisions: #33 (1.3.9/16) and #37 (1.3.12/19) must be numbered in merge order (section 12).

## 7. Master roadmap, priorities and dependencies

Status legend: DONE, PR (open), AGENT (a background agent is on it), DESIGNED (design doc in `docs/design/`), TODO.

| Order | Task | Status | Depends on / notes | Publishes a release when merged? |
|---|---|---|---|---|
| 1 | Task 4 background media copy | PR #37 | owner device checks E13-E19 | yes (app) |
| 1 | Task 2b nightly lifecycle | PR #33 | refresh and renumber; device checks E9-E11 | yes (app) |
| 2 | R3 CI runs once, flaky UI test fix | AGENT | none | no (CI and tests only) |
| 2 | P2 search, index, related speed | AGENT | none | yes (app) |
| 2 | P3 watchlist index | AGENT | none | yes (app) |
| 3 | R4-1 upgrade fixtures and round-trip tests | DESIGNED (tests only) | none | no |
| 3 | R4-2 newer-library rule (`State.NEWER`) | DESIGNED | R4-1; Opus review | yes |
| 4 | 5a temp-file sweep (allowlist) | TODO | Task 4 merged | yes |
| 4 | S4 backup and restore (S4-1 to S4-4) | DESIGNED | S4-3 needs #33 (`NightGuard`); R4-2 helpful | yes |
| 5 | 5b delete shared videos after success | TODO (owner decision D2 recorded) | 5a and S4 (irreversible: follow the backup) | yes |
| 5 | A1 retry cap, backoff, visible failure reasons | DESIGNED (A1-1 to A1-3) | R4-1 | yes |
| 6 | P4 memory: scan instead of tree parse | TODO | P2, P3, device heap check; Opus design | yes |
| 6 | A2 model hash verification | TODO | needs real hashes from a real download | yes |
| 6 | A3 prompt budget and evaluation | TODO | Opus design | yes |
| 7 | K1 user-editable notes with preserved edits; K2-K5 | TODO | A1, R4 | yes |
| 7 | R1 reconcile AGENTS.md and README.md | TODO | owner says when | no |
| 7 | U1-U4 storage screen, accessibility, diagnostics, background plan | TODO | later | yes |

Merge rule: one task per PR, dependency order; versions follow merge order (section 12).

## 8. Data-integrity and security requirements (must hold)

- Never silently delete or replace user data. A damaged or older file is set aside (renamed), never removed. Writes: temp file, fsync, rename. Reels and screenshots go through `LibraryFile` and its revision protocol; a stale page's save is refused. The share queue is acknowledged by id only after a successful save.
- Local-first. No mandatory paid API or cloud LLM. No hardcoded or bundled API keys (optional user-entered TMDB/OMDb keys are allowed). Never use `--source apify`. No Instagram login, cookies or automation. Model downloads only from the allowed host. No em dash characters in Python sources (a test enforces it). Always `encoding="utf-8"` for text files.
- No real reel data in tests or examples: placeholders and generated data only.
- Permission or manifest changes must be documented and approved if sensitive. The bridge is for the built-in page only; escape every interpolated HTML value.
- Never claim device testing that was not done. Device checks are run by the owner (rows in `TESTING.md`).

## 9. Test and build commands

CI (authoritative): `uv sync --locked`, `uv run pytest -q`; `gradle -p android/app-shell testReleaseUnitTest --stacktrace`; `gradle -p android/app-shell assembleRelease --stacktrace` (Gradle 8.13, JDK 21, no wrapper; the Android SDK platform 36 is preinstalled on GitHub runners). The whole Python suite takes about 5.5 minutes.
In the cloud container used so far (EPHEMERAL, NEEDS VERIFICATION in a new session): `/home/user/Reel-Watcher/.venv/bin/python -m pytest -q -p no:cacheprovider`; Gradle and an Android SDK had to be set up under `/tmp` (`ANDROID_HOME=<sdk>`, Gradle 8.13). If they are gone, install them or rely on the GitHub Android CI job for the Gradle checks and say so.
Timing tests can fail when the machine is busy: rerun alone before treating as real. Do not loosen budgets. Deterministic generated libraries: `GEN_JS` in `tests/test_phone_topics.py`.

## 10. Test results with evidence [V]

| Date | Commit | Check | Result | Evidence |
|---|---|---|---|---|
| 2026-11-15 | f6a3f29 (default) | GitHub Tests | success | run 43734081263 |
| 2026-11-15 | 5cd4fcd | GitHub Android APK (built and published v1.3.11) | success | run 43734040483 |
| 2026-11-15 | b17c89a (#36) | local pytest / JUnit / assembleRelease | 240 passed / 68 passed / success | session log |
| 2026-11-15 | 8e3c275 (#37) | local JUnit / assembleRelease | 112 passed (68 + 44 new) / success, versionCode 19 | session log |
| 2026-11-15 | c9f886b-tree (#37) | local pytest | 251 passed (240 + 11 new); the later commit 8e3c275 changed only Java | session log |
| 2026-11-15 | 8e3c275 (#37) | GitHub android, test x2, audit | all success | runs 43738527111, 43738527098, 43738522141 |
| 2026-11-15 | d8a839c (#38) | agent-file validation script | 8 of 8 valid; GitHub checks running | session log |

Earlier results (Tasks 1, 2a, 2b, P1) were reported per PR; the numbers are in each PR description.

## 11. Physical-device tests pending (only the owner can run them)

- **E13-E19** (Task 4, PR #37): small and large image, video, several files and sharing them again, leaving mid-copy and a force-stop, low storage with Try again, responsiveness.
- **E9, E10, E11** (Task 2b, PR #33): watchdog and foreground-service start from an exact alarm, on-device handover.
- **E12** (P1, merged): a big library on the phone: reel opens at once, Ask shows "Working out topics...", topic page lists as many reels as the link says. Whether it was run: UNKNOWN.
- **E7, E8** (Task 1, 2a, merged): damaged library recovery and "night run meets the open app". Whether run: UNKNOWN.
- Android 15 dataSync limits, Doze and battery managers, real heap limits with 10,000 reels, MediaStore export to Downloads: never tested on a device.

## 12. Owner decisions, standing authorization and limits

Decisions recorded by the owner in the sessions (verbatim in spirit):
- Separate branch and PR per task; never modify the default branch directly; do not merge without the standing conditions below.
- Keep the optional user-entered TMDB/OMDb keys; the restriction means no hardcoded or bundled keys and no mandatory paid or cloud AI.
- Task 1 decisions: keep the share screen open during copying; delete shared videos only after successful extraction and saving (this is Task 5b: not yet implemented); skip the nightly run while the app is visible and hand over if the app opens (implemented in #33); one release per task PR; postpone device memory measurements.
- Task 2a: refuse stale saves and reload; accept temporary overlap until 2b; id-based acknowledgement.
- Do not modify `AGENTS.md` or `README.md` until told. Every app change bumps `versionCode` (+1) and `versionName` and adds a `CHANGELOG.md` section.
- Defaults the Lead adopted from the design documents (the owner can override): S4 D1-D7 and A1/R4 D-A1..D-R3 in `docs/design/`.

**Standing automatic merge authorization (2026-11-15).** The owner authorized merging eligible development PRs without asking each time, when: the complete Python suite passes; Android JUnit passes; the release APK builds; required GitHub checks pass; an independent review is complete with no open Critical or High finding; versionName and versionCode are valid and higher than the default branch; the PR targets the default branch and is mergeable; mandatory device validation is done where required. After merging: verify GitHub shows it merged, record the SHA, verify the default branch, then continue.

**Owner approval is always required for:** destructive user-data operations, irreversible migrations, sensitive permission expansion, mandatory paid or cloud dependencies, and public release publication.

**UNRESOLVED CONFLICT, handled conservatively.** In this repo merging a PR that changes `android/app-shell/**` makes `android-apk.yml` publish a public release automatically. On 2026-11-15 the owner first answered "Complete autonomous without my intervention" about that, and later wrote "Do not publish an APK or public release automatically" and "Do not publish a public release without my explicit approval". Until the owner says otherwise, the Lead's working rule is the stricter one: **PRs that change `android/app-shell/**` are verified and left ready, not merged**; PRs that publish nothing (docs, CI, tests only, `.claude/`) may be merged under the standing conditions. A proposed fix is the small PR "R5": make the publish step of `android-apk.yml` run only on manual `workflow_dispatch` (the build and the artifact stay on every merge), so merging never publishes and the owner publishes with one click. R5 changes release publication, so the owner merges it.

## 13. Exact next steps (in order)

1. Check `git ls-remote --heads origin` and the PR list. Finish R3 from `wip/r3-single-test-run` (CI and tests only: it may be merged under the standing conditions after the full suite and an independent review). Finish P2 and P3 from their `wip/*` branches (they change app code: verify and leave ready, do not merge, until the owner merges R5 or says otherwise). Then R4-1 (tests only).
2. Merge the docs PR that adds this file, then PR #38 after its checks, once its release wording matches section 12.
3. Open R5 (decouple publishing). Do not merge it.
4. Start R4-1 (upgrade fixtures and round-trip tests, tests only) per `docs/design/A1-R4-retry-and-schema.md`: it publishes nothing.
5. Owner to-do (record in the report, do not wait): run E13-E19 and E9-E11, decide the release question. When #37 is merged (owner), renumber and merge #33's refresh, then 5a, S4-1..S4-4, 5b, A1.

## 14. Instructions for the next Claude session

1. Read `CLAUDE.md`, this file, `.claude/NEXT_SESSION.md`, and the design documents in `docs/design/`. Then verify the live state yourself: `git fetch --all`, the PR list, the default branch head and version, the latest GitHub Actions runs. Do not trust this file over the repository; fix this file if it is stale.
2. Do not repeat finished work: P1, the topic-key fix, Task 4 implementation and its reviews are done (only the owner's device checks and the merge remain), the subagent team and the S4 and A1/R4 designs exist.
3. Work in bounded tasks, one task per PR, in dependency order; independent tasks on separate branches and worktrees; assign versions in merge order.
4. Delegate: Opus for architecture, data integrity, security and independent review; Sonnet for implementation and tests. Subagents never merge, publish or touch GitHub; the Lead does.
5. Never claim a test or a device check that was not run. Never merge with a failing check or an open Critical or High finding. Never publish a release without the owner.
6. After every completed PR update section 2 to 4, 10 and 13 of this file and `.claude/NEXT_SESSION.md`.

## How to keep this file current

After each PR: add it to section 4 (or 3), update the default-branch head, version and CI lines in section 2, the results in section 10, and the next steps in section 13. Keep claims verified; mark the rest UNKNOWN.
