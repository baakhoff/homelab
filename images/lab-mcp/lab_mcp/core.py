"""Shared pieces: the log line, the file workspace and the HTTP client."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
from mcp.server.mcpserver.exceptions import ToolError as _ExpectedToolError

WORK = Path(os.environ.get("WORK_DIR", "/work"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://mcp.lab.baakhoff.com").rstrip("/")
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", str(1 << 30)))
MAX_TEXT_BYTES = 5 << 20
KEEP_SECONDS = int(os.environ.get("KEEP_HOURS", "48")) * 3600
DEFAULT_CHARS = 12000


class ToolError(_ExpectedToolError):
    """An error whose text is meant for the model to read and act on. The
    library passes this class's message to the client and hides any other."""


def log(**fields: Any) -> None:
    """One JSON line on stdout. The cluster's collectors carry it to raw.logs."""
    print(json.dumps({"event": "lab-mcp", **fields}, ensure_ascii=False, default=str), flush=True)


def clip(text: str, max_chars: int = DEFAULT_CHARS, start: int = 0) -> str:
    """A window of `text`, saying how to ask for the rest."""
    max_chars = max(200, min(int(max_chars), 100_000))
    start = max(0, int(start))
    part = text[start : start + max_chars]
    rest = len(text) - (start + len(part))
    if rest > 0:
        part += f"\n\n[{rest} more characters; call again with start={start + len(part)}]"
    return part


# --- the file workspace -----------------------------------------------------
#
# One flat directory of scratch files. Tools that produce a file put it here
# and tools that take a file read it from here; the person moves files in and
# out over HTTP at /files/<name>. Nothing in it is meant to last.

_UNSAFE = re.compile(r"[^\w.() \-]+", re.UNICODE)


def safe_name(name: str) -> str:
    cleaned = _UNSAFE.sub("_", Path(str(name).replace("\\", "/")).name).strip(". ")
    if not cleaned:
        raise ToolError(f"not a usable file name: {name!r}")
    return cleaned[:150]


def work_path(name: str, must_exist: bool = False) -> Path:
    path = WORK / safe_name(name)
    if must_exist and not path.is_file():
        have = ", ".join(sorted(p.name for p in WORK.iterdir() if p.is_file())[:30]) or "none"
        raise ToolError(f"no file named {path.name!r} in the workspace. Files there: {have}")
    return path


def sweep() -> None:
    """Drop workspace files older than KEEP_HOURS."""
    cutoff = time.time() - KEEP_SECONDS
    for path in WORK.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def describe(path: Path) -> str:
    size = path.stat().st_size
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            break
        size /= 1024
    shown = f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
    return f"{path.name} ({shown}); the person can fetch it at {PUBLIC_URL}/files/{path.name}"


# --- HTTP ---------------------------------------------------------------------

_client: httpx.AsyncClient | None = None
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10), follow_redirects=False)
    return _client


def set_client(new: httpx.AsyncClient | None) -> None:
    """Tests swap in a client with a mock transport."""
    global _client
    _client = new


class Reply:
    """What came back: a status, and either text or a file saved in the workspace."""

    def __init__(self, status: int, headers: httpx.Headers, text: str | None, saved: Path | None):
        self.status = status
        self.headers = headers
        self.text = text
        self.saved = saved

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        try:
            return json.loads(self.text or "null")
        except ValueError:
            raise ToolError(f"expected JSON, got: {(self.text or '')[:300]}")


_TEXTUAL = ("json", "text/", "xml", "yaml", "javascript", "x-www-form-urlencoded")


def _name_from(headers: httpx.Headers, url: httpx.URL, fallback: str) -> str:
    found = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", headers.get("content-disposition", ""), re.I)
    if found:
        return unquote(found.group(1))
    tail = url.path.rstrip("/").rsplit("/", 1)[-1]
    return tail if "." in tail else fallback


async def send(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    data: dict[str, Any] | None = None,
    files: list[tuple[str, tuple[str, Any, str]]] | None = None,
    save_as: str | None = None,
    save_binary: bool = True,
    timeout: float | None = None,
) -> Reply:
    """One request. A textual answer, and any error, comes back as text;
    anything else, or any success when `save_as` is set, is streamed into
    the workspace."""
    kwargs: dict[str, Any] = {"headers": headers or {}, "params": params or None}
    if json_body is not None:
        kwargs["json"] = json_body
    if data:
        kwargs["data"] = data
    if files:
        kwargs["files"] = files
    if timeout:
        kwargs["timeout"] = httpx.Timeout(timeout, connect=10)
    try:
        async with client().stream(method, url, **kwargs) as response:
            kind = response.headers.get("content-type", "").lower()
            textual = any(mark in kind for mark in _TEXTUAL) or not kind
            if not response.is_success or (save_as is None and (textual or not save_binary)):
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_TEXT_BYTES:
                        break
                return Reply(response.status_code, response.headers, body.decode(response.encoding or "utf-8", "replace"), None)
            sweep()
            path = work_path(save_as or _name_from(response.headers, response.url, "download.bin"))
            size = 0
            with path.open("wb") as out:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        out.close()
                        path.unlink(missing_ok=True)
                        raise ToolError(f"the file is larger than the {MAX_FILE_BYTES >> 20} MB limit")
                    out.write(chunk)
            return Reply(response.status_code, response.headers, None, path)
    except httpx.TimeoutException:
        raise ToolError(f"{method} {httpx.URL(url).host}: no answer in time")
    except httpx.HTTPError as exc:
        raise ToolError(f"{method} {httpx.URL(url).host}: {type(exc).__name__}: {exc}")


async def require_public(url: str) -> httpx.URL:
    """Refuse addresses inside the house. The pod's NetworkPolicy is the real
    wall; this gives the model a clear message instead of a timeout."""
    try:
        parsed = httpx.URL(url)
    except Exception:
        raise ToolError(f"not a valid URL: {url!r}")
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ToolError("only http:// and https:// addresses can be fetched")
    try:
        found = await asyncio.get_running_loop().getaddrinfo(parsed.host, None, type=socket.SOCK_STREAM)
    except OSError:
        raise ToolError(f"cannot find the host {parsed.host!r}")
    for entry in found:
        if not ipaddress.ip_address(entry[4][0]).is_global:
            raise ToolError(
                f"{parsed.host} is an address inside the house. Lab services are reached "
                "with api_call and the other tools, not by URL."
            )
    return parsed


async def fetch_public(url: str, *, save_as: str | None = None, save_binary: bool = True) -> Reply:
    """GET a page or file on the public internet, following up to five redirects."""
    for _ in range(6):
        parsed = await require_public(url)
        reply = await send(
            "GET", str(parsed), headers={"User-Agent": BROWSER_UA, "Accept-Language": "en,ru;q=0.8"},
            save_as=save_as, save_binary=save_binary, timeout=60,
        )
        if reply.status in (301, 302, 303, 307, 308) and reply.headers.get("location"):
            if reply.saved:
                reply.saved.unlink(missing_ok=True)
            url = str(parsed.join(reply.headers["location"]))
            continue
        return reply
    raise ToolError("too many redirects")
