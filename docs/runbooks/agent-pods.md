# Agent pods

Claude Code instances run in the cluster as **Remote Control servers**: one
Deployment per project — or per general slot — in the `agents` namespace, each
running `claude remote-control` on its own volume. The sessions
appear at [claude.ai/code](https://claude.ai/code) and in the Claude app, which
is where you talk to them. Nothing listens on a port: the server makes outbound
HTTPS calls to Anthropic and polls for work.

**Why server mode.** A pod has no terminal. `claude remote-control` is the mode
built for that: it serves sessions to the app and does nothing else. One server
serves many concurrent sessions, each in its own git worktree of the project.

**Why one pod per project.** Each one gets its own limits, its own replica
count (0 = parked), and the scheduler places it on whichever node has room. So
they are bounded together by the cluster, not by one node, and a node reboot
takes down a share of them rather than all.

**Named pods and general slots.** A pod with a `REPO_URL` clones that repo on
first start and serves sessions from it. A pod without one is a **general
slot**: empty `~/work`, and you clone whatever you want from inside a session.
Slots exist because `REPO_URL` and `PROJECT` are plain environment variables in
a public repository — a named pod publishes the project's name and the existence
of its repo, permanently. An anonymous slot publishes neither. What it costs is
worktree isolation; [the image README](../../images/claude-agent/README.md) has
the full trade.

Manifests: `clusters/lab/agents/`. Image:
`images/claude-agent/`.

**The two clusters differ in one line: the storage class.** node01's pods take
`local-path`, a directory on the node, so a pod can only run where its home
already is and a node rebuild takes the login, the checkout and every worktree
with it. The lab cluster's take `ceph-block`, an RBD image replicated across
all three nodes and mapped by whichever one runs the pod — so the home
directory follows the pod, and losing a node costs a restart rather than a
rebuild.

That also changes what a *hard* node failure looks like. A ReadWriteOnce image
is mapped by one node at a time, and Kubernetes will not map it elsewhere while
it believes the old node might still be writing. On a clean drain the handover
is immediate; on a node that simply vanishes, the pod stays `Terminating` for
roughly six minutes while the node is marked unreachable and the volume is
force-detached. Waiting is the correct behaviour — the alternative is two
writers on one filesystem.

## Add a project or a slot

1. Copy the cluster's own `agents/homelab.yaml` and change the name — it appears
   in four places (PVC, Deployment, and two label blocks) plus `PROJECT` — and
   the resources. For a named project set `REPO_URL`; for a general slot delete
   that env entry. A private repo cloned at startup needs a `GH_TOKEN` env from
   a SOPS-encrypted Secret, a fine-grained token scoped to that repo; a slot
   does not, because `gh auth login` inside the pod covers every repo the
   account can see. If that clone fails the pod still comes up and says why in
   its log — it has to, because the fix is `kubectl exec` into a running
   container. Authenticate, restart the pod, and the clone is retried.
2. Check the namespace quota first. `agents/resourcequota.yaml` sets `pods`, and
   a pod over that number is rejected **at admission** — a Deployment that never
   scales up plus a quota event, which reads like a scheduling problem and is
   not one.
3. Open a PR, merge. Flux creates the volume and the pod. The pod clones the
   repo if it has one, then waits, and says so in its log, because the rest is
   interactive.

## Bootstrap, once per pod

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

If this pod will touch GitHub — and a general slot will, that is the point —
authenticate `gh` in the same sitting:

```
gh auth login
```

Choose HTTPS and answer yes to authenticating Git with your GitHub credentials,
which installs the credential helper. Both land under `~/.config/gh` and
`~/.gitconfig`, which are on the volume, so this survives restarts and parking
exactly like the Claude login. One pod, one account — which is how a slot for a
second GitHub identity stays cleanly separate from the others.

GitLab works the same way over HTTPS with a project or personal access token;
egress is open to the internet, so `gitlab.com` is reachable. `glab` is not in
the image.

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

## GitLab from a pod

`glab` is in the image alongside `gh`. Authenticating it has two traps, both of
which present as a credential problem and are not one.

```
glab auth login --hostname gitlab.example.org --stdin < token-file
glab config set host gitlab.example.org --global
glab api user
```

**`glab auth login` can report success while `glab api` returns 401.** The login
validates against the hostname you named; `glab api` with no host goes to the
*default* host, which is `gitlab.com` until you set it. `glab api user` is the
check that means something — `glab auth status` reports "not authenticated" for
some configurations that work fine.

**`glab config set` writes repo-local config by default** and fails with "not a
Git repository" anywhere else. `--global` is required, and not only in `/tmp`: a
general slot's working directory is the parent of its checkouts, not a repo.
`--host` sets a per-host value and writes it globally too.

There is no OS keyring in the container, so glab stores the token as plaintext
in `~/.config/glab-cli/config.yml` and says so. That file is on the volume,
which nothing backs up — and a token there carries whatever the account can do,
bypassing any 2FA on it, so scope it to the project and give it an expiry.

For a host reachable only through the proxy below, put the proxy in glab's
config rather than the environment — agent sessions run through non-interactive
shells that never read `~/.bashrc`:

```
glab config set proxy socks5h://127.0.0.1:1080 --host gitlab.example.org
```

## A remote that is only reachable through a proxy

Some remotes are not on the public internet — a corporate GitLab behind a VPN,
say. A pod cannot reach those directly and should not be able to: it has no LAN
and no tailnet by policy, and that boundary is the reason an agent is safe to run
here at all. Relaxing the NetworkPolicy is the wrong fix.

A **userspace** proxy is the right one. A tunnel that needs a tun device also
needs `NET_ADMIN`, which these pods do not have and should not get; a client that
listens on `127.0.0.1` as a SOCKS proxy needs no capability whatsoever. Its own
outbound connection goes to a server on a public address, which the policy
already allows.

Run the client as a **native sidecar** — an `initContainer` with
`restartPolicy: Always` — so it starts before the agent container and is torn
down after it. `clusters/lab/agents/slot-3.yaml` is the worked example. The
agent in that slot cannot reach its remote without the proxy, and a sidecar
makes "the proxy is up first" a property of the platform rather than of
remembering to start it.

Two things the sidecar costs. Its requests are **added** to the pod's total
rather than max()'d like an ordinary initContainer's, so `resourcequota.yaml`
has to account for it or the pod is rejected at admission. And its config holds
the server address and credentials, so it is entered by a person onto the volume
and never committed — this repository is public.

A static binary under `~/.local/bin` started by hand also works, and survives
restarts because `$HOME` is the volume, but nothing restarts *it*: after any pod
restart the remote stops resolving until someone notices. Fine for trying
something out, not for a slot you rely on.

Either way, point ssh at it:

```
# ~/.ssh/config
Host gitlab.example.internal
    ProxyCommand nc -x 127.0.0.1:1080 %h %p
```

`nc` is in the agent image for exactly this. For an HTTPS remote the equivalent is
`git config --global http.proxy socks5h://127.0.0.1:1080`.

**Use `socks5h`, not `socks5`.** The `h` sends the *hostname* to the proxy
instead of resolving it locally. Without it, git resolves an internal-only name
inside the pod, gets `NXDOMAIN` or a private address the policy blocks, and fails
before the tunnel is used at all. The `nc -x` form above has the same property:
`%h` is passed through, and the far side resolves it.

The proxy's own config carries credentials, so it belongs on the volume, entered
by a person — not in this repository, which is public.

## Park and wake

```bash
kubectl -n agents scale deploy/homelab --replicas=0
```

and back to `1`, or use the scale control in Headlamp. An idle server costs
about 300 MB, so parking is for when memory is actually short.

**This parks a pod until Flux next reconciles, not permanently.** The manifest
says `replicas: 1`, so a manual scale is drift and gets corrected within minutes
— which is the right behaviour in general and a surprise here. For a pod that
should stay down, change `replicas` in its file and merge. Suspending the
Kustomization also works and is worse: it stops applying the whole cluster, and
it does so silently.

## Restart a pod

The image tag is the Claude Code version and is mutable, so a change to the
image that is not a CLI release rebuilds the same tag. `imagePullPolicy: Always`
means a new pod pulls it; the running one has to be replaced for that to happen.

Replace it by deleting the pod, not with `rollout restart`:

```bash
kubectl -n agents delete pod -l app.kubernetes.io/name=brand
```

**`kubectl rollout restart` costs two restarts here, not one.** It works by
stamping `kubectl.kubernetes.io/restartedAt` into the pod template, and the
template is what Flux owns. The manifest in git carries no such annotation, so
the next reconcile strips it — a second change to the template, a second
ReplicaSet, a second full rollout, ten minutes after the first and with no
obvious cause. It is the same drift as a manual `kubectl scale` above, except
the correction is not a scale but a restart of everything you restarted.
Deleting a pod avoids this because the pod is not an object Flux manages: the
Deployment is untouched, so there is nothing to revert.

Either way the replacement can take a minute to start. The volumes are
ReadWriteOnce and the strategy is `Recreate`, so the old pod is gone before the
new one is scheduled, and the scheduler is free to place it on a different node
— where the attach blocks on `FailedAttachVolume`, *"already exclusively
attached to one node, waiting on detach"*, until the old node's
`VolumeAttachment` clears. That is correct behaviour and it resolves itself in
tens of seconds. Restarting all eight pods at once means eight of those at once,
and the namespace is briefly unavailable.

What survives a restart is what is on the volume, which is all of `/home/node`:
the login, `~/.claude`, keys, tool configuration, repositories, uncommitted
work. What does not survive is anything running at that moment — an in-flight
session is killed, along with any background process started by hand inside the
container.

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

## An ssh key on the volume

A project whose remote is ssh needs a private key, and the natural place is
`~/.ssh/` on the volume so it survives restarts. Two things about that.

`fsGroup` rewrites its mode. The kubelet does not only set group ownership on a
volume — it walks it and **adds group read/write** — so a key written `0600`
comes back `0660`, and ssh refuses a group-readable private key outright rather
than offering it. The remote then answers `Permission denied (publickey)`, which
points at the wrong end entirely. `fsGroupChangePolicy: OnRootMismatch` in the
pod's `securityContext` stops the rewrite; the manifests here set it.

And prefer a **deploy key** scoped to the one project over a personal key that
opens everything you have access to. The pod runs a model's commands, and while
the NetworkPolicy keeps it off the LAN and the tailnet, anything on the public
internet is still reachable from inside. A key's blast radius is whatever it
unlocks.

## The pod that edits this repo runs in this cluster

The `homelab` pod is a Claude Code server working on the repository that defines
the cluster it runs in. That is circular, and it fails in the one case where it
would be most useful: if the cluster is down, so is the agent that could help
reason about why.

[ADR 0006](../decisions/0006-claude-code-remote-control-pods.md) argued for
moving agents *off* the workstation and did not consider this, so it is recorded
here rather than there. The mitigation is not a second cluster — it is
remembering that the agent is a convenience and not a dependency:

- Recovery work is done from the **workstation**, which holds a checkout and can
  run Claude Code locally. [Disaster recovery](disaster-recovery.md) assumes
  nothing in the cluster is available.
- Nothing an agent pod holds is an original. The repo is on GitHub, the age key
  is in the emergency kit, and the volumes are excluded from backup precisely
  because everything on them is a clone, a login or a cache.

The failure is mild in practice and worth naming anyway: an agent restarted
mid-change during its own cluster's image update, which is exactly the shape of
the problem in miniature.

## Known limits

- No Docker inside the pod. Projects whose tests need a Docker daemon are not
  served yet.
- A general slot has no `--spawn worktree`, because there is no repository at
  its working directory to branch from. Two concurrent sessions in one slot
  share a directory and can edit the same files. Giving the slot a `REPO_URL`
  restores the isolation.
- No cluster access, no LAN, no tailnet from inside, by policy.
- Deleting a project's manifest prunes its volume: the checkout, the login and
  any uncommitted work go with it. Commit or push first.
- Nothing backs the volumes up, on either cluster — and on both it is now a
  choice rather than an absence. On node01 they are excluded from the nightly
  restic run, see `hosts/node01/backup/restic-excludes.txt`; on the lab cluster
  a backup exists and agent volumes are simply not among its targets, see
  [`clusters/lab/backup/`](../../clusters/lab/backup/README.md). Everything on
  them is a clone, a login, or a cache — replication is not a backup, and three
  copies of a deleted volume is still no copies.
