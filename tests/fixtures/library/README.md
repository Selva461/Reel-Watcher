# Upgrade fixtures: one library per released version

`<version>/reels.json` and `<version>/shots.json` are the two library files **as the page code of that release wrote
them**. They are used by `tests/test_library_upgrade.py` to prove that today's page opens every old library and saves it
back without losing anything.

## They are synthetic

Every reel code, creator, caption, title, brand, quote and note is invented (`FIXA0001`, `sample_creator_one`,
"Bluebird Daily Face Wash", ...). There is no real reel data in them (AGENTS.md forbids it).

## How they were made (not by hand)

`tests/fixtures/make_library_fixtures.py` does, for each version:

1. `git archive v<version> android/app-shell/app/src/main/assets/local`: the page code of that release only.
2. Opens that page in Chromium at phone size with the fake `window.RN` of `tests/test_phone_app.py` (plus the screenshot
   bridge of `tests/test_shots.py`), a fixed clock, and one fixed scenario, played with that page's own functions:
   five things shared while the app was closed (three reel links, one YouTube short, a Meta AI answer for a new reel with
   a PRODUCTS line, one loose answer that stays in the inbox), an Instagram export with a collection, "Start" without
   the AI model (quick notes), "Start" with the model (one reel gets notes, the others fail), five screenshots read
   (titles, a quote, a product), an online check answered for two titles (one verified, one not found), "Ask Meta AI" on
   a reel, a category of your own and a title you typed, the nightly run, and finally a new session where two more reels
   are shared and the AI starts writing one when the app is closed.
3. Writes out, byte for byte, the last text the page handed to `RN.store` (reels.json) and `RN.storeShots` (shots.json).
   The last reel is therefore still `"working"` (the app was closed mid-way), which is what a real killed app leaves behind.

Nothing is edited afterwards. The clock is fixed, so the same tag always gives the same bytes. Run it by hand when a
version is released (CI has no tags):

    python tests/fixtures/make_library_fixtures.py 1.3.12

Never fix a fixture by hand. If a fixture is wrong, change the generator and regenerate it.

## What is in them

Every version has reels in the statuses `new`, `ready` or `ready_no_text`, `done` (notes by `phone`, by `meta`),
`failed` (with quick notes from `auto`) and `working`, an inbox entry, `media` (the watchlist: verified, not found,
typed, from a reel caption), `mediaTypes`, and `shots.json` with five pictures. Later versions add keys:

| Versions | What the page of that release writes |
|---|---|
| 1.0.0 | `reels`, `inbox`, `media`, `mediaTypes` (no quotes, no `lastNight`) |
| 1.1.0, 1.2.0 | adds `quotes`, `lastNight` |
| 1.3.0 to 1.3.2 | same keys, 1.3.x reel fields |
| 1.3.3 to 1.3.5 | adds `verify_rules` (the title-check rule version) |
| 1.3.6 to 1.3.11 | adds `products` |

Several versions give byte-identical files (1.1.0 and 1.2.0; 1.3.0 to 1.3.2; 1.3.6, 1.3.7, 1.3.8, 1.3.10 and 1.3.11;
and `shots.json` is the same in all of them). That is a finding, not a mistake: between 1.3.6 and 1.3.11 the code that
writes the library did not change shape (only how it is protected and shown), so the same scenario writes the same
bytes. They are kept per version anyway, so a future change that makes them differ is seen at once.

There is no v1.3.9 tag (1.3.9 was never released), so there is no `1.3.9/`.
