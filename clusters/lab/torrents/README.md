# qBittorrent, through PIA

[qBittorrent](https://www.qbittorrent.org), the torrent client Radarr and
Sonarr (`clusters/lab/arr/`) hand their downloads to, inside a VPN:
[gluetun](https://github.com/qdm12/gluetun) runs beside it in the same pod
and connects to Private Internet Access. Setup, the file layout and how it
fits with the rest are in the arr README; this is what is particular to
this namespace.

At <https://torrents.lab.baakhoff.com>, behind the admin gate, and on
Homepage under Ops → Platform.

## What is here

| File | What |
|---|---|
| `namespace.yaml` | the namespace - without a Pod Security label, because the VPN container needs NET_ADMIN |
| `deployment.yaml` | qBittorrent with gluetun as a sidecar that starts first; qBittorrent's first-start settings in a ConfigMap |
| `pvc.yaml` | qBittorrent's settings on Ceph, and the NAS share `tank/media`, writable |
| `service.yaml`, `ingress.yaml` | `torrents.lab.baakhoff.com`, behind the admin gate |
| `networkpolicy.yaml` | ingress-nginx, Radarr and Sonarr in, nothing else |
| `networkpolicy-no-nas.yaml` | no pod here reaches the NAS ([why](../../../docs/network.md#pods-and-the-lan)) |
| `secret.sops.yaml` | PIA's username and password - **created by hand**, arr README step 1 |

## How the VPN holds

- **One network for both containers.** They share the pod's network, and
  gluetun owns it: its firewall lets traffic out only through the tunnel to
  PIA, and in only on 8080, the web UI. qBittorrent has no other way out, so
  when the tunnel is down it is offline, not exposed.
- **Names are resolved over the tunnel.** The pod's DNS is gluetun's own
  server on localhost, not the cluster's.
- **qBittorrent starts second.** gluetun is a native sidecar with a startup
  probe, so qBittorrent starts only once the tunnel is up.
- **A port, forwarded by PIA.** gluetun asks PIA's Netherlands servers for a
  forwarded port and tells qBittorrent over localhost each time it gets
  one, which is why qBittorrent's localhost login is off.

The check, after any change here:

```
kubectl -n torrents exec deploy/qbittorrent -c qbittorrent -- curl -s https://ifconfig.me; echo
```

It must print a PIA address, never the house's.

## Things to know

- **The web UI has no login of its own.** It trusts the pod network, so the
  admin gate is the login, and `networkpolicy.yaml` decides which pods can
  reach it at all - ingress-nginx, Radarr and Sonarr.
- **Settings live in the web UI** after the first start: the ConfigMap is
  copied in only when there are none yet.

## Backup

Not backed up, on purpose (`clusters/lab/backup/README.md`, exclusions):
the volume holds qBittorrent's settings and its list of torrents. The films
and series are in the library, and Radarr and Sonarr, which are backed up,
know what belongs there; losing this volume loses only which torrents were
still seeding.
