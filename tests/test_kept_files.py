"""Settings, Backup and restore, "Files kept for safety" (S4-4): what the page lists, saves and deletes, and what it asks the phone first.

The Java side (KeptFiles: the name patterns, the listing, the confirmation token, every refusal; LocalBridge.keptFiles, saveKept,
askDeleteKept, deleteKept: the phone's folder, Downloads, work and nights) cannot run here: it is checked by the JUnit tests of
KeptFiles (with real files) and, for the bridge itself, on a device (TESTING.md, E60 to E65). Here: the page, in Chromium at phone size,
with a fake window.RN that follows the same contract: keptFiles lists what st.kept holds, askDeleteKept answers with the file and a token,
deleteKept deletes only the file that token was given for, once, and every call is logged in order. No network, no device."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_backup_now import BACKUP_RN, SAFE_LIBRARY
from test_backup_restore import FAST, PREVIEW, RESTORE_RN, ASIDE, BACKED_UP, confirm_screen, java_constants, pick, restore_button
from test_library_newer import newer_reels, newer_shots, open_newer
from test_library_safety import DAMAGED, LIB_RN, LINK, go, locked_screen
from test_phone_app import phone, site  # noqa: F401  (pytest fixtures)

JAVA = Path(__file__).resolve().parents[1] / "android" / "app-shell" / "app" / "src" / "main" / "java" / "app" / "reelshelf"


def ms(*when):
    return int(datetime(*when, tzinfo=timezone.utc).timestamp() * 1000)


AT_RESTORE = ms(2026, 11, 20, 23, 59, 59)
AT_BAD_SHOTS = ms(2026, 11, 19, 9, 0, 0)
AT_BAD_BAK = ms(2026, 11, 18, 11, 0, 0)
AT_BAD = ms(2026, 11, 18, 10, 30, 0)
NAME_RESTORE = "reels.json.before-restore-20261120-235959"
NAME_BAD_SHOTS = "shots.json.bad-20261119-090000"
NAME_BAD_BAK = "reels.json.bak.bad-20261118-110000"
NAME_BAD = "reels.json.bad-20261118-103000"
TEMP = "temporary-restore-files"
LIST = [
    {"name": NAME_RESTORE, "kind": "before_restore", "library": "reels", "size": 4404019, "at": AT_RESTORE, "files": 1},
    {"name": NAME_BAD_SHOTS, "kind": "bad", "library": "shots", "size": 52000, "at": AT_BAD_SHOTS, "files": 1},
    {"name": NAME_BAD_BAK, "kind": "bad_backup", "library": "reels", "size": 700, "at": AT_BAD_BAK, "files": 1},
    {"name": NAME_BAD, "kind": "bad", "library": "reels", "size": 0, "at": AT_BAD, "files": 1},
    {"name": TEMP, "kind": "temp", "library": "", "size": 15360, "at": AT_BAD, "files": 3},
]
SENT = {k: v for k, v in java_constants("KeptFiles.java").items()}

# The phone's side of LocalBridge.keptFiles / saveKept / askDeleteKept / deleteKept. st.kept is what the phone holds (newest first). askDeleteKept answers
# with the file as it is and a new token (or a sentence, or whatever st.ask says); the phone keeps ONE pending confirmation, a delete is for the name and
# token that were asked, uses the token up whatever the answer, and then removes the file from st.kept (st.del can make it refuse, or wait).
KEPT_RN = r"""
(() => {
  const st = window.__rn;
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  st.order = st.order || [];
  st.kept = st.kept || [];
  const find = (name) => st.kept.find((x) => x.name === name);
  Object.assign(window.RN, {
    keptFiles: function () {
      st.order.push("keptFiles");
      st.listCalls = (st.listCalls || 0) + 1;  // not kept in sessionStorage: the first page of open_with lists too, before the test's state is loaded, and must not overwrite it
      return st.keptRaw !== undefined ? st.keptRaw : JSON.stringify({ items: st.kept, error: st.keptError || "" });
    },
    saveKept: function (id, name) {
      st.order.push("saveKept");
      st.saveCalls = (st.saveCalls || []).concat([name]);
      window.__saveId = id;
      keep();
      const a = st.save || {};
      if (a.hold) return;
      setTimeout(() => {
        if (a.fail !== undefined) return rnDone(id, false, a.fail);
        if (typeof a.raw === "string") return rnDone(id, true, a.raw);
        const it = find(name) || {};
        rnDone(id, true, JSON.stringify(Object.assign({ name: "saved-" + name + ".txt", where: "Downloads/ReelShelf/saved-" + name + ".txt", bytes: it.size || 0, uninstall_warning: false }, a.ok)));
      }, 20);
    },
    askDeleteKept: function (name) {
      st.order.push("askDeleteKept");
      st.askCalls = (st.askCalls || []).concat([name]);
      const a = st.ask || {};
      if (a.raw !== undefined) { keep(); return a.raw; }
      if (a.fail !== undefined) { keep(); return JSON.stringify({ ok: false, text: a.fail }); }
      const it = find(name);
      if (!it) { keep(); return JSON.stringify({ ok: false, text: window.__gone }); }
      st.pending = { name, token: "ktok-" + st.askCalls.length };
      keep();
      return JSON.stringify({ ok: true, token: st.pending.token, item: it });
    },
    deleteKept: function (id, name, token) {
      st.order.push("deleteKept");
      st.deleteCalls = (st.deleteCalls || []).concat([[name, token]]);
      window.__deleteId = id;
      keep();
      const a = st.del || {};
      const finish = () => {
        const p = st.pending;
        if (!p || p.token !== token || p.name !== name) return rnDone(id, false, window.__notConfirmed);
        st.pending = null;  // used up by a call that gets this far, whatever the answer
        if (a.fail !== undefined) { keep(); return rnDone(id, false, a.fail); }
        const it = find(name);
        st.kept = st.kept.filter((x) => x.name !== name);
        st.deleted = (st.deleted || []).concat([name]);
        keep();
        rnDone(id, true, JSON.stringify({ deleted: name, bytes: it ? it.size : 0 }));
      };
      if (a.hold) { window.__finishDelete = finish; return; }
      setTimeout(finish, 20);
    },
  });
  window.__gone = "%GONE%";
  window.__notConfirmed = "%NOT_CONFIRMED%";
})();
""".replace("%GONE%", SENT["GONE"]).replace("%NOT_CONFIRMED%", SENT["NOT_CONFIRMED"])


def open_kept(pg, hash_="#/kept", kept=None, scripts=(), with_lib=False, **state):
    """The kept-files screen with the fake phone. kept: what the phone holds (default LIST)."""
    pg.set_default_timeout(8000)
    for s in ([LIB_RN] if with_lib else []) + [*scripts, BACKUP_RN, KEPT_RN]:
        pg.context.add_init_script(s)
    pg.open_with({"db": SAFE_LIBRARY, "kept": [dict(x) for x in (LIST if kept is None else kept)], **state}, hash_)
    return pg


def order(pg):
    return pg.rn().get("order", [])


def card(pg):
    return " ".join(pg.locator("#app").inner_text().split())


def cards(pg):
    return [" ".join(c.inner_text().split()) for c in pg.locator("#app .card").all()][1:]  # the first card is the introduction


def alert(pg):
    return " ".join(pg.locator("#app [role=alert]").first.inner_text().split())


def norm(s):
    return " ".join(s.split())


def date_of(pg, at):
    d = norm(pg.evaluate("t => keptDate(t)", at))  # toLocaleString may put a narrow no-break space before AM or PM: compared with the spaces made plain
    assert "2026" in d, d
    return d


def size_of(pg, n):
    return pg.evaluate("n => keptSize(n)", n)


def delete_button(pg, name):
    return pg.locator(f'[data-kdel="{name}"]')


def save_button(pg, name):
    return pg.locator(f'[data-ksave="{name}"]')


def listed(pg):
    pg.get_by_role("heading", name="Files kept for safety").wait_for()


def to_confirm(pg, name=NAME_RESTORE):
    delete_button(pg, name).click()
    pg.locator("#kquestion").wait_for()


def confirm_button(pg):
    return pg.get_by_role("button", name="Delete this file")


# ---------------------------------------------------------------- the entry in Settings, the list, the empty state

def test_settings_has_the_entry_next_to_restore_and_it_opens_the_screen_and_lists_once(phone):
    open_kept(phone, "#/settings")
    phone.locator("#keptbtn").wait_for()
    assert phone.locator("#backup #keptbtn").count() == 1 and phone.locator("#backup #restorebtn").count() == 1, "in the same section as Back up now and Restore"
    assert phone.get_by_role("link", name="Files kept for safety").count() == 1
    assert "keptFiles" not in order(phone), "opening Settings asks nothing and lists nothing"
    assert "Reel Shelf never deletes them for you" in phone.locator("#backup").inner_text()
    phone.get_by_role("link", name="Files kept for safety").click()
    listed(phone)
    assert phone.rn()["listCalls"] == 1
    assert order(phone) == ["keptFiles"]
    assert phone.locator("#app .icon-btn").get_attribute("href") == "#/settings", "the arrow goes back to Settings"


def test_the_list_shows_every_file_in_the_order_the_phone_gave_with_what_it_is_when_and_how_big(phone):
    open_kept(phone)
    listed(phone)
    got = cards(phone)
    assert len(got) == 5
    assert got[0] == (f"Your library before a restore Kept since {date_of(phone, AT_RESTORE)} · {size_of(phone, 4404019)} Kept when a backup replaced it. {NAME_RESTORE} "
                      "Save to Downloads Delete")
    assert got[1] == f"Your screenshot list that could not be read Kept since {date_of(phone, AT_BAD_SHOTS)} · 51 KB Set aside, not deleted, when it could not be read. {NAME_BAD_SHOTS} Save to Downloads Delete"
    assert got[2].startswith("Damaged earlier copy of your library Kept since") and "700 bytes" in got[2] and NAME_BAD_BAK in got[2]
    assert got[3].startswith("Your library that could not be read Kept since") and "· 0 bytes" in got[3] and NAME_BAD in got[3]
    assert got[4] == f"Temporary restore files 3 files, changed {date_of(phone, AT_BAD)} · 15 KB Left over from checking a backup file. Your library is not affected. Delete"
    assert phone.get_by_role("button", name="Save to Downloads").count() == 4, "not for the temporary files"
    assert phone.get_by_role("button", name="Delete").count() == 5
    assert "keptFiles" == order(phone)[0] and phone.rn()["listCalls"] == 1


def test_an_empty_list_says_nothing_is_kept_and_has_no_buttons(phone):
    open_kept(phone, kept=[])
    listed(phone)
    assert "Nothing is kept for safety." in card(phone)
    assert phone.locator("#app button").count() == 0


def test_a_list_that_cannot_be_read_is_not_shown_as_an_empty_one(phone):
    sentence = SENT["LIST_FAILED"]
    assert sentence == "The list of kept files could not be read. Nothing was changed."
    open_kept(phone, kept=[], keptError=sentence)
    listed(phone)
    assert alert(phone) == sentence
    assert "Nothing is kept for safety" not in card(phone)
    for raw in ("not json", "[1]", "null", "", '{"items": "x"}', "{}"):
        phone.evaluate("r => { window.__rn.keptRaw = r; kept = keptFresh(); render(); }", raw)
        phone.wait_for_timeout(50)
        assert alert(phone) == sentence, raw
        assert "Nothing is kept for safety" not in card(phone), raw


def test_with_an_older_bridge_that_cannot_list_the_page_says_so_and_changes_nothing(phone):
    phone.set_default_timeout(8000)
    phone.open_with({"db": SAFE_LIBRARY}, "#/kept")  # the plain fake bridge: no keptFiles
    listed(phone)
    assert alert(phone) == "The list of kept files could not be read. Nothing was changed."
    assert phone.locator("#app button").count() == 0


def test_the_privacy_wording_is_on_the_screen_before_anything_can_be_saved(phone):
    open_kept(phone)
    listed(phone)
    text = " ".join(phone.locator("#keptprivacy").inner_text().split())
    assert "A file kept for safety is a copy of your private library: your reels, notes, watchlist, quotes and products" in text
    assert "a short part of the text read from each screenshot, and their file names" in text
    assert "Saving one to Downloads/ReelShelf puts a copy where other apps and file managers can read it, and anyone who gets that file can read it." in text
    assert "It does not contain your settings, API keys or AI models." in text
    assert "never deletes them by itself" in card(phone)


def test_the_page_sentences_are_the_phones_sentences(phone):
    phone.open_with({"db": SAFE_LIBRARY}, "#/settings")
    assert phone.evaluate("KEPT_WORK") == SENT["WORK"]
    assert phone.evaluate("KEPT_BUSY") == SENT["BUSY"]
    assert SENT["WORK"].endswith("Nothing was deleted.") and SENT["BUSY"].endswith("Nothing was deleted.")


def test_hostile_names_and_numbers_from_the_phone_are_only_ever_text(phone):
    bad = '<img src=x onerror="window.__pwned=1">'
    hostile = [{"name": bad, "kind": "<b>bad</b>", "library": bad, "size": "<i>9</i>", "at": "<u>1</u>", "files": {"x": 1}},
               {"name": bad + "2", "kind": "temp", "library": "", "size": -5, "at": None, "files": "<b>3</b>"}]
    open_kept(phone, kept=hostile)
    listed(phone)
    assert phone.locator("#app img").count() == 0 and phone.locator("#app b").count() == 0 and phone.locator("#app i").count() == 0 and phone.locator("#app u").count() == 0
    assert bad in card(phone), "shown as it is, as text"
    assert phone.evaluate("window.__pwned") is None
    assert phone.evaluate("[...document.querySelectorAll('[data-ksave]')].map((b) => b.dataset.ksave)") == [bad], "the exact name goes back to the phone"
    phone.locator("[data-ksave]").first.click()
    phone.wait_for_function("() => window.__rn.saveCalls")
    assert phone.rn()["saveCalls"] == [bad]
    phone.locator("#app [role=status]").wait_for()
    assert phone.locator("#app img").count() == 0 and phone.evaluate("window.__pwned") is None, "the answer's text is text too"


# ---------------------------------------------------------------- Save to Downloads

def test_save_asks_the_phone_for_that_name_only_and_says_where_it_went_and_that_it_is_private(phone):
    open_kept(phone)
    listed(phone)
    save_button(phone, NAME_RESTORE).click()
    phone.locator("#app [role=status]").wait_for()
    assert phone.rn()["saveCalls"] == [NAME_RESTORE]
    assert order(phone) == ["keptFiles", "saveKept"], "no ask, no delete"
    first = cards(phone)[0]
    assert f"Saved to Downloads/ReelShelf/saved-{NAME_RESTORE}.txt ({size_of(phone, 4404019)})" in first
    assert "That copy is private data too: delete it from Downloads when you no longer need it." in first
    assert "deleted if you uninstall" not in first
    assert phone.get_by_role("button", name="Save to Downloads").first.is_enabled()
    assert len(cards(phone)) == 5 and phone.rn()["kept"] == LIST, "the kept file is still there and the list is the same"


def test_while_it_saves_every_button_is_off_and_a_second_tap_asks_nothing_more(phone):
    open_kept(phone, save={"hold": True})
    listed(phone)
    save_button(phone, NAME_BAD).click()
    phone.wait_for_function("() => window.__rn.saveCalls")
    expect(phone.get_by_role("button", name="Saving...")).to_be_disabled()
    assert all(not b.is_enabled() for b in phone.locator("#app button").all())
    phone.evaluate("(n) => keptSave(n)", NAME_BAD_SHOTS)
    phone.evaluate("(n) => keptAsk(n)", NAME_BAD)
    phone.wait_for_timeout(100)
    assert phone.rn()["saveCalls"] == [NAME_BAD] and "askDeleteKept" not in order(phone)
    phone.evaluate("([id, a]) => rnDone(id, true, JSON.stringify(a))", [phone.evaluate("window.__saveId"), {"name": "n.txt", "where": "Downloads/ReelShelf/n.txt", "bytes": 5, "uninstall_warning": False}])
    phone.locator("#app [role=status]").wait_for()
    assert phone.get_by_role("button", name="Delete").first.is_enabled()


def test_on_android_8_and_9_it_says_the_copy_goes_when_the_app_is_uninstalled(phone):
    open_kept(phone, save={"ok": {"uninstall_warning": True, "where": "Android/data/app.reelshelf/files/Download/ReelShelf/x.txt"}})
    listed(phone)
    save_button(phone, NAME_BAD).click()
    phone.locator("#app [role=status]").wait_for()
    text = cards(phone)[3]
    assert "Saved to Android/data/app.reelshelf/files/Download/ReelShelf/x.txt" in text
    assert "This file is in the app's own folder on this version of Android, so it is deleted if you uninstall Reel Shelf." in text


def test_a_save_that_failed_shows_the_phones_sentence_and_changes_nothing(phone):
    sentence = SENT["READ_BACK"]
    open_kept(phone, save={"fail": sentence})
    listed(phone)
    save_button(phone, NAME_BAD).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == sentence
    assert "Saved to" not in card(phone)
    assert phone.rn()["kept"] == LIST and len(cards(phone)) == 5
    assert phone.get_by_role("button", name="Save to Downloads").first.is_enabled()
    phone.evaluate("() => { window.__rn.save = {}; }")  # tried again: the old failure is gone
    save_button(phone, NAME_BAD).click()
    phone.locator("#app [role=status]").wait_for()
    assert phone.locator("#app [role=alert]").count() == 0


@pytest.mark.parametrize("raw", ["not json", "[1]", "{}", "null", ""])
def test_an_answer_to_a_save_that_the_page_cannot_read_is_a_plain_sentence(phone, raw):
    open_kept(phone, save={"raw": raw})
    listed(phone)
    save_button(phone, NAME_BAD).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == "The file could not be saved. The kept file was not changed."


def test_saving_is_never_refused_by_work_a_night_or_a_backup(phone):
    open_kept(phone)
    listed(phone)
    phone.evaluate("run = { codes: ['A'], i: 0, step: 'ai', finished: false, log: [] }; backup.running = true;")
    save_button(phone, NAME_BAD).click()
    phone.locator("#app [role=status]").wait_for()
    assert phone.rn()["saveCalls"] == [NAME_BAD], "listing and saving are always allowed"


# ---------------------------------------------------------------- Delete: the confirmation screen

def test_delete_only_asks_and_shows_the_confirm_screen_with_the_name_the_date_the_size_and_that_it_cannot_be_undone(phone):
    open_kept(phone)
    listed(phone)
    to_confirm(phone)
    assert phone.rn()["askCalls"] == [NAME_RESTORE]
    assert order(phone) == ["keptFiles", "askDeleteKept"], "nothing is deleted by asking"
    q = norm(phone.locator("#kquestion").inner_text())
    assert q == (f'Delete "Your library before a restore", the file {NAME_RESTORE}, kept since {date_of(phone, AT_RESTORE)} ({size_of(phone, 4404019)})? '
                 "This cannot be undone: once it is deleted it is gone from the phone.")
    assert "Your current library is not touched. If you might need this file, cancel and save it to Downloads first." in card(phone)
    assert confirm_button(phone).is_enabled() and phone.get_by_role("button", name="Cancel").is_enabled()
    assert phone.get_by_role("button", name="Save to Downloads").count() == 0 and phone.get_by_role("heading", name="Delete this file?").count() == 1
    assert phone.rn()["kept"] == LIST and not phone.rn().get("deleteCalls")


def test_cancel_goes_back_to_the_list_and_nothing_is_deleted(phone):
    open_kept(phone)
    listed(phone)
    to_confirm(phone)
    phone.get_by_role("button", name="Cancel").click()
    phone.get_by_text("Kept when a backup replaced it.").first.wait_for()
    assert phone.locator("#kquestion").count() == 0
    assert "deleteKept" not in order(phone) and phone.rn()["kept"] == LIST
    assert len(cards(phone)) == 5


def test_leaving_the_confirm_screen_drops_it_and_coming_back_shows_the_list(phone):
    open_kept(phone)
    listed(phone)
    to_confirm(phone)
    go(phone, "#/settings")
    phone.locator("#keptbtn").wait_for()
    go(phone, "#/kept")
    listed(phone)
    assert phone.locator("#kquestion").count() == 0 and len(cards(phone)) == 5
    assert "deleteKept" not in order(phone)
    assert phone.rn()["listCalls"] == 2, "listed again when the screen was opened again"
    assert phone.evaluate("keptGo(), 1") == 1  # a stray call with no confirmation does nothing at all
    phone.wait_for_timeout(100)
    assert "deleteKept" not in order(phone)


def test_the_back_arrow_of_the_confirm_screen_leaves_without_deleting(phone):
    open_kept(phone)
    listed(phone)
    to_confirm(phone)
    phone.locator("#app .icon-btn").click()
    phone.locator("#keptbtn").wait_for()
    assert "deleteKept" not in order(phone) and phone.rn()["kept"] == LIST


def test_confirming_deletes_that_file_with_the_token_the_phone_gave_once_and_reads_the_list_again(phone):
    open_kept(phone)
    listed(phone)
    to_confirm(phone, NAME_BAD_SHOTS)
    confirm_button(phone).click()
    phone.locator("#app [role=status]").wait_for()
    rn = phone.rn()
    assert rn["deleteCalls"] == [[NAME_BAD_SHOTS, "ktok-1"]], "that name, that token, once"
    assert order(phone) == ["keptFiles", "askDeleteKept", "deleteKept", "keptFiles"], "ask first, then delete, then the list again"
    assert rn["deleted"] == [NAME_BAD_SHOTS]
    assert [x["name"] for x in rn["kept"]] == [NAME_RESTORE, NAME_BAD_BAK, NAME_BAD, TEMP], "only that file is gone"
    text = card(phone)
    assert "Deleted: Your screenshot list that could not be read (51 KB). It cannot be brought back." in text
    assert NAME_BAD_SHOTS not in text and len(cards(phone)) == 4
    assert phone.locator("#kquestion").count() == 0, "back on the list"


def test_a_second_tap_while_it_deletes_asks_the_phone_once_and_the_button_says_so(phone):
    open_kept(phone, **{"del": {"hold": True}})
    listed(phone)
    to_confirm(phone)
    confirm_button(phone).click()
    phone.wait_for_function("() => window.__rn.deleteCalls")
    expect(phone.get_by_role("button", name="Deleting...")).to_be_disabled()
    phone.evaluate("keptGo()")
    phone.evaluate("keptGo()")
    phone.wait_for_timeout(100)
    assert phone.rn()["deleteCalls"] == [[NAME_RESTORE, "ktok-1"]]
    phone.evaluate("() => window.__finishDelete()")
    phone.locator("#app [role=status]").wait_for()
    assert len(phone.rn()["deleted"]) == 1


def test_the_page_never_calls_delete_without_asking_first(phone):
    open_kept(phone)
    listed(phone)
    for name in (NAME_RESTORE, NAME_BAD, TEMP):
        delete_button(phone, name).click()
        phone.locator("#kquestion").wait_for()
        phone.get_by_role("button", name="Cancel").click()
        phone.locator("[data-kdel]").first.wait_for()
    assert order(phone) == ["keptFiles"] + ["askDeleteKept"] * 3
    to_confirm(phone, NAME_BAD)
    confirm_button(phone).click()
    phone.locator("#app [role=status]").wait_for()
    seq = order(phone)
    assert seq.count("deleteKept") == 1 and seq[seq.index("deleteKept") - 1] == "askDeleteKept"
    assert phone.rn()["deleteCalls"] == [[NAME_BAD, "ktok-4"]], "the token of the last ask, for the file that was shown"


def test_the_temporary_files_have_a_delete_with_its_own_wording_and_no_save(phone):
    open_kept(phone)
    listed(phone)
    to_confirm(phone, TEMP)
    assert norm(phone.locator("#kquestion").inner_text()) == "Delete the temporary restore files (3 files, 15 KB together)? This cannot be undone: once it is deleted it is gone from the phone."
    assert "They are only copies made while a backup file was checked. Your library is not touched." in card(phone)
    confirm_button(phone).click()
    phone.locator("#app [role=status]").wait_for()
    assert phone.rn()["deleted"] == [TEMP]
    assert "Deleted: Temporary restore files (15 KB)." in card(phone)


# ---------------------------------------------------------------- Delete: refused

@pytest.mark.parametrize("job", ["run = { codes: ['A'], i: 0, step: 'ai', finished: false, log: [] };", "modelDl = { d: 1, t: 2 };"])
def test_delete_is_refused_by_the_page_while_work_runs_and_the_phone_is_not_even_asked(phone, job):
    open_kept(phone)
    listed(phone)
    phone.evaluate(job)
    delete_button(phone, NAME_RESTORE).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == SENT["WORK"]
    assert "askDeleteKept" not in order(phone) and phone.locator("#kquestion").count() == 0 and phone.rn()["kept"] == LIST


def test_delete_is_refused_while_the_nightly_run_is_going_or_a_backup_or_restore_runs(phone):
    open_kept(phone)
    listed(phone)
    phone.evaluate("() => { window.__rn.nightActive = true; }")
    delete_button(phone, NAME_BAD).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == SENT["WORK"]
    phone.evaluate("() => { window.__rn.nightActive = false; backup.running = true; }")
    delete_button(phone, NAME_BAD).click()
    assert alert(phone) == SENT["BUSY"]
    phone.evaluate("() => { backup.running = false; restore.busy = 'check'; }")
    delete_button(phone, NAME_BAD).click()
    assert alert(phone) == SENT["BUSY"]
    assert "askDeleteKept" not in order(phone) and not phone.rn().get("deleteCalls")


@pytest.mark.parametrize("key", ["WORK", "LOCKED", "BUSY", "WAITING", "NOT_KEPT"])
def test_the_phones_refusal_at_the_ask_is_shown_as_it_is_and_no_confirm_screen_opens(phone, key):
    sentence = SENT[key]
    open_kept(phone, ask={"fail": sentence})
    listed(phone)
    delete_button(phone, NAME_RESTORE).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == sentence
    assert phone.locator("#kquestion").count() == 0 and not phone.rn().get("deleteCalls") and phone.rn()["kept"] == LIST
    assert phone.rn()["listCalls"] == 2, "the list is read again: it may have changed"


@pytest.mark.parametrize("raw", ["not json", "[1]", "{}", "null", "", '{"ok": true}', '{"ok": true, "token": "t"}', '{"ok": true, "token": "", "item": {"name": "x"}}',
                                 '{"ok": true, "token": "t", "item": {"name": "some other file"}}', '{"ok": false}'])
def test_an_answer_to_the_ask_that_the_page_cannot_use_never_opens_the_confirm_screen(phone, raw):
    open_kept(phone, ask={"raw": raw})
    listed(phone)
    delete_button(phone, NAME_RESTORE).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == "That file could not be checked. Nothing was deleted."
    assert phone.locator("#kquestion").count() == 0 and not phone.rn().get("deleteCalls")


def test_a_file_that_is_gone_when_asked_says_so_and_the_list_is_read_again_without_it(phone):
    open_kept(phone)
    listed(phone)
    phone.evaluate("(n) => { window.__rn.kept = window.__rn.kept.filter((x) => x.name !== n); }", NAME_BAD)  # removed elsewhere since the list was read
    delete_button(phone, NAME_BAD).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == SENT["GONE"]
    phone.wait_for_function("(n) => !document.body.innerText.includes(n)", arg=NAME_BAD)
    assert len(cards(phone)) == 4


def test_the_phones_refusal_at_the_delete_is_shown_and_the_file_stays(phone):
    sentence = SENT["WORK"]
    open_kept(phone, **{"del": {"fail": sentence}})
    listed(phone)
    to_confirm(phone)
    confirm_button(phone).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == sentence
    rn = phone.rn()
    assert rn["deleteCalls"] == [[NAME_RESTORE, "ktok-1"]] and rn["kept"] == LIST and not rn.get("deleted")
    assert phone.locator("#kquestion").count() == 0, "back on the list, which was read again"
    assert rn["listCalls"] == 2 and len(cards(phone)) == 5


def test_a_job_started_after_the_confirm_screen_opened_stops_the_delete_and_the_same_confirmation_still_works_after(phone):
    open_kept(phone)
    listed(phone)
    to_confirm(phone)
    phone.evaluate("run = { codes: ['A'], i: 0, step: 'ai', finished: false, log: [] };")
    confirm_button(phone).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == SENT["WORK"]
    assert "deleteKept" not in order(phone) and phone.locator("#kquestion").count() == 1, "still on the confirm screen"
    phone.evaluate("run = null")
    confirm_button(phone).click()
    phone.locator("#app [role=status]").wait_for()
    assert phone.rn()["deleteCalls"] == [[NAME_RESTORE, "ktok-1"]]


def test_a_token_that_the_phone_no_longer_knows_deletes_nothing_and_the_page_goes_back_to_the_list(phone):
    open_kept(phone)
    listed(phone)
    to_confirm(phone)
    phone.evaluate("() => { window.__rn.pending = null; }")  # timed out, or another ask replaced it
    confirm_button(phone).click()
    phone.locator("#app [role=alert]").wait_for()
    assert alert(phone) == SENT["NOT_CONFIRMED"]
    assert phone.rn()["kept"] == LIST and not phone.rn().get("deleted")
    assert phone.locator("#kquestion").count() == 0 and len(cards(phone)) == 5


# ---------------------------------------------------------------- the screens that stay first, and the ones that cannot reach this

def test_the_waiting_screen_of_the_nightly_run_is_first_and_nothing_is_listed_meanwhile(phone):
    phone.context.add_init_script(FAST)
    open_kept(phone, nightActive=True)
    phone.get_by_text("The nightly run is finishing").wait_for()
    for route in ("#/kept", "#/settings", "#/inbox", "#/"):
        go(phone, route)
        phone.wait_for_timeout(80)
        assert phone.get_by_text("The nightly run is finishing").is_visible(), route
        assert phone.locator("[data-ksave]").count() == 0 and phone.locator("[data-kdel]").count() == 0 and phone.locator("#keptbtn").count() == 0, route
    assert "keptFiles" not in order(phone), "nothing was listed, asked or deleted while the night finished"
    phone.evaluate("() => { window.__rn.nightActive = false; }")
    phone.get_by_text("The nightly run is finishing").wait_for(state="hidden")
    go(phone, "#/kept")
    listed(phone)
    assert len(cards(phone)) == 5


def test_while_a_restore_installs_this_screen_is_not_shown(phone):
    open_kept(phone, "#/restore", scripts=[RESTORE_RN], choose={"preview": PREVIEW}, backupDb=BACKED_UP, install={"hold": True})
    pick(phone)
    confirm_screen(phone)
    phone.get_by_label("Save a backup of the current library first").uncheck()
    restore_button(phone).click()
    phone.wait_for_function("() => window.__rn.restoreCalls")
    go(phone, "#/kept")
    phone.wait_for_timeout(80)
    assert "Restoring. Please keep the app open." in card(phone)
    assert "keptFiles" not in order(phone) and phone.locator("[data-kdel]").count() == 0


def test_an_unreadable_library_shows_its_own_screen_on_this_route_and_nothing_is_asked(phone):
    open_kept(phone, "#/kept", with_lib=True, **{"db": DAMAGED, "shared": [LINK], "lib": {"reels": {"state": "unreadable"}}})
    locked_screen(phone)
    for route in ("#/kept", "#/settings"):
        go(phone, route)
        locked_screen(phone)
    assert phone.locator("[data-ksave]").count() == 0 and phone.locator("[data-kdel]").count() == 0
    assert not (set(order(phone)) & {"keptFiles", "saveKept", "askDeleteKept", "deleteKept"})
    assert phone.rn()["db"] == DAMAGED and phone.rn()["kept"] == LIST


@pytest.mark.parametrize("flavour", ["phone", "page"])
def test_a_newer_library_shows_its_own_screen_on_this_route_and_nothing_is_asked(phone, flavour):
    for s in (BACKUP_RN, KEPT_RN):
        phone.context.add_init_script(s)
    phone.set_default_timeout(8000)
    reels, shots = newer_reels(), newer_shots()
    open_newer(phone, flavour, reels, shots, hash_="#/kept", kept=[dict(x) for x in LIST])
    phone.get_by_text("This library was saved by a newer Reel Shelf.").first.wait_for()
    assert phone.locator("[data-ksave]").count() == 0 and phone.locator("[data-kdel]").count() == 0
    phone.wait_for_timeout(150)
    assert not (set(order(phone)) & {"keptFiles", "saveKept", "askDeleteKept", "deleteKept"})
    assert phone.rn()["db"] == reels and phone.rn()["shotsDb"] == shots and phone.rn()["kept"] == LIST


def test_the_restore_screen_the_backup_section_and_the_settings_are_unchanged_by_the_new_entry(phone):
    open_kept(phone, "#/settings")
    phone.locator("#backupnow").wait_for()
    names = [n.strip() for n in phone.locator("#backup .btn").all_inner_texts()]
    assert names == ["Back up now", "Restore from a backup", "Files kept for safety"]


# ---------------------------------------------------------------- the bridge itself (LocalBridge.java cannot run here: what it must do is pinned in its source)

def method(name):
    """The text of a method of LocalBridge.java (from its signature, a throws clause allowed, to the matching closing brace)."""
    text = (JAVA / "LocalBridge.java").read_text(encoding="utf-8")
    m = re.search(r"\n    (?:@JavascriptInterface\n    )?(?:public |private )?(?:static )?[\w.<>\[\]]+ %s\([^)]*\)(?: throws [\w., ]+)? \{" % re.escape(name), text)
    assert m, name
    depth = 0
    for j in range(m.end() - 1, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[m.start():j + 1]
    raise AssertionError("unbalanced " + name)


def kept_section():
    text = (JAVA / "LocalBridge.java").read_text(encoding="utf-8")
    start = text.index("// ------------------------------------------------------------------ files kept for safety")
    end = text.index("     * What was shared while the app was closed")
    return text[start:end]


def test_every_bridge_call_for_kept_files_is_behind_the_trust_gate_and_none_deletes_by_itself():
    section = kept_section()
    for name in ("keptFiles", "saveKept", "askDeleteKept", "deleteKept"):
        body = method(name)
        assert "if (!ok()) return" in body, name
    assert not re.search(r"(?<!KeptFiles)\.delete\(|(?<!Kept)Files\.delete|deleteRecursively|deleteIfExists|\.renameTo\(", section), "every delete goes through KeptFiles"
    assert "KeptFiles.delete(keptEnv(), name, token)" in method("deleteKept") and "KeptFiles.ask(keptEnv(), name)" in method("askDeleteKept")


def test_the_delete_is_handed_the_flag_the_work_checks_and_the_waiting_restore_of_the_real_bridge():
    env = method("keptEnv")
    assert "LIBRARY_JOB" in env, "the one-at-a-time flag of the backup and the restore"
    assert "this::busyWithWork" in env, "a job, a download and the nightly run"
    assert "STAGE" in env and "KEPT_CONFIRM" in env and "reelsFile()" in env and "shotsFile()" in env
    busy = method("busyWithWork")
    for needed in ("act.isNight()", "WorkService.isRunning()", "WorkService.nightActive()"):
        assert needed in busy, needed
    assert "private static final KeptFiles.Confirm KEPT_CONFIRM = new KeptFiles.Confirm();" in (JAVA / "LocalBridge.java").read_text(encoding="utf-8"), "one pending confirmation for the whole app"


def test_a_save_uses_the_hidden_until_proven_mechanism_of_back_up_now_and_a_read_back():
    body = method("saveKeptNow")
    call = body[body.index("saveToDownloads("):]
    assert 'KeptFiles.saveName(it), "text/plain"' in call
    assert "KeptFiles.EMPTY, in -> KeptFiles.verify(in, sha[0], size[0])" in call, "a read-back is given, so IS_PENDING (Android 10 and newer) or NAME.part (8 and 9) is used"
    assert ", null)" not in call
    assert body.index("KeptFiles.find(") < body.index("saveToDownloads("), "the name is looked up again before anything is copied"
    assert "KeptFiles.TEMP_SAVE" in body and "KeptFiles.NOT_KEPT" in body
    assert "LIBRARY_JOB" not in body and "busyWithWork" not in body, "saving is never blocked by work"
    assert "SharedItems.RESERVE_BYTES" in body, "the same reserve of free space as Back up now"


def test_keptfiles_removes_files_in_exactly_one_place_and_never_a_folder():
    text = (JAVA / "KeptFiles.java").read_text(encoding="utf-8")
    assert len(re.findall(r"Files\.delete\(", text)) == 1 and "private static void deleteRegular(" in text
    assert not re.search(r"\.delete\(\)|deleteRecursively|deleteIfExists|\.renameTo\(|\.mkdir", text)
    assert text.count("deleteRegular(") == 3, "the definition and its two uses: one file, or the plain files of the two temporary folders"
    assert "TEMP_FOLDERS = {\"restore-staging\", \"backup-check\"}" in text
    assert "NOFOLLOW_LINKS" in text and "isSymbolicLink()" in text


def test_the_java_sentences_were_found_so_the_refusal_tests_above_are_not_empty():
    assert {"NOT_KEPT", "GONE", "CHANGED", "NOT_CONFIRMED", "BUSY", "WORK", "LOCKED", "WAITING", "NOT_DELETED", "LIST_FAILED", "TEMP_SAVE", "READ_BACK", "GENERIC_SAVE", "DISK_FULL"} <= set(SENT)
    assert all(s.endswith(".") for k, s in SENT.items() if k not in ("TEMP_NAME", "STAMP_FORMAT", "EMPTY", "TAIL"))
    assert ASIDE.startswith("reels.json.before-restore-"), "the name the restore screen shows is one the list would show"
