# system-upgrade

[system-upgrade-controller](https://github.com/rancher/system-upgrade-controller)
upgrades k3s on the three nodes, one at a time, to the version written in
`plan-k3s.yaml`. k3s came from its install script, so it has no package and
nothing else would ever update it.

| File | What |
|---|---|
| `crd.yaml` | the `Plan` resource, vendored from the controller's release |
| `system-upgrade-controller.yaml` | the controller, its namespace (Pod Security privileged) and RBAC, vendored from the same release |
| `plan-k3s.yaml` | the k3s version, and how to roll it out: cordon, one node at a time |
| `networkpolicy-no-nas.yaml` | no pod here reaches the NAS ([why](../../../docs/network.md#pods-and-the-lan)) |

## A k3s upgrade

Renovate opens a PR when k3s releases (`renovate.json5`), one Kubernetes
minor at a time. Read the release notes - k3s's, and for a new minor
Kubernetes's own upgrade notes - then merge. Within minutes the
controller starts on the first node; follow it from the workstation:

```bash
kubectl -n system-upgrade get plans,jobs
kubectl get nodes -w
```

Each node is cordoned, its k3s replaced and restarted (ten to twenty
seconds without the API on that node), and uncordoned; then the next. The
nodes' containers keep running throughout. Done when all three show the new
version in `kubectl get nodes`.

A node whose upgrade fails stays cordoned, and the controller retries its
job; `kubectl -n system-upgrade logs job/<name>` says why. Nothing goes on
to the next node until it succeeds.

**Going back** is not a revert of the PR: k3s does not downgrade etcd's
data, and the controller would try. Restore is the
[disaster-recovery runbook](../../../docs/runbooks/disaster-recovery.md).

## Upgrading the controller

Renovate offers a new tag for the controller's image in
`system-upgrade-controller.yaml`. Before merging, replace both vendored
files from that release on the same branch, keeping each file's header, so
the CRD moves with the controller:

```bash
v=v0.21.0   # the new version
for f in crd.yaml system-upgrade-controller.yaml; do
  curl -sL "https://github.com/rancher/system-upgrade-controller/releases/download/$v/$f" -o "/tmp/$f"
done
```
