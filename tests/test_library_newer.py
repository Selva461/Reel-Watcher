"""A library saved by a NEWER Reel Shelf is never changed, and every library this version saves carries schema_version 1 (R4-2).

The Java side (LibraryFile: NEWER state, no restore from the backup, no rename, no write) is tested in
android/app-shell/app/src/test (JUnit). Here: what the page does with it, in Chromium at phone size with the fake
window.RN of test_phone_app.py, in two ways a newer library can reach the page:
- "phone": LibraryFile.java found the number and answers like a locked file: load() gives "" and libraryInfo says
  {"state": "newer", "found": 99, "supported": 1};
- "page": the phone knows nothing (an older bridge), it gives the text, and the page reads the number itself.
Every RN method the page calls is logged, so "nothing was written" is checked on the calls as well as on the files.
No network, no device."""
import json

import pytest

from test_library_safety import LINK, go, toast_has
from test_library_upgrade import NEWEST, VERSIONS, check_diff, diff, expected, open_fixture, shape_ok, texts
from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)
from test_shots import SHOTS_RN

FLAVOURS = ["phone", "page"]
SENTENCE = "This library was saved by a newer Reel Shelf. This version%s cannot open it safely and has not changed it. Install the newest Reel Shelf."

# What can change a library, the share queue or the check results. None of them may be called for a newer library.
WRITERS = {"store", "storeShots", "peekShared", "ackShared", "libraryStartNew", "dropBackup", "takeVerified", "saveFile", "verifyNow"}

# LibraryFile.java on the phone: a newer file is locked ("" instead of its text) and libraryInfo reports it.
NEWER_RN = r"""
(() => {
  const st = window.__rn;
  const newer = (w) => !!(st.newer && st.newer[w]);
  const load = window.RN.load, loadShots = window.RN.loadShots;
  Object.assign(window.RN, {
    appVersion: () => (st.phoneSaysNewer ? "9.9.9" : ""),
    // what the phone does when asked to set a file aside (LibraryFile.startNew): it would rename it away. A newer file must never get here.
    libraryStartNew: (w) => { if (w === "shots") { st.shotsBadFile = st.shotsDb; st.shotsDb = ""; } else { st.badFile = st.db; st.db = ""; } return true; },
    dropBackup: () => true,
    saveUnreadable: (id, w) => setTimeout(() => rnDone(id, true, "Downloads/ReelShelf/" + w + "-unreadable-20260101-000000.txt"), 5),
  });
  if (st.phoneSaysNewer) Object.assign(window.RN, {
    load: () => (newer("reels") ? "" : load()),
    loadShots: () => (newer("shots") ? "" : loadShots()),
    libraryInfo: (w) => JSON.stringify(newer(w) ? { state: "newer", found: st.newer[w], supported: 1, bad: "", notice: "" } : { state: "ok", bad: "", notice: "" }),
  });
})();
"""
# Logs every call the page makes to the phone: [name, ...short string arguments]. Added last, so it wraps everything above.
LOG_RN = r"""
(() => {
  const st = window.__rn;
  st.log = [];
  for (const k of Object.keys(window.RN)) {
    const f = window.RN[k];
    if (typeof f === "function") window.RN[k] = (...a) => { st.log.push([k, ...a.filter((x) => typeof x === "string" && x.length < 40)]); return f(...a); };
  }
})();
"""


def newer_reels():
    d = json.loads(texts(NEWEST)[0])
    d["schema_version"] = 99
    d["fieldOfTheFuture"] = {"renamed": [1, 2, 3]}
    return json.dumps(d)


def newer_shots():
    s = json.loads(texts(NEWEST)[1])
    s["v"] = 99
    return json.dumps(s)


def open_newer(pg, flavour, reels, shots, newer=("reels", "shots"), hash_="#/", **extra):
    for script in (SHOTS_RN, NEWER_RN, LOG_RN):
        pg.context.add_init_script(script)
    state = {"db": reels, "shotsDb": shots, "shared": [LINK], **extra}
    if flavour == "phone":
        state["phoneSaysNewer"] = True
        state["newer"] = {w: 99 for w in newer}
    pg.open_with(state, hash_)


def calls(pg):
    return [e[0] for e in pg.rn()["log"]]


def settle(pg):
    pg.wait_for_timeout(300)  # let anything the page started on its own run


def newer_screen(pg):
    pg.get_by_text("This library was saved by a newer Reel Shelf.").first.wait_for()


def assert_untouched(pg, reels, shots):
    rn = pg.rn()
    assert rn["db"] == reels, "the library is byte for byte as it was"
    assert rn["shotsDb"] == shots, "the screenshot list is byte for byte as it was"
    assert rn["shared"] == [LINK], "the shared reel is still waiting, not acknowledged"
    assert not WRITERS & set(calls(pg)), "the page called something that can change a library: %s" % sorted(WRITERS & set(calls(pg)))
    assert "badFile" not in rn and "shotsBadFile" not in rn, "nothing was set aside"


# ---------------------------------------------------------------- a newer library

@pytest.mark.parametrize("flavour", FLAVOURS)
def test_a_newer_library_shows_the_newer_screen_and_nothing_is_written(phone, flavour):
    reels, shots = newer_reels(), newer_shots()
    open_newer(phone, flavour, reels, shots)
    newer_screen(phone)
    settle(phone)
    version = " (9.9.9)" if flavour == "phone" else ""  # the phone tells the page its version (appVersion); an older bridge does not
    assert SENTENCE % version in " ".join(phone.inner_text("#app").split())
    assert phone.locator("#app button").all_inner_texts() == ["Save a copy to Downloads"], "one button: no start new, no try again"
    assert_untouched(phone, reels, shots)
    for route in ("#/settings", "#/inbox", "#/shots", "#/r/FIXA0001", "#/check", "#/"):  # every screen is the newer screen
        go(phone, route)
        newer_screen(phone)
        settle(phone)
        assert_untouched(phone, reels, shots)
    phone.reload()
    newer_screen(phone)
    settle(phone)
    assert_untouched(phone, reels, shots)


@pytest.mark.parametrize("flavour", FLAVOURS)
def test_save_a_copy_asks_the_phone_to_save_the_file_and_does_nothing_else(phone, flavour):
    reels, shots = newer_reels(), newer_shots()
    open_newer(phone, flavour, reels, shots)
    newer_screen(phone)
    settle(phone)
    before = len(phone.rn()["log"])
    phone.get_by_role("button", name="Save a copy to Downloads").click()
    toast_has(phone, "Saved to Downloads/ReelShelf/reels-unreadable-")
    settle(phone)
    assert phone.rn()["log"][before:] == [["saveUnreadable", "reels"]], "that call and no other"
    assert_untouched(phone, reels, shots)
    newer_screen(phone)


@pytest.mark.parametrize("flavour", FLAVOURS)
def test_the_nightly_run_on_a_newer_library_ends_without_touching_anything(phone, flavour):
    reels, shots = newer_reels(), newer_shots()
    open_newer(phone, flavour, reels, shots, night=True)
    phone.wait_for_function("() => window.__rn.nightDone === 1")
    settle(phone)
    rn = phone.rn()
    assert rn["nightDone"] == 1 and not rn.get("work")
    assert_untouched(phone, reels, shots)
    assert not {"generate", "fetchPage", "readShots", "verifyNow", "readReelVideo"} & set(calls(phone)), "no work was started"


# ---------------------------------------------------------------- a newer screenshot list (the library itself is fine)

@pytest.mark.parametrize("flavour", FLAVOURS)
def test_a_newer_screenshot_list_is_not_set_aside_or_saved_over(phone, flavour):
    reels, shots = texts(NEWEST)[0], newer_shots()
    open_newer(phone, flavour, reels, shots, newer=("shots",), shared=[])
    phone.wait_for_selector("#app > *")
    go(phone, "#/shots")
    phone.get_by_text("The screenshot list is not open").wait_for()
    assert "saved by a newer Reel Shelf" in phone.inner_text("#app")
    toast_has(phone, "saved by a newer Reel Shelf")
    phone.evaluate("() => Shots.process()")  # nothing is read for a list that cannot be saved
    go(phone, "#/inbox")
    go(phone, "#/shots")  # every visit tries again, and every visit changes nothing
    phone.get_by_text("The screenshot list is not open").wait_for()
    settle(phone)
    rn = phone.rn()
    assert rn["shotsDb"] == shots and "shotsBadFile" not in rn and not rn.get("shotsStores")
    assert not {"libraryStartNew", "storeShots", "readShots", "listShots"} & set(calls(phone)), calls(phone)
    assert sum(1 for c in calls(phone) if c == "loadShots") >= 2, "it looked again, and only looked"
    assert phone.evaluate("() => saveDb()") is True, "the library itself is not locked"
    assert json.loads(phone.rn()["db"])["schema_version"] == 1


# ---------------------------------------------------------------- the number: odd values (the same list as LibraryFileTest)

#   JSON text of the value, and how the page saves it back (None: newer than what this version reads (1), so it is never saved)
ODD = [("null", "1"), ("0", "0"), ("-3", "-3"), ("0.5", "0.5"), ("1", "1"), ("1.0", "1"),
       ('"2"', '"2"'), ('"99"', '"99"'), ("true", "true"), ("[7]", "[7]"), ('{"n": 2}', '{"n":2}'),
       ("2", None), ("2.0", None), ("1.5", None), ("1.0000001", None), ("9999999999999999999999", None), ("1e308", None), ("1e999", None)]


@pytest.mark.parametrize("literal,saved_as", ODD, ids=[o[0] for o in ODD])
def test_only_a_number_above_what_this_version_reads_is_newer(phone, literal, saved_as):
    text = '{"schema_version": %s, "reels": [{"code": "ODD00001", "url": "https://www.instagram.com/reel/ODD00001/", "status": "new", "added_at": 1}], "inbox": [], "media": [], "mediaTypes": []}' % literal
    shots = texts(NEWEST)[1]
    open_newer(phone, "page", text, shots)
    if saved_as is None:
        newer_screen(phone)
        settle(phone)
        assert_untouched(phone, text, shots)
        return
    phone.wait_for_function("() => window.__rn.shared.length === 0")  # the library opened and took the shared reel
    assert phone.get_by_text("saved by a newer Reel Shelf").count() == 0
    assert phone.evaluate("() => saveDb()") is True
    after = json.loads(phone.rn()["db"])
    assert json.dumps(after["schema_version"], separators=(",", ":")) == saved_as, "a value that is no sign of a newer version is kept as it is (null: stamped)"
    assert [r["code"] for r in after["reels"]] == ["SHARE0001", "ODD00001"]


# ---------------------------------------------------------------- the stamp

@pytest.mark.parametrize("version", VERSIONS)
def test_a_library_of_every_release_gets_schema_version_1_and_nothing_else_changes(phone, version):
    before = json.loads(texts(version)[0])
    assert "schema_version" not in before, "no released version wrote it: the page adds it"
    open_fixture(phone, version)
    assert phone.evaluate("() => saveDb()") is True
    after, _ = shape_ok(phone.rn()["db"], texts(version)[1])
    assert after["schema_version"] == 1 and type(after["schema_version"]) is int
    check_diff(diff(before, after), expected(version), "reels.json of %s with the stamp" % version)


def test_a_library_already_at_1_is_not_changed_by_another_save(phone):
    open_fixture(phone, NEWEST)
    assert phone.evaluate("() => saveDb()") is True
    first = phone.rn()["db"]
    assert json.loads(first)["schema_version"] == 1
    for _ in range(3):  # closed and opened again, saved again: the same bytes
        phone.open_with({"db": first, "shotsDb": texts(NEWEST)[1]})
        assert phone.evaluate("() => saveDb()") is True
        assert phone.rn()["db"] == first
    assert diff(json.loads(first), json.loads(phone.rn()["db"])) == []


def test_a_new_library_has_the_number_from_its_first_save(phone):
    phone.open_with({"db": "", "shared": [LINK]})
    phone.wait_for_function("() => window.__rn.db !== '' && window.__rn.shared.length === 0")
    after = db_of(phone)
    assert [r["code"] for r in after["reels"]] == ["SHARE0001"]
    assert after["schema_version"] == 1
