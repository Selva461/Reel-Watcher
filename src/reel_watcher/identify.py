"""Find which movie, series, anime, manga, book or game a reel or screenshot is about.

Clues, strongest first:
  1. names written or said with a label ("anime: Vinland Saga", "name is ..."), the creator's own comments
  2. quoted names, numbered lists ("1. Pluto"), names repeated by several commenters (votes)
  3. capitalised title text on screen, short title-card text, hashtags
Every candidate is checked against free databases (AniList, Wikidata); only names that exist there become
"confirmed". Scene search (trace.moe, SauceNAO) gives "matched". An AI guess from the picture alone is shown
right away as "check" so the user is never left with nothing.
All functions here are pure apart from the injected `resolver` / scene-search callables.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import evidence, lookups

KIND_WORDS = [
    ("quote", r"motivat|quote|inspir|mindset|discipline|affirm|wisdom|self.?improv|success|gym ?mot"),
    ("anime", r"anime"),
    ("manga", r"manga|manhwa|manhua|webtoon|comic"),
    ("series", r"series|tv|show|k.?drama|drama|sitcom|netflix series|web ?series"),
    ("movie", r"movie|film|cinema|flick|bollywood|kollywood|tollywood|hollywood"),
    ("book", r"book|novel|read"),
    ("game", r"game|gaming"),
]


def collection_kind(name: str) -> str:
    """What a collection holds, from its name: anime | manga | series | movie | book | game | quote | generic."""
    n = (name or "").lower()
    for kind, rx in KIND_WORDS:
        if re.search(rx, n):
            return kind
    return "generic"


STOP = {
    "this", "that", "it", "these", "those", "them", "the", "a", "an", "me", "you", "your", "my", "here", "below", "above",
    "link", "bio", "comment", "comments", "follow", "like", "share", "save", "subscribe", "part", "episode", "ep", "season",
    "anime", "manga", "movie", "film", "series", "show", "name", "title", "what", "which", "who", "please", "pls", "plz",
    "bro", "guys", "lol", "lmao", "omg", "wow", "yes", "no", "same", "facts", "fr", "real", "true", "netflix", "prime",
    "crunchyroll", "hotstar", "youtube", "instagram", "reels", "reel", "fyp", "viral", "explore", "trending", "edit", "amv",
    "top", "best", "watch", "read", "next", "now", "today", "day", "number", "one", "two", "three",
}
GENERIC_TAGS = {"anime", "manga", "movie", "movies", "film", "films", "series", "fyp", "foryou", "foryoupage", "viral", "reels",
                "reel", "explore", "explorepage", "trending", "edit", "edits", "amv", "otaku", "weeb", "netflix", "kdrama",
                "bollywood", "hollywood", "cinema", "recommendation", "recommendations", "animeedit", "mangaedit",
                "instagood", "love", "motivation", "quotes", "fun", "funny", "memes", "meme"}
COMMON = {"you", "can", "in", "to", "for", "of", "and", "or", "is", "are", "was", "be", "will", "with", "on", "at", "by", "from",
          "if", "so", "but", "not", "all", "just", "how", "why", "when", "do", "does", "did", "have", "has", "had", "get", "got",
          "make", "made", "more", "most", "very", "really", "need", "want", "love", "every", "weekend", "finish", "time",
          "pm", "am", "delivered", "seen", "typing", "online", "tomorrow", "yesterday", "ever", "never", "must", "should"}
FILLER = re.compile(r"(?:\s+(?:bro|bruh|guys|man|dude|lol|lmao|fr|btw|imo|tho|though|ofc|obviously|for sure|definitely|ya|yaar|bhai))+\s*$", re.I)
TRAIL = re.compile(r"\s*(?:\(?\b(?:19|20)\d{2}\)?|\bseason\s*\d+|\bs\d+\s*e?\d*|\bep(?:isode)?\.?\s*\d+|\bch(?:apter)?\.?\s*\d+|"
                   r"\bon\s+(?:netflix|prime|hulu|disney\+?|crunchyroll|hotstar|youtube)|\bpart\s*\d+|[-:|]+)\s*$", re.I)
LABEL = (r"(?:anime|movie|film|series|show|manga|manhwa|manhua|webtoon|book|novel|k-?drama|drama|game)?\s*(?:name|title)|"
         r"anime|movie|film|series|show|manga|manhwa|manhua|webtoon|book|novel|k-?drama|drama|game")
NAME = r"[\"“']?([^\n.!?,\"”#@|]{2,60})"

PATTERNS = [  # (regex, weight, label)
    (re.compile(rf"\b(?:{LABEL})\s*(?:is|was|:|-|=|–)\s*{NAME}", re.I), 3.0, "labelled"),
    (re.compile(r"[\"“]([A-Z0-9][^\"”\n]{1,58})[\"”]"), 2.0, "quoted"),
    (re.compile(r"(?:^|\n|\s)(?:#\s?\d{1,2}|\d{1,2}[.)]|no\.?\s*\d{1,2})\s*[-:–]?\s*([A-Z0-9][^\n.!?#@,]{1,58}?)(?=\s+(?:#\s?)?\d{1,2}[.)]|\s*$|\s*[\n.!?#@,])"), 2.0, "list"),
    (re.compile(r"\b(?i:number (?:one|two|three|four|five|1|2|3|4|5)|no\.?\s?\d|first|next)\s+(?i:is|has to be|would be|on (?:my|the) list is)\s+([A-Z][\w'’:-]*(?:\s+(?:[A-Z0-9][\w'’:-]*|of|the|no|to|in|and|a|on))*)"), 2.0, "ranked"),
    (re.compile(r"\b(?:watch|read|play|check out|try|recommend(?:ing)?)\s+([A-Z][\w'’:-]*(?:\s+(?:[A-Z0-9][\w'’:-]*|of|the|no|to|in|and|a|on))*)"), 1.5, "verb"),
    (re.compile(r"\b((?:[A-Z0-9][A-Z0-9'’:&-]+)(?:\s+[A-Z0-9][A-Z0-9'’:&-]+){0,5})\b"), 1.0, "caps"),
]
ANSWER = re.compile(r"^\s*(?:it'?s|its|this is|that'?s|it is|the (?:anime|movie|show|manga|series) is|name\s*[:-]|title\s*[:-]|ans(?:wer)?\s*[:-])\s*"
                    r"[\"“']?([^\n.!?\"”#@]{2,60})", re.I)
QUESTION = re.compile(r"\?|^\s*(?:name|title|sauce|source|what|which|who)\b|\bname\s*(?:pls|please|plz)\b", re.I)


def clean_name(raw: str, strict: bool = False) -> str | None:
    """Trim a raw clue to a plausible title, or None. strict (weak clues): reject phrases made of everyday words."""
    s = re.sub(r"\s+", " ", (raw or "")).strip(" \t-:–|'\"“”‘’*_~")
    for _ in range(3):
        s2 = FILLER.sub("", TRAIL.sub("", s)).strip(" -:–|")
        if s2 == s:
            break
        s = s2
    words = s.split()
    if not s or len(s) < 3 or len(words) > 8 or s.isdigit():
        return None
    if all(w.lower().strip("'’") in STOP for w in words):
        return None
    low = [w.lower().strip("'’:") for w in words]
    if strict and (sum(w in COMMON or w in STOP for w in low) / len(low) > 0.34 or (len(low) == 1 and len(low[0]) < 4)):
        return None
    if re.search(r"\d{1,2}:\d{2}", s):
        return None
    if all(re.fullmatch(r"[A-Za-z]{0,2}\d+(?:[.,]\d+)?[KkMm%]?|[ESes]\d{1,3}[Ee]?\d{0,3}", w) for w in words):
        return None  # episode codes, ratings and counts ("E21", "S2E5", "8.1", "13.4K") are not titles
    if words[0].lower() in {"i", "we", "he", "she", "they", "you", "it", "this", "that", "my", "your", "our", "if", "when", "and", "but", "so"}:
        return None
    return s


def _caps_ok(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.8


LANGS = {"tamil": "ta", "hindi": "hi", "telugu": "te", "malayalam": "ml", "kannada": "kn", "bengali": "bn", "marathi": "mr",
         "punjabi": "pa", "korean": "ko", "japanese": "ja", "chinese": "zh", "mandarin": "zh", "cantonese": "zh", "english": "en",
         "spanish": "es", "french": "fr", "german": "de", "italian": "it", "turkish": "tr", "thai": "th"}
LANG_NAMES = {v: k.title() for k, v in LANGS.items() if k not in ("mandarin", "cantonese")}
KINDS = r"film|movie|tv series|television series|web series|mini-?series|series|anime|anime series|manga|manhwa|novel|video game"
# "Scene (2026 film)", "Dark (TV series)", "Parasite (2019)": how Wikipedia, IMDb and posters name a work
PAGE_TITLE = re.compile(rf"(?<![\w(])([A-Z0-9][\w'’:&.!-]*(?:\s+[\w'’:&.!-]+){{0,7}}?)\s*\(\s*((?:19|20)\d\d)?\s*({KINDS})?\s*(?:(?:19|20)\d\d)?[^)]{{0,12}}\)", re.I)
# "Scene is an upcoming Indian Tamil-language action comedy film": the first line of every Wikipedia article
LEAD = re.compile(rf"\b([A-Z0-9][\w'’:&.!-]*(?:\s+[\w'’:&.!-]+){{0,7}}?)\s+(?:is|was)\s+(?:an?|the)\s+((?:[\w-]+\s+){{0,6}}?)({KINDS})(?![a-z])")
SMALL = {"of", "the", "a", "an", "and", "no", "to", "in", "on", "at", "for", "with", "vs", "vs.", "&", "de", "la", "le"}


def _title_tail(raw: str) -> str:
    """Keep the title words at the end of a matched phrase: 'Talk Article Scene' stays long, screen junk before it goes.
    Walks back over Capitalised words, numbers and small joining words."""
    words = raw.split()
    keep: list[str] = []
    for w in reversed(words):
        if re.match(r"^[A-Z0-9][\w'’:&.!-]*$", w) and not re.search(r"[^\x00-\x7f]", w) or (keep and w.lower() in SMALL):
            keep.insert(0, w)
        else:
            break
    lead_words = {"watch", "watching", "read", "reading", "play", "playing", "try", "check", "stream", "streaming", "now", "new", "starring"}
    while keep and (keep[0].lower() in (SMALL | lead_words) - {"a", "an", "the"} or (len(keep[0]) == 1 and keep[0] not in "AI" and len(keep) > 1)):
        keep.pop(0)
    return " ".join(keep)


def page_clues(text: str) -> list[dict]:
    """Strong clues from page-style titles: [{name, year, type, language, evidence}]."""
    out = []
    leads = [m for m in LEAD.finditer(text or "")]
    for m in PAGE_TITLE.finditer(text or ""):
        year, kind = m.group(2), m.group(3)
        if not year and not kind:
            continue
        name = _title_tail(m.group(1))
        # the article's first sentence names the work exactly: prefer it when it ends the title line
        for lm in leads:
            ln = _title_tail(lm.group(1))
            if ln and lookups.norm(name).endswith(lookups.norm(ln)):
                name = ln
        if not name:
            continue
        out.append({"name": name, "year": int(year) if year else None, "type": lookups._kind_of(kind or ""),
                    "language": None, "evidence": m.group(0)})
    for m in leads:
        if not _title_tail(m.group(1)):
            continue
        lang = re.search(r"\b(\w+)-language\b", m.group(2) or "", re.I)
        year = re.search(r"\b((?:19|20)\d\d)\b", m.group(2) or "")
        out.append({"name": _title_tail(m.group(1)), "year": int(year.group(1)) if year else None, "type": lookups._kind_of(m.group(3)),
                    "language": LANGS.get(lang.group(1).lower()) if lang else None, "evidence": m.group(0)})
    # the same work named twice (title line + first sentence): merge year, type and language
    merged: dict[str, dict] = {}
    for c in out:
        k = lookups.norm(c["name"])
        if k in merged:
            for f in ("year", "type", "language"):
                merged[k][f] = merged[k][f] or c[f]
        else:
            merged[k] = c
    return list(merged.values())


UI_WORDS = {"wikipedia", "article", "talk", "search", "home", "menu", "share", "save", "edit", "read", "more", "imdb", "google",
            "chrome", "instagram", "reels", "reel", "follow", "like", "comment", "comments", "send", "reply", "view", "views"}


def search_query(text: str, cands: list[dict], kind: str = "") -> str:
    """What to type into a search engine for this screenshot: the best name with its year and type when the page gave
    them, else the readable words of the screen (status bar, links and buttons dropped)."""
    word = {"movie": "film", "series": "TV series", "anime": "anime", "manga": "manga", "book": "novel", "game": "video game"}
    if cands and cands[0]["score"] >= 2:
        c = cands[0]
        return " ".join(str(x) for x in (c["name"], c.get("year") or "", word.get(c.get("type") or kind, "")) if x)
    words = [w.strip(".,;:!?()[]\"'") for w in (text or "").split()]
    words = [w for w in words if len(w) >= 2 and re.match(r"^[A-Za-z][A-Za-z'’-]*$", w) and w.lower() not in UI_WORDS
             and not re.search(r"\.(?:com|org|net|in)\b", w)]
    if len(words) < 2:
        return " ".join(str(x) for x in (cands[0]["name"], word.get(kind, ""))).strip() if cands else ""
    return " ".join(words[:14] + ([word[kind]] if kind in word else []))


CUES = [("series", re.compile(r"\bseason\s*\d|\bS\d{1,2}\s?E\d{1,3}\b|\bepisodes?\b|\bE\d{1,2}\s+\d\.\d", re.I)),
        ("manga", re.compile(r"\bchapter\s*\d|\bvol(?:ume)?\.?\s*\d", re.I)),
        ("movie", re.compile(r"\bdirected by\b|\bbox office\b|\bruntime\b|\bin cinemas\b", re.I))]


def context_kind(text: str) -> str:
    """What the text around a name says it is: 'Season 1', 'S2E5', episode ratings -> series; 'Chapter 12' -> manga."""
    for kind, rx in CUES:
        if rx.search(text or ""):
            return kind
    return ""


def extract_candidates(sources: list[tuple[str, str]]) -> list[dict]:
    """sources: [(where, text)] with where in text|speech|caption|comment|creator_comment.
    Returns candidates sorted by score: {name, key, score, sources:[...], evidence}."""
    found: dict[str, dict] = {}

    touched: list[tuple[str, float]] = []

    def add(name, where, weight, evidence):
        yr = re.search(r"\b(19[2-9]\d|20[0-4]\d)\b", name or "")
        n = clean_name(name, strict=weight < 2)
        if not n:
            return
        k = lookups.norm(n)
        if len(k) < 3:
            return
        c = found.setdefault(k, {"name": n, "key": k, "score": 0.0, "sources": [], "evidence": evidence.strip()[:200], "_seen": set(), "year": None})
        if yr and not c["year"]:
            c["year"] = int(yr.group(1))
        touched.append((k, weight))
        bonus = 1.0 if where == "creator_comment" else 0.0
        if (where, evidence) not in c["_seen"]:
            c["_seen"].add((where, evidence))
            c["score"] += weight + bonus + (0.5 if c["sources"] and where not in c["sources"] else 0.0)
            if where not in c["sources"]:
                c["sources"].append(where)
        if weight >= 2 and len(n) > len(c["name"]) and lookups.norm(n) == k:
            c["name"] = n

    for where, text in sources:
        text = text or ""
        strong_hit = False
        touched.clear()
        for pc in page_clues(text):
            add(pc["name"], where, 4.0, pc["evidence"])
            c = found.get(lookups.norm(clean_name(pc["name"]) or ""))
            if c:
                strong_hit = True
                c["year"] = c["year"] or pc["year"]
                c["type"] = c.get("type") or pc["type"]
                c["language"] = c.get("language") or pc["language"]
        for rx, w, label in PATTERNS:
            for m in rx.finditer(text):
                g = m.group(1)
                if label == "caps" and (not _caps_ok(g) or where in ("speech",)):
                    continue
                add(g, where, w, text[max(0, m.start() - 40): m.end() + 40])
                strong_hit = strong_hit or w >= 2
        if where in ("comment", "creator_comment"):
            if QUESTION.search(text) and not ANSWER.search(text):
                continue
            m = ANSWER.search(text)
            if m:
                add(m.group(1), where, 2.5, text)
            elif not strong_hit and 1 <= len(text.split()) <= 6:  # a bare short reply ("Vinland Saga") is a vote
                add(text, where, 1.2, text)
        if where == "text" and not strong_hit and 1 <= len(text.split()) <= 6:
            add(text, where, 1.0, text)
        cue = context_kind(text)
        if cue:  # "10. Friends" above "Season 1 (avg 8.1)": a listed name in a series context is a strong clue
            for k, w in touched:
                c = found.get(k)
                if c and w >= 2:
                    c["type"] = c.get("type") or cue
                    if not c.get("_cue"):
                        c["_cue"] = True
                        c["score"] += 0.5
        for tag in re.findall(r"#([A-Za-z][A-Za-z0-9_]{3,40})", text):
            if tag.lower() not in GENERIC_TAGS:
                spaced = re.sub(r"(?<=[a-z])(?=[A-Z])|_", " ", tag)
                add(spaced, where, 0.6, "#" + tag)
    out = sorted(found.values(), key=lambda c: -c["score"])
    for c in out:
        c.pop("_seen", None)
        c.pop("_cue", None)
    return out


def comment_sources(comments: list[dict], creator: str | None) -> list[tuple[str, str]]:
    """yt-dlp comment dicts -> sources. The reel creator's own comments are marked creator_comment."""
    out = []
    for c in comments or []:
        txt = str(c.get("text") or "").strip()
        if not txt:
            continue
        who = (c.get("author") or "").lower()
        out.append(("creator_comment" if creator and who == creator.lower() else "comment", txt))
    return out


SOURCE_LABEL = {"creator_comment": "comment", "comment": "comment", "text": "text", "speech": "speech", "caption": "caption"}


SINGLE_WORD_RISK = 2.5  # one common word ("Dark", "Monster", "Up") needs a labelled clue or several sources


def resolve_candidates(cands: list[dict], kind: str = "", resolver=lookups.resolve_name, max_lookups: int = 8,
                       min_score: float = 1.0, language: str | None = None) -> list[dict]:
    """Check the top candidates in the free databases. Returns titles (deduped by database id), each with
    confidence 'confirmed', or 'check' when another work with the same name fits almost as well."""
    coll_hint = kind if kind in ("anime", "manga", "movie", "series", "book", "game") else ""
    out: dict[str, dict] = {}
    for c in [c for c in cands if c["score"] >= min_score][:max_lookups]:
        hint = c.get("type") or coll_hint  # what the text itself says beats the collection's name
        kw = {}
        if c.get("year"):
            kw["year"] = c["year"]
        if language:
            kw["language"] = language
        try:
            hit = resolver(c["name"], hint, **kw)
        except lookups.QuotaExceeded:
            raise
        except Exception:  # noqa: BLE001  one bad lookup must not lose the others
            hit = None
        if not hit:
            continue
        prev = out.get(hit["ext_key"])
        if prev:
            prev["clue_score"] += c["score"]
            continue
        weak_word = len(c["name"].split()) == 1 and c["name"].lower() in COMMON_TITLE_WORDS and c["score"] < SINGLE_WORD_RISK
        ev = [evidence.named(w, c["evidence"]) for w in c["sources"]] + [evidence.database(hit, c["name"], weak_word)]
        conf, reason = evidence.verdict(ev)
        out[hit["ext_key"]] = {**hit, "source": SOURCE_LABEL.get(c["sources"][0], c["sources"][0]), "evidence": c["evidence"],
                               "confidence": conf, "reason": reason, "proof": ev, "clue_score": c["score"], "raw": c["name"],
                               "clue_year": c.get("year"), "clue_type": c.get("type")}
    return sorted(out.values(), key=lambda t: -t["clue_score"])


# real titles that are also everyday words: only trusted with a strong clue
COMMON_TITLE_WORDS = {"dark", "monster", "up", "her", "us", "it", "you", "friends", "lost", "heat", "split", "glass", "run", "crash",
                      "drive", "home", "family", "love", "life", "gold", "money", "fire", "ice", "rain", "spirit", "vikings",
                      "lucifer", "god", "hero", "beast", "jailer", "master", "leo", "animal", "fighter", "dangal", "pathaan"}


CHAT_RX = re.compile(r"\b(?:delivered|seen|typing|online|last seen|reply|message|whatsapp|imessage|sent)\b|\b\d{1,2}:\d{2}\s?(?:am|pm)?\b", re.I)
RECEIPT_RX = re.compile(r"(?:₹|\$|€|£|rs\.?)\s?\d|\b(?:total|invoice|receipt|gst|tax|amount|paid|upi|order id|transaction)\b", re.I)


def looks_like_other(text: str) -> bool:
    """Chats, receipts and payment screens are put aside instead of being searched."""
    t = text or ""
    return len(CHAT_RX.findall(t)) >= 3 or len(RECEIPT_RX.findall(t)) >= 2


AI_IMAGE_PROMPT = """This image is a screenshot saved by a viewer. Is it from a movie, TV series, anime, manga, book, game, or a poster/list about them?
Return ONLY JSON: {"is_media": true or false, "guesses": [{"name": "official title", "type": "movie|series|anime|manga|book|game", "why": "max 10 words"}]}
Give up to 3 guesses, best first. If you do not recognise it, return an empty guesses list. Never invent a title.
Text read from the image (may help): {ocr}"""


def ai_image_guesses(vision, image_path: str, ocr_text: str = "") -> tuple[bool, list[dict]]:
    """Ask the vision model (Ollama on PC, on-device model on phone). Returns (is_media, guesses)."""
    if vision is None:
        return True, []
    r = vision.ask(AI_IMAGE_PROMPT.replace("{ocr}", (ocr_text or "(none)")[:300]), image_path, max_tokens=220)
    if not isinstance(r, dict) or r.get("parse_error"):
        return True, []
    gs = [g for g in (r.get("guesses") or []) if isinstance(g, dict) and str(g.get("name") or "").strip()]
    return bool(r.get("is_media", True)), gs[:3]
