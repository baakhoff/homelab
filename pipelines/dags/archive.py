"""Files, onto the NAS, with a row for each in the warehouse - the helpers.

No DAG is defined here, so any DAG file can import this one: ingest_files is
in files.py beside it, and a DAG that fetches files itself uses store().

The warehouse holds rows; the files those rows talk about - a photo in a
chat, an attachment in a mail, a scan dropped in from the workstation - are
on the NAS, in tank/archive, mounted at /archive in the scheduler pod
(clusters/lab/airflow/archive.yaml). Each file is stored once, under its
SHA-256:

    /archive/objects/2d/2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881

and every place it came from is one record on Kafka topic raw.files, in the
usual envelope (ingest.py): endpoint the source, id that source's own key
for what the file belongs to. ods.files is the index, and a row anywhere
else in the warehouse finds its file through it. The same photo forwarded
to five chats is one object and five rows.

Two ways in:

- A DAG that fetches files itself writes each to tmp_path(), calls store(),
  and sends the record with Files.send().
- Anything else is dropped into the inbox, /archive/inbox, from the
  workstation over SMB (pipelines/files.md): a folder per batch, or a loose
  file. The ingest_files DAG, through sweep(), takes a batch once nothing in it has
  changed for QUIET, stores each file, sends its record, and removes it
  from the inbox. A batch may carry a manifest, files.jsonl, naming the
  source and key of each file in it - the pack tools write one. A file it
  does not list, and every file of a batch without one, goes under endpoint
  `inbox`, keyed by the path it was dropped under.

Nothing here changes or deletes an object. Its name is its hash, so the
file under a name is that file; ZFS's own checksums catch a disk that says
otherwise.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Secrets and identity numbers masked before anything leaves for Kafka -
# sensitive.py beside this file. Airflow puts the DAG folder, pipelines/, on
# the import path, not dags/, so the directory this file is in goes on first.
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sensitive import mask_record  # noqa: E402

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
TOPIC = "raw.files"
ROOT = Path(os.environ.get("ARCHIVE_ROOT", "/archive"))
MANIFEST = "files.jsonl"
# A batch is taken only once nothing in it has changed for this long, so a
# copy still running is not taken half-way. Change time, not modification
# time: robocopy and `cp -p` keep a file's original modification time.
QUIET = timedelta(minutes=30)
# A run stops taking files after this long; the next run carries on.
BUDGET = timedelta(minutes=45)
# Records are delivered, and their files removed from the inbox, in groups
# of this many, so a failed run redoes at most one group.
FLUSH_EVERY = 200
# What file managers leave behind. Deleted with the batch, never stored.
JUNK = {".DS_Store", "Thumbs.db", "desktop.ini"}
_ENDPOINT = re.compile(r"^[a-z][a-z0-9_/-]*$")


def object_path(sha256: str) -> Path:
    return ROOT / "objects" / sha256[:2] / sha256


def tmp_path() -> Path:
    """A fresh name in the archive's own tmp/, for a file about to be
    stored: on the same dataset as objects/, so store() is a rename."""
    d = ROOT / "tmp"
    d.mkdir(exist_ok=True)
    return d / uuid.uuid4().hex


def _hash(path: Path) -> tuple[str, int]:
    h, size = hashlib.sha256(), 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _place(path: Path, sha256: str, link: bool) -> None:
    target = object_path(sha256)
    if target.exists():
        if not link:
            path.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not link:
            os.rename(path, target)
            return
        try:
            os.link(path, target)
        except PermissionError:
            # The node refuses to hard-link a file this pod may not write
            # (fs.protected_hardlinks) - one copied in read-only, say. A copy
            # then, renamed into place whole.
            tmp = tmp_path()
            shutil.copyfile(path, tmp)
            os.rename(tmp, target)
    except FileExistsError:  # the same file, stored a moment ago
        if not link:
            path.unlink()


def store(path: Path) -> dict:
    """Move a file in tmp/ under its hash. Its sha256, size and object path."""
    sha256, size = _hash(path)
    _place(path, sha256, link=False)
    return {"sha256": sha256, "size": size, "object": object_path(sha256).relative_to(ROOT).as_posix()}


def _link(path: Path) -> dict:
    """The same for a file in the inbox, which stays until its record is
    delivered: a hard link, on the same dataset, so nothing is copied."""
    sha256, size = _hash(path)
    _place(path, sha256, link=True)
    return {"sha256": sha256, "size": size, "object": object_path(sha256).relative_to(ROOT).as_posix()}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class Files:
    """raw.files, in the envelope every source uses."""

    def __init__(self, run_id: str):
        from confluent_kafka import Producer

        self.run_id = run_id
        self.extracted_at = datetime.now(timezone.utc).isoformat()
        self.errors: list[str] = []
        self.counts: dict[str, int] = {}
        self.producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "compression.type": "zstd",
            "linger.ms": 50,
        })

    def send(self, endpoint: str, rid: str, record: dict) -> None:
        record, flags = mask_record(record)
        value = json.dumps({
            "source": "files",
            "endpoint": endpoint,
            "extracted_at": self.extracted_at,
            "run_id": self.run_id,
            "id": rid,
            "record": record,
            **flags,
        }, ensure_ascii=False).encode()
        while True:
            try:
                self.producer.produce(TOPIC, key=f"{endpoint}:{rid}".encode(), value=value,
                                      on_delivery=self._delivered)
                break
            except BufferError:
                self.producer.poll(1)
        self.producer.poll(0)
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1

    def _delivered(self, err, _msg):
        if err is not None:
            self.errors.append(str(err))

    def flush(self) -> None:
        left = self.producer.flush(60)
        if left or self.errors:
            raise RuntimeError(f"{left} undelivered, errors: {self.errors[:3]}")


def _manifest(batch: Path) -> dict[str, dict]:
    """files.jsonl as path -> entry. Each line:

        {"file": "<path in the batch>", "endpoint": "<source>", "id": "<its key>",
         "record": {...anything else to keep, such as the original name...}}
    """
    path = batch / MANIFEST
    if not path.is_file():
        return {}
    entries = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            e = json.loads(line)
            if not _ENDPOINT.match(e.get("endpoint", "")) or not e.get("id") or not e.get("file"):
                raise RuntimeError(f"{path}, line {n}: needs file, endpoint and id")
            entries[e["file"]] = e
    return entries


def _quiet(paths: list[Path]) -> bool:
    newest = max(p.stat().st_ctime for p in paths)
    return time.time() - newest > QUIET.total_seconds()


def _take(batch: Path, inbox: Path, files: Files, started: float) -> bool:
    """Store a batch, send its records, empty it from the inbox. False when
    the budget ran out first; the rest waits for the next run."""
    if batch.is_dir():
        paths = sorted(p for p in batch.rglob("*") if p.is_file() and not p.is_symlink())
        manifest = _manifest(batch)
    elif batch.name in JUNK:
        batch.unlink()
        return True
    else:
        paths, manifest = [batch], {}
    pending: list[Path] = []

    def deliver():
        files.flush()
        for p in pending:
            p.unlink()
        pending.clear()

    for p in paths:
        if time.monotonic() - started > BUDGET.total_seconds():
            deliver()
            return False
        rel = p.relative_to(batch).as_posix() if batch.is_dir() else p.name
        if p.name in JUNK or (rel == MANIFEST and batch.is_dir()):
            continue
        stat = p.stat()
        record = {
            **_link(p),
            "name": p.name,
            "mime_type": mimetypes.guess_type(p.name)[0],
            "modified_at": _iso(stat.st_mtime),
        }
        entry = manifest.get(rel)
        if entry:
            files.send(entry["endpoint"], str(entry["id"]), {**record, **entry.get("record", {})})
        else:
            files.send("inbox", p.relative_to(inbox).as_posix(), {**record, "batch": batch.name})
        pending.append(p)
        if len(pending) >= FLUSH_EVERY:
            deliver()
    deliver()
    if batch.is_dir():
        for p in batch.rglob("*"):
            if p.is_file() and (p.name in JUNK or p == batch / MANIFEST):
                p.unlink()
        # Deepest first. A folder that is not empty - something was copied
        # in after the batch was taken - stays, and the next run takes it.
        dirs = sorted((d for d in batch.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True)
        for d in dirs + [batch]:
            try:
                d.rmdir()
            except OSError:
                pass
    return True


def sweep(files: Files) -> None:
    """Take every batch in the inbox that has gone quiet, oldest name first."""
    inbox = ROOT / "inbox"
    if not inbox.is_dir():
        raise RuntimeError(f"no {inbox} - the NAS folders, pipelines/files.md")
    # What a fetching DAG left in tmp/ when it died mid-file.
    for p in (ROOT / "tmp").glob("*"):
        if time.time() - p.stat().st_ctime > 86400:
            p.unlink()

    started = time.monotonic()
    waiting = []
    for batch in sorted(inbox.iterdir()):
        if batch.name.startswith(".") or batch.is_symlink():
            continue
        if not _quiet([batch, *batch.rglob("*")] if batch.is_dir() else [batch]):
            waiting.append(batch.name)
            continue
        if not _take(batch, inbox, files, started):
            print("budget spent; the next run carries on")
            break
    print(f"to {TOPIC}: {files.counts or 'nothing new'}"
          + (f"; still being copied: {', '.join(waiting)}" if waiting else ""))
