"""Notes evaluation harness for the on-phone AI (A3-1; design: docs/design/A3-prompt-budget.md).

It checks, without a phone and without a model, what the page sends the AI and how an answer can be judged:

* the synthetic fixture (tests/fixtures/notes_eval/reels.json, made by tests/notes_eval.py) and its generator;
* the prompt the page's own `Notes.localPrompt` builds for every fixture reel, as it is TODAY (sizes, caps, `condense`);
* `check_answer`, the deterministic answer checker, on good and bad synthetic answers;
* the designed prompt budget (`Notes.promptBudget`, `Notes.estTokens`, `ctx` in MODELS, the fill order, the `condense` fix),
  which does not exist yet. Those tests are `xfail(strict=True, reason="A3-2")`: they fail today, and when A3-2 builds the
  budget they pass, strict makes pytest fail on the unexpected pass, so A3-2 has to remove the marks.

Everything is generated placeholder text; no real reel data. The page is loaded the same way the other phone tests load it."""
import hashlib
import re
import subprocess
import sys

import pytest

import notes_eval as ne
from test_phone_app import phone, site  # noqa: F401  (pytest fixtures)

CASES = ne.cases()
BY_CODE = {c["reel"]["code"]: c for c in CASES}
A3_2 = pytest.mark.xfail(strict=True, reason="A3-2")

NON_LATIN = ("EVAL010", "EVAL011")

# The size, in characters, of the prompt `Notes.localPrompt(reel, localExtra)` builds for each fixture reel TODAY (UTF-16 units,
# as JavaScript counts them). The largest, EVAL004, has every field at the most the app stores. When A3-2 changes what
# localPrompt builds, a number here changes on purpose and is updated in the same commit.
PROMPT_CHARS_TODAY = {"EVAL001": 1492, "EVAL002": 5355, "EVAL003": 4192, "EVAL004": 24143, "EVAL005": 1421, "EVAL006": 1757,
                      "EVAL007": 8375, "yt-EVALyt00008": 5237, "EVAL009": 2586, "EVAL010": 8111, "EVAL011": 3909, "EVAL012": 1154}

LABELS = {"caption": "Caption:\n", "transcript": "What is said (transcript):\n", "onscreen": "Text shown on screen in the reel:\n",
          "comments": "Top comments from viewers:\n", "typed": "What the reel says (typed by me):\n"}
END = "Write notes in exactly this format:"


def prompts_today(pg):
    """{code: prompt} as the page's Notes.localPrompt builds them today (no budget)."""
    pg.open_with()
    out = pg.evaluate("(cs) => cs.map((c) => Notes.localPrompt(c.reel, c.localExtra, {}))", CASES)
    return {c["reel"]["code"]: p for c, p in zip(CASES, out)}


def sources_of(prompt):
    """How many characters of each source (caption, transcript, ...) a prompt carries, found by the labels of its sections."""
    marks = sorted((prompt.index(label), key, label) for key, label in LABELS.items() if label in prompt) + [(prompt.index(END), None, END)]
    sizes = dict.fromkeys(LABELS, 0)
    for (at, key, label), (nxt, _, _) in zip(marks, marks[1:]):
        sizes[key] = len(prompt[at + len(label):nxt].strip())
    return sizes


def body_of(prompt, key):
    at = prompt.index(LABELS[key]) + len(LABELS[key])
    nxt = [prompt.index(x, at) for x in [*LABELS.values(), END] if x in prompt[at:]]
    return prompt[at:min(nxt)].strip()


# ---------------------------------------------------------------- the fixture and its generator (no page)

def test_the_generator_makes_the_same_bytes_every_time():
    assert ne.fixture_bytes() == ne.fixture_bytes()
    assert ne.build_fixture() == ne.build_fixture()


def test_the_committed_fixture_is_exactly_what_the_generator_makes():
    committed = ne.FIXTURE.read_bytes().replace(b"\r\n", b"\n")  # Windows may check text files out with CRLF
    assert committed == ne.fixture_bytes(), "tests/fixtures/notes_eval/reels.json is out of date: run  python tests/notes_eval.py generate"


def test_another_python_process_makes_the_same_file(tmp_path):
    out = tmp_path / "reels.json"
    done = subprocess.run([sys.executable, str(ne.HERE / "notes_eval.py"), "generate", "--out", str(out)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert out.read_bytes() == ne.fixture_bytes()   # a fresh process has its own random string-hash seed: nothing depends on it


def test_the_fixture_holds_only_placeholders():
    text = ne.FIXTURE.read_text(encoding="utf-8")
    assert "instagram" not in text.lower() and "youtube" not in text.lower() and "@" not in text
    assert chr(0x2014) not in text   # no em dash anywhere
    for c in CASES:
        r = c["reel"]
        assert r["url"].startswith("https://example.invalid/"), r["code"]
        assert re.fullmatch(r"eval_creator_\d\d\w*|Eval Channel \d\d|", r["author"]), r["code"]
        assert r["caption_read"] == 1 and r["video_tried"] == 1, r["code"]   # a run on a phone reads nothing from the network


def _field(code, name):
    return BY_CODE[code]["reel"].get(name, "")


def _has_non_latin(s):
    return any(ord(ch) > 0x24F for ch in s)


def test_the_fixture_has_the_reels_the_design_asks_for():
    assert [c["reel"]["code"] for c in CASES] == list(PROMPT_CHARS_TODAY)
    texts = ("title", "caption", "transcript", "onscreen", "comments", "extra")
    # a short caption and nothing else
    assert 0 < len(_field("EVAL001", "caption")) <= 300 and not any(_field("EVAL001", k) for k in texts if k != "caption")
    # every field at the most the app stores, and the longest 'Also:' setting
    top = dict(title=300, caption=8000, transcript=40000, onscreen=6000, comments=6000, extra=10000)
    assert {k: len(_field("EVAL004", k)) for k in top} == top and len(BY_CODE["EVAL004"]["localExtra"]) == 2000
    assert BY_CODE["EVAL004"]["localExtra"].isascii() and len(_field("EVAL004", "author")) == 32
    # punctuated transcripts, and unpunctuated ones: one line of 7,001 and of 20,000, and 20,000 with line breaks
    assert ". " in _field("EVAL002", "transcript") and ". " in _field("EVAL004", "transcript")
    for code, n, lines in (("EVAL005", 7001, False), ("EVAL006", 20000, False), ("EVAL007", 20000, True)):
        t = _field(code, "transcript")
        assert len(t) == n and not re.search(r"[.!?]", t) and ("\n" in t) == lines, code
    # a long caption, comments, on-screen text
    assert len(_field("EVAL003", "caption")) == 8000 and _field("EVAL002", "comments") and _field("EVAL002", "onscreen")
    # a YouTube video, a cooking reel
    assert _field("yt-EVALyt00008", "code").startswith("yt-") and _field("yt-EVALyt00008", "title")
    assert "Ingredients\n- " in _field("EVAL009", "caption") and "Step 1." in _field("EVAL009", "transcript")
    # non-Latin text in every field, and the always-kept part (a 300-character title, a 2,000-character 'Also:') in a non-Latin script
    for k in texts:
        assert _has_non_latin(_field("EVAL010", k)) and not re.search("[A-Za-z]", _field("EVAL010", k)), k
    assert len(_field("EVAL011", "title")) == 300 and _has_non_latin(_field("EVAL011", "title"))
    assert len(BY_CODE["EVAL011"]["localExtra"]) == 2000 and _has_non_latin(BY_CODE["EVAL011"]["localExtra"])
    # an empty reel: only its link
    assert not any(_field("EVAL012", k) for k in (*texts, "author"))


# ---------------------------------------------------------------- the prompt TODAY, built by the page's own Notes.localPrompt

def test_every_fixture_prompt_is_built_by_the_real_builder_and_its_size_is_recorded(phone):
    prompts = prompts_today(phone)
    assert {code: len(p) for code, p in prompts.items()} == PROMPT_CHARS_TODAY
    assert prompts_today(phone) == prompts   # the same input gives the same prompt
    # the unbudgeted prompt is far beyond a 4,096-token window for the big reels (the reason for A3): about 24,000 characters
    assert max(len(p) for p in prompts.values()) > 24000 and len(prompts["EVAL004"]) == max(len(p) for p in prompts.values())


def test_format_is_whole_and_once_in_every_prompt_today(phone):
    prompts = prompts_today(phone)
    fmt = phone.evaluate("() => Notes.FORMAT")
    assert len(fmt) == 1020
    for code, p in prompts.items():
        extra = BY_CODE[code]["localExtra"].strip()
        assert p.count(fmt) == 1 and p.endswith("Also: " + extra if extra else fmt), code


def test_three_small_prompts_are_exactly_the_documented_text(phone):
    prompts = prompts_today(phone)
    fmt = phone.evaluate("() => Notes.FORMAT")
    tail = "Write notes in exactly this format:\n\n" + fmt
    intro = "Here is what could be read from an Instagram reel."
    a = BY_CODE["EVAL001"]["reel"]
    assert prompts["EVAL001"] == "\n\n".join([intro, f"Link: {a['url']}", f"Creator: @{a['author']}", "Caption:\n" + a["caption"], tail])
    e = BY_CODE["EVAL012"]["reel"]
    assert prompts["EVAL012"] == "\n\n".join([intro, f"Link: {e['url']}", tail])
    y = BY_CODE["yt-EVALyt00008"]["reel"]
    yt = "\n\n".join(["Here is a YouTube video (title, description and what is said in it).", f"Link: {y['url']}", f"Title: {y['title']}",
                      f"Creator: {y['author']}", "Description:\n" + y["caption"], "What is said (transcript):\n" + y["transcript"], tail])
    assert prompts["yt-EVALyt00008"] == yt
    # and the 'Also:' setting goes last, trimmed
    again = phone.evaluate("(r) => Notes.localPrompt(r, '  Answer in two lines.  ', {})", y)
    assert again == yt + "\n\nAlso: Answer in two lines."


def test_the_prompt_cuts_each_source_at_its_fixed_cap_today(phone):
    """The biggest reel, field by field. Today every source has a fixed cap and nothing looks at the model's window."""
    c = BY_CODE["EVAL004"]
    r = c["reel"]
    phone.open_with()
    prompt, said, media = phone.evaluate("([r, x]) => [Notes.localPrompt(r, x, {}), Notes.condense(r.transcript, 7000), Notes.localPrompt(r, x, { media: true })]",
                                         [r, c["localExtra"]])
    fmt = phone.evaluate("() => Notes.FORMAT")
    assert 6500 <= len(said) <= 7000   # 40,000 characters of sentences come out as about 7,000
    expected = "\n\n".join(["Here is what could be read from an Instagram reel.", f"Link: {r['url']}", f"Title: {r['title']}", f"Creator: @{r['author']}",
                            "Caption:\n" + r["caption"][:3000], "What is said (transcript):\n" + said,
                            "Text shown on screen in the reel:\n" + r["onscreen"][:2000], "Top comments from viewers:\n" + r["comments"][:2500],
                            "What the reel says (typed by me):\n" + r["extra"][:6000], "Write notes in exactly this format:\n\n" + fmt,
                            "Also: " + c["localExtra"].strip()])
    assert prompt == expected
    assert media == expected.replace("\n\nLink:", "\n\nYou also get pictures from the reel (key frames) and its first 30 seconds of sound: use them.\n\nLink:", 1)


# ---------------------------------------------------------------- condense, today and as it should be

def _condense(pg, items):
    pg.open_with()
    return pg.evaluate("(items) => items.map(([t, max]) => Notes.condense(t, max))", items)


def test_a_punctuated_long_transcript_is_cut_to_about_7000_in_its_original_order(phone):
    text = _field("EVAL004", "transcript")
    (out,) = _condense(phone, [[text, 7000]])
    assert len(text) == 40000 and 6500 <= len(out) <= 7000
    at = 0
    for line in out.split("\n"):   # whole sentences of the transcript, in the order they were said
        at = text.index(line, at) + len(line)
    # a transcript with line breaks every 150 characters and no punctuation is cut by its lines, also to about 7,000
    (broken,) = _condense(phone, [[_field("EVAL007", "transcript"), 7000]])
    assert 6300 <= len(broken) <= 7000


def test_condense_today_returns_nothing_for_a_long_text_with_no_separator(phone):
    """TODAY'S VALUE OF A BUG, pinned on purpose. A text with no sentence end and no line break is one 'sentence'; condense skips
    any sentence longer than the limit, so 7,001 characters and more give an empty string and the prompt's transcript section is
    empty. A3-2 fixes condense (designed: fall back to a cut at a word boundary). When it does, THIS TEST FAILS and must be
    deleted; the xfail test below, test_condense_gives_text_when_there_is_no_separator, then passes and loses its mark."""
    flat = _field("EVAL005", "transcript")
    sizes = [len(x) for x in _condense(phone, [[flat[:7000], 7000], [flat, 7000], [_field("EVAL006", "transcript"), 7000]])]
    assert sizes == [7000, 0, 0]   # 7,000 stays 7,000, 7,001 gives 0, 20,000 gives 0
    prompt = prompts_today(phone)["EVAL006"]
    assert "What is said (transcript):\n" in prompt and body_of(prompt, "transcript") == ""   # the header stays, its body is empty


# The outputs of condense for transcripts of the fixture at several limits, all of which give text today. A3-2 may only add text
# where today's answer is empty; every answer that is non-empty today must stay exactly as it is (design: "Tests and deliberate breaks").
CONDENSE_PINNED = [("EVAL002", 1000), ("EVAL002", 3000), ("EVAL004", 1000), ("EVAL004", 3000), ("EVAL004", 7000), ("EVAL007", 1000),
                   ("EVAL007", 3000), ("EVAL007", 7000), ("yt-EVALyt00008", 1000), ("yt-EVALyt00008", 3000), ("EVAL010", 1000),
                   ("EVAL010", 3000), ("EVAL010", 7000)]
CONDENSE_PINNED_SHA256 = "3bc036ee5cc2b4114baf1a8ea9ae3a00184e1ae209430fe56d07112726900d65"


def test_condense_output_that_is_not_empty_today_is_pinned(phone):
    outs = _condense(phone, [[_field(code, "transcript"), m] for code, m in CONDENSE_PINNED])
    assert all(outs) and all(len(o) <= m for o, (_, m) in zip(outs, CONDENSE_PINNED))
    assert hashlib.sha256("\x00".join(outs).encode("utf-8")).hexdigest() == CONDENSE_PINNED_SHA256


@A3_2
def test_condense_gives_text_when_there_is_no_separator(phone):
    flat = _field("EVAL005", "transcript")
    got = _condense(phone, [[flat, 7000], [_field("EVAL006", "transcript"), 7000]])
    for out, text in zip(got, (flat, _field("EVAL006", "transcript"))):
        body = re.sub(r" \[shortened\]$", "", out)
        assert 0 < len(out) <= 7000 and text.startswith(body), f"condense gave {len(out)} characters for {len(text)}"


@A3_2
def test_a_long_unpunctuated_transcript_still_reaches_the_prompt(phone):
    prompts = prompts_today(phone)
    for code in ("EVAL005", "EVAL006"):
        body = re.sub(r" \[shortened\]$", "", body_of(prompts[code], "transcript"))
        assert body, f"{code}: the transcript section of the prompt is empty"
        assert _field(code, "transcript").startswith(body), f"{code}: the transcript section is not the start of the transcript"


# ---------------------------------------------------------------- the answer checker

def _compose(parts, order=None, bold=False):
    """An answer in the notes format. A section whose value is None is left out; a list is one point per line (ingredients with a dash)."""
    out = []
    for name in order or ne.SECTIONS:
        value = parts.get(name)
        if value is None:
            continue
        head = f"**{name}:**" if bold else f"{name}:"
        if isinstance(value, list):
            out += [head, *[("- " if name == "INGREDIENTS" else f"{i}. ") + p for i, p in enumerate(value, 1)]]
        else:
            out.append(f"{head} {value}".rstrip())
    return "\n".join(out)


PARTS = {"TOPIC": "Keeping a small plan on one page", "INTENT": "Show that a short plan gets followed more often than a long one.",
         "TONE": "Sincere and practical.",
         "POINTS": ["Write the whole plan on one page", "Cut every step that has no owner", "Review the page once a week"],
         "MEANING": "A plan that is short enough to read is a plan that gets used.", "USE IT FOR": "Planning a small project or a week of work.",
         "TOOLS": "none", "PRODUCTS": "none", "TAKEAWAY": "Keep the plan short enough to follow.", "TAGS": "planning, focus, habits"}
GOOD = _compose(PARTS)
TOPIC_200 = ("abcdefghi " * 21)[:199] + "z"


def _with(**over):
    return _compose({**PARTS, **over})


def _non_latin():
    w = ne.Writer(ne.Rng(7), ne.CYRILLIC)
    return _compose({"TOPIC": w.sentence(), "POINTS": [w.sentence() for _ in range(3)], "MEANING": w.sentence(), "USE IT FOR": w.sentence(),
                     "TOOLS": "none", "TAKEAWAY": w.sentence(), "TAGS": ", ".join(w.word() for _ in range(4))})


# name: (builder(template) -> answer text, the rules it must break; none for a good answer). An answer that is not complete
# breaks "limits" too, because a missing tag is outside the 1 to 12 the limits ask for.
CORPUS = {
    "good": (lambda t: GOOD, ()),
    "good_bold_headings": (lambda t: _compose(PARTS, bold=True), ()),
    "good_with_a_greeting": (lambda t: "Here are the notes:\n\n" + GOOD, ()),
    "good_cooking": (lambda t: _with(INGREDIENTS=["2 cups flour", "1 cup milk"], STEPS=["Mix them", "Bake it"]), ()),
    "good_non_latin": (lambda t: _non_latin(), ()),
    "good_topic_of_200_characters": (lambda t: _with(TOPIC=TOPIC_200), ()),
    "good_40_points": (lambda t: _with(POINTS=[f"Point {i}" for i in range(40)]), ()),
    "good_12_tags": (lambda t: _with(TAGS=", ".join(f"tag{i}" for i in range(12))), ()),
    "cut_before_tags": (lambda t: GOOD[:GOOD.index("TAGS:")], ("sections", "complete", "limits")),
    "cut_right_after_the_tags_heading": (lambda t: GOOD[:GOOD.index("TAGS:") + len("TAGS:")], ("sections", "complete", "limits")),
    "cut_inside_the_points": (lambda t: GOOD[:GOOD.index("2. Cut every") + len("2. Cut ev")], ("sections", "complete", "limits")),
    "missing_tags_line": (lambda t: _with(TAGS=None), ("sections", "complete", "limits")),
    "missing_takeaway": (lambda t: _with(TAKEAWAY=None), ("sections",)),
    "missing_topic": (lambda t: _with(TOPIC=None), ("sections",)),
    "missing_points": (lambda t: _with(POINTS=None), ("sections", "limits")),
    "tags_before_takeaway": (lambda t: _compose(PARTS, order=[n for n in ne.SECTIONS if n not in ("TAKEAWAY", "TAGS")] + ["TAGS", "TAKEAWAY"]), ("complete", "order")),
    "points_before_topic": (lambda t: _compose(PARTS, order=["POINTS"] + [n for n in ne.SECTIONS if n != "POINTS"]), ("order",)),
    "the_answer_written_twice": (lambda t: GOOD + "\n\n" + GOOD, ("order",)),
    "topic_of_201_characters": (lambda t: _with(TOPIC=TOPIC_200 + "z"), ("limits",)),
    "41_points": (lambda t: _with(POINTS=[f"Point {i}" for i in range(41)]), ("limits",)),
    "13_tags": (lambda t: _with(TAGS=", ".join(f"tag{i}" for i in range(13))), ("limits",)),
    "a_loop_of_one_point_until_it_was_cut_off": (lambda t: GOOD[:GOOD.index("MEANING:")] + "\n".join(f"{i}. Review the page once a week" for i in range(4, 80)),
                                                 ("sections", "complete", "limits")),
    "the_template_echoed": (lambda t: t, ("no_echo",)),
    "the_tags_line_of_the_template_echoed": (lambda t: _with(TAGS="5 to 8 short tags, separated by commas"), ("no_echo",)),
    "a_numbered_placeholder_point": (lambda t: _with(POINTS=["Write the whole plan on one page", "...", "Review the page once a week"]), ("no_echo",)),
    "a_refusal": (lambda t: "I'm sorry, but I can't help with that request.", ("parses", "sections", "complete", "limits")),
    "prose_only": (lambda t: "This reel is about keeping a plan short. The creator says to cut every step that has no owner.",
                   ("parses", "sections", "complete", "limits")),
    "an_empty_answer": (lambda t: "", ("parses", "sections", "complete", "limits")),
}


def _verdicts(pg):
    """check_answer for the whole corpus, with the page's own parser and FORMAT."""
    pg.open_with()
    template = pg.evaluate("() => Notes.FORMAT")
    texts = {name: build(template) for name, (build, _) in CORPUS.items()}
    parsed = dict(zip(texts, pg.evaluate("(ts) => ts.map((t) => Notes.parse(t))", list(texts.values()))))
    return {name: ne.check_answer(text, lambda _t, n=name: parsed[n], template) for name, text in texts.items()}


@pytest.mark.parametrize("rule", ne.RULES)
def test_each_checker_rule_passes_and_fails_the_right_answers(phone, rule):
    got = _verdicts(phone)
    wrong = {name: got[name][rule] for name, (_, breaks) in CORPUS.items() if got[name][rule] != (rule not in breaks)}
    assert not wrong, f"rule {rule}: these answers got the wrong verdict (shown: the verdict they got): {wrong}"


def test_the_checker_accepts_good_answers_rejects_bad_ones_and_is_deterministic(phone):
    got = _verdicts(phone)
    assert {name: ne.failed(v) for name, v in got.items()} == {name: list(breaks) for name, (_, breaks) in CORPUS.items()}
    assert {name for name, v in got.items() if v["ok"]} == {name for name, (_, breaks) in CORPUS.items() if not breaks}
    again = _verdicts(phone)
    assert again == got   # the same answers give the same verdicts
    assert sum(1 for name in CORPUS if name.startswith("good")) >= 8 and sum(1 for _, b in CORPUS.values() if b) >= 15


def test_the_template_is_found_as_an_echo_even_in_pieces():
    template = "TOPIC: one short line\nPOINTS:\n1. every useful point in the order it comes\n2. ...\nTAGS: 5 to 8 short tags, separated by commas"
    assert ne.echoes(template, template)
    assert ne.echoes("TOPIC: x\nPOINTS:\n1. a\n2. ...\nTAGS: a, b", template)
    assert ne.echoes(GOOD.replace("Cut every step that has no owner", "every useful point in the order it comes"), template)
    assert not ne.echoes(GOOD, template)


# ---------------------------------------------------------------- the designed budget (A3-2): expected to fail until it exists

# The designed API, in one place. The design fixes promptBudget({ctx, answer, system, media}) (tokens) and estTokens(text), and says
# the fill uses the budget; it does not fix how the budget reaches localPrompt. Assumed here: localPrompt(reel, extra, { budget }),
# budget in tokens. If A3-2 passes it another way, change only SEAM_JS: every test below builds its prompts through it.
SEAM_JS = "const promptWith = (c, budget) => Notes.localPrompt(c.reel, c.localExtra, { budget });"
BUDGETED_JS = "(cs) => {" + SEAM_JS + r"""
  const out = [];
  for (const c of cs) for (const m of MODELS) for (const answer of [400, 800, 1500]) {
    const budget = Notes.promptBudget({ ctx: m.ctx, answer, system: Notes.LOCAL_SYSTEM });
    const prompt = promptWith(c, budget);
    out.push({ code: c.reel.code, model: m.id, ctx: m.ctx, answer, budget, tokens: Notes.estTokens(prompt), chars: prompt.length });
  }
  return out;
}"""
ONE_PROMPT_JS = "([c, ctx, answer]) => {" + SEAM_JS + r"""
  const budget = Notes.promptBudget({ ctx, answer, system: Notes.LOCAL_SYSTEM });
  return { budget, prompt: promptWith(c, budget), format: Notes.FORMAT };
}"""
SWEEP_JS = "([c, budgets]) => {" + SEAM_JS + " return budgets.map((b) => promptWith(c, b)); }"


def _need_budget_api(pg):
    pg.open_with()
    kinds = pg.evaluate("() => [typeof Notes.promptBudget, typeof Notes.estTokens]")
    assert kinds == ["function", "function"], f"Notes.promptBudget and Notes.estTokens do not exist yet (typeof: {kinds})"


def _fit(pg, codes):
    _need_budget_api(pg)
    rows = [r for r in pg.evaluate(BUDGETED_JS, [BY_CODE[c] for c in codes]) if r["tokens"] > r["budget"]]
    assert not rows, f"{len(rows)} prompts over budget, for example: " + "; ".join(
        f"{r['code']} on {r['model']} with answer {r['answer']}: {r['tokens']} tokens, budget {r['budget']}" for r in rows[:4])


@A3_2
def test_every_model_states_its_context_window_and_the_budget_functions_exist(phone):
    _need_budget_api(phone)
    ctx = phone.evaluate("() => MODELS.map((m) => m.ctx)")
    assert len(ctx) == 3 and all(isinstance(x, int) and x > 0 for x in ctx), f"ctx per model: {ctx}"


@A3_2
def test_est_tokens_counts_ascii_by_three_and_every_other_letter_by_two(phone):
    _need_budget_api(phone)
    got = phone.evaluate("(ts) => ts.map((t) => Notes.estTokens(t))", ["", "a" * 300, "я" * 100, "abc" + "яя", "a" * 471])
    assert got == [0, 100, 200, 5, 157]
    assert phone.evaluate("() => Notes.estTokens(Notes.LOCAL_SYSTEM)") == 157   # the design's example: 471 characters, 157 tokens


@A3_2
def test_the_budget_is_the_window_less_the_answer_the_system_text_and_the_margin(phone):
    _need_budget_api(phone)
    # the design's own examples for Qwen (window 4,096): 4096 - 800 - 157 - 205 = 2,934 at Normal, 2,234 at Long
    got = phone.evaluate("""() => [[400, 0], [800, 0], [1500, 0], [800, 100]].map(([answer, media]) =>
      Notes.promptBudget({ ctx: 4096, answer, system: Notes.LOCAL_SYSTEM, media }))""")
    assert got == [3334, 2934, 2234, 2834]


@A3_2
def test_every_latin_fixture_prompt_fits_the_budget_of_every_model_at_every_answer_length(phone):
    _fit(phone, [c for c in PROMPT_CHARS_TODAY if c not in NON_LATIN])


@A3_2
def test_every_non_latin_fixture_prompt_fits_the_budget_too(phone):
    _fit(phone, NON_LATIN)


@A3_2
def test_a_non_latin_extra_too_long_for_the_budget_is_shortened_and_marked(phone):
    _need_budget_api(phone)
    got = phone.evaluate(ONE_PROMPT_JS, [BY_CODE["EVAL011"], 4096, 1500])
    prompt = got["prompt"]
    assert prompt.endswith(" [shortened]"), "the 'Also:' text (last in the prompt) must end with ' [shortened]'"
    extra = BY_CODE["EVAL011"]["localExtra"]
    assert "Also: " + extra[:60] in prompt and extra not in prompt


@A3_2
def test_format_and_the_start_of_the_prompt_stay_whole_when_the_budget_is_tight(phone):
    _need_budget_api(phone)
    for code in PROMPT_CHARS_TODAY:
        got = phone.evaluate(ONE_PROMPT_JS, [BY_CODE[code], 4096, 1500])
        r = BY_CODE[code]["reel"]
        assert got["prompt"].count(got["format"]) == 1, code
        assert r["url"] in got["prompt"] and (not r["author"] or r["author"] in got["prompt"]), code


@A3_2
def test_comments_are_cut_first_and_your_typed_text_last(phone):
    """Sweep the budget down on the reel that has every source. A source is full, cut, or absent. Comments are cut before any
    other source is touched; typed text is cut only when nothing else is left."""
    _need_budget_api(phone)
    c = BY_CODE["EVAL004"]
    budgets = [10 ** 6, *range(9000, 1249, -50)]
    prompts = phone.evaluate(SWEEP_JS, [c, budgets])
    full = sources_of(prompts[0])
    assert all(full.values()), full
    cut_comments_first = typed_cut_alone = False
    for b, p in zip(budgets, prompts):
        got = sources_of(p)
        state = {k: "absent" if not got[k] else "full" if got[k] >= full[k] else "cut" for k in LABELS}
        others = [k for k in LABELS if k not in ("comments", "typed")]
        if any(state[k] != "full" for k in others + ["typed"]):
            assert state["comments"] != "full", f"budget {b}: a source was cut while the comments were whole: {state}"
        if state["typed"] != "full":
            assert all(state[k] == "absent" for k in LABELS if k != "typed"), f"budget {b}: typed text was cut while others remained: {state}"
            typed_cut_alone = True
        if state["comments"] != "full" and all(state[k] == "full" for k in LABELS if k != "comments"):
            cut_comments_first = True
    assert cut_comments_first and typed_cut_alone, "the sweep never reached both ends of the order"


@A3_2
def test_a_cut_text_ends_with_shortened_at_a_word_boundary(phone):
    _need_budget_api(phone)
    c = BY_CODE["EVAL003"]
    (prompt,) = phone.evaluate(SWEEP_JS, [c, [900]])
    body = body_of(prompt, "caption")
    assert body.endswith(" [shortened]")
    cut = body[: -len(" [shortened]")]
    caption = c["reel"]["caption"]
    assert 0 < len(cut) < len(caption) and caption.startswith(cut) and caption[len(cut)].isspace()
