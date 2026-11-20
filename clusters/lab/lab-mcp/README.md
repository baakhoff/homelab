# lab-mcp

The lab's services as [MCP](https://modelcontextprotocol.io) tools, for an
AI agent that runs outside the cluster: today a Hermes agent on a local
model, on the workstation. The agent holds one token for this server. The
server holds a key for each service, and those never leave the cluster.

    [agent, local model] --HTTPS + token--> [lab-mcp] --each service's own key--> [Outline, Immich, ...]

At <https://mcp.lab.baakhoff.com/mcp>. The code is
[`images/lab-mcp`](../../images/lab-mcp/README.md).

## Why a server in between

- **The model is local, so the data stays in the house.** Nothing here
  calls a hosted model.
- **The keys stay here.** A workstation agent with nine API keys in a file
  is nine keys to leak. This way it has one, which opens only this server
  and is changed in one place.
- **One place to see what it did.** Every tool call is a log line
  ("What goes to the warehouse", below).
- **The agent's own internet can be shut.** Search, reading a page and
  downloads all go through here, so the workstation agent needs no route
  out but this one, and what it fetched is in the log.

## What it reaches

| Name | Service | With | Can |
|---|---|---|---|
| `notes` | Outline | an API key | read and write |
| `tasks` | Vikunja | an API token | read and write |
| `links` | Karakeep | an API key | read and write |
| `photos` | Immich | an API key | what the key allows |
| `documents` | Paperless-ngx | an API token | read and write |
| `recipes` | Mealie | an API token | read and write |
| `home` | Home Assistant | a long-lived token | read states, call services |
| `money` | Firefly III, through `firefly-broker` | no key: the broker holds it | read, write, delete |
| `models` | Manyfold | an API key (client id and secret) | read, unless the key has more scopes |
| `location` | Dawarich | the account's API key | read and write |
| `pdf` | Stirling-PDF | nothing: it has no login inside the cluster | every PDF operation |
| `metrics` | Prometheus | nothing | read only: the server refuses anything but GET |
| warehouse | ClickHouse | the `labmcp` user | `SELECT` on `ods`, `ads`, `dm` |
| web | SearXNG, cobalt, the public internet | nothing | search, read a page, download a file or a video |

A service whose key is not in the Secret is listed to the agent as "not set
up yet" and its tools answer with that. So the keys can be added one at a
time.

There are about 35 tools. Named ones cover the daily things (`notes_search`,
`task_save`, `photos_search`, `documents_search`, `home_call`,
`money_transactions`, `warehouse_query`, `web_search`, `web_read`,
`pdf_merge`, ...). `api_call` reaches any other endpoint of a listed
service, and `api_find` tells the model which endpoints there are.

### Files

Tools that produce a file (a download, a PDF, a photo) save it in a scratch
volume on the pod, and tools that take a file read it from there. A person
moves files in and out with the same token:

```bash
curl -H "Authorization: Bearer $LAB_MCP_TOKEN" -T scan.pdf https://mcp.lab.baakhoff.com/files/scan.pdf
curl -H "Authorization: Bearer $LAB_MCP_TOKEN" -O https://mcp.lab.baakhoff.com/files/scan-ocr.pdf
```

Files are deleted after 48 hours, and all of them when the pod restarts.
One file may be 1 GiB; the volume holds 4 GiB.

## What it does not reach, on purpose

- **Vaultwarden and Pocket ID.** Passwords and logins. No agent gets these.
- **The Kubernetes API.** It manages what runs in the services, not the
  cluster.
- **n8n and Airflow.** A workflow or a DAG is code that runs with its own
  network access: writing one is a way around every limit here.
- **The house LAN, the tailnet and every other pod.** `networkpolicy.yaml`
  names each service it may call, and cuts every private range out of the
  internet rule.
- **`raw` in the warehouse.** The modelled layers only, like brand. One
  `GRANT` line in `clusters/lab/data/clickhouse-schema.yaml` widens it.

## What can still leave the house

The model is local, but three tools speak to the outside, and each sends
whatever the model puts in the request: the words of a `web_search` (to the
search engines), the address in `web_read` and `web_download` (to that
site), and the link in `media_download`. A page or a saved link written to
steer an AI could ask the model to put something private into one of those.
Small local models resist that less well than the large hosted ones.

What stands against it: the server's instructions tell the model that
fetched text is information and not orders; only GET requests go out, with
no body; every one is logged with its full address; and these tools can be
taken away from the agent on its side without touching the rest
(`tools.exclude` in the agent's MCP settings).

Home Assistant's `notify.*` services also send a message out, to whatever
they are set up for.

## Login

A bearer token, `MCP_TOKEN`, checked by the server on every request, the
file paths included. Not the Pocket ID gate: the caller is a program and
cannot do a browser login. Only `/healthz` answers without it.

## What it keeps

Nothing. The scratch volume is an `emptyDir`. No volume, so no backup
entry.

## What goes to the warehouse

Every tool call is one JSON line on the pod's output, which the collectors
carry to `raw.logs` like any other pod's:

```json
{"event": "lab-mcp", "tool": "web_read", "ok": true, "ms": 412, "args": {"url": "https://example.org/"}, "chars": 3020}
```

`args` holds what was asked: the query, the path, the address, the SQL.
Long text being written (`text`, `body`, `form`) is logged as a length
only. The collectors mask secrets in the line before it leaves the node.

```sql
SELECT ts, JSONExtractString(body, 'tool') AS tool, JSONExtractRaw(body, 'args') AS args
FROM ods.logs
WHERE namespace = 'lab-mcp' AND body LIKE '{"event": "lab-mcp"%'
ORDER BY ts DESC LIMIT 50
```

The services' own data reaches the warehouse through their own pipelines,
as before.

## Setup

**1. The keys.** Make one in each service you want the agent to use, each
named `lab-mcp` so it can be told apart and revoked alone. Skip any; add it
later.

| Service | Where | Variable |
|---|---|---|
| Outline | Settings → API → New API key | `OUTLINE_API_KEY` |
| Vikunja | Settings → API Tokens, with the permissions to give | `VIKUNJA_API_TOKEN` |
| Karakeep | Settings → API Keys → New | `KARAKEEP_API_KEY` |
| Immich | Account settings → API keys → New, with the permissions to give | `IMMICH_API_KEY` |
| Paperless | My Profile → API Auth Token | `PAPERLESS_API_TOKEN` |
| Mealie | Profile → Manage Your API Tokens | `MEALIE_API_TOKEN` |
| Home Assistant | your profile → Security → Long-lived access tokens | `HOME_ASSISTANT_TOKEN` |
| Manyfold | Settings → API keys → New, confidential, redirect URI `urn:ietf:wg:oauth:2.0:oob` | `MANYFOLD_CLIENT_ID`, `MANYFOLD_CLIENT_SECRET` |
| Dawarich | Account → API key | `DAWARICH_API_KEY` |

A Manyfold key made with more than the `read` scope also needs
`MANYFOLD_SCOPE` set to the scopes to ask for, separated by spaces.

**2. The two Secrets.** On the workstation, from the repo root. The loop
asks for each key and skips the ones left empty; nothing is shown.

```bash
TOKEN=$(openssl rand -hex 32)
CHPW=$(openssl rand -hex 24)
args=(--from-literal=MCP_TOKEN="$TOKEN" --from-literal=CLICKHOUSE_PASSWORD="$CHPW")
for name in OUTLINE_API_KEY VIKUNJA_API_TOKEN KARAKEEP_API_KEY IMMICH_API_KEY PAPERLESS_API_TOKEN \
            MEALIE_API_TOKEN HOME_ASSISTANT_TOKEN MANYFOLD_CLIENT_ID MANYFOLD_CLIENT_SECRET DAWARICH_API_KEY; do
  read -rsp "$name (Enter to skip): " value; echo
  [ -n "$value" ] && args+=(--from-literal="$name=$value")
done
kubectl create secret generic lab-mcp --namespace lab-mcp "${args[@]}" \
  --dry-run=client -o yaml > clusters/lab/lab-mcp/secret.sops.yaml
sops --encrypt --in-place clusters/lab/lab-mcp/secret.sops.yaml
kubectl create secret generic clickhouse-labmcp --namespace data \
  --from-literal=LABMCP_PASSWORD="$CHPW" \
  --dry-run=client -o yaml > clusters/lab/data/clickhouse-labmcp.sops.yaml
sops --encrypt --in-place clusters/lab/data/clickhouse-labmcp.sops.yaml
```

On the Mac's zsh, the `read` line is `read -rs "value?$name (Enter to skip): "; echo`.

Keep the terminal open for step 4, then `unset TOKEN CHPW value args`.
Commit both files. The warehouse user appears at the schema job's next run,
within the hour.

**3. The image.** The first build publishes the package; check that it is
public (`images/lab-mcp/README.md`, "Build").

**4. The agent.** For Hermes, the token goes in `~/.hermes/.env`:

```bash
echo "LAB_MCP_TOKEN=$TOKEN" >> ~/.hermes/.env
```

and the server in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  lab:
    url: "https://mcp.lab.baakhoff.com/mcp"
    headers:
      Authorization: "Bearer ${LAB_MCP_TOKEN}"
    supports_parallel_tool_calls: true
```

The last line lets Hermes run several of this server's tools at once
instead of one per turn. It is off by default for every MCP server, and
safe here: the server keeps nothing between calls.

**5. Check.**

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://mcp.lab.baakhoff.com/healthz          # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://mcp.lab.baakhoff.com/mcp     # 401
```

Then ask the agent to call `lab_services`.

## Adding or changing a key

Edit the Secret (`sops clusters/lab/lab-mcp/secret.sops.yaml`; values are
base64), and bump `lab-mcp/secret` in `deployment.yaml` in the same commit
so the pod restarts and reads it.

Changing `MCP_TOKEN` locks the agent out until its `.env` has the new one.

## Adding a service

Every service added to the lab gets its tools here in the same change, if
it has an API worth giving an agent:

1. The code side: `images/lab-mcp/README.md`, "Adding a service".
2. An egress rule in `networkpolicy.yaml` here, to the service's pods and
   container port.
3. If the service's namespace has an ingress policy, a matching rule
   there. Today those are Outline, Vikunja, Karakeep, Immich, Manyfold,
   Mealie, Dawarich, SearXNG, `firefly-broker` and ClickHouse.
4. Its key in the Secret, a row in both tables above.

## When something fails

```bash
kubectl -n lab-mcp logs deploy/lab-mcp --tail=50
```

- **A tool says "no answer in time" or "ConnectError"** for one service: a
  NetworkPolicy half is missing, or that service is down.
- **HTTP 401 or 403 from a service:** its key is wrong, revoked, or lacks a
  permission. Make a new one and change the Secret.
- **The pod will not start, "MCP_TOKEN must be set":** the Secret is
  missing or has no `MCP_TOKEN`.
- **`ErrImagePull`:** the image is still building, or the package is
  private.
- **Restart it:** `kubectl -n lab-mcp delete pod -l app.kubernetes.io/name=lab-mcp`
