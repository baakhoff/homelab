"""The tools against a pretend lab: every upstream is an httpx mock.

Run from images/lab-mcp:  PYTHONPATH=. uv run --with-requirements requirements.txt --with pytest --with reportlab pytest -q
"""

import asyncio
import io
import json
import zipfile
import os

import httpx
import pytest

os.environ.update(
    OUTLINE_API_KEY="k", VIKUNJA_API_TOKEN="k", KARAKEEP_API_KEY="k", IMMICH_API_KEY="k", PAPERLESS_API_TOKEN="k",
    MEALIE_API_TOKEN="k", HOME_ASSISTANT_TOKEN="k", CLICKHOUSE_PASSWORD="k", MANYFOLD_CLIENT_ID="i",
    MANYFOLD_CLIENT_SECRET="s", BMM_API_TOKEN="k",
)

from lab_mcp import core, services, tools  # noqa: E402

SEEN: list[httpx.Request] = []
PHOTO = "11111111-2222-3333-4444-555555555555"
PHOTO2 = "22222222-2222-3333-4444-555555555555"
ANNA, BORIS, NOBODY = (f"{n}aaaaaaa-0000-0000-0000-000000000000" for n in "abc")


def picture(width: int, height: int) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), "navy").save(out, "JPEG")
    return out.getvalue()


def lab(request: httpx.Request) -> httpx.Response:
    SEEN.append(request)
    host, path = request.url.host.split(".")[0], request.url.path
    body = json.loads(request.content) if request.headers.get("content-type", "").startswith("application/json") else None
    if host == "outline":
        assert request.headers["authorization"] == "Bearer k"
        if path == "/api/documents.search":
            return httpx.Response(200, json={"data": [{"context": "the <b>boiler</b> manual", "document": {"id": "d1", "title": "Boiler", "updatedAt": "2026-11-01T10:00:00Z"}}]})
        if path == "/api/documents.info":
            return httpx.Response(200, json={"data": {"id": body["id"], "title": "Boiler", "text": "Pressure 1.5 bar."}})
        if path == "/api/collections.list":
            return httpx.Response(200, json={"data": [{"id": "c1", "name": "House"}]})
        if path == "/api/documents.create":
            assert body["collectionId"] == "c1" and body["publish"] is True
            return httpx.Response(200, json={"data": {"id": "d2", "title": body["title"]}})
        if path == "/api/documents.update":
            assert body == {"id": "d1", "text": "more", "append": True}
            return httpx.Response(200, json={"data": {"id": "d1", "title": "Boiler"}})
    if host == "vikunja":
        if path == "/api/v1/tasks" and request.method == "GET":
            assert request.url.params["filter"] == "done = false"
            return httpx.Response(200, json=[{"id": 7, "title": "Buy salt", "done": False, "due_date": "0001-01-01T00:00:00Z", "project_id": 1}])
        if path == "/api/v1/projects":
            return httpx.Response(200, json=[{"id": 1, "title": "Inbox"}, {"id": 2, "title": "House"}])
        if path == "/api/v1/projects/2/tasks" and request.method == "PUT":
            assert body == {"title": "Fix tap", "due_date": "2026-12-01T12:00:00Z"}
            return httpx.Response(201, json={"id": 8, "project_id": 2, "done": False, **body})
        if path == "/api/v1/tasks/7" and request.method == "GET":
            return httpx.Response(200, json={"id": 7, "title": "Buy salt", "done": False, "project_id": 1, "priority": 3})
        if path == "/api/v1/tasks/7" and request.method == "DELETE":
            return httpx.Response(200, json={"message": "Successfully deleted."})
        if path == "/api/v1/tasks/99":
            return httpx.Response(404, json={"message": "The task does not exist."})
        if path == "/api/v1/tasks/7" and request.method == "POST":
            assert body["done"] is True and body["priority"] == 3
            return httpx.Response(200, json=body)
        if path == "/api/v1/docs.json":
            return httpx.Response(200, json={"paths": {"/labels": {"get": {"summary": "Get all labels", "parameters": [{"in": "query", "name": "s"}]},
                                                                  "put": {"summary": "Create a label", "parameters": [{"in": "body", "schema": {"$ref": "#/definitions/Label"}}]}}},
                                             "definitions": {"Label": {"properties": {"title": {}, "hex_color": {}}}}})
        if path == "/api/v1/labels" and request.method == "PUT":
            return httpx.Response(201, json={"id": 3, **body})
    if host == "karakeep":
        if path == "/api/v1/bookmarks/search":
            return httpx.Response(200, json={"bookmarks": [{"id": "b1", "createdAt": "2026-10-01T00:00:00Z", "tags": [{"name": "diy"}], "content": {"type": "link", "url": "https://example.org/a", "title": "A guide"}}]})
        if path == "/api/v1/bookmarks" and request.method == "POST":
            assert body == {"type": "link", "url": "https://example.org/b", "note": "later"}
            return httpx.Response(201, json={"id": "b2"})
    if host == "immich-server":
        assert request.headers["x-api-key"] == "k"
        if path == "/api/search/smart":
            return httpx.Response(200, json={"assets": {"items": [{"id": PHOTO, "originalFileName": "IMG_1.jpg", "type": "IMAGE", "localDateTime": "2026-07-04T12:30:00.000Z", "exifInfo": {"city": "Novi Sad", "country": "Serbia"}}]}})
        if path == f"/api/assets/{PHOTO}/thumbnail":
            return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"})
        if path == "/api/people":
            return httpx.Response(200, json={"hasNextPage": False, "people": [{"id": ANNA, "name": "Anna"}, {"id": BORIS, "name": "Boris"}, {"id": NOBODY, "name": ""}]})
        if path.endswith("/statistics"):
            return httpx.Response(200, json={"assets": {ANNA: 12, BORIS: 40, NOBODY: 3}[path.split("/")[3]]})
        if path == "/api/search/metadata":
            assert body["personIds"] == [ANNA] and body["type"] == "IMAGE"
            return httpx.Response(200, json={"assets": {"nextPage": "2", "items": [{"id": PHOTO2, "originalFileName": "IMG_2.jpg", "localDateTime": "2026-08-01T09:00:00.000Z"}]}})
        if path == "/api/faces":
            if request.url.params["id"] != PHOTO2:
                return httpx.Response(200, json=[])
            box = {"imageWidth": 200, "imageHeight": 100}
            return httpx.Response(200, json=[
                {**box, "boundingBoxX1": 0, "boundingBoxY1": 0, "boundingBoxX2": 90, "boundingBoxY2": 90, "person": {"id": BORIS}},
                {**box, "boundingBoxX1": 150, "boundingBoxY1": 20, "boundingBoxX2": 170, "boundingBoxY2": 40, "person": {"id": ANNA}}])
        if path == f"/api/assets/{PHOTO2}/thumbnail":
            return httpx.Response(200, content=picture(400, 200), headers={"content-type": "image/jpeg"})
        if path == f"/api/assets/{PHOTO2}/original":
            return httpx.Response(200, content=b"heic bytes", headers={"content-type": "image/heic", "content-disposition": 'attachment; filename="IMG_2.HEIC"'})
    if host == "paperless":
        assert request.headers["authorization"] == "Token k"
        if path == "/api/documents/" and request.method == "GET":
            return httpx.Response(200, json={"count": 1, "results": [{"id": 5, "title": "Washer warranty", "created": "2025-03-02", "__search_hit__": {"highlights": "<span>warranty</span> until 2028"}}]})
        if path == "/api/documents/5/":
            return httpx.Response(200, json={"id": 5, "title": "Washer warranty", "created": "2025-03-02", "content": "Valid until 2028."})
        if path == "/api/documents/5/download/":
            return httpx.Response(200, content=b"%PDF-1.4 x", headers={"content-type": "application/pdf", "content-disposition": 'attachment; filename="washer warranty.pdf"'})
        if path == "/api/documents/post_document/":
            assert b'name="document"; filename="note.txt"' in request.content and b'name="title"' in request.content
            return httpx.Response(200, json="task-uuid")
    if host == "mealie":
        if path == "/api/recipes":
            return httpx.Response(200, json={"items": [{"slug": "borscht", "name": "Borscht", "description": "Beet soup"}]})
        if path == "/api/recipes/borscht":
            return httpx.Response(200, json={"name": "Borscht", "recipeYield": "6", "recipeIngredient": [{"display": "3 beets"}], "recipeInstructions": [{"text": "Boil."}]})
    if host == "home-assistant":
        if path == "/api/states":
            return httpx.Response(200, json=[{"entity_id": "light.kitchen", "state": "off", "attributes": {"friendly_name": "Kitchen"}},
                                             {"entity_id": "sensor.t", "state": "21.5", "attributes": {"friendly_name": "Hall temperature", "unit_of_measurement": "°C"}}])
        if path == "/api/services/light/turn_on":
            assert body == {"entity_id": "light.kitchen"}
            return httpx.Response(200, json=[{"entity_id": "light.kitchen", "state": "on"}])
    if host == "firefly-broker":
        assert "authorization" not in request.headers
        if path == "/v1/accounts":
            return httpx.Response(200, json={"data": [{"id": "1", "attributes": {"name": "Main", "current_balance": "100.50", "currency_code": "EUR", "type": "asset"}}]})
        if path == "/v1/transactions":
            assert request.url.params["start"] == "2026-11-01"
            return httpx.Response(200, json={"data": [{"id": "9", "attributes": {"transactions": [{"date": "2026-11-02T00:00:00+01:00", "type": "withdrawal", "amount": "12.500000000000", "currency_code": "EUR", "source_name": "Main", "destination_name": "Shop", "description": "Bread", "category_name": "Groceries"}]}}]})
    if host == "bmm" and path == "/api/v1/auth/me":
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"via": "token", "scopes": ["audit:read"]})
    if host == "manyfold":
        if path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        if path == "/models":
            assert request.headers["authorization"] == "Bearer tok" and "manyfold" in request.headers["accept"]
            return httpx.Response(200, json={"totalItems": 0})
    if host == "kube-prometheus-stack-prometheus" and path == "/api/v1/alerts":
        return httpx.Response(200, json={"status": "success", "data": {"alerts": []}})
    if host == "clickhouse":
        assert request.headers["x-clickhouse-user"] == "labmcp"
        sql = request.content.decode()
        if "system.tables" in sql:
            return httpx.Response(200, json={"meta": [{"name": "table"}, {"name": "rows"}, {"name": "comment"}], "data": [["ods.vikunja_tasks", "42", "Tasks"], ["ods.logs", "9", "Logs"]]})
        if "system.columns" in sql:
            assert "database = 'ods' AND table = 'vikunja_tasks'" in sql
            return httpx.Response(200, json={"meta": [], "data": [["id", "UInt64", "the task"]]})
        if "boom" in sql:
            return httpx.Response(403, text="Code: 164. DB::Exception: Cannot execute query in readonly mode")
        return httpx.Response(200, json={"meta": [{"name": "n"}], "data": [[1], [2], [3]], "rows": 3})
    if host == "searxng":
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json={"results": [{"title": "Kubernetes", "url": "https://kubernetes.io/", "content": "Production-grade"}]})
    if host == "cobalt":
        if request.method == "POST":
            assert body["url"] == "https://video.example/watch?v=1" and body["downloadMode"] == "audio"
            return httpx.Response(200, json={"status": "tunnel", "url": "https://cobalt.lab.example/tunnel?id=1&sig=2", "filename": "song.mp3"})
        if path == "/tunnel":
            assert request.url.params["sig"] == "2"
            return httpx.Response(200, content=b"ID3 audio", headers={"content-type": "audio/mpeg"})
    if host == "stirling-pdf" and path == "/api/v1/misc/ocr-pdf":
        assert request.content.count(b'name="languages"') == 2 and b'name="fileInput"' in request.content
        return httpx.Response(200, content=b"%PDF-1.4 ocr", headers={"content-type": "application/pdf"})
    if host == "news":
        if path == "/old":
            return httpx.Response(302, headers={"location": "/article"})
        return httpx.Response(200, html="<html><head><title>Big news</title></head><body><nav>menu</nav><article><p>"
                              + "The council approved the new bridge today after a long debate. " * 8 + "</p></article></body></html>")
    return httpx.Response(404, json={"message": f"no route {request.method} {host}{path}"})


@pytest.fixture(autouse=True)
def pretend_lab(tmp_path, monkeypatch):
    SEEN.clear()
    monkeypatch.setattr(core, "WORK", tmp_path)

    async def everything_is_public(url):
        return httpx.URL(url)

    monkeypatch.setattr(core, "require_public", everything_is_public)
    core.set_client(httpx.AsyncClient(transport=httpx.MockTransport(lab)))
    yield tmp_path
    core.set_client(None)


def run(coro):
    return asyncio.run(coro)


def test_notes():
    assert "Boiler  [id d1]" in run(tools.notes_search("boiler")) and "the boiler manual" in run(tools.notes_search("boiler"))
    assert "Pressure 1.5 bar." in run(tools.notes_read("d1"))
    assert "Created 'Pump' [id d2] in 'House'" == run(tools.notes_write(title="Pump", text="x", collection="house"))
    assert "Updated" in run(tools.notes_write(id="d1", text="more", append=True))
    with pytest.raises(core.ToolError, match="Collections: 'House'"):
        run(tools.notes_write(title="Pump"))


def test_tasks():
    assert run(tools.tasks_list()) == "#7 [open] Buy salt (project 1)"
    assert "Created #8 [open] Fix tap due 2026-12-01 12:00 (project 2) in 'House'" == run(tools.task_save(title="Fix tap", project="house", due="2026-12-01"))
    assert run(tools.task_save(id=7, done=True)).startswith("Updated #7 [done]")
    assert run(tools.task_done([7, 99])).splitlines()[0].startswith("#7 [done] Buy salt")
    assert "#99 FAILED" in run(tools.task_done("7, 99"))
    assert run(tools.task_delete([7, 99])).splitlines() == ["#7 deleted", '#99 FAILED: HTTP 404 {"message":"The task does not exist."}']
    with pytest.raises(core.ToolError):
        run(tools.task_done([]))


def test_links_photos_documents(pretend_lab):
    assert "A guide  [id b1]" in run(tools.links_search("guide")) and "tags: diy" in run(tools.links_search("guide"))
    assert run(tools.link_save("https://example.org/b", "later")) == "Saved [id b2]"
    assert "Novi Sad, Serbia" in run(tools.photos_search("beach"))
    assert "photo-11111111.jpg" in run(tools.photo_get(PHOTO))
    assert (pretend_lab / "photo-11111111.jpg").read_bytes() == b"\xff\xd8jpeg"
    assert "warranty until 2028" in run(tools.documents_search("warranty"))
    assert "Valid until 2028." in run(tools.document_read(5))
    assert "washer warranty.pdf" in run(tools.document_download(5))
    run(tools.file_write("note.txt", "hello"))
    assert "Handed note.txt" in run(tools.document_upload("note.txt", "A note"))


def test_photo_people_and_export(pretend_lab):
    from PIL import Image

    people = run(tools.photos_people()).splitlines()
    assert people == [f"Boris  [id {BORIS}]  40 photos", f"Anna  [id {ANNA}]  12 photos"]
    assert "(no name)" in run(tools.photos_people(include_unnamed=True))
    listed = run(tools.photos_by_person("anna"))
    assert f"[id {PHOTO2}]" in listed and "face 150,20,170,40 of 200x100" in listed and "page=2" in listed
    with pytest.raises(tools.ToolError, match="People: Anna, Boris"):
        run(tools.photos_by_person("Zed"))

    # A face crop: Anna's box, scaled from the 200x100 the faces were found
    # on to the 400x200 picture, squared with the margin. The photo with no
    # face is reported and left out.
    answer = run(tools.photos_export(f"{PHOTO2}, {PHOTO}", crop="face", person="Anna", margin=0.5))
    assert "Anna-faces.zip" in answer and "1 faces of Anna" in answer and f"{PHOTO} FAILED" in answer
    with zipfile.ZipFile(pretend_lab / "Anna-faces.zip") as archive:
        assert archive.namelist() == [f"{PHOTO2}.jpg"]
        assert Image.open(io.BytesIO(archive.read(f"{PHOTO2}.jpg"))).size == (80, 80)

    answer = run(tools.photos_export([PHOTO, PHOTO2], save_as="set"))
    assert "set.zip" in answer and "2 photos" in answer
    with zipfile.ZipFile(pretend_lab / "set.zip") as archive:
        assert sorted(archive.namelist()) == [f"{PHOTO}.jpg", f"{PHOTO2}.jpg"]
    run(tools.photos_export(PHOTO2, size="original", save_as="raw.zip"))
    with zipfile.ZipFile(pretend_lab / "raw.zip") as archive:
        assert archive.namelist() == [f"{PHOTO2}.heic"]
    assert sorted(p.name for p in pretend_lab.iterdir()) == ["Anna-faces.zip", "raw.zip", "set.zip"]
    with pytest.raises(tools.ToolError, match="not \"original\""):
        run(tools.photos_export(PHOTO2, size="original", crop="face"))


def test_recipes_home_money():
    assert "[slug borscht]" in run(tools.recipes_search("soup"))
    assert "- 3 beets" in run(tools.recipe_read("borscht")) and "1. Boil." in run(tools.recipe_read("borscht"))
    assert run(tools.home_states("temperature")) == "sensor.t = 21.5 °C  (Hall temperature)"
    assert "light.kitchen = on" in run(tools.home_call("light", "turn_on", {"entity_id": "light.kitchen"}))
    assert "Main  [id 1]  100.50 EUR" in run(tools.money_accounts())
    assert "2026-11-02  withdrawal  12.5 EUR  Main -> Shop  Bread  [Groceries]  (id 9)" == run(tools.money_transactions(start="2026-11-01"))


def test_warehouse():
    assert run(tools.warehouse_tables("task")) == "ods.vikunja_tasks (42 rows): Tasks"
    assert "id  UInt64  the task" == run(tools.warehouse_columns("ods.vikunja_tasks"))
    assert run(tools.warehouse_query("SELECT 1;", max_rows=2)).splitlines() == ["n", "1", "2", "[1 more rows not shown; add LIMIT/OFFSET or aggregate]"]
    with pytest.raises(core.ToolError, match="readonly"):
        run(tools.warehouse_query("boom"))
    with pytest.raises(core.ToolError):
        run(tools.warehouse_columns("ods.x'; DROP"))


def test_web(pretend_lab):
    assert "1. Kubernetes\n   https://kubernetes.io/" in run(tools.web_search("k8s"))
    page = run(tools.web_read("https://news.example/old"))
    assert page.startswith("# Big news") and "approved the new bridge" in page and "menu" not in page
    assert "song.mp3" in run(tools.media_download("https://video.example/watch?v=1", audio_only=True))
    assert (pretend_lab / "song.mp3").read_bytes() == b"ID3 audio"
    assert SEEN[-1].url.host == "cobalt.cobalt.svc.cluster.local"


def test_api_call_and_find():
    assert "PUT /labels: Create a label | body: title, hex_color" in run(tools.api_find("tasks", "label"))
    assert run(tools.api_call("tasks", "PUT", "/labels", body={"title": "x"})) == 'HTTP 201\n{"id":3,"title":"x"}'
    assert run(tools.api_call("tasks", "PUT", "/labels", body='{"title": "x"}')) == 'HTTP 201\n{"id":3,"title":"x"}'
    assert run(tools.api_call("models", "GET", "/models")) == 'HTTP 200\n{"totalItems":0}'
    assert run(tools.api_call("metrics", "GET", "/alerts")).startswith("HTTP 200")
    assert '"scopes":["audit:read"]' in run(tools.api_call("social", "GET", "/auth/me"))
    assert "POST /posts/validate" in run(tools.api_find("social"))
    assert run(tools.api_call("tasks", "GET", "/nope")).startswith("HTTP 404")
    assert "Endpoints" in run(tools.api_find("notes"))
    for bad in [("metrics", "POST", "/admin/tsdb/snapshot"), ("tasks", "GET", "/../admin"), ("tasks", "GET", "http://evil/"), ("nothing", "GET", "/")]:
        with pytest.raises(core.ToolError):
            run(tools.api_call(*bad))


def test_disabled_service(monkeypatch):
    monkeypatch.delenv("OUTLINE_API_KEY")
    with pytest.raises(core.ToolError, match="no key set"):
        run(tools.notes_search("x"))
    assert "notes: Outline" in run(tools.lab_services()) and "[not set up yet]" in run(tools.lab_services())


def test_files_and_pdfs(pretend_lab):
    from reportlab.pdfgen import canvas

    for name, words in (("a.pdf", ["alpha one", "alpha two"]), ("b.pdf", ["beta one"])):
        sheet = canvas.Canvas(str(pretend_lab / name))
        for word in words:
            sheet.drawString(72, 720, word)
            sheet.showPage()
        sheet.save()
    assert "merged.pdf" in run(tools.pdf_merge(["a.pdf", "b.pdf"]))
    text = run(tools.file_text("merged.pdf"))
    assert "[PDF, 3 pages]" in text and "beta one" in text
    run(tools.pdf_split("merged.pdf", "3,1", "pick.pdf"))
    picked = run(tools.file_text("pick.pdf"))
    assert picked.index("beta one") < picked.index("alpha one") and "alpha two" not in picked
    assert "a-ocr.pdf" in run(tools.pdf_ocr("a.pdf", "eng+rus"))
    assert "pick.pdf" in run(tools.files_list())
    run(tools.file_delete("pick.pdf"))
    with pytest.raises(core.ToolError, match="no file named"):
        run(tools.file_text("pick.pdf"))
    with pytest.raises(core.ToolError):
        run(tools.pdf_split("merged.pdf", "9"))
    assert core.work_path("../../etc/passwd").parent == pretend_lab
    assert core.clip("x" * 500, 200).endswith("[300 more characters; call again with start=200]")


def test_private_addresses_are_refused(monkeypatch):
    monkeypatch.undo()
    for url in ("http://127.0.0.1/", "http://192.168.1.1/admin", "file:///etc/passwd", "http://[::1]/"):
        with pytest.raises(core.ToolError):
            run(core.require_public(url))
