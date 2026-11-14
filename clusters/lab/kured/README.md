# kured

[kured](https://kured.dev) reboots a cluster node when an installed update
needs it - usually a new kernel from unattended-upgrades - so the fix takes
effect without anyone remembering to.

Every hour, on each node, it looks for `/var/run/reboot-required`, which
Ubuntu writes for such updates. If it is there, between 03:00 and 06:00 UTC,
and no other alert is firing, it takes a cluster-wide lock, drains the node,
reboots it, and uncordons it when it is back. The lock is held two hours
more, so Ceph has caught up before the next node goes. All settings, and
why: `helmrelease.yaml`.

## Things to know

- **Another firing alert holds every reboot.** That is on purpose; if a
  reboot waits three days, `HostRebootRequired` says so. What kured saw:
  `kubectl -n kured logs ds/kured --tail=50`.
- **A drain that takes over 30 minutes is given up**, the node uncordoned,
  and tried again the next hour. Usually Ceph was not healthy, which its own
  disruption budgets enforce.
- **A node with an agent pod on it is never rebooted by kured.** The drain
  would end whatever the pod's sessions are running. When
  `HostRebootRequired` fires for such a node, pick a moment when its agent
  pods are idle (`kubectl -n agents get pods -o wide` shows which are on
  it) and reboot it by hand:
  `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data`, then
  `ssh <node>.lab sudo reboot`, then `kubectl uncordon <node>` once it is
  `Ready`. One node at a time, and wait for Ceph to report `HEALTH_OK`
  before the next.
- **To hold reboots for a while** - a long job running, guests over:
  `kubectl -n kured annotate ds kured weave.works/kured-node-lock='{"nodeID":"manual"}'`,
  and the same with `weave.works/kured-node-lock-` to release it.
- **Not the Pi.** It is outside the cluster; `HostRebootRequired` tells you
  when it needs `sudo reboot`.
- **Nothing to back up**, no login: it has no state and no web page.
