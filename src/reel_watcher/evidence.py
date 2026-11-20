"""When is a find certain? The rule the whole app uses.

A work is VERIFIED only when two independent kinds of evidence agree on the same work:
  1. the material names it: the words are on screen, said in the reel, in the caption or a comment, and
  2. a reference identifies exactly one real work by that name: a database entry whose name matches exactly and has
     no same-name rival, or web results (Wikipedia, IMDb, MyAnimeList, ...) agreeing on it;
  or two different picture-search services match the same work, or a picture match agrees with a name on screen.
Everything else is a POSSIBLE match (shown with its evidence and alternatives, one tap to confirm), and nothing at all
is NOT FOUND. An AI guess never counts towards verification. The user's own choice is always final.
"""
from __future__ import annotations

from . import lookups

NAMED = ("screen", "speech", "caption", "comment")      # the reel or screenshot itself mentions the name
REFERENCE = ("database", "web")                         # an outside source says which work that name is
PICTURE_MIN = {"trace.moe": 0.90, "SauceNAO": 0.85}     # below these, picture matches are usually wrong
REFERENCE_SITES = ("Wikipedia", "IMDb", "MyAnimeList", "AniList")
LABEL = {"screen": "on screen", "speech": "said in the reel", "caption": "in the caption", "comment": "in a comment",
         "database": "", "web": "", "picture": "", "ai": "AI guess", "user": "chosen by you", "conflict": ""}


def _main(t: str) -> str:
    """'Frieren: Beyond Journey's End' -> 'Frieren' (the part people actually write)."""
    import re
    return re.split(r"\s*[:\u2013\u2014]\s+|\s+-\s+", t or "", maxsplit=1)[0]


def exact(a: str, b: str) -> bool:
    """Same title, allowing case, punctuation and 'The' differences, or the main title without its subtitle."""
    if not (a and b):
        return False
    na, nb = lookups.norm(a), lookups.norm(b)
    return na == nb or lookups.similarity(a, b) >= 0.95 or (len(na) >= 4 and (na == lookups.norm(_main(b)) or nb == lookups.norm(_main(a))))


def named(where: str, text: str) -> dict:
    kind = {"text": "screen", "creator_comment": "comment"}.get(where, where)
    return {"kind": kind if kind in NAMED else "screen", "counts": True, "detail": text[:160]}


def database(hit: dict, clue: str, weak_word: bool = False) -> dict:
    src = "AniList" if hit["ext_key"].startswith("anilist:") else "Wikidata" if hit["ext_key"].startswith("wikidata:") else "database"
    names = [hit["name"], *(hit.get("names") or [])]
    is_exact = any(exact(clue, n) for n in names)
    counts = is_exact and not hit.get("ambiguous") and not weak_word
    why = "" if counts else ("several works have this name" if hit.get("ambiguous") else
                             "the name on screen is only close" if not is_exact else "a common word needs a stronger clue")
    ev = {"kind": "database", "source": src, "counts": counts, "detail": f"{src}: {hit['name']}" + (f" ({hit['year']})" if hit.get("year") else "")}
    if why:
        ev["why"] = why
    return ev


def web(work: dict, clue: str = "", clue_year: int | None = None) -> list[dict]:
    """Evidence from a web search result; a same-name work from another year is reported as a conflict."""
    out = []
    name_ok = not clue or exact(clue, work["name"])
    year_ok = not clue_year or not work.get("year") or abs(work["year"] - clue_year) <= 1
    strong_site = work.get("site") in REFERENCE_SITES and (work.get("year") or work.get("type"))
    counts = name_ok and year_ok and (work.get("agree", 1) >= 2 or bool(strong_site))
    out.append({"kind": "web", "source": work.get("site") or "web", "counts": counts,
                "detail": f"web search: {work.get('evidence') or work['name']}" + (f" (+{work['agree'] - 1} more sites)" if work.get("agree", 1) > 1 else "")})
    if not year_ok:
        out.append({"kind": "conflict", "counts": True, "detail": f"the screen says {clue_year}, the web says {work.get('year')}"})
    for other in work.get("same_name_other_years") or []:
        if not clue_year:
            out.append({"kind": "conflict", "counts": True, "detail": f"another work with this name from {other}"})
    return out


def picture(service: str, res: dict) -> dict:
    score = float(res.get("score") or 0)
    return {"kind": "picture", "source": service, "counts": score >= PICTURE_MIN.get(service, 0.9),
            "detail": f"{service}: {round(score * 100)}% same picture"}


def ai(name: str, why: str = "") -> dict:
    return {"kind": "ai", "counts": False, "detail": f"AI guess: {name}" + (f" ({why})" if why else "")}


def user() -> dict:
    return {"kind": "user", "counts": True, "detail": "chosen by you"}


def verdict(ev: list[dict]) -> tuple[str, str]:
    """('confirmed' | 'check', plain reason)."""
    kinds = {e["kind"] for e in ev if e.get("counts")}
    if "user" in kinds:
        return "confirmed", "chosen by you"
    conflicts = [e["detail"] for e in ev if e["kind"] == "conflict"]
    if conflicts:
        return "check", "not certain: " + "; ".join(conflicts[:2])
    pics = {e["source"] for e in ev if e["kind"] == "picture" and e.get("counts")}
    has_named, has_ref = bool(kinds & set(NAMED)), bool(kinds & set(REFERENCE))
    if has_named and has_ref:
        return "confirmed", "named in the " + ("screenshot" if "screen" in kinds else "reel") + " and identified by " + \
            " + ".join(sorted({e.get("source", e["kind"]) for e in ev if e["kind"] in REFERENCE and e.get("counts")}))
    if len(pics) >= 2:
        return "confirmed", "two picture searches agree"
    if pics and has_named:
        return "confirmed", "picture match agrees with the name on screen"
    missing = [e["why"] for e in ev if e.get("why")]
    if missing:
        return "check", "not certain: " + missing[0]
    if pics:
        return "check", "picture match only; confirm if right"
    weak = [e for e in ev if e["kind"] == "picture"]
    if weak:
        return "check", f"picture match too weak ({weak[0]['detail'].split(': ')[-1].split(' ')[0]}); confirm if right"
    if has_ref:
        return "check", "found by search only; the screen does not name it"
    if has_named:
        return "check", "named, but no database or web page confirms which work"
    return "check", "guess only"


def summary(ev: list[dict]) -> str:
    """'On screen + Wikidata: Parasite (2019) + web search: ...' for the find's evidence line."""
    parts = []
    for e in ev:
        if e["kind"] == "conflict":
            continue
        txt = LABEL.get(e["kind"]) if e["kind"] in NAMED or e["kind"] in ("ai", "user") else e["detail"]
        if txt and txt not in parts:
            parts.append(txt)
    return " + ".join(parts)[:300]
