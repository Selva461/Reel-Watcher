"""Installed-version checks. On a phone, Pillow and NumPy come from Termux's packages and yt-dlp from pip, outside the
lock file, so the app checks at start that nothing below the audited safe versions is in use."""
from __future__ import annotations

import re
from importlib import metadata

# lowest versions without known security advisories (pip-audit against PyPI's vulnerability data, October 2026)
MIN_SAFE = {"pillow": "12.3.0", "yt-dlp": "2026.7.4"}
FIX = {"pillow": "pkg upgrade (Termux) or pip install -U pillow", "yt-dlp": "pip install -U yt-dlp"}


def _v(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:4])


def outdated() -> list[str]:
    """Readable warnings for installed packages older than their safe version."""
    out = []
    for pkg, safe in MIN_SAFE.items():
        try:
            have = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            continue
        if _v(have) < _v(safe):
            out.append(f"{pkg} {have} has known security problems; update to {safe} or newer: {FIX[pkg]}")
    return out
