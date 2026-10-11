# Notes (SilverBullet)

Notes in Markdown, in the browser: [[links]] between pages, tasks, queries
over your own notes, and an offline copy of the app that keeps working
without a connection. Every change is kept in a git history inside the
space (Revisions), so any page can be put back the way it was, whoever
changed it.

At <https://notes.lab.baakhoff.com>, and on Homepage under Home.

The `brand` agent pod reads and writes notes too, through SilverBullet's API
with an account of its own, so its changes show under its own name in the
history.

## How login works

Two layers, one passkey in practice. The oauth2-proxy gate stands in front
of the whole host, like every host here; behind it SilverBullet signs you in
with Pocket ID through its own OpenID Connect support, and finds the Pocket
ID session the gate just made. The gate also covers the setup wizard, which
makes whoever reaches it first the admin.

SilverBullet does not create accounts on first sign-in: each one is added
in its Dashboard, and bound to a Pocket ID identity the first time that
person signs in (step 2). One local admin with a password stays, for
recovery if Pocket ID is ever down.

Two paths are outside the gate, on purpose: `/service_worker.js` and
`/.client/`, the app's own code, which SilverBullet's docs require open for
the offline app to work behind a proxy. No note is ever served from them.

## Setup, in this order

**1. Before this merges: the backup's restic credentials** for the
namespace, as the backup README describes. On the workstation, from the
repo root, on this branch:

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: notes/' \
  > clusters/lab/backup/restic-repo-notes.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-notes.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-notes.sops.yaml
```

The `grep` must print `namespace: notes` before you encrypt. Commit and push
to the branch. Without it, the first nightly backup after the merge fails as
a whole, not only this volume.

**2. The setup wizard and Pocket ID**, once Flux has applied the merge and
the pod is `Running`.

Open <https://notes.lab.baakhoff.com>. Past the gate, the wizard asks for:

- the first admin account: a local username and a long password. Keep it in
  Vaultwarden; it is the way in if Pocket ID is down.
- the first space: name it `notes`, and bind it to the path `/` on the
  primary host, so the space is the site and the API is at `/.fs`.

Then, in the Dashboard:

1. **Admin → Server**: set the primary URL to `https://notes.lab.baakhoff.com`.
2. **The space's settings → Revisions**: *Managed*. SilverBullet then commits
   changes to a git repository inside the space about 30 seconds after
   things go quiet.
3. In Pocket ID at <https://id.lab.baakhoff.com>, Administration → OIDC
   Clients → Add:

   | Field | Value |
   |---|---|
   | Name | SilverBullet |
   | Callback URLs | `https://notes.lab.baakhoff.com/.auth/central/oidc/callback` |
   | PKCE | on |
   | Public Client | off |
   | Allowed User Groups | whoever keeps notes here |

4. **Admin → Authentication → OpenID Connect**: issuer
   `https://id.lab.baakhoff.com`, and the client ID and secret Pocket ID
   showed. Run the sign-in test, then enable SSO. The secret is kept in
   `authentication.json` on the volume, which the nightly backup covers; it
   is never in git.
5. **Users → Add user → SSO**, with your Pocket ID email. Give the account
   write on the `notes` space (and admin, if you want to manage the server
   from it). Sign out of the local admin and sign in with the passkey.

SilverBullet refuses a sign-in whose email Pocket ID does not report as
verified: under Administration → Users in Pocket ID, check it is.

**3. The brand agent's account.** In the Dashboard, **Users → Add user**, a
local account:

| Field | Value |
|---|---|
| Username | `brand` |
| Full name | `brand agent` - this is the name its changes carry in the history |
| Space | `notes`, write |

Give it a long random password nobody needs to remember, then issue it an
API token from its entry under Users. Paste the token into a session in the
`brand` pod and ask the agent to keep it under its home directory. It uses:

```
http://silverbullet.notes.svc.cluster.local/.fs/<page>.md
Authorization: Bearer <token>
X-Sync-Mode: true
```

`GET` reads a page, `PUT` writes one, `DELETE` removes one, and `GET /.fs`
lists them all. `X-Sync-Mode` is required: without it SilverBullet answers a
`GET` as a browser's navigation and redirects to the editor.
`clusters/lab/agents/networkpolicy-brand.yaml` is what lets that pod, and no
other agent, reach the server.

**4. Feed the data warehouse.** Airflow's `ingest_silverbullet` DAG copies
every page, text included, into ClickHouse's `raw.silverbullet` every six
hours (`pipelines/dags/ingest.py`); `ods.silverbullet_pages` has one row per
page. It needs a token of a read-only account: **Users → Add user**, local,
username `warehouse`, `notes` space with *read*, and an API token.

On the workstation from the repo root, one line at a time:

```bash
read -rsp 'silverbullet token: ' ST; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["SILVERBULLET_TOKEN"]' "\"$(printf %s "$ST" | base64 | tr -d '\n')\""
unset ST
```

On the Mac's zsh, the first line is `read -rs "ST?silverbullet token: "; echo`.
Commit and push. Once Flux has applied it, restart the scheduler, because a
pod reads its environment only when it starts:

```bash
kubectl -n airflow rollout restart deployment/airflow-scheduler
```

Then trigger `ingest_silverbullet` in the Airflow UI, and after it the
`warehouse` DAG. Until the token exists, that DAG's runs fail and nothing
else is affected.

## Things to know

- **Undoing a change**, yours or the agent's: *Revision: Page History* on
  the page, pick the version, *Restore*. *Revision: Space History* shows
  every commit across the space with who made it.
- **Phones**: the site installs as an app from the browser's menu (Add to
  Home Screen) and works offline, syncing when it is back. There is no
  separate app to install.
- **Only `brand` among the agents.** Another pod gets access with its own
  account here and a door in `networkpolicy.yaml` plus an egress rule on its
  side, like brand's.
- **The volume is 5Gi.** Notes are text; pasted images are what would grow
  it. It expands in place.

## Backup

`notes/silverbullet-data` is in the nightly backup (`clusters/lab/backup/`),
after Dawarich. It holds everything: the pages, their git history, and the
server's accounts, tokens and Pocket ID client.

## Rollback

Revert this component's PR. Flux prunes the namespace, and the volume and
every note with it; the last nightly snapshots stay in restic. Then delete
the SilverBullet client in Pocket ID.
