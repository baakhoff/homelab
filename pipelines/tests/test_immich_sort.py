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
    for _name in ("HTTPError", "ConnectionError", "Timeout"):
        setattr(_requests, _name, type(_name, (Exception,), {}))
    sys.modules["requests"] = _requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
import immich_sort as s  # noqa: E402

ASSET = {
    "id": "a1",
    "type": "VIDEO",
    "duration": 3_725_400,
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
    long_ = {"Very long type name the owner made in Immich by hand": "t3"}
    assert s.type_name("very long type name the owner made in immich by hand", long_) == next(iter(long_))


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
    assert "video, 1:02:05 long" in text
    assert "Camera: none recorded" in text
    assert "Has people the owner named: yes" in text
    assert "Existing types: Memes" in text
    for private in ("Ana", "Belgrade", "Serbia", "44.8"):
        assert private not in text


def test_photo_record_has_the_place_from_immich():
    rec = s.photo_record(ASSET, {"description": "A cat on a sofa.", "to_delete": True}, "Memes", False)
    assert rec["asset_id"] == "a1" and rec["file_name"] == "VID-20240101-WA0003.mp4"
    assert rec["kind"] == "video" and rec["duration_ms"] == 3_725_400
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
        FakeResponse(529),
        FakeResponse(200, {"content": [{"type": "tool_use", "input": answer}], "stop_reason": "tool_use",
                           "usage": {"input_tokens": 900, "output_tokens": 60}}),
    ])
    got = s._ask(session, b"jpeg", "image/jpeg", "facts", [])
    assert got == (answer, {"input_tokens": 900, "output_tokens": 60})
    body = session.bodies[0]
    assert body["model"] == s.MODEL and body["tool_choice"] == {"type": "tool", "name": "sort"}
    assert body["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_ask_skips_a_picture_claude_cannot_read():
    bad = FakeResponse(400, {"error": {"type": "invalid_request_error", "message": "Could not process image"}})
    assert s._ask(FakeSession([bad]), b"x", "image/jpeg", "facts", []) == (None, {})


def test_ask_fails_the_run_at_the_spend_limit():
    limit = FakeResponse(400, {"error": {"type": "invalid_request_error",
                                         "message": "You have reached your specified API usage limits."}})
    with pytest.raises(RuntimeError, match="usage limits"):
        s._ask(FakeSession([limit]), b"x", "image/jpeg", "facts", [])


def test_ask_counts_the_tokens_of_a_cut_off_answer():
    cut = FakeResponse(200, {"content": [{"type": "tool_use", "input": {"description": "A"}}],
                             "stop_reason": "max_tokens", "usage": {"input_tokens": 900, "output_tokens": 400}})
    assert s._ask(FakeSession([cut]), b"x", "image/jpeg", "facts", []) == (None, {"input_tokens": 900, "output_tokens": 400})


def test_shrink_without_pillow_sends_the_preview_as_it_is(monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    assert s._shrink(b"webp", "image/webp") == (b"webp", "image/webp")


# Runs with Pillow there: uv run --with pytest --with pillow pytest pipelines/tests
def test_shrink_fits_the_square():
    PIL = pytest.importorskip("PIL.Image")
    big = io.BytesIO()
    PIL.new("RGB", (1440, 1080)).save(big, "WEBP")
    data, media_type = s._shrink(big.getvalue(), "image/webp")
    assert media_type == "image/jpeg"
    assert max(PIL.open(io.BytesIO(data)).size) == s.SIDE
