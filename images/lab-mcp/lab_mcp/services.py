"""The lab's services, as the tools see them.

One entry per service: where it is, how a request is signed, and where its
API is described. A service whose key is not set is simply not offered.

ADDING A SERVICE: add an entry here, a guide in guides/<name>.md, its key to
the Secret, and a NetworkPolicy door on both sides
(clusters/lab/lab-mcp/README.md has the list).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import core
from .core import ToolError

GUIDES = Path(__file__).parent / "guides"


def env(name: str) -> str:
    return os.environ.get(name, "").strip()


def bearer(var: str, scheme: str = "Bearer") -> Callable[[], dict[str, str]]:
    return lambda: {"Authorization": f"{scheme} {env(var)}"}


@dataclass
class Service:
    name: str
    title: str
    about: str
    base: str
    needs: tuple[str, ...] = ()
    headers: Callable[[], dict[str, str]] = lambda: {}
    read_only: bool = False
    # Where the service publishes its own OpenAPI description, and the part
    # of each path there that `base` already covers.
    openapi: str = ""
    spec_strip: str = ""
    _spec: tuple[float, list[dict[str, Any]]] | None = field(default=None, repr=False)

    @property
    def url(self) -> str:
        return (env(f"{self.name.upper()}_URL") or self.base).rstrip("/")

    @property
    def enabled(self) -> bool:
        return all(env(var) for var in self.needs)

    def guide(self) -> str:
        path = GUIDES / f"{self.name}.md"
        return path.read_text() if path.exists() else f"No guide written for {self.name} yet."


def _svc(host: str, namespace: str, path: str = "", port: str = "") -> str:
    return f"http://{host}.{namespace}.svc.cluster.local{port}{path}"


SERVICES: dict[str, Service] = {
    s.name: s
    for s in [
        Service(
            "notes", "Outline", "the household wiki: documents in collections",
            _svc("outline", "notes", "/api"), ("OUTLINE_API_KEY",), bearer("OUTLINE_API_KEY"),
        ),
        Service(
            "tasks", "Vikunja", "to-do lists: projects and tasks",
            _svc("vikunja", "vikunja", "/api/v1"), ("VIKUNJA_API_TOKEN",), bearer("VIKUNJA_API_TOKEN"),
            openapi="/docs.json",
        ),
        Service(
            "links", "Karakeep", "saved links and notes, with tags and lists",
            _svc("karakeep", "karakeep", "/api/v1"), ("KARAKEEP_API_KEY",), bearer("KARAKEEP_API_KEY"),
        ),
        Service(
            "photos", "Immich", "the photo and video library",
            _svc("immich-server", "immich", "/api"), ("IMMICH_API_KEY",),
            lambda: {"x-api-key": env("IMMICH_API_KEY")},
        ),
        Service(
            "documents", "Paperless-ngx", "scanned letters, bills and contracts, with their text",
            _svc("paperless", "paperless", "/api"), ("PAPERLESS_API_TOKEN",),
            lambda: {"Authorization": f"Token {env('PAPERLESS_API_TOKEN')}", "Accept": "application/json; version=9"},
            openapi="/schema/?format=json", spec_strip="/api",
        ),
        Service(
            "recipes", "Mealie", "recipes, meal plans and shopping lists",
            _svc("mealie", "mealie", "/api"), ("MEALIE_API_TOKEN",), bearer("MEALIE_API_TOKEN"),
            openapi=_svc("mealie", "mealie", "/openapi.json"), spec_strip="/api",
        ),
        Service(
            "home", "Home Assistant", "the house: lights, sensors, switches, automations",
            _svc("home-assistant", "home-assistant", "/api"), ("HOME_ASSISTANT_TOKEN",), bearer("HOME_ASSISTANT_TOKEN"),
        ),
        Service(
            "money", "Firefly III", "the household's books: accounts, transactions, budgets",
            _svc("firefly-broker", "firefly-broker", "/v1"),
        ),
        Service(
            "models", "Manyfold", "the 3D model library",
            _svc("manyfold", "manyfold"), ("MANYFOLD_CLIENT_ID", "MANYFOLD_CLIENT_SECRET"),
        ),
        Service(
            "location", "Dawarich", "location history: points, visits, trips",
            _svc("dawarich", "dawarich", "/api/v1"), ("DAWARICH_API_KEY",), bearer("DAWARICH_API_KEY"),
        ),
        Service(
            "pdf", "Stirling-PDF", "heavy PDF work: OCR, compress, convert, sign, redact",
            _svc("stirling-pdf", "stirling-pdf", "/api/v1"),
            openapi=_svc("stirling-pdf", "stirling-pdf", "/v1/api-docs"), spec_strip="/api/v1",
        ),
        Service(
            "metrics", "Prometheus", "the cluster's metrics and firing alerts (read only)",
            _svc("kube-prometheus-stack-prometheus", "monitoring", "/api/v1", ":9090"), read_only=True,
        ),
    ]
}

# Reached by their own tools only.
SEARXNG_URL = env("SEARXNG_URL") or _svc("searxng", "searxng")
COBALT_URL = env("COBALT_URL") or _svc("cobalt", "cobalt")
CLICKHOUSE_URL = env("CLICKHOUSE_URL") or _svc("clickhouse", "data", port=":8123")


def get(name: str) -> Service:
    service = SERVICES.get(str(name).strip().lower())
    if service is None:
        raise ToolError(f"no service named {name!r}. Services: {', '.join(SERVICES)}")
    if not service.enabled:
        raise ToolError(f"{service.name} ({service.title}) has no key set on the server yet, so it cannot be used.")
    return service


# --- Manyfold signs in with a short-lived token ------------------------------

_manyfold: tuple[float, str] | None = None


async def _manyfold_headers() -> dict[str, str]:
    global _manyfold
    if _manyfold is None or _manyfold[0] < time.time():
        reply = await core.send(
            "POST", SERVICES["models"].url + "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": env("MANYFOLD_CLIENT_ID"),
                "client_secret": env("MANYFOLD_CLIENT_SECRET"),
                "scope": env("MANYFOLD_SCOPE") or "read",
            },
        )
        if not reply.ok:
            raise ToolError(f"Manyfold refused the sign-in: HTTP {reply.status} {(reply.text or '')[:200]}")
        token = reply.json()
        _manyfold = (time.time() + int(token.get("expires_in", 3600)) - 60, token["access_token"])
    return {"Authorization": f"Bearer {_manyfold[1]}", "Accept": "application/vnd.manyfold.v0+json"}


async def call(
    service: Service,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    data: dict[str, Any] | None = None,
    files: list[tuple[str, tuple[str, Any, str]]] | None = None,
    save_as: str | None = None,
    timeout: float | None = None,
) -> core.Reply:
    """A signed request to one of the lab's services."""
    method = method.upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ToolError("method must be GET, POST, PUT, PATCH or DELETE")
    if service.read_only and method != "GET":
        raise ToolError(f"{service.name} is read only: GET requests only")
    if not path.startswith("/") or "://" in path or ".." in path.split("?")[0].split("/"):
        raise ToolError("path must start with / and stay inside the service's API, for example /documents/")
    headers = await _manyfold_headers() if service.name == "models" else service.headers()
    headers.setdefault("Accept", "application/json, */*;q=0.5")
    return await core.send(
        method, service.url + path, headers=headers, params=params, json_body=json_body,
        data=data, files=files, save_as=save_as, timeout=timeout,
    )


async def ask(service_name: str, method: str, path: str, **kwargs: Any) -> Any:
    """`call`, for tools that expect JSON back and treat anything else as an error."""
    service = get(service_name)
    reply = await call(service, method, path, **kwargs)
    if not reply.ok:
        raise ToolError(f"{service.title} answered HTTP {reply.status}: {(reply.text or '')[:500]}")
    return reply.json() if reply.text else None


# --- finding an endpoint in a service's own API description ------------------


def _body_fields(spec: dict[str, Any], operation: dict[str, Any]) -> list[str]:
    content = (operation.get("requestBody") or {}).get("content") or {}
    for kind in content.values():
        schema = kind.get("schema") or {}
        ref = schema.get("$ref", "")
        if ref.startswith("#/"):
            node: Any = spec
            for part in ref[2:].split("/"):
                node = (node or {}).get(part)
            schema = node or {}
        return list((schema.get("properties") or {}).keys())[:25]
    for param in operation.get("parameters") or []:  # Swagger 2 puts the body here
        if param.get("in") == "body":
            ref = (param.get("schema") or {}).get("$ref", "")
            node = spec
            for part in ref[2:].split("/") if ref.startswith("#/") else []:
                node = (node or {}).get(part)
            return list(((node or {}).get("properties") or {}).keys())[:25] if ref else []
    return []


async def operations(service: Service) -> list[dict[str, Any]]:
    """The service's API as a flat list, from its OpenAPI document, cached for an hour."""
    if service._spec and service._spec[0] > time.time():
        return service._spec[1]
    url = service.openapi if service.openapi.startswith("http") else service.url + service.openapi
    reply = await core.send("GET", url, headers={**service.headers(), "Accept": "application/json"})
    if not reply.ok or not reply.text:
        raise ToolError(f"{service.title} did not serve its API description (HTTP {reply.status})")
    spec = json.loads(reply.text)
    found = []
    for path, item in (spec.get("paths") or {}).items():
        shown = path[len(service.spec_strip):] if service.spec_strip and path.startswith(service.spec_strip) else path
        for method, operation in item.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete") or not isinstance(operation, dict):
                continue
            params = [p.get("name", "") for p in operation.get("parameters") or [] if p.get("in") in ("query", "formData")]
            found.append({
                "method": method.upper(),
                "path": shown or "/",
                "summary": (operation.get("summary") or operation.get("description") or "").strip().split("\n")[0][:140],
                "id": operation.get("operationId", ""),
                "tags": " ".join(operation.get("tags") or []),
                "query": params[:25],
                "body": _body_fields(spec, operation),
            })
    service._spec = (time.time() + 3600, found)
    return found
