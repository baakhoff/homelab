# pocket-id

The lab's identity provider: one place to sign in, with a passkey, and OpenID
Connect out the other side for everything that can speak it. Reachable from the
house and the tailnet at `https://id.lab.baakhoff.com`, and from nowhere else.

Passkeys only. There is no password anywhere in this service to phish, reuse,
or rotate; a phone or a hardware key is the credential, and WebAuthn binds it
to the hostname above.

## What is here

| File | What |
|---|---|
| `deployment.yaml` | the server: `ghcr.io/pocket-id/pocket-id`, one replica, `Recreate`, non-root |
| `pvc.yaml` | the database and uploads, 1Gi on `ceph-block` |
| `service.yaml` | ClusterIP on 80 → 1411 |
| `ingress.yaml` | `id.lab.baakhoff.com` under the lab wildcard, with the Homepage tile |
| `encryption-key.sops.yaml` | the key that encrypts the OIDC signing keys at rest — **created by hand, see below** |

## The one secret

Pocket ID refuses to start without `ENCRYPTION_KEY`. It is the key to the OIDC
token signing keys in the database, so losing it means every client has to be
re-trusted and every session is void; it is therefore in git, encrypted, and
the volume and this Secret are only useful together.

It is created once, on the workstation, and never typed into anything else:

```bash
kubectl create secret generic pocket-id-encryption-key \
  --namespace pocket-id \
  --from-literal=ENCRYPTION_KEY="$(openssl rand -base64 32)" \
  --dry-run=client -o yaml > clusters/lab/pocket-id/encryption-key.sops.yaml

sops --encrypt --in-place clusters/lab/pocket-id/encryption-key.sops.yaml
```

The pre-commit hook asserts the staged file is encrypted, provided
`git config core.hooksPath .githooks` has been run in the clone. Without the
Secret the pod sits in `CreateContainerConfigError` — not a crash, so nothing
alerts — and starts by itself once the Secret reconciles.

## First run

`/setup` creates the first admin and is open to anyone who can reach the
hostname until it has been used once. The hostname is reachable the moment the
pod is ready — the wildcard already points at the nodes — so the sequence is:
merge, wait for the pod, open `https://id.lab.baakhoff.com/setup`, register a
passkey. The window is the LAN and the tailnet for a few minutes, which is an
acceptable exposure and not a negligible one; do not merge this and walk away.

After that, `/setup` is closed and the admin adds everyone else in the UI.
Signups are disabled by default and stay a UI setting: the Deployment says why
setting them as an env var would do nothing.

## What consumes it

| Client | Where | Role mapping |
|---|---|---|
| Grafana | `auth.generic_oauth` in `clusters/lab/monitoring/helmrelease.yaml`; id and secret in `grafana-oidc.sops.yaml` beside it | members of the Pocket ID group `grafana-admins` are org Admins, everyone else Viewer, re-evaluated at every login |
| Headlamp | `config.oidc` in `clusters/lab/headlamp/helmrelease.yaml`; id and secret in `headlamp-oidc.sops.yaml`; the apiserver side in `hosts/nodes/k3s-config.yaml` | the Pocket ID group `headlamp-users` maps to `oidc:headlamp-users`, bound read-only in `clusters/lab/headlamp/rbac.yaml`; anyone outside it logs in and sees nothing |
| Paperless | `PAPERLESS_SOCIALACCOUNT_PROVIDERS` in `clusters/lab/paperless/env.sops.yaml`, policy in the Deployment beside it | the Pocket ID group `paperless-admins` maps to superuser, re-evaluated at every login; who may log in at all is the client's *Allowed User Groups* |
| oauth2-proxy | `clusters/lab/oauth2-proxy/`; gates Homepage, Prometheus and Alertmanager through ingress-nginx `auth-url` annotations | yes/no only: anyone the client admits. Restrict on the client's *Allowed User Groups* tab in Pocket ID |

**Not behind it, on purpose: Vaultwarden.** The vault holds the passkeys. An
identity provider in front of the thing that stores its own credential is a
loop, and the day it closes is the day you are locked out of both.

Each client is created in Pocket ID's admin UI first, because the client secret
has to exist before the manifest that references it can. The callback URL for
Grafana is `https://grafana.lab.baakhoff.com/login/generic_oauth`, and for
Paperless `https://paperless.lab.baakhoff.com/accounts/oidc/pocketid/login/callback/`.


## Backup — not yet, and in this order

The database is the only thing here that is not reconstructible: it holds the
passkey public keys, the users and the OIDC clients. Rebuilding from nothing is
possible — re-register every passkey, re-create every client — which puts it a
notch below the Minecraft world in irreplaceability and well above "just redeploy
it". It is not in the nightly backup yet because that takes the same three things
the Minecraft README lists, and the first cannot come from this repository:

1. **The `restic-repo` Secret in the `pocket-id` namespace.** Same values as the
   other copies, differing only in `metadata.namespace`; the backup README has
   the exact commands. Encrypt it into
   `clusters/lab/backup/restic-repo-pocket-id.sops.yaml`.
2. **The `RoleBinding`** — already in `clusters/lab/backup/rbac.yaml`, landed
   with the server. Harmless ahead of time.
3. **`pocket-id/pocket-id-data` in `BACKUP_TARGETS`** in
   `clusters/lab/backup/cronjob-backup.yaml`. **Last**, in a commit after the
   Secret has reconciled: the driver fails the whole run, heartbeat included, on
   a target whose Secret is missing.

Crash-consistent RBD snapshot of a SQLite database in WAL mode, taken while the
server runs — the same trade every other target makes, and one SQLite is built
to survive.

## Operating it

- **Upgrades are one-way.** The server migrates the database forward on start and
  refuses to run an older version against it afterwards (`ALLOW_DOWNGRADE`
  exists and is off). Rolling back an image bump means restoring the volume,
  which is the second reason the backup above matters.
- **Changing the hostname is not an option**, in the same way it is not for
  Vaultwarden: `APP_URL` is the WebAuthn origin, and every passkey is bound to
  it.
- **Audit log IPs** all read as a `10.42.x.x` address. That is the ServiceLB hop,
  not a bug in Pocket ID; the Deployment says what it would take to fix.
