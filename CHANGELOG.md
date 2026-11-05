# Reel Shelf for Android: changes

Every change raises `versionCode` (+1) and `versionName` in `android/app-shell/app/build.gradle` and adds a
section here; the APK workflow publishes release `v<versionName>` with this section as its notes, and points
`apk-latest` at it. Builds signed with the stable key (GitHub secrets `ANDROID_KEYSTORE_BASE64` and
`ANDROID_KEYSTORE_PASSWORD`) install as updates over the previous version.

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
