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
| Further | Turkey, Georgia, Russia, China, Kazakhstan |

A point outside them still gets its country from Dawarich, which works
countries out itself, and no street or city.

Names come in the local language, plus English, Russian, Serbian and
Kazakh where OpenStreetMap has them.

## How the index is built

On the pod's first start, the `import` init container streams
GraphHopper's [Photon dumps](https://download1.graphhopper.com/public/)
for those countries, about 3.2GB, straight into Photon's importer, and
checks each against its published checksum. Nothing but the index is
written: about 16GB of it, built on the node's own disk and then copied to
the 40GB volume in one go, so that a rebuild fits beside the old index.
Building it straight on the Ceph volume failed: the index's constant
rewriting during the import, over the network, stalled the database past
the importer's fixed 30-second timeout. The import takes an hour or two,
during which the pod shows `Init:0/1`
and Dawarich's lookups fail; its nightly job looks the points up again
once Photon answers. Afterwards, every start finds
the index built from the same settings and goes straight to serving.

Watch it on the workstation:

```bash
kubectl -n photon logs deploy/photon -c import -f
```

It ends with `Index built.`, and the pod goes to `1/1`. If it stops on a
checksum mismatch, GraphHopper was uploading a new dump at that moment;
delete the pod and it starts over.

## Changing the countries, or fresher maps

The settings are environment variables on the `import` container in
`deployment.yaml`:

- `DUMPS`: which files to download, as paths on GraphHopper's server
- `COUNTRIES`: which countries the index keeps, as two-letter codes
- `LANGUAGES`: the translations kept besides the local names
- `IMPORT_STAMP`

A new country needs both its dump and its code. GraphHopper names the
dumps by region (`europe/italy`, `asia/japan`); their index page lists
them.

Any change rebuilds the index on the next start. So does a new
`IMPORT_STAMP`, which is the way to get GraphHopper's latest OpenStreetMap
data: they publish new dumps weekly, and streets change slowly, so a new
stamp once or twice a year is plenty. The rebuild happens beside the old
index and replaces it only when it has succeeded, but Photon is not
serving while it runs.

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
