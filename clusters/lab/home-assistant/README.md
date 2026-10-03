# Home Assistant

Home automation - lights, sensors, integrations - running as the official
container on one volume, reached at `https://hass.lab.baakhoff.com` from the
house and the tailnet only.

## How it fits

- **The official container, not HAOS.** HAOS is an appliance OS, not a
  workload. No add-ons here: anything that would be an add-on becomes a
  Deployment of its own, or does not happen.
- **Its own login, no gate.** The first-run owner account guards the UI;
  `oauth2-proxy` stays out because the frontend and the Companion app need
  the raw websocket API.
- **One volume** (`home-assistant-config`): config, the SQLite recorder,
  auth and automations. Recreate / one replica for the single-database
  reasons Vaultwarden's file spells out.
- **Root container.** The official image manages `/config` ownership itself
  and is not supported unprivileged; capabilities are trimmed to the short
  list in the Deployment comments.

## First-run notes (done at install - kept for rebuilds)

The reverse proxy must be trusted before the ingress host answers with
anything but `400`: **Settings -> System -> Network -> HTTP server**, turn on
**Trust X-Forwarded-For** and set **Trusted proxies** to `10.42.0.0/16` (the
k3s pod range). While it is still untrusted, reach the UI once via
`kubectl -n home-assistant port-forward deploy/home-assistant 8123:8123`.

## Every state change to the data warehouse

Home Assistant's [Apache Kafka](https://www.home-assistant.io/integrations/apache_kafka/)
integration sends each state change, as JSON, to the `raw.homeassistant`
topic, and ClickHouse keeps them in `raw.homeassistant`
(`clusters/lab/data/README.md`). It is configured in YAML only, so it
lives in `configuration.yaml` on the volume. Once, from the workstation:

```bash
kubectl -n home-assistant exec -i deploy/home-assistant -- sh -c 'cat >> /config/configuration.yaml' <<'EOF'

apache_kafka:
  ip_address: kafka.data.svc.cluster.local
  port: 9092
  topic: raw.homeassistant
EOF
kubectl -n home-assistant rollout restart deploy/home-assistant
```

Check that `configuration.yaml` had no `apache_kafka:` block already -
a second one is a config error, and Home Assistant starts in safe mode.
A `filter:` under it (include or exclude domains, entities, globs) narrows
what is sent; by default it is everything. Kafka is reachable from this pod
only because `clusters/lab/data/networkpolicy.yaml` names it.

## Known limits

- **No local discovery** (mDNS / SSDP / DHCP broadcasts): multicast does not
  reach a pod's network. Integrations that talk unicast or go through the
  cloud work; add local devices by IP.
- **No USB radios.** Zigbee / Z-Wave / Matter dongles need node-level device
  passthrough - a different architecture, deliberately not this one.
- **Not backed up yet.** When that changes it is the usual three pieces
  (Secret, RoleBinding, `BACKUP_TARGETS` entry) in the order
  `../backup/README.md` gives.
