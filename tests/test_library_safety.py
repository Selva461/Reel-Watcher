"""A library file that cannot be read is never replaced by an empty one (assets/local/local.js, shots.js).

The Java side (LibraryFile: backup, restore, lock, set aside) is tested in android/app-shell/app/src/test (JUnit).
Here: what the page does with what the phone reports, with a fake bridge. No network, no device."""
import json

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)
from test_shots import L, SHOTS_RN

GOOD = json.dumps({"reels": [{"code": f"OLD{i:05d}", "url": f"https://www.instagram.com/reel/OLD{i:05d}/", "status": "done",
                              "notes": {"topic": f"topic {i}"}, "added_at": 1} for i in range(20)], "inbox": []})
DAMAGED = GOOD[: len(GOOD) // 2]
LINK = "https://www.instagram.com/reel/SHARE0001/"

# The phone's side of it: reports "unreadable" like LibraryFile does (load gives nothing, saves are refused).
LIB_RN = r"""
(() => {
  const st = window.__rn;
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  const lib = (w) => { st.lib = st.lib || {}; return (st.lib[w] = st.lib[w] || {}); };
  const locked = () => !!(st.lib && st.lib.reels && st.lib.reels.state === "unreadable");
  Object.assign(window.RN, {
    load: () => (locked() ? "" : st.db),
    store: (j) => { if (locked() || st.storeRefused) return false; st.db = j; st.stores = (st.stores || 0) + 1; keep(); return true; },
    libraryInfo: (w) => { const i = lib(w); const o = { state: i.state || "ok", bad: i.bad || "", notice: i.notice || "" }; i.notice = ""; keep(); return JSON.stringify(o); },
    libraryStartNew: (w) => { st.calls.push(["libraryStartNew", w]); if (st.startNewFails) { keep(); return false; }
      if (w === "shots") { st.shotsBadFile = st.shotsDb; st.shotsDb = ""; } else { st.badFile = st.db; st.db = ""; }  // renamed away, kept
      lib(w).state = "started_new"; keep(); return true; },
    dropBackup: (w) => { st.calls.push(["dropBackup", w]); keep(); return true; },
    saveUnreadable: (id, w) => { st.calls.push(["saveUnreadable", w]); keep();
      setTimeout(() => rnDone(id, true, "Downloads/ReelShelf/" + w + "-unreadable-20260101-000000.txt"), 5); },
    loadShots: () => (lib("shots").state === "unreadable" ? "" : st.shotsDb || ""),
    storeShots: (j) => { if (lib("shots").state === "unreadable") return false; st.shotsDb = j; st.shotsStores = (st.shotsStores || 0) + 1; keep(); return true; },
  });
})();
"""


def unreadable(**extra):
    return {"db": DAMAGED, "shared": [LINK], "lib": {"reels": {"state": "unreadable"}}, **extra}


def locked_screen(pg):
    pg.get_by_text("Your library file could not be read").first.wait_for()


def toast_has(pg, text):
    pg.wait_for_function("t => document.getElementById('toast').textContent.includes(t)", arg=text)


def test_a_damaged_library_is_never_saved_over_even_without_help_from_the_phone(phone):
    phone.open_with({"db": DAMAGED, "shared": [LINK]})  # an older bridge: the page itself notices the damage
    locked_screen(phone)
    rn = phone.rn()
    assert rn["db"] == DAMAGED, "the damaged file must stay exactly as it was"
    assert rn["shared"] == [LINK], "the shared reel waits in its queue"
    phone.reload()
    locked_screen(phone)
    assert phone.rn()["db"] == DAMAGED


def test_the_page_locks_when_the_phone_says_unreadable_and_saves_nothing(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with(unreadable())
    locked_screen(phone)
    for name in ("Try again", "Save the unreadable file to Downloads", "Start a new library"):
        assert phone.get_by_role("button", name=name).count() == 1
    rn = phone.rn()
    assert rn["db"] == DAMAGED and not rn.get("stores")
    assert rn["shared"] == [LINK]
    phone.goto(phone.url.split("#")[0] + "#/settings")  # every screen is the recovery screen
    locked_screen(phone)
    assert not phone.rn().get("stores")


def test_a_file_the_page_cannot_use_locks_even_when_the_phone_thought_it_fine(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with({"db": '{"reels": {"not": "a list"}}', "shared": [LINK]})
    locked_screen(phone)
    assert not phone.rn().get("stores") and phone.rn()["shared"] == [LINK]
    phone.reload()
    phone.open_with({"db": "[1, 2]", "shared": [LINK]})
    locked_screen(phone)
    assert not phone.rn().get("stores")


def test_try_again_opens_the_library_once_the_file_is_readable_and_takes_the_waiting_shares(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with(unreadable())
    locked_screen(phone)
    phone.get_by_role("button", name="Try again").click()
    toast_has(phone, "Still unreadable")
    assert phone.rn()["shared"] == [LINK]
    phone.evaluate("g => { window.__rn.lib.reels.state = 'ok'; window.__rn.db = g; }", GOOD)  # the phone restored it
    phone.get_by_role("button", name="Try again").click()
    phone.wait_for_function("() => !document.body.innerText.includes('Library not opened')")
    phone.wait_for_function("() => window.__rn.stores >= 1")
    reels = db_of(phone)["reels"]
    assert len(reels) == 21 and {r["code"] for r in reels} >= {"OLD00000", "SHARE0001"}
    assert phone.rn()["shared"] == []


def test_a_recovered_library_says_so_and_loads_the_old_reels(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with({"db": GOOD, "lib": {"reels": {"state": "recovered", "notice": "recovered", "bad": "reels.json.bad-20260101-000000"}}})
    toast_has(phone, "restored")
    toast_has(phone, "reels.json.bad-20260101-000000")
    assert len(db_of(phone)["reels"]) == 20


def test_start_a_new_library_keeps_the_damaged_file_and_a_failure_changes_nothing(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with(unreadable(startNewFails=True))
    locked_screen(phone)
    phone.get_by_role("button", name="Start a new library").click()
    toast_has(phone, "Nothing was changed")
    locked_screen(phone)  # still locked: a failed recovery never resets the library
    assert phone.rn()["db"] == DAMAGED and phone.rn()["shared"] == [LINK]
    phone.evaluate("window.__rn.startNewFails = false")
    phone.get_by_role("button", name="Start a new library").click()
    phone.wait_for_function("() => !document.body.innerText.includes('Library not opened')")
    rn = phone.rn()
    assert ["libraryStartNew", "reels"] in rn["calls"]
    assert rn["badFile"] == DAMAGED, "the unreadable file was set aside, not deleted"
    phone.wait_for_function("() => window.__rn.stores >= 1")
    assert [r["code"] for r in db_of(phone)["reels"]] == ["SHARE0001"]  # the new library holds what was shared meanwhile


def test_the_unreadable_file_can_be_saved_to_downloads_from_the_recovery_screen(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with(unreadable())
    locked_screen(phone)
    phone.get_by_role("button", name="Save the unreadable file to Downloads").click()
    toast_has(phone, "Saved to Downloads/ReelShelf/reels-unreadable-")
    assert ["saveUnreadable", "reels"] in phone.rn()["calls"]
    assert phone.rn()["db"] == DAMAGED


def test_a_hundred_shared_reels_are_one_save(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with({"db": GOOD, "shared": [LINK]})
    phone.wait_for_function("() => window.__rn.stores >= 1")
    one = phone.rn()["stores"]
    links = [f"https://www.instagram.com/reel/BATCH{i:04d}/" for i in range(100)]
    phone.open_with({"db": GOOD, "shared": links})
    phone.wait_for_function("() => window.__rn.stores >= 1")
    assert phone.rn()["stores"] == one, "the number of saves does not grow with the number of shared items"
    assert len(db_of(phone)["reels"]) == 120 and phone.rn()["shared"] == []


def go(pg, route):
    pg.evaluate("r => { location.hash = r; }", route)  # after the page has loaded with its state (open_with's own hash would run on the old page)


def test_delete_all_drops_the_backup_only_when_the_empty_library_was_saved(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with({"db": GOOD})
    go(phone, "#/settings")
    phone.click("#wipe")
    phone.wait_for_function("() => window.__rn.calls.some((c) => c[0] === 'dropBackup')")
    assert ["dropBackup", "reels"] in phone.rn()["calls"] and db_of(phone)["reels"] == []
    phone.open_with({"db": GOOD, "storeRefused": True})  # a failed save keeps the backup (and the file)
    go(phone, "#/settings")
    phone.click("#wipe")
    toast_has(phone, "Deleted")
    assert not any(c[0] == "dropBackup" for c in phone.rn()["calls"]) and len(db_of(phone)["reels"]) == 20


def test_the_nightly_run_with_an_unreadable_library_ends_without_touching_anything(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with(unreadable(night=True))
    phone.wait_for_function("() => window.__rn.nightDone === 1")
    rn = phone.rn()
    assert rn["db"] == DAMAGED and not rn.get("stores") and rn["shared"] == [LINK] and not rn.get("work")


def test_a_library_from_the_previous_version_loads_and_saves_with_every_key_kept(phone):
    old = {"reels": [{"code": "R0001", "url": "https://www.instagram.com/reel/R0001/", "status": "done", "notes": {"topic": "t"}, "added_at": 1}],
           "inbox": [], "media": [], "mediaTypes": [], "verify_rules": 4, "lastNight": {"at": 5, "log": ["a"]}, "futureKey": {"a": [1, 2]}}
    phone.context.add_init_script(LIB_RN)
    phone.open_with({"db": json.dumps(old), "shared": [LINK]})
    phone.wait_for_function("() => window.__rn.stores >= 1")
    after = db_of(phone)
    for k in ("inbox", "media", "mediaTypes", "verify_rules", "lastNight", "futureKey"):
        assert after[k] == old[k], k
    assert [r["code"] for r in after["reels"]] == ["SHARE0001", "R0001"]


def test_the_screenshot_list_that_was_set_aside_says_so(phone):
    phone.context.add_init_script(LIB_RN)
    phone.open_with({"db": GOOD, "lib": {"shots": {"state": "started_new", "notice": "started_new", "bad": "shots.json.bad-1"}}})
    go(phone, "#/shots")
    toast_has(phone, "set aside and will be rebuilt")
    phone.open_with({"db": GOOD, "shotsDb": '{"seen": [1]'})  # the page cannot use it either: the phone is asked to set it aside
    go(phone, "#/shots")
    toast_has(phone, "could not be read")
    assert ["libraryStartNew", "shots"] in phone.rn()["calls"]


DAMAGED_SHOTS = '{"v": 1, "seen": {"content://x/1": {"m": 1, "st": "found", "n": "a.jpg", "f": "S", "c": ["Heat"], "x": ""}'  # cut short
PIC = {"k": "content://x/tree/primary%3AScreens/document/9", "n": "Screenshot_9.jpg", "f": "DCIM/Screenshots", "m": 9, "s": 1}
SHOT_STATE = {"folders": [{"uri": "content://x/tree/primary%3AScreens", "name": "DCIM/Screenshots"}], "pics": [PIC],
              "text": {PIC["k"]: [L("Movie: Interstellar", 600)]}}


def shots_phone(pg):
    pg.context.add_init_script(SHOTS_RN)
    pg.context.add_init_script(LIB_RN)  # after SHOTS_RN: its loadShots/storeShots know about "unreadable"


def test_an_unreadable_screenshot_list_is_set_aside_rebuilt_and_saves_again(phone):
    # the phone reports "unreadable", loadShots() gives "", and there is no good backup to restore
    shots_phone(phone)
    phone.open_with({"db": GOOD, "shotsDb": DAMAGED_SHOTS, "lib": {"shots": {"state": "unreadable"}}, **SHOT_STATE})
    go(phone, "#/shots")
    toast_has(phone, "set aside and will be rebuilt")
    rn = phone.rn()
    assert ["libraryStartNew", "shots"] in rn["calls"]
    assert rn["shotsBadFile"] == DAMAGED_SHOTS, "the damaged list is kept, not deleted"
    assert json.loads(rn["db"])["reels"] == json.loads(GOOD)["reels"], "the library's reels are not touched"
    phone.click("#go")  # rebuild: read the pictures again, and the list is saved again
    phone.wait_for_function("() => window.__rn.shotsStores >= 1")
    saved = json.loads(phone.rn()["shotsDb"])
    assert list(saved["seen"]) == [PIC["k"]] and saved["seen"][PIC["k"]]["c"] == ["Interstellar"]
    assert phone.rn()["shotsBadFile"] == DAMAGED_SHOTS


def test_a_screenshot_list_that_cannot_be_set_aside_is_left_alone_and_tried_again_later(phone):
    shots_phone(phone)
    phone.open_with({"db": GOOD, "shotsDb": DAMAGED_SHOTS, "startNewFails": True, "lib": {"shots": {"state": "unreadable"}}, **SHOT_STATE})
    go(phone, "#/shots")
    toast_has(phone, "could not be set aside")
    phone.get_by_text("The screenshot list is not open").wait_for()
    go(phone, "#/inbox")
    go(phone, "#/shots")  # every visit tries again, and every visit changes nothing while it fails
    phone.get_by_text("The screenshot list is not open").wait_for()
    phone.evaluate("window.__rn.calls.length")  # let the page settle
    rn = phone.rn()
    assert rn["shotsDb"] == DAMAGED_SHOTS and not rn.get("shotsStores"), "nothing was saved over the damaged list"
    assert not any(c[0] == "readShots" for c in rn["calls"]), "no pictures are read for a list that cannot be saved"
    assert sum(1 for c in rn["calls"] if c == ["libraryStartNew", "shots"]) >= 2
    phone.evaluate("window.__rn.startNewFails = false")  # the phone can set it aside now
    go(phone, "#/inbox")
    go(phone, "#/shots")
    toast_has(phone, "set aside and will be rebuilt")
    assert phone.rn()["shotsBadFile"] == DAMAGED_SHOTS
    phone.click("#go")
    phone.wait_for_function("() => window.__rn.shotsStores >= 1")
    assert list(json.loads(phone.rn()["shotsDb"])["seen"]) == [PIC["k"]]
