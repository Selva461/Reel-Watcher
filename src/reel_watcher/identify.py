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

from . import lookups

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
    if words[0].lower() in {"i", "we", "he", "she", "they", "you", "it", "this", "that", "my", "your", "our", "if", "when", "and", "but", "so"}:
        return None
    return s


def _caps_ok(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def extract_candidates(sources: list[tuple[str, str]]) -> list[dict]:
    """sources: [(where, text)] with where in text|speech|caption|comment|creator_comment.
    Returns candidates sorted by score: {name, key, score, sources:[...], evidence}."""
    found: dict[str, dict] = {}

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
        for tag in re.findall(r"#([A-Za-z][A-Za-z0-9_]{3,40})", text):
            if tag.lower() not in GENERIC_TAGS:
                spaced = re.sub(r"(?<=[a-z])(?=[A-Z])|_", " ", tag)
                add(spaced, where, 0.6, "#" + tag)
    out = sorted(found.values(), key=lambda c: -c["score"])
    for c in out:
        c.pop("_seen", None)
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
    hint = kind if kind in ("anime", "manga", "movie", "series", "book", "game") else ""
    out: dict[str, dict] = {}
    for c in [c for c in cands if c["score"] >= min_score][:max_lookups]:
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
        sure = not hit.get("ambiguous") and not weak_word
        out[hit["ext_key"]] = {**hit, "source": SOURCE_LABEL.get(c["sources"][0], c["sources"][0]), "evidence": c["evidence"],
                               "confidence": "confirmed" if sure else "check", "clue_score": c["score"], "raw": c["name"]}
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
