"""Nothing is kept on one word alone: reel-note points need the reel's own text behind them. No network."""
from test_phone_app import phone, site  # noqa: F401  (pytest fixtures)

REEL = {"caption": "Never hardcode a database password in your Android app. Keep secrets on the server.",
        "transcript": "a researcher scanned the app and found the password, then rotate every credential that leaked",
        "onscreen": "8.5M rewards members exposed"}


def test_ai_points_the_reel_does_not_back_up_are_left_out(phone):
    phone.open_with()
    got = phone.evaluate("""r => { const n = {topic: 't', points: [
        'Never hardcode a database password in the app',
        'Rotate every leaked credential',
        'Use Kubernetes operators for blue green deployments',
        'Members exposed',
        'Buy the course for lifetime updates and bonuses']};
      const out = Notes.keepBacked(n, r); return [out, n.points, n.unbacked]; }""", REEL)
    assert got == [2, ["Never hardcode a database password in the app", "Rotate every leaked credential", "Members exposed"], 2]
    # Too little reel text to judge: nothing is dropped.
    kept = phone.evaluate("() => { const n = {points: ['Anything at all here', 'And more']}; return [Notes.keepBacked(n, {caption: '#fun'}), n.points.length]; }")
    assert kept == [0, 2]


def test_a_web_fact_from_one_page_is_marked_one_source(phone):
    phone.open_with()
    web = [{"title": "Dune (novel)", "url": "https://en.wikipedia.org/wiki/Dune_(novel)"},
           {"title": "Dune", "url": "https://duckduckgo.com/Dune"}, {"title": "Dune (novel)", "url": "https://en.wikipedia.org/wiki/Dune_(novel)"}]
    got = phone.evaluate("""w => Notes.markOneSource(
        'Dune was written by Frank Herbert [W1][W2]. It came out in 1965 [W1]. It is twice cited from one page [W1][W3]. You liked it [2].\\nNo source here.', w)""", web)
    assert got == ("Dune was written by Frank Herbert [W1][W2]. It came out in 1965 [W1] (one source). It is twice cited from one page [W1][W3] (one source)."
                   " You liked it [2].\nNo source here.")


def test_quotes_are_looked_up_on_wikiquote(phone):
    phone.open_with()
    got = phone.evaluate("""async () => {
      const db = {quotes: [
        {id: 'a', text: 'Why so serious? Let us put a smile on that face', from: 'The Dark Knight'},
        {id: 'b', text: 'Fear is the mind-killer, the little death', from: ''},
        {id: 'c', text: 'My cousin said this at dinner last night', from: ''},
        {id: 'd', text: 'Already looked up and found earlier', online: {found: true, page: 'X', at: 1}}]};
      const asked = [];
      const pages = {a: 'The Dark Knight (film)', b: 'Dune (novel)'};
      const ask = async (t) => { asked.push(t); const id = db.quotes.find((q) => q.text === t).id;
        return JSON.stringify(pages[id] ? {found: true, page: pages[id], url: 'https://en.wikiquote.org/wiki/' + pages[id]} : {found: false}); };
      const n = await Quotes.checkOnline(db, ask, {gap: 0});
      return [n, asked.length, db.quotes.map((q) => [q.id, q.online.found, !!q.online.twice, q.from || ''])];
    }""")
    assert got == [2, 3, [["a", True, True, "The Dark Knight"], ["b", True, False, "Dune"], ["c", False, False, ""], ["d", True, False, ""]]]
