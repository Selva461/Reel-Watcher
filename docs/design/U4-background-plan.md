# U4: the nightly background run on a real phone: plan and measurements (design, not approved)

Base for every file:line below: `origin/stabilize/s4-4-files-set-aside` at **563f81f** (PR #70, not merged, 1.3.25 / 32; it contains Task 2b, PR #33, whose own head is `c511f47`). The default branch (1.3.11) has the nightly run without `NightGuard`. Planning only: no code was changed. **Nothing here was measured on a phone.** Every statement about Android behaviour that is not read from this repository is marked NEEDS VERIFICATION; the platform rules change per Android version and per maker.

## Problem
The nightly run is on by default and does real work: shared reels, notes with the on-phone AI, screenshots, online title checks (local.js:604-662). Whether it really starts, keeps network and CPU, finishes, and how much battery and heat it costs on a real phone is unknown (PROJECT_CONTINUATION.md:169: "Android 15 dataSync limits, Doze and battery managers ... never tested on a device"). U4 is a plan to find out, plus the few decisions that the results will force. It is not a rewrite.

## What the code does today (verified)
**Scheduling.** No WorkManager and no androidx dependency (build.gradle dependencies: LiteRT-LM, ML Kit, Vosk, JNA only). `NightRun.schedule` cancels and sets one `AlarmManager.RTC_WAKEUP` alarm at the chosen hour, minute 0, tomorrow if that is under a minute away; `setExactAndAllowWhileIdle` when exact alarms are allowed, else `setAndAllowWhileIdle` (NightRun.java:68-82). It is set again at app start (MainActivity.java:103), when the alarm fires (NightRun.java:103), at boot and after an update (NightRun.java:98-100; manifest receiver AndroidManifest.xml:82-89). Permissions: `USE_EXACT_ALARM`, `SCHEDULE_EXACT_ALARM` up to API 32, `RECEIVE_BOOT_COMPLETED`, `WAKE_LOCK`, `FOREGROUND_SERVICE_DATA_SYNC`, `POST_NOTIFICATIONS` (AndroidManifest.xml:3-13). `targetSdk 34`, `minSdk 26` (build.gradle:11-12). No receiver for time or time-zone changes.
**Start rules.** On the alarm: off, battery below the chosen level (default 40%, NightRun.java:58-60) or battery at 40 °C or more: skipped tonight (NightRun.java:104-107). No charger, Wi-Fi or idle rule (the comment says so, NightRun.java:106; the Settings text too, local.js:675).
**NightGuard (Task 2b).** `WorkService.startNight` asks `NightGuard.tryStart(visible, jobRunning, now)` (WorkService.java:48-58): skip when the app is on screen, when a job the user started runs, or when a claim younger than 4 h exists (NightGuard.java:24-32; NightRun.java:37). The claim is taken before the service starts, released when the service ends (WorkService.java:183) or when Android refuses the start (WorkService.java:55-57), and refreshed every minute while the run lives (NightRun.java:155). The service skips again if the app became visible after the alarm (WorkService.java:138-141). Opening the app during a run stops its current work and gives it 20 s to save (WorkService.java:41, 114-123); the page waits on a hand-over screen (local.js:1678-1703).
**Running.** A `dataSync` foreground service with a notification and Stop (WorkService.java:127-128, 148-174), a partial wake lock of at most 3 h (WorkService.java:29, 130-133), `START_NOT_STICKY` (WorkService.java:145). The page runs in a WebView that is never on screen (`NightRun.Headless`, NightRun.java:114-150) at `#/night`. Every 60 s it stops the run when the battery falls below the level or the battery reaches 42 °C (NightRun.java:152-163). The page processes at most `nightMax` reels (default 200, local.js:632) and stores `db.lastNight = {at, log}` (local.js:655).
**The separate nightly title check** (`NightlyCheck`, off by default): a periodic JobScheduler job, any network, device idle, persisted, 8-minute budget (NightlyCheck.java:22-42). The manifest comment says "Wi-Fi + charging + phone idle" (AndroidManifest.xml:77), which is **stale**: the code asks neither Wi-Fi nor charging. `AGENTS.md:68` ("nothing starts on its own besides the opt-in NightlyCheck") is stale too: the nightly run is on by default (NightRun.java:43-45). Both are mentioned, not changed here.

## What only a phone can tell (NEEDS VERIFICATION, all of it)
| Question | Why it matters | Expected (from Android docs, unverified) |
|---|---|---|
| Q1 Does the alarm fire within minutes of the hour in Doze, on battery, screen off? | everything | `setExactAndAllowWhileIdle` fires in Doze, at most about once per 9 minutes per app |
| Q2 May the service start from the alarm in the background (Android 12+ limits on starting foreground services)? | the run starts at all | an exact-alarm holder is exempt for a short window after the alarm |
| Q3 Has the headless run network in Doze (Instagram captions, title checks)? | half the work is online | a foreground service is usually allowed network; may differ per maker |
| Q4 Does the maker's battery manager (Samsung, Xiaomi, OnePlus...) kill or delay it? | many phones | often yes unless the app is exempted |
| Q5 After a reboot, is the alarm set again (first unlock, direct boot)? | runs after a restart | `BOOT_COMPLETED` arrives after the first unlock |
| Q6 Android 15+: dataSync time limits and the boot start rule | long runs | apply to apps that target 35; this app targets 34, so not yet |
| Q7 Battery used, temperature, time per reel with the AI on CPU and GPU | user trust | unknown |
| Q8 Does the WebView page keep running timers with no screen in Doze? | the run's own loop | unknown |
| Q9 Standby bucket (rare, restricted) effects on the alarm | rarely opened apps | restricted apps get fewer alarms |

## Options
1. **Keep the alarm plus foreground service, measure, then tune** (recommended). It is built, reviewed and has device checks E9-E11 waiting. Change only what the measurements show.
2. WorkManager with constraints (charging, unmetered, idle). Adds androidx; a long worker still needs the same foreground service; the start time becomes "some time tonight". Only worth it if Q1 or Q2 fail widely.
3. JobScheduler for everything (like `NightlyCheck`). Jobs get about 10 minutes (NightlyCheck.java:23); a night of AI notes is longer. Rejected for the main run.

## The change (option 1: a measurement build, then small fixes)
**Step 1, no behaviour change: record what happened.** A small additive record in prefs `night_trace`, the last 14 nights, each `{alarm_at, fired_at, verdict (START, SKIP_VISIBLE, SKIP_JOB, SKIP_DUPLICATE, LOW_BATTERY, HOT, OFF, REFUSED), started_at, ended_at, end (done, stopped, battery, heat, handover, killed), battery_start, battery_end, temp_max, charging, reels_done, reels_failed, network_ok}`. Numbers and words only: no reel, no text, no error message. Written by `NightRun.onReceive`, `WorkService` and `nightDone`. "killed" is inferred at the next start (started, never ended). Shown in U3 Diagnostics as a table, and in its report (it holds nothing private).
**Step 2, only after the owner's measurements:** the fixes the results call for, each a decision below (D-U4-2 to D-U4-6). Candidates: set the alarm again on `TIME_SET`/`TIMEZONE_CHANGED`; an optional "only while charging" rule; a button that opens Android's battery-optimisation page for Reel Shelf (no `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` permission); a line in Settings when exact alarms are not allowed (`nightRunInfo.exact`, LocalBridge.java:1616-1627, is already returned, but nothing shows it, local.js:665-676).

## Failure modes (of the plan)
- The trace itself must never block or crash the run: written with `apply()`, capped at 14 entries, a bad entry is dropped.
- Killed runs leave no end record: inferred at the next app start, never guessed as "done".
- The trace counts (`reels_done`) come from the page; the headless page can die before it reports: then they are "unknown".
- Measurement on one phone does not prove another maker's behaviour; results are recorded per phone.

## Tests (cloud, no phone)
- JUnit `NightTraceTest` (pure): add, cap at 14, every verdict, "killed" inferred from a start without an end, a damaged prefs value ignored.
- JUnit: `NightGuard` verdicts map to trace words (the existing `NightGuardTest` stays as it is).
- Phone harness: the U3 table shows the trace; the report contains only numbers and the fixed words.

## Measurement plan (the owner runs it; about 4 nights per phone)
Before: install the measurement build; Settings, Nightly run on, an hour 10 minutes from now for the first try; note the phone, Android version and maker skin. Optional with a computer: `adb shell dumpsys alarm | grep reelshelf` (the alarm is set), `adb shell dumpsys deviceidle` (Doze state).
| Night | Set-up | Answers |
|---|---|---|
| M1 | on charger, Wi-Fi, screen off, 50 reels waiting | Q1, Q2, Q7 (baseline), Q8 |
| M2 | on battery above the level, Wi-Fi, untouched for 1 h before (Doze) | Q1, Q3, Q7 |
| M3 | on battery, mobile data only, maker battery saver on | Q3, Q4 |
| M4 | restart the phone in the evening, unlock once, do not open the app | Q5 |
| M5 (optional, adb) | `adb shell dumpsys deviceidle force-idle` before the hour; `adb shell am set-standby-bucket app.reelshelf rare` | Q1, Q9 |
Each morning: open Diagnostics and copy the night's trace row; note the battery drop and anything odd. Repeat M2 with the AI model on GPU and on CPU for Q7. The existing device checks E9-E11 (TESTING.md:116-118) are run in the same week.

## PR split
1. **U4-1** (publishing, left READY; stacked on #70 or whatever holds Task 2b at the time): `NightTrace.java`, the hooks, `NightTraceTest`, the U3 table (or a plain list if U3 is not built), CHANGELOG, TESTING rows M1-M5. Opus review (it touches the nightly lifecycle).
2. **U4-2** after the measurements: only the fixes the owner chooses.
3. Separate small docs PR (owner says when, R1): fix the stale manifest comment and AGENTS.md:68.

## Device checks (owner only)
M1-M5 above, plus E9-E11. None has been run; the AI ran only computer tests.

## Owner decisions (recommended default first)
- **D-U4-1** Build the trace (step 1) before changing any rule. Alternative: change rules now from the Android docs alone.
- **D-U4-2** Keep "battery is the only rule" (no charger needed). Alternative: an option "only while charging", off by default; or charging required by default.
- **D-U4-3** Set the alarm again after a time or time-zone change. Alternative: leave it (the next app start fixes it).
- **D-U4-4** Offer a button to Android's battery-optimisation settings only when a trace shows a killed or missing night. Alternative: always show it; or never.
- **D-U4-5** Show "Exact alarms are off: the run may start late" in Settings when `exact` is false. Alternative: nothing.
- **D-U4-6** Stay on `targetSdk 34` until the Android 15 rules (Q6) are measured. Alternative: move to 35 now and accept the dataSync limits.

## Risks
- The riskiest assumption is that a foreground service started from an exact alarm has network and CPU through the night on the owner's phone (Q2, Q3, Q4). If not, much of the design of the nightly run must change (option 2).
- `USE_EXACT_ALARM` is meant for alarm and calendar apps in Google Play's policy (NEEDS VERIFICATION); the app is installed from GitHub releases, so this matters only if it ever goes to Play.
- Heat and battery wear from the AI at night are user-trust risks; the 40 °C / 42 °C guards are not measured.

## Out of scope
Moving to WorkManager, raising `targetSdk`, a new permission, any automatic deletion, changing what the run does.
