"""The nightly run and the app being used (assets/local/local.js).

Whether a night starts at all (never over the app on screen, never twice at once) is decided in Java: NightGuardTest.
Here: what the page does when the app is opened while the nightly run is still going (the phone asks the run to
finish; the page waits, then reads everything fresh), and that stopping the nightly run keeps what it saved and never
overwrites newer data. A fake bridge stands in for the phone. No network, no device."""
import json

from test_phone_app import EMBED, db_of, phone, site  # noqa: F401  (pytest fixtures)
from test_stale_writes import GOOD, LINK, RIVAL, another_page_saves, codes, page_codes, toast_has  # noqa: F401

FAST = "window.__handover = { poll: 20, max: 5000 };"
# fetches (Instagram pages) wait until the test lets them through, so a run can be stopped at a known moment
HOLD_FETCH = r"""
(() => {
  const st = window.__rn;
  const orig = window.RN.fetchPage;
  window.__held = [];
  window.RN.fetchPage = (id, url) => { if (st.hold) window.__held.push(() => orig(id, url)); else orig(id, url); };
})();
"""


def set_state(pg, **kw):
    pg.evaluate("kw => { const s = window.__rn; Object.assign(s, kw); sessionStorage.setItem('rn', JSON.stringify(s)); }", kw)


def waiting_screen(pg):
    return pg.get_by_text("The nightly run is finishing")


# ---------------------------------------------------------------- the app is opened during a run

def test_opening_the_app_during_the_nightly_run_waits_then_opens_the_fresh_library(phone):
    phone.context.add_init_script(FAST)
    phone.open_with({"db": GOOD, "shared": [LINK], "nightActive": True})
    waiting_screen(phone).wait_for()
    rn = phone.rn()
    assert rn["db"] == GOOD and rn["shared"] == [LINK], "while the run finishes the app reads and saves nothing"
    another_page_saves(phone, RIVAL)  # the run saves the reel it was on
    set_state(phone, nightActive=False)  # and ends
    waiting_screen(phone).wait_for(state="hidden")
    phone.wait_for_function("() => window.__rn.shared.length === 0")  # the share is filed, from the fresh copy
    stored = codes(phone)
    assert "RIVAL001" in stored and stored.count("SHARE0001") == 1 and len([c for c in stored if c.startswith("OLD")]) == 5
    assert "RIVAL001" in page_codes(phone)


def test_coming_back_to_the_app_while_the_night_is_running_hands_over_too(phone):
    phone.context.add_init_script(FAST)
    phone.open_with({"db": GOOD})
    assert len(page_codes(phone)) == 5
    set_state(phone, nightActive=True)  # the alarm started the run while this screen was away
    phone.evaluate("() => onAppResume()")
    waiting_screen(phone).wait_for()
    another_page_saves(phone, RIVAL)
    set_state(phone, nightActive=False)
    waiting_screen(phone).wait_for(state="hidden")
    phone.wait_for_function("() => db.reels.some((r) => r.code === 'RIVAL001')")
    assert "RIVAL001" in codes(phone), "what the run saved is still there"


def test_the_app_does_not_wait_for_ever_for_a_run_that_does_not_end(phone):
    phone.context.add_init_script("window.__handover = { poll: 20, max: 300 };")
    phone.open_with({"db": GOOD, "nightActive": True})
    waiting_screen(phone).wait_for()
    waiting_screen(phone).wait_for(state="hidden")  # the safety net: the library opens (a stale save is still refused by the revision)
    assert len(page_codes(phone)) == 5


def test_the_waiting_screen_stays_on_every_route_until_the_run_has_ended(phone):
    phone.context.add_init_script(FAST)
    phone.open_with({"db": GOOD, "nightActive": True})
    waiting_screen(phone).wait_for()
    phone.evaluate("() => { location.hash = '#/settings'; }")
    waiting_screen(phone).wait_for()
    assert phone.rn()["db"] == GOOD


def test_with_no_run_going_the_app_opens_as_before(phone):
    phone.open_with({"db": GOOD, "shared": [LINK]})
    phone.wait_for_function("() => window.__rn.shared.length === 0")
    assert waiting_screen(phone).count() == 0 and "SHARE0001" in codes(phone)


# ---------------------------------------------------------------- stopping a run keeps its work and newer data

def test_stopping_the_nightly_run_keeps_what_it_saved_and_never_overwrites_newer_data(phone):
    phone.context.add_init_script(HOLD_FETCH)
    phone.open_with({"night": True, "hold": True, "db": GOOD, "shared": ["https://www.instagram.com/reel/NEW001/"],
                     "pages": {"NEW001/embed": EMBED}})
    phone.wait_for_function("() => window.__held.length >= 1")  # the run has filed the shared reel and is reading its page
    assert "NEW001" in codes(phone)
    # the app is opened: it saves a reel of its own, and the phone asks the run to stop
    phone.evaluate("""() => { const s = window.__rn; const d = JSON.parse(s.db);
      d.reels.unshift({ code: 'APP00001', url: 'https://www.instagram.com/reel/APP00001/', status: 'new', added_at: 9 });
      s.db = JSON.stringify(d); s.rev = (s.rev || 0) + 1; s.hold = false; sessionStorage.setItem('rn', JSON.stringify(s)); }""")
    phone.evaluate("() => { window.stopAllWork(); window.__held.splice(0).forEach((f) => f()); }")
    phone.wait_for_function("() => window.__rn.nightDone === 1")
    stored = codes(phone)
    assert "APP00001" in stored, "newer data from the app was not overwritten"
    assert "NEW001" in stored and len([c for c in stored if c.startswith("OLD")]) == 5, "what the run had saved is still there"
    assert stored.count("APP00001") == 1 and stored.count("NEW001") == 1
    assert db_of(phone)["lastNight"]["log"][-1] == "Stopped"


# ---------------------------------------------------------------- duplicate runs

def test_a_second_attempt_to_run_the_night_while_one_is_going_does_nothing(phone):
    phone.context.add_init_script(HOLD_FETCH)
    phone.open_with({"night": True, "hold": True, "db": GOOD, "shared": ["https://www.instagram.com/reel/NEW001/"],
                     "pages": {"NEW001/embed": EMBED}})
    phone.wait_for_function("() => window.__held.length >= 1")
    phone.evaluate("() => { overnightRun(true); overnightRun(true); overnightRun(); }")  # more starts while one is going
    phone.evaluate("() => { window.__rn.hold = false; window.__held.splice(0).forEach((f) => f()); }")
    phone.wait_for_function("() => window.__rn.nightDone >= 1")
    phone.wait_for_timeout(300)
    rn = phone.rn()
    assert rn["nightDone"] == 1, "one run, one ending"
    fetched = [c for c in rn["calls"] if c[0] == "fetchPage" and "NEW001" in c[1]]
    assert len(fetched) <= 2, "the reel was read once (its page, and at most the reel's own page as a fallback), not once per start"
    assert codes(phone).count("NEW001") == 1
