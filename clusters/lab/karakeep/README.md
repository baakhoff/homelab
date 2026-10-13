# Karakeep

[Karakeep](https://karakeep.app) keeps what you want to come back to: links,
notes, images and PDFs, saved from the browser or the phone's share menu.
For a link it keeps a copy of the page here, with a screenshot, and the
video if the page has one. An AI adds tags and a short summary, and search
covers the full text of everything saved, including text in images and PDFs.

At <https://links.lab.baakhoff.com>, and on Homepage under Home.

## How it is put together

| Pod | Containers | What it does |
|---|---|---|
| `karakeep` | `web`, `workers`, `meilisearch` | the app and its API; crawling, AI, OCR and video downloads; the search index on loopback |
| `karakeep-chrome` | `chrome` | the headless browser the crawler opens each link in |

Upstream's image runs the web server and the workers under one supervisor
that needs root. Here they are two containers from the same image, as the
image's own user, with the database migration as an init container
(`deployment.yaml`).

The browser is a pod of its own because it is the part that visits
whatever was saved, follows redirects and runs scripts. Its NetworkPolicy
lets it reach the public internet and nothing in the house or the cluster.

| Volume | What is on it | Backed up |
|---|---|---|
| `karakeep-data` | the database, and every page copy, screenshot, video and upload | yes, nightly |
| `karakeep-meilisearch` | the search index | no: rebuilt from the database (below) |

## Login

Pocket ID, through Karakeep's own sign-in, and behind the oauth2-proxy gate
as well, like Outline. In practice it is one passkey: the gate asks for it,
and Karakeep goes straight on to Pocket ID and finds the session there.
There are no Karakeep passwords. An account is made at its first sign-in,
and each person's bookmarks are their own.

The first account to sign in is Karakeep's admin.

## Phone and browser

The phone app and the browser extension cannot pass the gate, so the API
paths they use are open past it, and they sign in with an API key instead
(`ingress.yaml` lists the paths). Nothing on those paths answers without a
key.

1. In Karakeep on the web: Settings → API Keys → New, one per device, named
   after it, so a lost phone's key can be revoked on its own.
2. The app (iOS or Android, "Karakeep") or the extension (Firefox or
   Chrome): server address `https://links.lab.baakhoff.com`, then sign in
   with the API key.

Then on the phone, Share → Karakeep saves whatever is open.

## What it costs

**AI:** each saved item is one request to `openai/gpt-5-mini` through
OpenRouter, for tags and a summary, with the page cut to about 4,000
tokens: a fraction of a cent each. The key is OpenRouter's, with a credit
limit set there. To change the model, edit `INFERENCE_TEXT_MODEL` and
`INFERENCE_IMAGE_MODEL` in `deployment.yaml`; any OpenRouter model that
reads images and returns structured output works.

**Disk:** a page copy is usually under a few MB, a video up to 200 MB
(`CRAWLER_VIDEO_DOWNLOAD_MAX_SIZE`). The volume is 20 GiB and grows in
place; Karakeep's admin settings show the space used.

## What goes to the warehouse

Airflow's `ingest_karakeep` DAG copies the bookmarks, with their text,
and the highlights, tags, lists and feeds into ClickHouse's `raw.karakeep`
every six hours (`pipelines/dags/ingest.py`).

| Table | One row per |
|---|---|
| `ods.karakeep_bookmarks` | bookmark: kind, title, URL and site, the page's text, the AI summary, your note, the tags (and which the AI added), favourite and archived, where it was saved from |
| `ods.karakeep_highlights` | highlighted passage, with its note |
| `ods.karakeep_tags` | tag, with how many bookmarks carry it |

Bookmarks are each account's own, so the warehouse sees the account whose
key the DAG uses (step 4). The page copies, screenshots and videos stay in
Karakeep. Secrets in the text are masked on the way in, as for every source
(`pipelines/sensitive.md`).

**Who can read it:** anyone who can read `ods`, which includes the brand
agent's `brand` user.

## Setup, in this order

The pod waits in `CreateContainerConfigError` until step 2's Secret exists.

**1. The Pocket ID client.** In Pocket ID at <https://id.lab.baakhoff.com>,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Karakeep |
| Callback URLs | `https://links.lab.baakhoff.com/api/auth/callback/custom` |
| PKCE | off |
| Public Client | off |
| Allowed User Groups | whoever saves links here |

**2. The Secret, before this merges.** On the workstation from the repo
root, on this branch. Run the `read` lines one at a time: pasted together,
the rest of the paste becomes the input. The OpenRouter key is a new one
made at openrouter.ai → Keys, named `karakeep`, with a credit limit. The
other two values are generated and never shown.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo
read -rsp 'openrouter key: ' ORK; echo

kubectl create secret generic karakeep \
  --namespace karakeep \
  --from-literal=NEXTAUTH_SECRET="$(openssl rand -base64 36)" \
  --from-literal=MEILI_MASTER_KEY="$(openssl rand -hex 24)" \
  --from-literal=OAUTH_CLIENT_ID="$CID" \
  --from-literal=OAUTH_CLIENT_SECRET="$CSEC" \
  --from-literal=OPENAI_API_KEY="$ORK" \
  --dry-run=client -o yaml > clusters/lab/karakeep/secret.sops.yaml

unset CID CSEC ORK
sops --encrypt --in-place clusters/lab/karakeep/secret.sops.yaml
```

Create it once. `NEXTAUTH_SECRET` signs everyone's sessions, and
`MEILI_MASTER_KEY` is fixed into the index when Meilisearch first starts:
new values sign everyone out and lock Karakeep out of its own index. To
change only the client or the OpenRouter key, edit in place with
`sops clusters/lab/karakeep/secret.sops.yaml`.

**3. The backup's Secret,** copied from an existing one without the values
touching the screen (`clusters/lab/backup/README.md`):

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: karakeep/' \
  > clusters/lab/backup/restic-repo-karakeep.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-karakeep.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-karakeep.sops.yaml
```

The `grep` must print `namespace: karakeep` before you encrypt. Commit and
push both files; the pre-commit hook checks that they are encrypted.

**After the merge,** once Flux has applied it: run the schema job now
rather than at the hour, so `raw.karakeep` exists before the first ingest,
and sign in first, so the admin account is yours.

```bash
kubectl -n data create job --from=cronjob/clickhouse-schema schema-karakeep
kubectl -n karakeep rollout status deploy/karakeep --timeout=10m
```

Then open <https://links.lab.baakhoff.com>.

**4. Feed the data warehouse.** In your own Karakeep account, Settings →
API Keys → New, named `warehouse`. On the workstation from the repo root,
one line at a time:

```bash
read -rsp 'karakeep api key: ' KK; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["KARAKEEP_API_KEY"]' "\"$(printf %s "$KK" | base64 | tr -d '\n')\""
unset KK
```

Commit and push. Once Flux has applied it, restart the scheduler, because a
pod reads its environment only when it starts:

```bash
kubectl -n airflow rollout restart deployment/airflow-scheduler
```

Then, in the Airflow UI, switch `ingest_karakeep` on - Airflow pauses every
new DAG until someone does - and trigger it, and after it the `warehouse`
DAG. Until the key exists, that DAG's runs fail and nothing else is
affected.

## Things to know

- **Search finds nothing after a restore,** or after the index volume was
  lost: Karakeep's admin settings → Background Jobs → "Reindex all
  bookmarks".
- **A link saved but never filled in** (no title, no copy): the crawl
  failed. The bookmark's menu → "Refresh" tries again. The workers' log says
  why:

  ```bash
  kubectl -n karakeep logs deploy/karakeep -c workers --tail=100
  ```

- **Links to lab services** are not crawled: Karakeep refuses private
  addresses, and the browser could not reach them anyway. The bookmark is
  kept, without a copy.
- **Upgrades:** the migration init container brings the database up to the
  new version before the app starts. The nightly backup is the undo.
  `karakeep-chrome` has its own version and moves on its own.
