# U2: accessibility audit and minimal fixes (design, not approved)

Base for every file:line below: `origin/stabilize/s4-4-files-set-aside` at **563f81f** (PR #70, not merged, 1.3.25). The page files are under `android/app-shell/app/src/main/assets/local/`. Where a line is the same on the default branch (1.3.11) is not checked line by line; screens added by unmerged PRs (backup, restore, kept files) are included. Planning only: no code was changed. **No finding below was checked with TalkBack or on a phone**: they come from reading the code and computing colour contrast (WCAG 2.x formula, script in the session scratchpad).

## Problem
Reel Shelf is one WebView page (`index.html`) with screens drawn by `$app.innerHTML` (29 places). Nothing has been checked for TalkBack, large text, contrast or motion. Some basics are good; a few patterns hurt every screen.

## What is already right (verified)
- `lang="en"` (index.html:2); the viewport does not block zoom (index.html:5).
- Every screen has one `<h1>` from `header()` (local.js:34-37); sections use `<h2>`.
- Icon-only controls in the top bar and headers have labels: Search, Clear search, Speak, Filters, Settings (index.html:16-18), Back (local.js:36), Close (home.js:262). SVGs are `aria-hidden` (local.js:27-31).
- Toggle buttons say their state: chips, segments and status use `aria-pressed` (home.js:86-87, watch.js:82, local.js:1553); the nightly switch has `role="switch"`, `aria-checked` and a label (verify.js:258).
- The current tab has `aria-current="page"` (home.js:366); the tab bar is a `nav` with a label (index.html:22).
- The toast is a persistent `role="status"` (index.html:28); 11 result messages use `role="status"` or `role="alert"`.
- Dialogs use `showModal()` (local.js:1020, home.js:287), so focus goes into them and back.
- Text contrast passes AA (4.5:1) everywhere I computed it: `--muted` #A3A09A on bg 6.93, on surface 6.23, on surface2 5.26; placeholder #8E8B85 on surface 4.78; `--danger` on surface 7.55; dark text on the accent 9.87; tags 9.16 and 9.17 (app.css:2-5, 67).
- Motion is almost nil: one 0.4 s width transition on progress bars (app.css:70), no animations, no smooth scrolling.

## Findings (severity: H high, M medium, L low)
| # | Sev | Where | Finding |
|---|---|---|---|
| F1 | H | index.html:21 | `<main id="app" aria-live="polite">`: every screen change, and every repaint of a screen (the run screen repaints after each reel, local.js:1150), is a live-region update of the whole page. TalkBack may read whole screens unasked, or interrupt itself (NEEDS VERIFICATION on a phone). |
| F2 | H | local.js:1741 | On a route change the page only calls `render()` and `scrollTo(0, 0)`. Focus is not moved: the element that was tapped is gone, so TalkBack focus lands somewhere undefined (often the top of the page or the tab bar). |
| F3 | M | app.css:66 | `.search input { outline: none }`, and no `:focus` or `:focus-visible` style exists in either CSS file. With a keyboard or switch access the focus is invisible in the search fields (top bar and Ask, local.js:939). |
| F4 | M | index.html:25, home.js:367-368 | The Inbox tab has `aria-label="Inbox"`, which replaces its content, so the badge count ("3") is never read. |
| F5 | M | shots.js:254-259 | On "Without a sure name", each card has the same buttons "Add", "Google Lens", "Not a title" and an image with `alt=""`. TalkBack hears 12 identical sets with nothing saying which screenshot they belong to. |
| F6 | M | app.css:69-70, local.js:1159, 1563, home.js:312 | Progress bars are plain `span`s with a width: no `role="progressbar"` or value, so "how far" is only visual (the text beside some bars helps; the run card shows only "3 / 10"). |
| F7 | M | app.css:40-41, 51, 62 | Non-text contrast: the border is the only edge of normal buttons, chips and inputs, and `--line` #3A3B43 is 1.62:1 on bg and 1.46:1 on surface (WCAG 1.4.11 asks 3:1). (`.check-btn`, 2.09:1, is not used by the Android page.) |
| F8 | M | see the table below | Tap targets under 48 dp. |
| F9 | L | home.js:181 | The quote row's copy button is labelled only "Copy" (copy what?). |
| F10 | L | index.html:17, home.js:45 | The Filters button shows a dot when a filter is on; the label does not change, so "filters are on" is not said. |
| F11 | L | local.js:19-24 | Toasts disappear after 3.6 s. TalkBack reads them (live region), but a sighted slow reader can miss a long one (some are two sentences, local.js:1012). |
| F12 | L | home.js:204, 325 | `<summary>` lines are 12-13 px text with no padding: a small target (the card-style ones, local.js:844-846, have card padding and are fine). |
| F13 | ? | MainActivity.java:59-64 | The WebView never calls `setTextZoom`. Whether this WebView follows the system font size by itself is **NEEDS VERIFICATION** (device check A11-2). All font sizes are fixed `px` (app.css, local.css), and several boxes have fixed heights (`.badge` 16 px, local.css:35; `button.bare` 40 px, local.css:30; `.switch` 32 px, app.css:91), so at 200% text they may clip. |
| F14 | ? | app.css:70 | Whether the WebView reports Android's "Remove animations" as `prefers-reduced-motion` is NEEDS VERIFICATION. The page has no rule for it either way. |

**Tap targets (F8).** At `width=device-width, initial-scale=1` one CSS px is one dp (assumed, NEEDS VERIFICATION with `devicePixelRatio`).
| Control | Size | Where |
|---|---|---|
| `.icon-btn` (Back, Settings, Filters, Copy, Close) | 44 x 44 | app.css:47 |
| `.chip` (Library kinds, topic and tool links) | 36 high | app.css:51; home.js:86; local.js:887, 905, 918 |
| `button.bare` (Clear search, Speak) | 36 x 40 | local.css:30; index.html:16 |
| `.seg button` (status, settings choices) | 44 high | app.css:58 |
| `.switch` (nightly check) | 52 x 32 | app.css:91; verify.js:258 |
| `.small-field select` | 44 high | local.css:16 |
| `.btn`, `.input`, tabs | 48 (fine) | app.css:40, 62, 104 |

## Options
1. **Minimal fixes in the page only** (recommended): the fix list below, mostly CSS in `local.css` plus a few attributes. No change to the look beyond slightly bigger targets and lighter borders.
2. Option 1 plus a design-system pass (rem units, a type scale): a rewrite of every screen. Rejected for now.
3. Do nothing until a phone audit: leaves F1 and F2, which are certain from the code.

## The change (option 1)
`app.css` must stay byte-equal to `src/reel_watcher/webapp/app.css` (tests/test_phone_app.py:452-453), so every CSS fix goes into **`local.css`** (Android only), which loads after it (index.html:11).
1. F1: remove `aria-live` from `<main>`. Messages that must be heard keep their `role="status"` or `role="alert"`, or go through the toast.
2. F2: `header()` gives the `<h1>` `tabindex="-1"`; the `hashchange` handler focuses it after `render()` (not on repaints of the same screen, not while a dialog is open).
3. F3: `local.css`: `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }` and the same for `.search:focus-within`.
4. F4: drop the tab `aria-label`s (the visible text is the name) and give the badge visually hidden text: "3 new". Same for Library.
5. F5: each card becomes a `group` labelled "Screenshot N of M, FILE-TEXT"; the buttons get `aria-label`s like "Add a name for screenshot 3", "Open screenshot 3 in Google Lens", "Screenshot 3 is not a title".
6. F6: `.bar` gets `role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow` and a label (in the shared bar markup).
7. F7: `local.css` overrides `--line` to #6A6B74 (3.42:1 on bg, 3.07:1 on surface; computed).
8. F8: `local.css`: `.icon-btn`, `button.bare`, `.chip`, `.seg button`, `.small-field select` get `min-width/min-height: 48px`; `.switch` keeps its look inside a 48 dp hit area (padding).
9. F9, F10: "Copy quote"; Filters says "Filters, on" when the dot shows.
10. F12: `summary { padding: 12px 0; }`.
11. F14: `@media (prefers-reduced-motion: reduce) { .bar > span { transition: none; } }`.
12. F13 and F11: no code until the device check A11-2 (D-U2-3, D-U2-4).

## Failure modes
- Moving focus on every repaint would make TalkBack jump during a run: focus moves only on `hashchange`.
- Lighter borders and 48 dp targets change the layout slightly: the chip row scrolls sideways already (app.css:49); the top bar (search plus two buttons) gets 8 dp tighter on a 360 dp phone (NEEDS VERIFICATION, check A11-3).
- Live regions created by `innerHTML` with text already inside may not be announced (NEEDS VERIFICATION). Critical results that must be heard should also go through the toast.

## Tests
**Phone harness (Playwright, Chromium, fake RN; `tests/test_accessibility.py`):** visit every route in `ROUTES` (local.js:1642-1651) plus the locked, newer, restore, kept and dialog states, and assert:
- every `button`, `a[href]`, `input`, `select`, `textarea`, `[role=switch]` has an accessible name (Playwright `get_by_role` / `aria_snapshot`, already used in tests/test_app.py:250-262);
- the names of buttons inside one card are unique on the screen (F5);
- every interactive element's bounding box is at least 48 x 48 (a short, named exception list, for example inline text links);
- `#app` has no `aria-live`; after a `hashchange`, `document.activeElement` is the `<h1>`;
- `.bar` elements have `role=progressbar` and a value;
- with `reduced_motion="reduce"`, the computed `transition-duration` of `.bar > span` is `0s`;
- reflow: at a 195 px wide viewport (390 at 200%) `scrollWidth <= clientWidth` on every screen. This only approximates large text; it is not the Android font setting.
**Pure test:** parse the CSS variables and assert text pairs >= 4.5:1 and border pairs >= 3:1.
**Cannot run in the harness:** TalkBack's real reading order and announcements, Android font scale, display size, Remove animations, the real dp size.

## PR split
1. **U2-1** (publishing, left READY; base: the newest app branch at the time): fixes 1-11 in `index.html`, `local.css`, `local.js`, `home.js`, `shots.js`, plus `tests/test_accessibility.py`, CHANGELOG, TESTING rows, version bump. One combined Opus review.
2. **U2-2** only after A11-2: text zoom (`setTextZoom` from `fontScale`, if needed) and fixed heights that clip.

## Device checks (owner only)
- A11-1: TalkBack on. Walk Library, a reel, Inbox, Settings, Screenshots review, Restore and Files kept for safety. Note what is read on each screen change and whether anything is read twice or not at all.
- A11-2: Android font size at the largest and display size at the largest: does the page text grow? Does any text clip or overlap? (decides F13)
- A11-3: on the smallest phone available, the top bar and chip rows after U2-1.
- A11-4: Remove animations on, then open Settings while the model downloads: does the bar still slide? (decides F14)
- A11-5: `devicePixelRatio` and a 48 px button measured on screen (decides the dp assumption).

## Owner decisions (recommended default first)
- **D-U2-1** Target WCAG 2.2 AA where it applies to a phone app, plus 48 dp targets (Android guidance). Alternative: only F1, F2, F4, F5.
- **D-U2-2** Lighter borders (#6A6B74) on Android only. Alternative: also in the PC web app (then both `app.css` copies change).
- **D-U2-3** If A11-2 shows the WebView ignores the font size: set the text zoom from the system font scale. Alternative: leave it; pinch zoom is not available either (no zoom controls set).
- **D-U2-4** Toast time: keep 3.6 s. Alternative: longer for messages over one sentence.

## Risks
- The harness proves names, sizes and focus, not what TalkBack really says: A11-1 is the real test.
- F13 could be the largest problem and is the least known.
- Touching `header()` and the router affects every screen; the existing phone tests must still pass.

## Out of scope
Translations, a light theme, the PC web app (`src/reel_watcher/webapp/`), TalkBack custom actions, a visual redesign.
