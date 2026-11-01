#!/usr/bin/env python3
"""Fetch the photos and videos still reachable from a VK data archive, for Immich.

    python3 pipelines/tools/vk_media.py survey "~/Downloads/VK Data.zip"
    python3 pipelines/tools/vk_media.py fetch "~/Downloads/VK Data.zip" ~/vk-media

The archive (pipelines/vk.md) never held the files: every photo and video
in it is a link to VK's servers, and the account was deleted in 2020, so
most of them no longer answer. This reads the same zip as vk_pack.py,
through its parser, and collects every photo and video link in all of it -
messages' attachments, and the wall, photo, video and every other
section's entries.

- survey: how many photo and video links there are, by year, and how many
  of a sample of each still answer. Nothing is saved.
- fetch: downloads every photo and video that still answers into a folder,
  named VK_<date>_<time>_<hash>.<ext> and dated by its message or entry, so
  Immich places it in its own day - VK stripped the files' own dates. Run
  it again and it skips what it already has. Then upload the folder with
  immich-go (pipelines/vk.md).

A video link is VK's player page, not a file, so videos go through yt-dlp
(https://github.com/yt-dlp/yt-dlp): `yt-dlp` on the PATH, or run through
`uvx`. Each takes the best quality that fits in 1 GB, and one that does
not fit at any quality is skipped. Photos need only the standard library.
Prints counts, never names or contents.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vk_pack import attachments, messages, parse, when  # noqa: E402

IMAGE = re.compile(r"\.(jpe?g|png|gif|webp)(\?|$)", re.I)
PHOTO_WORDS = ("фотограф", "photo")
VIDEO_WORDS = ("видео", "video")
VIDEO_LINK = re.compile(r"^https?://(m\.)?vk\.com/video-?\d+_\d+", re.I)
VIDEO_LIMIT = "1G"
VIDEO_FORMAT = "b[filesize<1G]/b[filesize_approx<1G]/b"  # one file, no ffmpeg needed
AGENT = "Mozilla/5.0 (X11; Linux x86_64) vk_media"


def kind(description: str, link: str) -> str | None:
    d = description.strip().lower()
    if VIDEO_LINK.match(link):
        return "video"
    if d.startswith(VIDEO_WORDS):
        return "video" if link.startswith("http") else None
    if link.startswith("http") and (d.startswith(PHOTO_WORDS) or IMAGE.search(link)):
        return "photo"  # a link to VK's photo page, not the file, simply fails to fetch
    return None


def collect(archive: Path) -> dict[str, dict]:
    """Every photo and video link, once each: {url: {"kind", "time"}}, the
    earliest time it was seen at."""
    found: dict[str, dict] = {}

    def add(k, url, t):
        if not k:
            return
        seen = found.get(url)
        if seen is None or (t and (not seen["time"] or t < seen["time"])):
            found[url] = {"kind": k, "time": t}

    with zipfile.ZipFile(archive) as z:
        for n in sorted(z.namelist()):
            parts = n.split("/")
            if not n.lower().endswith((".html", ".htm")) or len(parts) < 3:
                continue
            section = parts[1]
            try:
                root = parse(z.read(n))
            except Exception:
                continue
            if section == "messages":
                if len(parts) < 4:
                    continue
                for m in messages(root, parts[2], ""):
                    for a in m["attachments"]:
                        for link in a["links"]:
                            add(kind(a["description"], link), link, m["time"])
            elif section != "audio":
                for item in root.find_all("item"):
                    t = when(item.text())
                    for a in attachments(item):
                        for link in a["links"]:
                            add(kind(a["description"], link), link, t)
                    for link in item.links():
                        if VIDEO_LINK.match(link):
                            add("video", link, t)
                        elif IMAGE.search(link):
                            add("photo", link, t)
    return found


def stem_for(url: str, t: str | None) -> str:
    h = hashlib.sha256(url.encode()).hexdigest()[:12]
    stamp = t.replace("-", "").replace(":", "").replace("T", "_") if t else "00000000_000000"
    return f"VK_{stamp}_{h}"


def name_for(url: str, t: str | None) -> str:
    ext = (IMAGE.search(url).group(1).lower() if IMAGE.search(url) else "jpg").replace("jpeg", "jpg")
    return f"{stem_for(url, t)}.{ext}"


def have(folder: Path, url: str, t: str | None) -> bool:
    stem = stem_for(url, t)
    return any(p.suffix not in (".part", ".ytdl") for p in folder.glob(stem + ".*"))


def ytdlp() -> list[str] | None:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    if shutil.which("uvx"):
        return ["uvx", "yt-dlp"]
    return None


def get(url: str, timeout: float = 20) -> bytes | None:
    """The image, or None when the link no longer gives one."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if not r.headers.get("Content-Type", "").startswith("image/"):
                return None
            body = r.read()
            return body if len(body) > 1024 else None  # VK's "deleted" stubs are tiny
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError):
        return None


def video_alive(url: str) -> bool:
    cmd = ytdlp()
    if not cmd:
        return False
    r = subprocess.run(cmd + ["--simulate", "--quiet", "--no-warnings", "-f", VIDEO_FORMAT, url],
                       capture_output=True, timeout=120)
    return r.returncode == 0


def get_video(url: str, folder: Path, t: str | None) -> bool:
    """The video, at the best quality under 1 GB, into folder; False when
    the link no longer gives one or it does not fit."""
    cmd = ytdlp()
    stem = stem_for(url, t)
    try:
        r = subprocess.run(cmd + ["--quiet", "--no-warnings", "--no-playlist", "--no-mtime",
                                  "-f", VIDEO_FORMAT, "--max-filesize", VIDEO_LIMIT,
                                  "-o", str(folder / f"{stem}.%(ext)s"), url],
                           capture_output=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return False
    done = [p for p in folder.glob(stem + ".*") if p.suffix not in (".part", ".ytdl")]
    if r.returncode != 0 or not done:
        return False
    if t:
        ts = time.mktime(datetime.fromisoformat(t).timetuple())
        os.utime(done[0], (ts, ts))
    return True


def _sample(links: list[str], n: int) -> list[str]:
    return links[::max(1, len(links) // n)][:n]


def survey(archive: Path, sample: int = 60) -> None:
    found = collect(archive)
    photos = sorted(u for u, v in found.items() if v["kind"] == "photo")
    videos = sorted(u for u, v in found.items() if v["kind"] == "video")
    for label, links in (("photos", photos), ("videos", videos)):
        years: dict[str, int] = {}
        for u in links:
            y = (found[u]["time"] or "????")[:4]
            years[y] = years.get(y, 0) + 1
        print(f"{label}: {len(links)} links; by year: " + ", ".join(f"{y}: {c}" for y, c in sorted(years.items())))
    if photos:
        picked = _sample(photos, sample)
        with ThreadPoolExecutor(4) as pool:
            alive = sum(1 for b in pool.map(get, picked) if b)
        print(f"photo sample: {alive} of {len(picked)} still answer"
              f" - about {round(len(photos) * alive / len(picked))} to fetch")
    if videos and not ytdlp():
        print("video sample: skipped - install yt-dlp or uv to check videos")
    elif videos:
        picked = _sample(videos, sample // 3)
        with ThreadPoolExecutor(4) as pool:
            alive = sum(1 for ok in pool.map(video_alive, picked) if ok)
        print(f"video sample: {alive} of {len(picked)} still answer"
              f" - about {round(len(videos) * alive / len(picked))} to fetch")


def fetch(archive: Path, folder: Path, workers: int = 4) -> None:
    found = collect(archive)
    folder.mkdir(parents=True, exist_ok=True)
    for label in ("photo", "video"):
        links = sorted(u for u, v in found.items() if v["kind"] == label)
        todo = [u for u in links if not have(folder, u, found[u]["time"])]
        print(f"{label}s: {len(links)} links, already here: {len(links) - len(todo)}, to try: {len(todo)}")
        if label == "video" and todo and not ytdlp():
            print("  skipped: install yt-dlp or uv to fetch videos")
            continue
        _fetch(found, folder, todo, label, workers if label == "photo" else 2)
    print(f"in {folder}")


def _fetch(found: dict, folder: Path, todo: list[str], label: str, workers: int) -> None:
    counts = {"saved": 0, "gone": 0}

    def one(url):
        if label == "video":
            return get_video(url, folder, found[url]["time"])
        body = get(url)
        if not body:
            return False
        t = found[url]["time"]
        path = folder / name_for(url, t)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(body)
        if t:
            ts = time.mktime(datetime.fromisoformat(t).timetuple())
            os.utime(tmp, (ts, ts))
        tmp.rename(path)
        return True

    with ThreadPoolExecutor(workers) as pool:
        for i, ok in enumerate(pool.map(one, todo), 1):
            counts["saved" if ok else "gone"] += 1
            if i % (500 if label == "photo" else 50) == 0:
                print(f"  {i}/{len(todo)}: {counts}")
    print(f"  {label}s done: {counts}")


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "survey":
        survey(Path(args[1]).expanduser())
    elif len(args) == 3 and args[0] == "fetch":
        fetch(Path(args[1]).expanduser(), Path(args[2]).expanduser())
    else:
        sys.exit("usage: vk_media.py survey <VK archive .zip>\n"
                 "       vk_media.py fetch <VK archive .zip> <folder>")


if __name__ == "__main__":
    main()
