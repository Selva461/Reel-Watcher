"""Evaluation data and an answer checker for the on-phone AI's notes (A3-1, design: docs/design/A3-prompt-budget.md).

Two things, both usable without a phone and without any model:

* the synthetic fixture, `tests/fixtures/notes_eval/reels.json`: twelve generated reels (placeholder words, codes EVAL001 to
  EVAL012, links on example.invalid, no real reel data) that cover the prompt's edge cases. `build_fixture()` makes it from a
  seeded generator, so the same bytes come out on every run and every Python, and tests/test_notes_eval.py checks that the
  committed file is exactly what the generator makes. Rewrite it with:  python tests/notes_eval.py generate
* `check_answer(text, parse, template)`, a deterministic checker for an answer in the notes format.

The phone procedure (A3-4), written up for the owner in TESTING.md ("Evaluating the notes on a phone"):

* `make-backup [--out PATH]` writes the fixture as a Reel Shelf backup ZIP that the app's Restore (S4-3) accepts;
* `check ZIP` reads the backup the app makes afterwards and prints, per reel, the checker's verdicts for the stored answer.

The checker needs the page's own reader of the format, so it is handed the page's `Notes.parse` (as `parse`) and
`Notes.FORMAT` (as `template`) instead of keeping a copy of them here that could drift. The tests get both from the page
the same way the other phone tests do; `check` loads the page's notes.js into Chromium (Playwright, a dev dependency).
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURE = HERE / "fixtures" / "notes_eval" / "reels.json"
NOTES_JS = ROOT / "android" / "app-shell" / "app" / "src" / "main" / "assets" / "local" / "notes.js"

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
# The first form of the tail, `\s*[*_]*\s*`, could split a long run of blanks between its two `\s*` in thousands of ways when the
# rest then failed to match (quadratic); `\s*(?:[*_]+\s*)?` accepts exactly the same lines and can be matched only one way.
_HEAD = re.compile(r"^[\s>#*_]*(" + "|".join(s.replace(" ", r"\s+") for s in sorted(SECTIONS, key=len, reverse=True)) +
                   r")\s*(?:[*_]+\s*)?(?:[:：–-]\s*(?:[*_]+\s*)?(.*)|$)", re.I)
# One line only ([^\S\n] is blank space without the line break): with \s the search was quadratic on a long run of blank
# lines, and `check` (A3-4) now judges answers from a file that is not ours.
_PLACEHOLDER = re.compile(r"^[^\S\n]*\d{1,3}[.)][^\S\n]*(?:\.{3}|…)[^\S\n]*$", re.M)
# Every character of the class [\s*_"'] (\s is every Unicode space, and all of them are below U+3001), for str.rstrip: a regex that
# ends in [\s*_"']+$ is quadratic on a long run of these characters in the middle of the text, rstrip is not.
_TRIM = "".join(chr(i) for i in range(0x3001) if chr(i).isspace()) + "*_\"'"


def _clean_topic(topic):
    """The topic as written, without markdown stars, back-ticks, quotes and the blanks around it, in one line (its length is the `limits` rule)."""
    return re.sub(r"\s+", " ", re.sub(r"\*\*|`|^[\s*_\"']+", "", topic.rstrip(_TRIM))).strip()


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
    topic = _clean_topic(topic)
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


# ---------------------------------------------------------------- the phone procedure (A3-4): make-backup and check

# What the app's backup reader accepts (LibraryBackup.java; restore is S4-3, PR #67). Read there, not from the design text, because
# the real manifest differs from the design's: the app's version sits under "app" and each file's schema under "files".
BACKUP_FORMAT, BACKUP_FORMAT_VERSION = "reelshelf-backup", 1  # LibraryBackup.FORMAT, FORMAT_VERSION
REELS_SCHEMA = 1                                             # LibraryFile.REELS_SCHEMA and SCHEMA in local.js
BACKUP_ENTRIES = ("manifest.json", "reels.json", "shots.json")  # the only entry names the app accepts (nothing else, no folders)
BACKUP_CREATED_AT = "2026-01-01T00:00:00Z"                   # fixed, so the same bytes come out on every run
BACKUP_APP = {"version_name": "notes-eval", "version_code": 0}
BACKUP_CONTAINS = "synthetic notes-evaluation library: placeholder reels only; no settings, no API keys, no screenshots list, no pictures or videos"
ZIP_DATE = (2026, 1, 1, 0, 0, 0)
RAW_MAX = 20000                                              # setNotes (local.js) keeps r.raw at most this long
EXTRA_SETTING = "Extra instructions for the on-phone AI"     # the Settings field that `localExtra` is typed in

# What `check` will read from a ZIP. The evaluation library is a few hundred KB; these only stop a hostile file from filling memory.
MAX_ZIP_BYTES = MAX_JSON_BYTES = 64 << 20
MAX_MANIFEST_BYTES = 1 << 20                                 # the app's own limit for manifest.json

RULE_HELP = {
    "parses": "the page's own reader does not accept it as notes (not in the notes format)",
    "sections": "TOPIC, at least one point, TAKEAWAY or at least one tag is missing",
    "complete": "it does not end with TAGS: it was probably cut off by the answer length (Settings)",
    "order": "sections out of order or written twice (an answer that starts over or loops)",
    "no_echo": "it repeats the instructions of the format (\"one short line\", \"2. ...\") instead of filling them in",
    "limits": "topic over 200 characters, no points or more than 40, or no tags or more than 12",
}


def backup_library(fixture=None):
    """The fixture as the library the page stores (the reels.json of a backup): the reels as generated (status new, no notes, so
    Start has work to do) and the stored library's other lists, empty. `localExtra` is a phone setting, not part of a library."""
    fx = fixture or load_fixture()
    return {"reels": fx["reels"], "inbox": fx.get("inbox") or [], "media": [], "mediaTypes": [], "schema_version": REELS_SCHEMA}


def backup_bytes(library=None):
    """A backup ZIP for `library` (default: the fixture's): reels.json, then manifest.json last, as the app writes them. The
    same bytes every time: fixed entry dates, fixed order, no compression (so no zlib version can change them)."""
    lib = backup_library() if library is None else library
    reels = json.dumps(lib, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    manifest = {
        "format": BACKUP_FORMAT, "format_version": BACKUP_FORMAT_VERSION, "created_at": BACKUP_CREATED_AT, "app": dict(BACKUP_APP),
        "files": {"reels.json": {"bytes": len(reels), "sha256": hashlib.sha256(reels).hexdigest(), "schema_version": REELS_SCHEMA}},
        "counts": {"reels": len(lib["reels"]), "titles": len(lib.get("media") or []), "screenshots": 0},
        "contains": BACKUP_CONTAINS,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in (("reels.json", reels), ("manifest.json", json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8"))):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3          # not the platform's default, which would change the bytes on Windows
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


def make_backup(out):
    data = backup_bytes()
    Path(out).write_bytes(data)
    fx = load_fixture()
    extras = ", ".join(f"{code}: {len(text):,} characters" for code, text in fx["localExtra"].items())
    print(f"wrote {out}: {len(fx['reels'])} made-up reels ({fx['reels'][0]['code']} to {fx['reels'][-1]['code']}), {len(data):,} bytes, no notes yet")
    print("On the phone (needs Reel Shelf with Restore, S4-3): Settings > Backup and restore > Restore from a backup. This replaces the library there;")
    print("the app keeps the old one on the phone, and its box 'Save a backup of the current library first' is ticked by default: leave it ticked.")
    print(f"Two reels have an 'Also:' text ({extras}). It is the phone setting '{EXTRA_SETTING}': one text for all reels, and not part of a backup.")
    print(f"To use one, paste it from \"localExtra\" in {FIXTURE.relative_to(ROOT).as_posix()} into that field in Settings before Start; to skip it, leave the field empty.")
    return 0


class BadBackup(Exception):
    """The file is not a backup `check` can read; the message says why, in plain words."""


def _safe(value, n=200):
    """One printable line from anything a ZIP can hold: control and direction characters become ?, long text is cut."""
    s = value if isinstance(value, str) else repr(value) if isinstance(value, (int, float, bool)) else ""
    s = "".join(c if c.isprintable() else "?" for c in s[: n + 1])
    return s if len(s) <= n else s[:n] + "..."


def _member(z, info, limit):
    """The entry's bytes, read in memory and never more than `limit` of them: the size it declares is not trusted."""
    with z.open(info) as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise BadBackup(f"\"{info.orig_filename}\" is bigger than {limit:,} bytes")
    return data


def _json_object(data, what):
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise BadBackup(f"{what} is not readable JSON") from None
    if not isinstance(value, dict):
        raise BadBackup(f"{what} is not a JSON object")
    return value


def read_backup(path):
    """(manifest, library) from a backup ZIP made by the app, or BadBackup. The ZIP is read in memory: no entry is ever extracted
    to a file, so a name such as ../x cannot write anywhere. The rules are the app's own (LibraryBackup.check): only the names
    manifest.json, reels.json and shots.json, each once, no folders; the manifest says format reelshelf-backup, version 1, and lists
    reels.json with its bytes and sha256, which must match. shots.json is allowed and never read. One rule of the app is NOT applied:
    a backup whose schema_version is newer than the app's is refused by the app (NEWER_SCHEMA) but read and judged here."""
    path = Path(path)
    try:
        size = path.stat().st_size if path.is_file() else -1
    except OSError:
        size = -1
    if size < 0:
        raise BadBackup("it is not a readable file")
    if size > MAX_ZIP_BYTES:
        raise BadBackup(f"it is bigger than {MAX_ZIP_BYTES:,} bytes")
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if not infos:
                raise BadBackup("the ZIP is empty")
            names = [i.orig_filename for i in infos]   # as written in the file: ZipInfo.filename is cut at a NUL
            for info, name in zip(infos, names):
                if name not in BACKUP_ENTRIES or info.is_dir():
                    raise BadBackup(f"it contains something else (\"{_safe(name, 40)}\"): a Reel Shelf backup has only manifest.json, reels.json and shots.json")
                if info.flag_bits & 0x1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise BadBackup(f"\"{name}\" is encrypted or compressed in a way the app does not write")
            if len(set(names)) != len(names):
                raise BadBackup("an entry is in it twice")
            by_name = dict(zip(names, infos))
            if "manifest.json" not in by_name:
                raise BadBackup("it has no manifest.json (a plain reels.json or a notes export cannot be restored either)")
            if "reels.json" not in by_name:
                raise BadBackup("it has no reels.json")
            manifest = _json_object(_member(z, by_name["manifest.json"], MAX_MANIFEST_BYTES), "manifest.json")
            reels_raw = _member(z, by_name["reels.json"], MAX_JSON_BYTES)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, OverflowError, OSError):
        raise BadBackup("it is not a ZIP, or it is damaged or incomplete") from None
    if manifest.get("format") != BACKUP_FORMAT:
        raise BadBackup("its manifest does not say it is a Reel Shelf backup")
    version = manifest.get("format_version")
    if isinstance(version, bool) or not isinstance(version, (int, float)) or version != version:
        raise BadBackup("its manifest has no usable format_version")
    if version > BACKUP_FORMAT_VERSION:
        raise BadBackup("it was made by a newer Reel Shelf than this script knows")
    if version != BACKUP_FORMAT_VERSION:
        raise BadBackup("its manifest version is wrong")
    files = manifest.get("files")
    listed = files.get("reels.json") if isinstance(files, dict) else None
    if not isinstance(listed, dict):
        raise BadBackup("its manifest does not list reels.json")
    if listed.get("bytes") != len(reels_raw) or str(listed.get("sha256", "")).lower() != hashlib.sha256(reels_raw).hexdigest():
        raise BadBackup("reels.json is not what its manifest says was saved (a copy that stopped early, or a changed file)")
    library = _json_object(reels_raw, "reels.json")
    if not isinstance(library.get("reels"), list):
        raise BadBackup("reels.json has no list of reels")
    return manifest, library


def _chromium():
    """The Chromium the tests use (tests/test_app.py finds it), or None: Playwright then uses the browser it installed itself."""
    try:
        from test_app import CHROME
        return CHROME
    except Exception:  # noqa: BLE001  any trouble importing the test module means "use Playwright's own"
        return None


def parse_with_page(texts):
    """(template, [notes or None for each text]): the page's own Notes.FORMAT and Notes.parse, run in Chromium. Only notes.js is
    loaded (pure helpers, no screen code); it is the same Notes the whole page has."""
    from playwright.sync_api import sync_playwright
    source = NOTES_JS.read_text(encoding="utf-8")
    args = ["--no-sandbox"] if getattr(os, "geteuid", lambda: 1)() == 0 else []   # a root container has no sandbox to use
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_chromium(), args=args)
        try:
            page = browser.new_page()
            page.goto("about:blank")
            page.add_script_tag(content=source)
            return page.evaluate("() => Notes.FORMAT"), page.evaluate("(ts) => ts.map((t) => Notes.parse(t))", texts)
        finally:
            browser.close()


def _how_it_ended(r):
    parts = [f"status {_safe(r.get('status') or '-', 30)}", f"notes by {_safe(r.get('notes_by') or '-', 30)}"]
    tries = r.get("tries")
    if isinstance(tries, int) and not isinstance(tries, bool) and tries > 0:
        parts.append(f"{tries} {'try' if tries == 1 else 'tries'}")
    return ", ".join(parts)


def check(path):
    """Prints, for each reel of a backup the app made after the run, the checker's verdicts for the stored answer (r.raw), or why
    there is no answer text. Returns the exit code: 0 when every answer passes every rule and no reel failed; 1 when an answer breaks
    a rule, a reel failed on the phone, or there was no answer to judge at all; 2 for a file that is not a usable backup; 3 when
    Chromium cannot be started (nothing was judged). Note: a backup whose schema_version is newer than the app's is judged like
    any other here, whereas the app's own restore refuses it (see read_backup)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")   # a console with a legacy code page must not stop the report
    try:
        manifest, library = read_backup(path)
    except BadBackup as e:
        print(f"check: {_safe(Path(path).name, 80)} cannot be used: {e}.", file=sys.stderr)
        return 2
    rows = []
    for r in library["reels"]:
        if isinstance(r, dict):
            raw = r.get("raw")
            rows.append((r, raw[:RAW_MAX] if isinstance(raw, str) and raw.strip() else ""))   # the app keeps at most 20,000 characters
    texts = [text for _, text in rows if text]
    verdicts = {}
    if texts:
        try:
            template, parsed = parse_with_page(texts)
        except Exception as e:  # noqa: BLE001  Playwright, Chromium or its install: say what to do, judge nothing
            why = str(e).splitlines()[0] if str(e) else ""
            print(f"check: Chromium could not be started ({type(e).__name__}: {_safe(why, 160)}). Run  uv run playwright install chromium  once, then try again.",
                  file=sys.stderr)
            return 3
        verdicts = {text: check_answer(text, lambda _t, notes=notes: notes, template) for text, notes in zip(texts, parsed)}
    app = manifest.get("app") if isinstance(manifest.get("app"), dict) else {}
    print(f"Reel Shelf backup {_safe(Path(path).name, 80)}: made {_safe(manifest.get('created_at'), 40) or '?'} by Reel Shelf {_safe(app.get('version_name'), 30) or '?'}, "
          f"{len(rows)} reels")
    passed = broke = none = failed_reels = 0
    broken_rules = []
    for r, text in rows:
        code = _safe(r.get("code") or "?", 40)
        if text:
            v = verdicts[text]
            names = failed(v)
            passed, broke = passed + (not names), broke + bool(names)
            broken_rules += [n for n in names if n not in broken_rules]
            print(f"{code:<16} {'PASS' if v['ok'] else 'FAIL'}  " + ", ".join(f"{rule} {'ok' if v[rule] else 'FAIL'}" for rule in RULES))
            print(f"{'':<16} {_how_it_ended(r)}")
            continue
        none += 1
        failed_reels += r.get("status") == "failed"
        print(f"{code:<16} no answer text")
        print(f"{'':<16} {_how_it_ended(r)}")
        why = r.get("last_fail") or r.get("error")
        if why:
            print(f"{'':<16} reason: {_safe(why, 300)}")
        elif r.get("notes_by") == "auto":
            print(f"{'':<16} these are quick notes written without the AI: was the on-phone AI model installed and chosen?")
    if none:
        print("  no answer text: the app does not keep the text of an answer that failed, only the reason (when it has one), so there is no verdict")
    for rule in broken_rules:
        print(f"  {rule}: {RULE_HELP[rule]}")
    print(f"{len(rows)} reels: {passed} PASS, {broke} FAIL, {none} without answer text ({failed_reels} of them failed on the phone)")
    if not texts:
        print("RESULT: nothing to judge: no reel has an answer text. Did Start run with the on-phone AI model installed and chosen?")
        return 1
    ok = not broke and not failed_reels
    print("RESULT: " + ("PASS: every stored answer passes every rule" if ok else "FAIL: see the lines above"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Notes evaluation data for the on-phone AI (synthetic placeholders only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate", help="write the synthetic fixture (the same bytes every run)")
    gen.add_argument("--out", type=Path, default=FIXTURE, help="where to write it (default: tests/fixtures/notes_eval/reels.json)")
    mk = sub.add_parser("make-backup", help="write the fixture as a Reel Shelf backup ZIP for Restore on a phone (the same bytes every run)")
    mk.add_argument("--out", type=Path, default=Path("notes-eval-backup.zip"), help="where to write it (default: notes-eval-backup.zip here)")
    ck = sub.add_parser("check", help="judge the answers in a backup the app made after the run (exit 0 pass, 1 fail, 2 not a usable backup, 3 no Chromium)")
    ck.add_argument("zip", type=Path, help="the backup ZIP copied back from the phone")
    args = ap.parse_args(argv)
    if args.cmd == "generate":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(fixture_bytes())
        print(f"wrote {args.out}")
        return 0
    if args.cmd == "make-backup":
        return make_backup(args.out)
    return check(args.zip)


if __name__ == "__main__":
    sys.exit(main())
