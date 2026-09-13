# Agent pods

Claude Code instances run in the cluster as **Remote Control servers**: one
Deployment per project in the `agents` namespace, each running
`claude remote-control` in its own checkout on its own volume. The sessions
appear at [claude.ai/code](https://claude.ai/code) and in the Claude app, which
is where you talk to them. Nothing listens on a port: the server makes outbound
HTTPS calls to Anthropic and polls for work.

**Why server mode.** A pod has no terminal. `claude remote-control` is the mode
built for that: it serves sessions to the app and does nothing else. One server
serves many concurrent sessions, each in its own git worktree of the project.

**Why one pod per project.** Each project gets its own limits, its own replica
count (0 = parked), and the scheduler places it on whichever node has room. So
the projects together are bounded by the cluster, not by one node, and a node
reboot takes down a share of them rather than all.

Manifests: `clusters/homelab/agents/`. Image: `images/claude-agent/`.

## Add a project

1. Copy `clusters/homelab/agents/homelab.yaml` to `<project>.yaml` and change
   the names, `REPO_URL`, and the resources. A private repo needs a `GH_TOKEN`
   env from a SOPS-encrypted Secret: a fine-grained token scoped to that repo.
2. Open a PR, merge. Flux creates the volume and the pod. The pod clones the
   repo and then waits, and says so in its log, because the rest is interactive.

## Bootstrap, once per project

The login, the workspace-trust dialog and Remote Control's own one-time
confirmation all need a person. All of it lands on the volume, so it survives
restarts and parking.

```bash
kubectl -n agents exec -it deploy/homelab -- bash
```

Inside the pod, in order:

```
claude auth login
```

It prints a URL. Open it on your workstation, sign in, and paste the code the
browser shows back into the pod. Remote Control needs this full login; the
long-lived token from `claude setup-token` can only make model requests and
cannot open Remote Control sessions.

```
cd ~/work/homelab && claude
```

Accept the workspace trust dialog, then `/exit`.

```
claude remote-control
```

Answer `y` to "Enable Remote Control?". When it shows a session URL the account
is eligible and the connection works. Press Ctrl-C.

```
touch ~/.claude/.remote-control-enabled && exit
```

Within a minute the entrypoint starts the server. Its log shows the session
URL:

```bash
kubectl -n agents logs deploy/homelab -f
```

What a healthy server prints: a `Connected · homelab` line, the capacity
(`1/32` with one session), a note that new sessions get an isolated worktree,
and a claude.ai/code link.

Open claude.ai/code or the app: the session is listed under the project name
with a green dot. For permission prompts on your phone, run `/config` in a
session and enable "Push when actions required".

## Park and wake

```bash
kubectl -n agents scale deploy/homelab --replicas=0
```

and back to `1`, or use the scale control in Headlamp. An idle server costs
about 300 MB, so parking is for when memory is actually short.

## Smoke test, once after the first deploy

Verify the network boundary instead of trusting it. From the pod, the internet:

```bash
kubectl -n agents exec deploy/homelab -- curl -sS -m 5 -o /dev/null -w '%{http_code}\n' https://api.github.com/
```

expects `200`. And the Kubernetes API:

```bash
kubectl -n agents exec deploy/homelab -- curl -sS -m 5 https://kubernetes.default.svc/; echo "exit $?"
```

expects the connection to fail before any TLS handshake: either refused at
once, exit code 7, or a timeout, exit code 28. Which one depends on the policy
controller: k3s's rejects denied packets, so it is exit 7 here. A certificate
error, exit code 60, means the API server answered, so the policy is not
being enforced.

## When the login expires

`/status` in a session shows the login row and warns three days ahead. Renew
with `claude auth login` through `kubectl exec`, as above. The marker file
stays.

## Known limits

- No Docker inside the pod. Projects whose tests need a Docker daemon are not
  served yet.
- No cluster access, no LAN, no tailnet from inside, by policy.
- Deleting a project's manifest prunes its volume: the checkout, the login and
  any uncommitted work go with it. Commit or push first.
- The volumes are excluded from the nightly restic backup, see
  `hosts/node01/backup/restic-excludes.txt`: everything on them is a clone, a
  login, or a cache.
