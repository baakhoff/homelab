# Hermes

[Hermes Agent](https://github.com/NousResearch/hermes-agent), an AI agent
that keeps long-term memory, writes its own skills, runs scheduled tasks and
can talk on Telegram or other platforms, with its web dashboard: a chat
terminal in the browser, the agent's configuration and keys, its sessions,
skills, MCP servers and cron jobs.

At <https://hermes.lab.baakhoff.com>, and on Homepage under Lab.

## What it can reach, and why

The agent runs shell commands, and on Kubernetes they run in its own pod,
not in a separate sandbox container. `networkpolicy.yaml` is the
containment: the internet, and nothing of the lab's - no other pod, no
Kubernetes API, no node, no house LAN, no Pi, no tailnet machine. The pod
carries no Kubernetes token.

One exception: the lab's HTTPS front door, because the dashboard's login
has to fetch Pocket ID's keys from `id.lab.baakhoff.com`. Through it the
agent is an anonymous visitor, and every lab host either sits behind the
gate or has its own login.

Giving it a lab service later (filing into Paperless, say) is a deliberate
change to that policy, one Service at a time.

## How login works

Two locks, one passkey: the oauth2-proxy gate, then the dashboard's own
Pocket ID login, which finds the Pocket ID session already there. The
dashboard holds every key the agent has, so it gets both.

## Setup, in this order

The pod waits in `CreateContainerConfigError` until step 2 exists. That is not
a crash and does not alert. It starts by itself once the Secret reconciles.

**1. Create the OIDC client in Pocket ID** at `https://id.lab.baakhoff.com`,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Hermes |
| Callback URL | `https://hermes.lab.baakhoff.com/auth/callback` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | just you, e.g. a `hermes-users` group with one member |

**2. Create the Secret on the workstation**, entering the client ID and secret
Pocket ID shows. `read -rs` keeps both out of the shell history, and nothing
below prints them.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic hermes-oidc \
  --namespace hermes \
  --from-literal=HERMES_DASHBOARD_OIDC_CLIENT_ID="$CID" \
  --from-literal=HERMES_DASHBOARD_OIDC_CLIENT_SECRET="$CSEC" \
  --dry-run=client -o yaml > clusters/lab/hermes/oidc.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/hermes/oidc.sops.yaml
```

Commit and push. The pre-commit hook asserts the file is encrypted.

**3. Sign in** at <https://hermes.lab.baakhoff.com>, and add a model provider
under the dashboard's keys: an OpenRouter key works. Keys entered there live
in `.env` on the volume, not in git.

If the login fails with an error about discovery or keys, the front-door rule
in `networkpolicy.yaml` is not letting the pod reach Pocket ID:

```bash
kubectl -n hermes logs deploy/hermes | grep -i -E 'oidc|discovery|jwks'
```

## Things to know

- **What you tell it to install stays.** Packages and files the agent
  creates live on the volume and survive restarts. The image itself is
  replaced on every upgrade.
- **Messaging platforms** (Telegram and others) are set up in the dashboard.
  They connect outwards, so they work without anything exposed to the
  internet. A bot token entered there is one more key on the volume.
- **The API server** (an OpenAI-compatible endpoint on port 8642) is off.

## Backup - not yet, and in this order

The same three pieces as Paperless, whose README has the reasoning:

1. **The `restic-repo` Secret in the `hermes` namespace**, encrypted into
   `clusters/lab/backup/restic-repo-hermes.sops.yaml`. It uses the same values
   as the other copies and differs only in `metadata.namespace`.
2. **The `RoleBinding`**, already in `clusters/lab/backup/rbac.yaml`.
3. **`hermes/hermes-data` in `BACKUP_TARGETS`**, last, after the Secret has
   reconciled.
