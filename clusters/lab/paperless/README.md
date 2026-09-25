# paperless

The household's paper: scanned or photographed, OCR'd in Danish and English,
tagged, searchable, and kept in one place that is backed up. Reachable from the
house and the tailnet at `https://paperless.lab.baakhoff.com`, and from nowhere
else. Sign-in is a passkey through Pocket ID.

## What is here

| File | What |
|---|---|
| `deployment.yaml` | the server, from `images/paperless-ngx/` (upstream plus extra OCR languages), and its Redis broker beside it; one replica, `Recreate`, non-root |
| `pvc.yaml` | database, search index, originals, archived PDFs and thumbnails - all on one 20Gi `ceph-block` volume, and the file says why one |
| `service.yaml` | ClusterIP on 80 → 8000 |
| `ingress.yaml` | `paperless.lab.baakhoff.com` under the lab wildcard, with the Homepage tile |
| `env.sops.yaml` | the Django secret key and the Pocket ID client - **created by hand, see below** |
| `ai.sops.yaml` | the OpenRouter API key for the AI features - **created by hand, see below** |

## The one Secret, and it comes first

Two values, one Secret, neither of which can come from this repository. The pod
sits in `CreateContainerConfigError` until it exists - not a crash, so nothing
alerts - and starts by itself once it reconciles.

**1. Create the OIDC client in Pocket ID** at `https://id.lab.baakhoff.com`,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Paperless |
| Callback URL | `https://paperless.lab.baakhoff.com/accounts/oidc/pocketid/login/callback/` |
| Allowed User Groups | the group of people who may use the archive, e.g. `paperless-users` |

The `pocketid` in the callback is the `provider_id` from the JSON below; the
two have to match. Create the group `paperless-admins` too, and put yourself in
it: members become Paperless superusers on login, and nobody else can create
tags, correspondents' rules or other users. Every account needs a verified
email, as the oauth2-proxy README notes.

**2. Create the Secret on the workstation**, entering the client id and secret
Pocket ID shows you. `read -rs` keeps both out of the shell history; nothing
below echoes them.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic paperless-env \
  --namespace paperless \
  --from-literal=PAPERLESS_SECRET_KEY="$(openssl rand -base64 48)" \
  --from-literal=PAPERLESS_SOCIALACCOUNT_PROVIDERS="{\"openid_connect\":{\"OAUTH_PKCE_ENABLED\":true,\"SCOPE\":[\"openid\",\"profile\",\"email\",\"groups\"],\"APPS\":[{\"provider_id\":\"pocketid\",\"name\":\"Pocket ID\",\"client_id\":\"$CID\",\"secret\":\"$CSEC\",\"settings\":{\"server_url\":\"https://id.lab.baakhoff.com\"}}]}}" \
  --dry-run=client -o yaml > clusters/lab/paperless/env.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/paperless/env.sops.yaml
```

Commit and push; the pre-commit hook asserts the file is encrypted. The
`groups` scope is what carries the `paperless-admins` membership; drop it and
every login is a plain user.

`PAPERLESS_SECRET_KEY` signs sessions. Rotating it logs everyone out and
nothing more, so it is not precious the way Pocket ID's encryption key is; it
is in git encrypted because that is where every Secret here lives.

## The second Secret: AI

Suggestions for tags, correspondents, document types and titles, and a chat
box that answers questions about a document, all come from a hosted model:
DeepSeek V4.1 Flash through OpenRouter, configured on the Deployment. What
that means, plainly: **the OCR'd text of a document is sent to OpenRouter, and
from there to whichever provider serves the model, every time a suggestion is
generated or a question asked.** Nothing is sent for a document you never ask
about, and the feature is one env var to turn off. Before turning it on, in
OpenRouter's settings, disable training on your prompts and consider
restricting to providers with a zero-retention policy; both are account-level
switches on their side, not anything this repository can set.

One key, one Secret, same recipe as the first:

```bash
read -rsp 'openrouter api key: ' KEY; echo

kubectl create secret generic paperless-ai \
  --namespace paperless \
  --from-literal=PAPERLESS_AI_LLM_API_KEY="$KEY" \
  --dry-run=client -o yaml > clusters/lab/paperless/ai.sops.yaml

unset KEY
sops --encrypt --in-place clusters/lab/paperless/ai.sops.yaml
```

Commit and push. Make the key in OpenRouter with a spending limit: Flash is
cheap - fractions of a cent per document - but a limit turns a runaway loop
into a stopped feature rather than a bill.

**Embeddings** go through OpenRouter as well, to `baai/bge-m3`, the
multilingual model upstream recommends. They power similar-document search
and let chat pull in related documents. The index is built by a nightly task
at 02:10 and covers every document, so this is the one AI feature that sends
text you did not explicitly ask about - all of it, once, and then each new
document as it arrives. Cost is a cent per million tokens, so a whole archive
is small change; the privacy trade is the one to weigh. Set
`PAPERLESS_AI_LLM_EMBEDDING_BACKEND` to nothing to keep suggestions and
single-document chat without it. Changing the embedding model later means
rebuilding the index; the Paperless administration docs have the command.
The offline alternative is a Hugging Face model in the pod, upstream's pick
being `intfloat/multilingual-e5-small`, at roughly another gigabyte of memory
on the Deployment.

## First run

Merge, wait for the image build if it is the first one (below), then open the
hostname and press *Pocket ID*. Your account is created on that login and, if
you are in `paperless-admins`, is a superuser. There is no `/setup` window and
no default admin password: an account exists only for someone Pocket ID has
already admitted.

Then, in the UI: create the correspondents and tags you expect to use, and turn
on *auto* matching for them. Paperless learns from the first few documents you
tag by hand and starts suggesting after that.

## Getting documents in

**Browser**: drag files onto any page, or *Documents → Upload*. **Phone**: the
share sheet in either app below sends a photo or PDF straight to the archive,
and the OCR runs here, not on the phone.

The phone apps talk to the API and cannot do the passkey round-trip, so they
sign in with a token or a password instead:

- *Swift Paperless* (iOS) accepts an API token. Generate one under your profile
  (top right) → *API Auth Token*.
- *Paperless Mobile* (Android and iOS) wants a username and password. Your
  account has none, being made by Pocket ID; a superuser sets one under
  *Users & Groups*. The password unlocks only the API, not the passkey login,
  and only for that account.

The regular login form is left enabled for exactly this, and for the day Pocket
ID is down.

## Backup - not yet, and in this order

The volume is the only thing here that is not reconstructible, and it is the
whole point of the service. Same three pieces as Minecraft and Pocket ID, and
the first cannot come from this repository:

1. **The `restic-repo` Secret in the `paperless` namespace.** Same values as
   the other copies, differing only in `metadata.namespace`; the backup README
   has the commands. Encrypt it into
   `clusters/lab/backup/restic-repo-paperless.sops.yaml`. It has to point at
   the SAME repository as the others: the weekly prune job reads only the copy
   in the `backup` namespace, so a second repository would be written nightly
   and never pruned or checked.
2. **The `RoleBinding`** - already in `clusters/lab/backup/rbac.yaml`, landed
   with this. Harmless ahead of time.
3. **`paperless/paperless-data` in `BACKUP_TARGETS`** in
   `clusters/lab/backup/cronjob-backup.yaml`. **Last**, in a commit after the
   Secret has reconciled: the driver fails the whole run, heartbeat included,
   on a target whose Secret is missing.

What that backup is: a crash-consistent RBD snapshot of the one volume, taken
while the server runs. SQLite in WAL mode is built to survive exactly that, and
the originals are plain files. `PAPERLESS_FILENAME_FORMAT` on the Deployment
is chosen so the restored tree is readable by a human even if the database is
not: year, correspondent, title.

## Operating it

- **Upgrades are one-way.** Django migrates the database forward on start.
  Rolling back an image bump means restoring the volume.
- **The image is ours.** Renovate bumps upstream in
  `images/paperless-ngx/Dockerfile`, the workflow publishes the tag, Renovate
  then offers it to `deployment.yaml`. Two PRs per upgrade, as for the agent
  image, and for the same reason.
- **Locked out of admin.** `paperless-admins` is re-evaluated on every login,
  including your own, so an admin removed from the group is a viewer at the
  next sign-in. If Pocket ID itself is the problem, the local escape hatch is a
  superuser made from inside the pod, on the workstation:

  ```
  kubectl -n paperless exec -it deploy/paperless -c paperless -- python3 manage.py createsuperuser
  ```

  That account signs in through the password form.
- **AI off.** Set `PAPERLESS_AI_ENABLED` to `"false"` on the Deployment; the
  Secret can stay or go. Nothing already in the archive depends on it.
- **OCR quality.** `dan+eng` is tried on every page. A document that comes out
  as gibberish is usually a photo rather than a scan: retake it flat, in light,
  and re-upload. *Documents → the document → Actions → Redo OCR* also exists.
- **Storage.** *Documents* shows the count; `kubectl -n paperless exec
  deploy/paperless -c paperless -- df -h /data` shows the volume. Growing it is
  an edit to `pvc.yaml`.
