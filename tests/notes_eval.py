"""Evaluation data and an answer checker for the on-phone AI's notes (A3-1, design: docs/design/A3-prompt-budget.md).

Two things, both usable without a phone and without any model:

* the synthetic fixture, `tests/fixtures/notes_eval/reels.json`: twelve generated reels (placeholder words, codes EVAL001 to
  EVAL012, links on example.invalid, no real reel data) that cover the prompt's edge cases. `build_fixture()` makes it from a
  seeded generator, so the same bytes come out on every run and every Python, and tests/test_notes_eval.py checks that the
  committed file is exactly what the generator makes. Rewrite it with:  python tests/notes_eval.py generate
* `check_answer(text, parse, template)`, a deterministic checker for an answer in the notes format.

`make-backup` and `check` (the phone procedure, A3-4) are not here yet; they will be added to `main` below.

The checker needs the page's own reader of the format, so it is handed the page's `Notes.parse` (as `parse`) and
`Notes.FORMAT` (as `template`) instead of keeping a copy of them here that could drift. The tests get both from the page
the same way the other phone tests do; `check` will drive Chromium the same way tests/fixtures/make_library_fixtures.py does.
"""
import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "notes_eval" / "reels.json"

SEED = 20261119
START = 1767225600000  # 2026-01-01 00:00 UTC; the reels' added_at counts up from here

# What the app stores at most for each field (local.js), which a reel at its maximum fills completely.
TITLE_MAX, CAPTION_MAX, TRANSCRIPT_MAX, ONSCREEN_MAX, COMMENTS_MAX, TYPED_MAX, LOCAL_EXTRA_MAX = 300, 8000, 40000, 6000, 6000, 10000, 2000

LATIN = "ba be bi bo bu ka ke ki ko ku ma me mi mo mu ra re ri ro ru sa se si so su ta te ti to tu na ne ni no nu la le li lo lu".split()
CYRILLIC = [c + v for c in "бвгдзклмнпрстф" for v in "аеиоу"]


class Rng:
    """mulberry32 (the generator GEN_JS in tests/test_phone_topics.py uses): the same seed gives the same numbers anywhere."""

    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def next(self):
        self.s = (self.s + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((self.s ^ (self.s >> 15)) * (self.s | 1)) & 0xFFFFFFFF
        t = (((t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    def below(self, n):
        return int(self.next() * n)


class Writer:
    """Placeholder text in one script. A few hundred made-up words, some far more common than others, like real speech."""

    def __init__(self, rng, syllables):
        self.rng = rng
        self.pad = syllables[0][-1]
        self.vocab = ["".join(syllables[rng.below(len(syllables))] for _ in range(2 + i % 3)) for i in range(400)]

    def word(self):
        return self.vocab[int(len(self.vocab) * self.rng.next() ** 2)]

    def _fit(self, s, n, end=""):
        """Exactly n characters: s cut short, its tail cleaned up, and padded with letters if the cut ate some of it."""
        body = s[: n - len(end)].rstrip(" \n.!?,")
        return body + self.pad * (n - len(end) - len(body)) + end

    def sentence(self):
        s = " ".join(self.word() for _ in range(6 + self.rng.below(9)))
        u = self.rng.next()
        return s[0].upper() + s[1:] + ("." if u < 0.8 else "?" if u < 0.9 else "!")

    def prose(self, n, joint=" "):
        """n characters of sentences (all punctuated)."""
        parts, total = [], 0
        while total < n:
            parts.append(self.sentence())
            total += len(parts[-1]) + len(joint)
        return self._fit(joint.join(parts), n, ".")

    def run_on(self, n):
        """n characters of words on one line with no punctuation at all (what some speech results look like)."""
        parts, total = [], 0
        while total < n:
            parts.append(self.word())
            total += len(parts[-1]) + 1
        return self._fit(" ".join(parts), n)

    def title(self, n):
        t = self.run_on(n)
        return t[0].upper() + t[1:]

    def lines(self, n):
        """n characters of short lines (text read from the screen, or comments)."""
        parts, total = [], 0
        while total < n:
            parts.append(" ".join(self.word() for _ in range(2 + self.rng.below(7))))
            total += len(parts[-1]) + 1
        return self._fit("\n".join(parts), n)

    def hashtags(self, k):
        return " ".join("#" + self.word() for _ in range(k))

    def caption(self, n):
        """n characters: paragraphs, then a line of hashtags (the sentence splitter drops hashtags)."""
        tags = self.hashtags(3)
        return self.prose(n - len(tags) - 2, joint="\n") + "\n\n" + tags


def broken(s, width):
    """The same text with a line break instead of the first space after each `width` characters (the length does not change)."""
    out, i = [], 0
    while len(s) - i > width:
        j = s.find(" ", i + width)
        if j < 0:
            break
        out.append(s[i:j])
        i = j + 1
    out.append(s[i:])
    return "\n".join(out)


def _reel(i, code, **fields):
    reel = {"code": code, "url": f"https://example.invalid/reel/{code}/", "author": f"eval_creator_{i:02d}", "collections": ["eval"],
            "status": "new", "added_at": START + i * 1000, "added_by": "eval", "caption_read": 1, "video_tried": 1}
    reel.update(fields)
    return reel


def build_fixture():
    """{"reels": [...], "inbox": [], "localExtra": {code: text}}: the library the phone would hold (the shape of the app's own
    library file) and, for the two reels that need one, the 'Also:' text of Settings, which is a setting and not a reel field."""
    reels, extra = [], {}

    def add(spec=LATIN):
        """The next reel's number and its own writer: every reel has its own seed, so changing one does not change the others."""
        i = len(reels) + 1
        return i, Writer(Rng(SEED + i), spec)

    # 1. caption only, short: the smallest real prompt
    i, w = add()
    reels.append(_reel(i, "EVAL001", caption=w.caption(300)))

    # 2. an ordinary reel: every field, a few KB
    i, w = add()
    reels.append(_reel(i, "EVAL002", title=w.title(60), caption=w.caption(600), transcript=w.prose(2500, joint=" "),
                       onscreen=w.lines(400), comments=w.lines(500)))

    # 3. a long caption and nothing else
    i, w = add()
    reels.append(_reel(i, "EVAL003", caption=w.caption(CAPTION_MAX)))

    # 4. every field at the most the app stores, and the longest 'Also:' setting
    i, w = add()
    reels.append(_reel(i, "EVAL004", author=("eval_creator_04" + "x" * 32)[:32], title=w.title(TITLE_MAX), caption=w.caption(CAPTION_MAX),
                       transcript=w.prose(TRANSCRIPT_MAX), onscreen=w.lines(ONSCREEN_MAX), comments=w.lines(COMMENTS_MAX),
                       extra=w.prose(TYPED_MAX, joint="\n")))
    extra["EVAL004"] = w.prose(LOCAL_EXTRA_MAX)

    # 5. a transcript of 7,001 characters with no punctuation and no line break (one more than the prompt's 7,000)
    i, w = add()
    reels.append(_reel(i, "EVAL005", caption=w.caption(200), transcript=w.run_on(7001)))

    # 6. the same, 20,000 characters
    i, w = add()
    reels.append(_reel(i, "EVAL006", caption=w.caption(200), onscreen=w.lines(300), transcript=w.run_on(20000)))

    # 7. 20,000 characters with no punctuation but a line break about every 150 (caption files from YouTube look like this)
    i, w = add()
    reels.append(_reel(i, "EVAL007", caption=w.caption(200), transcript=broken(w.run_on(20000), 150)))

    # 8. a YouTube video: the code starts with yt-, the creator has no @, the description is called Description
    i, w = add()
    reels.append(_reel(i, "yt-EVALyt00008", url="https://example.invalid/watch?v=EVALyt00008", author="Eval Channel 08", title=w.title(80),
                       caption=w.caption(900), transcript=broken(w.run_on(3000), 150)))

    # 9. cooking-shaped: a list of ingredients, steps spoken in order
    i, w = add()
    ingredients = "\n".join(f"- {w.word()} {w.word()} {10 * (1 + w.rng.below(30))} g" for _ in range(8))
    steps = " ".join(f"Step {n}. {w.sentence()}" for n in range(1, 9))
    reels.append(_reel(i, "EVAL009", title=w.title(40), caption=w.sentence() + "\nIngredients\n" + ingredients + "\n\n" + w.hashtags(3),
                       transcript=steps, onscreen="\n".join(f"{10 * (1 + w.rng.below(30))} g {w.word()}" for _ in range(6)), comments=w.lines(300)))

    # 10. Cyrillic placeholder text in every field
    i, w = add(spec=CYRILLIC)
    reels.append(_reel(i, "EVAL010", title=w.title(80), caption=w.caption(1200), transcript=w.prose(4000), onscreen=w.lines(500),
                       comments=w.lines(600), extra=w.prose(400)))

    # 11. the always-kept part in a non-Latin script: a 300-character title and a 2,000-character 'Also:' setting
    i, w = add(spec=CYRILLIC)
    reels.append(_reel(i, "EVAL011", title=w.title(TITLE_MAX), caption=w.caption(400)))
    extra["EVAL011"] = w.prose(LOCAL_EXTRA_MAX)

    # 12. nothing but a link: a reel that was just saved, before anything was read from it
    i, w = add()
    reels.append(_reel(i, "EVAL012", author=""))

    return {"reels": reels, "inbox": [], "localExtra": extra}


def fixture_bytes():
    """The fixture file's exact content: UTF-8, sorted keys, LF line ends, one trailing newline."""
    return (json.dumps(build_fixture(), ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def load_fixture(path=FIXTURE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cases(fixture=None):
    """[{"reel": {...}, "localExtra": "..."}] in the fixture's order: what the prompt builder is given for each reel."""
    fx = fixture or load_fixture()
    return [{"reel": r, "localExtra": fx["localExtra"].get(r["code"], "")} for r in fx["reels"]]


# ---------------------------------------------------------------- the answer checker

SECTIONS = ("TOPIC", "INTENT", "TONE", "POINTS", "MEANING", "USE IT FOR", "TOOLS", "PRODUCTS", "INGREDIENTS", "STEPS", "TAKEAWAY", "TAGS")
RULES = ("parses", "sections", "complete", "order", "no_echo", "limits")
TOPIC_MAX, POINTS_MIN, POINTS_MAX, TAGS_MIN, TAGS_MAX = 200, 1, 40, 1, 12

# A heading starts a line, like the page's own (markdown # > * _ allowed, a list dash is not), but only the names FORMAT uses.
_HEAD = re.compile(r"^[\s>#*_]*(" + "|".join(s.replace(" ", r"\s+") for s in sorted(SECTIONS, key=len, reverse=True)) +
                   r")\s*[*_]*\s*(?:[:：–-]\s*[*_]*\s*(.*)|$)", re.I)
_PLACEHOLDER = re.compile(r"^\s*\d{1,3}[.)]\s*(?:\.{3}|…)\s*$", re.M)


def _squash(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def sections_of(text):
    """[(NAME, [lines])] in the order they are written. The text after the heading on its own line comes first. Lines before
    the first heading (a greeting) belong to no section."""
    out = []
    for line in str(text or "").replace("\r", "").split("\n"):
        m = _HEAD.match(line)
        if m:
            out.append((re.sub(r"\s+", " ", m.group(1)).upper(), [m.group(2)] if (m.group(2) or "").strip() else []))
        elif out:
            out[-1][1].append(line)
    return out


def _tags(lines):
    """The tags written in a TAGS section, the way the page's parser reads them (split at commas and spaces, # dropped, repeats once)."""
    tokens = (re.sub(r"[^\w-]", "", t.lstrip("#")).lower() for t in re.split(r"[,;\s]+", "\n".join(lines)))
    return {t for t in tokens if t}


def echoes(text, template):
    """True when the answer repeats the instructions of the template (FORMAT) instead of filling them in."""
    seen = _squash(text)
    for line in template.splitlines():
        m = _HEAD.match(line)
        body = (m.group(2) or "") if m else re.sub(r"^\s*\d{1,3}[.)]\s*", "", line)
        body = _squash(body)
        if len(body) >= 8 and body in seen:  # "..." and "none" are too short to count; "2. ..." is looked for below
            return True
    return bool(_PLACEHOLDER.search(str(text or "")))


def check_answer(text, parse, template):
    """The verdicts for one answer, each True when the answer passes that rule, plus "ok" (all of them).

    parse    the page's Notes.parse as a function: text -> notes dict, or None when it is not in the notes format
    template the page's Notes.FORMAT

    parses    the page's own reader accepts it (at least two sections, TOPIC or POINTS among them)
    sections  TOPIC, at least one point, TAKEAWAY and at least one tag are all there
    complete  the last section is TAGS with a tag in it. TAGS is the last section of FORMAT, so an answer that ran out of
              tokens before it fails. A cut inside the last tag itself cannot be seen.
    order     the sections come in the order of FORMAT, each once (an answer that starts over or loops fails)
    no_echo   none of the template's instructions ("one short line", "2. ...") is in the answer
    limits    topic at most 200 characters as written, 1 to 40 points, 1 to 12 tags as written
    """
    notes = parse(text)
    found = sections_of(text)
    names = [n for n, _ in found]
    order = [SECTIONS.index(n) for n in names]
    topic = " ".join(" ".join(lines) for n, lines in found if n == "TOPIC")
    topic = re.sub(r"\s+", " ", re.sub(r"\*\*|`|^[\s*_\"']+|[\s*_\"']+$", "", topic)).strip()
    tags = set().union(*(_tags(lines) for n, lines in found if n == "TAGS"))
    v = {
        "parses": notes is not None,
        "sections": bool(notes) and bool(notes.get("topic")) and len(notes.get("points") or []) >= 1 and bool(notes.get("takeaway")) and len(notes.get("tags") or []) >= 1,
        "complete": bool(found) and names[-1] == "TAGS" and len(_tags(found[-1][1])) >= 1,
        "order": all(a < b for a, b in zip(order, order[1:])),
        "no_echo": not echoes(text, template),
        "limits": bool(notes) and len(topic) <= TOPIC_MAX and POINTS_MIN <= len(notes.get("points") or []) <= POINTS_MAX and TAGS_MIN <= len(tags) <= TAGS_MAX,
    }
    v["ok"] = all(v[r] for r in RULES)
    return v


def failed(verdicts):
    """The names of the rules an answer broke, in RULES order."""
    return [r for r in RULES if not verdicts[r]]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Notes evaluation data for the on-phone AI (synthetic placeholders only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="write the synthetic fixture (the same bytes every run)")
    gen.add_argument("--out", type=Path, default=FIXTURE, help="where to write it (default: tests/fixtures/notes_eval/reels.json)")
    args = ap.parse_args(argv)
    if args.cmd == "generate":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(fixture_bytes())
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
