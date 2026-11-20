# K1: user-editable notes with preserved edits (design, not approved)

Base: `origin/ccr-d0c0b070-bdpssy` at 6d34b25 (1.3.11, versionCode 18). A1 read from `origin/stabilize/a1-retry-cap` at 492e131 (PR #53, not merged; it also carries R4-2 `schema_version`). Planning only. K1 needs A1 and R4-2 merged first (roadmap row 7).
K2 to K5 are not defined anywhere in the repo. They need the owner; this design does not guess them.

## Problem
A reel's notes are written by the phone AI, by Meta AI (paste or share) or without AI (quick notes). The user cannot correct them. If an edit existed, several writers would replace it without asking. K1 lets the user edit the notes and guarantees that no automatic or indirect path overwrites what they typed.

## Verified in code (file:line on 6d34b25 unless marked A1)
- **Shape.** `Notes.parse` (notes.js:85-120) gives `{topic, intent, tone, points[], meaning, use[], tools[], takeaway, tags[]}` plus optional `products`, `ingredients`, `steps`. `Notes.keepBacked` adds `unbacked` (notes.js:420-439). `Notes.autoNotes` gives the quick-notes shape (notes.js:614-633).
- **Per reel:** `notes`, `notes_by` (`"meta"`, `"phone"`, `"auto"`), `notes_at`, `status = "done"`, `error = ""`, `raw` (the answer text, at most 20,000 characters). All of them are written only by `setNotes` (local.js:198-206), which also calls `Products.addFromReel`. I found no reader of `r.raw` in the page.
- **Titles:** they are not stored on the reel. Watchlist entries point back to it by `source.ref` (watch.js:134; listed on the reel by `reelTitlesHtml`, watch.js:144-145).
- **Limits in `parse`:** topic at most 200 characters (notes.js:112); tags at most 12, lowercased, only letters, digits, `_` and `-` (notes.js:109-110); products 12, ingredients and steps 40 (notes.js:116-118). **Points, takeaway and meaning have no cap.** The brief's "40 points" is the ingredients and steps cap. `autoNotes` cuts sentences to 300 characters (notes.js:626).
- **Shown in:** the reel screen `notesHtml` with the `BY` label (local.js:790-807, 753-754); library rows, topic and 4 tags (local.js:780-788); tag counts (home.js:249); search lines (notes.js:534-538, library.js:73); Copy notes (local.js:845); exports (notes.js:713-738); Ask prompts (notes.js:636-651).
- **No edit UI exists today.** The only text box on a reel is "What the reel says" (`extra`, local.js:838-847), and it is input for the AI. `BY.you = "Your notes"` already exists (local.js:753), and does so since v1.3.6 (checked with `git show v1.3.6`). But nothing writes `notes_by: "you"`.
- **Writers and their guards today:**
  1. **Start and the nightly run.** `needsWork` (local.js:277-284; A1 285) skips every reel with notes unless `notes_by === "auto"`. `startRun` writes with the phone AI only when there are no notes or the notes are `"auto"` (local.js:545), and clears `"auto"` notes when more text was read (local.js:541). The night picks through the same `needsWork` (local.js:622; A1 `nightQueue` 531).
  2. **Explicit buttons.**
     - "Read this reel properly" (local.js:860-865) and "Read from YouTube again" (local.js:867) clear only `"auto"` notes.
     - By reading the code (not run), "Redo with phone AI" (local.js:848) writes nothing for a reel with `"meta"` or `"phone"` notes, because of line 545.
  3. **Meta AI, with no guard at all.** All of these call `setNotes` and overwrite any notes:
     - `pasteDialog` (local.js:1003-1013);
     - the shared-item inbox (`fileShared` then `fileAnswer`, local.js:209-224, 170-196), which **the nightly run also calls** (`takeShared`, local.js:607);
     - Add, "Paste links or answers" (local.js:1048);
     - `fileScreen` "pick" (local.js:1097).
     The "last asked" fallback (local.js:182) and the pick list (local.js:1089) exclude only `"meta"` notes.
  4. **The video merge.** `readFileVideo` (local.js:412-421) merges a caption-only reel into a phone video by the same author, then **removes the old reel and its notes**. Its notes are not carried over. Today that loses any Meta notes it had, and it would lose an edit too.
  5. **Not writers:** verify.js and catalog.js (no use of `notes`); comment screens (local.js:717-728, only reset `video_tried` for `"auto"`); the Instagram ZIP import (`addReels`, local.js:154-167, only adds collections). **Explicit deletes** ask first (local.js:868, 1270). **S4 restore** replaces the whole file (S4 design C); the page has no JSON import or merge.
- **Indexes.** `Notes.fieldsOf` reads topic, tags, tools, points, meaning, use, takeaway (notes.js:467-472). `docOf` caches per reel object and rebuilds when a field text changes (`sig`, notes.js:477-488; `sameTexts` on A1 and P2), so an in-place edit re-indexes search, Related (notes.js:545) and topics (library.js:17-23) with no new code. `Lib.tagsOf` reads `notes.tags` (library.js:34). `Shots.fromReels` re-reads a reel for titles when `text.length + ":" + notes_at` changes (shots.js:106-108).
- **A1:** a success deletes `tries`, `next_try_at`, `last_fail`, `last_fail_at` (A1 593); "Try again now" and the retry card show only for no or `"auto"` notes (A1 889); `failedScreen` lists `status === "failed"` (A1 862).
- **R4 rule** (A1-R4 design, Rules): an optional field old code ignores and keeps needs no bump; test_library_upgrade.py:244-275 keeps unknown keys; A1 `SCHEMA = 1` (A1 73). `.btn` and `.input` are 48 px high (app.css:40, 62).

## Options
**A. Edit in place plus a marker (recommended).**
- `r.notes` holds what the user sees, with their text in it.
- `notes_by` becomes `"you"`.
- A new `notes_edit` keeps which fields were edited and their AI text from before the edit.
- Pros:
  - Every reader (search, Related, topics, tags, Copy, exports, Ask prompts, Shots, Products) sees the edit with no change.
  - `needsWork` already skips `"you"` in every released version, so even a rollback build never re-writes an edited reel automatically.
- Con: every AI writer must divert its output instead of writing to `notes`. There is one choke point for that, `setNotes`, plus the video merge.

**B. Overlay: `r.user = {topic, ...}` over unchanged AI `notes`.**
- Pro: regeneration is trivial. Cons: about 12 readers need an "effective notes" helper (fieldsOf, notesHtml, reelRow, format, exports, tagsOf, tools, home tags, shots, search lines, Ask prompts), and one missed reader shows stale AI text. Older versions ignore the overlay, so after a rollback the edits seem gone, and they still re-write edited `"auto"` reels. Rejected.

## The change (option A; all additive)
**Data (per reel; missing means not edited):**
- `notes_by: "you"`, set at the first edit. The existing field gets a value released versions already label and skip.
- `notes_edit: { was_by: "phone", at: <ms>, fields: ["topic", "takeaway"], ai: { topic: "<AI text>", takeaway: "<AI text>" } }`.
  - `ai[f]` is written once: at the first edit of field `f`, from the AI notes.
  - For notes written from scratch, `was_by` is `""` and `ai` is `{}`.
- `notes_next: { meta: {at, notes, raw}, phone: {at, notes, raw}, you: {at, notes, edit, raw} }`: versions kept aside, **one slot per source** (H1). An arrival replaces only the slot of its own source, so a phone AI answer can never replace a waiting Meta AI answer, which the user cannot get back without asking Meta again. A newer Meta answer replaces an older Meta one: the user shared both, and the newer one is the one they chose to send. `raw` is kept per slot, capped at 20,000 characters as `setNotes` does (local.js:204). The `you` slot holds the user's own version, with its `notes_edit`, after "Use the new AI version" (M4). Versions move between the screen and the slots only by a swap (see K1-3), so a kept version is never dropped without a question.
- **`raw` (L1)** is AI bookkeeping with no reader in the page (local.js:204 is its only writer). It moves with its version: the `you` slot keeps the `r.raw` that was on the reel, so a swap back restores it. Only "Keep my edits, update the rest" drops a `raw` on purpose: it sets `r.raw` to the slot's `raw`, because the fields not edited now come from that answer, and the previous `r.raw` is discarded.
- **A Meta answer for a reel that is not edited (L2)**, for example after "Use the new AI version", is applied directly, as today. It also clears an older waiting `meta` slot: the same "newer Meta replaces older Meta" rule, so one reel never shows two Meta versions. `notes_next.you` and `phone` are untouched.
- **`notes_edit` while `notes_by` is not `"you"`** (an older build overwrote the reel, M5): it is ignored (`isEdited` is false) and kept on disk, not dropped (it then holds only AI text). The next first edit replaces it.
- Editable in v1: `topic`, `points`, `takeaway`, `tags` (D-K2). The other fields are shown read-only.

**Pure helpers in notes.js (exported, harness-testable):**
- `Notes.cleanField(f, value, old)` applies the normalisation of `parse` (`para` for topic and takeaway, one point per line, the tag rule) and returns `{value, error}`. **Only a field whose value changed is checked (M3)**: an unchanged AI field passes as it is, even past the limits, because `parse` already lets AI notes go past them (points, takeaway) and long values do not break render, search, export or Related. "Changed" means the cleaned new value differs from the cleaned stored value. Arrays (points, tags) are compared item by item, in order, so whitespace alone is not a change. A changed field may be as long as the larger of its limit and its stored length. Points are checked one line at a time: a line not in the stored list may be as long as the larger of 500 and the longest stored point, and the count limit is the larger of 40 and the stored count. `parse` keeps points longer than 500 (a 709-character one was kept). The longest stored point is used, not the line at the same position, because an inserted or moved line shifts positions and would then be checked against the wrong line. The bound still comes from text the parser already accepted. So fixing a typo in a 2,000-character AI takeaway, in one of 50 AI points or in a 700-character AI point is never blocked. Typed text limits (D-K8): topic 200 ("The topic can be at most 200 letters."), points 40 lines of 500 ("Keep at most 40 points, each under 500 letters."), takeaway 1,000, tags 12 ("Only the first 12 tags are kept."). Topic and points both empty: "Write a topic or at least one point." (`parse` needs one of them).
- `Notes.applyEdit(r, f, value, now)`, `Notes.revertField(r, f)`, `Notes.isEdited(r)` (true when `notes_by === "you"`). Reverting the last field sets `notes_by = was_by` and deletes `notes_edit`. `applyEdit` on points deletes `notes.unbacked` (L3), so "N lines were left out" is not shown under the user's own points.

**Guards in local.js (K1-1):**
- `setNotes(r, notes, by, raw, force)`: if `Notes.isEdited(r)`, `by !== "you"` and not `force`, it fills `r.notes_next[by]`, does not touch `notes`, `status`, `raw` or Products, and returns `false`. Every caller handles `false` (M1) with one message, "Kept aside: this reel has your edits. Open it to compare.":
  - `fileAnswer` counts kept answers apart and puts the count in its toast;
  - `pasteDialog` (local.js:1013) shows it instead of "Saved";
  - the `fileScreen` pick (local.js:1097) shows it, then shifts the inbox as today (the answer is in `notes_next`);
  - `writeWithPhoneAi` (local.js:509) returns it; `startRun` then does not count `run.done++` and logs that line.
  - Two callers cannot reach an edited reel, so they need no handling: `writeWithoutAi` (local.js:497) runs only for a reel with no notes (local.js:555-556), and "Keep it as a note on its own" (local.js:1101) creates a new reel.
- **`Notes.hasUserData(r)`** = `Notes.isEdited(r) || !!r.notes_edit || Object.values(r.notes_next || {}).some(Boolean)`. After "Use the new AI version" a reel is not edited but holds the user's version in `notes_next.you`, so `isEdited` alone is not enough.
- `readFileVideo` (local.js:412-421): a reel with `hasUserData` is never chosen as `old`, so it is never merged away (D-K10). Recommended over carrying `notes`, `notes_by`, `notes_edit`, `notes_next` and `raw` into the video reel. Why: the video reel can hold notes of its own (quick notes, or phone AI notes from the video), and carrying them over would need a two-sided merge of versions. Skipping leaves two entries for one reel, as today when more than one reel matches (`same.length !== 1`), and loses nothing. This is the only branch that drops a reel; the other branch changes nothing, and `addReels` (local.js:154-167) only adds collections to a reel it already has.
- **Explicit deletes.** "Remove from shelf" (local.js:868) says, for a reel with `hasUserData`: "Remove this reel, its notes, your edits and the versions kept aside from Reel Shelf?". "Delete all reels and notes" (local.js:1270) adds "including your own edits" when any reel has `hasUserData`.
- `applyEdit` also sets `status = "done"` and `error = ""`, deletes A1's `tries`, `next_try_at`, `last_fail`, `last_fail_at` (as A1 593), and bumps `notes_at` so Shots re-reads the tags.
- `needsWork` and `nightQueue` are unchanged: `"you"` returns false before any AI step (local.js:278).

**Edit UI (K1-2), reel screen:**
- "Edit notes" (`#editNotes`) next to Copy notes; "Write my own notes" when the reel has none (D-K7). It opens a `$dlg` form like `pasteDialog`: Topic `<input>`, Points `<textarea>` (one per line), Takeaway `<textarea>`, Tags `<input>` (commas). Each control has a visible `<label for>` and a hint linked by `aria-describedby`; an error shows under its field with `role="alert"`; Save and Cancel are 48 px.
- "Use the AI text" on an edited field (only when `ai[f]` exists) **changes only the form** (M4): Save applies it with `revertField`, and Cancel leaves the user's text as it was. So it needs no confirm.
- `notesHtml` shows "Edited by you" under each edited section label; `BY` reads "Your notes (edited from Notes by the on-phone AI)".
- Save goes through `saveDb()`. The typed draft lives in a page variable `editDraft = {code, fields}`, **apart from the reel object** (L5): `loadDb` replaces every reel object, and the draft is never written on a reel. If the save returns false with `staleSave`, the page reloads as today, reopens the editor on the fresh reel with the draft and says: "Your library changed elsewhere. Your text is still here: tap Save again." It is applied only on that tap.

**Regeneration choice (K1-3):**
- For each AI slot in `notes_next`, a card says: "A newer version from Meta AI (19 Nov) is waiting. Your edits are kept." It has 4 buttons:
  1. **Show it**: `notesHtml` of that slot.
  2. **Keep my edits, update the rest** (primary, D-K5): new AI text for the fields not edited; `ai[f]` set to the new AI text for the edited ones; `notes_by` stays `"you"`; calls `Products.addFromReel` (L4); clears that slot.
  3. **Use the new AI version** (M4): **the user's version is kept, not deleted**, by a swap (below). A card "Your edited version is kept" offers "Use my version again" and "Delete my version". Delete asks first: "Delete your edited notes for good?". Why: section 8 says never silently delete user data, and an undo costs about 1 KB.
  4. **Dismiss**: clears that slot, after asking.
- **The swap, `Notes.swapIn(r, slot)` (H-a).** Both "Use the new AI version" and "Use my version again" are swaps. Changed from "move to `you`, then apply" after re-review H-a, because that dropped a kept version without asking.
  - The version on screen goes to the slot it came from. That slot is `you` when `notes_by` is `"you"`. When the text on screen was applied from an AI slot, `notes_by` is that slot's source (`"meta"` or `"phone"`, set by `setNotes(..., force)`), and the slot is `meta` or `phone`. The `you` slot keeps `notes_edit`; an AI slot keeps `r.raw`.
  - Then the chosen slot is applied and emptied.
  - If the target slot is the chosen slot, it is a pure swap with nothing lost: for example, "Use my version again" while newer edits are on screen moves those edits into `you` and brings the kept version back.
  - If the target slot is a different slot that is already full, it asks first: "Replace your earlier kept version?" or "Replace the Meta AI version kept aside?". If the user says No, nothing changes.
  - So the AI version that "Use my version again" replaces goes back to its `meta` or `phone` slot.
- **Redo with phone AI (M2):** `#phoneai` alone calls `startRun([code], {redo: true})`. The other explicit lists (the nightly run at local.js:622, "Read this reel properly", "Read from YouTube again", A1's "Try again now" and "Try all again") have no flag. So they never send an edited reel to the AI, and test 2 holds. In `startRun`, the AI step may run for a reel only when `!r.notes || r.notes_by === "auto" || (redo && Notes.isEdited(r))`. `#phoneai` is also shown on reels that are not edited, and the guard covers edited reels only. So `redo` must never lift the line-545 rule for a reel with `"meta"` or `"phone"` notes, which would let `setNotes` overwrite them. For an edited reel, the notes land in `notes_next.phone` through the guard. If `notes_next.phone` already exists, Redo asks first: "A phone AI version is already waiting. Replace it?". A waiting Meta slot is never touched. **A failure on an edited reel** keeps `status = "done"`, adds no `tries` and no `last_fail`, and shows the reason in the run log only. So it never enters "Could not finish". The same holds for Stop and "slow down" in the `startRun` catch (local.js:561-562): they set `status = "new"` today, but an edited reel stays `"done"`.

**Size** (scratch Node on the P4 generated reel: about 4.8 KB per reel, 4.6 MB per 1,000; its notes object is 898 bytes):
- **Typical sizes** (L1): `notes_edit` with all 4 fields edited is 775 bytes; one `notes_next` slot is 948 bytes plus its `raw`. With 10 % of reels edited: about +0.08 MB per 1,000. If every reel is edited and has one slot waiting: about +1.7 MB per 1,000 (+37 %).
- **Theoretical maximum at the D-K8 sizes:**
  - `notes_edit`: about 22 KB;
  - each slot: about 22 KB of notes plus `raw`, capped at 20,000 **characters**: 20 KB for ASCII, more for other characters, which take 2 to 4 bytes each in UTF-8;
  - three slots: up to about 155 KB per reel for ASCII, about 155 MB per 1,000.
  - Real answers are far smaller: the phone AI is bounded by `maxTokens` (800 by default, local.js:131).

**Schema:** no bump. All three keys are optional, and old code ignores and keeps them (R4 rule, test_library_upgrade.py:244). `"you"` is a value released pages already label and skip. **Export:** JSON and Markdown export what is shown, so they include the edits, and `notes_by` reads `"you"`. Nothing more is added. **Backup and restore:** S4 copies the whole file, so the new keys travel with it.

**Privacy:** edits stay in reels.json on the phone. They leave it only when the user exports, copies or shares, or through the Ask prompts to the on-phone AI. `metaPrompt` sends the link and transcript, not the notes (notes.js:160-166). No network call is added.

**Out of scope:** editing intent, tone, meaning, use, tools, products, ingredients and steps; an edit history beyond the one AI original and the kept user version; merging two devices; the pre-existing loss of `old.notes` in the video merge for reels with no user data (D-K10); K2 to K5.

## Failure modes
| Case | Result |
|---|---|
| Meta answer shared at night for an edited reel | `takeShared` files it into `notes_next`; the share is acked after the save as today; the edit is untouched |
| Stale save while editing | refused, reloaded, editor reopened with the draft; nothing applied silently |
| Rollback to 1.3.11 (M5) | `needsWork` skips `"you"`, but every Meta path there overwrites `notes` and leaves a stale `notes_edit`: the paste dialog (1013), the share inbox on opening the app and in the nightly `takeShared` (215, 607), Add paste (1048), the "last asked" fallback (182, which excludes only `"meta"` notes) and the "File this answer" pick (1089, 1097). **So any rollback build must carry the K1-1 guard.** |
| Reverting the last field of edited quick notes | back to `"auto"`, so Start may rewrite it: correct, since no user text is left |
| Invalid input | field error, Save blocked, nothing stored |

## Tests (`tests/test_editable_notes.py`, phone harness with the fake RN from test_phone_app.py; no network, no model)
1. `applyEdit` on topic sets `"you"`, `notes_edit.ai.topic`, `status` and `notes_at`, and clears A1 fields. `RN.store` receives it. Search finds the new word.
2. An edited `"auto"` reel with a ready model: Start and `nightQueue` pick it 0 times, and a fake `generate` is called 0 times.
3. Every Meta path (share inbox, `pasteDialog`, Add paste, `fileScreen` pick, the night's `takeShared`) leaves `notes` equal, fills `notes_next.meta` and shows "Kept aside". `pasteDialog` does not say "Saved". A kept phone AI answer does not raise `run.done`.
4. The video merge does not remove a reel with `hasUserData`: an edited reel, a reel with only `notes_next.you` (after "Use the new AI version"), one with only a waiting AI slot, and one with only a stale `notes_edit`. The "Remove from shelf" text names the edits and kept versions.
5. `revertField` per field; reverting the last field restores `was_by`.
6. The three choice buttons and Dismiss.
7. `cleanField` limits and messages.
8. Stale refusal keeps the draft.
9. The R4 upgrade test with `notes_edit` and `notes_next` added (keys survive).
10. Labels and `role="alert"`; button height of at least 48 px.
11. Redo and validation:
    - a waiting Meta slot survives a phone Redo;
    - with a phone slot waiting, Redo asks first;
    - a failing, stopped or "slow down" Redo leaves `status` "done" and no `tries`;
    - other explicit lists never call `generate` for an edited reel;
    - Redo on a `"meta"` reel that is not edited calls `generate` 0 times and leaves its notes equal;
    - only changed fields are validated: an untouched 2,000-character AI takeaway does not block a topic edit, editing one point of a 50-point AI list saves, and fixing a typo in a 700-character AI point saves.
12. Swap: a second "Use the new AI version" with a full `you` slot asks, and on No changes nothing. "Use my version again" with newer edits on screen keeps those edits in `you` and puts the AI version back in its slot. A swap back restores `r.raw`. A Meta answer applied directly to a reel that is not edited clears an older `meta` slot and leaves `you` untouched.

**Deliberate breaks** (each must fail a test): remove the `setNotes` guard (3); make `isEdited` false (2, 3); let `"you"` pass `needsWork` (2); drop the merge exclusion (4); merge away a reel with only `notes_next.you` (4); skip the 200 cap (7); apply the draft after a reload (8); drop `notes_edit` in `loadDb` (9); use one `notes_next` slot for every source (11); run the AI for an edited reel without `redo` (11); count a failed Redo as a try (11); let `redo` alone allow the AI step (11, the "meta" reel); validate unchanged points (11); hold a changed point to 500 even when a stored point is longer (11); overwrite a full `you` slot without asking (12); drop the on-screen version in "Use my version again" (12).

## PR split (stacked; each bumps versionCode and versionName and adds a CHANGELOG section, per AGENTS.md)
1. **K1-1:** the data model, the helpers in notes.js, the `setNotes` guard, `notes_next`, the merge exclusion. The `false` handling in every caller. Tests 1-5, 7 and 9 call the functions directly; there is no UI. Opus review of the guard.
2. **K1-2:** the edit dialog, "Edited by you", "Use the AI text", "Write my own notes", the stale draft. Tests 5, 7, 8, 10 and the validation part of 11 through the screen.
3. **K1-3:** the regeneration cards, the kept user version, and the `redo` flag. Tests 6, 11 (the Redo part) and 12, and test 3 through the screen. The validation part of test 11 goes in K1-2.

## Device checks (owner only)
1. Edit a reel, close the app, run the nightly run with a Meta answer for it shared during the day. The edit is kept and the card shows.
2. TalkBack reads each field label and error. Large font: the dialog scrolls and the buttons stay reachable.
3. Install over the previous build. The counts are unchanged and an edited reel is still edited.

## Owner decisions (recommended default)
- **D-K1** Data shape: **in place, `notes_by: "you"` plus `notes_edit`**, not an overlay.
- **D-K2** Editable fields in v1: **topic, points, takeaway, tags**.
- **D-K3** Keep the AI original of each edited field: **yes** (about 0.8 KB per fully edited reel).
- **D-K4** New AI text for an edited reel: **held in `notes_next`, one slot per source; a newer answer replaces only its own source's slot; Redo asks before replacing a phone slot; the user chooses**. Changed from a single slot after review H1, because a phone Redo could otherwise erase a Meta answer.
- **D-K5** Primary choice: **"Keep my edits, update the rest"**. "Use the new AI version" keeps the user's version in `notes_next.you` (M4).
- **D-K6** Editing quick notes stops automatic AI notes for that reel: **yes**.
- **D-K7** "Write my own notes" for a reel without notes: **yes**, in K1-2.
- **D-K8** Limits: **topic 200, points 40 x 500, takeaway 1,000, tags 12, for typed (changed) fields only**.
- **D-K9** K2 to K5: **owner to define**. Nothing is built for them.
- **D-K10** Video merge: **never merge away a reel with `hasUserData` (edited, a stale `notes_edit`, or any kept version) (K1-1)**, rather than carrying its versions into the video reel. The loss of non-edited `old.notes` is a separate task.

## Risks
- **A missed writer.** Mitigated by the single choke point `setNotes`, a grep for `.notes =` in review, and test 3 covering every path found.
- **Rollback overwrite:** in an old build, every Meta path overwrites an edit, including the share inbox and the nightly run (see Failure modes). A rollback build must carry the K1-1 guard.
- **Library growth** if many reels hold `notes_next`. Dismiss clears it; P4 measures the cost.
- **Not run:** the "Redo with phone AI" no-op and the dialog after `staleReload` were found by reading only. **NEEDS VERIFICATION** in the harness in K1-1 and K1-2.
