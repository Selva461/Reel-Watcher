# A3: a prompt budget for the on-phone AI, and an evaluation that runs without a phone (design, not approved)

Base: `origin/ccr-d0c0b070-bdpssy` at 4de00d1 (Reel Shelf 1.3.11, versionCode 18), plus the A1 branch `stabilize/a1-retry-cap` and the A2-1 branch `stabilize/a2-1-model-catalog` where named. Planning only: no code was changed. Measurements were made on 2026-11-18 with Node 22 running the real `notes.js` (scratch script, generated placeholder text only).

## Problem
The notes prompt is built from fixed per-field character caps, with no idea of the model's context window. Its largest possible size is about 24,000 characters. The default model's file name says `ekv4096`, which suggests a 4,096-token window for prompt and answer together. At any plausible characters-per-token ratio for English, the largest prompt does not fit. What LiteRT-LM does then (an error, a silent cut, or garbage) is not known. Under A1 an error counts as a failed try, and the same reel fails the same way three times. There is also no repeatable way to check the answer format without a phone.

## Verified in code (file:line, what was read)
- **Prompt builder.** `Notes.localPrompt` (notes.js:178-192) joins: an intro line, `Link`, `Title`, `Creator`, the caption cut at 3,000 characters, the transcript passed through `condense(transcript, 7000)`, on-screen text cut at 2,000, comments cut at 2,500, an optional media sentence, the reel's typed text cut at 6,000, the `FORMAT` block, and `Also: <localExtra>`. The system text is `Notes.LOCAL_SYSTEM` (notes.js:27-31).
- **Stored caps upstream.** title 300 (local.js:292), caption 8,000 (local.js:294, 442, 453), transcript 40,000 (local.js:300, 330, 405, 469), on-screen 6,000 (local.js:404, 468), comments 6,000 (local.js:725, 854), typed text 10,000 (local.js:847), `localExtra` 2,000 (local.js:1258).
- **Call.** `writeWithPhoneAi` (local.js:501-511) sends the prompt with `maxTokens: settings.maxTokens` (default 800, local.js:131; choices 400, 800 and 1500, local.js:1208). Java clamps the answer length to between 64 and 3,000 (`Math.max(64, Math.min(maxTokens, 3000))`, LocalModel.java:200 and 203).
- **Context size.** `EngineConfig` is built with `maxNumTokens` left null in every branch (LocalModel.java:237, 248, 265, 275; the 5th argument, named `maxNumTokens` by `javap` on the cached `litertlm-android-0.19.0-api.jar`). So the window is whatever the model file sets. No context size is recorded anywhere: not in the page `MODELS` (local.js:120-130), not in `LocalModel`, not in A2-1's `ModelCatalog` (fields id, file, url, bytes, sha256). Qwen's 4,096 comes only from its file name: **NEEDS VERIFICATION**. Gemma 4 E2B and E4B: unknown, **NEEDS VERIFICATION**.
- **Media.** With a multimodal model and `media`, Java adds up to 4 key frames and a WAV of the first 30 s (LocalBridge.java:664-672, ReelVideo.java:205). These use context tokens too; how many is **NEEDS VERIFICATION**.
- **Token counts after the fact.** The 0.19.0 API jar has `Conversation.getTokenCount()` and `BenchmarkInfo.getLastPrefillTokenCount()` (read with `javap`). It exposes no tokenizer, so tokens cannot be counted before a call. What these two return on a phone is **NEEDS VERIFICATION**.
- **Failure path.** Any engine exception becomes "The AI model failed: ..." (LocalBridge.java:686-689). An answer `Notes.parse` rejects becomes "not in the notes format" (local.js:507). On the A1 branch both count as a try (`r.tries`, cap `Notes.RETRY_CAP = 3`, notes.js:201 there, local.js:602 there). `parse` (notes.js:85-121) needs at least two sections including TOPIC or POINTS. `setNotes` keeps the answer as `r.raw`, at most 20,000 characters (local.js:204). A failed answer's text is not kept.
- **Ask prompts.** `answerPrompt` (notes.js:636-641) takes 5 whole notes plus the question (`results.slice(0, 5)`, local.js:958). `webAnswerPrompt` (notes.js:644-651) takes 4 notes (`results.slice(0, 4)`, local.js:985) plus the web results. Neither has any cap.

## Measurements (Node 22, real notes.js, generated text; script `prompt.js` in the session scratchpad)

| Case | Characters |
|---|---|
| `FORMAT` block / `LOCAL_SYSTEM` | 1,020 / 471 |
| Largest `localPrompt` (every field at its stored cap, `localExtra` 2,000, media on) | 24,244 |
| Small prompt (300-character caption only) | 1,462 |
| Transcript section, 40,000-character punctuated transcript | 6,999 |
| Transcript section, 20,000 characters, one line, **no punctuation** | **0** (the "What is said (transcript):" header stays; its body is empty) |
| The same with a line break every 150 characters | 6,975 (the review measured 6,994 with its own spacing) |
| `answerPrompt`, question of 100 characters, 5 notes as in the fixture below | 20,544 |

The `answerPrompt` figure depends entirely on how big the notes are. It is the fixed instruction text, plus the question, plus, for each note, `[i] `, `Notes.format(note)` and a blank line. The fixture used is in `prompt.js`. Each note has a 10-word topic, 300-character intent and meaning, a 150-character tone, 12 points of 200 characters, 2 uses and a takeaway of 200 characters each, 2 tools and 8 tags. With sparser notes the review got 14,496.

The zero is a real bug. `sentences` splits only at `.!?` or line ends (notes.js:569-573). `condense` skips any sentence longer than the limit (notes.js:380-381). Measured on the real notes.js with Node 22: a text with no separator is returned unchanged up to 7,000 characters. At 7,001 characters and above it gives 0 characters (7,000 gives 7,000; 7,001 gives 0; 20,000 gives 0).

No page path writes typed or pasted text into `r.transcript`. Typed text goes to `r.extra` (local.js:847, `slice(0, 6000)`) and never passes through `condense`. The transcript comes only from YouTube (local.js:300, 330, through `joinCues`, which adds line breaks: notes.js:296-299) and from Vosk (local.js:405, 469, joined with ". ": ReelVideo.java:369-370). An unpunctuated transcript over 7,000 characters can therefore arrive in only two ways:
- a library imported or restored from elsewhere;
- a speech or caption result with no separator at all.

The fix stays in A3-2: it is cheap and right.

No tokenizer for Qwen or Gemma is in the repo or the caches (searched for `tokenizer*.json` and `~/.cache/huggingface`). Token counts below are therefore **estimates**: ASCII characters divided by 3, plus 2 tokens for every other code point. This is deliberately pessimistic; English often runs nearer 4 characters per token. **NEEDS VERIFICATION** by device check 2.

## Options
1. **Do nothing.** Short reels keep working. Long ones fail three times and park, or get notes from a silently cut prompt.
2. **Lower the fixed caps.** Simple, but blind to the model and the answer length, and it wastes context on short inputs.
3. **A budget per call (recommended).** Work out the tokens available (estimated) from the model's window, the answer length and the system text. Fill the prompt in a fixed priority order until the budget is used.
4. **Ask the engine to count tokens first.** Not possible: there is no tokenizer API in 0.19.0.

## The change (recommended: option 3; no data format change)
- **Budget, in tokens.** `Notes.promptBudget({ctx, answer, system, media})` returns a **token** count: `ctx - answer - estTokens(system) - media - margin`, where `answer = clamp(maxTokens, 64, 3000)`, exactly as Java clamps it. `ctx` is a per-model number in the page `MODELS` table, default 4096 for all three until device check 1 confirms or raises it. `margin` covers the chat template and is 5% of `ctx` (D-A3-3). `media` is a per-model reserve for 4 frames and 30 s of sound. It starts unset, and media prompts keep today's behaviour until device check 3 measures it (D-A3-4). Example for Qwen at "Normal" (800): 4096 - 800 - 157 - 205 = 2,934 tokens for the whole prompt (about 8,800 ASCII characters). At "Long" (1500): 2,234 tokens. Every fill decision is made with `estTokens`, never with a character count, so non-Latin text is measured by the same rule as the budget.
- **Order of filling.** The intro, link, title, creator, `FORMAT` and `localExtra` are kept first.
  - **Their largest size.** 3,617 characters, measured with a 300-character title, a 32-character creator name, a 2,000-character `localExtra` and the media sentence. In ASCII that is about 1,206 tokens and fits every budget above.
  - **In a non-Latin script it does not fit.** A 2,000-character `localExtra` plus a 300-character title is about 4,600 tokens by the estimator, over the whole 2,234-token "Long" budget.
  - **Rule when the always-kept part is over the budget.** First cut `localExtra` to what fits, at a word boundary, ending " [shortened]". Then cut the title the same way. The intro, link, creator, the media sentence (media prompts keep today's behaviour until device check 3, D-A3-4), `FORMAT` and the "Write notes in exactly this format" line are never cut. `FORMAT` alone is 1,020 ASCII characters, about 340 tokens. The run log then says "your extra instruction was shortened to fit the model".
  - **Then the sources.** In this order, each source takes the tokens that are left: typed text (yours, kept first), transcript, the first 1,000 characters of the caption, on-screen text, the rest of the caption, comments. So comments are cut first and your own typed text last (D-A3-2). A text that does not fit is cut at the last space before the limit and ends with " [shortened]". The transcript is cut with `condense` at its share.
- **Estimator.** `Notes.estTokens(text)` uses the rule stated above: ASCII characters divided by 3, plus 2 per other code point. It sizes and fills the budget and never blocks a reel.
- **`condense` fix.** When `condense` would return an empty string for a non-empty text, it falls back to the word-boundary cut instead. Every case that returns non-empty text today gives exactly the same output (tested).
- **Visible, not stored.** The run log line gets "(prompt shortened to fit the model)". The reel gets no new field (D-A3-1).
- **Calibration data.** `LocalBridge.generate` adds `tokens` (from `getTokenCount()`, or -1 when it throws) to the JSON it already returns. The page does not store it. Device check 2 reads it.
- **Ask prompts.** These use the same budget. Whole notes go in rank order until the budget is full; a note is never cut in the middle. The answer says "Used your top K notes" when K is under the number the screen asks for (5 for Ask, 4 with the web lookup).
- **Not changed.** The Meta AI prompt (`metaPrompt`, copied into the user's own chat app) is not the phone's model and keeps its 12,000 cap. The stored caps, the notes format, `parse` and the A1 retry rules stay as they are.

## Failure modes
| Case | Behaviour |
|---|---|
| Very long transcript, Qwen | Prompt fits the budget; notes from the best sentences; log says shortened |
| Text in a non-Latin script | The estimator counts 2 tokens per character, so the cut is deeper, not an overflow |
| The estimate is still too low on some phone | The engine error counts as an A1 try, as today; device check 2 exists to catch this |
| `ctx` set too high in `MODELS` | Same as today's behaviour for that model; the table-honesty test requires a device-check note beside each value |
| Model file picked by hand (unknown window) | Uses the smallest known `ctx` (4096) |

## Evaluation without a phone
- **Fixture.** `tests/fixtures/notes_eval/reels.json`, made by a deterministic generator (placeholder words, codes `EVAL001`.., no real reel data). About 12 reels: caption only; maximum of every field; a 40,000-character transcript; one with no punctuation; a YouTube one; cooking-shaped (STEPS); non-Latin generated text in every field; a non-Latin 2,000-character `localExtra` with a 300-character non-Latin title (the case where the always-kept part must be shortened); empty; an ASCII `localExtra` at 2,000. All have `caption_read: 1` and `video_tried: 1`, so a run reads nothing from the network.
- **Prompt checks** (`tests/test_notes_eval.py`, phone harness): for every reel, every model's `ctx` and each `maxTokens` choice, `estTokens(prompt) <= promptBudget(...)`, which is the same as `estTokens(system) + estTokens(prompt) + answer + media + margin <= ctx`. The non-Latin `localExtra` reel gets a shortened `localExtra` and the log line. `FORMAT` appears whole and once. Typed text survives whenever comments were cut. The prompt is the same on two builds of the same input. Three small reels have exact expected prompts, so any change is deliberate.
- **Answer checker** `checkAnswer(text)`, pure and deterministic, lives beside the test. Its verdicts: `parses` (`Notes.parse` not null); `sections` (TOPIC, at least 1 point, TAKEAWAY and at least 1 tag present); `complete` (a TAGS line exists, since TAGS is the last section of `FORMAT`, so an answer cut off by `maxTokens` fails); `no_echo` (none of the template phrases such as "one short line" or "2. ..."); `limits` (topic at most 200 characters, 1 to 40 points, 1 to 12 tags: the limits `parse` already enforces). The checker is tested on about 10 synthetic answers: good, bold-markdown headings, cut before TAGS, a refusal, the template echoed, prose only, a repeated loop.
- **On a real phone later (a documented procedure; no developer screen).** A script `tests/notes_eval.py make-backup` writes the fixture as an S4 backup ZIP (needs S4-3, PR #67). On a spare phone or a second Android user (recommended; D-A3-5): restore it, run "Write notes", then "Back up now". On the computer, `uv run python tests/notes_eval.py check <zip>` reads `reels.json`. It prints, per reel, the checker verdicts from `r.raw`, `status` and `last_fail`. Failed answers have no stored text, so only their reason is shown. Gemma's sight-and-sound path cannot be evaluated this way, because the fixture has no videos.

## Tests and deliberate breaks
Beyond the checks above: `condense` gives the same output as today on 1,000 generated texts that come out non-empty now. Breaks the tests must catch: remove the " [shortened]" cut (budget test fails); put comments before the transcript (order test); drop `FORMAT` when the budget is tight (format test); let `condense` return "" again (no-punctuation test); count 4 characters per token (non-Latin test); `checkAnswer` accepting an answer without TAGS (checker corpus).

## PR split (stacked; each passes `uv run pytest tests/test_phone_app.py tests/test_notes_eval.py` and CI `testReleaseUnitTest`)
1. **A3-1 eval harness only.** Fixture, generator, `checkAnswer`, prompt checks. The budget assertions are marked expected-fail until A3-2. Tests only; does not publish a release.
2. **A3-2 budget for notes.** `promptBudget`, `estTokens`, the fill order, the `condense` fix, `ctx` in `MODELS`, the run log text, `tokens` in the generate result.
3. **A3-3 budget for Ask.** Whole notes in rank order.
4. **A3-4 phone procedure.** `tests/notes_eval.py make-backup` and `check`, plus a section in `TESTING.md`.

## Device checks (owner; the AI ran only cloud tests)
1. With Qwen, Gemma 4 E2B and E4B: send a prompt of the budget size and one of twice the size. Note whether the larger one errors, cuts or answers. This confirms `ctx`.
2. Run the eval reels and note `tokens` against `estTokens` for each. The estimate must never be lower.
3. Gemma with media: note `tokens` with and without the 4 frames and the sound. That gives the media reserve.
4. A reel with a 40,000-character transcript writes notes on the first try, and the log says "shortened".

## Owner decisions (recommended default)
- **D-A3-1** Record a shortened prompt on the reel: no new field, log line only (recommended), or an optional `prompt_cut` field.
- **D-A3-2** What is cut first: comments, then the rest of the caption, then on-screen text, then the transcript, with your typed text last (recommended); or shrink all sources in proportion.
- **D-A3-3** Safety margin: 5% of the window (recommended) or none.
- **D-A3-4** Media prompts before device check 3: keep today's behaviour (recommended), or apply the text budget with a guessed reserve.
- **D-A3-5** Phone evaluation: a spare phone or a second Android user (recommended); or your own phone with "save a backup of the current library first" on and your backup restored afterwards.

## Out of scope
No cloud LLM, no API key, no mandatory download (the evaluation uses the model already on the phone). No change to the notes format, the Meta AI flow, model choice or sampling settings. Grading the content of notes for truth is not covered: `keepBacked` already filters unsupported points.

## Risks
- The estimator may be far too pessimistic for English, wasting context. Device check 2 lets a later PR raise the ratio, with evidence.
- A cut can drop the one sentence that mattered. The fill order keeps the transcript's best sentences and your own text.
- The budget prompt tests pin exact text, so harmless wording changes need the expected prompts updated.
