"""A library written by any released version opens with today's page and is saved back without losing anything (R4-1).

tests/fixtures/library/<version>/ holds reels.json and shots.json exactly as the page code of that release wrote them
(see its README and tests/fixtures/make_library_fixtures.py; the data is synthetic). Each is loaded by the CURRENT page
(loadDb, Shots.load), the page saves it again the way it does in use, and the saved text is compared with the loaded one
by a recursive diff. The only differences allowed are the ones listed by expected() below, with the reason for each.
Anything else (a lost reel, a lost or changed field, a lost screenshot record, an extra key) fails the test.

No network, no device: Chromium at phone size with the fake window.RN of test_phone_app.py."""
import json
import re
from pathlib import Path

import pytest

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)
from test_shots import SHOTS_RN

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "library"


def _version_key(name):
    return tuple(int(x) for x in name.split("."))


# only folders named like a version: a folder of something else (for example a made-up "newer" library) is not a release
VERSIONS = sorted((p.name for p in FIXTURES.iterdir() if p.is_dir() and re.fullmatch(r"\d+(\.\d+)+", p.name)), key=_version_key) if FIXTURES.is_dir() else []
NEWEST = "1.3.11"


def texts(version):
    d = FIXTURES / version
    return (d / "reels.json").read_text(encoding="utf-8"), (d / "shots.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the recursive diff

def _identity(items):
    """How the items of a list are matched up: by code (reels) or by id (titles, quotes, products, categories), else by place."""
    for key in ("code", "id"):
        if items and all(isinstance(x, dict) and isinstance(x.get(key), str) for x in items) and len({x[key] for x in items}) == len(items):
            return key
    return None


def diff(old, new, path=()):
    """Every difference between two parsed JSON values, as tuples:
    ("removed", path, old) | ("changed", path, old, new) | ("added", path, new).
    A path is a tuple of dict keys, list identities (reel code, item id) or list places. An added or removed subtree is one entry."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in old:
            out += diff(old[k], new[k], path + (k,)) if k in new else [("removed", path + (k,), old[k])]
        out += [("added", path + (k,), new[k]) for k in new if k not in old]
        return out
    if isinstance(old, list) and isinstance(new, list):
        key = _identity(old)
        if key and all(isinstance(x, dict) and isinstance(x.get(key), str) for x in new) and len({x[key] for x in new}) == len(new):
            a, b = {x[key]: x for x in old}, {x[key]: x for x in new}
        else:
            a, b = dict(enumerate(old)), dict(enumerate(new))
        return diff(a, b, path)
    if type(old) is not type(new) or old != new:
        return [("changed", path, old, new)]
    return []


def show(entries):
    return "\n".join("  %s %s %s" % (e[0], " > ".join(map(str, e[1])), " -> ".join(json.dumps(v, ensure_ascii=False)[:80] for v in e[2:])) for e in entries)


def check_diff(actual, expected, what):
    unexpected = [e for e in actual if e not in expected]
    missing = [e for e in expected if e not in actual]
    assert not unexpected, "%s: the page changed a saved library in ways nobody listed (lost or changed data?):\n%s" % (what, show(unexpected))
    assert not missing, "%s: a listed change did not happen (update EXPECTED if the page changed on purpose):\n%s" % (what, show(missing))


# ---------------------------------------------------------------- what the page is expected to change when it opens an old library
#
# These are the ONLY allowed differences between a fixture and what the current page saves back (reels.json).
# Everything in them is a migration that loadDb / Verify.migrate does on purpose:
#
# 1. loadDb (local.js): a reel left "working" (the app was closed or killed while it was written) becomes "done" if it
#    has notes, else "new", so it is picked up again. Every fixture ends with one such reel, FIXA0006, because the
#    generator closes the app in the middle of writing it. It has no notes, so it becomes "new".
# 2. loadDb: an author that is not an Instagram username ("Media", a label of the old export) is emptied. No fixture has
#    one (a released version since 1.3.5 never writes it), so it is covered by the hand-made library at the end of this file.
# 3. Verify.migrate (verify.js, run when the page opens, once per change of rules, db.verify_rules): libraries from before
#    the rules existed get `verify_rules: 4` and the titles are put back for a new online check (see RULES_*). The rule
#    version a library carries is read from the fixture, not assumed.
# 4. loadDb (R4-2): a library that has no `schema_version` gets `"schema_version": 1` (the number of the layout this page
#    reads; see SCHEMA in local.js). No released version wrote it, so every fixture gains exactly this one key, once.

CODE_WORKING = "FIXA0006"
WORKING = ("changed", ("reels", CODE_WORKING, "status"), "working", "new")
RULES_STAMP = ("added", ("verify_rules",), 4)
SCHEMA_STAMP = ("added", ("schema_version",), 1)


def expected(version):
    """The allowed differences for a fixture, from what the page of that version wrote. Returns a list of diff tuples."""
    reels = json.loads(texts(version)[0])
    out = [WORKING, SCHEMA_STAMP]
    rules = reels.get("verify_rules", 0)
    if rules < 4:
        out.append(RULES_STAMP if "verify_rules" not in reels else ("changed", ("verify_rules",), rules, 4))
    if rules < 2:
        # Rule 2 (1.3.3): a title that was checked online and not found ("Mushishi", answered "not found" with the date of
        # the check in `checked_at`) is put back to be checked again under the newer rules: `checked_at` is dropped, and
        # `verified` stays "unverified". The other titles are unchanged (the verified one has two agreeing sources, rule 4).
        mushishi = next(m for m in reels["media"] if m["id"] == "m-mushishi")
        out.append(("removed", ("media", "m-mushishi", "checked_at"), mushishi["checked_at"]))
    return out


# What Shots.process adds to shots.json: the list of reel captions already read ("reels": code -> signature). A reel whose
# caption was read after the last Process (FIXA0006 here) is read now and gets a signature. Nothing else is added, and
# no picture record (seen) is ever changed. An added entry must be for a reel that is in the library, and its value must
# have the shape the page writes (shots.js fromReels): "<length of the caption text>:<the reel's notes_at, or 0>", so
# FIXA0006 (a caption, no notes) is "97:0".
def expected_shots_additions(before, after, library):
    reels = {r["code"]: r for r in library["reels"]}
    out = []
    for code, sig in after["reels"].items():
        if code in before["reels"]:
            continue
        assert code in reels, "Process recorded a reel that is not in the library: %s" % code
        m = re.fullmatch(r"(\d+):(\d+)", sig)
        assert m and int(m[1]) > 0 and int(m[2]) == (reels[code].get("notes_at") or 0), "unexpected signature %r for %s" % (sig, code)
        out.append(("added", ("reels", code), sig))
    return out


# ---------------------------------------------------------------- the fake phone

# Counts what the page really wrote (the fake bridge of test_phone_app.py keeps only the last text).
COUNT_RN = r"""
(() => {
  const st = window.__rn;
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  const library = window.RN.store, list = window.RN.storeShots;
  window.RN.store = (j) => { const ok = library(j); if (ok !== false) { st.nStore = (st.nStore || 0) + 1; keep(); } return ok; };
  window.RN.storeShots = (j) => { const ok = list(j); if (ok !== false) { st.nShots = (st.nShots || 0) + 1; keep(); } return ok; };
})();
"""
LINK = "https://www.instagram.com/reel/SHARE0001/"

# The page's clock is pinned to the last timestamp in the fixtures (the generator's clock at its last step, 2026-01-06
# 00:00 UTC), as in make_library_fixtures.py, so a rule that depends on the date (a retry, an age limit) cannot make
# these results depend on the day the tests run. test_the_fixtures_are_there... checks that this really is their last timestamp.
FIXTURES_NOW = 1767657600000
FIXED_CLOCK = "window.__now = %d; Date.now = () => window.__now;" % FIXTURES_NOW


def open_fixture(pg, version=None, reels=None, shots=None, **extra):
    r, s = texts(version) if version else ("", "")
    pg.context.add_init_script(FIXED_CLOCK)
    pg.context.add_init_script(SHOTS_RN)
    pg.context.add_init_script(COUNT_RN)
    pg.open_with({"db": r if reels is None else reels, "shotsDb": s if shots is None else shots, **extra})


def shape_ok(reels, shots):
    """Valid JSON of the same shape: what a reader of the files (LibraryFile.valid, the old pages) relies on."""
    d, s = json.loads(reels), json.loads(shots)
    assert isinstance(d, dict) and isinstance(d["reels"], list) and all(isinstance(r, dict) and isinstance(r["code"], str) for r in d["reels"])
    assert isinstance(s, dict) and s["v"] == 1 and isinstance(s["seen"], dict) and isinstance(s["reels"], dict)
    return d, s


def timestamps(value):
    """Every millisecond timestamp (a number from 2020 on) anywhere in a parsed JSON value."""
    if isinstance(value, dict):
        value = value.values()
    elif not isinstance(value, list):
        return [value] if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 1.6e12 else []
    return [t for v in value for t in timestamps(v)]


def test_the_fixtures_are_there_for_every_released_version_that_has_a_tag():
    assert VERSIONS, "tests/fixtures/library is missing"
    assert NEWEST in VERSIONS and "1.3.6" in VERSIONS and "1.3.9" not in VERSIONS  # 1.3.9 was never released (no tag)
    for v in VERSIONS:
        assert (FIXTURES / v / "reels.json").is_file() and (FIXTURES / v / "shots.json").is_file(), v
    assert max(t for v in VERSIONS for name in texts(v) for t in timestamps(json.loads(name))) == FIXTURES_NOW


def test_the_diff_finds_what_it_must():
    old = {"reels": [{"code": "A", "n": 1, "k": [1, 2]}, {"code": "B", "n": 2}], "x": {"y": 1}, "t": "s"}
    assert diff(old, json.loads(json.dumps(old))) == []
    new = {"reels": [{"code": "B", "n": 2}, {"code": "A", "n": 1, "k": [1], "extra": 1}], "x": {}, "t": 5}  # reordered: not a difference
    assert sorted(map(repr, diff(old, new))) == sorted(map(repr, [
        ("removed", ("reels", "A", "k", 1), 2), ("added", ("reels", "A", "extra"), 1), ("removed", ("x", "y"), 1), ("changed", ("t",), "s", 5)]))
    assert diff({"r": [{"code": "A"}, {"code": "B"}]}, {"r": [{"code": "A"}]}) == [("removed", ("r", "B"), {"code": "B"})]
    assert diff({"a": 1}, {"a": True}) == [("changed", ("a",), 1, True)]  # a type change is a change


# ---------------------------------------------------------------- every released version

@pytest.mark.parametrize("version", VERSIONS)
def test_a_library_from_every_release_is_saved_back_without_losing_anything(phone, version):
    before = json.loads(texts(version)[0])
    codes = [r["code"] for r in before["reels"]]
    open_fixture(phone, version)
    assert phone.evaluate("() => Date.now()") == FIXTURES_NOW
    # the library as the page saves it in use (every change of a reel ends in saveDb)
    assert phone.evaluate("() => saveDb()") is True
    reels_text = phone.rn()["db"]
    assert phone.rn()["nStore"] >= 1, "the page did not write the library"
    after, _ = shape_ok(reels_text, texts(version)[1])
    assert [r["code"] for r in after["reels"]] == codes, "every reel survives, in the same order"
    assert len(after["reels"]) == len(codes) > 0
    check_diff(diff(before, after), expected(version), "reels.json of " + version)
    # a second save changes nothing more (the page's own result is stable)
    assert phone.evaluate("() => saveDb()") is True
    assert phone.rn()["db"] == reels_text


@pytest.mark.parametrize("version", VERSIONS)
def test_the_screenshot_list_and_the_library_survive_a_process_run(phone, version):
    """Process is the page's own way of saving the screenshot list (and the library, with the titles it found)."""
    before, before_shots = (json.loads(t) for t in texts(version))
    open_fixture(phone, version)  # no new pictures: listShots gives nothing, so only what was already read is in play
    phone.evaluate("() => Shots.process()")
    st = phone.rn()
    assert st["nShots"] >= 1, "the page did not write the screenshot list"
    after, after_shots = shape_ok(st["db"], st["shotsDb"])
    assert after_shots["v"] == before_shots["v"] == 1
    assert [r["code"] for r in after["reels"]] == [r["code"] for r in before["reels"]]
    check_diff(diff(before_shots, after_shots), expected_shots_additions(before_shots, after_shots, after), "shots.json of " + version)
    assert after_shots["seen"] == before_shots["seen"] and len(before_shots["seen"]) == 5, "no screenshot record is lost or changed"
    check_diff(diff(before, after), expected(version), "reels.json of %s after Process" % version)


@pytest.mark.parametrize("version", VERSIONS)
def test_sharing_a_link_to_an_old_library_adds_that_reel_and_nothing_else_changes(phone, version):
    before = json.loads(texts(version)[0])
    open_fixture(phone, version, shared=[LINK])
    phone.wait_for_function("() => window.__rn.nStore >= 1 && window.__rn.shared.length === 0")
    after, _ = shape_ok(phone.rn()["db"], texts(version)[1])
    assert [r["code"] for r in after["reels"]] == ["SHARE0001"] + [r["code"] for r in before["reels"]]
    added = next(r for r in after["reels"] if r["code"] == "SHARE0001")
    check_diff(diff(before, after), expected(version) + [("added", ("reels", "SHARE0001"), added)], "reels.json of %s after a share" % version)
    assert phone.rn()["shared"] == []


# ---------------------------------------------------------------- additive fields survive (the rule A1 and R4-2 rely on)

def _with_extras(reels_text):
    d = json.loads(reels_text)
    d["futureTopLevel"] = {"a": [1, 2, {"b": None}], "c": "text"}
    d["futureList"] = [3, 2, 1]
    for r in d["reels"]:  # every reel gets keys no released version knows, in every status
        r["futureFlag"] = True
        r["futureNested"] = {"list": [1, "two", None], "n": 3.5}
    by = {r["code"]: r for r in d["reels"]}
    by["FIXA0002"].update({"tries": 2, "last_fail_at": 1767312000000, "last_fail": "The AI model failed: out of memory", "next_try_at": 1767570000000})  # the retry fields (A1)
    for section in ("media", "quotes", "products", "inbox", "mediaTypes"):
        for item in d.get(section, []):
            item["futureItemKey"] = section
    return d


def test_unknown_top_level_and_per_reel_keys_survive_load_and_save(phone):
    d = _with_extras(texts(NEWEST)[0])
    open_fixture(phone, reels=json.dumps(d), shots=texts(NEWEST)[1])
    assert phone.evaluate("() => saveDb()") is True
    after = json.loads(phone.rn()["db"])
    for k in ("futureTopLevel", "futureList"):
        assert after[k] == d[k], k
    by = {r["code"]: r for r in after["reels"]}
    assert all(r["futureFlag"] is True and r["futureNested"] == {"list": [1, "two", None], "n": 3.5} for r in after["reels"])
    assert {k: by["FIXA0002"][k] for k in ("tries", "last_fail_at", "last_fail", "next_try_at")} == \
        {k: d["reels"][[r["code"] for r in d["reels"]].index("FIXA0002")][k] for k in ("tries", "last_fail_at", "last_fail", "next_try_at")}
    for section in ("media", "quotes", "products", "inbox", "mediaTypes"):
        assert after[section] and all(x["futureItemKey"] == section for x in after[section]), section
    # nothing else moved: the whole difference is the one listed migration
    check_diff(diff(d, after), expected(NEWEST), "a library with unknown keys")


def test_unknown_keys_inside_screenshot_records_survive_but_top_level_keys_of_shots_json_do_not(phone):
    """The screenshot list is rebuilt as {v, seen, reels} on load (shots.js), so new data for it goes INSIDE the entries
    of `seen` and `reels`, never as a new top-level key. If shots.js is ever changed to keep top-level keys, update this."""
    s = json.loads(texts(NEWEST)[1])
    s["futureTopLevel"] = {"a": 1}
    for rec in s["seen"].values():
        rec["futureKey"] = [1, 2]
    open_fixture(phone, reels=texts(NEWEST)[0], shots=json.dumps(s))
    phone.evaluate("() => Shots.process()")
    after = json.loads(phone.rn()["shotsDb"])
    assert all(rec["futureKey"] == [1, 2] for rec in after["seen"].values()) and len(after["seen"]) == 5
    assert "futureTopLevel" not in after and after["v"] == 1


# ---------------------------------------------------------------- the migrations no fixture contains (hand-made library)

def test_the_old_migrations_of_loaddb_do_what_the_allowlist_says_and_nothing_more(phone):
    """HAND-MADE, not written by any release: the cases of EXPECTED that the real fixtures cannot hold. A reel left
    "working" with notes becomes "done" (without notes "new"); an author that is only a label of Instagram's export
    ("Media", before 1.3.5) is emptied, a real username and a YouTube channel name are kept; every other field stays."""
    def reel(code, **kw):
        return {"code": code, "url": "https://www.instagram.com/reel/%s/" % code, "author": "", "collections": [], "status": "new", "added_at": 1, **kw}
    lib = {"reels": [reel("HAND0001", status="working", notes={"topic": "t"}, notes_by="meta", author="creator_x"),
                     reel("HAND0002", status="working"),
                     reel("HAND0003", author="Media", caption="c"),
                     reel("HAND0004", author="creator_y", status="done"),
                     {"code": "yt-HANDYT00001", "url": "https://www.youtube.com/shorts/HANDYT00001", "author": "Hand Made Channel", "collections": [],
                      "status": "done", "added_at": 2, "notes": {"topic": "y"}}],
           "inbox": [], "media": [], "mediaTypes": []}
    open_fixture(phone, reels=json.dumps(lib))
    assert phone.evaluate("() => saveDb()") is True
    after = json.loads(phone.rn()["db"])
    check_diff(diff(lib, after), [
        ("changed", ("reels", "HAND0001", "status"), "working", "done"),
        ("changed", ("reels", "HAND0002", "status"), "working", "new"),
        ("changed", ("reels", "HAND0003", "author"), "Media", ""),
        ("added", ("verify_rules",), 4),  # Verify.migrate on a library from before the rules
        SCHEMA_STAMP,  # loadDb: a library with no schema_version gets 1
    ], "the hand-made library")


# The migrations of Verify.migrate that DROP or DOWNGRADE titles. Every fixture holds only titles they leave alone (one
# verified by two sources, one "not found"), so this HAND-MADE library, not written by any release, holds every case.
# What the page does (verify.js, migrate), in this order, once per change of rules (`verify_rules`, absent = 0):
#   rules < 2  a title with verified "conflict", or "unverified" with a `checked_at`, is put back to be checked again:
#              verified "unverified", `checked_at` and `review` dropped
#   rules < 4  a title verified by ONE source (verified_by without a "+", and not "you" or "phone AI") is downgraded:
#              verified "unverified", `checked_at` and `check` dropped (verified_by and verified_at stay);
#              a title with `seasons` but no `seasons_by` loses `details_at` (looked up again)
#   rules < 3  every title that looks like a comment line or button ("12 likes Reply", "View 4 replies") is DELETED,
#              unless it is verified
#   then       verify_rules becomes 4
def _title(id_, text, **kw):
    m = {"id": id_, "title": text, "type": "movie", "year": None, "language": "", "aka": [], "genres": [], "ext": {}, "status": "want",
         "verified": "unverified", "confidence": 0.6, "updated_at": 1, "added_at": 1,
         "sources": [{"kind": "screenshot", "ref": "content://hand/1", "method": "ocr", "text": text, "confidence": 0.6, "at": 1}]}
    m.update(kw)
    return m


CHECKED = 1767225600000
SINGLE_CHECK = {"verdict": "verified", "by": "tmdb", "confidence": 0.9}
REVIEW = {"choices": [{"title": "Hand Made Film", "year": 2001}]}
HAND_TITLES = [
    _title("m-single", "Single Source Film", verified="verified", verified_by="tmdb", verified_at=CHECKED, checked_at=CHECKED, check=SINGLE_CHECK),
    _title("m-two", "Two Source Film", verified="verified", verified_by="tmdb+wikidata", verified_at=CHECKED, checked_at=CHECKED, check=SINGLE_CHECK),
    _title("m-you", "Chosen By You", verified="verified", verified_by="you", verified_at=CHECKED, checked_at=CHECKED),
    _title("m-ai", "Chosen By The Phone", verified="verified", verified_by="phone AI", verified_at=CHECKED, checked_at=CHECKED),
    _title("m-conflict", "Waiting For You", verified="conflict", checked_at=CHECKED, review=REVIEW),
    _title("m-notfound", "Not Found Film", checked_at=CHECKED, check={"verdict": "not_found"}),
    _title("m-fresh", "Never Checked Film"),
    _title("m-chrome", "12 likes Reply"),
    _title("m-chrome-verified", "View 4 replies", verified="verified", verified_by="tmdb+wikidata", verified_at=CHECKED),
    _title("m-conflict-chrome", "View 4 replies", verified="conflict", checked_at=CHECKED, review=REVIEW),
    _title("m-seasons", "Seasons Looked Up", verified="verified", verified_by="tmdb+wikidata", seasons=[{"n": 1, "episodes": 8}], details_at=CHECKED),
    _title("m-seasons-by", "Seasons Checked Twice", verified="verified", verified_by="tmdb+wikidata", seasons=[{"n": 1}], seasons_by="tmdb+anilist", details_at=CHECKED),
]
H = {m["id"]: m for m in HAND_TITLES}
SINGLE = [("changed", ("media", "m-single", "verified"), "verified", "unverified"),
          ("removed", ("media", "m-single", "checked_at"), CHECKED),
          ("removed", ("media", "m-single", "check"), SINGLE_CHECK)]
SEASONS = [("removed", ("media", "m-seasons", "details_at"), CHECKED)]
# the exact differences, per rule version the library carries; the other titles must come back untouched
HAND_EXPECTED = {
    0: [("added", ("verify_rules",), 4)] + SINGLE + SEASONS + [
        ("changed", ("media", "m-conflict", "verified"), "conflict", "unverified"),
        ("removed", ("media", "m-conflict", "checked_at"), CHECKED),
        ("removed", ("media", "m-conflict", "review"), REVIEW),
        ("removed", ("media", "m-notfound", "checked_at"), CHECKED),
        ("removed", ("media", "m-chrome"), H["m-chrome"]),                    # rule 3
        ("removed", ("media", "m-conflict-chrome"), H["m-conflict-chrome"])],  # reset by rule 2, then deleted by rule 3
    2: [("changed", ("verify_rules",), 2, 4)] + SINGLE + SEASONS + [  # rule 2 is done: the conflict and the not found stay as they are
        ("removed", ("media", "m-chrome"), H["m-chrome"]),
        ("removed", ("media", "m-conflict-chrome"), H["m-conflict-chrome"])],  # "conflict" is not "verified": deleted
    3: [("changed", ("verify_rules",), 3, 4)] + SINGLE + SEASONS,              # rules 2 and 3 are done: nothing is deleted or reset
}
HAND_KEPT = {0: ["m-single", "m-two", "m-you", "m-ai", "m-conflict", "m-notfound", "m-fresh", "m-chrome-verified", "m-seasons", "m-seasons-by"]}
HAND_KEPT[2] = HAND_KEPT[0]
HAND_KEPT[3] = HAND_KEPT[0] + ["m-chrome", "m-conflict-chrome"]


@pytest.mark.parametrize("rules", [0, 2, 3])
def test_hand_made_titles_that_the_verify_migration_downgrades_resets_or_deletes(phone, rules):
    """HAND-MADE (see the comment above): exactly the listed titles change, every other title and field comes back as it was."""
    lib = {"reels": [], "inbox": [], "media": HAND_TITLES, "mediaTypes": []}
    if rules:
        lib["verify_rules"] = rules
    open_fixture(phone, reels=json.dumps(lib))
    assert phone.evaluate("() => saveDb()") is True
    after = json.loads(phone.rn()["db"])
    check_diff(diff(lib, after), HAND_EXPECTED[rules] + [SCHEMA_STAMP], "the hand-made titles at rules %d" % rules)  # SCHEMA_STAMP: loadDb adds schema_version 1 (R4-2)
    assert sorted(m["id"] for m in after["media"]) == sorted(HAND_KEPT[rules]), "no title is lost beyond the listed ones"
    assert after["verify_rules"] == 4
