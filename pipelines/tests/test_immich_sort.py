"""Tests for pipelines/dags/immich_sort.py: how Claude's answers become
types, rows and the albums, without Immich, Claude or Kafka. Airflow,
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
    assert s.type_name("to Delete", existing) is None
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


class FakeImmich:
    """Immich's API for the tag and album calls: answers each (method, path)
    from routes - a body, or a function of the request's body - and keeps
    every call."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, timeout, json=None, params=None):
        path = url.removeprefix(s.IMMICH)
        self.calls.append((method, path, json))
        body = self.routes[(method, path)]
        reply = FakeResponse(200, body(json) if callable(body) else body, {"content-type": "application/json"})
        reply.content = b"{}"
        return reply


def immich_with(routes):
    immich = s._Immich.__new__(s._Immich)
    immich.s = FakeImmich(routes)
    return immich


def added(body):
    return [{"id": i, "success": True} for i in body["ids"]]


def test_bulk_adds_a_thousand_at_a_time():
    sizes = []
    immich = immich_with({("PUT", "/albums/al/assets"): lambda body: sizes.append(len(body["ids"])) or added(body)})
    assert immich.bulk("/albums/al/assets", [f"a{i}" for i in range(2500)]) is True
    assert sizes == [1000, 1000, 500]
    assert immich.bulk("/albums/al/assets", []) is True and len(sizes) == 3


def test_bulk_takes_a_duplicate_and_a_gone_picture_but_no_other_refusal():
    # Immich 3.3.5 answers a picture deleted or locked since it was listed
    # with no_permission: every picture here is the key owner's own.
    immich = immich_with({
        ("PUT", "/tags/t/assets"): [{"id": "a1", "success": False, "error": "duplicate"}],
        ("PUT", "/albums/al/assets"): [{"id": "a1", "success": True},
                                       {"id": "a2", "success": False, "error": "no_permission"}],
        ("PUT", "/albums/other/assets"): [{"id": "a1", "success": False, "error": "unknown"}],
    })
    assert immich.bulk("/tags/t/assets", ["a1"]) is True
    assert immich.bulk("/albums/al/assets", ["a1", "a2"]) is False
    with pytest.raises(RuntimeError, match="unknown"):
        immich.bulk("/albums/other/assets", ["a1"])


def test_a_new_type_album_starts_with_the_pictures_the_tag_has():
    pages = [
        {"assets": {"items": [{"id": "p1", "ownerId": "me"}, {"id": "shared", "ownerId": "partner"}],
                    "nextCursor": "2"}},
        {"assets": {"items": [{"id": "p2", "ownerId": "me"}, {"id": "bin", "ownerId": "me", "isTrashed": True}],
                    "nextCursor": None}},
    ]
    immich = immich_with({
        ("GET", "/users/me"): {"id": "me"},
        ("POST", "/albums"): {"id": "al"},
        ("POST", "/search/metadata"): lambda body: pages.pop(0),
    })
    assert immich.type_album("Food", "t1") == "al"
    calls = immich.s.calls
    searches = [body for _, path, body in calls if path == "/search/metadata"]
    assert searches[0]["filter"]["tagIds"] == {"any": ["t1"]}
    assert searches[0]["filter"]["visibility"] == {"in": ["timeline", "archive"]}
    assert "withExif" not in searches[0] and searches[1]["cursor"] == "2"
    # Listed first, then made with its pictures in one call: never an
    # empty album left behind by a failure in between.
    assert calls[-1][:2] == ("POST", "/albums")
    made = calls[-1][2]
    assert made["albumName"] == "Food" and made["assetIds"] == ["p1", "p2"] and s.MARK in made["description"]
    assert not any(method == "PUT" for method, _, _ in calls)


def test_only_the_sortings_own_albums_are_used_and_each_type_gets_one():
    mine = f"Pictures of the type Food, from {s.MARK}."
    immich = immich_with({
        ("GET", "/albums"): [
            {"albumName": "Food", "id": "sorting-food", "description": mine, "shared": True},
            {"albumName": "Pets", "id": "owners-pets", "description": "Our cats", "shared": False},
            {"albumName": "Family", "id": "owners-family", "description": None, "shared": True},
        ],
        ("GET", "/users/me"): {"id": "me"},
        ("POST", "/search/metadata"): {"assets": {"items": [], "nextCursor": None}},
        ("POST", "/albums"): lambda body: {"id": "new-" + body["albumName"].lower()},
    })
    got = immich.type_albums({"Food": "t1", "Pets": "t2", "To delete": "t3"})
    assert got == {"Food": "sorting-food", "Pets": "new-pets"}
    assert [body["albumName"] for method, path, body in immich.s.calls if (method, path) == ("POST", "/albums")] == ["Pets"]


def test_unsorted_leaves_out_the_typed_and_asks_for_the_facts():
    immich = immich_with({
        ("GET", "/users/me"): {"id": "me"},
        ("POST", "/search/metadata"): {"assets": {"items": [{"id": "p1", "ownerId": "me"}], "nextCursor": None}},
    })
    assert [a["id"] for a in immich.unsorted(["t1", "t2"], 10)] == ["p1"]
    body = immich.s.calls[-1][2]
    assert body["filter"]["tagIds"] == {"none": ["t1", "t2"]}
    assert body["withExif"] and body["withPeople"]
    immich.unsorted([], 10)
    assert "tagIds" not in immich.s.calls[-1][2]["filter"]


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


def test_asset_record():
    assert s.asset_record({
        "id": "a", "originalFileName": "TG_20210601_120000_16256bcae130.jpg", "type": "IMAGE",
        "createdAt": "2026-11-01T20:00:00.000Z", "fileCreatedAt": "2021-06-01T10:00:00.000Z",
    }) == {"file_name": "TG_20210601_120000_16256bcae130.jpg", "kind": "image",
           "uploaded_at": "2026-11-01T20:00:00.000Z", "taken_at": "2021-06-01T10:00:00.000Z",
           "status": "active", "duplicate_group": None}


def test_asset_changes():
    found = {"new": {"id": "new"}, "same": {"id": "same"}, "flagged": {"id": "flagged", "duplicateId": "g"}}
    known = {"same": "", "flagged": "", "deleted": "", "copy": "g"}
    changed, now = s.asset_changes(known, found)
    assert dict(changed) == {
        "new": s.asset_record(found["new"]),
        "flagged": s.asset_record(found["flagged"]),
        "deleted": {"status": "deleted"},
        "copy": {"status": "duplicate"},
    }
    assert now == {"new": "", "same": "", "flagged": "g"}
    assert s.asset_changes(now, found)[0] == []
