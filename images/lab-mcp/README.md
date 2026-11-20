# lab-mcp image

The lab's services as [MCP](https://modelcontextprotocol.io) tools: one
server that an agent outside the cluster connects to, instead of that agent
holding a key for every service. What it is for, what it reaches and how to
connect are in [`clusters/lab/lab-mcp/README.md`](../../clusters/lab/lab-mcp/README.md).
This page is about the code.

## Layout

| File | What it is |
|---|---|
| `lab_mcp/services.py` | the list of services: address, how a request is signed, where its API is described |
| `lab_mcp/guides/<name>.md` | one page per service that the model reads through `api_find`: main endpoints, examples |
| `lab_mcp/tools.py` | the tools, one function each |
| `lab_mcp/core.py` | the log line, the scratch file workspace, the HTTP client, the "public addresses only" check |
| `lab_mcp/app.py` | the server: registers every tool, checks the token, serves `/files/<name>` |
| `tests/` | every tool against a pretend lab |

## Two kinds of tool

- **Named tools** (`notes_search`, `task_save`, `photos_search`, ...) for
  what gets asked daily: small inputs, short plain-text answers. A small
  local model picks and uses these well.
- **`api_call`**, which reaches any endpoint of any listed service, signed
  in. `api_find` tells the model what there is: with no keyword it returns
  the service's guide, with one it searches the service's own OpenAPI
  document where the service publishes one.

So a new feature of a service is usable the day it ships, through
`api_call`, and gets a named tool only when it is used often enough to
deserve one.

## Adding a service

1. An entry in `SERVICES` in `lab_mcp/services.py`.
2. A guide, `lab_mcp/guides/<name>.md`. Keep it to what was checked against
   the running service.
3. Its key in the Secret, and a NetworkPolicy door on both sides
   (the cluster README has the steps).
4. A named tool or two in `tools.py`, with a case in `tests/test_tools.py`,
   if it will be used daily.
5. Bump `VERSION` and the tag in `clusters/lab/lab-mcp/deployment.yaml`, in
   the same change. The old pod keeps serving until the new image is built.

## Testing

```
cd images/lab-mcp
uv run --with-requirements requirements.txt --with pytest --with reportlab pytest -q
```

The tests answer for every upstream with made-up data, so they prove the
tools' own logic and the shape of what they send. They do not prove a
service still answers that shape after an upgrade: `api_call` on the real
thing does.

## Build

`.github/workflows/lab-mcp-image.yml` builds this directory on a push to
main and tags the image with `VERSION`. The package must be public, like
the lab's other images: check its visibility after the first build
(`images/claude-agent/README.md`, "Visibility").
