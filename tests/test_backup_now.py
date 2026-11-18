"""Settings, Backup and restore, "Back up now" (S4-2): what the page sends to the phone and what it shows.

The Java side (LocalBridge.backupLibrary: snapshots, free space, the ZIP, the read-back, the clean-up) cannot run here: it is
checked by the JUnit tests of LibraryBackup, LibraryFile and BackupNow and, for the bridge itself, on a device (TESTING.md,
E40 to E43). Here: the page, in Chromium at phone size, with a fake window.RN whose backupLibrary records what it was
given and answers as the test says (success, a failure sentence, the Android 8 and 9 flag, or not at all until told).
Restoring is in tests/test_backup_restore.py (S4-3). No network, no device."""
import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_library_newer import calls, newer_reels, newer_shots, open_newer
from test_library_safety import LIB_RN, go, locked_screen, unreadable
from test_phone_app import phone, site  # noqa: F401  (pytest fixtures)
from test_shots import SHOTS_RN
from test_verify_online import media

NAME = "ReelShelf-backup-20261118-103000.zip"
PRIVACY_DESIGN = ("The backup contains all your reels, notes, watchlist, quotes and products. Anyone who gets the file can read them. "
                  "It does not contain your settings, API keys, AI models, pictures or videos.")
# shots.json is in the backup byte for byte: for each screenshot read, the first 300 characters of its text and its file name and folder
PRIVACY_SHOTS = "It also holds a short part of the text read from each of your screenshots, and their file names."
PRIVACY = PRIVACY_DESIGN + " " + PRIVACY_SHOTS
BACKUP_JAVA = Path(__file__).resolve().parents[1] / "android" / "app-shell" / "app" / "src" / "main" / "java" / "app" / "reelshelf" / "BackupNow.java"
SAFE_LIBRARY = json.dumps({"reels": [{"code": f"BK{i:05d}", "url": f"https://www.instagram.com/reel/BK{i:05d}/", "status": "done",
                                      "notes": {"topic": f"topic {i}"}, "added_at": 1} for i in range(3)],
                           "inbox": [], "media": [media("m-dune", "Dune"), media("m-heat", "Heat")]})

# The phone's side of LocalBridge.backupLibrary(id, countsJson): records the call, then answers as st.backup says.
BACKUP_RN = r"""
(() => {
  const st = window.__rn;
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  window.RN.backupLibrary = function (id, countsJson) {
    st.backupCalls = (st.backupCalls || []).concat([{ args: arguments.length, idIsNumber: typeof id === "number", counts: countsJson }]);
    keep();
    window.__backupId = id;
    const a = st.backup || {};
    if (a.hold) return;  // the test answers by hand
    setTimeout(() => (a.fail !== undefined ? rnDone(id, false, a.fail) : rnDone(id, true, typeof a.raw === "string" ? a.raw : JSON.stringify(a.ok))), 20);
  };
})();
"""


# A screenshot list the page cannot use: loading it would make the page ask the phone to set it aside (libraryStartNew).
BAD_SHOTS_RN = r"""
(() => {
  const st = window.__rn;
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  Object.assign(window.RN, {
    loadShots: () => "this is not a screenshot list",
    storeShots: () => false,
    libraryStartNew: (w) => { st.startNew = (st.startNew || []).concat([w]); keep(); return true; },
  });
})();
"""


def answer(**kw):
    a = {"name": NAME, "where": "Downloads/ReelShelf/" + NAME, "bytes": 5 * 1024 * 1024,
         "counts": {"reels": 3, "titles": 2, "screenshots": 4}, "uninstall_warning": False, "shots_skipped": False}
    a.update(kw)
    return a


def open_settings(pg, backup=None, scripts=(), **state):
    pg.set_default_timeout(8000)
    for s in (*scripts, BACKUP_RN):
        pg.context.add_init_script(s)
    pg.open_with({"db": SAFE_LIBRARY, "backup": {"ok": answer()} if backup is None else backup, **state}, "#/settings")
    pg.locator("#backupnow").wait_for()


def section(pg):
    return " ".join(pg.locator("#backup").inner_text().split())


def status(pg):
    return " ".join(pg.locator("#backup [role=status]").first.inner_text().split())


def tap(pg):
    pg.locator("#backupnow").click()


def backup_calls(pg):
    return pg.rn().get("backupCalls", [])


def wait_saved(pg):
    pg.locator("#backup [role=status]").filter(has_text="Saved to").wait_for()  # "Making the backup" is a status too


def release(pg, ok, text):
    pg.evaluate("([ok, t]) => rnDone(window.__backupId, ok, t)", [ok, text])


# ---------------------------------------------------------------- what the button sends and what it shows

def test_back_up_now_sends_the_counts_and_says_where_it_saved(phone):
    shots = json.dumps({"v": 1, "seen": {f"k{i}": {"m": 1, "st": "done", "n": "a", "f": "f", "c": [], "x": ""} for i in range(4)}, "reels": {}})
    open_settings(phone, scripts=[SHOTS_RN], shotsDb=shots)
    go(phone, "#/shots")  # the list is read when that screen opens; a backup never opens it itself
    phone.get_by_role("heading", name="Screenshots").wait_for()
    go(phone, "#/settings")
    phone.locator("#backupnow").wait_for()
    library = phone.rn()["db"]  # as the page left it after opening (it migrates old libraries by itself)
    tap(phone)
    wait_saved(phone)
    calls_ = backup_calls(phone)
    assert len(calls_) == 1
    assert calls_[0]["args"] == 1 + 1 and calls_[0]["idIsNumber"], "RN.backupLibrary(id, countsJson): nothing else"
    assert json.loads(calls_[0]["counts"]) == {"reels": 3, "titles": 2, "screenshots": 4}, "db.reels, db.media and the screenshots read"
    assert status(phone) == f"Saved to Downloads/ReelShelf/{NAME} (3 reels, 2 titles, 5 MB)"
    assert phone.locator("#backupnow").is_enabled() and phone.locator("#backupnow").inner_text() == "Back up now"
    assert phone.rn()["db"] == library and phone.rn()["shotsDb"] == shots, "a backup changes nothing in the library or the screenshot list"


def test_a_backup_does_not_open_the_screenshot_list_so_it_counts_none_that_are_not_loaded(phone):
    shots = json.dumps({"v": 1, "seen": {f"k{i}": {"m": 1, "st": "done", "n": "a", "f": "f", "c": [], "x": ""} for i in range(4)}, "reels": {}})
    open_settings(phone, scripts=[SHOTS_RN], shotsDb=shots)  # the Screenshots screen was never opened this time
    tap(phone)
    wait_saved(phone)
    assert json.loads(backup_calls(phone)[0]["counts"])["screenshots"] == 0, "not loaded: no number is made up, and the list is not read for this"


def test_a_backup_never_sets_an_unreadable_screenshot_list_aside(phone):
    open_settings(phone, scripts=[BAD_SHOTS_RN])
    tap(phone)
    wait_saved(phone)
    phone.wait_for_timeout(200)
    assert not phone.rn().get("startNew"), "libraryStartNew(shots) was not asked: the damaged list is left exactly as it is"
    assert json.loads(backup_calls(phone)[0]["counts"])["screenshots"] == 0
    go(phone, "#/shots")  # opening the Screenshots screen does ask (so the check above could have failed)
    phone.wait_for_function("(window.__rn.startNew || []).length === 1")
    assert phone.rn()["startNew"] == ["shots"]


def test_the_counts_follow_the_library_on_the_page_not_a_fixed_number(phone):
    one = json.dumps({"reels": [{"code": "ONE0001", "url": "https://www.instagram.com/reel/ONE0001/", "status": "new", "added_at": 1}], "inbox": []})
    open_settings(phone, db=one, backup={"ok": answer(counts={"reels": 1, "titles": 0, "screenshots": 0})})
    tap(phone)
    wait_saved(phone)
    assert json.loads(backup_calls(phone)[0]["counts"]) == {"reels": 1, "titles": 0, "screenshots": 0}
    assert "(1 reel, 0 titles, 5 MB)" in status(phone)


def test_the_size_is_in_kb_below_a_megabyte_and_in_mb_or_gb_above(phone):
    open_settings(phone)
    assert phone.evaluate("[1, 307200, 1048576, 5242880, 1610612736].map(backupSize)") == ["1 KB", "300 KB", "1 MB", "5 MB", "1.50 GB"]


def test_a_failure_shows_its_sentence_and_the_button_works_again(phone):
    sentence = "There is not enough free space on the phone for a backup: about 221 MB are needed and 150 MB are free. Free up some space and try again. Your library was not changed."
    open_settings(phone, backup={"fail": sentence})
    tap(phone)
    phone.locator("#backup [role=alert]").wait_for()
    assert " ".join(phone.locator("#backup [role=alert]").inner_text().split()) == sentence
    assert "Saved to" not in section(phone), "a failed backup is never reported as saved"
    assert phone.locator("#backupnow").is_enabled()
    phone.evaluate("a => { window.__rn.backup = { ok: a }; }", answer())  # the phone can do it this time
    tap(phone)
    wait_saved(phone)
    assert "Saved to" in status(phone) and phone.locator("#backup [role=alert]").count() == 0, "the old failure is gone"
    assert len(backup_calls(phone)) == 2


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", "{}", "null", ""])
def test_an_answer_the_page_cannot_use_is_a_failure_not_a_success(phone, raw):
    open_settings(phone, backup={"raw": raw})
    tap(phone)
    phone.locator("#backup [role=alert]").wait_for()
    assert "The backup could not be saved. Your library was not changed." in section(phone)
    assert "Saved to" not in section(phone)


def test_with_an_older_bridge_that_has_no_backup_the_page_says_so_and_does_not_break(phone):
    phone.set_default_timeout(8000)
    phone.open_with({"db": SAFE_LIBRARY}, "#/settings")  # the plain fake bridge: no backupLibrary
    phone.locator("#backupnow").wait_for()
    tap(phone)
    phone.locator("#backup [role=alert]").wait_for()
    assert "Open this inside the Reel Shelf app" in section(phone)
    assert phone.locator("#backupnow").is_enabled()


# ---------------------------------------------------------------- while it runs

def test_the_button_is_disabled_while_it_runs_and_a_second_click_does_nothing(phone):
    open_settings(phone, backup={"hold": True})
    btn = phone.locator("#backupnow")
    tap(phone)
    expect(btn).to_be_disabled()
    assert btn.inner_text() == "Backing up..."
    assert "Making the backup" in section(phone)
    btn.dispatch_event("click")
    phone.evaluate("backupNow()")  # the page's own guard, whatever the button does
    phone.wait_for_timeout(150)
    assert len(backup_calls(phone)) == 1, "one call to the phone, however often it is asked"
    release(phone, True, json.dumps(answer()))
    wait_saved(phone)
    expect(btn).to_be_enabled()
    assert btn.inner_text() == "Back up now"
    tap(phone)  # finished: it can be done again
    assert len(backup_calls(phone)) == 2


def test_the_progress_state_survives_leaving_and_coming_back_to_settings(phone):
    open_settings(phone, backup={"hold": True})
    tap(phone)
    expect(phone.locator("#backupnow")).to_be_disabled()
    go(phone, "#/")
    phone.locator("#backupnow").wait_for(state="detached")
    go(phone, "#/settings")
    expect(phone.locator("#backupnow")).to_be_disabled()  # still running: not startable a second time from here
    phone.locator("#backupnow").dispatch_event("click")
    phone.wait_for_timeout(150)
    assert len(backup_calls(phone)) == 1
    release(phone, True, json.dumps(answer()))
    wait_saved(phone)
    expect(phone.locator("#backupnow")).to_be_enabled()


def test_the_result_that_arrives_after_leaving_settings_is_there_when_you_come_back(phone):
    open_settings(phone, backup={"hold": True})
    tap(phone)
    go(phone, "#/")
    phone.locator("#backupnow").wait_for(state="detached")
    release(phone, True, json.dumps(answer()))
    phone.wait_for_timeout(100)
    go(phone, "#/settings")
    wait_saved(phone)
    assert status(phone).startswith("Saved to Downloads/ReelShelf/")


# ---------------------------------------------------------------- what the page says about it

def test_the_privacy_sentence_is_shown_exactly(phone):
    open_settings(phone)
    assert phone.get_by_text(PRIVACY, exact=True).is_visible()
    assert PRIVACY_DESIGN in section(phone), "the sentence of the design is all there"
    assert PRIVACY_SHOTS in section(phone), "and it says the screenshots' text and file names are in the file too"
    assert "Backup and restore" in phone.locator("#backup h2").inner_text()
    assert "never deletes old backups" in section(phone)
    assert "Restoring a backup is not in this version yet" not in section(phone), "restoring is built (S4-3)"
    assert "Restoring replaces your library with a backup after you confirm; the library you have now is kept on the phone, not deleted." in section(phone)


def test_android_8_and_9_are_told_the_file_goes_when_the_app_is_uninstalled(phone):
    where = "Android/data/app.reelshelf/files/Download/ReelShelf/" + NAME
    open_settings(phone, backup={"ok": answer(where=where, uninstall_warning=True)})
    assert "uninstall" not in section(phone), "no warning before there is a file"
    tap(phone)
    wait_saved(phone)
    text = section(phone)
    assert f"Saved to {where}" in text
    assert "it is deleted if you uninstall Reel Shelf" in text
    assert "Copy it somewhere else" in text


def test_newer_android_gets_no_uninstall_warning(phone):
    open_settings(phone)
    tap(phone)
    wait_saved(phone)
    assert "uninstall" not in section(phone)


def test_a_screenshot_list_that_could_not_be_included_is_said_once(phone):
    open_settings(phone, backup={"ok": answer(shots_skipped=True)})
    tap(phone)
    wait_saved(phone)
    assert section(phone).count("The list of read screenshots could not be read, so it is not in this backup") == 1


def test_a_normal_backup_does_not_mention_the_screenshot_list(phone):
    open_settings(phone)
    tap(phone)
    wait_saved(phone)
    assert "screenshots could not be read" not in section(phone)


# ---------------------------------------------------------------- the exports and the overnight run

def test_the_json_export_is_relabelled_because_it_cannot_be_restored(phone):
    open_settings(phone)
    assert phone.get_by_role("button", name="Export notes (JSON, cannot be restored)").count() == 1
    assert phone.get_by_role("button", name="Save JSON").count() == 0
    assert "An export keeps only your notes and cannot be restored" in " ".join(phone.inner_text("#app").split())
    phone.get_by_role("button", name="Export notes (JSON, cannot be restored)").click()
    phone.wait_for_function("window.__rn.saved.length > 0")
    saved = phone.rn()["saved"][0]
    assert saved["name"].startswith("reel-notes-") and saved["name"].endswith(".json"), "the export itself still works as before"


def test_the_overnight_run_no_longer_calls_the_json_export_a_backup(phone):
    phone.set_default_timeout(8000)
    phone.open_with({"db": SAFE_LIBRARY}, "#/run")
    card = " ".join(phone.locator(".card", has_text="Overnight run").inner_text().split())
    assert "saves a backup" not in card
    assert "saves your notes as a JSON file to Downloads/ReelShelf" in card
    assert "not a backup you can restore: use Back up now in Settings" in card


# ---------------------------------------------------------------- hostile text is only ever text

def test_everything_the_phone_answers_is_shown_as_text(phone):
    bad = '<img src=x onerror="window.__pwned=1">'
    open_settings(phone, backup={"ok": answer(where=bad, counts={"reels": "<i>1</i>", "titles": {"x": 1}, "screenshots": "<b>"}, bytes="<u>9</u>")})
    tap(phone)
    wait_saved(phone)
    assert phone.locator("#backup img").count() == 0 and phone.locator("#backup i").count() == 0 and phone.locator("#backup u").count() == 0
    assert bad in section(phone), "the odd name is shown as it is, as text"
    assert "(0 reels, 0 titles, 1 KB)" in status(phone), "a count or a size that is not a number is nothing"
    assert phone.evaluate("window.__pwned") is None


def test_a_failure_sentence_with_markup_is_shown_as_text(phone):
    open_settings(phone, backup={"fail": '<b id="x">bold</b> & <script>window.__pwned=2</script>'})
    tap(phone)
    phone.locator("#backup [role=alert]").wait_for()
    assert phone.locator("#backup #x").count() == 0 and phone.locator("#backup b").count() == 0
    assert '<b id="x">bold</b> & <script>window.__pwned=2</script>' in section(phone)
    assert phone.evaluate("window.__pwned") is None


# ---------------------------------------------------------------- the restore button is next to Back up now, and no backup when the library is locked

def restore_things(pg):
    names = pg.get_by_role("button").all_inner_texts() + pg.get_by_role("link").all_inner_texts()
    return [n.strip() for n in names if re.search("restore", n, re.I)]


def test_settings_has_one_restore_button_next_to_back_up_now_and_no_file_input(phone):
    open_settings(phone)
    assert restore_things(phone) == ["Restore from a backup", "Export notes (JSON, cannot be restored)"]
    assert phone.locator("#backup #restorebtn").count() == 1 and phone.locator("#backup #backupnow").count() == 1
    tap(phone)
    wait_saved(phone)
    assert restore_things(phone) == ["Restore from a backup", "Export notes (JSON, cannot be restored)"]
    assert phone.locator("input[type=file]").count() == 0, "the phone's own picker is used, never a page file input"


def test_an_unreadable_library_offers_saving_the_file_and_no_backup(phone):
    phone.context.add_init_script(LIB_RN)
    phone.context.add_init_script(BACKUP_RN)
    phone.set_default_timeout(8000)
    phone.open_with(unreadable(backup={"ok": answer()}))
    locked_screen(phone)
    assert phone.get_by_role("button", name="Save the unreadable file to Downloads").count() == 1
    assert phone.get_by_role("button", name=re.compile("back up", re.I)).count() == 0 and phone.locator("#backupnow").count() == 0
    assert restore_things(phone) == ["Restore from a backup"], "restoring is the way back from an unreadable library"
    go(phone, "#/settings")  # every screen is the recovery screen: Settings, and its button, are not reachable
    locked_screen(phone)
    assert phone.locator("#backupnow").count() == 0 and "Back up now" not in phone.inner_text("#app")
    assert not backup_calls(phone)


def sentence_buttons():
    """The two button names BackupNow.java's LOCKED and LOCKED_NEWER sentences tell the user to use, read from the source."""
    return re.findall(r'Use \\"([^"\\]+)\\"', BACKUP_JAVA.read_text(encoding="utf-8"))


def test_the_sentence_for_an_unreadable_library_names_the_button_on_that_screen(phone):
    names = sentence_buttons()
    assert len(names) == 2, names
    phone.context.add_init_script(LIB_RN)
    phone.set_default_timeout(8000)
    phone.open_with(unreadable())
    locked_screen(phone)
    assert phone.get_by_role("button", name=names[0], exact=True).count() == 1, names[0]


def test_the_sentence_for_a_newer_library_names_the_button_on_that_screen(phone):
    names = sentence_buttons()
    assert len(names) == 2, names
    phone.set_default_timeout(8000)
    open_newer(phone, "phone", newer_reels(), newer_shots())
    phone.get_by_text("This library was saved by a newer Reel Shelf.").first.wait_for()
    assert phone.get_by_role("button", name=names[1], exact=True).count() == 1, names[1]


@pytest.mark.parametrize("flavour", ["phone", "page"])
def test_a_newer_library_offers_saving_a_copy_and_no_backup(phone, flavour):
    phone.context.add_init_script(BACKUP_RN)
    phone.set_default_timeout(8000)
    open_newer(phone, flavour, newer_reels(), newer_shots(), backup={"ok": answer()})
    phone.get_by_text("This library was saved by a newer Reel Shelf.").first.wait_for()
    assert phone.locator("#app button").all_inner_texts() == ["Save a copy to Downloads"]
    go(phone, "#/settings")
    phone.get_by_text("This library was saved by a newer Reel Shelf.").first.wait_for()
    assert phone.locator("#backupnow").count() == 0 and "Back up now" not in phone.inner_text("#app")
    assert "backupLibrary" not in calls(phone) and not backup_calls(phone)
    assert restore_things(phone) == []

