# data

The lab's data platform: [Apache Kafka](https://kafka.apache.org) as the
event bus and [ClickHouse](https://clickhouse.com) as the store everything
is queried from.

    [sources] --JSON--> [Kafka topic raw.<source>] --> [ClickHouse raw.events]

Every source writes its data **raw** - the JSON exactly as the source
produced it - to its own topic. ClickHouse consumes all the topics itself,
through its Kafka table engine, into one table. Nothing is parsed or
reshaped on the way in, so nothing a source sends is rejected or lost for
its shape. Shaping happens at query time, or in views over the raw table.

## What is here

| File | What |
|---|---|
| `kafka.yaml` | One broker, KRaft mode (no ZooKeeper), 20Gi, one week of retention. Kafka is the buffer; ClickHouse is the archive |
| `clickhouse.yaml` | One server, 50Gi, tuned for a 16 GB node it shares |
| `clickhouse-schema.yaml` | An hourly job that creates the topics and the tables. Idempotent |
| `networkpolicy.yaml` | Kafka has no login, so this is its access control: the list of everything allowed to write |
| `ingress.yaml` | `https://clickhouse.lab.baakhoff.com/play`, behind the admin gate |

## The table

```sql
raw.events (
  topic       LowCardinality(String),  -- raw.homeassistant, raw.firefly, ...
  partition   UInt64,
  offset      UInt64,                  -- with topic and partition: the message's identity
  key         String,                  -- the Kafka key, if the producer set one
  kafka_ts    DateTime64(3),           -- when Kafka received it
  ingested_at DateTime64(3),           -- when ClickHouse stored it
  payload     String                   -- the original JSON, untouched
)
```

Ordered by `(topic, kafka_ts)` and partitioned by topic and month, so a
query that names a topic and a time range reads only that. `raw.logs` rows
are deleted after 90 days; everything else is kept.

The topics are `TOPICS` in `clickhouse-schema.yaml`. Adding one is a line
there: on its next run the job creates the topic and recreates the consumer
with the new list. The consumer's position is kept in Kafka, so nothing is
read twice or skipped.

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

The last line says `schema in place for:` and the topic list.

## Use it

In the browser: <https://clickhouse.lab.baakhoff.com/play>, user `admin`.

From the workstation:

```bash
kubectl -n data exec -it clickhouse-0 -- clickhouse-client --user admin --ask-password
```

What has arrived, per source:

```sql
SELECT topic, count() AS rows, max(kafka_ts) AS latest
FROM raw.events GROUP BY topic ORDER BY topic;
```

Reading JSON out of the payload:

```sql
SELECT kafka_ts, JSONExtractString(payload, 'entity_id') AS entity
FROM raw.events
WHERE topic = 'raw.homeassistant' AND kafka_ts > now() - INTERVAL 1 DAY
LIMIT 10;
```

Is the consumer keeping up? Its lag, from Kafka's side:

```bash
kubectl -n data exec kafka-0 -- /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --group clickhouse-raw
```

`LAG` near 0 on every topic is right.

## Things to know

- **Writing to Kafka** takes a rule in `networkpolicy.yaml` naming the
  producer's namespace and pods, and the topic in `TOPICS`. Without both, the
  producer is refused or its messages go nowhere.
- **Producers send JSON.** Anything else still lands, as a string, but is no
  use to `JSONExtract`.
- **One broker, one replica per topic.** The volume is Ceph's three copies,
  so a lost node costs a restart, not data. A broker that is down for longer
  than a producer buffers loses that producer's messages for the gap.
- **Not backed up.** Neither volume is in the nightly backup. Kafka's
  should never need to be; ClickHouse's can be added like any other
  (`clusters/lab/backup/README.md`).
- **Memory:** Kafka is capped at 1Gi (512m heap), ClickHouse at 3Gi, and
  ClickHouse holds itself to 80% of that.
