# Photon

[Photon](https://github.com/komoot/photon), an OpenStreetMap geocoder.
Here it does one job: Dawarich (`clusters/lab/dawarich/`) asks it for the
street, city and place at each location point, so that lookup never leaves
the lab. Every hosted geocoder would otherwise receive the whole location
history, one coordinate at a time.

The image is [photon-docker](https://github.com/rtuszik/photon-docker),
the one Dawarich's documentation points to, used for its Java, Photon jar
and Python, not its own startup: the import here is `deployment.yaml`'s.

## What it knows

Not the whole planet. That index is about 95GB and Photon asks for 64GB of
RAM for it; each node has 16GB. Instead, the countries the household
lives in and travels to:

| | |
|---|---|
| Home | Denmark |
| The Balkans | Serbia, Bosnia and Herzegovina, Montenegro, Croatia, Kosovo, North Macedonia, Albania, Slovenia, Bulgaria, Greece, Romania |
| Further | Turkey, Georgia, Russia, China, Kazakhstan, India, Indonesia, Thailand, the United Arab Emirates |

A point outside them still gets its country from Dawarich, which works
countries out itself, and no street or city.

Names come in the local language, plus English, Russian, Serbian and
Kazakh where OpenStreetMap has them.

## How the index is built

On the workstation, never in the cluster. The index is tens of millions of
places in an OpenSearch database - 32.6 million and 11GB before India,
Indonesia, Thailand and the UAE joined - and building it is an hour or more of
constant disk writing. In the cluster that went wrong twice: on the Ceph
volume the database stalled past the importer's fixed 30-second timeout,
and on a node's own NVMe - the disk etcd and the node's Ceph OSD share - it
starved the node and took the control plane down for a moment. So the
cluster only serves. Its `check` init container lets Photon start only on
an index built from the settings in `deployment.yaml`; otherwise the pod
stops in `Init:Error` and its log points here.

The build is the cluster's own: the same image, and the script and
settings read out of the cluster. It needs Docker and about 40GB free.
On the workstation:

**1. The script and settings,** from the cluster:

```bash
mkdir -p ~/photon-build/scripts ~/photon-build/data ~/photon-build/build
cd ~/photon-build
kubectl -n photon get configmap photon-import -o jsonpath='{.data.import\.sh}' > scripts/import.sh
kubectl -n photon get configmap photon-import -o jsonpath='{.data.stream\.py}' > scripts/stream.py
kubectl -n photon get deploy photon -o jsonpath='{range .spec.template.spec.initContainers[0].env[*]}{.name}={.value}{"\n"}{end}' > settings.env
```

**2. The build,** about 80 minutes. It streams GraphHopper's
[Photon dumps](https://download1.graphhopper.com/public/) for the
countries, about 3.2GB, checks each against its published checksum, and
ends with `Index built.`:

```bash
docker run --rm -e HOME=/tmp --env-file settings.env \
  -v "$PWD/scripts:/scripts:ro" -v "$PWD/data:/photon/data" -v "$PWD/build:/build" \
  --entrypoint /bin/bash docker.io/rtuszik/photon-docker:2.4.0 /scripts/import.sh
```

With the plain Docker engine, add `--user "$(id -u):$(id -g)"`; Docker
Desktop maps the folders' owners itself and refuses it.

**3. The copy.** Photon has to be stopped while its volume is replaced,
and Flux would start it again within ten minutes, so Flux pauses too:

```bash
flux suspend kustomization flux-system
kubectl -n photon scale deploy/photon --replicas=0
kubectl -n photon wait --for=delete pod -l app.kubernetes.io/name=photon --timeout=3m
```

A pod that mounts the volume, as Photon's user:

```bash
kubectl -n photon run photon-load --image=docker.io/rtuszik/photon-docker:2.4.0 --restart=Never \
  --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":9011,"runAsGroup":9011,"fsGroup":9011,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"load","image":"docker.io/rtuszik/photon-docker:2.4.0","command":["sleep","infinity"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}},"volumeMounts":[{"name":"data","mountPath":"/photon/data"}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"photon-data"}}]}}'
kubectl -n photon wait --for=condition=Ready pod/photon-load --timeout=3m
```

The old index out, the new one in. `pv` holds the copy to 30MB/s so Ceph
takes it gently (`sudo apt install pv`); about eight minutes:

```bash
kubectl -n photon exec photon-load -- sh -c 'rm -rf /photon/data/photon_data /photon/data/import-settings'
cd ~/photon-build/data
tar -cf - photon_data import-settings | pv -L 30m | kubectl -n photon exec -i photon-load -- tar -C /photon/data -xf -
kubectl -n photon exec photon-load -- sh -c 'du -sh /photon/data/photon_data; cat /photon/data/import-settings; echo'
kubectl -n photon delete pod photon-load
```

**4. Photon back:**

```bash
flux resume kustomization flux-system
```

Flux sets the replicas back to 1; the check passes and Photon serves
within a minute. `~/photon-build` can go.

While Photon is down Dawarich's lookups fail; its nightly job looks up
every point still without an address once Photon answers again.

## Changing the countries, or fresher maps

The settings are environment variables on the `check` container in
`deployment.yaml`:

- `DUMPS`: which files to download, as paths on GraphHopper's server
- `COUNTRIES`: which countries the index keeps, as two-letter codes
- `LANGUAGES`: the translations kept besides the local names
- `IMPORT_STAMP`: changed to get GraphHopper's latest data, which they
  publish weekly; streets change slowly, so once or twice a year is plenty

A new country needs both its dump and its code. GraphHopper names the
dumps by region (`europe/italy`, `asia/japan`); their index page lists
them.

Merge the change first: the workstation reads the settings from the
cluster. From then until the new index is copied in, Photon is stopped by
its check. Then "How the index is built", steps 1 to 4.

## Not backed up, no login, no warehouse feed

The lab's rule is that every service is backed up, signs in through Pocket
ID and feeds ClickHouse. This one does none of the three, on purpose:

- **Backup**: everything on its volume is downloaded and built again by
  the next start. `clusters/lab/backup/README.md` lists it with the other
  exclusions.
- **Login**: there is nothing to log in to. It has no Ingress and no UI,
  and its NetworkPolicy admits Dawarich's pod and nothing else.
- **Warehouse**: what it answers is stored on Dawarich's points, which the
  `ingest_dawarich` DAG already carries into ClickHouse
  (`ods.dawarich_points.city`).
