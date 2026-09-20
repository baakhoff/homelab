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

## What it is for

Nothing consumes it yet. The two obvious clients on this cluster, in the order
they are worth doing:

1. **Grafana** — replaces the shared admin password with a login button. Native
   OIDC in `grafana.ini`; the client secret is a SOPS Secret in `monitoring`.
2. **Headlamp** — replaces pasting a ServiceAccount token. Native OIDC in the
   chart, but the *cluster* has to trust the issuer too: OIDC flags on the k3s
   apiserver on all three nodes, which is a node-side change outside GitOps.

Each of those is its own change, with its own client created in Pocket ID's
admin UI first, because the client secret has to exist before the manifest that
references it can.

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
