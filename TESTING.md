# Testing Reel Shelf

Two kinds of tests:

1. **Automatic tests** (no internet, no AI model needed): `uv run pytest` on a PC. 100+ tests, including a real
   browser at phone size, attack tests (see Security below) and the exact failures reported so far.
2. **Real-device tests** (this page): what you check on the phone with real internet, real Instagram data and the
   real AI model. Do them in order. Each case says what to do and what must happen.

Before you start: **Settings > Version** shows which version is running. Tap **Update now** first, so you test the
latest fixes. When something fails, send a screenshot of the screen **and** of **Settings > Self-check**.

---

## 0. Self-check (2 minutes, do this first)

| ID | Do | Expected |
|---|---|---|
| S1 | Settings > **Run self-check** | A list fills in one line at a time, then "N of 16 passed". |
| S2 | Read each FAIL line | Every FAIL says why (for example "Ollama: HTTP 500: model requires more system memory") and what to do. No line says only "Error". |
| S3 | Same from Termux: `reel-watcher check` | Same results as text, PASS/FAIL per line. |

Must pass on the phone: Library storage, Security of installed packages, Text reader, Video tools, at least one
**Web search** line, **Finds a new film by web search**, AniList, Wikidata, Instagram reachable.
May fail without breaking the app: AI model (phones are often too small), MyAnimeList, TVmaze, one of the search engines.

## 1. Install and update

| ID | Do | Expected |
|---|---|---|
| I1 | Fresh phone: install the APK, open it | "Step 1 of 2: Install Termux". If Termux came from the Play Store: a red warning. |
| I2 | Tap **Copy setup command and open Termux**, paste, Enter, go back to Reel Shelf | Progress screen "Step N of 7" with a moving bar and the current download line. |
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
| P1 | Identify > Screenshot > the Wikipedia page of **Scene (2026 film)** | "Match found": **Scene**, Movie, 2026, language Tamil. Found by: **Web search**. "What was tried" shows Read text ✓, Check names ✗ (not in the databases yet), Web search ✓. |
| P2 | An anime frame (any well-known anime) | The anime name with episode and time (trace.moe), or a guess marked "Check this". |
| P3 | A manga panel | The manga name (SauceNAO), or a guess marked "Check this". |
| P4 | A movie poster with the title written on it | The movie, found by on-screen text. |
| P5 | A WhatsApp chat or a payment receipt | "This does not look like a movie, show, anime or manga". |
| P6 | A plain photo (a wall, a meal) | "No match yet", "What was tried" open, **Try again** and **Type the name myself** both work. |
| P7 | P6, then Type the name myself > "Scene", type Movie > Save | Button shows "Looking it up...", then the title page of Scene opens. |
| P8 | Turn on airplane mode, identify a screenshot | No crash. "What was tried" shows each step with the network error. Turn internet back on, tap **Try again**: it now finds the name. |
| P9 | AI model failing (self-check says AI model FAIL) and repeat P1 | P1 still passes. "AI look" shows ✗ with the reason; the other steps still ran. |

## 4. Reels

| ID | Do | Expected |
|---|---|---|
| R1 | Identify > Reel link > paste one reel whose caption or comments name a movie or anime | Within a few minutes: the name, and where it was found (caption, comment, speech, on-screen text, web search). |
| R2 | Paste a link that is not Instagram (for example a YouTube link) | "Paste an Instagram reel or post link". Nothing is downloaded. |
| R3 | Open a collection > **Read this collection** | Jobs tab shows the job; items move from waiting to done; the collection fills with titles. |
| R4 | Pause and resume the job in Jobs | Stops after the current reel; continues when resumed. |
| R5 | Reel names a new or regional film the databases do not have | Found by **Web search** (shown under "Found by"). |
| R6 | AI model failing (P9 situation), read a reel | Still read from on-screen text, speech, caption and comments. |
| R7 | Many reels in a row | Some may show "Instagram is limiting downloads for now; it continues automatically"; they continue by themselves about an hour later. None shows a raw error. |
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

## 7. Security (what the attack tests prove, and what you can see)

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
