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
| E22 | Install this version over the previous one on a phone with a real library (no uninstall). Open it, note the counts on Library, Inbox and the watchlist, open a few reels and a title, share one reel from Instagram, then open Reel Shelf again. Optional, with a debug build and a computer (as E7): `adb shell run-as app.reelshelf grep -o '"schema_version":[0-9]*' files/reels.json` after the share was filed | The counts are the ones you had, every reel and note opens, the shared reel is filed. No "Library not opened" screen and no message about a newer Reel Shelf. The optional command prints `"schema_version":1` once something has been saved. |
| E23 | A newer library (needs a debug build and a computer, as E7; do it after E22, so the file has its number, and on a test install or a copy of your own library; never work on the only copy). Close Reel Shelf completely. Copy the files out first and keep them: `adb exec-out run-as app.reelshelf cat files/reels.json > reels.json.mine` (the same for `files/reels.json.bak`), and write down `sha256sum reels.json.mine`. Make the newer one on the computer: `sed 's/"schema_version":1/"schema_version":99/' reels.json.mine > reels.json.newer`, and check that `grep -c '"schema_version":99' reels.json.newer` prints 1. Put it in place without relying on piped input (some adb versions drop it and leave an empty file): `adb push reels.json.newer /data/local/tmp/` then `adb shell run-as app.reelshelf cp /data/local/tmp/reels.json.newer files/reels.json`. Check it arrived: `adb shell run-as app.reelshelf sha256sum files/reels.json` must equal `sha256sum reels.json.newer`. If it differs (or the file is empty), do not open the app: put `reels.json.mine` back the same way, check its checksum equals the one you wrote down, and try again. Only when they match, write down the output of `adb shell run-as app.reelshelf sh -c 'sha256sum files/reels.json*; ls files'`. Open Reel Shelf. Tap **Save a copy to Downloads**. Share a reel from Instagram, then open Reel Shelf again. Close it completely and run the `sha256sum` and `ls` command again | **Library not opened** says "This library was saved by a newer Reel Shelf. This version (1.3.15) cannot open it safely and has not changed it. Install the newest Reel Shelf." The only button is **Save a copy to Downloads** (no Start a new library, no Try again); it puts `reels-unreadable-<time>.txt` in Downloads/ReelShelf, and that file is the whole newer library. Every other screen is the same message. The shared reel is not filed (it waits). The output is exactly what you wrote down after placing the file: the same checksums for `reels.json` and `reels.json.bak` (the old copy was not put back over the newer one), no `reels.json.bad-<time>`, no new file. At the end put your copy back (`reels.json.mine` the same way, and check its checksum equals the one you wrote down) and open Reel Shelf: your library opens and the reel you shared is filed. |
| E24 | The screenshot list the same way (debug build and a computer; never work on the only copy). Close Reel Shelf completely. Copy it out first and keep it: `adb exec-out run-as app.reelshelf cat files/shots.json > shots.json.mine`, and write down `sha256sum shots.json.mine`. Make the newer one on the computer: `sed 's/^{"v":1,/{"v":99,/' shots.json.mine > shots.json.newer`, and check that `grep -c '^{"v":99,' shots.json.newer` prints 1. Put it in place: `adb push shots.json.newer /data/local/tmp/` then `adb shell run-as app.reelshelf cp /data/local/tmp/shots.json.newer files/shots.json`. Check it arrived: `adb shell run-as app.reelshelf sha256sum files/shots.json` must equal `sha256sum shots.json.newer` (if not, do not open the app: put `shots.json.mine` back the same way and try again). Then write down `adb shell run-as app.reelshelf sh -c 'sha256sum files/shots.json*; ls files'`. Open Reel Shelf, open Screenshots, tap **Read new screenshots now** if it is there, leave and open Screenshots again. Close Reel Shelf completely and run the `sha256sum` and `ls` command again | The library opens normally. Screenshots says "The screenshot list is not open. It was saved by a newer Reel Shelf. This version cannot open it safely and has not changed it, so nothing is read or saved." No pictures are read. `shots.json` has the same checksum as the file you placed (the newer one, not your original) and there is no `shots.json.bad-<time>`; the `ls` output is the same as before. At the end put `shots.json.mine` back the same way (its checksum must equal the one you wrote down) and Screenshots works as before. |

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
