"""The library layer of the built-in Reel Shelf (assets/local/library.js): search operators, spelling fixes,
highlighting, topic groups and the cached index. No AI, no network; placeholder notes only."""
import json

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)


def _mk(code, topic, points, tags, tools=(), takeaway=""):
    return {"code": code, "url": f"https://www.instagram.com/reel/{code}/", "status": "done", "added_at": 1, "notes_by": "meta",
            "notes": {"topic": topic, "points": points, "tags": tags, "tools": list(tools), "takeaway": takeaway}}


def _library():
    return {"reels": [
        _mk("SEC001", "Hardcoded passwords leak user data", ["Never hardcode a password in the app", "Rotate any leaked password"],
            ["security", "passwords"], ["gitleaks"], "Keep every password on the server"),
        _mk("SEC002", "Password managers for teams", ["Store each password in a password manager", "Turn on two factor login"],
            ["security", "passwords"], ["Bitwarden", "gitleaks"], "Use a password manager"),
        _mk("SEC003", "Scan your repo for leaked passwords", ["Run gitleaks before every release", "A leaked password must be rotated"],
            ["security"], ["gitleaks"], "Scan before you ship"),
        _mk("GYM001", "Chest workout at the gym", ["Bench press 3 sets of 8", "Rest 90 seconds between sets"], ["gym", "workout"], [],
            "Rest between sets"),
        _mk("GYM002", "Leg day workout", ["Squat 4 sets of 6", "Rest 2 minutes between sets"], ["gym", "workout"], [], "Squats first"),
        _mk("GYM003", "Back workout at the gym", ["Deadlift 3 sets of 5", "Rows 3 sets of 10"], ["gym", "workout"], []),
        _mk("FOOD01", "High protein breakfast", ["Eggs and oats, 40g protein"], ["diet"]),
    ], "inbox": []}


def _ev(pg, js, *args):
    return pg.evaluate(f"(a) => {{ const rs = JSON.parse(window.__rn.db).reels; return ({js})(rs, a); }}", *args)


def codes(pg, q):
    return _ev(pg, "(rs, q) => Lib.find(rs, q).map(x => x.reel.code)", q)


def test_search_operators_exact_words_leave_out_and_tag(phone):
    phone.open_with({"db": json.dumps(_library())})
    assert set(codes(phone, "password")) == {"SEC001", "SEC002", "SEC003"}
    assert codes(phone, '"password manager"') == ["SEC002"]              # exact words
    assert set(codes(phone, "password -manager")) == {"SEC001", "SEC003"}  # leave a word out (and its plural)
    assert set(codes(phone, 'password -"two factor"')) == {"SEC001", "SEC003"}
    assert codes(phone, "sets #workout")[:1] in (["GYM001"], ["GYM002"], ["GYM003"])
    assert "FOOD01" not in codes(phone, "#workout")
    assert set(codes(phone, "#passwords")) == {"SEC001", "SEC002"}       # a tag alone lists that tag
    assert codes(phone, "#nosuchtag password") == []
    lines = _ev(phone, '(rs, q) => Lib.find(rs, q)[0].lines', '"two factor"')
    assert lines[0] == "Turn on two factor login"                         # the line with the exact words comes first
    p = phone.evaluate("""Lib.parseQuery('api "two factor" -leak #Security keys')""")
    assert p["words"] == ["api", "keys"] and p["phrases"] == ["two factor"] and p["exclude"] == ["leak"] and p["tags"] == ["security"]


def test_did_you_mean_uses_only_words_from_the_library(phone):
    phone.open_with({"db": json.dumps(_library())})
    fix = lambda q: _ev(phone, "(rs, q) => Lib.didYouMean(rs, q)", q)
    assert fix("pasward") == "password"
    assert fix("gitleks scan") == "gitleaks scan"
    assert fix("password") is None          # already right
    assert fix("passw") is None             # still typing a longer word
    assert fix("zzzzzzzz") is None          # nothing close: no wild guesses
    assert fix('workot -"two factor" #gym') == 'workout -"two factor" #gym'
    assert phone.evaluate("Lib.distance('form', 'from')") == 1  # swapped letters count as one typo
    assert phone.evaluate("Lib.distance('kitten', 'sitting', 3)") == 3


def test_highlight_marks_matches_and_escapes_everything_else(phone):
    phone.open_with()
    out = phone.evaluate("""Lib.highlight('<b>Passwords</b> leak & the app <img src=x onerror=1>', 'password')""")
    assert out == "&lt;b&gt;<mark>Passwords</mark>&lt;/b&gt; leak &amp; the app &lt;img src=x onerror=1&gt;"
    assert phone.evaluate("""Lib.highlight('Turn on two factor login', '"two factor"')""") == "Turn on <mark>two factor</mark> login"
    assert phone.evaluate("""Lib.highlight('Do a workout', 'exercise')""") == "Do a <mark>workout</mark>"  # a synonym


def test_topics_group_reels_about_the_same_thing(phone):
    phone.open_with({"db": json.dumps(_library())})
    groups = _ev(phone, "(rs) => Lib.topics(rs).map(g => ({key: g.key, label: g.label, codes: g.reels.map(r => r.code).sort()}))")
    by = {tuple(g["codes"]): g for g in groups}
    assert ("SEC001", "SEC002", "SEC003") in by and ("GYM001", "GYM002", "GYM003") in by
    assert all("FOOD01" not in g["codes"] for g in groups)  # alone: no group
    assert "password" in by[("SEC001", "SEC002", "SEC003")]["label"]
    tools = _ev(phone, "(rs) => Lib.tools(rs)")
    assert tools[0] == {"name": "gitleaks", "count": 3}


def test_index_is_reused_until_a_reel_changes(phone):
    phone.open_with({"db": json.dumps(_library())})
    assert phone.evaluate("""() => {
      const rs = JSON.parse(window.__rn.db).reels;
      const a = Notes.index(rs), b = Notes.index(rs);
      if (a !== b) return "not reused";
      rs[6].notes.topic = "Quinoa bowl";
      const c = Notes.index(rs);
      if (c === a) return "not rebuilt";
      return Notes.search(rs, "quinoa")[0].reel.code;
    }""") == "FOOD01"


def test_ask_screen_topics_did_you_mean_and_marks(phone):
    phone.open_with({"db": json.dumps(_library())}, "#/ask")
    phone.get_by_role("heading", name="Topics you learned").wait_for()
    phone.get_by_role("heading", name="Tools you saw most").wait_for()
    phone.locator('a.list-item[href^="#/topic/"]', has_text="password").first.click()
    phone.get_by_text("What you learned").wait_for()
    phone.get_by_text("Use a password manager").wait_for()
    assert phone.locator(".list-item").count() == 3
    phone.goto(phone.url.split("#")[0] + "#/ask?q=pasward%20manajer")
    phone.locator("#fix", has_text="password manager").click()
    phone.locator("mark", has_text="password").first.wait_for()
    assert phone.locator("mark").count() >= 2
    # the reel screen points to its topic
    phone.goto(phone.url.split("#")[0] + "#/r/GYM002")
    phone.locator("a.chip", has_text="Topic:").click()
    phone.get_by_text("Squats first").wait_for()
    assert phone.evaluate("document.documentElement.scrollWidth") <= 390
    # the shelf search box takes the same operators
    phone.goto(phone.url.split("#")[0] + "#/")
    phone.fill("#tq", "password -manager")
    phone.wait_for_function("() => document.querySelectorAll('#results a.list-item').length === 2")


def test_big_library_stays_fast(phone):
    phone.open_with()
    ms = phone.evaluate("""() => {
      const subjects = ["password", "workout", "protein", "budget", "camera", "python", "sleep", "resume", "marketing", "editing"];
      const extra = ["tips", "guide", "mistakes", "tools", "routine", "plan", "basics", "advanced", "free", "fast"];
      const rs = [];
      for (let i = 0; i < 3000; i++) {
        const s = subjects[i % 10], e = extra[(i * 7) % 10], f = extra[(i * 3) % 10];
        rs.push({ code: "R" + i, url: "", notes: { topic: `${s} ${e} number ${i}`, points: [`step one for ${s} ${f}`, `avoid ${e} with ${s}`],
          tags: [s, e], tools: [`Tool${i % 37}`], takeaway: `${s} needs ${f}` } });
      }
      const t0 = performance.now();
      Notes.index(rs);
      const t1 = performance.now();
      for (const q of ["pasword tips", "workout -routine", '"step one" #python', "budgte"]) { Lib.find(rs, q, 20); Lib.didYouMean(rs, q); }
      const t2 = performance.now();
      const g = Lib.topics(rs);
      const t3 = performance.now();
      return { build: t1 - t0, queries: t2 - t1, topics: t3 - t2, groups: g.length };
    }""")
    assert ms["groups"] >= 5
    assert ms["queries"] < 3000, ms   # four searches over 3000 reels, with the index already built
    assert ms["build"] + ms["topics"] < 8000, ms
