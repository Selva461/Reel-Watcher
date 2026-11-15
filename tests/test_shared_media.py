"""Pictures and videos shared to the app, as the page sees them (the copying itself is Java: MediaCopyTest, MediaBatchTest).

The picker's answer is faked: the phone says how many pictures it kept, or why it could not, and the page tells the person.
Videos that were shared are files in the app's inbox; the page makes one reel for each file, and a file that is listed again
(the same share retried, the same video shared twice: one file, named from its content) is still one reel. No network."""
import json

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)
from test_shots import SHOTS_RN

# Each tap on "Choose screenshots" gets the next answer: {"ok": true, "text": "3"} (kept), or {"ok": false, "text": "why"}.
PICK_RN = r"""
(() => {
  const st = window.__rn;
  const later = (fn) => setTimeout(fn, 5);
  Object.assign(st, Object.assign({ pick: [], picked: 0, videos: [] }, st));
  const keep = () => sessionStorage.setItem("rn", JSON.stringify(st));
  Object.assign(window.RN, {
    addShotPictures: (id) => { st.picked++; const a = st.pick.shift() || { ok: false, text: "cancelled" }; keep(); later(() => rnDone(id, a.ok, a.text)); },
    listVideos: (id) => later(() => rnDone(id, true, JSON.stringify(st.videos))),
  });
})();
"""


def _open_shots(pg, answers):
    pg.context.add_init_script(SHOTS_RN)
    pg.context.add_init_script(PICK_RN)
    pg.open_with({"pick": answers}, "#/shots")
    pg.locator("#addp").wait_for()


def _toast(pg):
    return pg.locator("#toast")


def test_pictures_that_were_kept_are_counted(phone):
    _open_shots(phone, [{"ok": True, "text": "3"}])
    phone.locator("#addp").click()
    phone.locator("#toast", has_text="3 pictures added").wait_for()
    assert phone.rn()["picked"] == 1


def test_one_picture_is_counted_in_the_singular(phone):
    _open_shots(phone, [{"ok": True, "text": "1"}])
    phone.locator("#addp").click()
    phone.locator("#toast", has_text="1 picture added").wait_for()
    assert "1 pictures" not in _toast(phone).inner_text()


def test_pictures_that_could_not_be_kept_are_said_with_the_reason(phone):
    answer = json.dumps({"kept": 2, "failed": 1, "why": "not enough storage space on the phone"})
    _open_shots(phone, [{"ok": True, "text": answer}])
    phone.locator("#addp").click()
    phone.locator("#toast", has_text="2 pictures added, 1 could not be saved (not enough storage space on the phone)").wait_for()


def test_when_nothing_could_be_kept_the_reason_is_shown_and_nothing_is_counted_as_added(phone):
    why = "Could not keep those pictures: Reel Shelf is not allowed to read it (any more)"
    _open_shots(phone, [{"ok": False, "text": why}])
    phone.locator("#addp").click()
    phone.locator("#toast", has_text=why).wait_for()
    assert "added" not in _toast(phone).inner_text()


def test_trying_again_after_a_failure_keeps_the_pictures(phone):
    _open_shots(phone, [{"ok": False, "text": "Could not keep those pictures: not enough storage space on the phone"}, {"ok": True, "text": "4"}])
    phone.locator("#addp").click()
    phone.locator("#toast", has_text="not enough storage space").wait_for()
    phone.locator("#addp").click()
    phone.locator("#toast", has_text="4 pictures added").wait_for()
    assert phone.rn()["picked"] == 2


def test_closing_the_picker_says_nothing(phone):
    _open_shots(phone, [{"ok": False, "text": "cancelled"}])
    phone.locator("#addp").click()
    phone.wait_for_function("() => window.__rn.picked === 1")
    phone.wait_for_timeout(300)
    assert _toast(phone).inner_text() == ""


def test_the_comment_screenshots_button_tells_the_same(phone):
    phone.context.add_init_script(SHOTS_RN)
    phone.context.add_init_script(PICK_RN)
    answer = json.dumps({"kept": 1, "failed": 2, "why": "it is too big (over 30 MB)"})
    phone.open_with({"pick": [{"ok": True, "text": answer}]}, "#/inbox")
    phone.locator("#comments").click()
    phone.locator("#toast", has_text="1 picture added, 2 could not be saved (it is too big (over 30 MB))").wait_for()


# ---------------------------------------------------------------- shared videos: one file, one reel

VIDEO = {"k": "file:///data/user/0/app.reelshelf/files/video-inbox/video_0123456789abcdef01234567.mp4", "n": "video_0123456789abcdef01234567.mp4", "m": 1700000000000, "s": 5000000}
OTHER = {"k": "file:///data/user/0/app.reelshelf/files/video-inbox/video_fedcba9876543210fedcba98.mp4", "n": "video_fedcba9876543210fedcba98.mp4", "m": 1700000001000, "s": 7000000}


def _scan(pg):
    return pg.evaluate("() => scanVideos()")


def _files(pg):
    return sorted(r["file"] for r in pg.evaluate("() => db.reels.filter((r) => r.file)"))


def test_a_video_that_is_listed_again_is_still_one_reel(phone):
    phone.context.add_init_script(PICK_RN)
    phone.open_with({"videos": [VIDEO]})
    assert _scan(phone) == 1
    assert _scan(phone) == 0           # the same share retried: the same file (its name comes from its content)
    assert _files(phone) == [VIDEO["k"]]


def test_the_same_video_listed_twice_in_one_scan_is_one_reel(phone):
    phone.context.add_init_script(PICK_RN)
    phone.open_with({"videos": [VIDEO, dict(VIDEO)]})
    assert _scan(phone) == 1
    assert _files(phone) == [VIDEO["k"]]


def test_a_second_different_video_is_a_second_reel(phone):
    phone.context.add_init_script(PICK_RN)
    phone.open_with({"videos": [VIDEO]})
    assert _scan(phone) == 1
    phone.evaluate("(v) => { window.__rn.videos.push(v); }", OTHER)
    assert _scan(phone) == 1
    assert _files(phone) == sorted([VIDEO["k"], OTHER["k"]])


def test_a_video_whose_reel_was_removed_comes_back_when_it_is_shared_again(phone):
    phone.context.add_init_script(PICK_RN)
    phone.open_with({"videos": [VIDEO]})
    assert _scan(phone) == 1
    phone.evaluate("() => { db.reels = db.reels.filter((r) => !r.file); }")   # the person removed the reel
    assert _scan(phone) == 1                                                   # shared again: the file is there, the reel is made again
    assert _files(phone) == [VIDEO["k"]]
