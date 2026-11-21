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
    base = dict(notes=notes(topic="My own topic", takeaway="My own takeaway"), notes_by="you", notes_at=5, raw="raw text of the AI answer",
                notes_edit={"was_by": "phone", "at": 7, "fields": ["topic", "takeaway"], "ai": {"topic": "Passwords in apps", "takeaway": "Keep secrets on the server."}})
    base.update(more)
    return reel(code, **base)


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
              Notes.applyEdit(r, 'topic', 'x'.repeat(201), 1), Notes.applyEdit(r, 'intent', 'not editable', 1), Notes.applyEdit(r, 'takeaway', 'k'.repeat(1001), 1)]; }""")
    assert got == [False] * 5
    assert phone.evaluate("() => reel('REEL1')") == before  # still quick notes: Start may still rewrite them


def test_tags_or_a_takeaway_alone_do_not_make_notes_but_do_once_there_is_a_topic_or_a_point(phone):
    start(phone, [reel("REEL1", notes=None, status="ready"), reel("REEL2", notes=None, status="ready")])
    got = phone.evaluate("""() => { const a = reel('REEL1'), none = {};
      return [Notes.applyEdit(none, 'tags', 'a', 1), Notes.applyEdit(none, 'takeaway', 'only this', 1), JSON.stringify(none), Notes.applyEdit(a, 'tags', 'a', 1), a.notes, a.notes_by || '',
              Notes.applyEdit({ notes: { topic: ' ', points: [] }, notes_by: 'meta' }, 'tags', 'a', 1),
              Notes.applyEdit(a, 'topic', 'now a topic', 2), Notes.applyEdit(a, 'tags', 'a', 3), Notes.applyEdit(a, 'takeaway', 'k', 3), Notes.noBody('', []), Notes.noBody('t', []), Notes.noBody('', ['p'])]; }""")
    assert got[:2] == [False, False] and got[2] == "{}"  # the empty reel is left exactly as it was
    assert got[3] is False and got[4] is None and got[5] == ""
    assert got[6] is False  # notes with a blank topic and no points are not made better by tags
    assert got[7:10] == [True, True, True] and got[10:] == [True, False, False]
    r = phone.evaluate("() => reel('REEL1')")
    assert r["notes"]["topic"] == "now a topic" and r["notes"]["tags"] == ["a"] and r["notes"]["takeaway"] == "k"


def test_a_reel_marked_yours_with_no_or_damaged_notes_edit_can_still_be_edited(phone):
    start(phone, [reel("REEL1", notes=notes(), notes_by="you"), reel("REEL2", notes=notes(), notes_by="you", notes_edit={}),
                  reel("REEL3", notes=notes(), notes_by="you", notes_edit={"was_by": "meta", "fields": "topic", "ai": None})])
    got = phone.evaluate("() => ['REEL1', 'REEL2', 'REEL3'].map((c) => [Notes.applyEdit(reel(c), 'topic', 'Edited ' + c, 9), reel(c).notes_edit])")
    for code, (ok, edit) in zip(["REEL1", "REEL2", "REEL3"], got):
        assert ok is True, code
        assert edit == {"was_by": "", "at": 9, "fields": ["topic"], "ai": {}}, code  # a new, empty record: nothing was kept of the AI text, and nothing is claimed
    assert phone.evaluate("() => reel('REEL1').notes.topic") == "Edited REEL1" and phone.evaluate("() => Notes.revertField(reel('REEL1'), 'topic')") is False
    assert phone.evaluate("() => Notes.revertField({ notes_by: 'you', notes: {}, notes_edit: {} }, 'topic')") is False  # and reverting one does not throw


def test_more_than_twelve_typed_tags_keep_the_first_twelve(phone):
    start(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    assert phone.evaluate("() => Notes.applyEdit(reel('REEL1'), 'tags', Array.from({ length: 14 }, (_, i) => 't' + i).join(', '), 4)") is True
    assert phone.evaluate("() => reel('REEL1').notes.tags") == ["t%d" % i for i in range(12)]


def test_putting_a_field_back_uses_the_time_it_is_given(phone):
    start(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    assert phone.evaluate("() => [Notes.applyEdit(reel('REEL1'), 'topic', 'Mine', 5), Notes.revertField(reel('REEL1'), 'topic', 77), reel('REEL1').notes_at]") == [True, True, 77]


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
    phone.wait_for_function("() => document.getElementById('toast').textContent.includes('kept aside')")
    assert phone.evaluate("() => document.getElementById('toast').textContent") == "1 Meta AI answer filed. 2 answers kept aside: those reels have your edits. Open them to compare."
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


def test_an_answer_with_no_link_goes_to_the_reel_you_last_asked_about_even_when_you_edited_it_and_is_kept_aside(phone):
    text = answer_for("REEL1").split("\n\n", 1)[1]  # no link in it: the reel asked about last gets it
    start(phone, [edited("REEL1", asked_at=FIXTURES_NOW - 1000), reel("REEL2", notes=notes(), notes_by="auto", asked_at=FIXTURES_NOW - 5 * 86400e3)], shared=[text])
    phone.wait_for_function("() => window.__rn.shared.length === 0")
    assert phone.evaluate("() => document.getElementById('toast').textContent") == KEPT
    check_kept(phone, before=edited("REEL1", asked_at=FIXTURES_NOW - 1000))
    assert by_code(phone)["REEL2"]["notes_by"] == "auto" and db_of(phone)["inbox"] == []


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


@pytest.mark.parametrize("data,words", [
    ((), ""), (("edited",), ", including your own edits"), (("only a stale notes_edit",), ", including your own edits"),
    (("only a waiting AI answer",), ", including the versions kept aside"), (("only a kept version of yours",), ", including the versions kept aside"),
    (("edited", "only a waiting AI answer"), ", including your own edits and the versions kept aside")])
def test_delete_all_says_which_of_your_data_it_deletes(phone, data, words):
    reels = [reel("REEL1", notes=notes(), notes_by="meta")] + [reel("REEL%d" % (i + 2), **USER_DATA[d]) for i, d in enumerate(data)]
    start(phone, reels, settings="{}")
    phone.goto(phone.url.split("#")[0] + "#/settings")
    confirm_text(phone)
    phone.locator("#wipe").click()
    assert phone.evaluate("() => window.__confirms") == ["Delete all %d reels and their notes%s? This cannot be undone." % (len(reels), words)]
    assert len(by_code(phone)) == len(reels)


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
    assert got[2]["value"] == "a b" and got[3] == {"value": "x", "error": "", "changed": False, "note": ""}
    assert [(g["error"], g["changed"]) for g in got[4:6]] == [("", True), ("The takeaway can be at most 1,000 letters.", True)]
    assert got[6]["changed"] is False and got[6]["error"] == "" and got[7] == {"value": "", "error": "", "changed": True, "note": ""}


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
    assert [g["error"] for g in got[:2]] == ["", "Keep at most 40 points, each at most 500 letters."]
    assert [g["error"] for g in got[2:4]] == ["", "Keep at most 40 points, each at most 500 letters."]
    assert got[4]["value"] == ["a", "b", "c"]
    assert got[5]["changed"] is False and got[5]["error"] == ""
    assert got[6]["changed"] is True and got[6]["error"] == "" and got[6]["value"] == edited_one
    assert got[7]["error"] == "Keep at most 50 points, each at most 500 letters."
    assert len(cases[8][1][0]) == 700 and got[8]["error"] == "" and got[8]["changed"] is True
    assert got[9]["error"] == "Keep at most 40 points, each at most 700 letters."
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
    assert got[3]["error"] == "" and got[3]["note"] == "Only the first 12 tags are kept." and got[3]["value"] == twelve and got[3]["changed"] is True  # kept, and said
    assert got[4]["changed"] is True and got[4]["value"] == ["b", "a"]
    stored13 = phone.evaluate("() => Notes.cleanField('tags', Array.from({ length: 14 }, (_, i) => 's' + i).join(','), Array.from({ length: 13 }, (_, i) => 's' + i))")
    assert stored13["note"] == "Only the first 13 tags are kept." and len(stored13["value"]) == 13  # 14 typed, 13 stored: the larger one is the limit
    same12 = phone.evaluate("t => Notes.cleanField('tags', t.concat(['extra']).join(','), t)", twelve)
    assert same12["changed"] is False and same12["value"] == twelve and same12["note"]  # the first 12 are what is stored: nothing to change, still said


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


@pytest.mark.parametrize("by", ["meta", "phone"])
def test_redo_with_phone_ai_writes_nothing_for_a_reel_with_meta_or_phone_notes(phone, by):
    """Verified in the harness (design, NEEDS VERIFICATION 1): the button is shown, the run ends, the model is never called, the notes stay.
    (Since K1-3 the same button on a reel you EDITED does call the model and keeps the answer aside: see the Redo tests at the end.)"""
    r = reel("REEL1", notes=notes(), notes_by=by, notes_at=5, raw="old raw")
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


# ================================================================ K1-2: the editor on the reel page

def open_reel(pg, reels, code="REEL1", **extra):
    start(pg, reels, **extra)
    pg.goto(pg.url.split("#")[0] + "#/" + "r/" + code)
    watch_toasts(pg)


def edit_button(pg):
    return pg.get_by_role("button", name="Edit notes", exact=True)


def open_editor(pg):
    edit_button(pg).click()
    pg.locator("#ed-topic").wait_for()


def dialog_open(pg):
    return pg.evaluate("() => document.getElementById('dlg').open")


def typed(pg, **fields):
    for f, v in fields.items():
        pg.locator("#ed-" + f).fill(v)


def save(pg):
    pg.locator("#edSave").click()


def err(pg, f):
    return pg.locator("#ed-%s-err" % f).inner_text()


def stored(pg, code="REEL1"):
    return by_code(pg)[code]


def screen_text(pg):
    return pg.locator("#app").inner_text()


def test_the_reel_page_offers_edit_notes_or_write_my_own_notes(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone"), reel("REEL2")])
    assert edit_button(phone).is_visible() and phone.get_by_role("button", name="Copy notes").is_visible()
    assert phone.get_by_role("button", name="Write my own notes").count() == 0
    phone.goto(phone.url.split("#")[0] + "#/r/REEL2")
    assert phone.get_by_role("button", name="Write my own notes").is_visible() and edit_button(phone).count() == 0


def test_the_editor_opens_with_the_notes_and_cancel_changes_nothing(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    before = phone.rn()["db"]
    open_editor(phone)
    assert phone.locator("#ed-topic").input_value() == "Passwords in apps"
    assert phone.locator("#ed-points").input_value() == "First point about passwords\nSecond point about keys"
    assert phone.locator("#ed-takeaway").input_value() == "Keep secrets on the server."
    assert phone.locator("#ed-tags").input_value() == "security, apps"
    typed(phone, topic="Typed but not saved", tags="x")
    phone.locator("#edCancel").click()
    assert not dialog_open(phone) and phone.rn()["db"] == before  # nothing was written
    assert "Passwords in apps" in screen_text(phone) and "Typed but not saved" not in screen_text(phone)
    open_editor(phone)
    assert phone.locator("#ed-topic").input_value() == "Passwords in apps"  # the next editor starts from the notes, not from what was typed
    phone.keyboard.press("Escape")
    assert not dialog_open(phone) and phone.rn()["db"] == before


def test_saving_an_edit_marks_each_edited_section_and_says_whose_notes_they_are(phone):
    quick = reel("REEL1", notes=notes(unbacked=1), notes_by="phone", status="failed", error="boom", tries=1, next_try_at=5, last_fail="x", last_fail_at=4)
    open_reel(phone, [quick])
    assert "Notes by the on-phone AI (from the caption)" in screen_text(phone) and "Edited by you" not in screen_text(phone)
    open_editor(phone)
    typed(phone, topic="  My   topic ", points="one\n2. two\n\nthree", tags="#Mine, own")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert toasts(phone) == ["Saved"]
    r = stored(phone)
    assert r["notes_by"] == "you" and r["notes"]["topic"] == "My topic" and r["notes"]["points"] == ["one", "two", "three"] and r["notes"]["tags"] == ["mine", "own"]
    assert r["notes"]["takeaway"] == "Keep secrets on the server." and "unbacked" not in r["notes"]
    assert r["notes_edit"] == {"was_by": "phone", "at": FIXTURES_NOW, "fields": ["topic", "points", "tags"],
                               "ai": {"topic": "Passwords in apps", "points": notes()["points"], "tags": ["security", "apps"]}}
    assert r["status"] == "done" and "tries" not in r and r["notes_at"] == FIXTURES_NOW
    text = screen_text(phone)
    assert "Your notes (edited from Notes by the on-phone AI)" in text and text.count("Edited by you") == 3  # topic, points and tags, not the takeaway
    for label, edited_ in [("Topic", True), ("Points", True), ("Takeaway", False), ("Tags", True)]:
        block = phone.locator(".note-block", has=phone.locator(".label", has_text=label)).first
        assert ("Edited by you" in block.inner_text()) is edited_, label


def test_editing_failed_quick_notes_takes_away_the_retry_line_and_button(phone):
    quick = reel("REEL1", notes=notes(), notes_by="auto", status="failed", error="boom", tries=1, next_try_at=FIXTURES_NOW + 1, last_fail="The AI model failed", last_fail_at=FIXTURES_NOW)
    open_reel(phone, [quick])
    assert phone.get_by_role("button", name="Try again now").is_visible() and "Tried 1 time" in screen_text(phone)
    open_editor(phone)
    typed(phone, topic="Mine now")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert phone.get_by_role("button", name="Try again now").count() == 0 and "Tried 1 time" not in screen_text(phone)
    assert "Your notes (edited from Quick notes without AI)" in screen_text(phone)


def test_write_my_own_notes_for_a_reel_with_none(phone):
    open_reel(phone, [reel("REEL1", status="ready", notes=None)])
    phone.get_by_role("button", name="Write my own notes").click()
    phone.locator("#ed-topic").wait_for()
    assert phone.locator("[data-ai]").count() == 0 and phone.locator("h2", has_text="Write your own notes").is_visible()
    typed(phone, topic="Mine alone", points="a\nb")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes_by"] == "you" and r["notes"]["topic"] == "Mine alone" and r["notes"]["points"] == ["a", "b"] and r["status"] == "done"
    assert r["notes_edit"]["was_by"] == "" and r["notes_edit"]["ai"] == {} and r["notes_edit"]["fields"] == ["topic", "points"]
    text = screen_text(phone)
    assert "Your notes" in text and "edited from" not in text and phone.get_by_role("button", name="Edit notes", exact=True).is_visible()
    open_editor(phone)
    assert phone.locator("[data-ai]").count() == 0 and phone.locator("h2", has_text="Edit notes").is_visible()  # nothing of the AI to go back to


def test_a_cancelled_editor_leaves_nothing_behind_for_the_next_one(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="t" * 201)  # refused: the draft is kept in case of a reload
    save(phone)
    assert dialog_open(phone) and phone.evaluate("() => editDraft.fields.topic.length") == 201
    phone.locator("#edCancel").click()
    open_editor(phone)
    assert phone.locator("#ed-topic").input_value() == "Passwords in apps" and phone.evaluate("() => editDraft") is None


def test_saving_with_nothing_changed_writes_nothing(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="auto")])
    before = phone.rn()["db"]
    open_editor(phone)
    typed(phone, topic="  Passwords   in apps ")  # only spaces
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert phone.rn()["db"] == before and toasts(phone) == [] and stored(phone)["notes_by"] == "auto"  # still quick notes: Start may rewrite them


def test_enter_in_a_box_saves_and_does_not_cancel(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    phone.locator("#ed-topic").fill("Saved with the Enter key")
    phone.locator("#ed-topic").press("Enter")
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert stored(phone)["notes"]["topic"] == "Saved with the Enter key"


def test_typed_text_is_text_not_html_in_the_editor_and_on_the_page(phone):
    evil = '<img src=x onerror="window.__pwned=1"> </textarea><b>x</b> "q"'
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic=evil, points=evil + "\nsecond")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert phone.locator("#app img").count() == 0 and phone.evaluate("() => window.__pwned") is None
    open_editor(phone)
    assert phone.locator("#ed-topic").input_value() == " ".join(evil.split()) and phone.locator("#ed-points").input_value().split("\n")[1] == "second"
    assert phone.locator("#dlg img").count() == 0 and phone.evaluate("() => window.__pwned") is None


# ---------------------------------------------------------------- "Use the AI text" (revert) through the screen

def four_edited(code="REEL1", was_by="phone"):
    r = reel(code, notes=notes(), notes_by=was_by)
    return r


def edit_all(pg):
    open_editor(pg)
    typed(pg, topic="T2", points="one\ntwo", takeaway="K2", tags="x, y")
    save(pg)
    pg.wait_for_function("() => !document.getElementById('dlg').open")


def test_use_the_ai_text_changes_only_the_form_and_save_puts_it_back(phone):
    open_reel(phone, [four_edited()])
    edit_all(phone)
    assert stored(phone)["notes_edit"]["fields"] == ["topic", "points", "takeaway", "tags"]
    open_editor(phone)
    assert phone.locator("[data-ai]").count() == 4
    phone.locator('[data-ai="topic"]').click()
    assert phone.locator("#ed-topic").input_value() == "Passwords in apps" and stored(phone)["notes"]["topic"] == "T2"  # only the form changed
    before = phone.rn()["db"]
    phone.locator("#edCancel").click()
    assert phone.rn()["db"] == before and stored(phone)["notes"]["topic"] == "T2"  # Cancel leaves your text, with no question
    open_editor(phone)
    assert phone.locator("#ed-topic").input_value() == "T2"
    phone.locator('[data-ai="topic"]').click()
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["topic"] == "Passwords in apps" and r["notes_by"] == "you" and r["notes_edit"]["fields"] == ["points", "takeaway", "tags"]
    assert "topic" not in r["notes_edit"]["ai"] and screen_text(phone).count("Edited by you") == 3


def test_putting_back_every_field_gives_the_notes_back_to_whoever_wrote_them(phone):
    for was_by in ("phone", "meta", "auto"):
        open_reel(phone, [four_edited(was_by=was_by)])
        edit_all(phone)
        open_editor(phone)
        for f in ("topic", "points", "takeaway", "tags"):
            phone.locator('[data-ai="%s"]' % f).click()
        save(phone)
        phone.wait_for_function("() => !document.getElementById('dlg').open")
        r = stored(phone)
        assert r["notes_by"] == was_by and "notes_edit" not in r and r["notes"] == notes(), was_by  # as before the first edit
        assert "Edited by you" not in screen_text(phone) and edit_button(phone).is_visible()


def test_use_the_ai_text_is_only_offered_for_an_edited_field_and_typing_afterwards_wins(phone):
    open_reel(phone, [four_edited()])
    open_editor(phone)
    assert phone.locator("[data-ai]").count() == 0  # nothing edited yet
    typed(phone, topic="T2")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    open_editor(phone)
    assert phone.locator("[data-ai]").count() == 1 and phone.locator('[data-ai="topic"]').is_visible()
    phone.locator('[data-ai="topic"]').click()
    phone.locator("#ed-topic").fill("Typed after the AI text")  # changed his mind: the typed text is saved, not the AI's
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["topic"] == "Typed after the AI text" and r["notes_edit"]["fields"] == ["topic"] and r["notes_edit"]["ai"] == {"topic": "Passwords in apps"}


def test_no_use_the_ai_text_when_a_stale_notes_edit_is_all_that_is_left(phone):
    stale = {"was_by": "meta", "at": 1, "fields": ["topic"], "ai": {"topic": "old ai"}}
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="meta", notes_edit=stale)])
    open_editor(phone)
    assert phone.locator("[data-ai]").count() == 0


# ---------------------------------------------------------------- the limits through the screen

def test_a_topic_over_200_letters_is_refused_with_a_message_and_nothing_is_stored(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    before = phone.rn()["db"]
    open_editor(phone)
    typed(phone, topic="t" * 201)
    save(phone)
    assert dialog_open(phone) and err(phone, "topic") == "The topic can be at most 200 letters."
    assert phone.locator("#ed-topic").get_attribute("aria-invalid") == "true" and phone.evaluate("() => document.activeElement.id") == "ed-topic"
    assert phone.rn()["db"] == before and phone.locator("#ed-topic").input_value() == "t" * 201  # what was typed is still there
    typed(phone, topic="t" * 200)
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert stored(phone)["notes"]["topic"] == "t" * 200


def test_every_limit_has_its_message_under_its_own_box(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    before = phone.rn()["db"]
    open_editor(phone)
    typed(phone, topic="t" * 201, points="\n".join("p%d" % i for i in range(41)), takeaway="k" * 1001, tags=", ".join("t%d" % i for i in range(13)))
    save(phone)
    assert [err(phone, f) for f in ("topic", "points", "takeaway", "tags")] == [
        "The topic can be at most 200 letters.", "Keep at most 40 points, each at most 500 letters.", "The takeaway can be at most 1,000 letters.", ""]  # too many tags is not an error
    assert phone.locator("#dlg [role=alert]").count() == 4 and phone.rn()["db"] == before and dialog_open(phone)
    typed(phone, topic="ok", points="a", takeaway="ok", tags="ok")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert stored(phone)["notes"]["topic"] == "ok"
    open_editor(phone)
    assert [phone.locator("#ed-%s-err" % f).inner_text() for f in ("topic", "points", "takeaway", "tags")] == [""] * 4  # a new editor starts clean


def test_more_than_twelve_tags_are_saved_as_the_first_twelve_and_the_editor_says_so(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, tags=", ".join("t%d" % i for i in range(14)))
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert stored(phone)["notes"]["tags"] == ["t%d" % i for i in range(12)]
    assert toasts(phone) == ["Saved. Only the first 12 tags are kept."]
    open_editor(phone)
    typed(phone, tags=", ".join("t%d" % i for i in range(14)))  # the same again: nothing to change, still said
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert toasts(phone)[-1] == "Only the first 12 tags are kept."


def test_tags_or_a_takeaway_alone_are_not_notes_in_the_editor_either(phone):
    open_reel(phone, [reel("REEL1", status="ready", notes=None)])
    before = phone.rn()["db"]
    phone.get_by_role("button", name="Write my own notes").click()
    phone.locator("#ed-topic").wait_for()
    typed(phone, takeaway="Only a takeaway", tags="a, b")
    save(phone)
    assert dialog_open(phone) and phone.rn()["db"] == before
    assert err(phone, "topic") == err(phone, "points") == "Write a topic or at least one point." and err(phone, "takeaway") == ""
    typed(phone, points="one point")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["points"] == ["one point"] and r["notes"]["takeaway"] == "Only a takeaway" and r["notes"]["tags"] == ["a", "b"] and r["notes_by"] == "you"


def test_a_topic_and_points_that_are_both_emptied_are_refused_but_one_of_them_may_be(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="", points="")
    save(phone)
    assert dialog_open(phone) and err(phone, "topic") == "Write a topic or at least one point." and err(phone, "points") == "Write a topic or at least one point."
    typed(phone, topic="", points="only a point")  # the topic emptied and a point written in the same Save
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert stored(phone)["notes"]["topic"] == "" and stored(phone)["notes"]["points"] == ["only a point"]
    open_editor(phone)
    typed(phone, topic="A topic again", points="")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert stored(phone)["notes"]["points"] == [] and stored(phone)["notes"]["topic"] == "A topic again"


def test_only_changed_fields_are_checked_through_the_screen(phone):
    long_ai = ("word " * 400).strip()  # a 2,000-character takeaway from the AI
    fifty = ["Point number %d of the AI list" % i for i in range(50)]
    seven = ("abcdef " * 100)[:-1] + "z"  # 700 characters, with spaces (a 700-letter word would make the page wider than the phone)
    open_reel(phone, [reel("REEL1", notes=notes(takeaway=long_ai, points=fifty + [seven]), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="A new topic")  # the 2,000-character takeaway and the 51 points are untouched
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["topic"] == "A new topic" and r["notes"]["takeaway"] == long_ai and len(r["notes"]["points"]) == 51 and r["notes_edit"]["fields"] == ["topic"]
    open_editor(phone)
    lines = phone.locator("#ed-points").input_value().split("\n")
    lines[7] = "Point number 7 fixed"  # one point of 51 AI points
    lines[50] = "fix" + seven[3:]  # a typo in a 700-character AI point (the same length)
    typed(phone, points="\n".join(lines), takeaway=long_ai.replace("word", "wrod", 1))  # and a typo in the 2,000-character takeaway
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["points"][7] == "Point number 7 fixed" and r["notes"]["points"][50] == "fix" + seven[3:] and len(r["notes"]["points"]) == 51
    assert r["notes"]["takeaway"].startswith("wrod") and sorted(r["notes_edit"]["fields"]) == ["points", "takeaway", "topic"]
    open_editor(phone)
    typed(phone, points="\n".join(lines + ["one point more"]))
    save(phone)
    assert dialog_open(phone) and err(phone, "points") == "Keep at most 51 points, each at most 700 letters."  # but it may not grow past what is stored


# ---------------------------------------------------------------- labels, hints, alerts and size

def test_every_box_has_a_label_a_hint_and_an_alert_and_the_buttons_are_big_enough(phone):
    open_reel(phone, [four_edited()])
    edit_all(phone)
    open_editor(phone)
    for f, label in (("topic", "Topic"), ("points", "Points"), ("takeaway", "Takeaway"), ("tags", "Tags")):
        assert phone.locator('label[for="ed-%s"]' % f).inner_text() == label and phone.locator('label[for="ed-%s"]' % f).is_visible()
        assert phone.locator("#dlg").get_by_label(label, exact=True).get_attribute("id") == "ed-" + f  # the label really names its box
        ids = phone.locator("#ed-" + f).get_attribute("aria-describedby").split()
        assert ids == ["ed-%s-hint" % f, "ed-%s-err" % f] and all(phone.locator("#" + i).count() == 1 for i in ids)
        assert phone.locator("#ed-%s-hint" % f).inner_text().strip() and phone.locator("#ed-%s-err" % f).get_attribute("role") == "alert"
        assert phone.locator("#ed-" + f).bounding_box()["height"] >= 48
    for sel in ("#edSave", "#edCancel", '[data-ai="topic"]', '[data-ai="tags"]'):
        assert phone.locator(sel).bounding_box()["height"] >= 48, sel
    assert phone.evaluate("() => document.documentElement.scrollWidth") <= 390
    assert phone.locator("#dlg [role=alert]").count() == 4 and all(not t for t in phone.locator("#dlg [role=alert]").all_inner_texts())  # silent until there is an error
    typed(phone, topic="x" * 300)
    save(phone)
    assert phone.locator("#ed-topic-err").inner_text() and phone.evaluate("() => document.getElementById('ed-topic').getAttribute('aria-invalid')") == "true"


# ---------------------------------------------------------------- a stale save keeps what was typed

def rival_saves(pg, db_text=None):
    """Another page saves the library: this page's next save is refused (and, when db_text is given, the file has changed)."""
    pg.evaluate("t => { const s = window.__rn; if (t) s.db = t; s.rev = (s.rev || 0) + 1; }", db_text)


def test_a_stale_save_reloads_reopens_the_editor_with_what_was_typed_and_applies_it_only_on_the_next_save(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="What I typed", takeaway="And my takeaway")
    before = phone.rn()["db"]
    rival_saves(phone)
    save(phone)
    phone.wait_for_function("() => window.__toasts.some((t) => t.startsWith('Your library changed elsewhere'))")
    assert toasts(phone)[-1] == "Your library changed elsewhere. Your text is still here: tap Save again."
    assert dialog_open(phone) and phone.locator("#ed-topic").input_value() == "What I typed" and phone.locator("#ed-takeaway").input_value() == "And my takeaway"
    assert phone.rn()["db"] == before and phone.evaluate("() => reel('REEL1').notes.topic") == "Passwords in apps"  # nothing is applied by the reload
    assert phone.evaluate("() => JSON.stringify(db)").find("What I typed") == -1  # the draft is kept apart from the reels
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["topic"] == "What I typed" and r["notes"]["takeaway"] == "And my takeaway" and r["notes_by"] == "you"
    assert "editDraft" not in json.dumps(db_of(phone)) and phone.evaluate("() => editDraft") is None


def test_a_change_made_elsewhere_is_kept_when_the_reopened_editor_saves(phone):
    reels = [reel("REEL1", notes=notes(), notes_by="phone")]
    open_reel(phone, reels)
    open_editor(phone)
    typed(phone, topic="Mine from here")
    elsewhere = copy.deepcopy(reels[0])
    elsewhere["notes"]["tags"] = ["from", "elsewhere"]
    rival_saves(phone, json.dumps({"reels": [elsewhere], "inbox": []}))
    save(phone)
    phone.wait_for_function("() => window.__toasts.some((t) => t.startsWith('Your library changed elsewhere'))")
    assert phone.locator("#ed-topic").input_value() == "Mine from here" and dialog_open(phone)  # what was typed is kept
    assert phone.locator("#ed-tags").input_value() == "from, elsewhere"  # a box you did not touch shows the reel as it is now, not as it was
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["topic"] == "Mine from here" and r["notes"]["tags"] == ["from", "elsewhere"] and r["notes_edit"]["fields"] == ["topic"]  # applied on the reel as it is now


def test_a_reload_while_the_editor_is_open_keeps_the_edit_and_does_not_undo_a_change_made_elsewhere(phone):
    """The page may reload (the nightly run saved) while you type: Save must use the reel as it is after the reload,
    and a box you did not touch must not put its old text back over what changed elsewhere."""
    reels = [reel("REEL1", notes=notes(), notes_by="phone")]
    open_reel(phone, reels)
    open_editor(phone)
    typed(phone, topic="Typed before the reload")
    elsewhere = copy.deepcopy(reels[0])
    elsewhere["notes"]["tags"] = ["from", "elsewhere"]
    rival_saves(phone, json.dumps({"reels": [elsewhere], "inbox": []}))
    phone.evaluate("() => staleReload()")
    assert dialog_open(phone) and phone.locator("#ed-topic").input_value() == "Typed before the reload"
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["topic"] == "Typed before the reload" and r["notes_by"] == "you" and r["notes_edit"]["fields"] == ["topic"]
    assert r["notes"]["tags"] == ["from", "elsewhere"]  # the untouched Tags box did not bring back "security, apps"
    assert phone.evaluate("() => reel('REEL1').notes.topic") == "Typed before the reload"


def test_a_reel_removed_elsewhere_says_so_and_closes_the_editor(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="Too late")
    phone.evaluate("() => { db.reels = []; }")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert toasts(phone) == ["This reel is no longer on your shelf."]


def test_a_save_the_phone_refuses_for_lack_of_space_keeps_the_editor_open_and_the_next_save_stores_it(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="Needs space")
    phone.evaluate("() => { window.__rn.storeRefused = true; }")
    save(phone)
    assert dialog_open(phone) and toasts(phone) == ["Could not save. Is the phone's storage full?"] and stored(phone)["notes"]["topic"] == "Passwords in apps"
    phone.evaluate("() => { window.__rn.storeRefused = false; }")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert stored(phone)["notes"]["topic"] == "Needs space" and toasts(phone)[-1] == "Saved"


# ================================================================ K1-3: a newer AI answer for an edited reel waits for your choice

WAITED = FIXTURES_NOW - 86400000  # when the kept answers arrived


def new_notes(topic="New AI topic", **more):
    return {"topic": topic, "intent": "New intent", "tone": "New tone", "points": ["New point one", "New point two"], "meaning": "New meaning", "use": [],
            "tools": ["newtool"], "takeaway": "New AI takeaway", "tags": ["newtag"], "products": ["Acme Soap"], **more}


def slot(src, **more):
    return {"at": WAITED, "notes": new_notes(), "raw": "raw of the " + src + " answer", **more}


def kept_buttons(pg):
    return [b.inner_text() for b in pg.locator("#app [data-kept]").all()]


def click(pg, name):
    pg.get_by_role("button", name=name, exact=True).click()


def reel_now(pg, code="REEL1"):
    return pg.evaluate("c => JSON.parse(JSON.stringify(reel(c)))", code)


# ---------------------------------------------------------------- 6. the four choices

def test_a_waiting_answer_shows_a_card_with_four_choices_and_show_it_changes_nothing(phone):
    open_reel(phone, [edited("REEL1", notes_next={"meta": slot("meta")})])
    when = phone.evaluate("t => day(t)", WAITED)
    assert phone.get_by_text("A newer version from Meta AI (%s) is waiting. Your edits are kept." % when).is_visible()
    assert kept_buttons(phone) == ["Show it", "Keep my edits, update the rest", "Use the new AI version", "Dismiss"]
    assert all(b.bounding_box()["height"] >= 48 for b in phone.locator("#app [data-kept]").all())
    before = phone.rn()["db"]
    assert "New intent" not in screen_text(phone)
    click(phone, "Show it")
    assert "New intent" in screen_text(phone) and "New AI takeaway" in screen_text(phone) and phone.get_by_role("button", name="Hide it").is_visible()
    assert phone.rn()["db"] == before and reel_now(phone)["notes"]["topic"] == "My own topic"  # looking changes nothing
    click(phone, "Hide it")
    assert "New intent" not in screen_text(phone) and phone.get_by_role("button", name="Show it").is_visible()


def test_the_card_names_the_phone_ai_and_a_reel_that_is_not_edited_has_no_keep_button(phone):
    open_reel(phone, [edited("REEL1", notes_next={"phone": slot("phone")}), reel("REEL2", notes=notes(), notes_by="meta", notes_next={"phone": slot("phone")})])
    when = phone.evaluate("t => day(t)", WAITED)
    assert phone.get_by_text("A newer version from the on-phone AI (%s) is waiting. Your edits are kept." % when).is_visible()
    phone.goto(phone.url.split("#")[0] + "#/r/REEL2")
    assert phone.get_by_text("A newer version from the on-phone AI (%s) is waiting." % when).is_visible() and "Your edits are kept" not in screen_text(phone)
    assert kept_buttons(phone) == ["Show it", "Use the new AI version", "Dismiss"]  # nothing of yours to keep


def test_keep_my_edits_updates_the_rest_and_keeps_your_text(phone):
    open_reel(phone, [edited("REEL1", notes_next={"meta": slot("meta")}, raw="R-you")])
    click(phone, "Keep my edits, update the rest")
    r = stored(phone)
    assert r["notes"]["topic"] == "My own topic" and r["notes"]["takeaway"] == "My own takeaway"  # yours
    assert r["notes"]["points"] == ["New point one", "New point two"] and r["notes"]["intent"] == "New intent" and r["notes"]["tags"] == ["newtag"]  # the rest is new
    assert r["notes"]["meaning"] == "New meaning" and r["notes"]["tools"] == ["newtool"] and r["notes"]["products"] == ["Acme Soap"]
    assert r["notes_by"] == "you" and r["raw"] == "raw of the meta answer" and "notes_next" not in r and r["status"] == "done"  # raw: the rest now comes from that answer
    assert r["notes_edit"] == {"was_by": "meta", "at": 7, "fields": ["topic", "takeaway"], "ai": {"topic": "New AI topic", "takeaway": "New AI takeaway"}}
    assert [p["name"] for p in db_of(phone)["products"]] == ["Acme Soap"] and toasts(phone) == ["Updated. Your edits are kept."]
    assert phone.locator("#app [data-kept]").count() == 0 and screen_text(phone).count("Edited by you") == 2
    open_editor(phone)  # "Use the AI text" now brings back the NEW AI text
    phone.locator('[data-ai="topic"]').click()
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert stored(phone)["notes"]["topic"] == "New AI topic" and stored(phone)["notes_edit"]["fields"] == ["takeaway"]


def test_keep_my_edits_with_edited_points_leaves_no_left_out_line_and_without_them_takes_the_new_one(phone):
    start(phone, [edited("REEL1", notes_next={"meta": slot("meta", notes=new_notes(unbacked=2))}),
                  reel("REEL2", notes=notes(topic="Mine"), notes_by="you", notes_next={"meta": slot("meta", notes=new_notes(unbacked=2))},
                       notes_edit={"was_by": "meta", "at": 1, "fields": ["points"], "ai": {"points": ["old"]}})])
    got = phone.evaluate("() => [Notes.keepEdits(reel('REEL1'), 'meta', 9), reel('REEL1').notes.unbacked, Notes.keepEdits(reel('REEL2'), 'meta', 9), 'unbacked' in reel('REEL2').notes]")
    assert got == [True, 2, True, False]  # the new "2 lines left out" belongs to the new points; your points have no such line


def test_keep_my_edits_edge_cases(phone):
    scratch = reel("REEL1", notes=notes(), notes_by="you", notes_edit={"was_by": "", "at": 1, "fields": ["topic"], "ai": {}}, notes_next={"meta": slot("meta"), "you": slot("you")})
    plain = reel("REEL2", notes=notes(), notes_by="meta", notes_next={"meta": slot("meta")})
    start(phone, [scratch, plain])
    got = phone.evaluate("""() => [Notes.keepEdits(reel('REEL1'), 'you'), Notes.keepEdits(reel('REEL1'), 'phone'), Notes.keepEdits(reel('REEL2'), 'meta'),
      Notes.keepEdits(reel('REEL1'), 'meta', 4), reel('REEL1').notes_edit, Object.keys(reel('REEL1').notes_next)]""")
    assert got[:3] == [False, False, False]  # your own slot, nothing waiting, a reel that is not edited
    assert got[3] is True and got[4] == {"was_by": "meta", "at": 1, "fields": ["topic"], "ai": {"topic": "New AI topic"}}  # written from scratch: now there is an AI text to go back to
    assert got[5] == ["you"]


def test_use_the_new_ai_version_keeps_yours_and_use_my_version_again_brings_it_back(phone):
    original = edited("REEL1", notes_next={"meta": slot("meta")}, raw="R-you")
    open_reel(phone, [copy.deepcopy(original)])
    confirm_text(phone, False)
    click(phone, "Use the new AI version")
    assert phone.evaluate("() => window.__confirms") == []  # nothing is replaced: no question
    r = stored(phone)
    assert r["notes"] == new_notes() and r["notes_by"] == "meta" and r["raw"] == "raw of the meta answer" and "notes_edit" not in r and r["status"] == "done"
    assert r["notes_next"] == {"you": {"at": 5, "notes": original["notes"], "edit": original["notes_edit"], "raw": "R-you"}}  # yours is kept whole, with its raw
    assert [p["name"] for p in db_of(phone)["products"]] == ["Acme Soap"]
    text = screen_text(phone)
    assert "Notes by Meta AI" in text and "Edited by you" not in text and "Your edited version is kept." in text
    assert kept_buttons(phone) == ["Use my version again", "Delete my version"]
    click(phone, "Use my version again")  # a swap back: the AI version goes back to its own place
    back = stored(phone)
    assert back["notes_next"] == {"meta": {"at": FIXTURES_NOW, "notes": new_notes(), "raw": "raw of the meta answer"}}
    assert {k: v for k, v in back.items() if k not in ("notes_next", "notes_at", "error")} == {k: v for k, v in original.items() if k not in ("notes_next", "notes_at")}  # notes, notes_edit and raw are as they were
    assert "A newer version from Meta AI" in screen_text(phone) and "Your edits are kept." in screen_text(phone) and "Edited by you" in screen_text(phone)


def test_delete_my_version_asks_and_only_then_deletes_it(phone):
    open_reel(phone, [edited("REEL1", notes_next={"meta": slot("meta")})])
    click(phone, "Use the new AI version")
    confirm_text(phone, False)
    click(phone, "Delete my version")
    assert phone.evaluate("() => window.__confirms") == ["Delete your edited notes for good?"] and "you" in stored(phone)["notes_next"]
    confirm_text(phone, True)
    click(phone, "Delete my version")
    r = stored(phone)
    assert "notes_next" not in r and r["notes"] == new_notes() and phone.evaluate("() => Notes.hasUserData(reel('REEL1'))") is False
    assert phone.locator("#app [data-kept]").count() == 0


def test_dismiss_asks_and_only_then_throws_the_newer_version_away(phone):
    original = edited("REEL1", notes_next={"meta": slot("meta"), "phone": slot("phone")})
    open_reel(phone, [copy.deepcopy(original)])
    confirm_text(phone, False)
    phone.locator('[data-kept="dismiss"][data-src="meta"]').click()
    assert phone.evaluate("() => window.__confirms") == ["Delete the newer version from Meta AI that was kept aside? The notes on the screen stay as they are."]
    assert stored(phone) == original  # No: nothing changes
    confirm_text(phone, True)
    phone.locator('[data-kept="dismiss"][data-src="meta"]').click()
    r = stored(phone)
    assert list(r["notes_next"]) == ["phone"] and r["notes"] == original["notes"] and r["notes_by"] == "you"  # only that one went; the phone answer waits
    confirm_text(phone, True)
    phone.locator('[data-kept="dismiss"][data-src="phone"]').click()
    assert "notes_next" not in stored(phone) and phone.locator("#app [data-kept]").count() == 0


# ---------------------------------------------------------------- 12. swaps

def test_a_second_use_the_new_ai_version_with_your_earlier_version_kept_asks_first(phone):
    e1 = {"was_by": "phone", "at": 1, "fields": ["topic"], "ai": {"topic": "Passwords in apps"}}
    earlier = {"at": 3, "notes": notes(topic="Earlier edit"), "edit": e1, "raw": "R1"}
    original = edited("REEL1", notes_next={"you": earlier, "meta": slot("meta")}, raw="R2")
    open_reel(phone, [copy.deepcopy(original)])
    before = phone.rn()["db"]
    confirm_text(phone, False)
    click(phone, "Use the new AI version")
    assert phone.evaluate("() => window.__confirms") == ["Replace your earlier kept version?"]
    assert phone.rn()["db"] == before and stored(phone) == original  # No: nothing changes at all
    confirm_text(phone, True)
    click(phone, "Use the new AI version")
    r = stored(phone)
    assert r["notes_by"] == "meta" and r["notes"] == new_notes() and r["notes_next"] == {"you": {"at": 5, "notes": original["notes"], "edit": original["notes_edit"], "raw": "R2"}}  # the newer edits are kept, the earlier ones replaced


def test_use_my_version_again_with_newer_edits_on_screen_keeps_those_edits_in_the_kept_place(phone):
    e1 = {"was_by": "phone", "at": 1, "fields": ["topic"], "ai": {"topic": "Passwords in apps"}}
    original = edited("REEL1", notes_next={"you": {"at": 3, "notes": notes(topic="Earlier edit"), "edit": e1, "raw": "R1"}}, raw="R2")
    open_reel(phone, [copy.deepcopy(original)])
    confirm_text(phone, False)
    click(phone, "Use my version again")
    assert phone.evaluate("() => window.__confirms") == []  # the same place: a pure swap, nothing is lost, no question
    r = stored(phone)
    assert r["notes"] == notes(topic="Earlier edit") and r["notes_edit"] == e1 and r["raw"] == "R1" and r["notes_by"] == "you"
    assert r["notes_next"] == {"you": {"at": 5, "notes": original["notes"], "edit": original["notes_edit"], "raw": "R2"}}
    click(phone, "Use my version again")  # and back again: nothing was dropped
    again = stored(phone)
    assert again["notes"] == original["notes"] and again["notes_edit"] == original["notes_edit"] and again["raw"] == "R2"
    assert again["notes_next"]["you"]["notes"] == notes(topic="Earlier edit") and again["notes_next"]["you"]["raw"] == "R1"


@pytest.mark.parametrize("by", ["meta", "phone"])
def test_use_my_version_again_puts_the_ai_version_back_in_its_own_place(phone, by):
    e1 = {"was_by": "phone", "at": 1, "fields": ["topic"], "ai": {"topic": "Passwords in apps"}}
    original = reel("REEL1", notes=new_notes(), notes_by=by, notes_at=8, raw="R-" + by, notes_next={"you": {"at": 3, "notes": notes(topic="Mine"), "edit": e1, "raw": "R-you"}})
    open_reel(phone, [copy.deepcopy(original)])
    confirm_text(phone, False)
    click(phone, "Use my version again")
    assert phone.evaluate("() => window.__confirms") == []
    r = stored(phone)
    assert r["notes"] == notes(topic="Mine") and r["notes_by"] == "you" and r["notes_edit"] == e1 and r["raw"] == "R-you"
    assert r["notes_next"] == {by: {"at": 8, "notes": new_notes(), "raw": "R-" + by}}  # the AI version and its raw went back to where it came from


def test_swapping_in_when_the_places_are_taken_by_another_ai_version_asks_and_names_it(phone):
    original = reel("REEL1", notes=new_notes(), notes_by="meta", notes_at=8, raw="R-meta", notes_next={"meta": {"at": 2, "notes": notes(topic="Older Meta"), "raw": "R-old"}, "phone": slot("phone")})
    open_reel(phone, [copy.deepcopy(original)])
    confirm_text(phone, False)
    phone.locator('[data-kept="use"][data-src="phone"]').click()
    assert phone.evaluate("() => window.__confirms") == ["Replace the Meta AI version kept aside?"] and stored(phone) == original


def test_swap_helper_edges(phone):
    start(phone, [reel("REEL1", notes=notes(), notes_by="auto", notes_next={"meta": slot("meta")}), reel("REEL2", notes=notes(), notes_by="meta", notes_next={})])
    got = phone.evaluate("""() => [Notes.screenSlot({ notes_by: 'you' }), Notes.screenSlot({ notes_by: 'meta' }), Notes.screenSlot({ notes_by: 'phone' }), Notes.screenSlot({ notes_by: 'auto' }), Notes.screenSlot({}),
      Notes.swapIn(reel('REEL2'), 'meta'), Notes.swapIn(reel('REEL1'), 'phone'), Notes.swapIn(reel('REEL1'), 'meta', 6), reel('REEL1').notes_by, reel('REEL1').notes.topic, reel('REEL1').notes_next === undefined,
      Notes.dropSlot(reel('REEL2'), 'meta')]""")
    assert got[:5] == ["you", "meta", "phone", "", ""] and got[5:8] == [False, False, True]
    assert got[8:] == ["meta", "New AI topic", True, False]  # quick notes on screen are not kept: nothing of yours was lost


# ---------------------------------------------------------------- 3 through the screen: every path shows the card

def test_a_kept_meta_answer_shows_its_card_on_the_reel_page(phone):
    start(phone, [edited("REEL1")], shared=[answer_for("REEL1")])
    phone.wait_for_function("() => window.__rn.shared.length === 0")
    phone.goto(phone.url.split("#")[0] + "#/r/REEL1")
    when = phone.evaluate("t => day(t)", FIXTURES_NOW)
    assert phone.get_by_text("A newer version from Meta AI (%s) is waiting. Your edits are kept." % when).is_visible()
    assert kept_buttons(phone) == ["Show it", "Keep my edits, update the rest", "Use the new AI version", "Dismiss"]
    click(phone, "Show it")
    assert "A newer topic from Meta AI" in screen_text(phone)
    click(phone, "Keep my edits, update the rest")
    r = stored(phone)
    assert r["notes"]["topic"] == "My own topic" and r["notes"]["points"] == ["A new point"] and r["notes"]["tags"] == ["newtag"] and r["notes_by"] == "you"
    assert "TOPIC: A newer topic from Meta AI" in r["raw"] and [p["name"] for p in db_of(phone)["products"]] == ["Acme Soap"]


# ---------------------------------------------------------------- 11. Redo with phone AI on an edited reel

def run_log(pg):
    return pg.evaluate("() => run.log")


def test_redo_keeps_the_phone_answer_aside_and_a_waiting_meta_answer_survives(phone):
    original = edited("REEL1", notes_next={"meta": slot("meta")})
    open_reel(phone, [copy.deepcopy(original)], model=READY, answers=[ANSWER])
    click(phone, "Redo with phone AI")
    finished(phone)
    assert len(generate_calls(phone)) == 1 and phone.evaluate("() => run.done") == 0
    r = stored(phone)
    assert r["notes_next"]["phone"]["notes"]["topic"] == AI_TOPIC and r["notes_next"]["phone"]["raw"] == ANSWER
    assert r["notes_next"]["meta"] == original["notes_next"]["meta"]  # the Meta answer is not touched: the user cannot get it back without asking Meta again
    assert {k: v for k, v in r.items() if k not in ("notes_next", "error")} == {k: v for k, v in original.items() if k != "notes_next"}  # notes, raw, status: as they were
    assert run_log(phone)[0]["text"] == KEPT and "tries" not in r
    phone.goto(phone.url.split("#")[0] + "#/r/REEL1")
    assert phone.get_by_text("A newer version from the on-phone AI").is_visible() and phone.get_by_text("A newer version from Meta AI").is_visible()


def test_redo_asks_before_replacing_a_waiting_phone_answer(phone):
    original = edited("REEL1", notes_next={"phone": slot("phone"), "meta": slot("meta")})
    open_reel(phone, [copy.deepcopy(original)], model=READY, answers=[ANSWER])
    confirm_text(phone, False)
    click(phone, "Redo with phone AI")
    assert phone.evaluate("() => window.__confirms") == ["A phone AI version is already waiting. Replace it?"]
    assert generate_calls(phone) == [] and stored(phone) == original  # No: the model is not even called
    confirm_text(phone, True)
    click(phone, "Redo with phone AI")
    finished(phone)
    r = stored(phone)
    assert len(generate_calls(phone)) == 1 and r["notes_next"]["phone"]["raw"] == ANSWER and r["notes_next"]["meta"] == original["notes_next"]["meta"]


def run_redo_that_ends_with(pg, how, reels=None):
    """An edited reel on a model that fails ("fail"), is stopped ("stopped") or meets Instagram's slow down ("slow")."""
    open_reel(pg, reels or [edited("REEL1")], model=READY)
    message = {"stopped": "stopped", "slow": "Instagram says slow down"}.get(how)
    if message:
        pg.evaluate("m => { RN.generate = (id) => setTimeout(() => rnDone(id, false, m), 5); }", message)
    click(pg, "Redo with phone AI")
    finished(pg)


@pytest.mark.parametrize("how", ["fail", "stopped", "slow"])
def test_a_redo_that_fails_is_stopped_or_slowed_down_leaves_an_edited_reel_done_with_no_tries(phone, how):
    run_redo_that_ends_with(phone, how)
    r = stored(phone)
    assert r["status"] == "done" and r["error"] == "" and r["notes_by"] == "you" and r["notes"]["topic"] == "My own topic"
    assert not any(k in r for k in ("tries", "next_try_at", "last_fail", "last_fail_at")) and "notes_next" not in r
    assert phone.evaluate("() => db.reels.filter((x) => x.status === 'failed').length") == 0  # never in "Could not finish"
    if how == "fail":
        assert phone.evaluate("() => [run.failed, run.log[0].ok, run.log[0].text]") == [1, False, "The AI model failed: out of memory"]  # the reason is in the run log only
    elif how == "slow":
        assert phone.evaluate("() => run.note") == "Instagram says slow down"
    phone.goto(phone.url.split("#")[0] + "#/failed")
    assert "Nothing here." in screen_text(phone)


@pytest.mark.parametrize("how,status", [("fail", "failed"), ("stopped", "new"), ("slow", "new")])
def test_the_same_run_on_a_reel_that_is_not_edited_still_counts_or_resets_as_before(phone, how, status):
    """The control for the test above: for a reel nobody edited the three endings are what A1 made them."""
    open_reel(phone, [reel("REEL1", status="new", notes=None)], model=READY)
    message = {"stopped": "stopped", "slow": "Instagram says slow down"}.get(how)
    if message:
        phone.evaluate("m => { RN.generate = (id) => setTimeout(() => rnDone(id, false, m), 5); }", message)
    phone.evaluate("() => startRun(['REEL1'])")
    phone.wait_for_function("() => run && run.finished")
    r = stored(phone)
    assert r["status"] == status and (r.get("tries") == 1) is (how == "fail")


def test_the_other_explicit_runs_never_send_an_edited_reel_to_the_ai(phone):
    original = edited("REEL1", notes_next={"meta": slot("meta")})
    open_reel(phone, [copy.deepcopy(original)], model=READY, answers=[ANSWER, ANSWER])
    phone.evaluate("() => startRun(['REEL1'])")  # by hand, no redo
    phone.goto(phone.url.split("#")[0] + "#/r/REEL1")
    phone.evaluate("() => { window.__before = run; }")
    click(phone, "Read this reel properly")  # caption, video, then the notes: but not for a reel you edited
    phone.wait_for_function("() => run !== window.__before && run.finished")
    assert generate_calls(phone) == []
    r = stored(phone)
    assert r["notes"] == original["notes"] and r["notes_by"] == "you" and r["notes_edit"] == original["notes_edit"] and r["notes_next"] == original["notes_next"] and r["raw"] == original["raw"]


# ---------------------------------------------------------------- the old Redo claim holds for reels that are not edited

@pytest.mark.parametrize("by", ["meta", "phone"])
def test_redo_on_a_reel_with_meta_or_phone_notes_that_is_not_edited_changes_nothing_with_the_redo_flag_too(phone, by):
    r = reel("REEL1", notes=notes(), notes_by=by, notes_at=5, raw="old raw")
    open_reel(phone, [copy.deepcopy(r)], model=READY, answers=[ANSWER])
    phone.evaluate("() => startRun(['REEL1'], { redo: true })")  # redo alone must never let the AI write over Meta or phone notes
    phone.wait_for_function("() => run && run.finished")
    assert generate_calls(phone) == [] and stored(phone) == {**r, "error": ""}
# ---------------------------------------------------------------- review of K1-2 (L-1, L-2, L-5)

@pytest.mark.parametrize("how", ["cancel", "escape"])
def test_closing_the_editor_after_a_save_the_phone_refused_says_so_and_shows_what_the_reel_holds(phone, how):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="Needs space")
    phone.evaluate("() => { window.__rn.storeRefused = true; }")
    save(phone)
    assert dialog_open(phone) and stored(phone)["notes"]["topic"] == "Passwords in apps"  # refused: nothing stored
    if how == "cancel":
        phone.locator("#edCancel").click()
    else:
        phone.keyboard.press("Escape")
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    phone.wait_for_function("() => window.__toasts.some((t) => t.startsWith('Not saved yet'))")
    assert toasts(phone)[-1] == "Not saved yet: the phone's storage is full. Your change is on this screen and is saved with your next successful save."
    assert "Needs space" in screen_text(phone)  # the screen shows what the reel holds, not the old notes
    assert phone.evaluate("() => reel('REEL1').notes.topic") == "Needs space" and stored(phone)["notes"]["topic"] == "Passwords in apps"
    phone.evaluate("() => { window.__rn.storeRefused = false; saveDb(); }")
    assert stored(phone)["notes"]["topic"] == "Needs space"  # saved with the next successful save, as said


def test_closing_the_editor_says_nothing_about_saving_when_nothing_is_pending(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="Fine")
    phone.locator("#edCancel").click()  # typed but not saved: nothing was applied
    open_editor(phone)
    typed(phone, topic="Saved fine")
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    open_editor(phone)
    typed(phone, topic="Stale")
    rival_saves(phone)
    save(phone)  # refused as stale: reloaded, reopened with the text
    phone.wait_for_function("() => window.__toasts.some((t) => t.startsWith('Your library changed elsewhere'))")
    phone.locator("#edCancel").click()
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert not any("Not saved yet" in t for t in toasts(phone)) and toasts(phone)[0] == "Saved"
    assert stored(phone)["notes"]["topic"] == "Saved fine"


def test_use_the_ai_text_reads_the_ai_text_of_the_reel_as_it_is_after_a_reload(phone):
    reels = [edited("REEL1")]
    open_reel(phone, copy.deepcopy(reels))
    open_editor(phone)
    elsewhere = copy.deepcopy(reels[0])
    elsewhere["notes_edit"]["ai"]["topic"] = "The AI topic after another answer"  # e.g. "Keep my edits, update the rest" on another page
    rival_saves(phone, json.dumps({"reels": [elsewhere], "inbox": []}))
    phone.evaluate("() => staleReload()")
    assert dialog_open(phone)
    phone.locator('[data-ai="topic"]').click()
    assert phone.locator("#ed-topic").input_value() == "The AI topic after another answer"  # not the one the editor opened with
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["topic"] == "The AI topic after another answer" and r["notes_edit"]["fields"] == ["takeaway"]


def test_use_the_ai_text_does_nothing_when_the_box_is_no_longer_edited_after_a_reload(phone):
    reels = [edited("REEL1")]
    open_reel(phone, copy.deepcopy(reels))
    open_editor(phone)
    elsewhere = reel("REEL1", notes=notes(topic="Topic put back elsewhere"), notes_by="phone")  # the edits were all put back on another page
    rival_saves(phone, json.dumps({"reels": [elsewhere], "inbox": []}))
    phone.evaluate("() => staleReload()")
    assert phone.locator("#ed-topic").input_value() == "My own topic"
    phone.locator('[data-ai="topic"]').click()
    assert toasts(phone)[-1] == "This box is no longer edited, so there is no AI text to put back."
    assert phone.locator("#ed-topic").input_value() == "My own topic" and phone.locator('[data-ai="topic"]').count() == 0  # the old AI text is not used
    phone.locator("#ed-topic").fill("Typed after")  # and what is typed is yours
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    r = stored(phone)
    assert r["notes"]["topic"] == "Typed after" and r["notes_by"] == "you"
    assert r["notes_edit"]["ai"] == {"topic": "Topic put back elsewhere"} and r["notes_edit"]["was_by"] == "phone"  # the AI text kept is the reel's own, from now


def test_a_reel_removed_elsewhere_closes_the_editor_when_a_stale_save_reloads(phone):
    open_reel(phone, [reel("REEL1", notes=notes(), notes_by="phone")])
    open_editor(phone)
    typed(phone, topic="Typed for nothing")
    rival_saves(phone, json.dumps({"reels": [], "inbox": []}))
    save(phone)
    phone.wait_for_function("() => !document.getElementById('dlg').open")
    assert toasts(phone)[-1] == "This reel is no longer on your shelf." and not any("tap Save again" in t for t in toasts(phone))
    assert phone.evaluate("() => reel('REEL1')") is None and phone.evaluate("() => editDraft") is None


# ---------------------------------------------------------------- review of K1-3 (M-1, L-4)

LITTLE = "Instagram gave too little to work from (no video, little caption). Type what the reel says, or open it in Instagram."


def test_redo_on_an_edited_reel_with_too_little_text_says_so_in_the_run_log_and_leaves_the_reel_alone(phone):
    original = edited("REEL1", caption="hi")
    open_reel(phone, [copy.deepcopy(original)], model=READY, answers=[ANSWER])
    click(phone, "Redo with phone AI")
    finished(phone)
    assert generate_calls(phone) == []
    r = stored(phone)
    assert r["status"] == "done" and r.get("error", "") == "" and r["notes"] == original["notes"] and "notes_next" not in r  # not "Little text", no error text left on the reel
    assert phone.evaluate("() => [run.log[0].ok, run.log[0].text, run.failed]") == [False, LITTLE, 0]  # no green tick, and the reason is plain
    phone.goto(phone.url.split("#")[0] + "#/r/REEL1")
    assert "Little text" not in screen_text(phone) and "Instagram gave too little" not in screen_text(phone)


def test_the_same_run_on_a_reel_that_is_not_edited_still_marks_it_as_little_text(phone):
    open_reel(phone, [reel("REEL1", status="new", notes=None, caption="hi")], model=READY)
    phone.evaluate("() => startRun(['REEL1'])")
    r = stored(phone)
    assert r["status"] == "ready_no_text" and r["error"] == LITTLE and generate_calls(phone) == []  # as before: the control for the test above


def test_after_use_the_new_ai_version_with_a_phone_answer_a_later_meta_answer_replaces_it_directly(phone):
    open_reel(phone, [edited("REEL1", notes_next={"phone": slot("phone")}, raw="R-you")])
    phone.locator('[data-kept="use"][data-src="phone"]').click()
    r = stored(phone)
    assert r["notes_by"] == "phone" and r["notes"] == new_notes() and list(r["notes_next"]) == ["you"]
    mine = r["notes_next"]["you"]
    got = phone.evaluate("t => fileAnswer(t)", answer_for("REEL1"))  # a Meta AI answer for the reel, now a phone AI reel
    assert got["filed"] == 1 and got["kept"] == 0
    after = stored(phone)
    assert after["notes_by"] == "meta" and after["notes"]["topic"] == "A newer topic from Meta AI"  # replaced directly: not kept aside
    assert after["notes_next"] == {"you": mine}  # your own version is untouched, and no phone version is left waiting
