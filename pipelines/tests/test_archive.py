"""Tests for pipelines/dags/archive.py, on an archive in a temporary folder.
Airflow, pendulum and Kafka are not needed: stand-ins take their place.
Run from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import hashlib
import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

# Stand-ins for what the DAG file imports at the top, before importing it.
_sdk = types.ModuleType("airflow.sdk")
_sdk.dag = lambda **kw: (lambda f: f)
# A task is not run when the DAG is defined.
_sdk.task = lambda **kw: (lambda f: (lambda *a, **k: None))
sys.modules.setdefault("airflow", types.ModuleType("airflow"))
sys.modules.setdefault("airflow.sdk", _sdk)
_pendulum = types.ModuleType("pendulum")
_pendulum.datetime = lambda *a, **kw: None
_pendulum.duration = lambda **kw: None
sys.modules.setdefault("pendulum", _pendulum)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
import archive  # noqa: E402


class FakeFiles:
    def __init__(self):
        self.sent: list[tuple[str, str, dict]] = []
        self.flushed = 0

    def send(self, endpoint, rid, record):
        self.sent.append((endpoint, rid, record))

    def flush(self):
        self.flushed += 1


@pytest.fixture
def root(tmp_path, monkeypatch):
    for d in ("inbox", "objects", "tmp"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(archive, "ROOT", tmp_path)
    return tmp_path


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_store_moves_under_hash_once(root):
    for _ in range(2):
        p = archive.tmp_path()
        p.write_bytes(b"photo")
        got = archive.store(p)
        assert not p.exists()
    assert got == {"sha256": sha(b"photo"), "size": 5, "object": f"objects/{sha(b'photo')[:2]}/{sha(b'photo')}"}
    assert (root / got["object"]).read_bytes() == b"photo"
    assert list((root / "tmp").iterdir()) == []


def test_batch_without_manifest(root):
    batch = root / "inbox" / "receipts"
    (batch / "2026").mkdir(parents=True)
    (batch / "2026" / "a.pdf").write_bytes(b"A")
    (batch / "b.jpg").write_bytes(b"B")
    (batch / "Thumbs.db").write_bytes(b"junk")
    files = FakeFiles()
    assert archive._take(batch, root / "inbox", files, time.monotonic())
    sent = {rid: (endpoint, rec) for endpoint, rid, rec in files.sent}
    assert set(sent) == {"receipts/2026/a.pdf", "receipts/b.jpg"}
    endpoint, rec = sent["receipts/2026/a.pdf"]
    assert endpoint == "inbox"
    assert rec["sha256"] == sha(b"A") and rec["name"] == "a.pdf"
    assert rec["mime_type"] == "application/pdf" and rec["batch"] == "receipts"
    assert (root / rec["object"]).read_bytes() == b"A"
    assert not batch.exists()


def test_manifest_names_source_and_key(root):
    batch = root / "inbox" / "proton-2026-10"
    (batch / "m1").mkdir(parents=True)
    (batch / "m1" / "1").write_bytes(b"invoice")
    (batch / "stray.txt").write_bytes(b"x")
    (batch / "files.jsonl").write_text(json.dumps({
        "file": "m1/1", "endpoint": "proton", "id": "m1/1",
        "record": {"name": "invoice.pdf", "mime_type": "application/pdf"},
    }) + "\n")
    files = FakeFiles()
    archive._take(batch, root / "inbox", files, time.monotonic())
    by_endpoint = {endpoint: (rid, rec) for endpoint, rid, rec in files.sent}
    assert set(by_endpoint) == {"proton", "inbox"}
    rid, rec = by_endpoint["proton"]
    assert rid == "m1/1" and rec["name"] == "invoice.pdf" and rec["sha256"] == sha(b"invoice")
    assert by_endpoint["inbox"][0] == "proton-2026-10/stray.txt"
    assert not batch.exists()


def test_bad_manifest_line_fails(root):
    batch = root / "inbox" / "bad"
    batch.mkdir()
    (batch / "f").write_bytes(b"x")
    (batch / "files.jsonl").write_text(json.dumps({"file": "f", "endpoint": "Bad Name", "id": "1"}) + "\n")
    with pytest.raises(RuntimeError, match="line 1"):
        archive._take(batch, root / "inbox", FakeFiles(), time.monotonic())
    assert (batch / "f").exists()


def test_same_file_twice_is_one_object(root):
    for name in ("one", "two"):
        (root / "inbox" / name).mkdir()
        (root / "inbox" / name / "same.jpg").write_bytes(b"same")
    files = FakeFiles()
    for name in ("one", "two"):
        archive._take(root / "inbox" / name, root / "inbox", files, time.monotonic())
    assert [rid for _, rid, _ in files.sent] == ["one/same.jpg", "two/same.jpg"]
    assert len(list((root / "objects").rglob("*.*"))) == 0
    assert len([p for p in (root / "objects").rglob("*") if p.is_file()]) == 1


def test_loose_file(root):
    p = root / "inbox" / "scan.png"
    p.write_bytes(b"scan")
    files = FakeFiles()
    archive._take(p, root / "inbox", files, time.monotonic())
    assert files.sent[0][:2] == ("inbox", "scan.png")
    assert not p.exists()


def test_budget_spent_leaves_the_rest(root, monkeypatch):
    batch = root / "inbox" / "big"
    batch.mkdir()
    for i in range(3):
        (batch / f"{i}.bin").write_bytes(bytes([i]))
    monkeypatch.setattr(archive, "BUDGET", archive.timedelta(seconds=-1))
    files = FakeFiles()
    assert not archive._take(batch, root / "inbox", files, time.monotonic())
    assert files.sent == [] and len(list(batch.iterdir())) == 3


def test_quiet(root):
    p = root / "inbox" / "new.txt"
    p.write_bytes(b"x")
    assert not archive._quiet([p])
    old = time.time() - 3600
    os.utime(p, (old, old))  # robocopy keeps the old time: still not quiet
    assert not archive._quiet([p])
