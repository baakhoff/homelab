# Termix

[Termix](https://github.com/Termix-SSH/Termix) puts every server in one
browser page: an SSH terminal with tabs and split panes, each host's CPU,
memory, disk, network and uptime, a file manager over SFTP, the host's
Docker containers, and SSH tunnels. From any browser, the phone's included.

At <https://servers.lab.baakhoff.com>, and on Homepage under Platform.

## How it is put together

| File | What |
|---|---|
| `namespace.yaml` | the namespace, at Pod Security `baseline` |
| `deployment.yaml` | the app - nginx, the backend and its plugins in one container - and its settings |
| `pvc.yaml` | SQLite and the plugins, on a 2 GiB Ceph volume |
| `networkpolicy.yaml` | ingress-nginx in; out open but for the NAS, which gets SSH only |
| `service.yaml`, `ingress.yaml` | `servers.lab.baakhoff.com`, behind the admin gate, with the Homepage tile |
| `secret.sops.yaml` | the Pocket ID client and Termix's four keys - **created by hand, step 2** |

The SSH connections start from the pod, not from the browser: the browser
talks to Termix over a WebSocket, and Termix talks SSH to the host. So a
host must be reachable from the cluster, and it sees the connection
coming from the node the pod runs on.

The standard image, not `-full`: the terminal, the file manager, stats,
Docker, tunnels and single sign-on. `-full` adds some fifty plugins
(Proxmox, Kubernetes, an AI chat, ...) that can be added later from the
Plugins tab.

## Login

Pocket ID, through Termix's single sign-on plugin, set from
`deployment.yaml` rather than in the app, and behind the oauth2-proxy gate
as well. In practice it is one passkey. There is no password form and no
sign-up: an account is made at its first sign-in, the Pocket ID client
admits only `lab-admins`, and members of `lab-admins` are Termix admins,
checked at every sign-in.

**This is the most valuable thing in the lab to break into**: it holds a
key to every server. Hence both locks, and the keys inside it are
encrypted with `ENCRYPTION_KEY` from the Secret.

## What it reaches

Anything the pod can reach, on any port: the nodes, the exitnode, and
servers on the internet. The one exception is the NAS, which every other
open namespace is cut off from (`docs/network.md`, "Pods and the LAN"):
Termix gets port 22 there and nothing else.

Not the tailnet: a host reached only through Tailscale, like the
workstation away from home, is out of reach.

## Setup, in this order

Steps 1 to 3 come before the merge. The backup Secret has to be on the
branch: the backup driver fails its whole nightly run on a target whose
namespace has no `restic-repo` Secret. The pod waits in
`CreateContainerConfigError` until step 2's Secret exists.

**1. Pocket ID**, at <https://id.lab.baakhoff.com>, Administration → OIDC
Clients → Add:

| Field | Value |
|---|---|
| Name | Termix |
| Callback URLs | `https://servers.lab.baakhoff.com/plugin-api/sso/callback` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | `lab-admins` |

**2. The Secret**, from the repo root, on this branch. Run the `read`
lines one at a time: pasted together, the rest of the paste becomes the
input. The four keys are generated and never shown.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic termix \
  --namespace termix \
  --from-literal=OIDC_CLIENT_ID="$CID" \
  --from-literal=OIDC_CLIENT_SECRET="$CSEC" \
  --from-literal=JWT_SECRET="$(openssl rand -hex 48)" \
  --from-literal=DATABASE_KEY="$(openssl rand -hex 32)" \
  --from-literal=ENCRYPTION_KEY="$(openssl rand -hex 32)" \
  --from-literal=INTERNAL_AUTH_TOKEN="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml > clusters/lab/termix/secret.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/termix/secret.sops.yaml
```

On the Mac's zsh, the `read` lines are `read -rs 'CID?client id: '; echo`
and `read -rs 'CSEC?client secret: '; echo`.

Create it once. `DATABASE_KEY` opens the database and `ENCRYPTION_KEY`
every saved password and SSH key: new values lock Termix out of both. To
change only the client, edit in place with
`sops clusters/lab/termix/secret.sops.yaml`.

**3. The backup's Secret**, copied from an existing one without the values
touching the screen:

```bash
sops -d clusters/lab/backup/restic-repo-vaultwarden.sops.yaml \
  | sed -E 's/^( +)namespace: vaultwarden$/\1namespace: termix/' \
  > clusters/lab/backup/restic-repo-termix.sops.yaml
grep -E '^ +namespace:' clusters/lab/backup/restic-repo-termix.sops.yaml
sops --encrypt --in-place clusters/lab/backup/restic-repo-termix.sops.yaml
```

The `grep` must print `namespace: termix` before you encrypt. Commit and
push both files; the pre-commit hook checks that they are encrypted.

**4. After the merge**, wait for the pod, then open
<https://servers.lab.baakhoff.com>:

```bash
kubectl -n termix rollout status deploy/termix --timeout=10m
```

The page goes straight to Pocket ID and back. Then look in the Plugins
tab: the standard image includes a telemetry plugin; turn it off.

**5. The servers.** In Termix, make an SSH key (Credentials → New →
Generate), then add each host with it. The public key goes into each
host's `~/.ssh/authorized_keys`:

| Host | Address | User |
|---|---|---|
| node02, node03, node04 | `192.168.68.102` - `.104` | your user on the nodes |
| exitnode | `192.168.68.65` | `baakh` |
| NAS | `192.168.68.105` | `truenas_admin` - the key goes in TrueNAS, Credentials → Users → `truenas_admin` → Authorized Keys |

Stats need nothing installed on the host: Termix reads them over the same
SSH connection.

## What goes to the warehouse

Termix's own log lines, like every pod's, reach `raw.logs` and `ods.logs`
through the collectors: sign-ins and errors. Its audit log, which session
went to which host, stays in its database for now; it has an API with
keys, but no pipeline reads it yet.

## Not in lab-mcp, on purpose

lab-mcp gives the local agent no shell anywhere, and Termix would be one
on every server. How a host is doing is already there: `metrics` reads
Prometheus, which watches every one of these machines.

## Things to know

- **Locked out?** If Pocket ID is down there is no other way in: the
  password form is off. `ALLOW_PASSWORD_LOGIN: "true"` in
  `deployment.yaml` brings it back for an account that has a password.
- **Upgrades:** Renovate opens a PR for each release; Termix migrates its
  database when the new version starts. The nightly backup is the undo.
- **Restart:** `kubectl -n termix delete pod -l app.kubernetes.io/name=termix`

## Backup

`termix/termix-data` is in the nightly backup (`clusters/lab/backup/`). A
restore needs `DATABASE_KEY` and `ENCRYPTION_KEY` from `secret.sops.yaml`
too.
