"""Settings, Backup and restore, "Restore from a backup" (S4-3): what the page asks the phone and what it shows.

The Java side (LocalBridge.chooseBackup, restoreBackup, cancelRestore: the picker, the check, the token, the free space, the
install over a library, a newer library, a night or a job) cannot run here: it is checked by the JUnit tests of RestoreNow,
LibraryBackup and LibraryFile and, for the bridge itself, on a device (TESTING.md, E44 to E47). Here: the page, in Chromium at
phone size, with a fake window.RN that follows the same contract: chooseBackup answers with a preview and a token (or a plain
sentence), restoreBackup installs only the backup that token belongs to, once (the library in place is kept, the revision moves
on), and every call is logged in order. No network, no device."""
import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_backup_now import BACKUP_RN, NAME, SAFE_LIBRARY, answer, restore_things
from test_library_newer import newer_reels, newer_shots, open_newer
from test_library_safety import DAMAGED, LIB_RN, LINK, go, locked_screen, unreadable
from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)
from test_shots import SHOTS_RN
from test_verify_online import media

JAVA = Path(__file__).resolve().parents[1] / "android" / "app-shell" / "app" / "src" / "main" / "java" / "app" / "reelshelf"
ASIDE = "reels.json.before-restore-20261118-103000"
SHOTS_ASIDE = "shots.json.before-restore-20261118-103000"
PRIVACY_NOTE = "Pictures and videos are not in backups; reels whose video is no longer on this phone keep their notes."
NOT_READY = "That backup is no longer ready (it was cancelled, another file was chosen, or Reel Shelf was restarted). Choose the file again. Nothing was changed."

BACKED_UP = json.dumps({"reels": [{"code": f"BKP{i:05d}", "url": f"https://www.instagram.com/reel/BKP{i:05d}/", "status": "done",
                                   "notes": {"topic": f"restored topic {i}"}, "added_at": 1} for i in range(5)],
                        "inbox": [], "media": [media(f"m-{n}", n) for n in ("Alien", "Aliens", "Dune")]})
BACKED_SHOTS = json.dumps({"v": 1, "seen": {f"k{i}": {"m": 1, "st": "done", "n": "a", "f": "f", "c": [], "x": ""} for i in range(7)}, "reels": {}})
OLD_SHOTS = json.dumps({"v": 1, "seen": {"old": {"m": 1, "st": "done", "n": "a", "f": "f", "c": [], "x": ""}}, "reels": {}})
BACKED_CODES = [f"BKP{i:05d}" for i in range(5)]
PREVIEW = {"created_at": "2026-11-03T12:00:00Z", "app_version": "1.3.22", "reels": 5, "titles": 3, "screenshots": 7, "has_shots": True, "bytes": 2 * 1024 * 1024}

# The phone's side of LocalBridge.chooseBackup / restoreBackup / cancelRestore. st.choose answers the first (a preview, a sentence, an odd
# answer, or nothing until the test lets it); st.install answers the second. The phone keeps ONE checked backup with ONE token, a new
# choice replaces it, a restore uses it up (whatever the answer), a wrong token installs nothing, and cancelRestore forgets it. Installing
# keeps the library that was in place (st.setAside), takes the backup's, unlocks, and moves the revision on (a page that has not
# loaded again is refused as stale), like LibraryFile.replaceWith.
RESTORE_RN = r"""
(() => {
  const st = window.__rn;
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  st.order = st.order || [];
  const wrap = (name, before) => { const f = window.RN[name]; if (typeof f !== "function") return; window.RN[name] = function () { st.order.push(name); if (before) before(...arguments); keep(); return f.apply(this, arguments); }; };
  wrap("backupLibrary", () => { st.dbAtBackup = st.db; });
  wrap("ackShared", (ids) => { st.acks = (st.acks || []).concat([JSON.parse(ids)]); });
  Object.assign(window.RN, {
    chooseBackup: function (id) {
      st.order.push("chooseBackup");
      st.chooseCalls = (st.chooseCalls || 0) + 1;
      window.__chooseId = id;
      keep();
      const a = st.choose || {};
      if (a.hold) return;
      setTimeout(() => {
        if (a.fail !== undefined) { st.staged = null; keep(); return rnDone(id, false, a.fail); }
        if (typeof a.raw === "string") return rnDone(id, true, a.raw);
        st.staged = { token: "tok-" + st.chooseCalls, db: a.db === undefined ? st.backupDb : a.db, shots: a.shots === undefined ? null : a.shots };
        keep();
        rnDone(id, true, JSON.stringify(Object.assign({ token: st.staged.token }, a.preview)));
      }, 20);
    },
    restoreBackup: function (id, token) {
      st.order.push("restoreBackup");
      st.restoreCalls = (st.restoreCalls || []).concat([token]);
      window.__restoreId = id;
      keep();
      const a = st.install || {};
      if (a.hold) return;
      setTimeout(() => {
        const staged = st.staged;
        if (!staged || staged.token !== token) return rnDone(id, false, window.__notReady);
        st.staged = null;  // the token is used up by a call that reaches this point, whatever the answer
        if (a.fail !== undefined) { keep(); return rnDone(id, false, a.fail); }
        st.setAside = st.db;
        st.db = staged.db;
        if (staged.shots != null) { st.shotsAside = st.shotsDb; st.shotsDb = staged.shots; st.shotsRev = (st.shotsRev || 0) + 1; }
        st.rev = (st.rev || 0) + 1;
        if (st.lib && st.lib.reels) st.lib.reels.state = "ok";
        keep();
        rnDone(id, true, JSON.stringify(Object.assign({ set_aside: "%ASIDE%", shots: staged.shots != null ? "restored" : "kept", shots_set_aside: staged.shots != null ? "%SHOTS_ASIDE%" : "" }, a.reply)));
      }, 20);
    },
    cancelRestore: function () { st.order.push("cancelRestore"); st.cancelCalls = (st.cancelCalls || 0) + 1; st.staged = null; keep(); },
  });
  window.__notReady = "%NOT_READY%";
})();
""".replace("%ASIDE%", ASIDE).replace("%SHOTS_ASIDE%", SHOTS_ASIDE).replace("%NOT_READY%", NOT_READY)


def open_restore(pg, hash_="#/restore", choose=None, install=None, scripts=(), with_lib=False, **state):
    """The restore screen with the fake phone. choose: what chooseBackup does (default: a good preview of BACKED_UP); install: restoreBackup."""
    pg.set_default_timeout(8000)
    for s in ([LIB_RN] if with_lib else []) + [*scripts, BACKUP_RN, RESTORE_RN]:
        pg.context.add_init_script(s)
    st = {"db": SAFE_LIBRARY, "backupDb": BACKED_UP, "backup": {"ok": answer()},
          "choose": {"preview": PREVIEW} if choose is None else choose, "install": install or {}, **state}
    pg.open_with(st, hash_)
    pg.start_db = pg.rn()["db"]  # as the page left it after opening (it migrates old libraries by itself): what "nothing changed" is compared with
    return pg


def stored_codes(pg):
    """The reel codes in the library the phone holds (the page may save it again after reading it: it migrates old libraries), so the bytes are not compared."""
    return [r["code"] for r in json.loads(pg.rn()["db"])["reels"]]


def order(pg):
    return pg.rn().get("order", [])


def calls_of(pg, name):
    return [o for o in order(pg) if o == name]


def card(pg):
    return " ".join(pg.locator("#app").inner_text().split())


def pick(pg):
    pg.get_by_role("button", name="Choose a backup file").click()


def confirm_screen(pg):
    pg.locator("#rquestion").wait_for()


def alert(pg):
    return " ".join(pg.locator("#app [role=alert]").first.inner_text().split())


def to_confirm(pg):
    pick(pg)
    confirm_screen(pg)


def restore_button(pg):
    return pg.get_by_role("button", name="Restore this backup")


def restored_screen(pg):
    pg.get_by_text("Your library was restored").first.wait_for()


def expected_question(pg, now="3 reels, 2 titles", backup="5 reels, 3 titles"):
    date = pg.evaluate("iso => backupDate(iso)", PREVIEW["created_at"])
    assert "2026" in date, date
    return f"Replace your library ({now}) with the backup from {date} ({backup})? Your current library is kept on the phone, not deleted."


def java_constants(name="RestoreNow.java"):
    """The sentences of a Java class: every `static final String NAME = "...";`."""
    text = (JAVA / name).read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'static final String (\w+) = "((?:[^"\\]|\\.)*)";', text):
        out[m.group(1)] = json.loads('"' + m.group(2) + '"')
    return out


def refusals_of_the_check():
    """The plain sentences LibraryBackup.check refuses with (the ones that are one string): what a bad file shows."""
    text = (JAVA / "LibraryBackup.java").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'new (?:Refused|Checked)\(Code\.(\w+), "((?:[^"\\]|\\.)*)"[,)]', text):
        if m.group(2):  # the OK answer has no sentence
            out[m.group(1)] = json.loads('"' + m.group(2) + '"')
    return out


# ---------------------------------------------------------------- the button, and the first step

def test_settings_restore_button_opens_the_restore_screen_and_nothing_is_asked_yet(phone):
    open_restore(phone, "#/settings")
    phone.locator("#restorebtn").wait_for()
    assert phone.get_by_role("link", name="Restore from a backup").count() == 1
    assert "Restore from a backup" in phone.locator("#backup").inner_text(), "next to Back up now, in the same section"
    phone.get_by_role("link", name="Restore from a backup").click()
    phone.get_by_role("heading", name="Restore from a backup").wait_for()
    assert phone.get_by_role("button", name="Choose a backup file").is_enabled()
    assert "chooseBackup" not in order(phone), "opening the screen asks nothing and changes nothing"
    assert "nothing changes until you confirm" in card(phone)
    assert "A reels.json file or a notes export (JSON) is not a backup and cannot be restored" in card(phone)


def test_a_cancelled_picker_changes_nothing(phone):
    sentence = java_constants()["NO_FILE"]
    open_restore(phone, choose={"fail": sentence})
    before = phone.rn()["db"]
    pick(phone)
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == sentence == "No file was chosen. Nothing was changed."
    assert phone.get_by_role("button", name="Choose a backup file").is_enabled(), "it can be tried again"
    assert phone.locator("#rquestion").count() == 0
    rn = phone.rn()
    assert rn["db"] == before and not rn.get("setAside") and not rn.get("restoreCalls")
    assert order(phone) == ["chooseBackup"]
    assert not rn.get("stores"), "nothing was saved either"


SENTENCES = {**{k: v for k, v in java_constants().items() if k not in ("SHOTS_RESTORED", "SHOTS_KEPT", "SHOTS_FAILED")},
             **{"check_" + k: v for k, v in refusals_of_the_check().items()}}


def test_the_java_sentences_were_found_so_the_refusal_tests_below_are_not_empty():
    assert {"BUSY", "WORK", "NO_FILE", "CANNOT_OPEN", "NOT_READY", "NEWER_LIBRARY", "NEWER_SHOTS", "NOT_INSTALLED", "OUT_OF_MEMORY", "DISK_FULL", "GENERIC"} <= set(SENTENCES)
    assert {"check_NOT_A_BACKUP", "check_CORRUPT", "check_IO_ERROR", "check_NEWER_FORMAT", "check_WRONG_FORMAT", "check_NO_MANIFEST", "check_NO_REELS"} <= set(SENTENCES), sorted(SENTENCES)
    assert "A plain reels.json or a notes export (JSON) cannot be restored" in SENTENCES["check_NOT_A_BACKUP"], "owner decision D4: a sentence, not a restore"
    assert all(s.endswith(".") for s in SENTENCES.values())


@pytest.mark.parametrize("code", sorted(SENTENCES))
def test_every_refusal_shows_its_sentence_as_it_is_and_never_calls_restore(phone, code):
    sentence = SENTENCES[code]
    open_restore(phone, choose={"fail": sentence})
    pick(phone)
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == sentence
    assert phone.locator("#rquestion").count() == 0 and phone.get_by_role("button", name="Restore this backup").count() == 0, "no confirm screen for a refused file"
    assert not phone.rn().get("restoreCalls"), "restoreBackup is never called for a refused file"
    assert phone.rn()["db"] == phone.start_db
    assert phone.get_by_role("button", name="Choose a backup file").is_enabled()


@pytest.mark.parametrize("raw", ["not json", "[1]", "{}", "null", "", '{"token": ""}', '{"token": 5}'])
def test_an_answer_the_page_cannot_use_is_a_refusal_not_a_confirm_screen(phone, raw):
    open_restore(phone, choose={"raw": raw})
    pick(phone)
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == "The file could not be checked. Nothing was changed."
    assert phone.locator("#rquestion").count() == 0 and not phone.rn().get("restoreCalls")


def test_with_an_older_bridge_that_cannot_restore_the_page_says_so(phone):
    phone.set_default_timeout(8000)
    phone.open_with({"db": SAFE_LIBRARY}, "#/restore")  # the plain fake bridge: no chooseBackup
    pick(phone)
    phone.locator("#app [role=alert]").wait_for()
    assert "Open this inside the Reel Shelf app" in alert(phone)
    assert phone.get_by_role("button", name="Choose a backup file").is_enabled()


def test_while_the_file_is_checked_the_button_is_off_and_a_second_tap_asks_nothing_more(phone):
    open_restore(phone, choose={"hold": True})
    pick(phone)
    expect(phone.get_by_role("button", name="Checking...")).to_be_disabled()
    assert "Checking the file" in card(phone)
    phone.evaluate("restorePick()")
    phone.wait_for_timeout(100)
    assert phone.rn()["chooseCalls"] == 1
    phone.evaluate("([id, p]) => rnDone(id, true, JSON.stringify(p))", [phone.evaluate("window.__chooseId"), {"token": "tok-x", **PREVIEW}])
    confirm_screen(phone)


# ---------------------------------------------------------------- the confirm screen

def test_the_confirm_screen_shows_both_counts_and_says_the_library_is_kept(phone):
    open_restore(phone)
    to_confirm(phone)
    assert phone.locator("#rquestion").inner_text() == expected_question(phone)
    assert "Your current library is kept on the phone, not deleted." in card(phone)
    assert phone.rn()["db"] == phone.start_db and not phone.rn().get("restoreCalls"), "nothing changed yet: the confirm screen only asks"
    assert "Made by Reel Shelf 1.3.22" in card(phone) and "It includes the list of read screenshots." in card(phone)
    assert phone.get_by_role("button", name="Restore this backup").is_enabled() and phone.get_by_role("button", name="Cancel").is_enabled()


def test_the_counts_follow_the_library_and_the_backup_not_fixed_numbers(phone):
    one = json.dumps({"reels": [{"code": "ONE0001", "url": "https://www.instagram.com/reel/ONE0001/", "status": "new", "added_at": 1}], "inbox": []})
    open_restore(phone, db=one, choose={"preview": {**PREVIEW, "reels": 1204, "titles": 1, "has_shots": False}})
    to_confirm(phone)
    assert phone.locator("#rquestion").inner_text() == expected_question(phone, "1 reel, 0 titles", "1204 reels, 1 title")
    assert "It has no list of read screenshots, so yours stays as it is." in card(phone)


def test_the_save_a_backup_first_box_is_on_by_default(phone):
    open_restore(phone)
    to_confirm(phone)
    box = phone.get_by_label("Save a backup of the current library first")
    expect(box).to_be_checked()
    assert "If it cannot be made, nothing is restored." in card(phone)


def test_hostile_text_from_the_phone_is_only_ever_shown_as_text(phone):
    bad = '<img src=x onerror="window.__pwned=1">'
    open_restore(phone, choose={"preview": {**PREVIEW, "created_at": bad, "app_version": bad, "reels": "<b>5</b>", "titles": {"x": 1}}},
                 install={"reply": {"set_aside": bad, "shots_set_aside": bad}})
    to_confirm(phone)
    assert phone.locator("#app img").count() == 0 and phone.locator("#app b").count() == 0
    assert "(0 reels, 0 titles)" in phone.locator("#rquestion").inner_text(), "a count that is not a number is nothing"
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    restored_screen(phone)
    assert phone.locator("#app img").count() == 0
    assert bad in card(phone), "a file name from the phone is shown as it is, as text"
    assert phone.evaluate("window.__pwned") is None


# ---------------------------------------------------------------- the pre-backup (owner decision D2: on by default)

def test_the_pre_backup_runs_first_with_the_current_counts_and_the_library_is_still_the_old_one_then(phone):
    open_restore(phone)
    to_confirm(phone)
    restore_button(phone).click()
    restored_screen(phone)
    assert order(phone) == ["chooseBackup", "backupLibrary", "restoreBackup"], "the backup of what is there comes before anything is replaced"
    rn = phone.rn()
    assert rn["dbAtBackup"] == phone.start_db, "when the backup was made the old library was still in place"
    assert json.loads(rn["backupCalls"][0]["counts"]) == {"reels": 3, "titles": 2, "screenshots": 0}
    assert rn["restoreCalls"] == ["tok-1"], "restored with the token the phone gave, once"
    assert rn["setAside"] == phone.start_db
    assert f"A backup of the library you had was saved to Downloads/ReelShelf/{NAME}." in card(phone)


def test_unticked_the_restore_goes_ahead_without_a_backup(phone):
    open_restore(phone)
    to_confirm(phone)
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    restored_screen(phone)
    assert order(phone) == ["chooseBackup", "restoreBackup"] and not phone.rn().get("backupCalls")
    assert "A backup of the library you had was saved" not in card(phone)


def test_a_failed_pre_backup_stops_the_restore_and_changes_nothing(phone):
    sentence = "There is not enough free space on the phone for a backup: about 221 MB are needed and 150 MB are free. Free up some space and try again. Your library was not changed."
    open_restore(phone, backup={"fail": sentence})
    to_confirm(phone)
    restore_button(phone).click()
    phone.locator("#app [role=alert]").wait_for()
    text = alert(phone)
    assert sentence in text and "nothing was restored" in text and 'Untick "Save a backup of the current library first"' in text
    assert order(phone) == ["chooseBackup", "backupLibrary"], "restoreBackup was never called"
    rn = phone.rn()
    assert rn["db"] == phone.start_db and not rn.get("setAside") and not rn.get("restoreCalls")
    assert phone.locator("#rquestion").count() == 1, "still on the confirm screen, the checked file is kept"
    assert phone.get_by_role("button", name="Restore this backup").is_enabled()
    expect(phone.get_by_label("Save a backup of the current library first")).to_be_checked()
    # the user chooses to go on without the backup: the same checked file restores
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    restored_screen(phone)
    assert phone.rn()["restoreCalls"] == ["tok-1"] and stored_codes(phone) == BACKED_CODES


def test_an_empty_phone_with_no_library_yet_is_not_stopped_by_the_backup_of_nothing(phone):
    nothing = "There is nothing to back up yet."
    assert nothing == java_constants("BackupNow.java")["NOTHING"], "the page compares with the phone's own sentence"
    open_restore(phone, backup={"fail": nothing}, db="")
    to_confirm(phone)
    restore_button(phone).click()
    restored_screen(phone)
    assert order(phone) == ["chooseBackup", "backupLibrary", "restoreBackup"]
    assert stored_codes(phone) == BACKED_CODES


def test_the_page_sentences_are_the_phones_sentences(phone):
    j = java_constants()
    phone.open_with({"db": SAFE_LIBRARY}, "#/restore")
    assert phone.evaluate("RESTORE_WORK") == j["WORK"]
    assert phone.evaluate("RESTORE_BUSY") == j["BUSY"]
    assert phone.evaluate("NOTHING_TO_BACK_UP") == java_constants("BackupNow.java")["NOTHING"]


# ---------------------------------------------------------------- after a restore

def test_the_restored_reels_show_and_the_page_reads_everything_fresh(phone):
    open_restore(phone, choose={"preview": PREVIEW, "shots": BACKED_SHOTS}, scripts=[SHOTS_RN], shotsDb=OLD_SHOTS)
    to_confirm(phone)
    restore_button(phone).click()
    restored_screen(phone)
    text = card(phone)
    assert "Your library was restored from the backup of" in text
    assert "Your library now has 5 reels, 3 titles." in text, "the real counts of what was loaded, not the backup's label"
    assert f"Your previous library is kept on the phone as {ASIDE} (in Reel Shelf's private storage, not in Downloads). It is not deleted." in text
    assert f"Your previous list of read screenshots is kept as {SHOTS_ASIDE}." in text
    assert "The list of read screenshots was restored too." in text
    assert PRIVACY_NOTE in text
    assert phone.evaluate("db.reels.map((r) => r.code)") == BACKED_CODES
    assert phone.evaluate("Shots.total()") == 7, "the screenshot list was read again"
    assert phone.rn()["setAside"] == phone.start_db and phone.rn()["shotsAside"] == OLD_SHOTS
    phone.get_by_role("link", name="Open my library").click()
    phone.wait_for_function("() => document.body.innerText.includes('restored topic 0') || document.body.innerText.includes('BKP00000')")
    assert phone.locator("#rquestion").count() == 0
    assert phone.evaluate("restore.step") == "pick" and phone.evaluate("restore.result") is None, "the result is forgotten once you leave it"


def test_after_the_restore_the_page_has_the_new_revision_and_saves_the_restored_library(phone):
    open_restore(phone)
    to_confirm(phone)
    stale_before = phone.evaluate("RN.libraryStale('reels')")
    assert stale_before is False
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    restored_screen(phone)
    assert phone.evaluate("RN.libraryStale('reels')") is False, "the page loaded the restored library: its copy is current"
    assert phone.evaluate("saveDb()") is True
    assert json.loads(phone.rn()["db"])["reels"][0]["code"] == "BKP00000", "and what it saves is the restored library"
    assert "updated elsewhere" not in phone.evaluate("document.getElementById('toast').textContent"), "no stale-page reload: the page read the restored library on purpose"


def test_a_backup_without_a_screenshot_list_leaves_the_one_in_place(phone):
    open_restore(phone, scripts=[SHOTS_RN], shotsDb=OLD_SHOTS)
    to_confirm(phone)
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    restored_screen(phone)
    assert "The backup has no list of read screenshots, so yours was left as it is." in card(phone)
    assert phone.rn()["shotsDb"] == OLD_SHOTS and not phone.rn().get("shotsAside")
    assert "Your previous list of read screenshots" not in card(phone)


def test_if_the_reels_were_restored_and_the_screenshot_list_was_not_the_page_says_exactly_that(phone):
    open_restore(phone, install={"reply": {"shots": "failed", "shots_set_aside": ""}}, scripts=[SHOTS_RN], shotsDb=OLD_SHOTS)
    to_confirm(phone)
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    restored_screen(phone)
    assert "The list of read screenshots could not be restored: it is as it was before. Your reels, notes and watchlist were restored." in alert(phone)
    assert stored_codes(phone) == BACKED_CODES
    assert "The list of read screenshots was restored too" not in card(phone)
    assert phone.evaluate("db.reels.length") == 5


def test_a_fresh_install_has_no_library_to_keep(phone):
    open_restore(phone, db="", install={"reply": {"set_aside": ""}}, backup={"fail": "There is nothing to back up yet."})
    to_confirm(phone)
    restore_button(phone).click()
    restored_screen(phone)
    assert "There was no library on this phone to keep." in card(phone)
    assert phone.evaluate("db.reels.length") == 5


def test_a_link_shared_before_the_restore_is_filed_into_the_restored_library_and_acknowledged_once(phone):
    open_restore(phone, "#/", with_lib=True, **{"db": DAMAGED, "shared": [LINK], "lib": {"reels": {"state": "unreadable"}}})
    locked_screen(phone)
    assert phone.rn()["shared"] == [LINK], "it waits safely while the library is shut"
    phone.get_by_role("link", name="Restore from a backup").click()
    to_confirm(phone)
    restore_button(phone).click()
    restored_screen(phone)
    phone.wait_for_function("() => window.__rn.shared.length === 0")
    codes = [r["code"] for r in json.loads(phone.rn()["db"])["reels"]]
    assert codes.count("SHARE0001") == 1 and {f"BKP{i:05d}" for i in range(5)} <= set(codes), "filed once, into the restored library"
    assert phone.rn()["acks"] == [["id-" + LINK]], "acknowledged once, by its id"
    assert phone.evaluate("db.reels.some((r) => r.code === 'SHARE0001')")


# ---------------------------------------------------------------- refusals on the page: work, a night, and the phone's own answers

@pytest.mark.parametrize("job", ["run = { codes: ['A'], i: 0, step: 'ai', finished: false, log: [] };", "modelDl = { d: 1, t: 2 };"])
def test_choosing_a_file_is_refused_while_work_runs_and_nothing_is_asked(phone, job):
    open_restore(phone)
    phone.evaluate(job)
    pick(phone)
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == java_constants()["WORK"]
    assert "chooseBackup" not in order(phone)
    assert phone.get_by_role("button", name="Choose a backup file").is_enabled()


def test_a_job_started_after_the_file_was_checked_stops_the_restore_and_the_file_waits(phone):
    open_restore(phone)
    to_confirm(phone)
    phone.evaluate("run = { codes: ['A'], i: 0, step: 'ai', finished: false, log: [] };")
    restore_button(phone).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == java_constants()["WORK"]
    assert order(phone) == ["chooseBackup"], "neither the backup nor the restore was asked"
    assert phone.rn()["db"] == phone.start_db
    phone.evaluate("run = null")  # the job is stopped: the same checked file restores
    restore_button(phone).click()
    restored_screen(phone)
    assert phone.rn()["restoreCalls"] == ["tok-1"]


def test_a_job_that_starts_during_the_pre_backup_stops_the_restore_before_it_is_asked(phone):
    open_restore(phone, backup={"hold": True})
    to_confirm(phone)
    restore_button(phone).click()
    phone.wait_for_function("() => window.__backupId")
    phone.evaluate("run = { codes: ['A'], i: 0, step: 'ai', finished: false, log: [] };")
    phone.evaluate("([id, a]) => rnDone(id, true, JSON.stringify(a))", [phone.evaluate("window.__backupId"), answer()])
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == java_constants()["WORK"]
    assert "restoreBackup" not in order(phone)
    assert phone.rn()["db"] == phone.start_db


def test_a_nightly_run_that_started_after_the_file_was_checked_stops_the_restore(phone):
    open_restore(phone)
    to_confirm(phone)
    phone.evaluate("() => { window.__rn.nightActive = true; }")  # the phone says a night is going (the page has not been handed over yet)
    restore_button(phone).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == java_constants()["WORK"]
    assert order(phone) == ["chooseBackup"] and phone.rn()["db"] == phone.start_db


def test_a_night_that_began_while_the_picker_was_open_is_refused_by_the_phone_and_shown(phone):
    open_restore(phone, choose={"fail": java_constants()["WORK"]})
    pick(phone)
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == java_constants()["WORK"]
    assert not phone.rn().get("restoreCalls")


def test_a_refusal_by_the_phone_at_the_restore_step_goes_back_to_choosing_and_drops_the_file(phone):
    sentence = java_constants()["WORK"]
    open_restore(phone, install={"fail": sentence})
    to_confirm(phone)
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == sentence
    assert phone.get_by_role("button", name="Choose a backup file").is_enabled() and phone.locator("#rquestion").count() == 0
    assert phone.rn()["db"] == phone.start_db and not phone.rn().get("setAside")
    assert order(phone)[-2:] == ["restoreBackup", "cancelRestore"], "the page tells the phone to forget the file"
    # the used-up token installs nothing if anything asks again
    phone.evaluate("RN.restoreBackup(99, 'tok-1')")
    phone.wait_for_function("() => window.__rn.restoreCalls.length === 2")
    phone.wait_for_timeout(100)
    assert phone.rn()["db"] == phone.start_db


def test_a_restore_is_asked_once_however_often_the_button_is_tapped(phone):
    open_restore(phone, install={"hold": True})
    to_confirm(phone)
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    phone.wait_for_function("() => window.__rn.restoreCalls && window.__rn.restoreCalls.length === 1")
    phone.evaluate("restoreGo()")
    phone.evaluate("restoreGo()")
    phone.wait_for_timeout(150)
    assert phone.rn()["restoreCalls"] == ["tok-1"]
    assert "Restoring. Please keep the app open." in card(phone)


def test_while_it_installs_every_route_shows_the_restoring_screen(phone):
    open_restore(phone, install={"hold": True})
    to_confirm(phone)
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    phone.wait_for_function("() => window.__rn.restoreCalls")
    for route in ("#/settings", "#/inbox", "#/", "#/r/BK00000"):
        go(phone, route)
        phone.wait_for_timeout(60)
        assert "Restoring. Please keep the app open." in card(phone), route
    phone.evaluate("([id]) => rnDone(id, true, JSON.stringify({ set_aside: '%s', shots: 'kept', shots_set_aside: '' }))" % ASIDE, [phone.evaluate("window.__restoreId")])
    phone.get_by_text("Your library was restored").first.wait_for()  # the address bar said something else: the result is still shown
    assert phone.evaluate("location.hash") == "#/restore"


# ---------------------------------------------------------------- leaving, cancelling, and a different file

def test_cancel_drops_the_checked_file_and_goes_back_to_settings(phone):
    open_restore(phone)
    to_confirm(phone)
    phone.get_by_role("button", name="Cancel").click()
    phone.locator("#backupnow").wait_for()
    assert order(phone) == ["chooseBackup", "cancelRestore"]
    assert not phone.rn().get("staged") and phone.rn()["db"] == phone.start_db
    go(phone, "#/restore")
    phone.get_by_role("button", name="Choose a backup file").wait_for()
    assert phone.locator("#rquestion").count() == 0, "a cancelled file does not come back"


def test_leaving_the_screen_drops_the_checked_file_too(phone):
    open_restore(phone)
    to_confirm(phone)
    go(phone, "#/inbox")
    phone.wait_for_function("() => window.__rn.cancelCalls === 1")
    assert order(phone) == ["chooseBackup", "cancelRestore"] and not phone.rn().get("staged")
    go(phone, "#/restore")
    phone.get_by_role("button", name="Choose a backup file").wait_for()


def test_a_file_that_finished_checking_after_you_left_is_dropped(phone):
    open_restore(phone, choose={"hold": True})
    pick(phone)
    go(phone, "#/settings")
    phone.locator("#backupnow").wait_for()
    phone.evaluate("([id, p]) => rnDone(id, true, JSON.stringify(p))", [phone.evaluate("window.__chooseId"), {"token": "tok-1", **PREVIEW}])
    phone.wait_for_function("() => window.__rn.cancelCalls === 1")
    assert phone.evaluate("restore.preview") is None


def test_choosing_a_file_again_gets_a_new_token_and_only_that_one_restores(phone):
    open_restore(phone)
    to_confirm(phone)
    phone.evaluate("() => { window.__rn.choose = { preview: %s, db: %s }; }" % (json.dumps({**PREVIEW, "reels": 2, "titles": 0}), json.dumps(SAFE_LIBRARY)))
    phone.get_by_role("button", name="Cancel").click()
    go(phone, "#/restore")
    to_confirm(phone)
    assert "(2 reels, 0 titles)" in phone.locator("#rquestion").inner_text()
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    restored_screen(phone)
    assert phone.rn()["restoreCalls"] == ["tok-2"], "the token of the file that was shown"


# ---------------------------------------------------------------- the waiting screen, a locked library and a newer one

FAST = "window.__handover = { poll: 20, max: 5000 };"


def test_the_waiting_screen_is_first_on_every_route_including_restore(phone):
    phone.context.add_init_script(FAST)
    open_restore(phone, "#/restore", nightActive=True)
    phone.get_by_text("The nightly run is finishing").wait_for()
    for route in ("#/restore", "#/settings", "#/inbox", "#/", "#/r/BK00000"):
        go(phone, route)
        phone.wait_for_timeout(80)
        assert phone.get_by_text("The nightly run is finishing").is_visible(), route
        assert phone.get_by_role("button", name="Choose a backup file").count() == 0 and phone.locator("#restorebtn").count() == 0, route
    assert not phone.rn().get("chooseCalls") and not phone.rn().get("restoreCalls")
    phone.evaluate("() => { window.__rn.nightActive = false; }")
    phone.get_by_text("The nightly run is finishing").wait_for(state="hidden")


def test_a_night_that_starts_while_the_confirm_screen_is_open_hands_over_first_and_the_restore_is_refused_until_it_ends(phone):
    phone.context.add_init_script(FAST)
    open_restore(phone)
    to_confirm(phone)
    phone.evaluate("() => { window.__rn.nightActive = true; }")
    phone.evaluate("() => onAppResume()")
    phone.get_by_text("The nightly run is finishing").wait_for()
    assert phone.locator("#rquestion").count() == 0, "the waiting screen has the whole screen"
    assert "restoreBackup" not in order(phone)
    phone.evaluate("() => { window.__rn.nightActive = false; }")
    phone.get_by_text("The nightly run is finishing").wait_for(state="hidden")
    assert phone.rn()["db"] == phone.start_db and not phone.rn().get("restoreCalls")


def test_an_unreadable_library_offers_restore_on_its_screen_and_restoring_opens_it(phone):
    open_restore(phone, "#/", with_lib=True, **{"db": DAMAGED, "shared": [], "lib": {"reels": {"state": "unreadable"}}})
    locked_screen(phone)
    assert restore_things(phone) == ["Restore from a backup"]
    phone.get_by_role("link", name="Restore from a backup").click()
    phone.get_by_role("heading", name="Restore from a backup").wait_for()
    pick(phone)
    confirm_screen(phone)
    text = phone.locator("#rquestion").inner_text()
    date = phone.evaluate("iso => backupDate(iso)", PREVIEW["created_at"])
    assert text == f"Replace your library, which could not be read, with the backup from {date} (5 reels, 3 titles)? Your current library is kept on the phone, not deleted."
    assert phone.get_by_label("Save a backup of the current library first").count() == 0, "an unreadable library cannot be backed up"
    assert "The unreadable file is set aside under a new name, not deleted." in card(phone)
    restore_button(phone).click()
    restored_screen(phone)
    assert order(phone) == ["chooseBackup", "restoreBackup"], "no backup of the unreadable file was asked for"
    assert phone.rn()["setAside"] == DAMAGED, "the unreadable file is kept, not deleted"
    assert stored_codes(phone) == BACKED_CODES
    assert "Library not opened" not in card(phone)
    phone.get_by_role("link", name="Open my library").click()
    phone.wait_for_function("() => !document.body.innerText.includes('Your library file could not be read')")
    assert phone.evaluate("db.reels.length") == 5


def test_an_unreadable_library_still_is_the_recovery_screen_on_other_routes_and_cancel_goes_back_to_it(phone):
    open_restore(phone, "#/", with_lib=True, **{"db": DAMAGED, "shared": [], "lib": {"reels": {"state": "unreadable"}}})
    locked_screen(phone)
    for route in ("#/settings", "#/inbox"):
        go(phone, route)
        locked_screen(phone)
        assert phone.locator("#rquestion").count() == 0
    go(phone, "#/restore")
    phone.get_by_role("button", name="Choose a backup file").wait_for()
    phone.get_by_role("link", name="Cancel").click()
    locked_screen(phone)
    assert phone.rn()["db"] == DAMAGED and not phone.rn().get("restoreCalls")


@pytest.mark.parametrize("flavour", ["phone", "page"])
def test_a_newer_library_is_not_restored_over_and_its_screen_has_no_restore(phone, flavour):
    for s in (BACKUP_RN, RESTORE_RN):
        phone.context.add_init_script(s)
    phone.set_default_timeout(8000)
    reels, shots = newer_reels(), newer_shots()
    open_newer(phone, flavour, reels, shots, hash_="#/restore", choose={"preview": PREVIEW}, backupDb=BACKED_UP, install={}, backup={"ok": answer()})
    phone.get_by_text("This library was saved by a newer Reel Shelf.").first.wait_for()
    assert restore_things(phone) == [] and phone.get_by_role("button", name="Choose a backup file").count() == 0, "the restore screen is not reachable"
    assert phone.locator("#app button").all_inner_texts() == ["Save a copy to Downloads"]
    phone.wait_for_timeout(150)
    rn = phone.rn()
    assert not rn.get("chooseCalls") and not rn.get("restoreCalls") and not rn.get("setAside")
    assert rn["db"] == reels and rn["shotsDb"] == shots, "byte for byte as it was"


def test_the_phones_own_refusal_for_a_newer_library_is_shown_and_nothing_changes(phone):
    sentence = java_constants()["NEWER_LIBRARY"]
    open_restore(phone, install={"fail": sentence})
    to_confirm(phone)
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == sentence and "newer Reel Shelf" in sentence
    assert phone.rn()["db"] == phone.start_db and not phone.rn().get("setAside")
