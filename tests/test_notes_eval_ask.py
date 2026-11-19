"""Evaluation of the Ask prompts for the on-phone AI (A3-3; design: docs/design/A3-prompt-budget.md, "Ask prompts" and "PR split" item 3).

The notes prompt got its token budget in A3-2 (tests/test_notes_eval.py). Here the Ask prompts get the same budget, without a phone and
without a model, in this order:

* a frozen copy of the Ask builders as they were before the budget: a prompt that fits is byte for byte the old one (400 generated
  questions with note sets and web results);
* an independent oracle written in Python (its own token estimate, its own cut of the question) that says exactly what a prompt over its
  budget must be: the instructions kept, the question cut only when it does not fit, whole notes in rank order while they fit, the last
  ones left out, the web results after them in what is left;
* the rules one at a time: nothing cut in the middle of a note, non-Latin text counted by tokens, absurd budgets;
* the Ask screen with the fake bridge: the prompt it sends is within budget and the page says what was left out; nothing is stored;
* `metaPrompt`, the batch prompt and the notes prompt are what they were.

Everything is generated placeholder text; no real reel data."""
import hashlib
import json
import math
import re

import pytest

import notes_eval as ne
from test_notes_eval import CASES, GOOD, _non_latin, _with
from test_phone_app import db_of, phone, site  # noqa: F401  (phone, site: pytest fixtures)

# ---------------------------------------------------------------- what the Ask prompts say (a frozen copy; a wording change is deliberate)

ASK_HEAD = ("Answer my question using only my notes below (from reels I watched). Be specific: give the steps, names, numbers "
            "and tools from the notes. After each fact, write the note number like [1]. If the notes do not answer it, say so.\n\n")
WEB_HEAD = ("Answer my question briefly and accurately. Use my notes first; use the web results only for what my notes do not "
            "cover. After each fact, write where it came from, like [1] or [W1]. A fact from the web needs two web results that both "
            "say it: cite both, like [W1][W2]. If only one says it, still cite it. If neither answers it, say so; do not guess.\n\n")
ASK_SYSTEM = "You answer only from the notes you are given, briefly, citing them like [1]."
WEB_ASK_SYSTEM = "You answer only from the notes and web results you are given, briefly, citing them like [1] or [W1]."
SHORT = " [shortened]"


def ask_text(q, notes, found=()):
    return ASK_HEAD + f"Question: {q}\n\nMy notes:\n\n" + "\n\n".join(notes)


def web_text(q, notes, found):
    mine = "My notes:\n\n" + "\n\n".join(notes) + "\n\n" if notes else ""
    return WEB_HEAD + f"Question: {q}\n\n" + mine + "Web results:\n\n" + "\n\n".join(found)


TEXT = {"ask": ask_text, "web": web_text}
SYSTEM = {"ask": ASK_SYSTEM, "web": WEB_ASK_SYSTEM}

# The builders as they were in A3-2 (and before), copied verbatim: what a prompt that fits must still be.
OLD_JS = r"""
const oldAnswer = (question, results) => {
  const src = results.map((x, i) => `[${i + 1}] ${Notes.format(x.reel.notes || {}) || (x.reel.caption || "").slice(0, 800)}`).join("\n\n");
  return `Answer my question using only my notes below (from reels I watched). Be specific: give the steps, names, numbers ` +
    `and tools from the notes. After each fact, write the note number like [1]. If the notes do not answer it, say so.\n\n` +
    `Question: ${question}\n\nMy notes:\n\n${src}`;
};
const oldWeb = (question, results, web) => {
  const notes = results.map((x, i) => `[${i + 1}] ${Notes.format(x.reel.notes || {}) || (x.reel.caption || "").slice(0, 800)}`).join("\n\n");
  const found = web.map((w, i) => `[W${i + 1}] ${w.title} (${w.source}): ${w.text}`).join("\n\n");
  return `Answer my question briefly and accurately. Use my notes first; use the web results only for what my notes do not ` +
    `cover. After each fact, write where it came from, like [1] or [W1]. A fact from the web needs two web results that both ` +
    `say it: cite both, like [W1][W2]. If only one says it, still cite it. If neither answers it, say so; do not guess.\n\n` +
    `Question: ${question}\n\n${notes ? `My notes:\n\n${notes}\n\n` : ""}Web results:\n\n${found}`;
};
"""


# ---------------------------------------------------------------- the oracle (Python; nothing of it is shared with the page)

def counts(text):
    ascii_ = sum(1 for ch in text if ord(ch) < 128)
    return ascii_, len(text) - ascii_


def est(text):
    """The design's estimate: ASCII characters / 3 (rounded up) plus 2 for every other character."""
    a, o = counts(text)
    return -(-a // 3) + 2 * o


def budget_for(ctx, answer, system):
    """promptBudget: the window less the answer (clamped 64..3000), the system text and 5% of the window; never below 0."""
    return max(0, ctx - min(max(answer, 64), 3000) - est(system) - math.ceil(ctx / 20))


def cut_start(text, fits):
    """The longest start of `text` that `fits(ASCII count, other count)` allows, cut back to a word, ending ' [shortened]'; '' when
    not even one character fits."""
    a = o = end = 0
    space = -1
    for ch in text:
        na, no = a + (ord(ch) < 128), o + (ord(ch) >= 128)
        if not fits(na, no):
            break
        a, o = na, no
        if re.fullmatch(r"\s", ch):
            space = end
        end += 1
    if end < len(text) and re.fullmatch(r"\s", text[end]):
        space = end
    body = text[: space if space > 0 else end].rstrip()
    return body + SHORT if body else ""


def fill(kind, q, notes, found, budget):
    """What the prompt must be for `budget` tokens (None: no limit): (prompt, notes in, web results in, question cut)."""
    text = TEXT[kind]
    found = found if kind == "web" else []
    full = text(q, notes, found)
    if budget is None or est(full) <= budget:
        return full, len(notes), len(found), False
    q2 = q
    if est(text(q, [], [])) > budget:
        a0, o0 = counts(text("", [], []))
        ma, mo = counts(SHORT)
        q2 = cut_start(q, lambda a, o: -(-(a0 + ma + a) // 3) + 2 * (o0 + mo + o) <= budget) or q   # no room at all: the question stays whole
    n = max([k for k in range(len(notes) + 1) if est(text(q2, notes[:k], [])) <= budget] or [0])
    w = max([j for j in range(len(found) + 1) if est(text(q2, notes[:n], found[:j])) <= budget] or [0])
    return text(q2, notes[:n], found[:w]), n, w, q2 != q


# ---------------------------------------------------------------- generated notes, questions and web results

CJK = ["日本", "語文", "中国", "漢字", "学習", "動画", "保存", "検索", "質問", "回答", "要点", "道具"]
SIZES = {"tiny": (1, 30), "small": (3, 70), "medium": (6, 140), "large": (12, 200), "huge": (40, 400)}   # (points, characters per point)


def make_note(w, size):
    points, plen = SIZES[size]
    return {"topic": w.title(30 + w.rng.below(60)), "intent": w.prose(plen + 60), "tone": w.prose(60), "points": [w.prose(plen) for _ in range(points)],
            "meaning": w.prose(plen + 60), "use": [w.prose(plen) for _ in range(1 + w.rng.below(2))], "tools": [w.word(), w.word()],
            "takeaway": w.prose(plen), "tags": [w.word() for _ in range(6)]}


def make_question(w, rng):
    kind = rng.below(10)
    if kind < 5:
        return " ".join(w.word() for _ in range(3 + rng.below(8))) + "?"
    if kind == 5:
        return w.prose(250)
    if kind == 6:
        return w.prose(3000, joint="\n")        # longer than any budget below a window of about 4,000 tokens
    if kind == 7:
        return "".join(w.word() for _ in range(300))[:1500]   # one long word: no space to cut at
    if kind == 8:
        return w.word() + "\n" + w.word() + " " + w.word()
    return ""


def make_cases(count=420, seed=33):
    rng = ne.Rng(seed)
    scripts = [ne.LATIN] * 5 + [ne.CYRILLIC, CJK]
    sizes = ["tiny"] * 2 + ["small"] * 3 + ["medium"] * 3 + ["large"] * 2
    cases = []
    for i in range(count):
        w = ne.Writer(ne.Rng(seed * 7919 + i), scripts[rng.below(len(scripts))])
        notes = []
        for j in range(rng.below(9)):
            reel = {"code": f"ASK{i:03d}x{j}", "url": f"https://example.invalid/reel/ASK{i:03d}x{j}/"}
            kind = rng.below(10)
            if kind < 7:
                reel["notes"], reel["caption"] = make_note(w, sizes[rng.below(len(sizes))]), w.prose(200)
            elif kind == 7:
                reel["caption"] = w.prose(1500)      # no notes yet (the old builder would cut the caption at 800, but never gets to)
            elif kind == 8:
                reel["notes"] = {}
            notes.append(reel)
        web = [{"title": w.title(20 + rng.below(30)), "source": ("Wikipedia", "DuckDuckGo")[rng.below(2)], "text": w.prose(50 + rng.below(1150)),
                "url": f"https://example.invalid/w/{i}/{j}"} for j in range(rng.below(6))]
        cases.append({"q": make_question(w, rng), "notes": notes, "web": web})
    return cases


GENERATED = make_cases()

TEXTS_JS = r"""(cases) => cases.map((c) => ({
  notes: c.notes.map((reel, i) => `[${i + 1}] ${Notes.format(reel.notes || {}) || (reel.caption || "").slice(0, 800)}`),
  found: c.web.map((w, i) => `[W${i + 1}] ${w.title} (${w.source}): ${w.text}`) }))"""

RUN_JS = r"""([cases, budgets]) => cases.map((c, k) => {
  const res = c.notes.map((reel) => ({ reel }));
  return budgets[k].map((b) => { const a = Notes.answerPromptInfo(c.q, res, { budget: b }), w = Notes.webAnswerPromptInfo(c.q, res, c.web, { budget: b });
    return { b, ask: { ...a, tokens: Notes.estTokens(a.prompt) }, web: { ...w, tokens: Notes.estTokens(w.prompt) } }; }); })"""


def run_cases(pg, cases, budgets_of):
    """Run the page's budgeted builders for every case at the budgets `budgets_of(ask tokens, web tokens)` names. One row per
    (case, kind, budget): the case, what the page gave, and the oracle's answer for it."""
    pg.open_with()
    texts = pg.evaluate(TEXTS_JS, cases)
    budgets = []
    for c, t in zip(cases, texts):
        ta, tw = est(ask_text(c["q"], t["notes"])), est(web_text(c["q"], t["notes"], t["found"]))
        budgets.append(sorted(set(budgets_of(ta, tw))))
    got = pg.evaluate(RUN_JS, [cases, budgets])
    rows = []
    for k, (c, t, per) in enumerate(zip(cases, texts, got)):
        for r in per:
            for kind in ("ask", "web"):
                rows.append({"k": k, "case": c, "kind": kind, "budget": r["b"], "got": r[kind], "notes": t["notes"], "found": t["found"],
                             "want": fill(kind, c["q"], t["notes"], t["found"], r["b"])})
    return rows


def spread(ta, tw):
    return [tw, ta, ta - 1, int(tw * 0.85), int(tw * 0.6), int(tw * 0.35), int(tw * 0.15)]


_ROWS = {}


def rows_of(pg):
    """The oracle rows for every third generated case (about 140 cases at 7 budgets), made once for the tests below."""
    if "rows" not in _ROWS:
        _ROWS["rows"] = run_cases(pg, GENERATED[::3], spread)
    return _ROWS["rows"]


def shown(row):
    return f"case {row['k']} {row['kind']} at budget {row['budget']}"


def question_of(prompt, kind):
    """The question as it stands in an Ask prompt."""
    body = prompt[len(ASK_HEAD if kind == "ask" else WEB_HEAD) + len("Question: "):]
    return body[: min(i for i in (body.find("\n\nMy notes:\n\n"), body.find("\n\nWeb results:\n\n")) if i >= 0)]


def cut_at_a_word(q, shown_question):
    """True when `shown_question` is the start of `q` cut at a word (or, in text with no space at all, where the limit fell) and
    ends with ' [shortened]'."""
    if not shown_question.endswith(SHORT):
        return False
    body = shown_question[: -len(SHORT)]
    return bool(body) and q.startswith(body) and (q[len(body):][:1].isspace() or not re.search(r"\s", body))


# ---------------------------------------------------------------- the page's own builders are a frozen copy's equal when the prompt fits

def test_the_ask_texts_and_system_texts_are_the_documented_ones(phone):
    phone.open_with()
    assert phone.evaluate("() => [Notes.ASK_SYSTEM, Notes.WEB_ASK_SYSTEM]") == [ASK_SYSTEM, WEB_ASK_SYSTEM]
    reels = [{"reel": {"notes": {"topic": "A", "points": ["p"], "tags": ["t"]}}}, {"reel": {"caption": "c" * 900}}, {"reel": {}}]
    web = [{"title": "T", "source": "Wikipedia", "text": "x"}]
    notes = phone.evaluate("(rs) => rs.map((x, i) => `[${i + 1}] ${Notes.format(x.reel.notes || {}) || (x.reel.caption || '').slice(0, 800)}`)", reels)
    # a reel with no notes gets the empty notes template, not its caption: `format({})` is never empty, so the old builder's caption
    # fallback (the first 800 characters) never runs. That is how it was; the budget keeps it (a prompt that fits is unchanged).
    empty = "TOPIC: \nPOINTS:\nMEANING: \nUSE IT FOR: \nTOOLS: none\nTAKEAWAY: \nTAGS: "
    assert notes[0].startswith("[1] TOPIC: A\nPOINTS:\n1. p\n") and notes[1] == "[2] " + empty and notes[2] == "[3] " + empty
    assert phone.evaluate("([q, rs]) => Notes.answerPrompt(q, rs)", ["Why?", reels]) == ask_text("Why?", notes)
    assert phone.evaluate("([q, rs, w]) => Notes.webAnswerPrompt(q, rs, w)", ["Why?", reels, web]) == web_text("Why?", notes, ["[W1] T (Wikipedia): x"])
    assert phone.evaluate("([q, w]) => Notes.webAnswerPrompt(q, [], w)", ["Why?", web]) == web_text("Why?", [], ["[W1] T (Wikipedia): x"])
    assert "My notes:" not in web_text("Why?", [], ["[W1] T (Wikipedia): x"])   # with no notes the web prompt has no notes section
    # and with a budget that fits, the same
    assert phone.evaluate("([q, rs]) => Notes.answerPromptInfo(q, rs, { budget: 100000 }).prompt", ["Why?", reels]) == ask_text("Why?", notes)


DIFF_JS = "(cases) => {" + OLD_JS + r"""
  const budgets0 = [];
  for (const m of MODELS) for (const answer of [400, 800, 1500]) for (const system of [Notes.ASK_SYSTEM, Notes.WEB_ASK_SYSTEM])
    budgets0.push(Notes.promptBudget({ ctx: m.ctx, answer, system }));
  const out = { plain: 0, fits: 0, over: 0, bad: [] };
  cases.forEach((c, k) => {
    const res = c.notes.map((reel) => ({ reel }));
    const oa = oldAnswer(c.q, res), ow = oldWeb(c.q, res, c.web);
    if (Notes.answerPrompt(c.q, res) !== oa || Notes.webAnswerPrompt(c.q, res, c.web) !== ow) out.bad.push(["the plain builder changed", k]); else out.plain++;
    for (const [kind, old, build] of [["ask", oa, (b) => Notes.answerPromptInfo(c.q, res, { budget: b })],
                                      ["web", ow, (b) => Notes.webAnswerPromptInfo(c.q, res, c.web, { budget: b })]]) {
      const t = Notes.estTokens(old);
      for (const b of [...budgets0, t, t + 1, t * 2, t - 1]) {   // t is the very edge: exactly fits; t - 1 does not
        const i = build(b);
        if (t <= b) {
          out.fits++;
          if (i.prompt !== old || i.used !== res.length || i.webUsed !== (kind === "web" ? c.web.length : 0) || i.questionCut) out.bad.push(["a prompt that fits changed", kind, k, b, t]);
        } else {
          out.over++;   // something can be left out (a note or a web result) or the question cut: the prompt must differ
          if (i.prompt === old && (res.length || (kind === "web" && c.web.length))) out.bad.push(["over budget but sent whole", kind, k, b, t]);
        }
      }
    }
  });
  return out; }"""


def test_a_prompt_that_fits_is_byte_identical_to_the_frozen_old_builder_over_400_generated_cases(phone):
    assert len(GENERATED) >= 400
    phone.open_with()
    out = phone.evaluate(DIFF_JS, GENERATED)
    assert out["bad"] == [], out["bad"][:5]
    assert out["plain"] == len(GENERATED)       # no budget at all: the old text, every time
    assert out["fits"] > 4000 and out["over"] > 1000, out   # both sides really ran: with the edge (exactly fits, one over) in each case
    # the generated set covers what the screen can hold: no notes at all, caption-only and empty reels, three scripts, very long questions
    assert any(not c["notes"] for c in GENERATED) and any(len(c["q"]) >= 3000 for c in GENERATED) and any(not c["q"] for c in GENERATED)
    assert any("notes" not in n and n.get("caption") for c in GENERATED for n in c["notes"]) and any(n.get("notes") == {} for c in GENERATED for n in c["notes"])
    assert any(re.search("[а-я]", c["q"]) for c in GENERATED) and any(re.search("[一-龥]", c["q"]) for c in GENERATED)


def test_the_notes_written_by_the_checker_corpus_go_through_the_ask_builder_too(phone):
    """Real answers in the notes format (the checker's good ones, read by Notes.parse): a prompt that fits is the old one, a tight one is the oracle's."""
    phone.open_with()
    parsed = phone.evaluate("(ts) => ts.map((t) => Notes.parse(t))", [GOOD, _with(INGREDIENTS=["2 cups flour", "1 cup milk"], STEPS=["Mix them", "Bake it"]), _non_latin(), GOOD])
    assert all(parsed) and parsed[1]["ingredients"] and parsed[1]["steps"]
    cases = [{"q": "how do I keep a plan short?", "notes": [{"code": f"G{i}", "notes": n} for i, n in enumerate(parsed)] * 2, "web": []}]
    base = est(ask_text(cases[0]["q"], []))
    rows = run_cases(phone, cases, lambda ta, tw: [ta, ta - 1, ta * 3 // 4, ta // 2, ta // 3, ta // 5, base + 5])
    assert {r["got"]["used"] for r in rows if r["kind"] == "ask"} >= {len(parsed) * 2, 0} and len({r["got"]["used"] for r in rows if r["kind"] == "ask"}) >= 4
    for r in rows:
        assert (r["got"]["prompt"], r["got"]["used"], r["got"]["webUsed"], r["got"]["questionCut"]) == r["want"], shown(r)


# ---------------------------------------------------------------- over budget: the oracle's exact prompt, and the rules one by one

def test_an_ask_prompt_over_budget_is_exactly_what_the_rules_make_it(phone):
    rows = rows_of(phone)
    assert len(rows) >= 1900
    bad = [shown(r) for r in rows if (r["got"]["prompt"], r["got"]["used"], r["got"]["webUsed"], r["got"]["questionCut"]) != r["want"]]
    assert not bad, f"{len(bad)} of {len(rows)} prompts differ from the oracle, for example: {bad[:5]}"
    # the page's token count is the oracle's, for every prompt
    assert all(r["got"]["tokens"] == est(r["got"]["prompt"]) for r in rows)
    # the sweep reached every kind of outcome
    ask = [r for r in rows if r["kind"] == "ask"]
    web = [r for r in rows if r["kind"] == "web"]
    assert sum(0 < r["got"]["used"] < r["got"]["total"] for r in ask) >= 250      # some notes in, the last ones left out
    assert sum(r["got"]["used"] == 0 and r["got"]["total"] > 0 for r in ask) >= 100  # none fit
    assert sum(0 < r["got"]["webUsed"] < r["got"]["webTotal"] for r in web) >= 150  # some web results in, the last ones left out
    assert sum(r["got"]["questionCut"] for r in rows) >= 100


def test_the_prompt_is_within_the_budget_by_est_tokens_whenever_the_fixed_part_fits(phone):
    rows = rows_of(phone)
    checked = 0
    for r in rows:
        g = r["got"]
        fixed = est(TEXT[r["kind"]](r["case"]["q"], [], []))   # the instructions and the question as asked
        if r["budget"] >= fixed or g["questionCut"]:
            assert g["tokens"] <= r["budget"], f"{shown(r)}: {g['tokens']} tokens"
            checked += 1
        else:   # not even the instructions and the question fit: nothing is added to them
            assert g["used"] == 0 and g["webUsed"] == 0 and g["prompt"] == TEXT[r["kind"]](r["case"]["q"], [], []), shown(r)
    assert checked >= 1700


def test_notes_go_in_whole_in_rank_order_and_the_ones_left_out_are_the_last(phone):
    rows = rows_of(phone)
    seen = {"partial": 0, "web": 0}
    for r in rows:
        g, texts = r["got"], r["notes"]
        assert g["total"] == len(texts) and 0 <= g["used"] <= g["total"] and g["webTotal"] == (len(r["found"]) if r["kind"] == "web" else 0), shown(r)
        # the prompt holds notes 1..used exactly as the old builder wrote them, one after the other: whole and in rank order
        block = "\n\n".join(texts[: g["used"]])
        prompt = g["prompt"]
        if g["used"]:
            assert f"My notes:\n\n{block}" in prompt, shown(r)
            for t in texts[: g["used"]]:
                assert prompt.count(t) == 1, shown(r)      # every note of the prompt is a full note text, once
        for i in range(g["used"], g["total"]):             # the notes after them are not there, not even their start
            assert texts[i][:40] not in prompt, f"{shown(r)}: note {i + 1} (left out) is in the prompt"
        # the numbers [1]..[used] are those of the screen, so the links in the answer still point at the right note
        assert re.findall(r"(?m)^\[(\d+)\] ", prompt) == [str(i + 1) for i in range(g["used"])], shown(r)
        # whole notes only: the next note did not fit (that is why it is out), the first one that does not fit ends the list
        if 0 < g["used"] < g["total"] and not g["questionCut"] and r["kind"] == "ask":
            more = ask_text(r["case"]["q"], texts[: g["used"] + 1])
            assert est(more) > r["budget"], f"{shown(r)}: the next note would have fit"
            seen["partial"] += 1
        if r["kind"] == "web" and 0 < g["webUsed"] < g["webTotal"]:
            assert est(web_text(r["case"]["q"], texts[: g["used"]], r["found"][: g["webUsed"] + 1])) > r["budget"], shown(r)
            seen["web"] += 1
    assert seen["partial"] >= 250 and seen["web"] >= 150, seen


def test_the_web_results_are_filled_after_the_notes_in_what_is_left(phone):
    """Notes first: a note is never given up for a web result, and a web result that does not fit is left out with all after it."""
    rows = [r for r in rows_of(phone) if r["kind"] == "web"]
    for r in rows:
        g, q = r["got"], r["case"]["q"]
        if g["webUsed"] and not g["questionCut"]:
            assert g["prompt"].endswith("Web results:\n\n" + "\n\n".join(r["found"][: g["webUsed"]])), shown(r)   # in their order, from the first
            assert ("My notes:" in g["prompt"]) == (g["used"] > 0) and g["prompt"].count("[W1] ") == 1, shown(r)
        if g["used"] < g["total"] and not g["questionCut"]:
            # a note that is left out would not have fit even with no web result beside it
            assert est(web_text(q, r["notes"][: g["used"] + 1], [])) > r["budget"], shown(r)
    assert sum(r["got"]["webUsed"] > 0 and r["got"]["used"] < r["got"]["total"] for r in rows) >= 200  # web results went in while notes were out


def test_the_instructions_and_the_question_are_never_cut_except_an_oversize_question(phone):
    rows = rows_of(phone)
    whole = cut = 0
    for r in rows:
        g, q = r["got"], r["case"]["q"]
        head = ASK_HEAD if r["kind"] == "ask" else WEB_HEAD
        assert g["prompt"].startswith(head + "Question: "), shown(r)        # the instructions are whole
        assert g["prompt"].count(head) == 1, shown(r)
        fixed = est(TEXT[r["kind"]](q, [], []))
        if r["budget"] >= fixed:
            assert not g["questionCut"] and f"Question: {q}\n\n" in g["prompt"], shown(r)   # it fits with the instructions: whole
            whole += 1
        elif g["questionCut"]:   # an oversize question: its start, cut at a word, with the marker
            assert cut_at_a_word(q, question_of(g["prompt"], r["kind"])) and g["tokens"] <= r["budget"], shown(r)
            cut += 1
        else:                    # no room for any of it: kept whole, nothing added
            assert f"Question: {q}\n\n" in g["prompt"], shown(r)
    assert whole >= 1500 and cut >= 100, (whole, cut)


def test_an_oversize_question_is_cut_at_a_word_with_the_marker_and_takes_the_whole_budget(phone):
    w = ne.Writer(ne.Rng(5), ne.LATIN)
    note = {"code": "N1", "notes": make_note(w, "small")}
    base = est(ask_text("", []))
    spoken = w.prose(3000, joint="\n")
    flat = "".join(w.word() for _ in range(300))[:1500]
    cases = [{"q": spoken, "notes": [note], "web": []}, {"q": flat, "notes": [note], "web": []}, {"q": "short question", "notes": [note], "web": []}]
    for budget in (base + 40, base + 200, base + 450):   # the flat question is 500 tokens, the spoken one 1,000: both are over all three
        rows = run_cases(phone, cases, lambda ta, tw: [budget])
        for r in (x for x in rows if x["kind"] == "ask"):
            g, q = r["got"], r["case"]["q"]
            assert (g["prompt"], g["used"], g["webUsed"], g["questionCut"]) == r["want"], shown(r)
            if q == "short question":
                assert not g["questionCut"], shown(r)
                continue
            assert g["questionCut"] and g["used"] == 0 and g["tokens"] <= budget, shown(r)
            assert cut_at_a_word(q, question_of(g["prompt"], "ask")), shown(r)
            assert budget - g["tokens"] <= (8 if q == spoken else 3), f"{shown(r)}: the cut left {budget - g['tokens']} tokens unused"
            assert (" " in q) == (q == spoken)


def test_non_latin_notes_cost_two_tokens_a_character_so_fewer_of_them_fit(phone):
    """The same number of characters: a Cyrillic or Japanese note takes 3 or more times the tokens of an English one."""
    latin, cyr, cjk = (ne.Writer(ne.Rng(9), s) for s in (ne.LATIN, ne.CYRILLIC, CJK))
    five = lambda w: [{"code": f"L{i}", "notes": {"topic": "Topic", "points": [w.prose(760)], "tags": ["t"]}} for i in range(5)]   # 760 characters each
    cases = [{"q": "question?", "notes": five(w), "web": []} for w in (latin, cyr, cjk)]
    (first,) = [r for r in run_cases(phone, cases[:1], lambda ta, tw: [ta]) if r["kind"] == "ask"]
    budget = first["budget"]   # exactly what the five English notes take
    rows = [first] + [r for r in run_cases(phone, cases[1:], lambda ta, tw: [budget]) if r["kind"] == "ask"]
    used = [r["got"]["used"] for r in rows]
    assert used[0] == 5 and used[1] <= 2 and used[2] <= 2, used   # an English note takes about 300 tokens, a Cyrillic or Japanese one 5 times that
    for r in rows:
        assert (r["got"]["prompt"], r["got"]["used"]) == r["want"][:2], shown(r)
        assert r["got"]["tokens"] <= budget
        assert est(ask_text("question?", r["notes"][: r["got"]["used"] + 1])) > budget or r["got"]["used"] == 5   # and the next one did not fit
    # what counting characters would have done: the Cyrillic prompt looks small by length (chars / 3) and is over budget by tokens
    cyr_all = ask_text("question?", rows[1]["notes"][:5])
    assert math.ceil(len(cyr_all) / 3) <= budget < est(cyr_all)


@pytest.mark.parametrize("budget", [0, -1, -10 ** 9, 1, 5, 50, 83])   # the instructions alone are 84 tokens (the web ones 146)
def test_a_budget_of_nothing_or_less_than_the_instructions_keeps_the_fixed_part_and_the_whole_question(phone, budget):
    phone.open_with()
    w = ne.Writer(ne.Rng(4), ne.LATIN)
    notes = [{"code": "A", "notes": make_note(w, "tiny")}, {"code": "B", "caption": "a caption"}]
    web = [{"title": "T", "source": "Wikipedia", "text": "x"}]
    for q in ("short question?", w.prose(3000), ""):
        got = phone.evaluate("""([q, notes, web, b]) => { const rs = notes.map((reel) => ({ reel }));
          return [Notes.answerPromptInfo(q, rs, { budget: b }), Notes.webAnswerPromptInfo(q, rs, web, { budget: b })]; }""", [q, notes, web, budget])
        for kind, g in zip(("ask", "web"), got):
            assert g["prompt"] == TEXT[kind](q, [], []), (kind, len(q), budget)    # the instructions and the question as asked, nothing else
            assert (g["used"], g["webUsed"], g["total"]) == (0, 0, 2), (kind, g)


@pytest.mark.parametrize("budget_js", ["NaN", "Infinity", "undefined", "null", "'abc'", "{}"])
def test_a_budget_that_is_not_a_finite_number_means_no_limit_like_the_notes_prompt(phone, budget_js):
    phone.open_with()
    w = ne.Writer(ne.Rng(6), ne.LATIN)
    notes = [{"code": f"N{i}", "notes": make_note(w, "large")} for i in range(5)]
    web = [{"title": "T", "source": "Wikipedia", "text": w.prose(1100)}]
    got = phone.evaluate("""([notes, web]) => { const b = %s, rs = notes.map((reel) => ({ reel }));
      return [Notes.answerPromptInfo('q?', rs, { budget: b }).prompt, Notes.webAnswerPromptInfo('q?', rs, web, { budget: b }).prompt,
              Notes.answerPrompt('q?', rs), Notes.webAnswerPrompt('q?', rs, web)]; }""" % budget_js, [notes, web])
    assert got[0] == got[2] and got[1] == got[3] and est(got[0]) > 4000   # the whole prompt, not an error and not an empty one


def test_a_missing_options_object_and_empty_lists_do_not_throw(phone):
    phone.open_with()
    got = phone.evaluate("""() => [Notes.answerPromptInfo('q', []), Notes.answerPromptInfo('q', [], {}), Notes.answerPromptInfo('q', [], { budget: 10 }),
      Notes.webAnswerPromptInfo('q', [], [{ title: 't', source: 's', text: 'x' }], { budget: 10 }), Notes.answerPromptInfo(undefined, [], { budget: 10 })].map((i) => [i.used, i.total, i.webUsed, i.webTotal])""")
    assert got == [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 1], [0, 0, 0, 0]]


# ---------------------------------------------------------------- the Ask screen with the fake bridge

MODEL_READY = {"ready": True, "partial": 0, "installed": []}
KEY = "zorbelix"   # every library note holds this word, so the question "zorbelix" finds them all
QWEN_CTX = 4096


def ask_library(count, size, seed=21, script=ne.LATIN):
    w = ne.Writer(ne.Rng(seed), script)
    reels = []
    for i in range(count):
        note = make_note(w, size)
        note["topic"], note["tags"] = f"Zorbelix {note['topic']}", [KEY, *note["tags"]]
        reels.append({"code": f"ASK{i:03d}", "url": f"https://example.invalid/reel/ASK{i:03d}/", "status": "done", "added_at": 1000 + i,
                      "notes_by": "meta", "notes": note, "collections": []})
    return {"reels": reels, "inbox": []}


WEB_RESULTS = [{"title": f"Page {i}", "url": f"https://example.invalid/page/{i}", "source": ("Wikipedia", "DuckDuckGo")[i % 2],
                "text": ne.Writer(ne.Rng(40 + i), ne.LATIN).prose(1150)} for i in range(4)]


def open_ask(pg, lib, settings=None, extra=None, answers=("It says to rotate keys [1] and [2].",), hash_=f"#/ask?q={KEY}"):
    state = {"db": json.dumps(lib), "model": MODEL_READY, "answers": list(answers), "settings": json.dumps(settings or {}), **(extra or {})}
    pg.open_with(state, hash_)
    pg.locator("#aiAns").wait_for()
    st = pg.rn()
    return st["db"], st.get("rev")


def results_texts(pg, limit):
    """The Ask screen's results in rank order (what it hands to the builder) and their old-builder note texts."""
    codes = pg.evaluate("(n) => lastAsk.results.slice(0, n).map((x) => x.reel.code)", limit)
    reels = pg.evaluate("(cs) => cs.map((c) => db.reels.find((r) => r.code === c))", codes)
    return codes, pg.evaluate(TEXTS_JS, [{"q": KEY, "notes": reels, "web": []}])[0]["notes"]


def generates(pg):
    return [c for c in pg.rn()["calls"] if c[0] == "generate"]


def stored_unchanged(pg, before):
    st = pg.rn()
    assert (st["db"], st.get("rev")) == before, "the Ask changed what is stored on the phone"
    assert not re.search(r"left out|did not fit|shortened|askLeft", st["db"])


@pytest.mark.parametrize("answer", [400, 800, 1500])
def test_the_ask_screen_sends_a_prompt_within_the_budget_and_says_which_notes_were_left_out(phone, answer):
    lib = ask_library(8, "large")
    before = open_ask(phone, lib, {"maxTokens": answer})
    phone.locator("#aiAns").click()
    phone.locator("#askLeft").wait_for()
    (gen,) = generates(phone)
    prompt, opts = gen[1], gen[2]
    budget = budget_for(QWEN_CTX, answer, ASK_SYSTEM)
    assert phone.evaluate("() => promptBudget(Notes.ASK_SYSTEM)") == budget
    assert opts["system"] == ASK_SYSTEM and opts["maxTokens"] == answer and "media" not in opts   # no reserve for pictures and sound
    codes, texts = results_texts(phone, 5)
    want, used, _, cut = fill("ask", KEY, texts, [], budget)
    assert prompt == want and est(prompt) <= budget and not cut
    assert 0 < used < 5 and est(ask_text(KEY, texts[: used + 1])) > budget   # a real cut: the next note did not fit whole
    # whole notes in rank order: note texts 1..used, and nothing of note used+1
    assert f"My notes:\n\n" + "\n\n".join(texts[:used]) in prompt and f"[{used + 1}] " not in prompt
    line = phone.locator("#askLeft").inner_text()
    left = 5 - used
    assert line == f"{left} of 5 notes did not fit and {'was' if left == 1 else 'were'} left out (the best matches go in first)."
    assert phone.locator(".card:has(#askLeft) .pre a").count() == 2   # the line is in the answer's own card; its [1] and [2] still link to reels
    stored_unchanged(phone, before)
    assert db_of(phone)["reels"] == lib["reels"]   # no reel was touched


def test_notes_that_fit_are_sent_exactly_as_before_and_no_line_is_shown(phone):
    lib = ask_library(8, "small")
    before = open_ask(phone, lib)
    phone.locator("#aiAns").click()
    phone.locator(".pre").wait_for()
    (gen,) = generates(phone)
    old = phone.evaluate("() => {" + OLD_JS + " return oldAnswer(lastAsk.q, lastAsk.results.slice(0, 5)); }")
    assert gen[1] == old and est(old) <= budget_for(QWEN_CTX, 800, ASK_SYSTEM) and "[5] " in old and "[6] " not in old   # all five notes
    assert phone.locator("#askLeft").count() == 0
    stored_unchanged(phone, before)


def test_the_web_answer_is_budgeted_too_and_the_line_names_notes_and_web_results(phone):
    lib = ask_library(6, "medium", seed=23)
    before = open_ask(phone, lib, {"webLookup": True, "maxTokens": 1500}, {"web": WEB_RESULTS}, answers=("Rotate keys [1] as the page says [W1].",))
    phone.locator("#webAsk").click()
    phone.locator("#askLeft").wait_for()
    (gen,) = generates(phone)
    prompt, opts = gen[1], gen[2]
    budget = budget_for(QWEN_CTX, 1500, WEB_ASK_SYSTEM)
    assert phone.evaluate("() => promptBudget(Notes.WEB_ASK_SYSTEM)") == budget
    assert opts["system"] == WEB_ASK_SYSTEM and opts["maxTokens"] == 1500
    _, texts = results_texts(phone, 4)
    found = [f"[W{i + 1}] {w['title']} ({w['source']}): {w['text']}" for i, w in enumerate(WEB_RESULTS)]
    want, used, web_used, _ = fill("web", KEY, texts, found, budget)
    assert prompt == want and est(prompt) <= budget
    assert 0 < used < 4 and 0 < web_used < 4, (used, web_used)   # both kinds were cut: the notes first, the web results in what was left
    left_notes, left_web = 4 - used, 4 - web_used
    assert phone.locator("#askLeft").inner_text() == (
        f"{left_notes} of 4 notes did not fit and {'was' if left_notes == 1 else 'were'} left out (the best matches go in first). "
        f"{left_web} of 4 web results did not fit and {'was' if left_web == 1 else 'were'} left out.")
    assert phone.locator(".pre a[data-url]", has_text="[W1]").count() == 1   # the answer still links its web result
    stored_unchanged(phone, before)


def test_a_web_answer_that_fits_is_the_old_prompt_and_has_no_line(phone):
    lib = ask_library(3, "small", seed=24)
    before = open_ask(phone, lib, {"webLookup": True}, {"web": WEB_RESULTS[:2]})
    phone.locator("#webAsk").click()
    phone.locator(".pre").wait_for()
    (gen,) = generates(phone)
    old = phone.evaluate("(web) => {" + OLD_JS + " return oldWeb(lastAsk.q, lastAsk.results.slice(0, 4), web); }", WEB_RESULTS[:2])
    assert gen[1] == old and phone.locator("#askLeft").count() == 0
    stored_unchanged(phone, before)


def test_when_not_even_the_best_note_fits_nothing_is_sent_and_the_page_says_so(phone):
    lib = ask_library(3, "huge", seed=25)   # one note is about 5,000 tokens: more than a whole window
    before = open_ask(phone, lib)
    phone.locator("#aiAns").click()
    phone.get_by_text("None of your best notes fit the phone AI's window").wait_for()
    assert generates(phone) == [] and phone.locator("#askLeft").count() == 0 and phone.locator(".pre").count() == 0
    stored_unchanged(phone, before)
    # the web answer still has its web results to answer from: the notes are all left out and the page says so
    open_ask(phone, lib, {"webLookup": True}, {"web": WEB_RESULTS[:2]})
    phone.locator("#webAsk").click()
    phone.locator("#askLeft").wait_for()
    (gen,) = generates(phone)
    assert "My notes:" not in gen[1] and "[W1] " in gen[1]
    assert phone.locator("#askLeft").inner_text() == "3 of 3 notes did not fit and were left out (the best matches go in first)."


def test_ask_any_ai_with_these_notes_is_not_shortened_it_goes_to_your_own_chat_app(phone):
    lib = ask_library(8, "large")
    open_ask(phone, lib)
    phone.get_by_role("button", name="Ask any AI with these notes").click()
    codes = phone.evaluate("() => lastAsk.results.slice(0, 6).map((x) => x.reel.code)")
    reels = phone.evaluate("(cs) => cs.map((c) => db.reels.find((r) => r.code === c))", codes)
    texts = phone.evaluate(TEXTS_JS, [{"q": KEY, "notes": reels, "web": []}])[0]["notes"]
    copied = phone.rn()["copied"]
    assert copied == ask_text(KEY, texts) and len(texts) == 6 and est(copied) > budget_for(QWEN_CTX, 800, ASK_SYSTEM) * 2   # all six, whole, as before
    assert generates(phone) == []


@pytest.mark.parametrize("model", ["qwen_with_a_bigger_window", "picked_by_hand"])
def test_a_model_picked_by_hand_gets_the_smallest_window_in_ask(phone, model):
    lib = ask_library(8, "large")
    open_ask(phone, lib, {"modelFile": "my-own-model.litertlm"} if model == "picked_by_hand" else {})
    phone.evaluate("() => { MODELS[0].ctx = 8192; }")   # as if a phone had confirmed a bigger window for the first model
    phone.locator("#aiAns").click()
    phone.locator(".pre").wait_for()
    (gen,) = generates(phone)
    ctx = 4096 if model == "picked_by_hand" else 8192
    _, texts = results_texts(phone, 5)
    budget = budget_for(ctx, 800, ASK_SYSTEM)
    want, used, _, _ = fill("ask", KEY, texts, [], budget)
    assert gen[1] == want and est(gen[1]) <= budget
    assert (used <= 2) == (model == "picked_by_hand") and (used >= 4) == (model != "picked_by_hand"), used   # the bigger window lets more notes in
    assert gen[2]["file"] == ("my-own-model.litertlm" if model == "picked_by_hand" else phone.evaluate("() => MODELS[0].file"))


# ---------------------------------------------------------------- what must not change

# sha256 of the prompts joined with a NUL, computed (scratch script, Node) on the A3-2 head 920c563, whose Ask code this PR changes and
# whose Meta AI and notes prompts it must not: metaPrompt for every fixture reel (the default template, a template with no {link}, one
# with two), batchPrompt for the first three, and localPrompt for every fixture reel with no budget and at the Qwen budget of each
# answer length.
PINNED = {"meta": "85eab60e9aa30b0a24f5b686ec21cedd3d0f1a7fcabe4bb4582c9b87bf139301",
          "notes": "020e9e4d291441cfa6876eec4c4a3b8eef3515b334e982b61d10a2bc31d74bd2",
          "batch": "883fabd0a1e4359441ea84251158e24e5b37ad2b2ac2b43e531428ffb2511db1"}
PINNED_JS = r"""(cases) => {
  const meta = [], notes = [];
  for (const c of cases) {
    meta.push(Notes.metaPrompt(Notes.META_PROMPT, c.reel), Notes.metaPrompt("Break it down", c.reel), Notes.metaPrompt("Look at {link} and {link}", c.reel));
    notes.push(Notes.localPrompt(c.reel, c.localExtra, {}));
    for (const answer of [400, 800, 1500]) notes.push(Notes.localPrompt(c.reel, c.localExtra, { budget: Notes.promptBudget({ ctx: 4096, answer, system: Notes.LOCAL_SYSTEM }) }));
  }
  return { meta, notes, batch: Notes.batchPrompt(cases.slice(0, 3).map((c) => c.reel)), system: Notes.LOCAL_SYSTEM.length, format: Notes.FORMAT.length };
}"""


def sha(items):
    return hashlib.sha256("\x00".join(items).encode("utf-8")).hexdigest()


def test_the_meta_ai_prompt_the_batch_prompt_and_the_notes_prompt_are_unchanged(phone):
    phone.open_with()
    got = phone.evaluate(PINNED_JS, CASES)
    assert (len(got["meta"]), len(got["notes"]), got["system"], got["format"]) == (36, 48, 471, 1020)
    assert sha(got["meta"]) == PINNED["meta"], "Notes.metaPrompt changed (the Meta AI prompt is not the phone's model and has no budget)"
    assert sha([got["batch"]]) == PINNED["batch"], "Notes.batchPrompt changed"
    assert sha(got["notes"]) == PINNED["notes"], "Notes.localPrompt changed (the notes prompt was budgeted in A3-2)"
    # the Meta AI prompt keeps its 12,000-character cap for the transcript and is never shortened by a token budget
    long = {"url": "https://example.invalid/reel/X/", "transcript": "word " * 5000}
    out = phone.evaluate("(r) => Notes.metaPrompt('Look at {link}', r)", long)
    assert out == "Look at https://example.invalid/reel/X/\n\nWhat is said in it (transcript):\n" + long["transcript"][:12000] and "[shortened]" not in out


def test_the_page_budget_with_no_argument_is_still_the_notes_budget(phone):
    phone.open_with()
    system = phone.evaluate("() => Notes.LOCAL_SYSTEM")
    assert phone.evaluate("() => [promptBudget() === promptBudget(Notes.LOCAL_SYSTEM), promptBudget(Notes.ASK_SYSTEM) > promptBudget()]") == [True, True]
    assert phone.evaluate("() => promptBudget()") == budget_for(QWEN_CTX, 800, system) == 2934   # the A3-2 number (design: 4096 - 800 - 157 - 205)
