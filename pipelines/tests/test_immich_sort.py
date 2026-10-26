"""Tests for pipelines/dags/immich_sort.py: how Claude's answers become
types, rows and the album, without Immich, Claude or Kafka. Airflow,
pendulum and requests are stood in for when they are not installed. Run
from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import io
import sys
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
try:
    import requests  # noqa: F401
except ImportError:
    _requests = types.ModuleType("requests")
    _requests.Session = object
    _requests.HTTPError = type("HTTPError", (Exception,), {})
    sys.modules["requests"] = _requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
import immich_sort as s  # noqa: E402

ASSET = {
    "id": "a1",
    "type": "VIDEO",
    "duration": "0:00:12.345000",
    "originalFileName": "VID-20240101-WA0003.mp4",
    "fileCreatedAt": "2024-01-01T10:00:00.000Z",
    "localDateTime": "2024-01-01T11:00:00.000Z",
    "isFavorite": False,
    "people": [{"name": "Ana"}, {"name": ""}],
    "exifInfo": {"make": None, "model": None, "exifImageWidth": 720, "exifImageHeight": 1280,
                 "city": "Belgrade", "state": "Belgrade", "country": "Serbia",
                 "latitude": 44.8, "longitude": 20.46},
}


def test_type_name_tidies_and_reuses():
    existing = {"Memes": "t1", "Screenshots": "t2"}
    assert s.type_name("  memes ", existing) == "Memes"
    assert s.type_name("Meme", existing) == "Memes"
    assert s.type_name("screenshot", existing) == "Screenshots"
    assert s.type_name("food/drink", existing) == "Food drink"
    assert s.type_name("pets", existing) == "Pets"
    assert s.type_name(" / ", existing) is None


def test_tool_makes_types_until_the_cap():
    open_ = s.tool(["Food"])["input_schema"]
    assert "enum" not in open_["properties"]["type"]
    assert open_["required"] == ["description", "type", "to_delete"]
    full = [f"T{i}" for i in range(s.MAX_TYPES)]
    assert s.tool(full)["input_schema"]["properties"]["type"]["enum"] == sorted(full)


def test_a_favourite_is_never_set_aside():
    assert s.set_aside({"to_delete": True}, {"isFavorite": False})
    assert not s.set_aside({"to_delete": True}, {"isFavorite": True})
    assert not s.set_aside({"to_delete": "yes"}, {})
    assert not s.set_aside({}, {})


def test_facts_name_no_person_and_no_place():
    text = s.facts(ASSET, ["Memes"])
    assert "VID-20240101-WA0003.mp4" in text
    assert "video, 0:00:12 long" in text
    assert "Camera: none recorded" in text
    assert "Has people the owner named: yes" in text
    assert "Existing types: Memes" in text
    for private in ("Ana", "Belgrade", "Serbia", "44.8"):
        assert private not in text


def test_photo_record_has_the_place_from_immich():
    rec = s.photo_record(ASSET, {"description": "A cat on a sofa.", "to_delete": True}, "Memes", False)
    assert rec["asset_id"] == "a1" and rec["file_name"] == "VID-20240101-WA0003.mp4"
    assert rec["kind"] == "video" and rec["duration"] == "0:00:12.345000"
    assert (rec["city"], rec["country"], rec["latitude"], rec["longitude"]) == ("Belgrade", "Serbia", 44.8, 20.46)
    assert rec["type"] == "Memes" and rec["description"] == "A cat on a sofa."
    assert rec["to_delete"] is True and rec["set_aside"] is False


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, replies):
        self.replies, self.bodies = list(replies), []

    def post(self, url, json, timeout):
        self.bodies.append(json)
        return self.replies.pop(0)


def test_ask_waits_out_a_rate_limit(monkeypatch):
    monkeypatch.setattr(s.time, "sleep", lambda _: None)
    answer = {"description": "A receipt.", "type": "Receipts", "to_delete": False}
    session = FakeSession([
        FakeResponse(429, headers={"retry-after": "1"}),
        FakeResponse(200, {"content": [{"type": "tool_use", "input": answer}],
                           "usage": {"input_tokens": 900, "output_tokens": 60}}),
    ])
    got = s._ask(session, b"jpeg", "image/jpeg", "facts", [])
    assert got == (answer, {"input_tokens": 900, "output_tokens": 60})
    body = session.bodies[0]
    assert body["model"] == s.MODEL and body["tool_choice"] == {"type": "tool", "name": "sort"}
    assert body["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_ask_skips_a_picture_claude_refuses():
    assert s._ask(FakeSession([FakeResponse(400, {})]), b"x", "image/jpeg", "facts", []) is None


def test_shrink_fits_the_square():
    PIL = pytest.importorskip("PIL.Image")
    big = io.BytesIO()
    PIL.new("RGB", (1440, 1080)).save(big, "WEBP")
    data, media_type = s._shrink(big.getvalue(), "image/webp")
    assert media_type == "image/jpeg"
    assert max(PIL.open(io.BytesIO(data)).size) == s.SIDE
