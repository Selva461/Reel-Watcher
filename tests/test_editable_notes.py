"""K1-1: notes you edited are never overwritten (data model, helpers and guards; no screen for editing yet).

A reel whose notes you edited has notes_by "you" and notes_edit; an AI answer for it (Meta AI by any path, or the on-phone AI)
is kept aside in notes_next and says so. Phone harness (Chromium at phone size, the fake window.RN of test_phone_app.py): no
network, no model. The page's clock is pinned (window.__now). The pure helpers are called directly in the page; the guards are
driven the way the app reaches them (shared answers, the paste dialog, Add, the inbox pick, the night run, Start)."""
import copy
import json

import pytest

from test_library_upgrade import FIXTURES_NOW, NEWEST, check_diff, diff, expected, open_fixture, texts
from test_phone_app import ANSWER, db_of, phone, site  # noqa: F401  (pytest fixtures)

CLOCK = "window.__now = %d; Date.now = () => window.__now;" % FIXTURES_NOW
READY = {"ready": True, "partial": 0, "installed": []}
KEPT = "Kept aside: this reel has your edits. Open it to compare."
AI_TOPIC = "Hardcoded secrets in mobile apps"  # the topic of ANSWER


def notes(**more):
    return {"topic": "Passwords in apps", "intent": "", "tone": "", "points": ["First point about passwords", "Second point about keys"],
            "meaning": "Anything shipped inside an app can be read.", "use": [], "tools": ["gitleaks"], "takeaway": "Keep secrets on the server.",
            "tags": ["security", "apps"], **more}


def reel(code, **more):
    return {"code": code, "url": "https://www.instagram.com/reel/%s/" % code, "author": "", "collections": [], "status": "done", "added_at": 1000,
            "caption": "Three free tools for taking notes on your phone: " + code, "caption_read": 1, "video_tried": 1, **more}


def edited(code, **more):
    """A reel the user edited (topic and takeaway), as applyEdit leaves it."""
    return reel(code, notes=notes(topic="My own topic", takeaway="My own takeaway"), notes_by="you", notes_at=5, raw="raw text of the AI answer",
                notes_edit={"was_by": "phone", "at": 7, "fields": ["topic", "takeaway"],
                            "ai": {"topic": "Passwords in apps", "takeaway": "Keep secrets on the server."}}, **more)


def answer_for(code, topic="A newer topic from Meta AI"):
    return ("https://www.instagram.com/reel/%s/\n\nTOPIC: %s\nPOINTS:\n1. A new point\nMEANING: Something new.\nPRODUCTS: Acme Soap\n"
            "TAKEAWAY: A new takeaway.\nTAGS: #newtag" % (code, topic))


def start(pg, reels, **extra):
    pg.set_default_timeout(8000)
    pg.context.add_init_script(CLOCK)
    pg.open_with({"db": json.dumps({"reels": reels, "inbox": extra.pop("inbox", [])}), **extra})


def by_code(pg):
    return {r["code"]: r for r in db_of(pg)["reels"]}


def generate_calls(pg):
    return [c for c in pg.rn()["calls"] if c[0] == "generate"]


def watch_toasts(pg):
    pg.evaluate("() => { window.__toasts = []; const t = toast; window.toast = (m) => { window.__toasts.push(m); t(m); }; }")


def toasts(pg):
    return pg.evaluate("() => window.__toasts")


# ---------------------------------------------------------------- 1. applyEdit

def test_editing_a_topic_marks_the_reel_yours_keeps_the_ai_text_and_search_finds_it(phone):
    quick = reel("REEL1", notes=notes(unbacked=2), notes_by="auto", status="failed", error="boom", tries=2, next_try_at=9, last_fail="x", last_fail_at=8, notes_at=3)
    start(phone, [quick, reel("REEL2", notes=notes(topic="Other"), notes_by="meta")])
    assert phone.evaluate("() => Notes.search(db.reels, 'zebrafish').length") == 0
    assert phone.evaluate("() => Notes.applyEdit(reel('REEL1'), 'topic', '  My   own zebrafish topic ', Date.now())") is True
    assert phone.evaluate("() => saveDb()") is True  # what the page does after an edit: RN.store gets it
    r = by_code(phone)["REEL1"]
    assert r["notes_by"] == "you" and r["notes"]["topic"] == "My own zebrafish topic"
    assert r["notes_edit"] == {"was_by": "auto", "at": FIXTURES_NOW, "fields": ["topic"], "ai": {"topic": "Passwords in apps"}}
    assert r["status"] == "done" and r["error"] == "" and r["notes_at"] == FIXTURES_NOW
    assert not any(k in r for k in ("tries", "next_try_at", "last_fail", "last_fail_at"))
    assert {k: v for k, v in r["notes"].items() if k != "topic"} == {k: v for k, v in notes(unbacked=2).items() if k != "topic"}  # nothing else moved
    assert phone.evaluate("() => Notes.search(db.reels, 'zebrafish').map((x) => x.reel.code)") == ["REEL1"]
    assert by_code(phone)["REEL2"]["notes"]["topic"] == "Other" and "notes_by" in by_code(phone)["REEL2"] and by_code(phone)["REEL2"]["notes_by"] == "meta"


def test_a_second_edit_keeps_the_first_ai_text_and_a_points_edit_drops_the_left_out_line(phone):
    start(phone, [reel("REEL1", notes=notes(unbacked=2), notes_by="phone", notes_at=1)])
    ok = phone.evaluate("""() => { const r = reel('REEL1'), t = 5;
      return [Notes.applyEdit(r, 'topic', 'First edit', t), Notes.applyEdit(r, 'topic', 'Second edit', t + 1), Notes.applyEdit(r, 'points', 'my one\\nmy two', t + 2)]; }""")
    assert ok == [True, True, True]
    r = phone.evaluate("() => reel('REEL1')")
    assert r["notes_edit"]["ai"]["topic"] == "Passwords in apps"  # written once, at the first edit of the field
    assert r["notes_edit"]["ai"]["points"] == notes()["points"] and r["notes_edit"]["fields"] == ["topic", "points"]
    assert r["notes_edit"]["at"] == 5 and r["notes_at"] == 7 and r["notes_edit"]["was_by"] == "phone"
    assert r["notes"]["points"] == ["my one", "my two"] and "unbacked" not in r["notes"]


def test_an_edit_that_changes_nothing_or_is_refused_leaves_the_reel_as_it_was(phone):
    start(phone, [reel("REEL1", notes=notes(), notes_by="auto")])
    before = phone.evaluate("() => JSON.parse(JSON.stringify(reel('REEL1')))")
    got = phone.evaluate("""() => { const r = reel('REEL1');
      return [Notes.applyEdit(r, 'topic', ' Passwords   in apps ', 1), Notes.applyEdit(r, 'points', ['First point about passwords', 'Second point about keys'], 1),
              Notes.applyEdit(r, 'topic', 'x'.repeat(201), 1), Notes.applyEdit(r, 'intent', 'not editable', 1), Notes.applyEdit(r, 'tags', 'a b c d e f g h i j k l m n', 1)]; }""")
    assert got == [False] * 5
    assert phone.evaluate("() => reel('REEL1')") == before  # still quick notes: Start may still rewrite them


def test_writing_notes_from_scratch_has_no_ai_text_to_go_back_to(phone):
    start(phone, [reel("REEL1", status="ready", notes=None)])
    assert phone.evaluate("() => Notes.applyEdit(reel('REEL1'), 'topic', 'Mine', 1)") is True
    r = phone.evaluate("() => reel('REEL1')")
    assert r["notes_by"] == "you" and r["notes"]["topic"] == "Mine" and r["notes"]["points"] == [] and r["status"] == "done"
    assert r["notes_edit"] == {"was_by": "", "at": 1, "fields": ["topic"], "ai": {}}
    assert phone.evaluate("() => Notes.revertField(reel('REEL1'), 'topic')") is False and phone.evaluate("() => reel('REEL1').notes.topic") == "Mine"
    assert phone.evaluate("() => Notes.applyEdit(reel('REEL1'), 'topic', '', 2)") is False  # a topic and points both empty is not notes


# ---------------------------------------------------------------- 2. an edited reel is not rewritten by Start or the night

def test_an_edited_quick_notes_reel_is_never_picked_by_start_or_the_night_and_the_ai_is_not_called(phone):
    a, b = reel("A1", notes=notes(), notes_by="auto", added_at=1000), reel("B1", notes=notes(topic="Other"), notes_by="auto", added_at=900)
    start(phone, [a, b], model=READY, answers=[ANSWER])
    assert phone.evaluate("() => [needsWork(reel('A1'), true), needsWork(reel('B1'), true)]") == [True, True]  # a quick-notes reel is normally rewritten
    assert phone.evaluate("() => Notes.applyEdit(reel('A1'), 'tags', 'mine, own', 1)") is True
    assert phone.evaluate("() => [needsWork(reel('A1'), true), needsWork(reel('A1'), false)]") == [False, False]
    assert phone.evaluate("() => nightQueue(db.reels, true, Date.now(), 200).map((r) => r.code)") == ["B1"]
    phone.evaluate("() => startRun()")
    calls = generate_calls(phone)
    assert len(calls) == 1 and "B1" in calls[0][1] and "A1" not in calls[0][1]  # only the reel nobody edited was sent to the model
    phone.evaluate("() => startRun(['A1'])")  # by hand (Read this reel properly, Try again now): still not
    assert len(generate_calls(phone)) == 1
    r = by_code(phone)
    assert r["A1"]["notes_by"] == "you" and r["A1"]["notes"]["tags"] == ["mine", "own"] and r["A1"]["notes"]["topic"] == "Passwords in apps"
    assert r["B1"]["notes_by"] == "phone"


# ---------------------------------------------------------------- 3. every writer keeps its answer aside

def check_kept(pg, code="REEL1", before=None, where="meta"):
    after = by_code(pg)[code]
    slot = after.pop("notes_next")[where]
    assert slot["notes"]["topic"] and slot["at"] == FIXTURES_NOW and slot["raw"]
    assert after == before  # notes, notes_by, notes_at, status, raw, notes_edit: untouched
    assert "products" not in db_of(pg) or db_of(pg)["products"] == []  # the answer's PRODUCTS line did not reach Products
    return slot


def test_a_shared_meta_answer_for_an_edited_reel_is_kept_aside_and_acknowledged(phone):
    start(phone, [edited("REEL1")], shared=[answer_for("REEL1")])
    phone.wait_for_function("() => window.__rn.shared.length === 0")  # acknowledged after the save
    phone.wait_for_function("() => document.getElementById('toast').textContent.includes('Kept aside')")
    assert phone.evaluate("() => document.getElementById('toast').textContent") == KEPT  # one reel: the single message, no "filed"
    slot = check_kept(phone, before=edited("REEL1"))
    assert slot["notes"]["topic"] == "A newer topic from Meta AI" and "TOPIC: A newer topic" in slot["raw"]


def test_several_shared_answers_kept_aside_are_counted(phone):
    start(phone, [edited("REEL1"), edited("REEL2"), reel("REEL3")], shared=[answer_for("REEL1"), answer_for("REEL2"), answer_for("REEL3")])
    phone.wait_for_function("() => document.getElementById('toast').textContent.includes('Kept aside')")
    assert phone.evaluate("() => document.getElementById('toast').textContent") == "1 Meta AI answer filed. Kept aside: 2 reels have your edits. Open them to compare."
    r = by_code(phone)
    assert r["REEL3"]["notes"]["topic"] == "A newer topic from Meta AI" and r["REEL3"]["notes_by"] == "meta" and "notes_next" not in r["REEL3"]
    assert "notes_next" in r["REEL1"] and "notes_next" in r["REEL2"] and r["REEL1"]["notes"]["topic"] == "My own topic"


def test_the_paste_dialog_keeps_the_answer_aside_and_does_not_say_saved(phone):
    start(phone, [edited("REEL1")], settings=json.dumps({"metaAi": True}))
    phone.goto(phone.url.split("#")[0] + "#/r/REEL1")
    watch_toasts(phone)
    phone.get_by_role("button", name="Paste an answer").click()
    phone.locator("#ans").fill(answer_for("REEL1"))
    phone.get_by_role("button", name="Save", exact=True).click()
    phone.wait_for_function("() => window.__toasts.length > 0")
    assert toasts(phone) == [KEPT]  # not "Saved"
    check_kept(phone, before=edited("REEL1"))
    # a reel nobody edited still says Saved
    start(phone, [reel("REEL9", notes=notes(), notes_by="auto")], settings=json.dumps({"metaAi": True}))
    phone.goto(phone.url.split("#")[0] + "#/r/REEL9")
    watch_toasts(phone)
    phone.get_by_role("button", name="Paste an answer").click()
    phone.locator("#ans").fill(answer_for("REEL9"))
    phone.get_by_role("button", name="Save", exact=True).click()
    phone.wait_for_function("() => window.__toasts.length > 0")
    assert toasts(phone) == ["Saved"] and by_code(phone)["REEL9"]["notes_by"] == "meta"


def test_add_paste_keeps_the_answer_aside(phone):
    start(phone, [edited("REEL1")])
    phone.goto(phone.url.split("#")[0] + "#/add")
    watch_toasts(phone)
    phone.locator("#paste").fill(answer_for("REEL1"))
    phone.locator("#add").click()
    phone.wait_for_function("() => window.__toasts.length > 0")
    assert toasts(phone) == [KEPT]
    check_kept(phone, before=edited("REEL1"))


def test_filing_an_inbox_answer_under_an_edited_reel_keeps_it_aside_and_moves_on(phone):
    text = answer_for("REEL1").split("\n\n", 1)[1]  # no link: it waits in the inbox
    start(phone, [edited("REEL1")], inbox=[{"text": text, "at": 1}])
    phone.goto(phone.url.split("#")[0] + "#/file")
    watch_toasts(phone)
    phone.locator('[data-pick="REEL1"]').click()
    phone.wait_for_function("() => window.__toasts.length > 0")
    assert toasts(phone) == [KEPT]
    assert db_of(phone)["inbox"] == []  # the inbox moved on: the answer is in notes_next
    check_kept(phone, before=edited("REEL1"))


def test_the_nightly_run_files_a_shared_answer_for_an_edited_reel_aside(phone):
    start(phone, [edited("REEL1")])
    watch_toasts(phone)
    phone.evaluate("a => { window.__rn.shared.push(a); }", answer_for("REEL1"))
    phone.evaluate("() => overnightRun(true)")
    phone.wait_for_function("() => window.__rn.nightDone >= 1")
    assert phone.rn()["shared"] == [] and KEPT in toasts(phone)
    assert check_kept(phone, before=edited("REEL1"))["notes"]["topic"] == "A newer topic from Meta AI"


def test_a_phone_ai_answer_that_arrives_after_you_edited_is_kept_aside_and_not_counted(phone):
    start(phone, [reel("REEL1", notes=notes(), notes_by="auto", status="new"), reel("REEL2", notes=None, status="new", added_at=900)], model=READY, answers=[ANSWER, ANSWER])
    phone.evaluate("""() => { const g = RN.generate; let first = true;
      RN.generate = (id, p, o) => { if (first) { first = false; Notes.applyEdit(reel('REEL1'), 'topic', 'Typed while it wrote', Date.now()); } g(id, p, o); }; }""")  # you edit during the first answer
    phone.evaluate("() => startRun(['REEL1', 'REEL2'])")
    assert len(generate_calls(phone)) == 2
    assert phone.evaluate("() => [run.done, run.log.map((l) => l.text)]") == [1, [AI_TOPIC, KEPT]]  # only REEL2 counted; the newest line first
    r = by_code(phone)
    assert r["REEL1"]["notes_by"] == "you" and r["REEL1"]["notes"]["topic"] == "Typed while it wrote" and r["REEL1"]["status"] == "done" and "tries" not in r["REEL1"]
    slot = r["REEL1"]["notes_next"]["phone"]
    assert slot["notes"]["topic"] == AI_TOPIC and slot["raw"] == ANSWER and "meta" not in r["REEL1"]["notes_next"]
    assert r["REEL2"]["notes_by"] == "phone" and r["REEL2"]["notes"]["topic"] == AI_TOPIC and "notes_next" not in r["REEL2"]


def test_one_kept_answer_per_source_and_a_forced_write_goes_through(phone):
    start(phone, [edited("REEL1")])
    got = phone.evaluate("""() => { const r = reel('REEL1'), n = (t) => ({ topic: t, points: ['p'], tags: [] });
      const res = [setNotes(r, n('meta one'), 'meta', 'raw meta one'), setNotes(r, n('phone one'), 'phone', 'raw phone one'), setNotes(r, n('meta two'), 'meta', 'raw meta two')];
      return [res, JSON.parse(JSON.stringify(r.notes_next))]; }""")
    assert got[0] == [False, False, False]
    next_ = got[1]
    assert next_["meta"]["notes"]["topic"] == "meta two" and next_["meta"]["raw"] == "raw meta two"  # a newer Meta answer replaces the older Meta one
    assert next_["phone"]["notes"]["topic"] == "phone one"  # and only that one: the phone answer waits untouched
    assert phone.evaluate("() => reel('REEL1').notes.topic") == "My own topic" and phone.evaluate("() => reel('REEL1').raw") == "raw text of the AI answer"
    forced = phone.evaluate("() => [setNotes(reel('REEL1'), { topic: 'forced' }, 'meta', 'raw forced', true), reel('REEL1').notes_by, reel('REEL1').notes.topic]")
    assert forced == [True, "meta", "forced"] and phone.evaluate("() => Object.keys(reel('REEL1').notes_next).sort()") == ["meta", "phone"]


def test_a_meta_answer_for_a_reel_that_is_not_edited_is_applied_and_replaces_an_older_kept_meta_answer(phone):
    r = reel("REEL1", notes=notes(), notes_by="meta", notes_next={"meta": {"at": 1, "notes": {"topic": "older"}, "raw": "r"}, "you": {"at": 2, "notes": {"topic": "mine"}, "raw": "y"},
                                                            "phone": {"at": 3, "notes": {"topic": "ph"}, "raw": "p"}})
    start(phone, [r])
    assert phone.evaluate("() => setNotes(reel('REEL1'), { topic: 'direct', points: ['p'], tags: [] }, 'meta', 'raw direct')") is True
    got = phone.evaluate("() => reel('REEL1')")
    assert got["notes"]["topic"] == "direct" and got["notes_by"] == "meta" and got["raw"] == "raw direct"
    assert sorted(got["notes_next"]) == ["phone", "you"]  # the older Meta slot is gone; the others are untouched


# ---------------------------------------------------------------- 4. the video merge and the deletes

VIDEO = {"code": "V1", "url": "", "file": "K1", "author": "", "status": "new", "added_at": 6, "collections": []}
USER_DATA = {
    "edited": dict(notes=notes(topic="Mine"), notes_by="you", notes_edit={"was_by": "meta", "at": 1, "fields": ["topic"], "ai": {"topic": "Passwords in apps"}}),
    "only a kept version of yours": dict(notes=notes(), notes_by="meta", notes_next={"you": {"at": 1, "notes": notes(topic="Mine"), "edit": {"was_by": "meta", "at": 1, "fields": ["topic"], "ai": {}}, "raw": "r"}}),
    "only a waiting AI answer": dict(notes=notes(), notes_by="auto", notes_next={"meta": {"at": 1, "notes": notes(topic="Waiting"), "raw": "r"}}),
    "only a stale notes_edit": dict(notes=notes(), notes_by="meta", notes_edit={"was_by": "meta", "at": 1, "fields": ["topic"], "ai": {"topic": "Passwords in apps"}}),
}


def old_reel(**more):
    return reel("OLD1", author="chef.ana", added_at=5, **more)


def read_video(pg):
    pg.evaluate("""() => { RN.readLocalVideo = (id) => setTimeout(() => rnDone(id, true, JSON.stringify({ screen: "@chef.ana\\nCrispy rice in 10 minutes\\nUse day-old rice", seconds: 48 })), 5); }""")
    pg.evaluate("() => startRun(['V1'])")


@pytest.mark.parametrize("kind", USER_DATA)
def test_a_video_never_takes_over_and_removes_a_reel_with_your_data(phone, kind):
    old = old_reel(**USER_DATA[kind])
    start(phone, [dict(VIDEO), copy.deepcopy(old)])
    read_video(phone)
    reels = by_code(phone)
    assert reels["OLD1"] == old  # both stay, the saved reel exactly as it was
    assert "ig_code" not in reels["V1"] and reels["V1"]["url"] == ""


def test_a_video_still_takes_over_a_saved_reel_with_nothing_of_yours(phone):
    start(phone, [dict(VIDEO), old_reel(notes=notes(), notes_by="meta")])
    read_video(phone)
    reels = by_code(phone)
    assert "OLD1" not in reels and reels["V1"]["ig_code"] == "OLD1"  # the existing behavior is unchanged


def confirm_text(pg, answer=False):
    pg.evaluate("a => { window.__confirms = []; window.confirm = (m) => { window.__confirms.push(m); return a; }; }", answer)


@pytest.mark.parametrize("kind", USER_DATA)
def test_remove_from_shelf_names_your_edits_and_the_kept_versions(phone, kind):
    start(phone, [old_reel(**USER_DATA[kind])])
    phone.goto(phone.url.split("#")[0] + "#/r/OLD1")
    confirm_text(phone)
    phone.locator("#del").click()
    assert phone.evaluate("() => window.__confirms") == ["Remove this reel, its notes, your edits and the versions kept aside from Reel Shelf?"]
    assert "OLD1" in by_code(phone)  # No: nothing is removed


def test_remove_from_shelf_keeps_its_old_words_for_a_reel_with_nothing_of_yours_and_removes_it_on_yes(phone):
    start(phone, [old_reel(notes=notes(), notes_by="meta")])
    phone.goto(phone.url.split("#")[0] + "#/r/OLD1")
    confirm_text(phone, True)
    phone.locator("#del").click()
    assert phone.evaluate("() => window.__confirms") == ["Remove this reel and its notes from Reel Shelf?"]
    phone.wait_for_function("() => reel('OLD1') === undefined")


@pytest.mark.parametrize("data,words", [(None, ""), ("edited", ", including your own edits"), ("only a waiting AI answer", ", including your own edits")])
def test_delete_all_adds_your_own_edits_when_any_reel_has_your_data(phone, data, words):
    reels = [reel("REEL1", notes=notes(), notes_by="meta"), reel("REEL2", **(USER_DATA[data] if data else {}))]
    start(phone, reels, settings="{}")
    phone.goto(phone.url.split("#")[0] + "#/settings")
    confirm_text(phone)
    phone.locator("#wipe").click()
    assert phone.evaluate("() => window.__confirms") == ["Delete all 2 reels and their notes%s? This cannot be undone." % words]
    assert sorted(by_code(phone)) == ["REEL1", "REEL2"]


# ---------------------------------------------------------------- 5. reverting

def four_edits(pg, code="REEL1"):
    return pg.evaluate("""c => { const r = reel(c), t = 10;
      return [Notes.applyEdit(r, 'topic', 'T2', t), Notes.applyEdit(r, 'points', 'one\\ntwo\\nthree', t), Notes.applyEdit(r, 'takeaway', 'K2', t), Notes.applyEdit(r, 'tags', 'x, y', t)]; }""", code)


@pytest.mark.parametrize("was_by", ["phone", "meta", "auto"])
def test_reverting_each_field_brings_the_ai_text_back_and_the_last_one_gives_the_notes_back(phone, was_by):
    original = notes()
    start(phone, [reel("REEL1", notes=notes(), notes_by=was_by)])
    assert four_edits(phone) == [True] * 4
    r = phone.evaluate("() => reel('REEL1')")
    assert r["notes_edit"]["fields"] == ["topic", "points", "takeaway", "tags"] and sorted(r["notes_edit"]["ai"]) == ["points", "tags", "takeaway", "topic"]
    for i, f in enumerate(["takeaway", "topic", "tags", "points"]):  # any order
        assert phone.evaluate("f => Notes.revertField(reel('REEL1'), f)", f) is True
        r = phone.evaluate("() => reel('REEL1')")
        assert r["notes"][f] == original[f] and f not in r.get("notes_edit", {"fields": [], "ai": {}})["fields"]
        if i < 3:
            assert r["notes_by"] == "you" and f not in r["notes_edit"]["ai"]
        assert phone.evaluate("f => Notes.revertField(reel('REEL1'), f)", f) is False  # already reverted
    assert r["notes_by"] == was_by and "notes_edit" not in r and r["notes"] == original  # the last field gave the notes back
    assert phone.evaluate("() => Notes.isEdited(reel('REEL1'))") is False


def test_reverting_does_nothing_for_a_stale_notes_edit_and_the_next_edit_replaces_it(phone):
    stale = {"was_by": "meta", "at": 1, "fields": ["topic"], "ai": {"topic": "old ai"}}
    start(phone, [reel("REEL1", notes=notes(), notes_by="meta", notes_edit=copy.deepcopy(stale))])
    assert phone.evaluate("() => [Notes.isEdited(reel('REEL1')), Notes.hasUserData(reel('REEL1')), Notes.revertField(reel('REEL1'), 'topic')]") == [False, True, False]
    assert phone.evaluate("() => reel('REEL1')")["notes_edit"] == stale and phone.evaluate("() => reel('REEL1').notes.topic") == "Passwords in apps"
    assert phone.evaluate("() => Notes.applyEdit(reel('REEL1'), 'takeaway', 'New', 5)") is True
    assert phone.evaluate("() => reel('REEL1').notes_edit") == {"was_by": "meta", "at": 5, "fields": ["takeaway"], "ai": {"takeaway": "Keep secrets on the server."}}


def test_hasuserdata_is_true_for_every_form_of_your_data_and_false_for_none(phone):
    start(phone, [reel("REEL1", notes=notes(), notes_by="meta")])
    got = phone.evaluate("""d => d.map((x) => Notes.hasUserData({ notes: {}, notes_by: 'meta', ...x }))""",
                         [{}, {"notes_by": "you"}, {"notes_edit": {"fields": []}}, {"notes_next": {"you": {"at": 1}}}, {"notes_next": {"meta": {"at": 1}}}, {"notes_next": {"phone": None}}, {"notes_next": {}}])
    assert got == [False, True, True, True, True, False, False]


# ---------------------------------------------------------------- 7. the limits

LONG = 2000


def clean(pg, cases):
    return pg.evaluate("cs => cs.map(([f, v, old, other]) => Notes.cleanField(f, v, old, other))", cases)


def test_topic_and_takeaway_limits_and_messages(phone):
    phone.open_with()
    got = clean(phone, [["topic", "t" * 200, "x"], ["topic", "t" * 201, "x"], ["topic", "  a   b  ", "x"], ["topic", " x ", "x"],
                        ["takeaway", "k" * 1000, ""], ["takeaway", "k" * 1001, ""], ["takeaway", "k" * 1001, "k" * 1001], ["takeaway", "", "was"]])
    assert [(g["error"], g["changed"]) for g in got[:2]] == [("", True), ("The topic can be at most 200 letters.", True)]
    assert got[2]["value"] == "a b" and got[3] == {"value": "x", "error": "", "changed": False}
    assert [(g["error"], g["changed"]) for g in got[4:6]] == [("", True), ("The takeaway can be at most 1,000 letters.", True)]
    assert got[6]["changed"] is False and got[6]["error"] == "" and got[7] == {"value": "", "error": "", "changed": True}


def test_only_a_changed_field_is_checked_and_a_changed_one_may_be_as_long_as_what_is_stored(phone):
    phone.open_with()
    long_ai = "word " * 400  # 2,000 characters from the AI: more than the 1,000 a typed takeaway may have
    long_text = long_ai.strip()
    typo = long_text.replace("word", "wrod", 1)  # same length
    got = clean(phone, [["takeaway", long_ai, long_text], ["takeaway", typo, long_text], ["takeaway", long_text + "x", long_text], ["takeaway", "short", long_text]])
    assert got[0]["changed"] is False and got[0]["error"] == "" and got[0]["value"] == long_text  # untouched: kept as it is, past the limit
    assert got[1]["changed"] is True and got[1]["error"] == ""  # a typo fix in a 2,000-character AI takeaway is not blocked
    assert got[2]["error"] == "The takeaway can be at most 1,999 letters."  # but it may not grow past what is stored
    assert got[3]["error"] == ""


def test_points_limits_messages_and_the_stored_text_that_is_allowed(phone):
    phone.open_with()
    fifty = ["Point number %d of the AI list" % i for i in range(50)]
    seven = "q" * 700
    edited_one = fifty[:7] + ["Point number 7 fixed"] + fifty[8:]
    cases = [
        ["points", "\n".join("p%d" % i for i in range(40)), ["a"]],      # 0: 40 lines
        ["points", "\n".join("p%d" % i for i in range(41)), ["a"]],      # 1: 41 lines
        ["points", "x" * 500, ["a"]],                                    # 2: a 500 line
        ["points", "x" * 501, ["a"]],                                    # 3: 501
        ["points", "- a\n2. b\n\n  c  \n", []],                          # 4: bullets, blanks and spaces go
        ["points", fifty, fifty],                                        # 5: 50 AI points, untouched
        ["points", edited_one, fifty],                                   # 6: one of 50 AI points edited
        ["points", fifty + ["one more"], fifty],                         # 7: a 51st
        ["points", ["fix " + "q" * 695 + "!"], [seven]],                 # 8: a 700-character AI point, a typo fixed (still 700)
        ["points", ["q" * 701], [seven]],                                # 9: grown past what is stored
        ["points", ["a new one", seven, "B"], [seven, "B"]],             # 10: a line inserted: the stored 700 one is not checked against its new place
        ["points", "  First   point\nSecond", ["First point", "Second"]],  # 11: spaces only: not a change
        ["points", "Second\nFirst point", ["First point", "Second"]],    # 12: another order is a change
    ]
    got = clean(phone, cases)
    assert [g["error"] for g in got[:2]] == ["", "Keep at most 40 points, each under 500 letters."]
    assert [g["error"] for g in got[2:4]] == ["", "Keep at most 40 points, each under 500 letters."]
    assert got[4]["value"] == ["a", "b", "c"]
    assert got[5]["changed"] is False and got[5]["error"] == ""
    assert got[6]["changed"] is True and got[6]["error"] == "" and got[6]["value"] == edited_one
    assert got[7]["error"] == "Keep at most 50 points, each under 500 letters."
    assert len(cases[8][1][0]) == 700 and got[8]["error"] == "" and got[8]["changed"] is True
    assert got[9]["error"] == "Keep at most 40 points, each under 700 letters."
    assert got[10]["error"] == "" and got[10]["changed"] is True
    assert got[11]["changed"] is False and got[12]["changed"] is True and got[12]["error"] == ""


def test_tags_follow_the_rule_of_parse_and_are_limited_to_twelve(phone):
    phone.open_with()
    twelve = ["t%d" % i for i in range(12)]
    got = clean(phone, [["tags", "#A, b ,c_d, B, é-x!", []], ["tags", ["a", "B"], ["a", "b"]], ["tags", ", ".join(twelve), []], ["tags", ", ".join(twelve + ["more", "t0"]), []],
                        ["tags", "b, a", ["a", "b"]]])
    assert got[0]["value"] == ["a", "b", "c_d", "é-x"] and got[0]["error"] == ""
    assert phone.evaluate("t => Notes.parse(t).tags", "TOPIC: x\nPOINTS:\n- p\nTAGS: #A, b ,c_d, B, é-x!") == got[0]["value"]  # the same rule as the AI's
    assert got[1]["changed"] is False  # case alone is not a change
    assert got[2]["error"] == "" and got[2]["value"] == twelve
    assert got[3]["error"] == "Only the first 12 tags are kept." and got[3]["value"] == twelve  # the 13th is "more"; a repeated tag is not a tag
    assert got[4]["changed"] is True and got[4]["value"] == ["b", "a"]
    stored13 = phone.evaluate("() => Notes.cleanField('tags', Array.from({ length: 14 }, (_, i) => 's' + i).join(','), Array.from({ length: 13 }, (_, i) => 's' + i))")
    assert stored13["error"] == "Only the first 13 tags are kept." and len(stored13["value"]) == 13  # 14 typed, 13 stored: the larger one is the limit


def test_a_topic_and_points_that_are_both_empty_are_refused(phone):
    phone.open_with()
    empty = "Write a topic or at least one point."
    got = clean(phone, [["topic", "", "T", []], ["topic", "  ", "T", ["p"]], ["topic", "", "T"], ["points", "", ["p"], ""], ["points", "\n \n", ["p"], "T"], ["points", "", ["p"]]])
    assert [g["error"] for g in got] == [empty, "", "", empty, "", ""]  # "other" is what the other field will hold; without it nothing is judged
    assert phone.evaluate("() => { const r = { notes: { topic: 'T', points: [] }, notes_by: 'meta' }; return [Notes.applyEdit(r, 'topic', '', 1), r.notes_by]; }") == [False, "meta"]


# ---------------------------------------------------------------- 9. old libraries keep the new keys

def test_the_new_keys_survive_load_and_save_and_the_page_reads_them_back(phone):
    d = json.loads(texts(NEWEST)[0])
    mine = {"was_by": "phone", "at": 1767312000000, "fields": ["topic", "takeaway"], "ai": {"topic": "AI topic", "takeaway": "AI takeaway"}, "futureKey": [1, {"a": None}]}
    slots = {"meta": {"at": 1767312000001, "notes": {"topic": "Meta topic", "points": ["p"], "tags": [], "futureNote": 1}, "raw": "meta raw", "futureSlot": True},
             "you": {"at": 1767312000002, "notes": {"topic": "Mine"}, "edit": copy.deepcopy(mine), "raw": "old raw"}}
    codes = [r["code"] for r in d["reels"]]
    d["reels"][0].update({"notes_by": "you", "notes_edit": copy.deepcopy(mine), "notes_next": copy.deepcopy(slots)})
    d["reels"][1].update({"notes_next": {"phone": {"at": 5, "notes": {"topic": "T"}, "raw": ""}}})
    d["reels"][2].update({"notes_edit": copy.deepcopy(mine)})  # stale: notes_by is not "you"
    d["reels"][2]["notes_by"] = "meta"
    open_fixture(phone, reels=json.dumps(d), shots=texts(NEWEST)[1])
    assert phone.evaluate("() => saveDb()") is True
    after = json.loads(phone.rn()["db"])
    assert [r["code"] for r in after["reels"]] == codes
    check_diff(diff(d, after), expected(NEWEST), "a library with notes_edit and notes_next")
    assert phone.evaluate("c => c.map((x) => [Notes.isEdited(reel(x)), Notes.hasUserData(reel(x))])", codes[:4]) == [[True, True], [False, True], [False, True], [False, False]]
    assert phone.evaluate("() => saveDb()") is True and json.loads(phone.rn()["db"]) == after  # a second save changes nothing more


# ---------------------------------------------------------------- the two "NEEDS VERIFICATION" items of the design

def finished(pg):
    pg.wait_for_function("() => run && run.finished")


@pytest.mark.parametrize("by", ["meta", "phone", "you"])
def test_redo_with_phone_ai_writes_nothing_for_a_reel_with_meta_phone_or_your_notes(phone, by):
    """Verified in the harness (design, NEEDS VERIFICATION 1): the button is shown, the run ends, the model is never called, the notes stay."""
    extra = dict(notes_edit={"was_by": "phone", "at": 1, "fields": ["topic"], "ai": {"topic": "Passwords in apps"}}) if by == "you" else {}
    r = reel("REEL1", notes=notes(), notes_by=by, notes_at=5, raw="old raw", **extra)
    start(phone, [copy.deepcopy(r)], model=READY, answers=[ANSWER])
    phone.goto(phone.url.split("#")[0] + "#/r/REEL1")
    phone.get_by_role("button", name="Redo with phone AI").click()
    finished(phone)
    assert generate_calls(phone) == [] and phone.evaluate("() => run.done") == 0
    assert by_code(phone)["REEL1"] == {**r, "error": ""}  # the run only clears the (empty) error text of the reel it looked at; notes, status and raw are untouched


def test_redo_with_phone_ai_does_rewrite_quick_notes(phone):
    """The control for the test above: the same button on quick notes does call the model, so the harness really exercises that path."""
    start(phone, [reel("REEL1", notes=notes(), notes_by="auto")], model=READY, answers=[ANSWER])
    phone.goto(phone.url.split("#")[0] + "#/r/REEL1")
    phone.get_by_role("button", name="Redo with phone AI").click()
    finished(phone)
    assert len(generate_calls(phone)) == 1 and by_code(phone)["REEL1"]["notes_by"] == "phone" and by_code(phone)["REEL1"]["notes"]["topic"] == AI_TOPIC


def test_an_open_dialog_survives_a_stale_reload_and_the_save_that_triggers_it_closes_it(phone):
    """Verified in the harness for K1-2 (design, NEEDS VERIFICATION 2: the dialog after staleReload), on today's paste dialog:
    staleReload() re-renders the page but leaves an open <dialog> and what was typed in it alone; clicking Save closes the dialog
    for good even when the save is refused (form method="dialog"), so the edit dialog of K1-2 has to keep its draft itself."""
    start(phone, [reel("REEL1", notes=notes(), notes_by="auto")], settings=json.dumps({"metaAi": True}))
    phone.goto(phone.url.split("#")[0] + "#/r/REEL1")
    phone.get_by_role("button", name="Paste an answer").click()
    phone.locator("#ans").fill(answer_for("REEL1"))
    phone.evaluate("() => { window.__rn.rev = (window.__rn.rev || 0) + 1; staleReload(); }")  # another page saved: this page reloads
    assert phone.evaluate("() => [document.getElementById('dlg').open, document.querySelector('#dlg #ans')?.value.length > 0]") == [True, True]
    phone.evaluate("() => { window.__rn.rev = (window.__rn.rev || 0) + 1; }")  # stale again, then Save
    phone.get_by_role("button", name="Save", exact=True).click()
    assert phone.evaluate("() => [document.getElementById('dlg').open, staleSave]") == [False, True]
    assert by_code(phone)["REEL1"]["notes_by"] == "auto"  # the refused save wrote nothing
