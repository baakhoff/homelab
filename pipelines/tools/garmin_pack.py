#!/usr/bin/env python3
"""Pack a Garmin "Export Your Data" archive into one file for the ingest_garmin_export DAG.

    uv run --with fitdecode==0.11.0 python3 pipelines/tools/garmin_pack.py \\
      ~/Downloads/garmin-export.zip ~/garmin-export.jsonl.gz

The archive is a zip of JSON files - DI_CONNECT/DI-Connect-<area>/... - and,
under DI-Connect-Uploaded-Files, zips of the FIT files the watches
uploaded. This reads it as it is, the inner zips through a temporary file,
and writes one gzipped JSON line per record:

- export/<area>/<kind>: every item of every JSON file - the area is the
  folder without its DI-Connect- prefix, the kind the file's name without
  its dates, numbers and email address (2019-01-01_2019-04-11_123_sleepData
  is export/wellness/sleepData). A file that is one object is one item; an
  item that only wraps a list (summarizedActivitiesExport) is that list's
  items.
- fit/<message>: from each activity FIT file, every session, lap, length,
  split, set, HRV and record message - a record is one second, or a few, of
  the recording: time, position, heart rate, speed, cadence, power,
  altitude. Their fields as the FIT SDK names them, positions as degrees,
  times in UTC. Monitoring and other FIT files are left out: the same
  days come from the JSON and the API, summed.

Each record's id is a hash of what it is, so packing and loading again adds
nothing. File names keep the number, never the email address that Garmin
puts in some. Nothing is masked here; the DAG does that. Prints counts,
never contents. The procedure: pipelines/garmin.md.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

FIT_MESSAGES = {"session", "lap", "length", "split", "set", "hrv", "record"}
SEMICIRCLE = 180 / 2 ** 31
DATEISH = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d+$|^-$|^$")


def plain(value):
    """A FIT field's value as JSON can hold it."""
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        if isinstance(value, dt.datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, float) and value != value:
        return None
    return value


def safe_name(name: str) -> str:
    """A file's base name without the email address in it."""
    stem, dot, ext = Path(name).name.rpartition(".")
    parts = [p for p in (stem or ext).split("_") if "@" not in p]
    return "_".join(parts) + (dot + ext if stem else "")


def kind(name: str) -> str:
    stem = Path(name).name.rsplit(".", 1)[0]
    words = [p for p in stem.split("_") if "@" not in p and not DATEISH.match(p)]
    return "_".join(words) or "file"


def area(path: str) -> str:
    for part in path.split("/")[:-1]:
        if part.startswith("DI-Connect-"):
            return part[len("DI-Connect-"):].lower()
    parts = path.split("/")
    return parts[-2].lower() if len(parts) > 1 else "root"


def json_items(data):
    items = data if isinstance(data, list) else [data]
    for item in items:
        if isinstance(item, dict) and len(item) == 1 and isinstance(next(iter(item.values())), list):
            yield from next(iter(item.values()))
        else:
            yield item


class Packer:
    def __init__(self, out):
        import fitdecode  # noqa: F401  - fails early, before the archive is read

        self.out = out
        self.counts: dict[str, int] = {}

    def write(self, endpoint: str, rid: str, record, file: str = "") -> None:
        self.out.write(json.dumps({"endpoint": endpoint, "id": rid, "record": record, "file": file},
                                  ensure_ascii=False) + "\n")
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1

    def skip(self, why: str) -> None:
        self.counts[f"skipped: {why}"] = self.counts.get(f"skipped: {why}", 0) + 1

    def json_file(self, path: str, raw: bytes) -> None:
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.skip("unreadable JSON")
            print(f"skipped {safe_name(path)}: not JSON", file=sys.stderr)
            return
        endpoint = f"export/{area(path)}/{kind(path)}"
        for item in json_items(data):
            digest = json.dumps([endpoint, item], sort_keys=True, ensure_ascii=False)
            self.write(endpoint, hashlib.sha256(digest.encode()).hexdigest()[:32], item, safe_name(path))

    def fit_file(self, path: str, raw: bytes) -> None:
        import fitdecode

        key = hashlib.sha256(raw).hexdigest()[:16]
        name = safe_name(path)
        rows: list[tuple[str, dict]] = []
        file_type = None
        try:
            with fitdecode.FitReader(io.BytesIO(raw), check_crc=fitdecode.CrcCheck.WARN) as fit:
                for frame in fit:
                    if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                        continue
                    if frame.name == "file_id":
                        file_type = frame.get_value("type", fallback=None)
                        if file_type not in ("activity", 4):
                            break
                    if frame.name not in FIT_MESSAGES:
                        continue
                    fields = {}
                    for f in frame.fields:
                        if f.name.startswith("unknown") or f.value is None:
                            continue
                        v = plain(f.value)
                        if f.name.startswith("position_") or f.name.endswith(("_lat", "_long")):
                            v = v * SEMICIRCLE if isinstance(v, (int, float)) else v
                        fields[f.name] = v
                    rows.append((frame.name, fields))
        except Exception as e:  # one broken file never stops the rest
            self.skip("broken FIT")
            print(f"skipped {name}: {type(e).__name__}", file=sys.stderr)
            return
        if file_type not in ("activity", 4):
            self.skip(f"FIT {file_type or 'without a type'}")
            return
        seen: dict[str, int] = {}
        for message, fields in rows:
            i = seen[message] = seen.get(message, -1) + 1
            self.write(f"fit/{message}", f"{key}/{message}/{i}", {"fit": key, "index": i, **fields}, name)
        self.counts["FIT activities"] = self.counts.get("FIT activities", 0) + 1

    def zip_file(self, z: zipfile.ZipFile) -> None:
        for info in z.infolist():
            if info.is_dir():
                continue
            lower = info.filename.lower()
            if lower.endswith(".zip"):
                # Inner zips are read from a temporary file: a zip inside a
                # zip cannot be read without seeking through it.
                with tempfile.TemporaryFile() as tmp:
                    with z.open(info) as member:
                        shutil.copyfileobj(member, tmp, 1 << 20)
                    tmp.seek(0)
                    try:
                        with zipfile.ZipFile(tmp) as inner:
                            self.zip_file(inner)
                    except zipfile.BadZipFile:
                        self.skip("broken zip")
            elif lower.endswith(".json"):
                self.json_file(info.filename, z.read(info))
            elif lower.endswith(".fit"):
                self.fit_file(info.filename, z.read(info))
            else:
                self.skip(f".{lower.rsplit('.', 1)[-1]}" if "." in lower else "no extension")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: garmin_pack.py <Garmin export .zip> <output .jsonl.gz>")
    archive, target = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    try:
        with gzip.open(target, "wt", encoding="utf-8") as out:
            packer = Packer(out)
            with zipfile.ZipFile(archive) as z:
                packer.zip_file(z)
    except ImportError:
        target.unlink(missing_ok=True)
        sys.exit("fitdecode is not installed - run this through uv, as the docstring says")
    for what, n in sorted(packer.counts.items()):
        print(f"{n:>10}  {what}")
    print(f"{target}: {target.stat().st_size / 1e6:.1f} MB")
    if not any(k.startswith("export/") for k in packer.counts):
        sys.exit("no JSON found - is that Garmin's data export?")


if __name__ == "__main__":
    main()
