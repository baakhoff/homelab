# Hermes slots

Instances of [Hermes Agent](https://github.com/NousResearch/hermes-agent), an
AI agent that keeps long-term memory, writes its own skills, runs scheduled
tasks and can talk on Telegram or other platforms. Each slot is reached from
Hermes Desktop as a remote gateway, or in the browser at its own address, and
has its own volume, memory, skills and keys; nothing is shared between them.

| Slot | Remote URL | Memory limit |
|---|---|---|
| `slot-1` | `https://hermes-1.lab.baakhoff.com` | 6Gi |
| `slot-2` | `https://hermes-2.lab.baakhoff.com` | 3Gi |
| `slot-3` | `https://hermes-3.lab.baakhoff.com` | 3Gi |

## What a slot can reach, and why

The agent runs shell commands, and on Kubernetes they run in its own pod, not
in a separate sandbox container. `networkpolicy.yaml` is the containment: the
internet, and nothing of the lab's - no other pod, no Kubernetes API, no node,
no house LAN, no Pi, no tailnet machine. The pods carry no Kubernetes token.

Three exceptions. The lab's HTTPS front door, because the dashboard's login
has to fetch Pocket ID's keys from `id.lab.baakhoff.com` - through it a slot
is an anonymous visitor, and every lab host either sits behind the gate or
has its own login. The Firefly API broker
(`clusters/lab/firefly-broker/`): the CFO seat's tools call it from slot-1,
it holds the Firefly token server-side, and the slot drives the API without
the credential ever being here. It is reachable from slot-1 and nothing
else, and reaches nothing but Firefly in turn. And the team's task board,
Vikunja (`clusters/lab/vikunja/`): every seat's tools call it from slot-1,
with one API token per profile; it is reachable from slot-1 and nothing
else in turn.

## How login works, and why there is no gate

One lock: the dashboard's own Pocket ID login. Without a session everything
but a few read-only endpoints (`/api/health`, `/api/status`, the config
schema, themes) answers 401, and Pocket ID admits only the client's allowed
group. Like everything in the lab, the slots are reachable from the house and
the tailnet only.

They are not behind the oauth2-proxy gate, unlike the other admin tools,
because Desktop cannot pass it. Desktop signs in through the system browser,
gets a Hermes token on a loopback address, and sends that token with every
request; the gate only knows its own cookie and answers each one with a
redirect to `auth.lab.baakhoff.com`, which Desktop reports as "Could not reach
this gateway". A slot holds every key it is given, and one passkey is all that
stands in front of it - which is the reason to give a slot limited keys.

## Setup, in this order

**1. Create one OIDC client in Pocket ID** at `https://id.lab.baakhoff.com`,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Hermes slots |
| Callback URLs | `https://hermes-N.lab.baakhoff.com/auth/callback`, one per slot in the table above |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | just you, e.g. a `hermes-users` group with one member |

**2. Create the Secret on the workstation**, from the repo root. Run the two
`read` lines one at a time: pasted together, the rest of the paste becomes
the input.

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

Commit and push. Until it reconciles, the pods wait in
`CreateContainerConfigError` - not a crash, but not silent either: the
not-ready warnings (KubePodNotReady, replicas mismatch, rollout stuck) fire
after 15 minutes; they clear the moment the Secret lands.

**3. Trust the front door**, once per slot, then restart it. ingress-nginx
ends TLS and talks to Hermes over plain HTTP, saying `X-Forwarded-Proto:
https`. Hermes believes that header only from loopback unless told otherwise,
so it decides the site is HTTP and sets its login cookie without
`SameSite=None; Secure` - and Chromium, which is what Desktop is, drops it on
the way back from Pocket ID. The sign-in then ends in `Missing PKCE state
cookie`. The setting lives in `config.yaml` on the volume, not in an
environment variable:

```bash
kubectl -n hermes-slots exec deploy/slot-1 -- runuser -u hermes -- env HOME=/opt/data \
  hermes config set dashboard.trusted_proxies '["10.42.0.0/16"]'
kubectl -n hermes-slots delete pod -l app.kubernetes.io/name=slot-1
```

`10.42.0.0/16` is the k3s pod range, which is wider than ingress-nginx. That
is safe here because `networkpolicy.yaml` admits no other pod to the
dashboard's port. Once the pod is back, the login cookie should say
`SameSite=none; Secure`:

```bash
curl -s -D - -o /dev/null 'https://hermes-1.lab.baakhoff.com/auth/login?provider=self-hosted' | grep -i set-cookie
```

A bare name with `SameSite=lax` means the setting did not take.

**4. Attach Desktop.** Settings → Gateways → Connection mode → Remote gateway,
Remote URL from the table above. Sign-in opens the browser at Pocket ID. Then
give it a model: an OpenRouter key under the dashboard's keys, or the Claude
subscription below. Keys entered there live in `.env` on the volume, not in
git.

Check from the workstation that a slot answers without the gate:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://hermes-1.lab.baakhoff.com/api/status
```

`200` is right. A `302` means the request met a gate. Not `curl -I`: the
endpoint answers only GET, and a HEAD gets a `405` that looks like a fault.

If the login fails with an error about discovery or keys, the front-door rule
in `networkpolicy.yaml` is not letting the pod reach Pocket ID:

```bash
kubectl -n hermes-slots logs deploy/slot-1 | grep -i -E 'oidc|discovery|jwks'
```

## Claude subscription

The [Claude subscription DirectSDK
plugin](https://hermes-agent.nousresearch.com/docs/plugins/claude-subscription-directsdk)
makes a Claude Pro/Max subscription the model provider, through the official
Claude Code CLI, instead of an API key. Each turn spends the subscription's
Agent SDK allowance, at about 1.7× what the same turn costs in Claude Code
itself, and every slot logged in to the account draws on the same allowance.

The image has Node and npm but not the CLI, so it is installed onto the
volume, where it survives restarts and image upgrades.
`CLAUDE_SUBSCRIPTION_DIRECTSDK_COMMAND` in each Deployment points the plugin
at it. Once per slot, as the `hermes` user so that the files are its own
(`kubectl exec` lands as root):

```bash
kubectl -n hermes-slots exec -it deploy/slot-1 -- runuser -u hermes -- env HOME=/opt/data bash
```

Inside:

```bash
npm install -g --prefix ~/.local @anthropic-ai/claude-code
~/.local/bin/claude auth login
hermes plugins install claude-subscription-directsdk
hermes plugins enable claude-subscription-directsdk-experimental
hermes config set model.provider claude-subscription-directsdk-experimental
hermes config set model.default sonnet
exit
```

`claude auth login` prints a URL: open it, sign in to the Claude account, and
paste the code back. The login lands in `/opt/data/.claude`, on the volume.
The install asks whether to enable the plugin; the `enable` line makes the
answer not matter - a `н` typed on a Russian layout is a no.

Then restart the slot so the gateway loads the plugin:

```bash
kubectl -n hermes-slots delete pod -l app.kubernetes.io/name=slot-1
```

The CLI does not update itself from here. Rerun the `npm install` line to
update it, and `claude auth login` again when the login expires.

## Things to know

- **It keeps working without Desktop.** Desktop is a window onto the slot;
  cron jobs and messaging bots run in the pod whether or not anything is
  attached.
- **What you tell it to install stays.** Packages and files the agent
  creates live on the volume and survive restarts. The image itself is
  replaced on every upgrade.
- **Messaging platforms** (Telegram and others) are set up in the dashboard.
  They connect outwards, so they work without anything exposed to the
  internet. A bot token is one more key on the volume, and each slot needs
  its own bot: Telegram hands a bot's messages to one process at a time.
- **The API server** (an OpenAI-compatible endpoint on port 8642) is off.

## Add a slot, or remove one

Copy `slot-2.yaml` and change `2` to the new number everywhere, including the
host and `HERMES_DASHBOARD_PUBLIC_URL`, then add its callback URL to the
Pocket ID client. Deleting a slot's file deletes its volume with it.

## Not backed up

Nothing here is in the nightly backup, so deleting a slot, or losing its
volume, loses its memories, skills, sessions and keys. To back one up, the
same three pieces as Paperless, whose README has the reasoning: the
`restic-repo` Secret in the `hermes-slots` namespace, a `RoleBinding` for
`backup-driver` there in `clusters/lab/backup/rbac.yaml`, and last
`hermes-slots/slot-N` in `BACKUP_TARGETS`.
