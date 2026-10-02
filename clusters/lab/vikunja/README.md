# Vikunja

The team's shared task board: projects, tasks, assignees, due dates - one
place where the ten agent seats and the CEO see the same work. The CEO (and
anyone with a passkey) uses the web UI; each seat drives it over the REST
API with its own scoped token, a later ops-orchestrator phase.

At <https://tasks.lab.baakhoff.com>, and on Homepage under Lab.

## How it is reached

Two doors, deliberately different:

- **The gate.** `https://tasks.lab.baakhoff.com` sits behind Pocket ID
  through oauth2-proxy - whole host, `/api` paths included. One passkey to
  reach the UI; below that, Vikunja's own login (a local account until the
  OIDC phase replaces it).
- **The Service, from inside only.**
  `http://vikunja.vikunja.svc.cluster.local` (port 80 -> 3456), reachable
  from slot-1 and nowhere else (`networkpolicy.yaml`). No gate on this path
  by construction - callers skip the proxy by talking to the Service
  directly. API tokens are the authentication here, per seat.

## Setup, in this order

After the merge the pod waits in `CreateContainerConfigError` until step 2
exists. That is not a crash - and not silent: the not-ready warnings
(KubePodNotReady, replicas mismatch, rollout stuck) fire after 15 minutes
and clear the moment the Secret lands.

**1. Reconcile.** On the workstation:

```bash
flux reconcile kustomization flux-system --with-source
kubectl -n vikunja get pods     # CreateContainerConfigError, by design
```

**2. Create the Secret**, from the repo root. The value is any long random
string - it signs tokens and derives crypto, never leaves the cluster, and
losing it logs everyone out but loses no data:

```bash
read -rsp 'vikunja secret: ' SEC; echo

kubectl create secret generic vikunja \
  --namespace vikunja \
  --from-literal=VIKUNJA_SERVICE_SECRET="$SEC" \
  --dry-run=client -o yaml > clusters/lab/vikunja/secret.sops.yaml

unset SEC
sops --encrypt --in-place clusters/lab/vikunja/secret.sops.yaml
```

Commit and push. (The docs' older name for this key,
`VIKUNJA_SERVICE_JWTSECRET`, maps to the same value; the manifest pins the
current name.)

**3. First account.** Reconcile, wait for `Running`, then sign in at
<https://tasks.lab.baakhoff.com> - the gate asks for the passkey, and
Vikunja asks you to register. The first registered user is the instance
admin. Then the seat accounts (one per agent profile).

**4. Close registration.** Once every account exists, set
`VIKUNJA_SERVICE_ENABLEREGISTRATION` to `"false"` in `deployment.yaml`,
commit and push. Verify in step 5.

**5. Verify.**

```bash
# From slot-1: the API answers ungated, and shows the registration state.
kubectl -n hermes-slots exec deploy/slot-1 -- runuser -u hermes -- \
  curl -s http://vikunja.vikunja.svc.cluster.local/api/v1/info
# -> JSON with the version; "registration_enabled": true until step 4 ran.

# From anywhere: the front door answers behind the gate.
curl -s -o /dev/null -w '%{http_code}\n' https://tasks.lab.baakhoff.com/
# -> 302 to the sign-in while logged out; 200 once a browser session exists.
```

## Things to know

- **Single replica, SQLite, 2Gi.** Sized for a team's tasks, not a
  company's; the volume grows in place if attachments ever need it.
- **Registration is a one-time door.** It is only open between step 3 and
  step 4, and even then only behind the gate. First registered user is
  admin.
- **No email is configured** (no SMTP): no reminder mails, no password
  resets by mail. Accounts are made here, behind the gate.
- **API tokens** live under each user's Settings -> API Tokens; each seat
  gets its own, scoped, created by the ops-orchestrator phase. The public
  host stays fully gated - agents use the in-cluster address above.
- **Later phases, each naming its own networkpolicy rule:** OIDC login
  (needs the lab front door), webhooks (needs their targets), SMTP.

## Not backed up yet

As of 2026-10-02 this volume is staged on the parking list - last in line,
behind the six services already waiting. To back it up later, the same
three pieces as Paperless, in this order:

1. the `restic-repo` Secret in the `vikunja` namespace (hand-made, same
   values as elsewhere),
2. the RoleBinding - already in `clusters/lab/backup/rbac.yaml`, landed
   with this component,
3. and last, the `vikunja/vikunja-data` entry in `BACKUP_TARGETS`.

Order is load-bearing: a target whose Secret is missing fails the whole
nightly run, heartbeat included.

## Rollback

Revert this component's PR: Flux prunes the namespace, and the volume and
Secret with it. To keep the tasks, copy the volume out first - the backup
README's restore section is the same drill in reverse.
