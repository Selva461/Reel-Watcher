"""Local model wrappers for Windows (also runs on Linux and macOS).

Vision model: served by Ollama (https://ollama.com) on this PC, default http://localhost:11434.
Speech: faster-whisper (CTranslate2), CPU by default. Models download on first use.

Model choice (highest priority first):
  --model <ollama tag> / REEL_WATCHER_VLM   exact Ollama vision model, e.g. qwen2.5vl:7b
  --model-size phone|small|large / REEL_WATCHER_MODEL
  auto: phone below 12 GB of RAM, small below 32 GB, else large
REEL_WATCHER_WHISPER overrides the faster-whisper model (tiny, base, small, medium, large-v3, large-v3-turbo).
REEL_WATCHER_WHISPER_DEVICE: cpu (default) or cuda (needs the NVIDIA cuBLAS/cuDNN libraries, see README).
OLLAMA_HOST overrides the Ollama address.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

SIZES = {
    "large": ("qwen3-vl:30b", "large-v3-turbo"),
    "small": ("qwen2.5vl:7b", "small"),
    "phone": ("qwen2.5vl:3b", "base"),  # phones and 8 GB PCs
}
SMALL_RAM_LIMIT = 32 * 1024**3  # below this, auto picks "small"
PHONE_RAM_LIMIT = 12 * 1024**3  # below this, auto picks "phone"
NUM_CTX = int(os.environ.get("REEL_WATCHER_NUM_CTX", "16384"))  # contact sheet + prompt need a large context


def total_ram_bytes() -> int:
    """Physical RAM in bytes (Windows, Linux, macOS), 0 if unknown."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.ullTotalPhys)
        if sys.platform == "darwin":
            import subprocess
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except Exception:
        return 0


def select_models(size=None, model=None, env=None, ram_bytes=None):
    """Return (vlm_tag, whisper_model, size_used). No downloads, no model loading."""
    env = os.environ if env is None else env
    size = size or env.get("REEL_WATCHER_MODEL") or "auto"
    if size == "auto":
        ram = total_ram_bytes() if ram_bytes is None else ram_bytes
        size = "phone" if 0 < ram < PHONE_RAM_LIMIT else "small" if ram < SMALL_RAM_LIMIT else "large"
    if size not in SIZES:
        raise ValueError(f"model size must be phone, small, large or auto, got {size!r}")
    vlm, whisper = SIZES[size]
    vlm = model or env.get("REEL_WATCHER_VLM") or vlm
    whisper = env.get("REEL_WATCHER_WHISPER") or whisper
    return vlm, whisper, size


VISION_MODEL, WHISPER_MODEL, _ = select_models()


def configure(size=None, model=None):
    """Set the module-wide model choice (called once from the CLI before models load)."""
    global VISION_MODEL, WHISPER_MODEL
    VISION_MODEL, WHISPER_MODEL, used = select_models(size, model)
    return used


RETRY_HINT = (
    "\n\nIMPORTANT: output must be short, valid JSON. Keep every text field under 200 characters: "
    "summarize visible text, never copy long passages, code, numbers or grids."
)


def parse_json(text: str):
    """Extract the outermost JSON object from model output, or None."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None


def ollama_host() -> str:
    h = os.environ.get("OLLAMA_HOST", "").strip() or "http://localhost:11434"
    if not h.startswith("http"):
        h = "http://" + h
    return h.replace("0.0.0.0", "localhost").rstrip("/")


def ollama_request(path: str, body: dict | None = None, timeout: float = 900):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(ollama_host() + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:  # Ollama explains failures in the body, e.g. not enough memory for the model
        try:
            reason = (json.loads(e.read().decode("utf-8", errors="replace") or "{}") or {}).get("error") or ""
        except ValueError:
            reason = ""
        raise RuntimeError(f"Ollama: HTTP {e.code}" + (f": {reason}" if reason else "")) from e


def ensure_ollama_model(tag: str, log=print) -> None:
    """Fail with a clear hint if Ollama is not running; pull the model if it is missing."""
    try:
        have = {m.get("name") for m in (ollama_request("/api/tags", timeout=10) or {}).get("models", [])}
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"Ollama is not reachable at {ollama_host()} ({e}). Install it from https://ollama.com/download "
                           "and make sure it is running (Ollama icon in the system tray).") from e
    if tag in have or (":" not in tag and f"{tag}:latest" in have):
        return
    log(f"downloading vision model {tag} through Ollama (one time, several GB)...")
    req = urllib.request.Request(ollama_host() + "/api/pull", data=json.dumps({"model": tag, "stream": True}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    last = -10
    with urllib.request.urlopen(req, timeout=None) as r:
        for line in r:
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("error"):
                raise RuntimeError(f"ollama pull {tag} failed: {ev['error']}")
            if ev.get("total") and ev.get("completed"):
                pct = int(ev["completed"] * 100 / ev["total"])
                if pct >= last + 10:
                    last = pct
                    log(f"  {ev.get('status', '')} {pct}%")
    log(f"{tag} ready")


class Vision:
    """Talks to the Ollama vision model; `ask(prompt, image_path)` returns parsed JSON (or a parse_error dict)."""

    def __init__(self):
        ensure_ollama_model(VISION_MODEL, log=lambda m: print(m, file=sys.stderr, flush=True))
        self.model = VISION_MODEL

    def generate(self, prompt: str, image: str | None, max_tokens: int, penalty: float | None) -> str:
        msg: dict = {"role": "user", "content": prompt}
        if image:
            with open(image, "rb") as f:
                msg["images"] = [base64.b64encode(f.read()).decode("ascii")]
        opts = {"temperature": 0.0, "num_predict": max_tokens, "num_ctx": NUM_CTX}
        if penalty:
            opts["repeat_penalty"] = penalty
        r = ollama_request("/api/chat", {"model": self.model, "messages": [msg], "stream": False,
                                         "format": "json", "options": opts})
        return ((r or {}).get("message") or {}).get("content") or ""

    def ask(self, prompt, image=None, max_tokens=500):
        # Second attempt uses a stricter prompt: busy screens can make the model transcribe text until it runs out of tokens.
        attempts = [(prompt, max_tokens, None), (prompt + RETRY_HINT, max_tokens * 2, 1.15)]
        out = ""
        for text, limit, penalty in attempts:
            out = self.generate(text, image, limit, penalty)
            parsed = parse_json(out)
            if parsed is not None:
                return parsed
        return {"parse_error": True, "raw": str(out)[:1000]}
