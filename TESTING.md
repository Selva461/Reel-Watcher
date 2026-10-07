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
