# Trivy Operator

[Trivy Operator](https://github.com/aquasecurity/trivy-operator) checks every
container image the cluster runs against the public CVE databases, this
repo's workloads and the private repo's alike, and checks them again every
day. A critical CVE that a newer package fixes becomes a Telegram message.

There is no web page. The findings are Kubernetes objects,
`VulnerabilityReport`s, one per container, in the namespace of the workload
they are about, and metrics in Prometheus.

## How it is put together

| File | What |
|---|---|
| `namespace.yaml` | `trivy-system`, at Pod Security `baseline`: the operator, its Trivy server and the scan jobs |
| `helmrelease.yaml` | the operator, from Aqua's chart, with what it scans and how hard |
| `helmrepository.yaml` | Aqua's chart repository |
| `networkpolicy-no-nas.yaml` | no pod here reaches the NAS ([why](../../../docs/network.md#pods-and-the-lan)) |
| `../monitoring/trivy-rules.yaml` | the alert |

When a workload starts with an image it has not seen, the operator starts a
scan job for it, two at a time. The job reads the image from its registry,
not from the node, and sends the package list to the Trivy server in the
same namespace, which keeps the CVE database and what it has already read
from each image layer, on a 5 GiB Ceph volume. Each report is deleted after
a day, and that starts the next scan; an unchanged image costs its manifest
and no layers.

## What it reports, and what alerts

- **Reported:** HIGH and CRITICAL CVEs a newer package fixes. CVEs nobody has
  fixed yet are left out: almost every image has some, nothing can be done
  about them here, and an alert about them would never go away.
- **Alerted:** `ContainerImageCriticalCVE`, for each image with at least one
  of those CRITICAL ones, after an hour. One Telegram message per namespace,
  then a reminder weekly while it lasts, and a resolved message once the
  image is upgraded.
- **Also alerted:** `ContainerImageOSEndOfLife`, for each image built on an OS
  release that no longer gets security fixes. Its CVEs never count as
  fixable, so the first alert would never see them.

The fix is a newer image. Usually Renovate already has a PR open for it, or
will on Monday; if upstream has not rebuilt yet, waiting is the answer, and
a silence in Alertmanager for that image keeps the chat quiet meanwhile.

The nodes and the Pi are checked differently, by what apt knows: security
updates not installed after two days, a reboot not done after three
(`clusters/lab/monitoring/host-security-rules.yaml`, and the host files in
`hosts/nodes/` and `hosts/exitnode/`). Not covered: k3s itself, which is not
from apt, and the NAS, which TrueNAS updates.

## Reading the findings

```bash
kubectl get vulnerabilityreports -A -o wide
```

lists every report, with its counts. For one image's CVEs, with the fixed
version of each:

```bash
kubectl -n <namespace> describe vulnerabilityreport <name>
```

The first pass over every image takes an hour or two after the merge, so
the list fills in gradually.

## Things to know

- **Nothing to back up.** The reports are made again by the next scan and
  the database is downloaded again; a lost volume costs one slower pass.
- **No login.** Nothing here is reached from outside the cluster; who may
  read the reports is who may read the namespaces they are in.
- **A scan that fails** (a registry down, a rate limit) is retried after 30
  seconds; the operator's log says why:
  `kubectl -n trivy-system logs deploy/trivy-operator --tail=100`.
- **Upgrades:** Renovate offers the chart, which carries the Trivy version
  with it. The CRDs are replaced with each upgrade.
