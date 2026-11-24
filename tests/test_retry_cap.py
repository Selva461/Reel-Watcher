"""A1: a reel that keeps failing is tried 3 times (12 hours, then 3 days apart), then waits for you, with the reason shown.

Phone harness (Chromium at phone size, the fake window.RN of test_phone_app.py). The page's clock is pinned and moved by
hand (window.__now), so nothing here sleeps or depends on the day the tests run. A fake model with no answers left
rejects ("The AI model failed: out of memory"), which is a reel that fails."""
import json

import pytest

from test_library_upgrade import FIXTURES_NOW, open_fixture, texts
from test_phone_app import ANSWER, db_of, phone, site  # noqa: F401  (pytest fixtures)

HOUR = 3600e3
CLOCK = "window.__now = %d; Date.now = () => window.__now;" % FIXTURES_NOW
READY = {"ready": True, "partial": 0, "installed": []}


def waiting(code, added=1000, **more):
    """A reel that only needs the AI model: caption and video were read, there is enough to write from."""
    return {"code": code, "url": "https://www.instagram.com/reel/%s/" % code, "status": "new", "added_at": added, "collections": [],
            "caption": "Three free tools for taking notes on your phone: " + code, "caption_read": 1, "video_tried": 1, **more}


def start(pg, reels, **extra):
    pg.set_default_timeout(8000)  # a wait that never succeeds fails in seconds
    pg.context.add_init_script(CLOCK)
    pg.open_with({"db": json.dumps({"reels": reels, "inbox": []}), "model": READY, **extra})


def run_start(pg, codes=None):
    return pg.evaluate("c => startRun(c || undefined)", codes)


def generate_calls(pg):
    return len([c for c in pg.rn()["calls"] if c[0] == "generate"])


def reels_by_code(pg):
    return {r["code"]: r for r in db_of(pg)["reels"]}


def advance(pg, ms):
    pg.evaluate("ms => { window.__now += ms; }", ms)


def now(pg):
    return pg.evaluate("() => Date.now()")


# ---------------------------------------------------------------- the helper

def test_retry_after_is_12_hours_then_3_days_then_parked(phone):
    phone.open_with()
    assert phone.evaluate("() => [1, 2].map(Notes.retryAfter)") == [12 * HOUR, 72 * HOUR]
    assert phone.evaluate("() => [Notes.retryAfter(3), Notes.retryAfter(4), Notes.RETRY_CAP]") == [None, None, 3]


# ---------------------------------------------------------------- the cap

def test_five_runs_try_a_failing_reel_three_times_and_then_stop(phone):
    start(phone, [waiting("R1")])
    seen = []
    for step in range(5):
        run_start(phone)
        seen.append(generate_calls(phone))
        r = reels_by_code(phone)["R1"]
        if step == 0:  # the next try is 12 hours away: starting again at once does nothing
            assert r["next_try_at"] == now(phone) + 12 * HOUR
            run_start(phone)
            assert generate_calls(phone) == 1
        if step == 1:
            assert r["next_try_at"] == now(phone) + 72 * HOUR
        advance(phone, 100 * 24 * HOUR if step >= 2 else (r["next_try_at"] - now(phone)) + 1)
    assert seen == [1, 2, 3, 3, 3]
    r = reels_by_code(phone)["R1"]
    assert r["status"] == "failed" and r["tries"] == 3 and r["next_try_at"] == 0
    assert r["last_fail"] == "The AI model failed: out of memory" and r["last_fail_at"] == FIXTURES_NOW + 12 * HOUR + 72 * HOUR + 2


def test_a_reel_given_by_hand_is_tried_even_when_it_is_waiting_or_parked(phone):
    start(phone, [waiting("R1", tries=3, last_fail="x", next_try_at=0), waiting("R2", tries=1, next_try_at=FIXTURES_NOW + HOUR)])
    run_start(phone)
    assert generate_calls(phone) == 0  # Start skips both
    run_start(phone, ["R1", "R2"])  # a button on the reel itself does not
    assert generate_calls(phone) == 2


def test_the_last_failure_text_is_at_most_300_characters(phone):
    start(phone, [waiting("R1")])
    phone.evaluate("() => { RN.generate = (id) => window.__rn.calls.push(['generate']) && setTimeout(() => rnDone(id, false, 'x'.repeat(900)), 5); }")
    run_start(phone)
    assert len(reels_by_code(phone)["R1"]["last_fail"]) == 300


# ---------------------------------------------------------------- what does not count

def test_stop_does_not_count(phone):
    start(phone, [waiting("R1")])
    phone.evaluate("() => { RN.generate = (id) => { window.__rn.calls.push(['generate']); stopRun(); setTimeout(() => rnDone(id, false, 'stopped'), 5); }; }")
    run_start(phone)
    r = reels_by_code(phone)["R1"]
    assert generate_calls(phone) == 1 and "tries" not in r and "last_fail" not in r and r["status"] == "new"


def test_the_battery_stop_does_not_count_even_when_the_model_reports_another_reason(phone):
    start(phone, [waiting("R1")])
    phone.evaluate("() => { RN.generate = (id) => { window.__rn.calls.push(['generate']); stopAllWork(); setTimeout(() => rnDone(id, false, 'The AI model failed: interrupted'), 5); }; }")
    run_start(phone)
    r = reels_by_code(phone)["R1"]
    assert generate_calls(phone) == 1 and "tries" not in r and "next_try_at" not in r


def test_leaving_the_app_does_not_count(phone):
    start(phone, [waiting("R1")])
    phone.evaluate("() => { RN.generate = (id) => { window.__rn.calls.push(['generate']); onAppPause(); setTimeout(() => rnDone(id, false, 'The AI model failed: gone'), 5); }; }")
    run_start(phone)
    assert "tries" not in reels_by_code(phone)["R1"]


def test_instagram_slow_down_does_not_count(phone):
    start(phone, [waiting("R1", caption_read=0, video_tried=0, caption="")], igStatus="Instagram answered 429")
    run_start(phone)
    r = reels_by_code(phone)["R1"]
    assert phone.evaluate("() => run.note").startswith("Instagram asked to slow down")
    assert "tries" not in r and r["status"] == "new"


def test_a_caption_that_cannot_be_read_does_not_count(phone):
    start(phone, [waiting("R1", caption_read=0, video_tried=0, caption="")], igStatus="Instagram answered 404")
    run_start(phone)
    assert "tries" not in reels_by_code(phone)["R1"]


# ---------------------------------------------------------------- success

def test_success_clears_the_failure_fields(phone):
    start(phone, [waiting("R1", status="failed", tries=2, last_fail="old", last_fail_at=5, next_try_at=FIXTURES_NOW - 1)], answers=[ANSWER])
    run_start(phone)
    r = reels_by_code(phone)["R1"]
    assert r["status"] == "done" and r["notes_by"] == "phone"
    assert not {"tries", "last_fail", "last_fail_at", "next_try_at"} & set(r)


# ---------------------------------------------------------------- Try again now, and the breaker

def test_try_again_now_resets_the_reel_and_runs_only_that_one(phone):
    start(phone, [waiting("R1", status="failed", tries=3, last_fail="The AI model failed: out of memory", last_fail_at=FIXTURES_NOW - 1000),
                  waiting("R2")])
    phone.goto(phone.url.split("#")[0] + "#/r/R1")
    phone.get_by_text("Stopped trying after 3 tries: The AI model failed: out of memory.").wait_for()
    phone.get_by_role("button", name="Try again now").click()
    phone.wait_for_function("() => run && run.finished")
    assert generate_calls(phone) == 1
    reels = reels_by_code(phone)
    assert reels["R1"]["tries"] == 1 and "tries" not in reels["R2"]  # it was tried once, then failed once more; R2 was not touched
    assert reels["R1"]["next_try_at"] == FIXTURES_NOW + 12 * HOUR


def test_three_failures_in_a_row_with_the_same_reason_stop_the_run(phone):
    start(phone, [waiting("R%02d" % i, added=1000 + i) for i in range(10)])
    run_start(phone)
    assert generate_calls(phone) == 3
    assert phone.evaluate("() => run.note") == "Stopped after 3 failures in a row: The AI model failed: out of memory"
    tried = [c for c, r in reels_by_code(phone).items() if r.get("tries")]
    assert len(tried) == 3  # only the reels actually tried: a broken model cannot park the library
    assert len([c for c, r in reels_by_code(phone).items() if r["status"] == "new" and "tries" not in r]) == 7


def test_a_success_in_between_resets_the_breaker(phone):
    start(phone, [waiting("R%02d" % i, added=2000 - i) for i in range(8)])
    phone.evaluate("""a => { let n = 0; const g = RN.generate;
      RN.generate = (id, p, o) => (++n === 3 ? window.__rn.calls.push(['generate']) && setTimeout(() => rnDone(id, true, JSON.stringify({ text: a, backend: "gpu", ms: 1 })), 5) : g(id, p, o)); }""", ANSWER)
    run_start(phone)
    assert generate_calls(phone) == 6  # fail, fail, success, then fail, fail, fail: only now are there 3 in a row
    assert phone.evaluate("() => run.note") == "Stopped after 3 failures in a row: The AI model failed: out of memory"


def test_failures_with_different_reasons_do_not_trip_the_breaker(phone):
    start(phone, [waiting("R%02d" % i, added=2000 - i) for i in range(5)])
    phone.evaluate("""() => { let n = 0; RN.generate = (id) => window.__rn.calls.push(['generate']) && setTimeout(() => rnDone(id, false, 'Reason number ' + (++n) + ': x'), 5); }""")
    run_start(phone)
    assert generate_calls(phone) == 5 and phone.evaluate("() => run.note") is None


# ---------------------------------------------------------------- the night queue

def test_night_queue_with_1000_waiting_and_a_cap_of_200_includes_the_50_oldest_without_duplicates(phone):
    phone.open_with()
    got = phone.evaluate("""() => {
      const reels = Array.from({ length: 1000 }, (_, i) => ({ code: "R" + i, url: "u", added_at: 1000 + i, caption: "A caption long enough to write notes from, number " + i, caption_read: 1, video_tried: 1 }));
      return nightQueue(reels, true, Date.now(), 200).map((r) => r.code); }""")
    ids = [int(c[1:]) for c in got]
    assert len(got) == len(set(got)) == 200
    assert set(range(50)) <= set(ids)  # the 50 oldest
    assert ids[:4] == [999, 998, 997, 0] and ids[4:8] == [996, 995, 994, 1]  # 3 newest, then 1 oldest


def test_night_queue_takes_due_retries_from_the_old_end_and_skips_parked_and_waiting(phone):
    phone.open_with()
    got = phone.evaluate("""() => {
      const mk = (code, added, more) => Object.assign({ code, url: "u", added_at: added, caption: "A caption long enough to write notes from " + code, caption_read: 1, video_tried: 1 }, more);
      const now = Date.now();
      const reels = [mk("new1", 50), mk("new2", 40), mk("due", 1, { tries: 1, next_try_at: now - 1 }), mk("later", 2, { tries: 1, next_try_at: now + 1 }),
                     mk("parked", 3, { tries: 3 }), mk("new3", 30), mk("new4", 20)];
      return [nightQueue(reels, true, now, 200).map((r) => r.code), nightQueue(reels, true, now, 2).map((r) => r.code)]; }""")
    assert got[0] == ["new1", "new2", "new3", "due", "new4"]
    assert got[1] == ["new1", "new2"]


def test_the_nightly_run_does_three_new_reels_then_the_oldest(phone):
    reels = [waiting("R%d" % i, added=1000 + i) for i in range(6)]
    start(phone, reels, night=True, answers=[ANSWER] * 6, settings=json.dumps({"nightMax": 4, "rereadOk": True}))
    phone.wait_for_function("window.__rn.nightDone >= 1")
    done = sorted(c for c, r in reels_by_code(phone).items() if r["status"] == "done")
    assert done == ["R0", "R3", "R4", "R5"]


# ---------------------------------------------------------------- old libraries and stale saves

def test_a_reel_without_the_fields_loads_and_a_released_library_keeps_every_key_next_to_them(phone):
    open_fixture(phone, "1.3.11", model=READY)
    before = {r["code"]: r for r in json.loads(texts("1.3.11")[0])["reels"]}
    assert not any("tries" in r or "next_try_at" in r for r in before.values())
    failed = next(c for c, r in before.items() if r["status"] == "failed")
    phone.evaluate("() => { RN.generate = (id) => window.__rn.calls.push(['generate']) && setTimeout(() => rnDone(id, false, 'The AI model failed: out of memory'), 5); }")
    run_start(phone, [failed])
    phone.open_with({"db": phone.rn()["db"]})  # the next session
    assert phone.evaluate("c => reel(c).tries", failed) == 1  # the page read the fields back
    after = reels_by_code(phone)[failed]
    assert after["tries"] == 1 and after["last_fail"] == "The AI model failed: out of memory" and after["next_try_at"] == FIXTURES_NOW + 12 * HOUR
    for key, value in before[failed].items():
        assert key in after, key
        if key not in ("status", "error"):
            assert after[key] == value, key
    assert set(after) - set(before[failed]) == {"tries", "last_fail_at", "last_fail", "next_try_at"}
    assert after["status"] == "failed"  # no new status


def test_a_stale_save_during_a_failure_gives_at_most_one_extra_attempt(phone):
    start(phone, [waiting("R1")])
    phone.evaluate("""() => { const g = RN.generate; let first = true;
      RN.generate = (id, p, o) => { if (first) { first = false; window.__rn.rev = (window.__rn.rev || 0) + 1; } g(id, p, o); }; }""")  # another page saves during the first try
    run_start(phone)
    assert "tries" not in reels_by_code(phone)["R1"]  # the refused save was dropped and the library read again
    for _ in range(2):
        advance(phone, 100 * 24 * HOUR)
        run_start(phone)
    assert reels_by_code(phone)["R1"]["tries"] == 2 and generate_calls(phone) == 3  # 3 attempts, 2 counted: not more than one extra


# ---------------------------------------------------------------- what you see

def day_of(pg, ts):
    return pg.evaluate("t => day(t)", ts)


def test_the_reel_page_says_what_happened_and_when_it_will_be_tried_again(phone):
    start(phone, [waiting("R1", status="failed", tries=2, last_fail="The AI model failed: out of memory", last_fail_at=FIXTURES_NOW - 5 * 24 * HOUR,
                          next_try_at=FIXTURES_NOW + 3 * 24 * HOUR)])
    phone.goto(phone.url.split("#")[0] + "#/r/R1")
    want = "Tried 2 times, last on %s: The AI model failed: out of memory. Next try after %s." % (
        day_of(phone, FIXTURES_NOW - 5 * 24 * HOUR), day_of(phone, FIXTURES_NOW + 3 * 24 * HOUR))
    phone.get_by_text(want).wait_for()
    phone.get_by_role("button", name="Try again now").wait_for()


def test_a_reel_with_notes_shows_no_failure_line(phone):
    start(phone, [waiting("R1", status="done", notes={"topic": "T", "points": ["p"], "tags": []}, notes_by="meta", tries=2, last_fail="old")])
    phone.goto(phone.url.split("#")[0] + "#/r/R1")
    phone.get_by_text("T", exact=True).first.wait_for()
    assert phone.get_by_text("Tried 2 times").count() == 0 and phone.get_by_role("button", name="Try again now").count() == 0


def test_the_inbox_counts_the_reels_that_could_not_be_finished_and_try_all_again_runs_them(phone):
    start(phone, [waiting("R1", status="failed", tries=3, last_fail="a"), waiting("R2", status="failed", tries=1, last_fail="b", next_try_at=FIXTURES_NOW + HOUR),
                  waiting("R3", status="done", notes={"topic": "T"})], settings=json.dumps({}))
    phone.goto(phone.url.split("#")[0] + "#/inbox")
    phone.get_by_text("2 reels could not be finished").click()
    phone.get_by_role("heading", name="Could not finish").wait_for()
    phone.get_by_role("button", name="Try all again").click()
    phone.wait_for_function("() => run && run.finished")
    assert generate_calls(phone) == 2
    reels = reels_by_code(phone)
    assert reels["R1"]["tries"] == 1 and reels["R2"]["tries"] == 1  # reset to 0, then failed once


def test_the_start_screen_says_how_many_wait_and_how_many_stopped(phone):
    start(phone, [waiting("R1", status="failed", tries=3, last_fail="a"), waiting("R2", status="failed", tries=1, last_fail="b", next_try_at=FIXTURES_NOW + HOUR),
                  waiting("R3", status="failed", tries=3, last_fail="c")])
    phone.goto(phone.url.split("#")[0] + "#/run")
    phone.get_by_text("1 reel waits for a retry; 2 stopped after 3 tries.").wait_for()


def test_a_failure_reason_is_shown_as_text_not_as_html(phone):
    evil = '<img src=x onerror="window.__pwned=1">'
    start(phone, [waiting("R1", status="failed", tries=3, last_fail=evil, last_fail_at=FIXTURES_NOW)])
    base = phone.url.split("#")[0]
    for route in ("#/r/R1", "#/failed"):
        phone.goto(base + route)
        phone.get_by_text("Stopped trying after 3 tries").first.wait_for()
        assert phone.locator("#app img").count() == 0
        assert evil in phone.locator("#app").inner_text()
    assert phone.evaluate("() => window.__pwned") is None


# ---------------------------------------------------------------- review follow-ups

def test_a_video_that_takes_over_its_caption_only_reel_is_one_failure_not_two(phone):
    old = waiting("OLD1", author="chef.ana", added=5)
    video = {"code": "V1", "url": "", "file": "K1", "author": "", "status": "new", "added_at": 6, "collections": []}
    start(phone, [video, old])
    phone.evaluate("""() => { RN.readLocalVideo = (id) => setTimeout(() => rnDone(id, true, JSON.stringify({ screen: "@chef.ana\\nCrispy rice in 10 minutes\\nUse day-old rice", seconds: 48 })), 5); }""")
    run_start(phone, ["V1", "OLD1"])
    assert generate_calls(phone) == 1
    reels = reels_by_code(phone)
    assert "OLD1" not in reels and reels["V1"]["ig_code"] == "OLD1"  # the two became one
    assert reels["V1"]["tries"] == 1 and reels["V1"]["next_try_at"] == FIXTURES_NOW + 12 * HOUR


def test_a_night_stopped_by_the_breaker_says_so_in_the_morning(phone):
    start(phone, [waiting("R%d" % i, added=1000 + i) for i in range(6)], night=True, settings=json.dumps({"nightMax": 10, "rereadOk": True}))
    phone.wait_for_function("window.__rn.nightDone >= 1")
    log = db_of(phone)["lastNight"]["log"]
    assert "Stopped after 3 failures in a row: The AI model failed: out of memory" in log


def test_the_tries_number_is_escaped_in_the_failure_line(phone):
    evil = '<img src=x onerror="window.__pwned=1">'
    start(phone, [waiting("R1", status="failed", tries=evil, last_fail="a", last_fail_at=FIXTURES_NOW)])
    phone.goto(phone.url.split("#")[0] + "#/r/R1")
    phone.get_by_text("Tried 0 times").wait_for()
    assert phone.locator("#app img").count() == 0 and phone.evaluate("() => window.__pwned") is None


def test_a_retry_date_far_in_the_future_is_a_wrong_clock_and_counts_as_due(phone):
    start(phone, [waiting("R1", tries=1, next_try_at=FIXTURES_NOW + 100 * 24 * HOUR), waiting("R2", tries=1, next_try_at=FIXTURES_NOW + 71 * HOUR)])
    run_start(phone)
    assert generate_calls(phone) == 1 and reels_by_code(phone)["R1"]["tries"] == 2  # R1 was tried, R2 (a real wait) was not
    assert reels_by_code(phone)["R2"]["tries"] == 1


def test_a_reel_with_quick_notes_and_a_parked_ai_rewrite_shows_the_line_and_the_button(phone):
    start(phone, [waiting("R1", status="failed", notes={"topic": "Quick", "points": ["p"], "tags": []}, notes_by="auto", tries=3, last_fail="why", last_fail_at=FIXTURES_NOW)])
    phone.goto(phone.url.split("#")[0] + "#/r/R1")
    phone.get_by_text("Stopped trying after 3 tries: why.").wait_for()
    phone.get_by_role("button", name="Try again now").wait_for()


def test_the_nightly_run_leaves_reels_read_before_videos_alone_unless_you_tried_it_yourself(phone):
    start(phone, [waiting("R1")], night=True, answers=[ANSWER], settings=json.dumps({}))
    phone.wait_for_function("window.__rn.nightDone >= 1")
    assert generate_calls(phone) == 0 and reels_by_code(phone)["R1"]["status"] == "new"


def test_the_three_new_reels_of_the_night_never_include_a_reel_that_failed_before(phone):
    phone.open_with()
    got = phone.evaluate("""() => {
      const mk = (code, added, more) => Object.assign({ code, url: "u", added_at: added, caption: "A caption long enough to write notes from " + code, caption_read: 1, video_tried: 1 }, more);
      const now = Date.now();
      const reels = [10, 20, 30, 40, 50].map((a) => mk("new" + a, a)).concat([mk("tried", 9999, { tries: 1, next_try_at: now - 1 })]);
      return nightQueue(reels, true, now, 4).map((r) => r.code); }""")
    assert got == ["new50", "new40", "new30", "new10"]  # 3 new, then the oldest; the retry (newest) waits for the old end
