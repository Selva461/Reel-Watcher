"""A page working on an out-of-date copy never overwrites newer data (assets/local/local.js, shots.js).

The Java side (LibraryFile revisions, SharedQueue, SettingsPatch) is tested in android/app-shell/app/src/test (JUnit).
Here: what the page does with what the phone reports, with a fake bridge whose library file has a revision, whose
shared items stay listed until acknowledged, and whose settings are merged key by key. No network, no device."""
import json

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)

GOOD = json.dumps({"reels": [{"code": f"OLD{i:05d}", "url": f"https://www.instagram.com/reel/OLD{i:05d}/", "status": "done",
                              "notes": {"topic": f"topic {i}"}, "added_at": 1} for i in range(5)], "inbox": []})
RIVAL = json.dumps({"reels": [{"code": "RIVAL001", "url": "https://www.instagram.com/reel/RIVAL001/", "status": "done", "added_at": 2}]
                    + json.loads(GOOD)["reels"], "inbox": []})
LINK = "https://www.instagram.com/reel/SHARE0001/"


def link(i):
    return f"https://www.instagram.com/reel/BATCH{i:04d}/"


def codes(pg):
    return [r["code"] for r in db_of(pg)["reels"]]


def page_codes(pg):
    return pg.evaluate("() => db.reels.map((r) => r.code)")


def another_page_saves(pg, db_text):
    """What the nightly run (the other page) does while this page is open: it saves the library, the revision moves on."""
    pg.evaluate("t => { const s = window.__rn; s.db = t; s.rev = (s.rev || 0) + 1; sessionStorage.setItem('rn', JSON.stringify(s)); }", db_text)


def toast_has(pg, text):
    pg.wait_for_function("t => document.getElementById('toast').textContent.includes(t)", arg=text)


# ---------------------------------------------------------------- the library

def test_a_stale_save_is_refused_the_page_reloads_and_the_newer_data_stays(phone):
    phone.open_with({"db": GOOD})
    another_page_saves(phone, RIVAL)
    phone.evaluate("() => addReels([{ code: 'MINE0001', url: 'https://www.instagram.com/reel/MINE0001/' }], 'paste')")
    toast_has(phone, "updated elsewhere")
    assert codes(phone)[0] == "RIVAL001" and "MINE0001" not in codes(phone), "the other page's data was not overwritten"
    assert page_codes(phone)[0] == "RIVAL001" and "MINE0001" not in page_codes(phone), "this page now shows the newer copy"
    phone.evaluate("() => addReels([{ code: 'MINE0002', url: 'https://www.instagram.com/reel/MINE0002/' }], 'paste')")
    phone.wait_for_function("() => window.__rn.db.includes('MINE0002')")  # after the reload, saving works again
    assert "RIVAL001" in codes(phone) and "MINE0002" in codes(phone)


def test_a_page_that_comes_back_reloads_before_it_saves_anything(phone):
    phone.open_with({"db": GOOD})
    another_page_saves(phone, RIVAL)
    phone.evaluate("() => onAppResume()")
    phone.wait_for_function("() => db.reels.some((r) => r.code === 'RIVAL001')")
    # what the page saves afterwards (its own housekeeping on opening) is made from the reloaded copy: the other page's reels stay
    assert json.loads(phone.rn()["db"])["reels"] == json.loads(RIVAL)["reels"]


def test_the_same_page_saving_again_and_again_is_never_stale(phone):
    phone.open_with({"db": GOOD})
    for i in range(5):
        phone.evaluate("i => addReels([{ code: 'SELF000' + i, url: 'https://www.instagram.com/reel/SELF000' + i + '/' }], 'paste')", i)
    assert len([c for c in codes(phone) if c.startswith("SELF")]) == 5
    assert not phone.evaluate("() => document.getElementById('toast').textContent.includes('elsewhere')")


# ---------------------------------------------------------------- shared items: kept until saved

def test_shared_items_are_listed_until_they_are_saved_then_acknowledged(phone):
    phone.open_with({"db": GOOD, "shared": [LINK]})
    phone.wait_for_function("() => window.__rn.db.includes('SHARE0001')")
    phone.wait_for_function("() => window.__rn.shared.length === 0")  # acknowledged after the save
    assert "SHARE0001" in codes(phone)


def test_a_save_that_fails_leaves_the_shared_items_listed(phone):
    phone.open_with({"db": GOOD, "shared": [LINK, link(1)], "storeRefused": True})
    toast_has(phone, "Could not save")
    rn = phone.rn()
    assert rn["shared"] == [LINK, link(1)], "nothing was acknowledged, so nothing is lost"
    assert json.loads(rn["db"]) == json.loads(GOOD)
    phone.evaluate("() => { window.__rn.storeRefused = false; sessionStorage.setItem('rn', JSON.stringify(window.__rn)); onAppResume(); }")
    phone.wait_for_function("() => window.__rn.shared.length === 0")  # the next opening files them
    assert {"SHARE0001", "BATCH0001"} <= set(codes(phone))


def test_shared_items_are_filed_from_the_fresh_copy_when_the_first_save_was_stale(phone):
    phone.open_with({"db": GOOD, "shared": [LINK], "rivalDb": RIVAL})  # the other page saved between this page's load and its save
    phone.wait_for_function("() => window.__rn.shared.length === 0")
    stored = codes(phone)
    assert "RIVAL001" in stored, "the other page's data is still there"
    assert stored.count("SHARE0001") == 1, "and the shared reel is in, once"


def test_a_hundred_shares_survive_a_stale_first_save_exactly_once(phone):
    links = [link(i) for i in range(100)]
    phone.open_with({"db": GOOD, "shared": links, "rivalDb": RIVAL})
    phone.wait_for_function("() => window.__rn.shared.length === 0")
    stored = codes(phone)
    assert len(stored) == 5 + 1 + 100 and len(set(stored)) == len(stored)
    assert "RIVAL001" in stored and all(f"BATCH{i:04d}" in stored for i in range(100))


# ---------------------------------------------------------------- settings: only what changed is sent

def test_only_the_changed_setting_is_sent_and_the_others_stay(phone):
    phone.open_with({"db": GOOD, "settings": json.dumps({"tmdbKey": "my-own-key", "nightMax": 400})})
    phone.evaluate("() => { settings.webLookup = true; saveSettings(); }")
    rn = phone.rn()
    assert [json.loads(p) for p in rn["patches"]] == [{"webLookup": True}], "one key, not the whole settings object"
    stored = json.loads(rn["settings"])
    assert stored["tmdbKey"] == "my-own-key" and stored["nightMax"] == 400 and stored["webLookup"] is True
    phone.evaluate("() => saveSettings()")  # nothing changed: nothing is sent
    assert len(phone.rn()["patches"]) == 1


def test_a_setting_changed_by_the_other_page_is_not_reverted_and_is_picked_up(phone):
    phone.open_with({"db": GOOD, "settings": json.dumps({"tmdbKey": "mine"})})
    phone.evaluate("""() => { const s = window.__rn; s.settings = JSON.stringify({ tmdbKey: 'mine', verifyRunning: true });
                              sessionStorage.setItem('rn', JSON.stringify(s)); }""")  # the nightly page started a check
    phone.evaluate("() => { settings.omdbKey = 'omdb-key'; saveSettings(); }")
    stored = json.loads(phone.rn()["settings"])
    assert stored == {"tmdbKey": "mine", "verifyRunning": True, "omdbKey": "omdb-key"}
    assert phone.evaluate("() => settings.verifyRunning") is True, "this page picked up what the other page set"


def test_settings_are_read_again_when_the_screen_comes_back(phone):
    phone.open_with({"db": GOOD, "settings": json.dumps({"tmdbKey": "old"})})
    phone.evaluate("""() => { const s = window.__rn; s.settings = JSON.stringify({ tmdbKey: 'new' });
                              sessionStorage.setItem('rn', JSON.stringify(s)); onAppResume(); }""")
    assert phone.evaluate("() => settings.tmdbKey") == "new"
    assert not phone.rn().get("patches"), "reading settings again saved nothing"


# ---------------------------------------------------------------- two pages at once

TWO_PAGES_RN = r"""
(() => {
  const key = "two";
  const get = () => JSON.parse(localStorage.getItem(key) || "{}");
  const put = (o) => localStorage.setItem(key, JSON.stringify(o));
  const page = { rev: 0 };
  Object.assign(window.RN, {
    load: () => { const o = get(); page.rev = o.rev || 0; return o.db || ""; },
    store: (j) => { const o = get(); if ((o.rev || 0) !== page.rev) return false; o.db = j; o.rev = page.rev = (o.rev || 0) + 1; put(o); return true; },
    libraryStale: (w) => (w === "shots" ? false : (get().rev || 0) !== page.rev),
    peekShared: () => JSON.stringify((get().shared || []).map((t) => ({ id: "id-" + t, text: t, at: 1 }))),
    ackShared: (ids) => { const o = get(); const gone = JSON.parse(ids); o.shared = (o.shared || []).filter((t) => !gone.includes("id-" + t)); put(o); },
    getSettings: () => get().settings || "{}",
    patchSettings: (j) => { const o = get(); o.settings = JSON.stringify(Object.assign(JSON.parse(o.settings || "{}"), JSON.parse(j))); put(o); return o.settings; },
  });
})();
"""


def shared_state(pg):
    return json.loads(pg.evaluate("() => localStorage.getItem('two')"))


def test_two_live_pages_one_is_refused_reloads_and_loses_neither_data_nor_shares(phone, site):
    base = site.split("#")[0]
    phone.context.add_init_script(TWO_PAGES_RN)
    phone.goto(base + "#/blank")
    phone.evaluate("t => localStorage.setItem('two', JSON.stringify({ db: t, rev: 0, shared: [], settings: '{}' }))", GOOD)
    phone.goto(base + "#/")
    phone.reload()
    phone.wait_for_selector("#app > *")
    other = phone.context.new_page()  # the nightly page: loads the same version of the library
    other.goto(base + "#/")
    other.wait_for_selector("#app > *")
    assert phone.evaluate("() => db.reels.length") == other.evaluate("() => db.reels.length") == 5

    phone.evaluate("() => addReels([{ code: 'AAAA0001', url: 'https://www.instagram.com/reel/AAAA0001/' }], 'paste')")  # saves first
    phone.evaluate("t => { const o = JSON.parse(localStorage.getItem('two')); o.shared = [t]; localStorage.setItem('two', JSON.stringify(o)); }", LINK)
    other.evaluate("() => addReels([{ code: 'BBBB0002', url: 'https://www.instagram.com/reel/BBBB0002/' }], 'paste')")  # out of date
    other.wait_for_function("() => document.getElementById('toast').textContent.includes('updated elsewhere')")
    saved = [r["code"] for r in json.loads(shared_state(phone)["db"])["reels"]]
    assert "AAAA0001" in saved and "BBBB0002" not in saved, "the first page's save stands"
    assert other.evaluate("() => db.reels.some((r) => r.code === 'AAAA0001')"), "the second page reloaded and shows it"

    other.evaluate("() => takeShared()")  # the share is still listed: filed from the fresh copy
    state = shared_state(phone)
    final = [r["code"] for r in json.loads(state["db"])["reels"]]
    assert final.count("SHARE0001") == 1 and "AAAA0001" in final and len(final) == 5 + 1 + 1
    assert state["shared"] == []
    other.close()
