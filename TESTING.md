# Testing Reel Shelf

Two kinds of tests:

1. **Automatic tests** (no internet, no AI model needed): `uv run pytest` on a PC. 100+ tests, including a real
   browser at phone size, attack tests (see Security below) and the exact failures reported so far.
2. **Real-device tests** (this page): what you check on the phone with real internet, real Instagram data and the
   real AI model. Do them in order. Each case says what to do and what must happen.

Before you start: **Settings > Version** shows which version is running. Tap **Update now** first, so you test the
latest fixes. When something fails, tap **Copy debug report** (on the item, or in Settings) and paste it in your
message: it has every step, what each service answered and why the app decided what it did.

## How the app decides (what "Verified" means)

- **Verified**: two independent sources agree on the same work. For example the name is on the screen (or said in the
  reel, or in the caption or a comment) AND a database or web pages identify exactly one work by that name; or two
  picture searches match the same work; or a picture match agrees with the name on screen.
- **Possible match**: only one source, a name that is only close, or several works with the same name. The screen
  says why ("Why: ..."), lists the evidence, and one tap confirms or picks another.
- **Not found**: nothing reliable. Offers **Search with Google Lens**, **Type the name myself** and **Try again**.
- AI guesses are **off** by default. When turned on (Settings), they are shown as possible matches and never count as proof.
- Every item ends in one of: Verified, Possible match, Not found, Not a movie or show, Could not finish (with the
  reason and Try again), or Paused (a free limit; it continues by itself).

---

## 0. Self-check (2 minutes, do this first)

| ID | Do | Expected |
|---|---|---|
| S1 | Settings > **Run self-check** | A list fills in one line at a time, then "N of 16 passed". |
| S2 | Read each FAIL line | Every FAIL says why (for example "Ollama: HTTP 500: model requires more system memory") and what to do. No line says only "Error". |
| S3 | Same from Termux: `reel-watcher check` | Same results as text, PASS/FAIL per line. |

Must pass on the phone: Library storage, Security of installed packages, Text reader, Video tools, AI model (says
"off: not needed" unless you turned AI guesses on), at least one **Web search** line, **Finds a new film by web
search**, AniList, Wikidata, Instagram reachable.
May fail without breaking the app: MyAnimeList, TVmaze, one of the search engines, the anime scene search budget.

## 1. Install and update

| ID | Do | Expected |
|---|---|---|
| I1 | Fresh phone: install the APK, open it | "Step 1 of 2: Install Termux". If Termux came from the Play Store: a red warning. |
| I2 | Tap **Copy setup command and open Termux**, paste, Enter, go back to Reel Shelf | Progress screen "Step N of 7" with a moving bar and the current download line. About 15 minutes and 1 GB (the 3 GB AI model is skipped). |
| I3 | Wait for the end | Reel Shelf opens by itself (no extra taps). |
| I4 | Close Reel Shelf, open it again | It opens straight into the app. If Android refuses to let it start Termux, it opens Termux, which starts Reel Shelf and comes back. |
| I5 | Settings > **Update now** | "Already up to date", or "Restarting..." then the page reloads showing the new version. |
| I6 | Settings > Version > Recent problems | Empty, or plain sentences (for example an outdated package with the command to fix it). |

## 2. Import your saved reels

| ID | Do | Expected |
|---|---|---|
| M1 | Import > choose the Instagram **ZIP** | "Found N collections" with the right names and counts. |
| M2 | Import > choose **saved_collections.json** and **saved_posts.json** together from Google Drive | Same collections as M1, plus "Saved (no collection)" for reels in no collection. |
| M3 | Pick the two files one after the other | Same result as M2. A reel in a collection is not also listed under "Saved (no collection)". |
| M4 | Also pick **saved_music.json** | "Skipped: saved_music.json: ... not one of the files Reel Shelf needs". The other files still import. |
| M5 | If M2 says "No saved posts found" | The message ends with "The file looks like this (field names only ...)". Send that screenshot: it contains no personal data and is enough to support the layout. |
| M6 | Pick a photo instead of an export | A clear message, no crash. |

## 3. Screenshots

| ID | Do | Expected |
|---|---|---|
| P1 | Identify > Screenshot > the Wikipedia page of **Scene (2026 film)** | **Verified**: Scene, 2026. Why: "Named in the screenshot and identified by Wikipedia" (or IMDb). Evidence: on screen + web search. What was tried: Read text ✓, Check names – (not in the databases yet), Web search ✓. |
| P2 | A poster or title card with a name only one work has (for example "VINLAND SAGA") | **Verified**: on screen + database. With a name several works share (for example "PARASITE", more than one film), or with the year on screen it can decide: Verified; without it: **Possible match** listing the works. |
| P3 | A frame from a well-known anime, no title visible | **Possible match** with episode and time (picture match only). Tap the right one to confirm. With the title visible on screen: **Verified**. |
| P4 | A manga panel | **Possible match** with the chapter (SauceNAO), or Not found. |
| P5 | A screenshot whose title has twins (for example only the word "MONSTER") | **Possible match**. Why: "several works have this name"; the other works are offered as chips. |
| P6 | A WhatsApp chat or a payment receipt | **Not a movie or show**. |
| P7 | A plain photo (a wall, a meal) | **Not found** with: Search with Google Lens, Type the name myself, Try again, Copy debug report. "What was tried" is open. |
| P8 | P7 > **Search with Google Lens** | The Google app opens Lens with the picture (a copy is saved in Pictures/ReelShelf). Without the Google app: the share menu opens. |
| P9 | P7 > Type the name myself > "Scene", type Movie > Save | Button shows "Looking it up...", then the title page of Scene opens. The item shows **Verified** (chosen by you). |
| P10 | Airplane mode on, identify a screenshot | Ends (never stuck): steps show ✗ with the network error. Internet back on, **Try again**: it now finds the name. |
| P11 | Settings > AI guesses on, identify P7 again | An "AI guesses" step; any guess is a **Possible match**, never Verified on its own. |

## 4. Reels

| ID | Do | Expected |
|---|---|---|
| R1 | Identify > Reel link > paste one reel whose caption or comments name a movie or anime | Within a few minutes: **Verified** "named in the reel and identified by ..." (caption, comment, speech or on-screen text, plus a database or web pages). |
| R2 | Paste a link that is not Instagram (for example a YouTube link) | "Paste an Instagram reel or post link". Nothing is downloaded. |
| R3 | Open a collection > **Read this collection** | Jobs tab shows the job; items move from waiting to done; the collection fills with titles. |
| R4 | Pause and resume the job in Jobs | Stops after the current reel; continues when resumed. |
| R5 | Reel names a new or regional film the databases do not have | **Verified** through web search (the evidence lists the web pages). |
| R6 | AI guesses off (default), read a reel | Read from on-screen text, speech, caption and comments; the AI model is never started. |
| R7 | Many reels in a row | Some may show "Instagram is limiting downloads for now; it continues automatically"; they continue by themselves about an hour later. None shows a raw error. |
| R9 | A post made of pictures (one picture or a carousel, for example a "Top 10 series" list with episode ratings) | Not "failed": Download "N pictures (no video)", the text of each picture is read; titles written on the pictures ("10. Friends" above "Season 1") end **Verified**. |
| R10 | A quote picture in a Motivation collection | The quote text from the picture is saved as a quote. |
| R8 | A "Motivation" collection | Quotes with a GIF that has captions in time with the voice. Save and Share work. |

## 5. Library

| ID | Do | Expected |
|---|---|---|
| L1 | Search a title, filter by language and type | Results update as you type; counts are right. |
| L2 | Open a title | Story, year, type, language, where to watch (with a free TMDB key: services in your country). |
| L3 | Mark Watched / To watch / Favorite | Stays after closing and reopening the app. |
| L4 | "Check this" list: pick the right alternative | The title switches; it disappears from the Check list. |
| L5 | Export CSV, open it in Google Sheets | One row per title; nothing in it runs as a formula. |

## 6. Errors and recovery

| ID | Do | Expected |
|---|---|---|
| E1 | In Termux: `reel-shelf-stop`, then use the app | "Reel Shelf is not running. On this phone: open Termux (it starts Reel Shelf), then come back." |
| E2 | Open Termux | Reel Shelf starts and the app comes back by itself. |
| E3 | Settings > Online lookups off, identify a screenshot | "Check names: online lookups are off (Settings)". No crash. |
| E4 | Restart the phone in the middle of reading a collection | After starting again, the job continues; nothing is lost or stuck on "working". |
| E5 | Any item that keeps failing (for example the phone kills the app on the same reel) | After 4 tries: **Could not finish** "Stopped after 4 tries. Last problem: ...", with Try again. |
| E6 | A reel Instagram refuses again and again | Paused and retried about every hour; after 6 refusals: Could not finish, "Instagram refused this reel 6 times". |
| E7 | Damaged library (needs a debug build and a computer: `adb shell run-as app.reelshelf`, then cut `files/reels.json` short with `head -c 2000 reels.json > t && mv t reels.json` after copying it away). Open the app | With a good `reels.json.bak`: your reels are back and a message says the damaged file was kept as `reels.json.bad-<time>`. Without one: **Library not opened**, nothing saved. **Save the unreadable file to Downloads** puts `reels-unreadable-<time>.txt` in Downloads/ReelShelf (open it in the Files app). **Start a new library** asks first, then opens an empty shelf; the old file is still in the app folder as `reels.json.bad-<time>`. Share a reel while locked: after Start a new library it appears. |
| E8 | Night run meets the open app (device only): set the nightly hour (Settings, Nightly run) to the next full hour, leave the phone idle until the notification appears, open Reel Shelf while it runs, share a reel from Instagram, then wait for the run to end and look at the shelf | The night's notes are all there, the reel you shared is there once, and the Settings you changed are unchanged. If a message says the library was "updated elsewhere", repeat the one change you made; nothing else is missing. |
| E12 | A big library on the phone (1,000 or more reels: import an Instagram export, or use a copy of your own library). Open any reel before ever opening Ask, then open **Ask**, wait, open a topic, then a reel from it | The reel opens at once and has no "Topic" link yet. Ask says "Working out topics...", then the topics list appears; while it works, the page still scrolls and taps answer (try the tabs). Note how long it took. Opening the topic is at once, it lists as many reels as the number in the reel's "Topic: ... (N)" link and includes that reel, and the reel in it now has "Topic: ...". Open a topic, then go back before it appears: nothing from it shows on the next screen. |
| E13 | Shared pictures and videos, device only. Share ONE small picture from the Gallery to Reel Shelf | A small card "Saving your pictures" shows for a moment, then the message "1 picture saved ...". The picture is read under Screenshots, Read my screenshots. The original is still in the Gallery, same size and date. |
| E14 | Share ONE large picture (20-30 MB, for example a big PNG) | The card shows "x MB of y MB" moving; the phone does not stall (the Stop button answers at once). It is saved. A picture over 30 MB is not saved: "too big (over 30 MB)", no Try again. |
| E15 | Share ONE video from the Gallery (100-400 MB) | The card shows the MB moving and Stop works. Saved; Start reads it as a reel. The original video is unchanged. A video over 500 MB: "too big (over 500 MB)", nothing saved. |
| E16 | Share SEVERAL files together (20 pictures; then 3 videos). Then share exactly the same ones again | "Saving picture n of 20", all saved, "20 pictures saved". The second time: "already in Reel Shelf (shared before)", nothing is doubled (no second reel for a video, no second copy in the app). |
| E17 | Start sharing a big video, press Home (or Back) after a few seconds. Then, with a debug build and a computer: `adb shell run-as app.reelshelf ls -l files/video-inbox files/share-staging`. Repeat, and this time force-stop the app (Settings, Apps) in the middle | A message says it stopped; nothing half-written is in `video-inbox` (only complete files, if any were saved earlier), and no reel appears for it after Start. After a force-stop a `.part` file may remain in `share-staging` until the next share removes it, but it is never listed as a video. Sharing the video again saves it completely. |
| E18 | Fill the phone's storage until under 100 MB is free, then share a picture | "not enough storage space on the phone", with Try again. After you free space, Try again saves it. Nothing is doubled, and the library still saves. |
| E19 | While a big video copies: pull down the notification shade, rotate the phone, switch dark mode on or off. Then start another big video and leave the share screen (Home, or another app) | The phone stays responsive the whole time (scroll, tap, the Stop button answers). Pulling the shade, rotating and switching dark mode do not stop the copy. Leaving the share screen stops it: a message says so, the card is gone when you come back, nothing half-written is left; sharing again starts it again. |
| E20 | A big library on the phone (1,000 or more reels; run this with E12 on the same library): type a few words in the Library search box and in **Ask**, then open ten reels one after another, then edit one reel's notes and open another reel | Each key press in the search box shows its results without a pause you notice, **Ask** answers at once, and each reel opens at once with its "Related reels". Right after you changed a reel the next search or reel may take a moment longer (once), then it is quick again. Results look right (the reels you expect, the lines that hold your words). Note the time the first search after starting the app takes: it reads the whole library and is not made faster by this change. |
| E21 | A big watchlist on the phone (1,000 or more titles: a copy of your own library). Add ten titles one after another (Library, the filter button, **+ Title**; or Process a folder of screenshots), among them one you already have under another spelling ("The Dune" for "Dune") and one with the same name as a title you have but another year, then open **Check titles now** and tap **Process** | Each add is at once, with no pause you notice. The spelling you already have is merged into the existing title (its sources grow, no second row); the other year is still its own row. After Process the official names replace the ones read from the screenshots, and a title that now has the same name as another is folded into it, as before. Note the time the first add after starting the app takes: it prepares the lookup for your whole list once (a fraction of a second even with 5,000 titles), and is not made faster. |

## 7. Debugging

| ID | Do | Expected |
|---|---|---|
| D1 | On any item: **Copy debug report**, paste it in a note | Version, settings, the text read, each step with OK/ERR, the web queries and answers, picture-search answers, and for each candidate: Verified/Possible with every piece of evidence and why it counted or not. |
| D2 | Settings > **Copy debug report** | Version, counts per status, jobs, recent problems with their failed steps, the last self-check, recent errors. No pictures, no file contents, no folder paths. |
| D3 | In Termux: `tail ~/ReelShelf/logs/events.jsonl` | One line per event (start, each step, end, errors with where they happened). |

## 8. Security (what the attack tests prove, and what you can see)

Automatic tests try these attacks on every run; they must all be refused:

- a web site in the phone's browser reading or changing your library (DNS rebinding, cross-site requests);
- names, captions, comments or web results containing code (it is always shown as text);
- reading folders outside your storage, or files outside the app's media folder;
- links to other sites disguised as Instagram links; huge "zip bomb" exports; spreadsheet formulas in exports;
- bad or absurd input on every API call (always a readable message, never a crash).

What you can check yourself:

| ID | Do | Expected |
|---|---|---|
| X1 | PC: `reel-watcher app --lan`, open the address on the phone | Works. The access code disappears from the address bar after the first load. |
| X2 | Phone browser: open the PC address without the `?t=` code | "Open the address shown on your PC (it contains the access code)." |
| X3 | Settings > Version > Recent problems | Warns if an installed package has known security problems, with the command to update it. |

Dependencies are scanned for known vulnerabilities on every push and weekly (GitHub Actions, `pip-audit`), and
Dependabot proposes updates. GitHub Actions are pinned to exact commits.

## 9. Evaluating the notes on a phone (A3-4)

This checks, on a real phone, whether the on-phone AI writes notes in the right format. Twelve made-up reels (EVAL001 to EVAL012, no real reel data) go onto the phone as a backup, the phone writes notes for them, and the computer judges each answer. Nothing is graded for truth: only the shape of the notes. It is a procedure, not a row in the tables above.

**Before you start**
- Reel Shelf on the phone must have **Restore from a backup** (S4-3, pull request #67). It was not merged when this was written: without it the phone cannot read the file. Check that Settings has a **Backup and restore** section with both **Back up now** and **Restore from a backup**.
- The on-phone AI model must be downloaded and chosen in Settings. Without a ready model there is nothing to Start for these reels (they are read already, so there are not even quick notes to write): the Inbox tile says plain **Start** with no number, its screen says "Nothing waiting", and `check` would find nothing to judge.
- On the computer: this repository, `uv sync`, and Chromium for Playwright (`uv run playwright install chromium`, once). The computer sends nothing anywhere.
- **Restoring replaces the library on the phone.** The app keeps the old one on the phone, set aside as `reels.json.before-restore-<time>` and never deleted, and the box **Save a backup of the current library first** is ticked by default: leave it ticked. Best is a spare phone, or a second Android user on your phone (the app and the AI model must be installed for that user). On your own phone with your real reels, tap **Back up now** first and copy that ZIP to the computer. To go back afterwards, restore that ZIP.

**Steps**
1. On the computer, in the repository folder: `uv run python tests/notes_eval.py make-backup --out eval.zip`. The same file comes out every time. It prints a few lines; the last two are about the extra instruction (step 4).
2. Copy `eval.zip` to the phone (Files, Drive, or `adb push eval.zip /sdcard/Download/`).
3. On the phone: Settings > Backup and restore > **Restore from a backup** > **Choose a backup file** > `eval.zip`. The next screen asks "Replace your library?" and shows 12 reels. Keep the box ticked, tap **Restore this backup**. The box makes a backup of your current library first: it is a file `ReelShelf-backup-<date>-<time>.zip` in Downloads/ReelShelf, so note its time (it is the one that brings your own library back). The library now holds the twelve made-up reels, with no notes.
4. Optional: two of the reels (EVAL004 and EVAL011) are meant to be written with an extra instruction of 2,000 characters. That is a phone setting, not part of a backup, and there is one for all reels. To use one, paste its text from `localExtra` in `tests/fixtures/notes_eval/reels.json` into Settings > **Extra instructions for the on-phone AI**. Leave the field empty to skip it (and empty it again afterwards).
5. Inbox tab > **Start 11** (the tile shows the number; EVAL012 is only a link, so Start skips it). Leave the phone on the charger with the app open and wait until the run is done: Gemma takes about a minute per reel (the app's own note on the model). Do not tap Stop.
6. Settings > Backup and restore > **Back up now**. It says where the file is saved (Downloads/ReelShelf/ReelShelf-backup-<date>-<time>.zip). It is the newest file in that folder, and it has the same kind of name as the one step 3 made, so check the time.
7. Copy that newest ZIP (not the one from step 3) to the computer and run: `uv run python tests/notes_eval.py check ReelShelf-backup-<date>-<time>.zip`

**What `check` prints.** One block per reel. The ZIP is only read, never unpacked, and a file that is not a Reel Shelf backup is refused (unlike the app, it does not refuse a backup from a newer Reel Shelf layout: it judges it).
- **PASS**: the stored answer passes all six rules. **FAIL** names the rules it broke: `parses` (not in the notes format at all), `sections` (TOPIC, a point, TAKEAWAY or a tag missing), `complete` (does not end with TAGS: usually cut off by the answer length setting), `order` (sections out of order or written twice), `no_echo` (it repeated the instructions instead of filling them in), `limits` (topic over 200 characters, 1 to 40 points, 1 to 12 tags).
- **no answer text**: the app does not keep the text of an answer that failed, only the reason, so there is no verdict. The block shows the status, who wrote the notes, the number of tries (newer versions) and the reason, for example "The AI model failed: ..." or "The on-phone AI's answer was not in the notes format". A reel that failed on the phone counts as a failure in the result. EVAL012 is expected to have no answer text (status new).
- The last line is the result. Exit code **0**: every stored answer passes and no reel failed. **1**: an answer broke a rule, a reel failed, or no reel had an answer to judge. **2**: the file is not a usable backup. **3**: Chromium could not be started, nothing was judged.

**What this does not evaluate.** Gemma's picture and sound path: the made-up reels have no videos, so only the text prompt is tested. It does not measure tokens or speed, and it does not judge whether the notes are true. Keep the ZIPs of each run: a run before the prompt budget (A3-2) is the baseline for a run after it.

**Afterwards.** Restoring leaves your settings, API keys and AI models alone. If Start found reel videos saved on the phone, they were read too (codes starting with `v`) and are in the ZIP from step 6, so do not pass that ZIP around. To get your own library back, use **Restore from a backup** with the ZIP you made first.
