# The lab over time

The [README](../README.md) shows what the lab is now. This is what it was.

Newest first. A version number here is not a release — it is an excuse to keep a
photograph, and the bar for a new one is the build looking different enough that the old
picture has stopped being useful. When that happens the README's photo moves down here
and a new one takes its place up there.

Everything below is written in the past tense on purpose, even where the hardware is
still plugged in. The README is the only place that describes the present; if these two
ever disagree, the README is right and this file needs fixing.

## v0.1 — one laptop in a letter rack

![An MSI laptop, lid closed and covered in stickers, standing on its edge in a wire mesh letter rack on a desk, power cable plugged in](images/node01-v0.1.jpg)

`node01` was an MSI laptop: i5-1240P, 16 GB RAM, 512 GB NVMe, Wi-Fi only —
[details](hardware.md).

Where it started: one laptop stood on edge in a wire letter rack so it ran with the lid
shut, on Wi-Fi, with nothing else on the LAN. k3s, Flux, cert-manager and ingress-nginx,
Prometheus and Loki, Headlamp, Homepage, Vaultwarden, the agent pods and two Incus
containers — all of it on that one machine, on one ext4 root filesystem, on one NVMe.

That last part is the reason most of the decisions from this period read the way they do.
With everything on a single disk, a dead NVMe took the operating system, the cluster and
every volume together, which is what [ADR 0004](decisions/0004-restic-to-object-storage.md)
exists to answer. With 16 GB of soldered memory and no upgrade path, what could be run at
all was a real constraint rather than a budgeting exercise —
[ADR 0003](decisions/0003-epicurus-compose-in-incus.md) turns on that number.

It was emptied rather than switched off in one go. Each workload moved to the three-node
cluster on its own, cutting over by gaining a DNS record that beat the wildcard, so a
rollback was deleting one record. Monitoring and logging went first and gained Ceph
instead of local-path; Headlamp and Homepage were copied and their URLs rewritten;
Vaultwarden waited for a restore rehearsal before its SQLite database was carried;
epicurus was rebuilt as Kubernetes workloads rather than ported
([ADR 0007](decisions/0007-epicurus-rebuilt-on-kubernetes.md)), and its Postgres, object
storage, message bus and vector store were moved into it. `podinfo` was deleted rather
than migrated.

The wildcard moved last, deliberately while the laptop was still running, so anything
forgotten would break loudly with a one-record rollback. Nothing did.

It was powered off on 2026-09-19, with its Flux suspended first so that deleting
`clusters/homelab/` could not make a future boot prune the cluster it no longer serves.
It was wiped the next day. The day in between was not idle: keeping the disk intact
rather than wiping it on the spot is what recovered the vector store's memories during
the move, and what made the three-node cluster's own install flags readable when it
turned out nobody had written them down. Anything else that lived only on that disk is
now only in its restic archive.
