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

Manifests: `clusters/homelab/agents/` and `clusters/lab/agents/`. Image:
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

Run the client in the pod — a static binary under `~/.local/bin` survives
restarts, because `$HOME` is the volume — and point ssh at it:

```
# ~/.ssh/config
Host gitlab.example.internal
    ProxyCommand nc -x 127.0.0.1:1080 %h %p
```

`nc` is in the image for exactly this. For an HTTPS remote the equivalent is
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
