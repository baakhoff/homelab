# Hermes slots

Two test instances of [Hermes Agent](https://github.com/NousResearch/hermes-agent)
for Hermes Desktop to attach to as remote gateways, beside the main Hermes in
[`../hermes/`](../hermes/README.md). Each has its own volume, memory, skills
and keys; nothing is shared between them or with the main one.

| Slot | Remote URL |
|---|---|
| `slot-1` | `https://hermes-1.lab.baakhoff.com` |
| `slot-2` | `https://hermes-2.lab.baakhoff.com` |

## How login works, and why there is no gate

One lock: the dashboard's own Pocket ID login. Without a session everything
but a few read-only endpoints (`/api/health`, `/api/status`, the config
schema, themes) answers 401, and Pocket ID admits only the client's allowed
group. Like everything in the lab, the slots are reachable from the house and
the tailnet only.

The main Hermes also sits behind the oauth2-proxy gate, and that is why
Desktop cannot attach to it. Desktop signs in through the system browser,
gets a Hermes token on a loopback address, and sends that token with every
request; the gate only knows its own cookie and answers each one with a
redirect to `auth.lab.baakhoff.com`, which Desktop reports as "Could not reach
this gateway". So the slots have no gate, and are for testing: put
throwaway or tightly limited model keys in them, not the main Hermes's.

## Setup, in this order

**1. Create one OIDC client in Pocket ID** at `https://id.lab.baakhoff.com`,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Hermes slots |
| Callback URLs | `https://hermes-1.lab.baakhoff.com/auth/callback` and `https://hermes-2.lab.baakhoff.com/auth/callback` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | just you, as for the main Hermes |

**2. Create the Secret on the workstation.** One Secret serves both slots.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic hermes-slots-oidc \
  --namespace hermes-slots \
  --from-literal=HERMES_DASHBOARD_OIDC_CLIENT_ID="$CID" \
  --from-literal=HERMES_DASHBOARD_OIDC_CLIENT_SECRET="$CSEC" \
  --dry-run=client -o yaml > clusters/lab/hermes-slots/oidc.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/hermes-slots/oidc.sops.yaml
```

Commit and push. Until it reconciles, both pods wait in
`CreateContainerConfigError`, which is not a crash and does not alert.

**3. Attach Desktop.** Settings → Gateways → Connection mode → Remote gateway,
Remote URL from the table above. Sign-in opens the browser at Pocket ID; then
add a model provider under the dashboard's keys, as for the main Hermes.

Check from the workstation that a slot answers without the gate:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://hermes-1.lab.baakhoff.com/api/status
```

`200` is right. A `302` means the request met a gate. Not `curl -I`: the
endpoint answers only GET, and a HEAD gets a `405` that looks like a fault.

**4. The Claude subscription as the model**, if wanted: the steps in [the main
Hermes's README](../hermes/README.md#claude-subscription), with the slot's
namespace, Deployment and label:

```bash
kubectl -n hermes-slots exec -it deploy/slot-1 -- runuser -u hermes -- env HOME=/opt/data bash
kubectl -n hermes-slots delete pod -l app.kubernetes.io/name=slot-1
```

Every slot logged in to the account draws on the same subscription allowance.

## Add a slot, or remove one

Copy `slot-1.yaml` and change `1` to the new number everywhere, including the
host and `HERMES_DASHBOARD_PUBLIC_URL`, then add its callback URL to the
Pocket ID client. Deleting a slot's file deletes its volume with it.

## Not backed up

Deliberately: these are test instances. Anything worth keeping belongs in the
main Hermes, whose README has the backup steps.
