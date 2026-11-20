"""The tools. Each is a plain async function; app.py registers them all.

Two kinds live here. The named tools (notes_search, task_save, ...) cover
what gets asked every day, with small inputs and short text answers a small
local model handles well. api_call reaches everything else a service's API
offers, and api_find says what that is.
"""

from __future__ import annotations

import html
import json
import mimetypes
import re
from typing import Any

from . import core, services
from .core import ToolError, clip
from .services import SERVICES, ask, env

TOOLS: list[Any] = []


def tool(fn: Any) -> Any:
    TOOLS.append(fn)
    return fn


def _strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _obj(value: Any, what: str) -> Any:
    """Small models often send an object as a JSON string. Take both."""
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            return json.loads(value)
        except ValueError:
            raise ToolError(f"{what} must be a JSON object, like {{\"key\": \"value\"}}")
    return value


def _one_line(text: Any, width: int = 220) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


# --- finding your way ---------------------------------------------------------


@tool
async def lab_services() -> str:
    """List the home server's services, which tools reach each one, and how files move in and out. Start here when unsure."""
    lines = ["Services (use the name with api_call and api_find):"]
    for s in SERVICES.values():
        state = "" if s.enabled else "  [not set up yet]"
        mode = " (read only)" if s.read_only else ""
        lines.append(f"- {s.name}: {s.title}, {s.about}{mode}{state}")
    lines += [
        "",
        "Also: warehouse_* tools read the data warehouse (ClickHouse) that collects every service's data; "
        "web_search, web_read and web_download reach the internet; media_download saves video or audio from a link.",
        "",
        "Files: tools that produce a file save it in a scratch workspace on the server (files_list shows it). "
        f"The person downloads one with GET {core.PUBLIC_URL}/files/NAME and uploads one with "
        f"PUT {core.PUBLIC_URL}/files/NAME, both with the same Authorization header as this server. "
        f"Files are deleted after {core.KEEP_SECONDS // 3600} hours.",
    ]
    return "\n".join(lines)


@tool
async def api_find(service: str, keyword: str = "") -> str:
    """Look up how to use a service's API before calling api_call. With no keyword: the service's guide (main endpoints, examples). With a keyword: matching endpoints, e.g. api_find("documents", "tag")."""
    svc = services.get(service)
    word = keyword.strip().lower()
    if not word:
        return svc.guide()
    lines: list[str] = []
    if svc.openapi:
        try:
            for op in await services.operations(svc):
                haystack = f"{op['path']} {op['summary']} {op['id']} {op['tags']}".lower()
                if all(part in haystack for part in word.split()):
                    extra = ""
                    if op["query"]:
                        extra += f" | query: {', '.join(op['query'])}"
                    if op["body"]:
                        extra += f" | body: {', '.join(op['body'])}"
                    lines.append(f"{op['method']} {op['path']}: {op['summary']}{extra}")
        except (ToolError, ValueError) as exc:
            lines.append(f"(could not read the API description: {exc})")
    guide_hits = [line for line in svc.guide().splitlines() if word in line.lower()]
    if len(lines) > 40:
        lines = lines[:40] + [f"... {len(lines) - 40} more; use a narrower keyword"]
    if guide_hits:
        lines += ["", "From the guide:"] + guide_hits[:20]
    return "\n".join(lines) if lines else f"Nothing matches {keyword!r}. Call api_find({svc.name!r}) for the guide."


@tool
async def api_call(
    service: str,
    method: str,
    path: str,
    query: dict[str, Any] | str | None = None,
    body: Any = None,
    form: dict[str, Any] | str | None = None,
    files: dict[str, Any] | str | None = None,
    save_as: str = "",
    max_chars: int = core.DEFAULT_CHARS,
    start: int = 0,
) -> str:
    """Call any endpoint of a lab service's API, already signed in. Use api_find first to learn the path.

    service: a name from lab_services. method: GET, POST, PUT, PATCH or DELETE.
    path: the endpoint, starting with /, relative to the service's API root.
    query: URL parameters. body: a JSON body. form: form fields (for uploads).
    files: upload workspace files, as {"form field": "file name"} or a list of names.
    save_as: save the answer as this workspace file instead of returning it.
    A non-text answer (image, PDF, zip) is always saved to the workspace.
    """
    svc = services.get(service)
    query, body, form, files = _obj(query, "query"), _obj(body, "body"), _obj(form, "form"), _obj(files, "files")
    for what, value in (("query", query), ("form", form), ("files", files)):
        if value is not None and not isinstance(value, dict):
            raise ToolError(f"{what} must be a JSON object")
    opened = []
    upload = []
    try:
        for field_name, names in (files or {}).items():
            for name in names if isinstance(names, list) else [names]:
                file_path = core.work_path(str(name), must_exist=True)
                handle = file_path.open("rb")
                opened.append(handle)
                kind = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
                upload.append((field_name, (file_path.name, handle, kind)))
        reply = await services.call(
            svc, method, path, params=query, json_body=body, data=form,
            files=upload or None, save_as=save_as or None, timeout=600 if upload or save_as else None,
        )
    finally:
        for handle in opened:
            handle.close()
    if reply.saved:
        return f"HTTP {reply.status}. Saved {core.describe(reply.saved)}"
    text = reply.text or ""
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    except ValueError:
        pass
    return f"HTTP {reply.status}\n{clip(text, max_chars, start)}"


# --- the warehouse --------------------------------------------------------------


async def _clickhouse(sql: str) -> dict[str, Any]:
    if not env("CLICKHOUSE_PASSWORD"):
        raise ToolError("the warehouse has no password set on the server yet, so it cannot be used.")
    response = await core.client().post(
        services.CLICKHOUSE_URL,
        params={"default_format": "JSONCompact"},
        content=sql.encode(),
        headers={
            "X-ClickHouse-User": env("CLICKHOUSE_USER") or "labmcp",
            "X-ClickHouse-Key": env("CLICKHOUSE_PASSWORD"),
        },
        timeout=90,
    )
    if response.status_code != 200:
        raise ToolError(f"ClickHouse refused the query: {response.text.strip()[:800]}")
    try:
        return response.json()
    except ValueError:
        return {"meta": [{"name": "result"}], "data": [[response.text.strip()]], "rows": 1}


def _table(result: dict[str, Any], max_rows: int) -> str:
    names = [column["name"] for column in result.get("meta", [])]
    rows = result.get("data", [])
    lines = ["\t".join(names)]
    for row in rows[:max_rows]:
        lines.append("\t".join(_one_line(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v, 300) for v in row))
    if len(rows) > max_rows:
        lines.append(f"[{len(rows) - max_rows} more rows not shown; add LIMIT/OFFSET or aggregate]")
    return "\n".join(lines)


@tool
async def warehouse_tables(search: str = "") -> str:
    """List the data warehouse's tables with their descriptions. The warehouse holds data from every lab service (photos, location, fitness, tasks, messages, searches, 3D prints, logs...). `search` filters by name or description."""
    result = await _clickhouse(
        "SELECT concat(database, '.', name) AS table, total_rows AS rows, comment FROM system.tables "
        "WHERE database NOT IN ('system', 'INFORMATION_SCHEMA', 'information_schema') ORDER BY database, name"
    )
    word = search.strip().lower()
    rows = [r for r in result["data"] if not word or word in f"{r[0]} {r[2]}".lower()]
    if not rows:
        return f"No table matches {search!r}."
    return "\n".join(f"{r[0]} ({r[1] or 0} rows): {_one_line(r[2], 200)}" for r in rows[:300])


@tool
async def warehouse_columns(table: str) -> str:
    """Show a warehouse table's columns, types and descriptions. `table` is database.table, for example ods.vikunja_tasks."""
    database, _, name = table.strip().partition(".")
    if not name or not re.fullmatch(r"\w+", database) or not re.fullmatch(r"\w+", name):
        raise ToolError("give the table as database.table")
    result = await _clickhouse(
        f"SELECT name, type, comment FROM system.columns WHERE database = '{database}' AND table = '{name}' ORDER BY position"
    )
    if not result["data"]:
        raise ToolError(f"no table {table}; see warehouse_tables")
    return "\n".join(f"{r[0]}  {r[1]}  {_one_line(r[2], 160)}".rstrip() for r in result["data"])


@tool
async def warehouse_query(sql: str, max_rows: int = 100) -> str:
    """Run one read-only SQL query (ClickHouse dialect) on the data warehouse and get the rows as tab-separated text. Check warehouse_tables and warehouse_columns first; always use LIMIT or aggregate."""
    result = await _clickhouse(sql.strip().rstrip(";"))
    return clip(_table(result, max(1, min(int(max_rows), 1000))), 30000)


# --- the internet ---------------------------------------------------------------


@tool
async def web_search(query: str, limit: int = 8, language: str = "", category: str = "") -> str:
    """Search the web through the house's own search engine. Returns titles, links and snippets. language: e.g. "ru" or "en". category: general (default), news, images, videos, it, science, map."""
    params: dict[str, Any] = {"q": query, "format": "json"}
    if language:
        params["language"] = language
    if category:
        params["categories"] = category
    reply = await core.send("GET", services.SEARXNG_URL + "/search", params=params, timeout=30)
    if not reply.ok:
        raise ToolError(f"the search engine answered HTTP {reply.status}")
    data = reply.json()
    lines = []
    for answer in data.get("answers", [])[:2]:
        lines.append(f"Answer: {_one_line(answer.get('answer') if isinstance(answer, dict) else answer, 400)}")
    for index, item in enumerate(data.get("results", [])[: max(1, min(int(limit), 30))], 1):
        lines.append(f"{index}. {_one_line(item.get('title'), 160)}\n   {item.get('url')}\n   {_one_line(item.get('content'), 300)}")
    return "\n".join(lines) if lines else "No results."


def _pdf_text(path: Any) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [f"--- page {number} ---\n{page.extract_text() or ''}" for number, page in enumerate(reader.pages, 1)]
    return f"[PDF, {len(reader.pages)} pages]\n" + "\n".join(pages)


@tool
async def web_read(url: str, max_chars: int = core.DEFAULT_CHARS, start: int = 0) -> str:
    """Read a web page (or an online PDF) as plain text. Use after web_search to read a result. For long pages call again with `start`."""
    reply = await core.fetch_public(url, save_binary=False)
    if not reply.ok:
        raise ToolError(f"the site answered HTTP {reply.status}")
    kind = reply.headers.get("content-type", "").lower()
    if "pdf" in kind or url.lower().split("?")[0].endswith(".pdf"):
        saved = await core.fetch_public(url, save_as=core.safe_name(url.split("?")[0].rsplit("/", 1)[-1] or "page.pdf"))
        return clip(_pdf_text(saved.saved), max_chars, start)
    text = reply.text or ""
    if "html" in kind or "<html" in text[:2000].lower():
        import trafilatura

        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
        main = trafilatura.extract(text, include_links=True, include_tables=True, favor_recall=True) or _strip_tags(
            re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
        )
        text = (f"# {_strip_tags(title.group(1))}\n\n" if title else "") + main
    return clip(text, max_chars, start)


@tool
async def web_download(url: str, save_as: str = "") -> str:
    """Download a file from the internet into the workspace. For video or audio pages (YouTube, etc.) use media_download instead."""
    reply = await core.fetch_public(url, save_as=core.safe_name(save_as or url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "download.bin"))
    if not reply.ok or not reply.saved:
        raise ToolError(f"the site answered HTTP {reply.status}")
    return f"Saved {core.describe(reply.saved)}"


@tool
async def media_download(url: str, audio_only: bool = False, save_as: str = "") -> str:
    """Download the video or audio behind a link (YouTube, Instagram, TikTok, X, SoundCloud and others) into the workspace."""
    await core.require_public(url)
    reply = await core.send(
        "POST", services.COBALT_URL + "/",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json_body={"url": url, "downloadMode": "audio" if audio_only else "auto", "filenameStyle": "basic"},
        timeout=120,
    )
    answer = reply.json() if reply.text else {}
    status = answer.get("status")
    if status == "error" or not reply.ok:
        raise ToolError(f"the downloader could not handle this link: {(answer.get('error') or {}).get('code', reply.status)}")
    if status == "picker":
        targets = [(item.get("url"), None) for item in answer.get("picker", [])[:10] if item.get("url")]
    elif status in ("tunnel", "redirect"):
        targets = [(answer.get("url"), answer.get("filename"))]
    else:
        raise ToolError(f"the downloader answered {status!r}, which this tool does not handle")
    saved = []
    for index, (target, filename) in enumerate(targets, 1):
        parsed = core.httpx.URL(target)
        if parsed.path.startswith("/tunnel"):
            # A link back to the downloader itself, by its public name. Fetch it inside the cluster.
            base = core.httpx.URL(services.COBALT_URL)
            reply = await core.send(
                "GET", str(parsed.copy_with(scheme=base.scheme, host=base.host, port=base.port)),
                save_as=core.safe_name(save_as or filename or f"media-{index}.bin"), timeout=3600,
            )
        else:
            name = save_as or filename or parsed.path.rsplit("/", 1)[-1] or f"media-{index}.bin"
            if len(targets) > 1:
                stem, dot, ext = core.safe_name(name).rpartition(".")
                name = f"{stem or ext}-{index}{dot}{ext if stem else ''}"
            reply = await core.fetch_public(target, save_as=core.safe_name(name))
        if not reply.ok or not reply.saved:
            raise ToolError(f"downloading the media failed: HTTP {reply.status}")
        saved.append(core.describe(reply.saved))
    return "Saved:\n" + "\n".join(saved)


# --- notes (Outline) ------------------------------------------------------------


@tool
async def notes_search(query: str, limit: int = 8) -> str:
    """Search the household wiki (Outline) and get matching documents with their ids."""
    data = await ask("notes", "POST", "/documents.search", json_body={"query": query, "limit": max(1, min(int(limit), 25))})
    lines = []
    for hit in data.get("data", []):
        doc = hit.get("document", {})
        lines.append(f"{doc.get('title')}  [id {doc.get('id')}]  updated {str(doc.get('updatedAt'))[:10]}\n   {_one_line(_strip_tags(hit.get('context', '')), 300)}")
    return "\n".join(lines) if lines else "No documents match."


@tool
async def notes_read(id: str, max_chars: int = core.DEFAULT_CHARS, start: int = 0) -> str:
    """Read one wiki document as Markdown, by the id from notes_search."""
    doc = (await ask("notes", "POST", "/documents.info", json_body={"id": id}))["data"]
    return clip(f"# {doc.get('title')}\n\n{doc.get('text', '')}", max_chars, start)


@tool
async def notes_write(title: str = "", text: str = "", id: str = "", collection: str = "", append: bool = False) -> str:
    """Create a wiki document, or change one. With `id`: update that document (append=True adds `text` at the end instead of replacing). Without `id`: create a new one in `collection` (a collection's name or id; lists them if left empty)."""
    if id:
        body: dict[str, Any] = {"id": id}
        if title:
            body["title"] = title
        if text:
            body.update(text=text, append=bool(append))
        doc = (await ask("notes", "POST", "/documents.update", json_body=body))["data"]
        return f"Updated {doc.get('title')!r} [id {doc.get('id')}]"
    collections = (await ask("notes", "POST", "/collections.list", json_body={"limit": 100}))["data"]
    wanted = collection.strip().lower()
    match = [c for c in collections if wanted and wanted in (c["id"].lower(), c["name"].lower())]
    if not match:
        names = ", ".join(f"{c['name']!r}" for c in collections)
        raise ToolError(f"say which collection the new document goes in. Collections: {names}")
    if not title:
        raise ToolError("a new document needs a title")
    doc = (await ask("notes", "POST", "/documents.create", json_body={
        "title": title, "text": text, "collectionId": match[0]["id"], "publish": True,
    }))["data"]
    return f"Created {doc.get('title')!r} [id {doc.get('id')}] in {match[0]['name']!r}"


# --- tasks (Vikunja) --------------------------------------------------------------

_NO_DATE = "0001-01-01"


def _task_line(task: dict[str, Any]) -> str:
    due = str(task.get("due_date") or "")
    parts = [f"#{task.get('id')}", "[done]" if task.get("done") else "[open]", str(task.get("title"))]
    if due and not due.startswith(_NO_DATE):
        parts.append(f"due {due[:16].replace('T', ' ')}")
    parts.append(f"(project {task.get('project_id')})")
    return " ".join(parts)


@tool
async def tasks_list(search: str = "", include_done: bool = False, limit: int = 50) -> str:
    """List tasks from the to-do app (Vikunja), open ones by default, soonest due first."""
    params: dict[str, Any] = {"per_page": max(1, min(int(limit), 200)), "sort_by": "due_date", "order_by": "asc"}
    if search:
        params["s"] = search
    if not include_done:
        params["filter"] = "done = false"
    svc = services.get("tasks")
    reply = await services.call(svc, "GET", "/tasks", params=params)
    if reply.status == 404:  # older servers
        reply = await services.call(svc, "GET", "/tasks/all", params=params)
    if not reply.ok:
        raise ToolError(f"Vikunja answered HTTP {reply.status}: {(reply.text or '')[:300]}")
    tasks = reply.json() or []
    return "\n".join(_task_line(t) for t in tasks) if tasks else "No tasks."


@tool
async def task_save(title: str = "", id: int = 0, project: str = "", description: str = "", due: str = "", done: bool | None = None) -> str:
    """Add a task, or change one (to finish or delete tasks use task_done / task_delete). With `id`: update that task (only the fields given). Without: create it in `project` (name or id; the first project if empty). `due` is a date or date-time like 2026-12-01 or 2026-12-01T18:00:00Z."""
    if due and re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        due += "T12:00:00Z"
    if id:
        task = await ask("tasks", "GET", f"/tasks/{int(id)}")
        if title:
            task["title"] = title
        if description:
            task["description"] = description
        if due:
            task["due_date"] = due
        if done is not None:
            task["done"] = bool(done)
        return "Updated " + _task_line(await ask("tasks", "POST", f"/tasks/{int(id)}", json_body=task))
    if not title:
        raise ToolError("a new task needs a title")
    projects = await ask("tasks", "GET", "/projects", params={"per_page": 200}) or []
    wanted = project.strip().lower()
    match = [p for p in projects if wanted in (str(p["id"]), p["title"].lower())] if wanted else projects[:1]
    if not match:
        raise ToolError(f"no project {project!r}. Projects: {', '.join(repr(p['title']) for p in projects)}")
    body: dict[str, Any] = {"title": title}
    if description:
        body["description"] = description
    if due:
        body["due_date"] = due
    created = await ask("tasks", "PUT", f"/projects/{match[0]['id']}/tasks", json_body=body)
    return f"Created {_task_line(created)} in {match[0]['title']!r}"


def _ids(ids: Any) -> list[int]:
    """One id or several, as numbers, a list, or text like "3, 4 5"."""
    if isinstance(ids, str):
        ids = re.findall(r"\d+", ids)
    elif not isinstance(ids, (list, tuple)):
        ids = [ids]
    try:
        found = list(dict.fromkeys(int(i) for i in ids))
    except (TypeError, ValueError):
        raise ToolError("ids are task numbers, like [12, 15]")
    if not found:
        raise ToolError("give at least one task id, like [12, 15]")
    if len(found) > 100:
        raise ToolError("at most 100 tasks in one call")
    return found


@tool
async def task_done(ids: list[int] | int | str, done: bool = True) -> str:
    """Mark one or many tasks as done in a single call, e.g. ids=[12, 15, 19]. done=False reopens them."""
    lines = []
    for task_id in _ids(ids):
        try:
            task = await ask("tasks", "GET", f"/tasks/{task_id}")
            task["done"] = bool(done)
            lines.append(_task_line(await ask("tasks", "POST", f"/tasks/{task_id}", json_body=task)))
        except ToolError as exc:
            lines.append(f"#{task_id} FAILED: {_one_line(exc, 160)}")
    return "\n".join(lines)


@tool
async def task_delete(ids: list[int] | int | str) -> str:
    """Delete one or many tasks for good, in a single call, e.g. ids=[12, 15]. Only when the person asked to delete; to finish a task use task_done."""
    lines = []
    for task_id in _ids(ids):
        reply = await services.call(services.get("tasks"), "DELETE", f"/tasks/{task_id}")
        lines.append(f"#{task_id} deleted" if reply.ok else f"#{task_id} FAILED: HTTP {reply.status} {_one_line(reply.text, 120)}")
    return "\n".join(lines)


# --- links (Karakeep) -------------------------------------------------------------


@tool
async def links_search(query: str, limit: int = 10) -> str:
    """Search the saved links and notes (Karakeep)."""
    data = await ask("links", "GET", "/bookmarks/search", params={"q": query, "limit": max(1, min(int(limit), 50))})
    lines = []
    for mark in data.get("bookmarks", []):
        content = mark.get("content") or {}
        title = mark.get("title") or content.get("title") or content.get("url") or _one_line(content.get("text"), 80)
        tags = ", ".join(t.get("name", "") for t in mark.get("tags", []))
        lines.append(f"{_one_line(title, 150)}  [id {mark.get('id')}]\n   {content.get('url', '')}  saved {str(mark.get('createdAt'))[:10]}"
                     + (f"  tags: {tags}" if tags else "")
                     + (f"\n   note: {_one_line(mark.get('note'))}" if mark.get("note") else ""))
    return "\n".join(lines) if lines else "No saved links match."


@tool
async def link_save(url: str, note: str = "") -> str:
    """Save a link to the read-later app (Karakeep), optionally with a note."""
    body: dict[str, Any] = {"type": "link", "url": url}
    if note:
        body["note"] = note
    mark = await ask("links", "POST", "/bookmarks", json_body=body)
    return f"Saved [id {mark.get('id')}]"


# --- photos (Immich) --------------------------------------------------------------


@tool
async def photos_search(query: str, limit: int = 10) -> str:
    """Search the photo library (Immich) by what a photo shows, in plain words: "dog on a beach", "birthday cake"."""
    data = await ask("photos", "POST", "/search/smart", json_body={"query": query, "size": max(1, min(int(limit), 50))})
    lines = []
    for asset in (data.get("assets") or {}).get("items", []):
        exif = asset.get("exifInfo") or {}
        place = ", ".join(x for x in (exif.get("city"), exif.get("country")) if x)
        lines.append(f"{asset.get('originalFileName')}  [id {asset.get('id')}]  {asset.get('type', '').lower()}  "
                     f"{str(asset.get('localDateTime'))[:16].replace('T', ' ')}"
                     + (f"  {place}" if place else "")
                     + (f"\n   {_one_line(exif.get('description'))}" if exif.get("description") else ""))
    return "\n".join(lines) if lines else "No photos match."


@tool
async def photo_get(id: str, original: bool = False) -> str:
    """Save a photo from the library into the workspace: a screen-size JPEG by default, or the original file."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", id):
        raise ToolError("the id is the one in square brackets from photos_search")
    svc = services.get("photos")
    if original:
        reply = await services.call(svc, "GET", f"/assets/{id}/original", save_as=None, timeout=600)
    else:
        reply = await services.call(svc, "GET", f"/assets/{id}/thumbnail", params={"size": "preview"}, save_as=f"photo-{id[:8]}.jpg")
    if not reply.ok or not reply.saved:
        raise ToolError(f"Immich answered HTTP {reply.status}: {(reply.text or '')[:200]}")
    return f"Saved {core.describe(reply.saved)}"


# --- documents (Paperless) -----------------------------------------------------------


@tool
async def documents_search(query: str, limit: int = 10) -> str:
    """Search the scanned documents (Paperless: letters, bills, contracts, manuals) by their text."""
    data = await ask("documents", "GET", "/documents/", params={"query": query, "page_size": max(1, min(int(limit), 50))})
    lines = [f"{data.get('count', 0)} documents match."]
    for doc in data.get("results", []):
        hit = (doc.get("__search_hit__") or {}).get("highlights", "")
        lines.append(f"{doc.get('title')}  [id {doc.get('id')}]  dated {str(doc.get('created'))[:10]}"
                     + (f"\n   {_one_line(_strip_tags(hit), 300)}" if hit else ""))
    return "\n".join(lines)


@tool
async def document_read(id: int, max_chars: int = core.DEFAULT_CHARS, start: int = 0) -> str:
    """Read the text of one scanned document, by the id from documents_search."""
    doc = await ask("documents", "GET", f"/documents/{int(id)}/")
    return clip(f"# {doc.get('title')}\ndated {str(doc.get('created'))[:10]}\n\n{doc.get('content', '')}", max_chars, start)


@tool
async def document_download(id: int, original: bool = False) -> str:
    """Save a scanned document's PDF into the workspace (the archived, searchable version by default)."""
    reply = await services.call(
        services.get("documents"), "GET", f"/documents/{int(id)}/download/",
        params={"original": "true"} if original else None, save_as=None, timeout=300,
    )
    if not reply.ok or not reply.saved:
        raise ToolError(f"Paperless answered HTTP {reply.status}: {(reply.text or '')[:200]}")
    return f"Saved {core.describe(reply.saved)}"


@tool
async def document_upload(file: str, title: str = "") -> str:
    """Add a workspace file (PDF, image, office document) to the scanned documents. Paperless reads its text and files it."""
    path = core.work_path(file, must_exist=True)
    with path.open("rb") as handle:
        reply = await services.call(
            services.get("documents"), "POST", "/documents/post_document/",
            data={"title": title} if title else None,
            files=[("document", (path.name, handle, mimetypes.guess_type(path.name)[0] or "application/octet-stream"))],
            timeout=300,
        )
    if not reply.ok:
        raise ToolError(f"Paperless answered HTTP {reply.status}: {(reply.text or '')[:300]}")
    return f"Handed {path.name} to Paperless; it appears in documents_search in a minute or two."


# --- recipes (Mealie) -------------------------------------------------------------


@tool
async def recipes_search(query: str = "", limit: int = 10) -> str:
    """Search the recipe book (Mealie)."""
    data = await ask("recipes", "GET", "/recipes", params={"search": query, "perPage": max(1, min(int(limit), 50)), "page": 1})
    lines = [f"{item.get('name')}  [slug {item.get('slug')}]" + (f"\n   {_one_line(item.get('description'))}" if item.get("description") else "")
             for item in data.get("items", [])]
    return "\n".join(lines) if lines else "No recipes match."


@tool
async def recipe_read(slug: str) -> str:
    """Read one recipe (ingredients and steps), by the slug from recipes_search."""
    if not re.fullmatch(r"[\w-]+", slug):
        raise ToolError("the slug is the one in square brackets from recipes_search")
    recipe = await ask("recipes", "GET", f"/recipes/{slug}")
    lines = [f"# {recipe.get('name')}", _one_line(recipe.get("description"), 500)]
    for label, key in (("Makes", "recipeYield"), ("Total time", "totalTime")):
        if recipe.get(key):
            lines.append(f"{label}: {recipe[key]}")
    lines.append("\nIngredients:")
    lines += [f"- {i.get('display') or i.get('note') or ''}" for i in recipe.get("recipeIngredient", [])]
    lines.append("\nSteps:")
    lines += [f"{n}. {step.get('text', '').strip()}" for n, step in enumerate(recipe.get("recipeInstructions", []), 1)]
    return "\n".join(lines)


# --- the house (Home Assistant) --------------------------------------------------------


@tool
async def home_states(search: str = "", limit: int = 100) -> str:
    """List the house's devices and sensors with their current state (Home Assistant). `search` filters by name or entity id, e.g. "light", "temperature", "kitchen"."""
    states = await ask("home", "GET", "/states")
    word = search.strip().lower()
    lines = []
    for state in sorted(states, key=lambda s: s.get("entity_id", "")):
        attributes = state.get("attributes") or {}
        name = attributes.get("friendly_name", "")
        if word and word not in f"{state.get('entity_id')} {name}".lower():
            continue
        unit = attributes.get("unit_of_measurement", "")
        lines.append(f"{state.get('entity_id')} = {state.get('state')}{' ' + unit if unit else ''}  ({name})")
    shown = lines[: max(1, min(int(limit), 500))]
    if len(lines) > len(shown):
        shown.append(f"[{len(lines) - len(shown)} more; narrow the search]")
    return "\n".join(shown) if shown else "Nothing matches."


@tool
async def home_call(domain: str, service: str, data: dict[str, Any] | str | None = None) -> str:
    """Control the house: call a Home Assistant service, e.g. domain="light", service="turn_on", data={"entity_id": "light.kitchen", "brightness_pct": 40}."""
    if not re.fullmatch(r"\w+", domain) or not re.fullmatch(r"\w+", service):
        raise ToolError("domain and service are single words, like light and turn_on")
    changed = await ask("home", "POST", f"/services/{domain}/{service}", json_body=_obj(data, "data") or {})
    lines = [f"{s.get('entity_id')} = {s.get('state')}" for s in changed or [] if isinstance(s, dict)]
    return "Done." + ("\n" + "\n".join(lines[:40]) if lines else "")


# --- money (Firefly III) ----------------------------------------------------------


@tool
async def money_accounts(type: str = "asset") -> str:
    """List the household's accounts with balances (Firefly III). type: asset (default), expense, revenue, liabilities or all."""
    data = await ask("money", "GET", "/accounts", params={"type": type, "limit": 200})
    lines = []
    for account in data.get("data", []):
        a = account.get("attributes", {})
        lines.append(f"{a.get('name')}  [id {account.get('id')}]  {a.get('current_balance')} {a.get('currency_code')}  ({a.get('type')})")
    return "\n".join(lines) if lines else "No accounts."


@tool
async def money_transactions(start: str = "", end: str = "", search: str = "", limit: int = 50) -> str:
    """List transactions from the household's books. Dates are YYYY-MM-DD. With `search`: find by text instead (Firefly's search syntax also works, e.g. "category:Groceries amount_more:50")."""
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 200))}
    if search:
        data = await ask("money", "GET", "/search/transactions", params={**params, "query": search})
    else:
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        data = await ask("money", "GET", "/transactions", params={**params, "type": "all"})
    lines = []
    for journal in data.get("data", []):
        for split in journal.get("attributes", {}).get("transactions", []):
            amount = str(split.get("amount", ""))
            amount = amount.rstrip("0").rstrip(".") if "." in amount else amount
            lines.append(
                f"{str(split.get('date'))[:10]}  {split.get('type')}  {amount} {split.get('currency_code')}  "
                f"{split.get('source_name')} -> {split.get('destination_name')}  {_one_line(split.get('description'), 100)}"
                + (f"  [{split.get('category_name')}]" if split.get("category_name") else "")
                + f"  (id {journal.get('id')})"
            )
    return "\n".join(lines) if lines else "No transactions."


# --- workspace files and PDFs -----------------------------------------------------------


@tool
async def files_list() -> str:
    """List the files in the server's scratch workspace (downloads, results of other tools, files the person uploaded)."""
    core.sweep()
    paths = sorted((p for p in core.WORK.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    return "\n".join(core.describe(p) for p in paths) if paths else "The workspace is empty."


@tool
async def file_text(name: str, max_chars: int = core.DEFAULT_CHARS, start: int = 0) -> str:
    """Read a workspace file as text. PDFs are read page by page; other files are read as plain text."""
    path = core.work_path(name, must_exist=True)
    if path.suffix.lower() == ".pdf":
        return clip(_pdf_text(path), max_chars, start)
    raw = path.read_bytes()[: core.MAX_TEXT_BYTES]
    if b"\x00" in raw[:4096]:
        raise ToolError(f"{path.name} is not a text file. For a scan or image, use pdf_ocr or document_upload.")
    return clip(raw.decode("utf-8", "replace"), max_chars, start)


@tool
async def file_write(name: str, text: str) -> str:
    """Write a text file into the workspace (to upload somewhere or hand to the person)."""
    core.sweep()
    path = core.work_path(name)
    path.write_text(text)
    return f"Wrote {core.describe(path)}"


@tool
async def file_delete(name: str) -> str:
    """Delete a file from the workspace."""
    core.work_path(name, must_exist=True).unlink()
    return "Deleted."


def _page_numbers(spec: str, total: int) -> list[int]:
    pages: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        first, _, last = part.partition("-")
        try:
            a = int(first)
            b = int(last) if last else a
        except ValueError:
            raise ToolError('pages look like "1-3,5,8-10"')
        if not 1 <= a <= b <= total:
            raise ToolError(f"pages must be between 1 and {total}")
        pages += range(a, b + 1)
    if not pages:
        raise ToolError('say which pages, like "1-3,5"')
    return pages


@tool
async def pdf_merge(files: list[str], save_as: str = "merged.pdf") -> str:
    """Join workspace PDFs into one, in the order given."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for name in files:
        writer.append(str(core.work_path(name, must_exist=True)))
    out = core.work_path(save_as)
    with out.open("wb") as handle:
        writer.write(handle)
    return f"Saved {core.describe(out)}"


@tool
async def pdf_split(file: str, pages: str, save_as: str = "") -> str:
    """Take pages out of a workspace PDF into a new PDF. pages: "1-3,5,8-10" (also reorders: pages come out in the order written)."""
    from pypdf import PdfReader, PdfWriter

    source = core.work_path(file, must_exist=True)
    reader = PdfReader(str(source))
    writer = PdfWriter()
    for number in _page_numbers(pages, len(reader.pages)):
        writer.add_page(reader.pages[number - 1])
    out = core.work_path(save_as or f"{source.stem}-pages.pdf")
    with out.open("wb") as handle:
        writer.write(handle)
    return f"Saved {core.describe(out)}"


@tool
async def pdf_ocr(file: str, languages: str = "eng+rus", save_as: str = "") -> str:
    """Make a scanned PDF searchable by recognising its text (Stirling-PDF). languages: Tesseract codes joined by +, e.g. eng+rus+srp. Then read it with file_text."""
    source = core.work_path(file, must_exist=True)
    with source.open("rb") as handle:
        reply = await services.call(
            services.get("pdf"), "POST", "/misc/ocr-pdf",
            data={"languages": [code for code in languages.split("+") if code], "ocrType": "skip-text", "ocrRenderType": "hocr"},
            files=[("fileInput", (source.name, handle, "application/pdf"))],
            save_as=core.safe_name(save_as or f"{source.stem}-ocr.pdf"), timeout=900,
        )
    if not reply.ok:
        detail = (reply.text or "")[:300]
        raise ToolError(f"Stirling-PDF answered HTTP {reply.status}: {detail}")
    return f"Saved {core.describe(reply.saved)}"
