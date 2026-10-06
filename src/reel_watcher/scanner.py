"""Add every image in one or more folders to the library (thousands at a time), skipping exact and near duplicates."""
from __future__ import annotations

import hashlib
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
NEAR_DUP_BITS = 2  # dhash bits (of 64) within which two images count as the same picture


def file_key(p: Path) -> str:
    """Content key: size + first and last 64 KB. Same file copied or renamed gets the same key."""
    h = hashlib.sha1()
    size = p.stat().st_size
    h.update(str(size).encode())
    with open(p, "rb") as f:
        h.update(f.read(65536))
        if size > 131072:
            f.seek(-65536, 2)
            h.update(f.read(65536))
    return "img:" + h.hexdigest()[:24]


def list_images(folders: list[str]) -> list[Path]:
    out = []
    for f in folders:
        root = Path(f).expanduser()
        if root.is_file() and root.suffix.lower() in IMAGE_EXT:
            out.append(root)
        elif root.is_dir():
            out += [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT and not p.name.startswith(".")]
    return sorted(out, key=lambda p: (p.stat().st_mtime, str(p)))


def scan_folders(lib, folders: list[str], job_id: int, collection: str = "Screenshots", skip_dupes: bool = True,
                 hasher=None) -> dict:
    """Queue new images. Returns {found, added, duplicates, known}. Safe to call again (watch mode): known files are skipped."""
    if hasher is None:
        from .study import dhash_bits as hasher
    known_hashes = [int(r["hash"], 16) for r in lib.q("SELECT hash FROM items WHERE kind='image' AND hash!='' AND status!='duplicate'")]
    res = {"found": 0, "added": 0, "duplicates": 0, "known": 0}
    for p in list_images(folders):
        res["found"] += 1
        key = file_key(p)
        if lib.one("SELECT id FROM items WHERE key=?", (key,)):
            res["known"] += 1
            continue
        try:
            h = hasher(p)
        except Exception:  # noqa: BLE001  unreadable or not really an image
            lib.add_item(key, "image", str(p), [collection], job_id=job_id, status="skipped")
            continue
        dup = skip_dupes and any((h ^ k).bit_count() <= NEAR_DUP_BITS for k in known_hashes)
        lib.add_item(key, "image", str(p), [collection], job_id=job_id, hash_=f"{h:016x}", status="duplicate" if dup else "waiting")
        if dup:
            res["duplicates"] += 1
        else:
            known_hashes.append(h)
            res["added"] += 1
    return res
