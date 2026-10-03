# data

The lab's data platform: [Apache Kafka](https://kafka.apache.org) as the
event bus and [ClickHouse](https://clickhouse.com) as the warehouse.

    [source] --JSON--> [Kafka topic raw.<source>] --> [ClickHouse raw.<source>]
                                                            |
                                                ods  ->  ads  ->  dm

Every source system writes its data **raw** - the JSON exactly as the
system produced it - to its own topic, and ClickHouse consumes each topic
into that system's own table in the `raw` database. Nothing is parsed or
reshaped on the way in, so nothing a source sends is rejected or lost for
its shape.

## The layers

One ClickHouse database each:

| Database | What is in it | Built by |
|---|---|---|
| `raw` | One table per source system, every message as it arrived | the Kafka consumers, set up by `clickhouse-schema.yaml` |
| `ods` | Operational data store: each system's raw rows parsed into typed, cleaned, deduplicated tables | dbt, from `raw` |
| `ads` | Aggregated data storage: joins and aggregates across systems | dbt, from `ods` |
| `dm` | Data marts: the tables a question or a dashboard reads | dbt, from `ads` |

A fifth database, `kafka`, holds the plumbing between Kafka and `raw` - one
Kafka engine table (`<source>_queue`) and one materialized view
(`<source>_to_raw`) per source - so that `raw` holds data and nothing else.
The schema job creates `ods`, `ads` and `dm` empty, and the `dbt` user
that fills them: it reads `raw` and owns the three layers, nothing more.
The models are in [`pipelines/dbt/`](../../../pipelines/README.md), run
hourly by Airflow (`clusters/lab/airflow/`). Nothing writes into those
layers by hand.

## Who writes

| Source | Producer | Topic |
|---|---|---|
| Every pod's log lines | the Alloy collectors, `clusters/lab/logging/alloy.yaml` - OTLP JSON, the line plus its namespace, pod, container and node | `raw.logs` |
| Kubernetes events | the same collectors, one of them at a time - OTLP JSON, the event as JSON in the body | `raw.k8s-events` |
| Home Assistant | its Apache Kafka integration, `clusters/lab/home-assistant/README.md` - one JSON state object per change | `raw.homeassistant` |
| Firefly, Vikunja, Mealie, Paperless, SparkyFitness | Airflow's `ingest_<source>` DAGs, `pipelines/dags/ingest.py` - full API snapshots, one record per message in a small envelope | `raw.firefly`, `raw.vikunja`, `raw.mealie`, `raw.paperless`, `raw.sparkyfitness` |
| The Google account | Airflow's `ingest_google*` DAGs, `pipelines/dags/google.py` - snapshots, Gmail changes and Data Portability exports, in the same envelope (`pipelines/google.md`) | `raw.google` |

## What is here

| File | What |
|---|---|
| `kafka.yaml` | One broker, KRaft mode (no ZooKeeper), 10Gi, one week of retention. Kafka is the buffer; ClickHouse is the archive |
| `clickhouse.yaml` | One server, 30Gi, tuned for a 16 GB node it shares |
| `clickhouse-schema.yaml` | An hourly job that creates the topics, the databases and the raw tables. Idempotent |
| `networkpolicy.yaml` | Kafka has no login, so this is its access control: the list of everything allowed to write |
| `ingress.yaml` | `https://clickhouse.lab.baakhoff.com/play`, behind the admin gate |
| `kafka-ui.yaml` | [Kafbat UI](https://github.com/kafbat/kafka-ui) at `https://kafka.lab.baakhoff.com`, behind the admin gate: topics, messages and consumer lag. Read-only - it cannot delete, reset or produce |
| `alerts.yaml` | `DataIngestionStalled` (nothing read from Kafka for 30 minutes) and `DataKafkaConsumerErrors` (consumers failing for 15), from ClickHouse's own counters on port 9363 |

## A raw table

Every source's table has the same shape:

```sql
raw.<source> (
  partition   UInt64,
  offset      UInt64,         -- with partition: the message's identity in its topic
  key         String,         -- the Kafka key, if the producer set one
  kafka_ts    DateTime64(3),  -- when Kafka received it
  ingested_at DateTime64(3),  -- when ClickHouse stored it
  payload     String          -- the original JSON, untouched
)
```

Ordered by `kafka_ts` and partitioned by month, so a time-range query reads
only that range. `raw.logs` rows are deleted after 90 days; every other
table keeps everything.

The sources are `SOURCES` in `clickhouse-schema.yaml`:
`homeassistant logs k8s-events firefly vikunja mealie paperless sparkyfitness google`. Topic
`raw.<name>`, table `raw.<name>`, a dash becoming an underscore
(`raw.k8s-events` -> `raw.k8s_events`). Adding a source is one word there:
the next run creates its topic, its table and its consumer. Removing one is
by hand - drop its view and queue in `kafka` first, then decide whether its
raw table goes too.

## Setup

**1. The admin password.** On the workstation, from the repo root:

```bash
read -rsp 'clickhouse admin password: ' PW; echo

kubectl create secret generic clickhouse-admin \
  --namespace data \
  --from-literal=CLICKHOUSE_PASSWORD="$PW" \
  --dry-run=client -o yaml > clusters/lab/data/clickhouse-admin.sops.yaml

unset PW
sops --encrypt --in-place clusters/lab/data/clickhouse-admin.sops.yaml
```

Commit and push. Until it reconciles, ClickHouse and the schema job wait in
`CreateContainerConfigError` - not a crash, but not silent either: the
not-ready warnings fire after 15 minutes and clear when the Secret lands.

**2. Run the schema job once** rather than waiting for the hour:

```bash
kubectl -n data create job --from=cronjob/clickhouse-schema schema-now
kubectl -n data logs -f job/schema-now --all-containers
```

The last line says `schema in place for:` and the source list.

## Use it

In the browser: <https://clickhouse.lab.baakhoff.com/play>, user `admin`.

From the workstation:

```bash
kubectl -n data exec -it clickhouse-0 -- clickhouse-client --user admin
```

No password prompt: inside the pod, the client reads it from the pod's
own `CLICKHOUSE_PASSWORD`, and `--ask-password` on top of that is an error.

What has arrived, per source:

```sql
SELECT table, sum(rows) AS rows
FROM system.parts WHERE database = 'raw' AND active
GROUP BY table ORDER BY table;
```

Reading JSON out of a payload:

```sql
SELECT kafka_ts, JSONExtractString(payload, 'entity_id') AS entity
FROM raw.homeassistant
WHERE kafka_ts > now() - INTERVAL 1 DAY
LIMIT 10;
```

Are the consumers keeping up? <https://kafka.lab.baakhoff.com> shows it
under Consumers - one group per source, `clickhouse-<source>`, with its
lag. Or from the workstation:

```bash
kubectl -n data exec kafka-0 -- env KAFKA_HEAP_OPTS=-Xmx128m \
  /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups
```

One group per source, `clickhouse-<source>`. `LAG` near 0 is right.

Every Kafka tool run inside `kafka-0` needs that `KAFKA_HEAP_OPTS`: the
pod's own variable gives each Java process the broker's 512m heap, and a
second one beside the broker can push the pod past its 1Gi limit - and the
kernel then kills the broker, not the tool.

## Things to know

- **Writing to Kafka** takes a rule in `networkpolicy.yaml` naming the
  producer's namespace and pods, and the source in `SOURCES`. Without both,
  the producer is refused or its messages go nowhere.
- **Producers send JSON.** Anything else still lands, as a string, but is no
  use to `JSONExtract`.
- **One broker, one replica per topic.** The volume is Ceph's three copies,
  so a lost node costs a restart, not data. A broker that is down for longer
  than a producer buffers loses that producer's messages for the gap.
- **Backed up: ClickHouse, nightly** (`data/data-clickhouse-0`, last in
  `clusters/lab/backup/`). Kafka's volume is not and should never need to
  be: a week's buffer of what ClickHouse already holds. The backup's restic
  pod reaches the bucket through `restic-backup-egress` in
  `networkpolicy.yaml`; nothing else here has the internet.
- **Memory:** Kafka is capped at 1Gi (512m heap), ClickHouse at 3Gi, and
  ClickHouse holds itself to 80% of that.
