"""Motivation clips: cut the quote out of a reel and burn in word-by-word captions (GIF or MP4 with sound).

Captions are an ASS subtitle file rendered by ffmpeg's libass, so the same code works on Windows, Linux
and Android (Termux ffmpeg ships libass). Styles match the app: bold (big capitals, the spoken word
highlighted), clean (plain white lines), typewriter (words appear one by one).
"""
from __future__ import annotations

import difflib
import re
import subprocess
from pathlib import Path

from . import media

STYLES = ("bold", "clean", "typewriter")
HIGHLIGHT = "&H0044B5F2&"  # ASS colours are &HAABBGGRR: this is #F2B544
LINE_LIMITS = {"bold": (3, 15), "clean": (4, 24), "typewriter": (4, 24)}  # (words, characters) per caption line


def _tok(s: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", (s or "").lower())


def find_span(words: list[dict], quote: str) -> tuple[int, int] | None:
    """Index range [i, j] of the transcript words that best match `quote` (ratio >= 0.6), else None."""
    q = [t for t in (_tok(w) for w in (quote or "").split()) if t]
    toks = [_tok(w.get("w", "")) for w in words]
    if not q or not toks:
        return None
    best, best_r = None, 0.0
    for size in range(max(1, len(q) - 2), len(q) + 3):
        for i in range(0, max(1, len(toks) - size + 1)):
            win = toks[i: i + size]
            r = difflib.SequenceMatcher(None, q, win).ratio()
            if r > best_r:
                best, best_r = (i, min(i + size, len(toks)) - 1), r
    return best if best_r >= 0.6 else None


def pick_quote(analysis: dict | None, words: list[dict], screen_texts: list[str]) -> dict | None:
    """Choose the motivational line and its timing. Returns {text, start, end, words, source} or None."""
    a = analysis if isinstance(analysis, dict) else {}
    mq = a.get("motivational_quote") if isinstance(a.get("motivational_quote"), dict) else {}
    text = str(mq.get("text") or "").strip()
    if text and words:
        span = find_span(words, text)
        if span:
            i, j = span
            return {"text": text, "start": words[i]["s"], "end": words[j]["e"], "words": words[i: j + 1], "source": "speech"}
    on_screen = next((t for t in screen_texts if t and len(t.split()) >= 4), "")
    if text or on_screen:
        s = float(mq.get("start_s") or 0)
        return {"text": text or on_screen, "start": s, "end": float(mq.get("end_s") or s + 6), "words": [], "source": "text"}
    if words:  # no AI verdict: the first full spoken sentence
        end = next((k for k, w in enumerate(words) if w["w"].endswith((".", "!", "?"))), min(len(words), 14) - 1)
        return {"text": " ".join(w["w"] for w in words[: end + 1]), "start": words[0]["s"], "end": words[end]["e"],
                "words": words[: end + 1], "source": "speech"}
    return None


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _lines(words: list[dict], style: str = "clean") -> list[list[dict]]:
    max_words, max_chars = LINE_LIMITS[style]
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(x["w"] for x in cur + [w])) > max_chars):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(words: list[dict], offset: float, style: str = "bold", width: int = 360, height: int = 640) -> str:
    """ASS subtitle text for `words` (times in reel seconds; `offset` = clip start)."""
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")
    size = round(width * (0.115 if style == "bold" else 0.085))
    bold = -1 if style != "clean" else 0
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Cap,DejaVu Sans,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,{bold},0,0,0,100,100,0,0,1,"
            f"{max(2, size // 12)},1,2,{width // 14},{width // 14},{height // 7},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    lines = _lines(words, style)
    for li, line in enumerate(lines):
        line_end = lines[li + 1][0]["s"] if li + 1 < len(lines) else line[-1]["e"] + 0.4
        if style == "clean":
            ev.append((line[0]["s"], line_end, " ".join(_esc(w["w"]) for w in line)))
            continue
        for k, w in enumerate(line):
            end = line[k + 1]["s"] if k + 1 < len(line) else line_end
            parts = []
            for m, x in enumerate(line):
                t = _esc(x["w"].upper() if style == "bold" else x["w"])
                if style == "typewriter" and m > k:
                    break  # words appear one by one
                if style == "bold" and m == k:
                    t = "{\\c" + HIGHLIGHT + "}" + t + "{\\c&H00FFFFFF&}"
                parts.append(t)
            ev.append((w["s"], end, " ".join(parts)))
    body = "".join(f"Dialogue: 0,{_ts(s - offset)},{_ts(e - offset)},Cap,,0,0,0,,{t}\n" for s, e, t in ev if e > s)
    return head + body


def make_clip(video: Path, out: Path, start: float, end: float, words: list[dict], style: str = "bold",
              fmt: str = "gif", pad: float = 0.3, width: int = 360) -> Path:
    """Cut [start-pad, end+pad] of `video` to `out` (.gif silent, .mp4 with sound) with burned-in captions."""
    pr = media.probe(str(video))
    s = max(0.0, start - pad)
    e = min(pr["duration"] or end + pad, end + pad)
    if e - s < 0.5:
        e = s + 0.5
    height = int(round(width * pr["height"] / max(1, pr["width"]) / 2) * 2)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ass = out.with_suffix(".ass")
    ass.write_text(build_ass(words, s, style, width, height), encoding="utf-8")
    sub = f"subtitles={ass.name}" if words else "null"
    base = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{s:.2f}", "-to", f"{e:.2f}", "-i", str(Path(video).resolve())]
    if fmt == "gif":
        cmd = base + ["-filter_complex", f"[0:v]fps=12,scale={width}:-2:flags=lanczos,{sub},split[a][b];"
                                         "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                      "-loop", "0", out.name]
    elif fmt == "mp4":
        cmd = base + ["-vf", f"scale={width}:-2,{sub}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                      "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out.name]
    else:
        raise ValueError("fmt must be gif or mp4")
    # run inside the output folder so the subtitles path needs no escaping (Windows drive letters break it)
    p = subprocess.run(cmd, cwd=str(out.parent), capture_output=True, text=True, encoding="utf-8", errors="replace")
    ass.unlink(missing_ok=True)
    if p.returncode != 0 or not out.exists():
        raise RuntimeError(f"ffmpeg clip failed: {(p.stderr or '').strip()[-400:]}")
    return out
