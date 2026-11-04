# Reel Shelf for Android: changes

Every change raises `versionCode` (+1) and `versionName` in `android/app-shell/app/build.gradle` and adds a
section here; the APK workflow publishes release `v<versionName>` with this section as its notes, and points
`apk-latest` at it. Builds signed with the stable key (GitHub secrets `ANDROID_KEYSTORE_BASE64` and
`ANDROID_KEYSTORE_PASSWORD`) install as updates over the previous version.

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
