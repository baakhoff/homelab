# Notes (Outline)

Notes and documents in a polished web editor: collections to group them,
nested pages, Markdown shortcuts, tables, images, mentions, search across
everything, and live editing by several people at once. Every edit is kept
in the document's history, with who made it, and any earlier version can be
restored.

At <https://notes.lab.baakhoff.com>, and on Homepage under Home.

The `brand` agent pod reads and writes documents too, through Outline's API
with an API key (step 3).

## How login works

Pocket ID, through Outline's own OpenID Connect support, behind the
oauth2-proxy gate as well, the one rule for every host here. In practice it
is one passkey: the gate asks for it, and Outline's sign-in finds the Pocket
ID session already there. There is no Outline password.

The first person to sign in creates the workspace and becomes its admin.
Everyone after joins it as a member; who may sign in at all is the client's
Allowed User Groups in Pocket ID. Roles (admin, member, viewer) are changed
in Outline's settings, under Members.

The gate means Outline's desktop and phone apps cannot sign in; the web app
is the way in, and on a phone it installs to the home screen from the
browser's menu.

## What is here

| File | What |
|---|---|
| `deployment.yaml` | Outline, plus Redis beside it on loopback for its queues and live collaboration |
| `postgres.yaml` | its own Postgres 18: the documents, their history, collections, users, API keys |
| `pvc.yaml` | the images and attachments added to documents |
| `ingress.yaml` | `notes.lab.baakhoff.com`, behind the gate |
| `networkpolicy.yaml` | in: ingress-nginx, the brand pod and Airflow's scheduler to Outline; only Outline to Postgres |
| `secret.sops.yaml` | made by you, step 1 |

## Setup, in this order

The pod waits in `CreateContainerConfigError` until step 1's Secret exists.

**1. The Pocket ID client and the Secret, before this merges.** In Pocket
ID at <https://id.lab.baakhoff.com>, Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Outline |
| Callback URLs | `https://notes.lab.baakhoff.com/auth/oidc.callback` |
| PKCE | off |
| Public Client | off |
| Allowed User Groups | whoever keeps notes here |

Then the Secret, on the workstation from the repo root, on this branch. Run
the two `read` lines one at a time: pasted together, the rest of the paste
becomes the input. The other three values are generated and never shown.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic outline \
  --namespace notes \
  --from-literal=DATABASE_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=UTILS_SECRET="$(openssl rand -hex 32)" \
  --from-literal=OIDC_CLIENT_ID="$CID" \
  --from-literal=OIDC_CLIENT_SECRET="$CSEC" \
  --dry-run=client -o yaml > clusters/lab/notes/secret.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/notes/secret.sops.yaml
```

Commit and push. The pre-commit hook asserts the file is encrypted.

Create it once. Run again, it replaces values already in use:

- `DATABASE_PASSWORD` is set in Postgres when the database is first
  created. A new value no longer matches, and Outline cannot connect.
- `SECRET_KEY` is what Outline encrypts stored secrets and signs sessions
  with. A new one signs everyone out and makes stored integration secrets
  unreadable.

To change only the Pocket ID client, edit in place with
`sops clusters/lab/notes/secret.sops.yaml`.

**2. Sign in first**, once Flux has applied the merge and the pod is
`Running`. Open <https://notes.lab.baakhoff.com> and sign in with Pocket ID
before anyone else does: that first account is the workspace's admin.

Outline refuses a sign-in without an email. Under Administration → Users in
Pocket ID, check that each person's email is set.

**3. The brand agent's key.** In your own Outline account, Settings → API →
New API key, named `brand agent` so it can be told apart and revoked on its
own. Paste it into a session in the `brand` pod and ask the agent to keep it
under its home directory.

Outline records which account made an edit, not which key, so the agent's
edits show in each document's history as yours. Restore works the same; ask
the agent to note its own changes if you want to tell them apart. The key
reaches everything your account does. To keep the agent to some
collections, or to see its edits under its own name, it needs an account of
its own instead, and Outline makes accounts only at sign-in: a Pocket ID
user for it (e.g. `brand-agent`, in the client's allowed group), a one-time
login link from Pocket ID opened in a private window, a sign-in to Outline
there, and the API key made in that window.

The agent calls:

```
POST http://outline.notes.svc.cluster.local/api/<method>
Authorization: Bearer <key>
Content-Type: application/json
```

with methods such as `documents.list`, `documents.info`, `documents.search`,
`documents.create` and `documents.update` - Outline's API reference is at
<https://www.getoutline.com/developers>.

`clusters/lab/agents/networkpolicy-brand.yaml` is what lets that pod, and no
other agent, reach Outline.

**4. Feed the data warehouse.** Airflow's `ingest_outline` DAG copies every
published document, text included, and the collections into ClickHouse's
`raw.outline` every six hours (`pipelines/dags/ingest.py`);
`ods.outline_documents` and `ods.outline_collections` have one row each.
It needs an API key that can read every collection: create one in your own
account, Settings → API. If the form offers scopes, keep it to reading.

On the workstation from the repo root, one line at a time:

```bash
read -rsp 'outline api key: ' OK; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["OUTLINE_API_KEY"]' "\"$(printf %s "$OK" | base64 | tr -d '\n')\""
unset OK
```

On the Mac's zsh, the first line is `read -rs "OK?outline api key: "; echo`.
Commit and push. Once Flux has applied it, restart the scheduler, because a
pod reads its environment only when it starts:

```bash
kubectl -n airflow rollout restart deployment/airflow-scheduler
```

Then, in the Airflow UI, switch `ingest_outline` on - Airflow pauses every
new DAG until someone does - and trigger it, and after it the `warehouse`
DAG. Until the key exists, that DAG's runs fail and nothing else
is affected.

## Things to know

- **Undoing an edit**, yours or the agent's: the document's menu → History,
  pick the version, Restore.
- **Drafts are private** until published, and `documents.list` does not
  return them, so they reach neither the warehouse nor another account.
- **Only `brand` among the agents.** Another pod gets access with a key and
  a door in `networkpolicy.yaml` plus an egress rule on its side, like
  brand's.
- **No email.** No SMTP is configured, so there are no notification mails
  and no email sign-in; Pocket ID is the only way in.
- **Sizes.** Postgres and the attachments volume are 5Gi each, expandable in
  place.

## Backup

Both volumes are in the nightly backup (`clusters/lab/backup/`), after
Dawarich: `notes/data-outline-postgres-0`, the documents and their history,
and `notes/outline-data`, the images and attachments. Each is a
crash-consistent snapshot, which Postgres recovers from like a power cut.

## Rollback

Revert this component's PR: Flux prunes the namespace, and both volumes
with it; the last nightly snapshots stay in restic. Then delete the Outline
client in Pocket ID.
