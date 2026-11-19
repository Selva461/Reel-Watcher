# Reel Shelf for Android: changes

Every change raises `versionCode` (+1) and `versionName` in `android/app-shell/app/build.gradle` and adds a
section here; the APK workflow publishes release `v<versionName>` with this section as its notes, and points
`apk-latest` at it. Builds signed with the stable key (GitHub secrets `ANDROID_KEYSTORE_BASE64` and
`ANDROID_KEYSTORE_PASSWORD`) install as updates over the previous version.

## 1.3.27
- A long question to your library no longer overflows the on-phone AI. "Answer with phone AI" sent your question with
  your 5 best-matching notes (4 with "Look it up online", plus the web results), each note whole, however long.
  Notes can be long, so that could be several times what a small model can read (its "window", which holds the
  prompt and the answer together). Then the AI failed or answered from a prompt it had silently cut. The app now
  works out how much the model can take, the same way it does for writing notes (the window, less the answer length
  you chose, the model's own instructions and some room for the chat format), and fills the prompt best match first.
- A question whose notes already fit gets exactly the same prompt as before. When they do not: the instructions and
  your question stay, and the notes go in whole, in the order of the match, as many as fit. A note that does not fit is
  left out completely (never cut in the middle), and so are the ones after it, so [1], [2] in the answer are still the
  notes with those numbers on the screen. With "Look it up online", the web results come after the notes, in what
  is left, each whole or left out.
- Under the answer, a line says plainly what was left out, for example "2 of 5 notes did not fit and were left out
  (the best matches go in first)." Nothing about it is saved in your library.
- The budget never stops an Ask. If not even your best note fits whole (with "Look it up online": no note and no web
  result fits), or your question alone takes the whole window, everything is sent in full, exactly as before this
  version, and a line says so: "Your notes are longer than the phone AI's assumed window, so they were sent in full as
  before. If the answer looks cut off or wrong, choose Answer length "Short" or use "Ask any AI with these notes"."
  (For a long question the line says "Your question ..." and suggests shortening it; for web results alone it says
  "The web results ...".) This matters most for notes in Cyrillic, Hindi, Japanese and other scripts: the size
  estimate counts 2 tokens for each such character, so an ordinary note of about 1,900 characters is judged too long
  for the 4,096-token window although a real model may well read it. It is sent as before, so it still answers. The
  question is cut at a word with "[shortened]" only when something still fits beside it (for example a small web
  result), and then the line says "Your question was long and was shortened."
- Not changed: "Ask any AI with these notes" still copies everything (it goes to a chat app of your own, not to
  the phone's model), the Meta AI prompt, the prompt for writing notes (1.3.26), the models and the permissions.
  The window is still a cautious 4,096 tokens for each model, and a model you pick by hand gets the smallest window.

## 1.3.26
- Long reels no longer overflow the on-phone AI. The prompt sent to the AI used to be cut by fixed limits that did not
  look at the model's memory (its "window", which holds the prompt and the answer together). A reel with a lot of
  text, a long transcript above all, could send far more than a small model can read, and the reel failed. The app now
  works out how much the model can take (its window, less the answer length you chose and some room for the chat
  format) and fills the prompt in a fixed order: the first lines, the title, the format and your "Extra instructions",
  then what you typed, the transcript, the start of the caption, the text on screen, the rest of the caption and
  the comments last. A text that does not fit is cut at a word and ends with "[shortened]".
- A reel whose text already fits gets exactly the same prompt as before. When something was cut, the run log says
  "(prompt shortened to fit the model)" after that reel (nothing new is saved on the reel). If your own "Extra
  instructions" had to be shortened, it says so too.
- A long transcript with no full stops or line breaks (a speech result, or a library imported from elsewhere) used to
  vanish from the prompt completely above 7,000 characters, so the AI wrote notes without what was said. Now its start
  is used.
- The size of each model's window is a cautious 4,096 tokens for now (only Qwen's file name says so). A longer
  window is not used until a phone confirms it. Prompts that come with the reel's pictures and sound are not shortened
  yet (their size is not known). Nothing about the notes, the models or the permissions changes.
- For checking later: the app asks the engine how many tokens the last prompt and answer took, and gives that number
  to the page (nothing stores or shows it yet).

## 1.3.11
- A reel's "Topic: ..." link now always opens the group it counted. In a library of more than 500 reels, one subject
  could be cut into a big group and a small piece with the same words, and the link of a reel in the small piece
  opened the big group (which did not hold that reel). Each group now has its own address. Smaller libraries and the
  groups themselves are unchanged.

## 1.3.10
- Reels open at once in a big library. Opening a reel used to work out the topics of your whole library first (about 2
  seconds with 1,000 reels, minutes with thousands). Now it does not. A reel's "Topic: ..." link shows once the topics
  are known, which is when you have opened **Ask** (and until a reel changes).
- The topics on **Ask** and on a topic page are worked out a few milliseconds at a time, so the app stays usable while
  they appear ("Working out topics..."). Leaving the screen stops the work; a changed reel starts it again.
- In a library of more than 500 reels, each reel is grouped by its 40 most telling words, which makes the grouping
  several times faster (the groups stay just as pure, and most reels stay with the same others). A library of up to 500
  reels is grouped exactly as before.

## 1.3.8
- Two screens can no longer overwrite each other. If the app and the nightly run both work on your library, a save made
  from an out-of-date copy is refused instead of replacing newer data: the screen reads the library, screenshots and
  settings again and says so ("updated elsewhere"). Only the one change that was not saved yet needs repeating.
- Reels you share are removed from the waiting list only after they are saved. If a save fails or is refused, they
  stay listed and are filed at the next opening (or at once, from the fresh copy).
- Changing one setting no longer reverts others changed elsewhere (for example a TMDB key typed while the nightly run
  is checking titles): only the keys you changed are saved, and settings are read again when you come back to the app.

## 1.3.7
- Your library is safer. If the library file cannot be read, Reel Shelf no longer replaces it with an empty one. It
  restores the last good copy when there is one (the damaged file is kept under a new name). Otherwise it stops, shows
  a recovery screen, and saves nothing until you choose: Try again, Save the unreadable file to Downloads, or Start a
  new library (the unreadable file is set aside, never deleted). Reels shared meanwhile wait safely.
- Each save keeps the previous version as a backup. The screenshot list is protected the same way; if it cannot be read
  it is set aside and read again from your pictures. "Delete all reels and notes" also removes the backup.
- Reels shared while the app was closed are filed in one save instead of one per reel.

## 1.3.6
- Products: a new Products chip in Library. Screenshots of a label ("Clinic Plus / Strong & Long Shampoo") or a store
  page (Amazon, Flipkart, Nykaa...) add the product, with the store link and price when the screenshot shows them.
  Reels add the products their notes name, with a store link from the caption. Process looks each one up in Open
  Beauty Facts, Open Food Facts and Open Products Facts (free, no key, only the name is sent): "Confirmed" only when
  the brand and name there match the label; then "Details" opens its page (size, picture). "Find in stores" opens a
  shopping search in your browser. A product with no readable name is not guessed.
- Recipes: notes of cooking reels get Ingredients (with amounts only when the reel says them) and Steps. Like points,
  any ingredient or step the reel's own words do not back up is left out.

## 1.3.5
- Two sources for everything: a title is verified only when two independent services agree on its name, year and
  kind (Wikipedia and Wikidata count as one). Titles verified by a single source before are checked again. Without a
  TMDB key, movies and series have only Wikidata, so they stay "not found online yet".
- About 10 titles are checked at once; each service keeps its own pace, so none of them blocks the app. Each name is
  looked up once even when many screenshots have it. A check cut off by an app update carries on when the app opens.
- Seasons are checked with a second source (Wikidata's number of seasons, or AniList / MyAnimeList's episodes) and the
  title page says so ("From TMDB, checked with Wikidata"), says where they differ, or says "(one source)".
- Reel notes: points the phone AI writes that nothing in the reel backs up (caption, text on screen, speech,
  comments) are left out, and the note says how many.
- Web answers: a fact that only one web page gives is marked "(one source)".
- Quotes from screenshots are looked up on Wikiquote during Process (only their first words are sent): "Confirmed"
  when the screenshot's title and Wikiquote agree, "Wikiquote: <page>" when only Wikiquote has it, or "Not found
  online".
- Whole reels: pick a folder with downloaded reels or screen recordings (Inbox, Videos), or share videos to Reel
  Shelf. Start reads each one whole (frames, text on screen, speech) and replaces the caption-only note of the same
  creator's reel.
- Creators read as "@Media" from the Instagram export are fixed: export labels are not usernames.
- Background jobs no longer need Wi-Fi or the charger; mobile data is fine. The only rule is the battery: the
  nightly run and the nightly check stop below 40% (adjustable). They still pause when the phone is hot.

## 1.3.4
- Nothing to check by hand anywhere: the "It is right" and "Not a real title" buttons are gone from the title page.
  When no database matches a title closely, the phone AI (if downloaded) reads the closest matches and a web search
  for the name (only the name is sent) and picks one, or none. Titles still not found keep their name, show "Not
  found online yet" and are tried again later by themselves.
- Comment text is no longer taken for titles ("View 4 replies", "12 likes Reply", usernames like ezequiel_266,
  "Liked by..."), and such entries already saved are deleted.
- Like a movie app, each title shows its seasons with their episodes (Re:Zero: S1 · 25 eps · 2016, S2 · 25 eps,
  S3 · 16 eps) and a rating: MyAnimeList for anime, TMDB for movies and series, or the IMDb rating with your own free
  OMDb key (Settings; IMDb itself has no free way to read its ratings). An IMDb button opens the title's IMDb page.
  Titles checked before get their seasons and rating on the next check.

## 1.3.3
- Titles from screenshots are checked by the app alone: nothing waits for you to pick. Each title is looked up in
  TMDB (or Wikidata), AniList, MyAnimeList and MangaDex, and when none of them finds it, in Wikipedia's search, which
  forgives misspelt or half-read names. The best match is picked and the title takes its official name ("DUNE" and
  "Intersteller" become "Dune" and "Interstellar"); the name read from the screenshot is kept as another name.
- Remakes and look-alikes (a film and its remake, an anime and its manga) go to the one more sources agree on; the
  note says which one it was picked over.
- A title is renamed only when a second source agrees, or one source matches it closely. Anything weaker keeps its
  name and is tried again in 30 days; nothing is renamed on a guess.
- New screenshot titles are checked online right after they are read (no Process tap needed).
- Titles that were waiting for you to pick, or were not found before, are checked again under the new rules.

## 1.3.2
- Look things up online (Settings, off by default): when your notes do not answer a question, Reel Shelf searches
  Wikipedia and DuckDuckGo (free, no key, no account, not AI). Only your question is sent, never your notes. With the
  phone AI, you get one answer that cites your notes [1] and the web [W1]; every web result shows its link.
- In Library, a question ("how do I...", "what is...?") shows "Answer this".
- No new Android permission (the app already uses the internet).

## 1.3.1
- Fix: Play Protect blocked 1.3.0 ("App blocked to protect your device ... can request access to sensitive data").
  The cause was the new Accessibility helper ("Read while I scroll"): Play Protect blocks apps installed from outside
  the Play Store that ask for Accessibility. It is removed. Comments still come from screenshots: tap Add comments on a
  reel, use Comments in Inbox, or keep them in your Screenshots folder; they are matched to their reel.
- No other permission changed: internet, notifications, the nightly alarm and the background-job notification.

## 1.3.0
- Reels are read for real, all on the phone. When Instagram gives the video (logged out), Reel Shelf reads the text on
  screen (a frame every 2 seconds) and what is said (offline speech to text, about 40 MB, Settings, What reels say).
  With Gemma 4 E2B (recommended, 2.6 GB) or E4B (best, 3.7 GB) the AI also looks at key frames and listens to the
  sound, then writes ONE note: what the creator really means (INTENT), the TONE (sincere, sarcastic, joking) and the
  real points. Memes get the joke explained. Reels without a video say "Read from: the caption only".
- Useful reels are read first (newest first), then memes and fun reels. "Try on 5 reels first" on Start; the nightly
  run only re-reads old reels after you tap Start yourself.
- Comments: tap Add comments on a reel and pick screenshots of its comments, or switch on "Read while I scroll"
  (Settings, Comments): an Accessibility helper that keeps Instagram comment screens while you scroll yourself. It never
  taps or scrolls. Note: Play Protect and Android ("restricted settings") are strict with Accessibility helpers in apps
  from outside the Play Store; it is off unless you switch it on. Comment screenshots in your Screenshots folder are
  matched to their reel too.
- Open in Instagram, then come back: Reel Shelf opens that reel with the next step (Add comments, Read this reel properly).
- Battery: the nightly run only runs while charging (default), stops when unplugged, pauses when the phone is warm
  (40°C) and reads at most 200 reels a night (Settings).
- Screenshots: choose pictures, or share them from Gallery to Reel Shelf; "Read my screenshots" is on the Shelf too.
- Ask Meta AI is hidden on reels unless switched on in Settings.
- The APK is for 64-bit phones only (smaller download).
- New, simpler layout: two tabs. **Library** holds everything (reels, quotes, movies, series, anime, manga) with
  chips, To watch / Watching / Watched, and a filter button (status, language, genre, years, length, tag).
  **Inbox** has today's shares, Start, Try 5, Screenshots, Comments, Add, tonight's run and what needs you.
  The top bar has the search, filters, a mic and Settings.
- Search understands everyday words without AI: "horror movie under 1.5 hours", "korean drama I haven't watched",
  "anime from the 2010s", "funny reels about money". It shows what it understood. Titles without a known length are
  listed separately, never mixed in. If the words are unclear and the phone AI is installed, it can turn them into
  a search (nothing leaves the phone).
- Speak your search: the mic uses Android's own speech recognizer (offline when the phone has the language pack);
  Reel Shelf gets no microphone permission.
- Lengths of movies and episodes come from TMDB, AniList, MyAnimeList and Wikidata. Titles checked before get their
  length once, on the next Process or nightly check.

## 1.2.0
- Play Protect: the app no longer has an Instagram sign-in page inside it, no Termux permission, no old server mode and
  no unencrypted (http) traffic. "Get my saved reels" opens Instagram's export page in Chrome; choose the ZIP in Add.
- Instagram is read gently: one reel every 4 to 7 seconds, logged out. If Instagram asks to slow down, the run waits
  2, 10, then 30 minutes, then stops and keeps the rest for the next run.
- More than the caption: the text on a reel's cover picture is read on the phone, plus Instagram's own description of
  the picture. Both count for notes and search.
- "Read my screenshots" buttons on Start, Add and the running screen.
- The AI model download keeps going after you leave the app (notification with Stop).

## 1.1.0
- Nightly run, on by default: every night at 00:00 (change the time in Settings), if the battery is above 40%
  (or charging), Reel Shelf files what you shared and imported during the day, writes notes for reels still waiting,
  reads only new screenshots and checks titles online. Reels already on the shelf or done are skipped. Notification with Stop.
- Quotes: lines worth keeping (movie and series quotes, sayings) are kept from your screenshots, searchable (Shelf, Quotes).
- Start tab shows what the last nightly run did.

## 1.0.0
- First update-safe build: signed with the app's own stable key, so later versions install over it.
  (Copies installed before 1.0.0 were signed with a temporary key: uninstall that once, then install 1.0.0.)
- Instagram export: if Meta sends a web page instead of the ZIP, the download opens in Chrome; choose the ZIP in Add.
- Jobs you start (Start, screenshots, online check, export download) keep running after you leave the app,
  with a notification showing progress and a Stop button. Nothing starts by itself.
- Overnight run (Start tab): AI model, notes for every reel, new screenshots, title check, JSON backup, in one go.
- Meta AI is only used when you tap Ask Meta AI (the Shelf suggestion is off unless switched on in Settings).
- Saved-reels import: big/ZIP64 exports, a "check now" reminder, Chrome fallback.
