# U3: a local-only "Diagnostics" page with a copyable report (design, not approved)

Base for every file:line below: `origin/stabilize/s4-4-files-set-aside` at **563f81f** (PR #70, not merged, 1.3.25 / 32). Lines marked **A1** are from `origin/stabilize/a1-retry-cap` at **492e131** (PR #53, not merged; a sibling line, so `last_fail` is not on 563f81f). Lines marked **A2-3** are from `origin/stabilize/a2-3-existing-models` at **fd16625** (PR #68, not merged). Line numbers in `docs/` files (PROJECT_CONTINUATION.md) are from the docs branch `docs/designs-u1-u4`. Planning only: no code was changed. **The AI ran only computer tests; no phone test was run for this design.**

## Problem
When something goes wrong on the owner's phone (a night that did nothing, reels that keep failing, a model that will not load), the facts are spread over several screens or not shown at all, and there is no safe way to hand them to a helper. Copying screens by hand risks sending notes, links or keys. Goal: one page that shows the facts and makes a short text report that, by default, holds **no transcripts, notes, captions, links, names, file names, keys or other personal data**. The page sends nothing anywhere: no network, no analytics, no crash upload. The text leaves the phone only when the user copies or shares it.

## Verified in code (563f81f unless marked)
What the page can already read, all local and synchronous through `window.RN`:
| Fact | Source |
|---|---|
| App version name | `RN.appVersion()` (LocalBridge.java:182) |
| Library state (`ok`, `missing`, `recovered`, `unreadable`, `started_new`, `newer`), found and supported schema | `RN.libraryInfo(which)` (LocalBridge.java:161-178). **It has a side effect:** it calls `f.takeNotice()` (LocalBridge.java:168), which hands out the one-time "recovered"/"started_new" notice and clears it (LibraryFile.java:150-155); the page reads it in `loadDb` (local.js:83) and for screenshots in shots.js:41, which runs only when Screenshots is opened. So Diagnostics must **not** call `libraryInfo` (see the change). Also `bad` is a file name. `SCHEMA = 1` (local.js:73), `SHOTS_SCHEMA = 1` (shots.js:14), `REELS_SCHEMA`/`SHOTS_SCHEMA` (LibraryFile.java:46-47) |
| Reels by status | `db.reels[].status`, statuses in `STATUS` (local.js:761-764) |
| Last nightly run: time and up to 12 log lines | `db.lastNight = {at, log}` (local.js:655), shown on the run screen (local.js:1139) |
| Error of a reel | `r.error = e.message` (local.js:442, 455, 572) |
| Retry state: `tries`, `last_fail` (first 300 characters of the message), `last_fail_at`, `next_try_at` | **A1** local.js:600-606; shown on the reel (**A1** local.js:856-858) |
| Nightly title check: `{checked, verified, review, notFound, left, at}` | `RN.nightlyInfo()` (LocalBridge.java:1561-1575), written by NightlyCheck.java:78-80 |
| Nightly run settings and whether exact alarms are allowed | `RN.nightRunInfo()` (LocalBridge.java:1616-1627) |
| Model file, ready, size, backend, `verified` (yes/no/unknown/checking/own) | `RN.modelInfo` (LocalBridge.java:949-968; `verified` in **A2-3** LocalBridge.java:591-604) |
| Speech model ready | `RN.speechInfo()` (LocalBridge.java:1171-1180) |
| Battery level and charging | `RN.battery()` (LocalBridge.java:1465) |
| Files kept for safety | `RN.keptFiles()` (LocalBridge.java:570) |
| Last temp-file sweep | prefs `last_sweep` (TempSweeper.java:103-105); no bridge reads it yet (U1's `storageInfo` would) |
| Settings, including the user's optional TMDB and OMDb keys | `settings` (`DEFAULTS`, local.js:139) |
| Copy and share | `RN.copy` puts text on the clipboard (LocalBridge.java:713-718); `RN.shareText` opens Android's share menu (LocalBridge.java:723) |

Not available today: Android and WebView versions, whether notifications are allowed, whether the app is exempt from battery optimisation, any record of a crash (a killed renderer is not handled, PROJECT_CONTINUATION.md:94).

Error texts are mixed. Network errors from `request` give only the class name (LocalBridge.java:937-938), but other paths pass `e.getMessage()` through (for example `downloadModel`, LocalBridge.java:992, and `generate`, LocalBridge.java:1102), and page errors can hold an author, a title or a number. **So no error text can be trusted to be free of personal data.**

## Options
1. **A page plus a report built by an allowlist** (recommended): each line of the report is made from a known field by a known rule; anything not in the table below is left out.
2. A dump of `settings` and `db` with known private fields removed (a deny-list). Any new field leaks by default. Rejected.
3. Logcat export. Needs a permission it cannot have and holds other apps' lines. Rejected.

## The change (option 1)
**Page:** route `#/diagnostics` (a row in `ROUTES`, local.js:1642-1651), opened from a "Diagnostics" link at the bottom of Settings. It shows, in plain words: version; library and screenshot-list state and schema; counts; the last nightly run (time and its lines); the nightly title check; failures (counts by kind, newest dates); models and speech; nightly settings and permissions; storage totals (if U1 is built); last cleanup.
- One switch, **off** every time the page opens: "Include error messages (links, @names, long numbers and paths removed; titles may remain, read before sharing)". No other switch.
- Library state comes from a new **side-effect-free** bridge method `RN.libraryState(which)` that returns only `{state, found, supported}` (no `bad` file name, never touches the notice). Diagnostics never calls `libraryInfo`.
- The page shows no picture and loads nothing: no `<img>`, no `https:` anywhere in its markup (the CSP allows `img-src https:`, index.html:7, so an image would be a network request).
- Buttons: **Copy report** (`RN.copy`) and **Share report** (`RN.shareText`, the user picks the app). The report is shown in full on the screen above the buttons, so the user sees exactly what leaves.
- One line under the buttons: "The report stays on this phone until you copy or share it. Reel Shelf never sends it anywhere."

**Java (small, read-only, no permission):** `RN.deviceInfo()` gives `{android, sdk, webview, notifications, exact_alarms, battery_exempt}` from `Build.VERSION`, `WebView.getCurrentWebViewPackage()` (API 26+), `NotificationManager.areNotificationsEnabled()`, `AlarmManager.canScheduleExactAlarms()` (API 31+ only: `SDK_INT < 31 || canScheduleExactAlarms()`, as LocalBridge.java:1622 does) and `PowerManager.isIgnoringBatteryOptimizations()`. That none of these needs a permission is NEEDS VERIFICATION. The device maker and model are not included (D-U3-2).

**Pure report builder `Diag.report(facts, includeErrors)`** in a new page file (no DOM, testable in the harness). `Diag.scrub(text)` is applied to every text that did not come from the app's own fixed words.

## Redaction rules
| Data | In the report by default | With "Include error messages" | Never |
|---|---|---|---|
| App version, schema numbers, library state | yes | yes | |
| Android version, SDK, WebView version | yes | yes | |
| Device maker and model | | | yes, unless D-U3-2 |
| Counts (reels per status, titles, quotes, products, screenshots read, inbox) | numbers only | numbers only | |
| Sizes (U1) | rounded to MB | rounded to MB | |
| Choices in settings (GPU, answer length, style, nightly hour and battery, reels per night, look-ups on or off, Meta AI on or off, YouTube language) | yes | yes | |
| TMDB and OMDb keys | "set" or "not set" | the same | the value |
| Meta AI prompt, extra AI instructions | "default" or "changed" | the same | the text |
| AI model | catalog name, size, `verified`, backend | the same | the file name of an own model ("your own model file") |
| Last nightly run | time, and each log line only if it matches, **whole line anchored** (`^...$`, the only variable parts `\d+`), one of the run's fixed sentences (local.js:619-652), for example `^Reel notes: \d+ written, \d+ failed$`. Line 624 starts with a fixed sentence ("AI model not downloaded (") and then embeds `e.message`, so it never matches and becomes "AI model not downloaded (reason left out)". Every other line becomes "(other line)" | each other line after `scrub` | |
| Reel failures | count per **fixed category word**, oldest and newest date. The category comes from anchored patterns on the app's own sentences, never from the error text itself: `network` (`^No internet, or the site did not answer \(\w+\)$`, LocalBridge.java:938; `^(Instagram\|YouTube) answered \d+$`, LocalBridge.java:833, 922; `^(Instagram\|YouTube) sent a sign-in or consent page$`, :927); `slow down` (`^Instagram asked to slow down\.`, local.js:369); `model` (`^The on-phone AI's answer was not in the notes format\.`, local.js:515); `caption` (`^Instagram gave too little to work from`, local.js:556; `^This video has no captions`, `^YouTube did not give the spoken words`, local.js:342-344); `other` for everything else. A1's streak key (`String(e.message).split(":")[0]`, **A1** local.js:601) is raw error text (a message with no ":" is the whole message; a Java `e.getMessage()` can start with a path or a model file name) and is **never** used | each distinct `last_fail` / `error` after `scrub`, at most 10 | which reel it was |
| Nightly title check | the numbers and the time | the same | titles |
| Files kept for safety | count, kinds, total size | the same | (names hold only dates; left out anyway) |
| Reel links, codes, authors, captions, comments, transcripts, text on screen, notes, tags, topics, watchlist titles, quotes, products, screenshot text and file names, search words, Ask questions, web answers, paths | | | yes |
| Any identifier for the phone or install | | | yes (none is made) |

`Diag.scrub(s)`: replace URLs (`\bhttps?://\S+`, `\bwww\.\S+`) with `[link]`; `@handles` with `[name]`; e-mail addresses with `[email]`; runs of 6 or more digits with `[number]`; paths (`(/[\w.-]+){2,}`, and `content://` or `file://` addresses) with `[path]`; text in quotes (straight or curly) with `[text]`; Instagram-style codes (an 11-character token of letters, digits, `_`, `-` that contains both letters and digits) with `[code]`; then cut to 120 characters. The rule is deliberately crude: it removes too much rather than too little, but it has no rule for unquoted titles or names, so it does **not** make an error text safe; that is why error texts are only in the report with the switch.

## Failure modes
- A bridge call is missing (an older build, the harness): that line says "not available"; the report is still made.
- The library is locked or newer: today `render()` shows only the locked or newer screen for every route except `#/restore` (local.js:1727), so Diagnostics would not open exactly when it is most useful. U3 adds `#/diagnostics` to that exception and a "Diagnostics" link on both screens (D-U3-6); counts are then "not available" (the library was not read) and the state line says why. The page reads no library file, saves nothing, and uses `libraryState` (no side effect), so it cannot write over a locked library or swallow the one-time "recovered"/"started_new" notice.
- A huge library: counting statuses is one pass over `db.reels` (no JSON tree, no new read).
- The clipboard: on Android 12 and older another app in the foreground could read it (NEEDS VERIFICATION per version); the default report has nothing private. Android 13+ shows a clipboard preview.
- The user turns the switch on and shares: error texts may still hold something `scrub` missed. The switch's label says what it adds, and the full report is visible before Copy or Share.

## Tests
- **Phone harness `tests/test_diagnostics.py`** (fake RN): build a library where every text field (caption, transcript, notes, tags, author, url, code, comments, onscreen, watchlist titles, quotes, products, screenshot names, `localExtra`, `prompt`, `tmdbKey`, `omdbKey`, an own model file name in `modelInfo.file` and in `modelInfo.installed[]`, `libraryInfo.bad` and `libraryInfo.notice` in the fake, `error`, `last_fail`, `run.log[].text` and `run.note`, `lastNight.log` including a line 624 "AI model not downloaded (MARKER)", and a Java-style error "/data/user/0/app.reelshelf/files/models/MARKER.litertlm (No such file)" with no ":" before the path) holds a unique marker string; assert that **no marker appears** in the default report (failures appear only as the fixed category words), and that with the switch on only the scrubbed error texts appear (no URL, handle, code, long number or path).
- A visit to Diagnostics never calls `libraryInfo`: with a fake notice "recovered" pending, open Diagnostics, then the library and Screenshots: the notice is still shown.
- The page has no `<img>` element and no `https:` in its HTML.
- `Diag.scrub` table tests: each rule, and a mixed sentence.
- The report has every allowlisted line with the fake values; "not available" when a bridge method is missing; the locked and newer states.
- The page makes no `fetchPage`, `postJson`, `webSearch` or other network call (the fake RN records calls); the switch is off on every open.
- **JUnit** for `deviceInfo` with the parts that can run off a phone (the JSON shape).

## PR split
1. **U3-1** (publishing, left READY; stacked on the newest app branch; the A1 fields are used when present): `diag.js`, the route and screen, the Settings link, `RN.deviceInfo`, `RN.libraryState`, tests, CHANGELOG, TESTING rows, version bump. One Opus review with **privacy first**.

## Device checks (owner only)
- D1: open Diagnostics on the phone, Copy, paste into a note: the text matches the screen; no reel link, name or key in it.
- D2: with a nightly run that failed (for example the battery below the level), the last run and failures lines say what happened.
- D3: `deviceInfo` values match Android's settings (notifications, battery optimisation, alarms and reminders).
- D4: turn on airplane mode: the page and both buttons still work.

## Owner decisions (recommended default first)
- **D-U3-1** A "Diagnostics" link at the bottom of Settings. Alternative: hidden behind a long press on the version.
- **D-U3-2** No device maker or model. Alternative: a second switch "Include phone model".
- **D-U3-3** Error texts only with the switch, scrubbed, at most 10. Alternative: never include error texts.
- **D-U3-4** Copy and Share only, no file. Alternative: also "Save to Downloads" (leaves a file other apps can read).
- **D-U3-5** Use only what is already recorded, plus U4's numbers-only `night_trace` if U4-1 is built. Alternative: also keep the last 7 nightly run logs (needs a new field, R4 rules apply).
- **D-U3-6** Diagnostics opens from the locked and newer screens too (a router exception like `#/restore`). Alternative: only from Settings (then not while locked).

## Risks
- The riskiest assumption is that the fixed-word allowlist (anchored patterns, category words) is complete enough to be useful while letting no error text through; `scrub` is not trusted, so the default report has no error text at all, and the switch label says titles may remain.
- A later PR adds a field to `db` or `settings` and a later helper copies it into the report by hand. The marker test catches only the fields it knows; the review must check the table.
- Users may paste the report into a cloud AI. That is their choice; the default report is designed to be safe for it.

## Out of scope
Crash capture (`onRenderProcessGone`), logcat, any upload, analytics, an install ID, remote support.
