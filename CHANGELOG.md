# Reel Shelf for Android: changes

Every change raises `versionCode` (+1) and `versionName` in `android/app-shell/app/build.gradle` and adds a
section here. A merge builds and tests the APK (kept as the workflow artifact); the owner publishes it by running the
"Android APK" workflow by hand on the install branch, which creates release `v<versionName>` with this section as its
notes and points `apk-latest` at it. Builds signed with the stable key (GitHub secrets `ANDROID_KEYSTORE_BASE64` and
`ANDROID_KEYSTORE_PASSWORD`) install as updates over the previous version.

## 1.3.25
<!-- Written as S4-4 on top of 1.3.22; the number is provisional (merge order). -->
- New: Settings > Backup and restore > **Files kept for safety**. Reel Shelf never deletes a library file it could not
  read, or the library a restore replaced: it sets them aside in its private storage. Until now they were invisible and
  took space for ever. The new screen lists them, newest first, with what each one is, the date it was set aside and its
  size: your library or screenshot list **set aside**, an **earlier copy** of one set aside, and **your library (or
  screenshot list) before a restore**. A set-aside file is never called damaged: it was set aside when the library could not
  be read, but it can be a good copy (for example when restoring it failed), so the screen says "It may still hold your
  data". Leftover files from checking a backup (`restore-staging`, `backup-check`) are one row, **Temporary restore
  files**, with their total size.
- **Save to Downloads** puts a copy of one of them in Downloads/ReelShelf as a `.txt` file (named like
  `reels-before-restore-<date>-<time>.txt`), the same way Back up now does: it only appears in Downloads once it has been
  read back and found complete, and it is deleted again if anything goes wrong. The screen says that the copy is private
  data that other apps and file managers can read (your reels, notes, watchlist, quotes and products, or the text read from
  your screenshots), and on Android 8 and 9 that the copy is deleted if you uninstall Reel Shelf. Saving never changes or
  removes the kept file, and is allowed whatever else is running. The temporary files cannot be saved, only deleted.
- **Delete** is only ever your own tap, and has two steps. The first asks the phone for the file and opens a screen that
  names the file, the date it was set aside and its size, and says "This cannot be undone: once it is deleted it is gone
  from the phone." Only **Delete this file** on that screen deletes it (one file; never a folder; the confirmation works
  once and runs out after two minutes). Delete is refused, with a plain sentence and nothing deleted, while a job you
  started or the nightly run is going, while a backup or restore is running, when the library or the screenshot list cannot
  be read or was saved by a newer Reel Shelf (the files kept may then be the only copy of something you need), when the
  library file a kept file belongs to has not been opened yet since Reel Shelf started (the sentence says what to open:
  your library, or Screenshots; the library is opened by the app at start, the screenshot list only when you open
  Screenshots, and Delete never opens either itself), when a restore is waiting for the temporary files, and when the file
  changed after you looked at it. Listing and saving are never refused.
- Only these files are ever listed or touched: `reels.json` / `shots.json` followed by `.bad-<date>-<time>`,
  `.bak.bad-<date>-<time>` or `.before-restore-<date>-<time>` (with `-2`, `-3` ... when two were set aside in the same
  second), and the plain files directly inside `restore-staging` and `backup-check`. Never your current library, its previous
  copy (`.bak`), a file of a write that is running, the AI or speech models, the picture and video inboxes, shared files that
  are being copied, a link, or a folder. The page only passes back a name from the list; the phone checks it again against
  these patterns and looks the file up again before it saves or deletes anything. The automatic clean-up of leftover temporary
  files is unchanged and still never removes any of these.
- The library screens for "could not be read" and "newer Reel Shelf" do not have this entry (they are the only screens
  shown then); it is in Settings once the library opens.
- Checked with automatic tests on a computer (the page, and the parts that need no phone, including real files in a
  folder: every name the library code makes, a link, a delete without the confirmation, a delete while work or a restore
  runs). Not tried on a phone yet: see TESTING.md, E60 to E65.
## 1.3.24
- AI models that were already on your phone before this version (downloaded by an older Reel Shelf) are now checked too.
  The first time Settings shows one, Reel Shelf reads the file once in the background (about a minute for the big ones
  on a slow phone; the card says "Checking this model file", with a **Stop checking** button) and compares it with the
  exact published file. If it is the published file the card says "Verified: this is the published model file." The
  answer is remembered next to the file together with its size and modified time, and is not asked again while both stay
  the same. It is a label for your information, not a guarantee: it tells what the file was when it was read, so a file
  copied in with its modified time kept, or damage inside the file that keeps its size and time, is not noticed until
  the size or time changes. A model you download in this version is verified while it downloads, so it shows "Verified"
  at once.
- If the file is **not** the published one (damaged, cut off, or another version), nothing is deleted and the model
  keeps working for notes. The card says "This model file is not the published one. It may be damaged." and offers
  **Download again** (the new file replaces the old one only when it is complete and verified; if it fails, the old one
  stays) or **Keep using it**, which is remembered.
- A model file you pick yourself (**Use my own model file**) is always shown as "Your own file, not verified". It is
  never hashed or claimed verified, even when it is the published file (this differs from the design's rule 12, which
  would have called a matching picked file verified). Picking a file no longer replaces a model that is already there:
  when the name is taken (or is the name of a model Reel Shelf downloads) the copy is kept as `name (own).litertlm`, and a
  model download you paused is no longer disturbed by picking a file with the same name. A file name with hidden
  control characters is cleaned up and the file is kept. A copy that was cut off because the app was closed in the middle
  is removed the next time you pick a file or tap Delete the model.
- The check runs only while the app is on screen, never in the nightly run, never beside a download, not while a notes
  job is writing (it can start between two reels and stops when the next one starts), and not on a battery under 15%
  that is not charging. It gives way to anything you start (a download, a notes run, saving a file, picking a file,
  leaving the app) and can be stopped; a stopped check records nothing and the model is never touched. "Ready" still
  only means the file exists, so nothing that worked before stops working.
- Checked with automatic tests on a computer (the check, its remembered answer, stopping, the rules for when it may start,
  picked files, and the Settings screen). Not tried on a phone.

## 1.3.23
- The speech model you download in Settings (Speech to text, about 40 MB) is now checked like the AI models. Reel Shelf
  knows the exact size of the published file and two fingerprints of it (its MD5, which the publisher lists, and a
  SHA-256), and it only takes the file from alphacephei.com itself: an answer that sends the download somewhere else is
  refused. The file is unpacked only after all three match. If the check fails (a cut-off connection, a Wi-Fi sign-in
  page, a damaged or changed file), nothing is installed, only the unfinished download is removed, and a message tells
  you what happened.
- The unpacking is careful too. The download is unpacked into a temporary folder first and refused if it holds anything
  that could write outside the model's own folder (a path that climbs out, a link, a repeated name), more files than
  the published model has, or far more data than it. Only a finished, complete model folder is moved into place in one
  step, so a model can no longer show "Ready" after an unpack that was cut off. A speech model that is already
  installed is set aside first and deleted only when the new one is in place; if anything goes wrong it stays exactly as
  it was.
- A paused speech download is kept and shows **Paused** with **Continue download**; it continues from where it stopped.
  The unfinished download is now kept in the app's own storage (next to the AI models) instead of the cache, so Android
  cannot clear it. A speech download left in the cache by an older version is not used again (Android clears it when it
  needs the room).
- Only one download runs at a time, the speech model or an AI model (they used to be able to run together and stop each
  other). A second tap now says which download is running.
- The page no longer holds anything about where the speech model comes from; the app's own list does. Models already
  on your phone are untouched. The AI model path is unchanged.
- Checked with automatic tests on a computer, including a local test server that sends damaged, cut-off, wrong-size and
  redirected files, and ZIP files built to write outside their folder. The published speech file was also downloaded
  once on a computer: its size and MD5 match what the publisher lists, and its SHA-256 (measured there) is the one in
  the app's list. Not tried on a phone.

## 1.3.22
<!-- Written as S4-3 on top of 1.3.21; the number is provisional (merge order). -->
- You can now **restore a backup**. Settings > Backup and restore > **Restore from a backup** (next to Back up now), and
  the same button on the screen that says your library could not be read. Choose a file made by Back up now with
  Android's own file picker. Reel Shelf checks it first (the whole file, its sizes and checksums, and that it is a
  library this version can read) and only then shows what it would do: "Replace your library (N reels, M titles) with
  the backup from <date> (X reels, Y titles)? Your current library is kept on the phone, not deleted." Nothing changes
  until you tap **Restore this backup**. A file that is not a Reel Shelf backup (a plain reels.json, a notes export
  (JSON), a photo, another ZIP), a damaged or cut-off one, one made by a newer Reel Shelf, or one that does not fit in
  the free space is refused with a plain sentence, and nothing is changed.
- The box **Save a backup of the current library first** is ticked by default: Reel Shelf makes a backup of what you
  have now (as Back up now does) and only then restores. If that backup cannot be made, nothing is restored; untick the
  box to go on without it. (A library that cannot be read cannot be backed up: it is set aside instead.)
- Nothing is deleted. The library you had is kept in Reel Shelf's private storage as `reels.json.before-restore-<date>-<time>`
  (and `shots.json.before-restore-...` for the list of read screenshots when the backup has one), and the screen says
  so. If the backup has no list of read screenshots, yours is left as it is. If the reels were restored and the screenshot
  list could not be, the screen says exactly that.
- Restoring is refused while a job you started (notes, screenshots, an online check, a download) or the nightly run is
  going, and never replaces a library saved by a newer Reel Shelf (the screen for that has no restore button). It
  works on a library that cannot be read, which makes it a way back, and on a new install with no library. The
  "The nightly run is finishing" screen still comes first on every screen. After a restore the app reads your
  library, settings and screenshot list again; a reel you shared while the library was shut is filed into the restored
  library once, and the same goes for a reel shared while a restore is running: it waits and is filed into the restored library.
- Pictures and videos, the AI models, your settings and your API keys are not in a backup, so they are not restored:
  "Pictures and videos are not in backups; reels whose video is no longer on this phone keep their notes."
- A backup's read-back (Back up now) now unpacks into its own folder (`backup-check`) instead of `restore-staging`, so
  the backup made before a restore cannot empty the restore that is waiting.
- Checked with automatic tests on a computer (the page, and the parts of the restore that need no phone, including a
  backup restored over a real library on disk). Not tried on a phone yet: see TESTING.md, E44 to E48.

## 1.3.21
<!-- Written and reviewed as 1.3.9 (Task 2b), before 1.3.10 to 1.3.20 existed; it keeps that text and is numbered after 1.3.20. -->
- The nightly run and the app no longer get in each other's way. If Reel Shelf is on screen when the nightly run is
  due, that night is skipped (the schedule, the hour and the battery level are unchanged: it runs again the next
  night). If you open the app while the nightly run is going, the run is asked to stop its current work and keep
  everything already saved (the reel being processed is cancelled and is retried next night); the app shows "The
  nightly run is finishing" for a few seconds, then opens with everything the run saved. Nothing it saved is lost,
  and your own changes are never overwritten.
- Two nightly runs can no longer overlap, even if two alarms arrive at the same moment.

## 1.3.20
- A **Back up now** button in Settings (under "Backup and restore") saves one file with your whole library to
  Downloads/ReelShelf, named `ReelShelf-backup-<date>-<time>.zip`. It holds your reels, notes, watchlist, quotes and
  products, and the list of screenshots already read. It checks that there is enough free space first, and after
  saving it reads the file back and checks it, so a backup that could not be read back is deleted and reported as
  failed instead of being kept. While it is being made and checked, the file is hidden (Android 10 or newer) or has
  the ending `.part` (Android 8 and 9), and only gets its real name once the check has passed, so a half-finished file
  is never mistaken for a backup. If Reel Shelf is stopped in the middle, a half-finished file may remain (Android 10
  or newer removes the hidden one by itself after about a week; on Android 8 and 9 delete the `.part` file): it is not
  a backup. The message tells you where it saved (with the name Android really gave the file), how many
  reels and titles it holds and how big it is. Your library is not changed by a backup, and a backup is refused while
  the library cannot be opened (then the "Save the unreadable file to Downloads" or "Save a copy to Downloads" button
  is what you have, as before).
- Privacy: the backup file has all your notes in it and can be read by any app with access to your files, so keep it
  somewhere safe or delete it. It does not contain your settings, API keys, AI models, pictures or videos. It also
  holds a short part of the text read from each of your screenshots, and their file names. Reel Shelf
  never deletes old backups for you. On Android 8 and 9 the file is saved in the app's own folder, which Android
  deletes when you uninstall Reel Shelf, and the screen says so: copy it somewhere else.
- There is no restore button yet: this version only makes backups. A later version adds restoring.
- The old **Save JSON** button is now called **Export notes (JSON, cannot be restored)**, because it keeps only some
  of your notes and cannot be read back. The last step of the manual overnight run, which saves that JSON file, no
  longer calls it a backup and points to Back up now.
- Checked with automatic tests on a computer (the page, and the parts of the backup that need no phone). The part that
  talks to Android (saving into Downloads, the free-space check, the read-back) is not tried on a phone yet.
## 1.3.19
- The AI models you download in Settings (Qwen2.5 1.5B, Gemma 4 E2B and Gemma 4 E4B) are now checked. Reel Shelf knows the
  exact size and the fingerprint (SHA-256) of each published file and the exact version to fetch, so it no longer follows
  whatever Hugging Face shows as the newest file. A download is installed only when it has exactly the published size and
  the matching fingerprint. If the check fails (a cut-off connection, a Wi-Fi sign-in page, a damaged or changed file),
  nothing is installed, only the unfinished download is removed, and a message tells you what happened. Tap Download to
  try again.
- Pausing and continuing works as before. When you continue, the part that was already saved is read once more to check it
  (a few seconds), and a download paused by an older version is checked the same way at the end.
- Models are only taken from Hugging Face (huggingface.co and its own download hosts) over https, and a model that is
  already installed is never deleted because a new download failed. The page no longer sends a download address: the app
  uses its own list.
- Models already on your phone are untouched: this version does not check, move or delete them, and a model file you pick
  yourself works as before. The speech model download is unchanged.
- Checked with automatic tests on a computer, including a local test server that sends damaged, cut-off, wrong-size and
  redirected files. The three published files were also downloaded once on a computer: their size and fingerprint match
  the list. Not tried on a phone.
## 1.3.18
- Reel Shelf now cleans up its own leftover temporary files after a crash or a force-stop. It does this once each time
  the app starts, about 20 seconds after you open it, and only if no job and no nightly run is running at that moment.
  It looks in a few fixed places for the unfinished files that a cut-off share, a cut-off video read or a cut-off save
  can leave behind, and removes the ones that are clearly stale: a half-copied shared picture or video, the temporary
  copy of a video that was being read (after 6 hours), the key pictures and sound made for the on-phone AI (after 6
  hours), and a library save that never finished (after 1 hour, and only when your library opened normally this time).
  Each kind of file also has its own check at the moment it would be removed: a share that is being copied, a video that
  is being read, or a library that is being saved is left alone.
- It never touches your library or its backups, your notes, your pictures or videos (including the ones shared to Reel
  Shelf that have not been read yet), the AI and speech models or their downloads, or anything it does not recognise.
  Only a file with one of these exact names in one of these exact places can be removed, and when anything is in doubt
  the file is left alone. It shows no message; it only keeps a count for a Storage screen that may come later.
- Checked with automatic tests on a computer, including a long list of things it must never delete. Not tried on a phone.

## 1.3.17
- Groundwork for backing up and restoring your library. Nothing changes for you yet: there is no button, no screen
  and nothing in the app uses it, so Reel Shelf looks and works exactly as before. The next versions add "Back up now"
  and "Restore from a backup" on top of it.
- What is in place: the code that packs your library into one backup file and that checks a backup file very carefully
  before it could ever be used (it refuses a damaged, cut, unrecognised or newer-than-this-version file and changes
  nothing), and the library file's way of being replaced by a backup without deleting anything: the library it
  replaces is kept next to it under a new name, and a library saved by a newer Reel Shelf is never replaced.
- Checked with automatic tests on a computer. Not tried on a phone.

## 1.3.16
- A reel that fails no longer comes back on every Start and every night. If the on-phone AI cannot write the notes for
  a reel, Reel Shelf tries again after 12 hours, then after 3 days, and after the third failure it **stops trying and
  waits for you**. Stopping the run, the battery or heat stop, leaving the app and Instagram's "slow down" do not count
  as failures.
- The reel page says what happened ("Tried 2 times, last on 14 Nov: ... Next try after 17 Nov." or "Stopped trying after
  3 tries: ...") and has a **Try again now** button. The Inbox shows "N reels could not be finished", which opens a list
  with **Try all again**. The Start screen says how many reels wait for a retry and how many stopped.
- If the AI fails 3 times in a row for the same reason, the run stops with a note, so a broken model cannot use up a
  whole night or mark many reels.
- The nightly run now does three new reels, then one of the oldest waiting reels, so with more waiting reels than the
  nightly limit the old ones are no longer left behind forever. Start by hand is unchanged (useful reels first).
- Your library file gets four optional fields on a reel that failed (`tries`, `last_fail_at`, `last_fail`,
  `next_try_at`); older versions keep them. Nothing was tried on a phone yet.
## 1.3.15
- Your library now carries a small version number (`"schema_version": 1` in the library file), and Reel Shelf checks it
  every time it opens the library. If a future Reel Shelf ever saves your library in a layout this version cannot read,
  this version says so instead of guessing: **"This library was saved by a newer Reel Shelf. This version cannot open
  it safely and has not changed it. Install the newest Reel Shelf."** It then leaves the file exactly as it is: it does
  not put an older copy back over it, does not rename or move it, and saves nothing. The one button is **Save a copy
  to Downloads**; there is no "Start a new library". Reels you share meanwhile wait safely, and the nightly run does
  nothing to it. The screenshot list has the same rule (its own version number, which it always had): it is left as it
  is and the Screenshots screen says why.
- Nothing changes for your library today: it opens the same, with the same reels, and the number is added the next
  time something is saved (a library you start from nothing has it from its first save). Older Reel Shelf installs
  keep working with it, and keep the number when they save. Only this version and later look at the number, so this
  protects you from the release after this one, not from the ones before it.
- Checked with automatic tests on a computer (every earlier release's library file opens and is saved back the same,
  apart from this number). Not yet tried on a phone: see tests E22 to E24 in TESTING.md.

## 1.3.14
- Adding a title to your watchlist, and the online check of a title, no longer slow down as the list grows. Each one used
  to read the whole list again to see whether the title was already there: in a test with a list of 5,000 titles,
  adding them all took about 13 seconds and checking them all about 14 seconds. Now each takes a fraction of a second.
  Which titles count as the same one (name, year, kind, language, other names, database ids, the checked one first, the
  newest first) is exactly as before, and nothing saved changes.
- The first title you add or check after the app starts prepares the lookup for your whole list once (a fraction of a
  second even with 5,000 titles); the next ones are quick.

## 1.3.13
- Searching and opening a reel are much faster in a big library. With 5,000 reels, a search in the Library box or in **Ask**
  is several times faster, and a reel's screen opens about ten times faster (the "Related reels" part was almost all of
  its time). These speeds were measured on a computer, not on a phone. Reels, order, scores and the lines shown for each
  are exactly the same as before.
- The words of your library are checked more cheaply each time you type or open a reel, and only a reel you changed is
  read again. Changing a reel makes the next search or reel screen do a little more work once.
- Not changed: the first search after the app starts still reads the whole library (a second or two with 5,000 reels).

## 1.3.12
- Sharing pictures or videos to Reel Shelf no longer holds the phone up. They are copied in the background while a small
  screen shows how far it is (with Stop). The screen stays until every file is saved, or says which ones could not be
  saved and why (with Try again). Leaving the screen stops the copy; what was already saved stays.
- A file only shows up once it is complete. It is first copied to a separate temporary place, checked, and only then moved
  in, so a copy that is cut short (the phone ends the app, the storage fills up, the other app stops answering) can no
  longer leave a half-written file that is taken for a picture or a video.
- Sharing the same picture or video again does not keep a second copy (and a video does not become a second reel): it
  says it was already saved. So trying again after a failure is safe.
- A copy is refused or stopped (and keeps nothing) when it would leave less than 100 MB free on the phone ("not enough
  storage space on the phone"), so your library can always still be saved. The size limits are as before: 30 MB a
  picture, 500 MB a video. A file that is already saved is still answered as saved when the phone is short of space.
- If the other app stops answering while a file's data is being read, Stop (or leaving the screen) now ends it, and a
  share that waits behind another one can be stopped too, or says it could not start, instead of waiting for ever. A file
  that the other app cut short (it stopped sending half way) is not saved: it says so, and Try again can fetch it.
- Choosing pictures inside Reel Shelf is safe in the same way, and now says when some could not be saved, and why.
  Pictures and videos saved by earlier versions stay as they are.
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
