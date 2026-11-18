# Reel Shelf: project continuation record

Durable project state for any new Claude session. Written 2026-11-15 around 17:20 UTC and updated 2026-11-18 10:00 UTC from the live repository and GitHub, not from memory. Items marked **[V]** were verified against git or GitHub on that date. **UNKNOWN** and **NEEDS VERIFICATION** mean exactly that: do not treat them as done. Update this file after every completed PR (see "How to keep this file current").

## 1. What the project is

Reel Shelf (repo `Selva461/Reel-Watcher`) is an Android app that keeps the user's saved Instagram reels (and YouTube Shorts), reads them locally, makes notes, and lets the user search them and build a watchlist of titles. Local-first: on-phone models, no mandatory paid or cloud service, no login to Instagram, the user taps in Chrome themselves. `AGENTS.md` is partly stale (it still says "Windows edition"); the Android app is the active product. `README.md` is stale too. Both are deliberately untouched until the owner says to reconcile them.

Architecture [V, from the code and AGENTS.md]:
- **Android shell** `android/app-shell/app/src/main/`: a WebView loads `assets/local/` (plain JavaScript, no build step, no React or TypeScript, CSP forbids inline scripts): `local.js` (screens, run loop, library load and save), `notes.js`, `library.js` (search helpers, topics), `search.js`, `catalog.js` (watchlist), `shots.js` (screenshots), `titles.js`, `verify.js`, `home.js`, `watch.js`. The page talks to Java through `window.RN` (`LocalBridge.java`, about 68 `@JavascriptInterface` methods, trusted only for the built-in page).
- **Java** `java/app/reelshelf/`: `LibraryFile` (reels.json and shots.json: temp file, fsync, `.bak`, lock when unreadable, `.bad-TIME` set-aside, revision), `SharedQueue`, `SettingsPatch`, `LocalBridge`, `MainActivity`, `ShareActivity`, `WorkService`, `NightRun` (the nightly run uses a hidden headless WebView running the same page), `NightlyCheck`, `VerifyJob`, `TitleVerifier`, `TitleMatch`, `WebLookup`, `LocalModel` (LiteRT-LM: Qwen 2.5 1.5B, Gemma 4 E2B/E4B), `ScreenshotReader` (ML Kit OCR, Latin), `ReelVideo`, `SpeechModel` (Vosk, English).
- **Storage** in the app's files folder: `reels.json`, `shots.json`, `verify-results.json`, `models/`, `speech/`, `shot-inbox/`, `video-inbox/`; settings (including optional user-entered TMDB/OMDb keys) and the share queue in SharedPreferences. `allowBackup` is false.
- **Python engine** `src/reel_watcher/` and `webapp/`: the older PC edition (SQLite library). The Android app does not start it. Tests in `tests/` (Python; the "phone harness" drives the page in Chromium with a fake `window.RN`: `tests/test_phone_app.py`) and JUnit 4 in `android/app-shell/app/src/test/`.
- **CI** `.github/workflows/`: `tests.yml` (uv run pytest and pip-audit; on push and pull_request), `android-ci.yml` (JUnit and assembleRelease on PRs that touch `android/app-shell`), `android-apk.yml` (a push to the default branch that touches `android/app-shell/**` builds the APK and PUBLISHES release `v<versionName>` and `apk-latest`; the repository is public).

## 2. Repository state [V, 2026-11-18 09:50 UTC]

- Default (install) branch: `ccr-d0c0b070-bdpssy`, head **`c7e1d06`** (merge of PR #55). App version on default: **versionName 1.3.11, versionCode 18**; nothing since #36 touched `android/app-shell/**`, so no release was published after v1.3.11.
- Merged since the first records (none publishes): #41 R3 (CI runs once per PR commit), #38 the agent team, #43 and #45 R4-1/R4-1b (upgrade fixtures and round-trip tests), #49 Python lock (yt-dlp 2026.10.26, playwright 1.64.1, pytest 9.2.0; Dependabot #16 had been cancelled by an `apt-get` DNS failure on the runner, not by the packages), #50 `setup-uv` v10.2.0, #51 designs, #54 `83b4fb7` one shared Chromium per test run with a fresh context per test (17% faster, same 290 tests), #55 `c7e1d06` PC web settings race fix (a setting changed before the self-check answered was lost).
- `tests.yml` runs on push only for the default branch; the full Python suite takes about 5.5 minutes on GitHub. Known load-sensitive test: `TitleVerifierTest.tenTitlesAreCheckedAtOnceButEachServiceKeepsItsPace` (a wall-clock pacing check; it failed under load average 12 to 14 and passes on a quiet machine; unrelated to any change).
- Process rules in force (owner asked to cut waste and hitting the usage limit): at most 2 agents at a time; one combined Opus review per ordinary PR (a second reviewer only for persistence, permissions or the bridge, one after the other); no re-merging of moving stack branches by agents; agents push a WIP checkpoint at least every 40 minutes. A recurring hourly timer ("Reel Shelf autopilot") wakes the session after a usage-limit reset; the weekly limit may be used to 100%.
- Main checkout: branch `stabilize/task-4-background-media-copy` at `8e3c275`, clean. Agent worktrees live under `.claude/worktrees/` and the session scratchpad.

## 3. Open pull requests and branches [V, 2026-11-18 09:50 UTC]

All app PRs publish a release when merged (unless #40 is merged first) and are **left READY, never merged by the AI**. Merge order and provisional versions: **#37 (1.3.12 / 19), #44 (1.3.13 / 20), #47 (1.3.14 / 21), #48 (1.3.15 / 22), #53 A1 (1.3.16 / 23), #52 S4-1 (1.3.17 / 24), #56 5a-1 (1.3.18 / 25), #57 A2-1 (1.3.19 / 26), #58 S4-2 (1.3.20 / 27)**. Each branch contains the ones below it, except A1 (#53), #57 and #58, which are siblings on the R4-2 / 5a-1 line and will conflict only in CHANGELOG.md, TESTING.md and build.gradle (renumber at merge time). Every PR below had an independent Opus review (data-integrity or security first where it matters) and its findings are fixed; all results are from the computer, none from a phone.

| PR | What | Head | Review and device checks |
|---|---|---|---|
| #37 | Task 4: shared pictures and videos copied in the background, atomically | `8e3c275` | two Opus reviews, no blockers; device E13-E19 |
| #44 | P2: search, index and related reels fast in a big library (results identical) | `83dc49c` | SAFE TO MERGE (about 31,000 old-vs-new comparisons, 0 differences); E20 |
| #47 | P3: watchlist add and check no longer rescan the list | `58a575a` | SAFE TO MERGE (about 390,000 random operations, 0 differences); E21 |
| #48 | R4-2: `schema_version` and the newer-library rule (a newer library is never touched) | `6272154` | data integrity SAFE FOR DATA, independent SAFE TO MERGE; E22-E24 |
| #53 | A1: retry cap (3 tries, 12 h then 3 days), failure reason and "Try again now", fairer night queue | `492e131` | SAFE TO MERGE (17 of 19 breaks caught, 2 gaps closed); E25-E28 |
| #52 | S4-1: backup core (`LibraryBackup`, `snapshotTo`, `replaceWith`), no UI | `303e56f` | data integrity SAFE FOR DATA (3 Medium fixed), independent SAFE TO MERGE; no device row |
| #56 | 5a-1: strict temp-file sweep (allowlist; never inboxes, library, models) | `acb3d6a` | SAFE TO MERGE (15 of 16 breaks, survivor has a second guard); E29-E30 |
| #57 | A2-1: pinned model catalog, verified download (size and sha256, never installed if damaged); three hashes confirmed by real streamed downloads | `5028e67` | SAFE TO MERGE (live Hugging Face metadata re-checked); E31-E33 |
| #58 | S4-2: "Back up now" button (no restore yet) | `9fc15d4` | independent review IN PROGRESS; E40-E43 |
| #40 | R5: publishing a release is manual (`android-apk.yml`) | `bf20dcf` | only the owner merges it |
| #33 | Task 2b: nightly run and the app no longer overlap | `a0d205e` | based on the old default: refresh and renumber first; E9-E11 |
| Dependabot #9, #5, #4, #2, #1 | AGP 9.5.0 and actions bumps that touch the Android workflows or `build.gradle` | n/a | publishing PRs: owner (the Python lock and `setup-uv` bumps were re-applied and merged as #49 and #50) |

## 4. Recently merged [V]

| PR | What | Merge commit | Merged (UTC) |
|---|---|---|---|
| #45 | R4-1b: review follow-ups for the upgrade tests (hand-made library for the Verify.migrate downgrade, reset and delete rules at rules 0, 2 and 3; pinned page clock; stricter shots check) (independent review: SAFE TO MERGE, 4 Low) | `19bbd58` | 2026-11-16 04:40 |
| #43 | R4-1: upgrade fixtures for 14 released versions made by each tag's own page code, plus 47 round-trip tests (independent review: SAFE TO MERGE; 1 Medium and 5 Low, resolved in #45 except L2) | `d7935b6` | 2026-11-16 04:12 |
| #42 | Docs: continuation record update | `fa3ac7b` | 2026-11-16 04:04 |
| #41 | R3: CI runs the Python tests once per PR commit; two flaky UI tests fixed at their cause (independent review: SAFE TO MERGE, 4 Low) | `cf5d8ca` | 2026-11-16 03:55 |
| #38 | The subagent team (`.claude/agents/`, 8 agents), delegation rules, standing merge authorization and the Release rule in CLAUDE.md (two Opus reviews; the first was BLOCKING on a release loophole, fixed) | `050640c` | 2026-11-16 03:46 |
| #39 | This continuation record, NEXT_SESSION.md, the S4 and A1/R4 designs | `53119a2` | 2026-11-16 03:44 |
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
- Docs: `AGENTS.md` and `README.md` stale (owner said: not yet). Also stale after R3/R5: `TESTING.md` says dependencies are scanned "on every push and weekly" (now push only on the default branch), and the comment in `android-apk.yml` says "other branches are tested by tests.yml" (true only once a PR is open; that file is a publishing path: owner/R5).
- R4-1 test debt (optional, from the reviews, all Low): the empty-settings path is the only one covered (open-time rules that need settings such as `metaAi`, a ready model, `verifyRunning` are not; add when A1 adds retries); a rules-2 title never carries `verified_by` in the hand-made library, so "rule 2 also deletes verified_by" would go unnoticed; the shots signature is checked by shape and `notes_at`, not the exact length; a single-source verified title that looks like a comment line (downgraded then deleted at rules below 3) and an unverified title without a `verified` key are not covered; a few "EXPECTED" wording leftovers in `tests/test_library_upgrade.py` (about lines 75 and 80).
- **PC web app settings race** (`src/reel_watcher/webapp/app.js`, not the Android app): `settingsScreen()` draws the controls, awaits `GET /api/selfcheck`, and only then binds the handlers, so a change made before the answer arrives is silently dropped. Fix: bind first. `tests/test_app.py::test_ui_import_and_settings` may have the same latent race. Low priority (PC edition).
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
| 2026-11-16 | 0830710 (#39) | GitHub test x2, audit x2 | all success | runs 43799282708, 43799276407 |
| 2026-11-16 | 89f8120 (#38) | GitHub test x2, audit x2; agent-file validation script | all success; 8 of 8 valid | runs 43799393296, 43799388182 |
| 2026-11-16 | dd1a925 (#38) | independent Opus re-review | SAFE TO MERGE (one Medium and two Low fixed in 89f8120, not re-reviewed) | session log |
| 2026-11-16 | 494d330 (#41) | GitHub test (one run) and audit; independent Opus review | success; SAFE TO MERGE (4 Low); agent-run local suite 240 passed | run 43799977866 |
| 2026-11-16 | 7117848 (#43) | GitHub test and audit (PR run); agent-run full suite; independent Opus review | success; 287 passed locally; SAFE TO MERGE (14 fixtures regenerated byte-identical; 10 of 10 breaks caught) | run 43801828462 |
| 2026-11-16 | 48fe2aa (#45) | GitHub test and audit; independent Opus review; agent-run full suite | success; SAFE TO MERGE (10 of 11 breaks caught); 290 passed locally | run 43804341205 |
| 2026-11-16 | ea5ea74 (#44) | agent-run full suite and Gradle (on ea9a129); independent Opus review | 299 passed; BUILD SUCCESSFUL; SAFE TO MERGE | session log |
| 2026-11-16 | 83dc49c (#44) | GitHub Android CI (JUnit and assembleRelease), Tests, audit | all success (wording-only change on top of the reviewed ea5ea74, whose Android CI 43803841147 and Tests 43803841106 were also green) | runs 43805765415, 43805765345 |

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

**UNRESOLVED CONFLICT, handled conservatively.** In this repo merging a PR that changes `android/app-shell/**` makes `android-apk.yml` publish a public release automatically. On 2026-11-15 the owner first answered "Complete autonomous without my intervention" about that, and later wrote "Do not publish an APK or public release automatically" and "Do not publish a public release without my explicit approval". Until the owner says otherwise, the Lead's working rule is the stricter one. A push to the default branch publishes whenever it changes a path in `android-apk.yml`'s `on.push.paths`: **`android/app-shell/**` or `.github/workflows/android-apk.yml` itself**. So a "publishing PR" is any PR that touches either (app code, Android JUnit tests, a Dependabot bump of that workflow, any edit of it): verified and **left ready, never merged by the AI**. Only PRs that touch neither (docs, `.claude/`, `docs/`, Python tests under `tests/`, and the workflows `tests.yml` and `android-ci.yml`) may be merged under the standing conditions; check the file list before every merge. (Found by the independent review of PR #38.) A proposed fix is the small PR "R5": make the publish step of `android-apk.yml` run only on manual `workflow_dispatch` (the build and the artifact stay on every merge), so merging never publishes and the owner publishes with one click. R5 changes release publication, so the owner merges it.

## 12b. Where the project stands (estimate, 2026-11-18 10:00 UTC)

By task count with partial credit (merged 100%, built and independently reviewed but unmerged 85%, a design or an early start 5 to 30%, not started 0%): **about 60% of the roadmap is built, about 29% is merged to the default branch, and none has been checked on a real phone.** This is an estimate, not a measurement: the roadmap is not a fixed scope and can grow. Built and waiting for the owner: Task 4, P2, P3, R4-2, A1, S4-1, 5a-1, A2-1 and S4-2 (review in progress). Designed only: S4-3/S4-4 restore (needs Task 2b first), 5b (needs the owner's approval of the exact deletion rules), A2-2/A2-3. Not started: P4 memory, A3 prompt budget, K1 editable notes, U1-U4 storage and accessibility screens, R1 docs reconciliation.

Open owner decisions: **A1** a "not in the notes format" error counts toward the circuit breaker as the design says, so a model that gets the format wrong often could end a night after about 14 reels (alternative: only count model failures); **5b** deleting shared videos after success is a destructive user-data operation, the exact rules D-5b-1..6 in `docs/design/5a-5b-temp-files.md` need approval; **A2** D1-D5 (what to do with an existing unverified model, a failed check, redirect hosts); **S4/R4-2** a newer library has no way out of the newer screen except installing the newest build (D-R3), `VerifyJob` still reads a newer `reels.json` (harmless); whether to merge #40 so publishing becomes manual. Optional CI hardening: a retry or shorter timeout around the `apt-get` step of `tests.yml`; add `tests/fixtures/library/**` to the `android-ci.yml` paths so a fixtures-only change runs `LibraryFileTest`. Test-speed ideas not done: split the 65 s PC UI test `test_ui_every_screen_and_button_survives` (about 20% of the run), parallel runs (care: timing-budget tests).

## 13. Exact next steps (in order)

1. Check `git ls-remote --heads origin`, the PR list and the agents. Finish the S4-2 review (#58, agent id in the session) and fix its findings; update this file after each PR.
2. Next roadmap tasks, each stacked and left READY (all publish): **S4-3 restore** (needs Task 2b #33 refreshed and renumbered first, and S4-2 merged by the owner for the UI), then S4-4 (list the files set aside), 5b (only after the owner approves the rules), A2-2 (speech model) and A2-3 (existing and picked models), then P4, A3, K1, U1-U4, R1.
3. Merge only PRs that touch neither `android/app-shell/**` nor `.github/workflows/android-apk.yml`, after green checks and an Opus review. Docs, `.claude/`, `tests/` and `tests.yml` PRs qualify.
4. Owner to-do (do not wait): run the device checks E9-E11 and E13-E33, E40-E43; merge #40 if publishing should become manual; approve or change the decisions in 12b; then merge the app PRs in the order of section 3.

## 14. Instructions for the next Claude session

1. Read `CLAUDE.md`, this file, `.claude/NEXT_SESSION.md`, and the design documents in `docs/design/`. Then verify the live state yourself: `git fetch --all`, the PR list, the default branch head and version, the latest GitHub Actions runs. Do not trust this file over the repository; fix this file if it is stale.
2. Do not repeat finished work: P1, the topic-key fix, Task 4 implementation and its reviews are done (only the owner's device checks and the merge remain), the subagent team and the S4 and A1/R4 designs exist.
3. Work in bounded tasks, one task per PR, in dependency order; independent tasks on separate branches and worktrees; assign versions in merge order.
4. Delegate: Opus for architecture, data integrity, security and independent review; Sonnet for implementation and tests. Subagents never merge, publish or touch GitHub; the Lead does.
5. Never claim a test or a device check that was not run. Never merge with a failing check or an open Critical or High finding. Never publish a release without the owner.
6. After every completed PR update section 2 to 4, 10 and 13 of this file and `.claude/NEXT_SESSION.md`.

## How to keep this file current

After each PR: add it to section 4 (or 3), update the default-branch head, version and CI lines in section 2, the results in section 10, and the next steps in section 13. Keep claims verified; mark the rest UNKNOWN.
