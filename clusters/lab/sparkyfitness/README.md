# SparkyFitness

[SparkyFitness](https://github.com/CodeWithCJ/SparkyFitness), a self-hosted
replacement for MyFitnessPal. It is a food diary with calories and macros,
plus exercise, water, weight and body measurements, with goals and reports.
Food comes from Open Food Facts, USDA and others, with barcode scanning. Its AI
assistant logs a meal from a sentence or a photo.

At <https://fitness.lab.baakhoff.com>, and on Homepage under Everyday → Home.

## How login works

Pocket ID, through SparkyFitness's own OpenID Connect, and nothing else. The
password form and sign-up are off, closed at the API as well as on the page.
An account is created at the person's first Pocket ID login. Members of the
Pocket ID group `sparkyfitness-admins` are SparkyFitness admins.

It is **not behind the oauth2-proxy gate**, like Paperless and Vaultwarden.
The phone app cannot pass the gate: it signs in to Pocket ID in the system
browser, then sends a session token the gate does not know. ingress.yaml has
the rest.

## Setup, in this order

The server waits in `CreateContainerConfigError` until step 2 exists, and so
does Postgres. That is not a crash, but not silent either: the not-ready
warnings fire after 15 minutes, and clear once the Secret lands.

**1. Create the OIDC client in Pocket ID** at `https://id.lab.baakhoff.com`,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | SparkyFitness |
| Callback URLs | `https://fitness.lab.baakhoff.com/api/auth/sso/callback/pocket-id` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | the people who use it, e.g. `sparkyfitness-users` |

Then, under Administration → User Groups, create `sparkyfitness-admins` and
put yourself in it.

The phone app signs in through the same callback, so it needs no URL of its
own.

**2. Create the Secret on the workstation**, from the repo root. Run the two
`read` lines one at a time: pasted together, the rest of the paste becomes
the input. The other four values are generated and never shown.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic sparkyfitness \
  --namespace sparkyfitness \
  --from-literal=SPARKY_FITNESS_DB_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=SPARKY_FITNESS_APP_DB_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=SPARKY_FITNESS_API_ENCRYPTION_KEY="$(openssl rand -hex 32)" \
  --from-literal=BETTER_AUTH_SECRET="$(openssl rand -hex 32)" \
  --from-literal=SPARKY_FITNESS_OIDC_CLIENT_ID="$CID" \
  --from-literal=SPARKY_FITNESS_OIDC_CLIENT_SECRET="$CSEC" \
  --dry-run=client -o yaml > clusters/lab/sparkyfitness/secret.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/sparkyfitness/secret.sops.yaml
```

Commit and push. The pre-commit hook asserts the file is encrypted.

Create this once. If you run it again, you replace values that are already in
use:

- `SPARKY_FITNESS_DB_PASSWORD` is set in Postgres when the database is first
  created. A new value no longer matches, and the server cannot log in.
- `SPARKY_FITNESS_API_ENCRYPTION_KEY` encrypts the AI and food-provider keys
  stored in the database. A new key makes them unreadable, and they have to
  be entered again.

To change only the Pocket ID client, edit the file in place with
`sops clusters/lab/sparkyfitness/secret.sops.yaml`.

**3. Sign in** at <https://fitness.lab.baakhoff.com>. The first start runs
the migrations, which takes a minute or two.

**4. The phone app.** It is on the App Store for iPhone. For Android, use
the Google Play beta or the APK from the GitHub releases page; upstream's
[mobile app page](https://codewithcj.github.io/SparkyFitness/mobile-app/mobile-app)
has the links. Set the server to `https://fitness.lab.baakhoff.com` and sign
in with Pocket ID. Then let the app read Apple Health or Health Connect.

**5. Feed the data warehouse.** Airflow's `ingest_sparkyfitness` DAG
copies the diary into ClickHouse's `raw.sparkyfitness` every 6 hours
(`pipelines/dags/ingest.py`), with an API key. Until the key exists, that
DAG's runs fail and nothing else is affected.

Signed in as the person whose diary should be copied, open Settings → API
Key Management and generate a key. Then, on the workstation from the repo
root, add it to Airflow's Secret, one line at a time:

```bash
read -rsp 'sparkyfitness api key: ' SK; echo
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["SPARKYFITNESS_API_KEY"]' "\"$(printf %s "$SK" | base64 | tr -d '\n')\""
unset SK
```

On the Mac's zsh, the first line is `read -rs "SK?sparkyfitness api key: "; echo`.
The Secret's values are base64, hence the `base64` in the middle. Commit
and push. Once Flux has applied it, restart the scheduler, because a pod
reads its environment only when it starts:

```bash
kubectl -n airflow rollout restart deployment/airflow-scheduler
```

Then trigger `ingest_sparkyfitness` in the Airflow UI, and after it the
`warehouse` DAG. The day-by-day view is `ads.nutrition_daily`.

## What reaches the warehouse

The API key belongs to one account, and SparkyFitness's API answers for
that account only. So the warehouse holds **one person's diary**, the key
owner's, not the whole household's. Everything that account can see, the
DAG can read: the key has the account's full rights, read and write, like
the Mealie and Vikunja tokens. It reaches the server directly on 3010, not
through the frontend, past a door in `networkpolicy.yaml`.

The DAG takes a full snapshot each run: every food entry, check-in, daily
water total, night of sleep and workout from 2000 to tomorrow. The ods
layer keeps the newest copy of each (`ods.sparkyfitness_*`), so a deleted
entry drops out at the next run.

Not copied yet: custom measurements, mood, fasting and the raw health
samples the phone app syncs. Each is one more endpoint in the DAG.

## Garmin

Through the phone, not the Garmin service. Garmin Connect writes to Apple
Health on iPhone, or to Health Connect on Android, where the sharing is
switched on in the Garmin Connect app. The SparkyFitness app reads it from
there.

You get calories burned, steps, workouts, heart rate, sleep and weight. Body
Battery, stress and intensity minutes stay in Garmin Connect.

Upstream also has a Garmin service that logs in to Garmin Connect directly.
It is not deployed here, for three reasons:

- It would keep the Garmin password in the cluster.
- It uses an unofficial login, which breaks when Garmin changes theirs.
- Upstream's own Compose file still calls it work in progress.

## Things to know

- **AI** (logging by chat or photo) is off until a provider is added under
  Settings → AI Service. OpenRouter works, as it does for Paperless and
  Mealie, and the text or photo then leaves the cluster. The key is stored
  encrypted in the database.
- **Mealie** can be added as a recipe source. It would need
  `ALLOW_PRIVATE_NETWORK_FOOD_PROVIDERS`, because Mealie is on the lab's own
  network, and a rule admitting the server in Mealie's networkpolicy.yaml.
  Neither is set up yet.
- **The login rate limit** in the frontend's nginx counts by the address it
  sees, which is ingress-nginx's. The whole household therefore shares one
  limit of 5 sign-ins a second, which is far more than it needs.
- **The `groups` scope** is what tells SparkyFitness who is in
  `sparkyfitness-admins`. Without it, admin rights are removed at the next
  login.

## Not backed up yet

Neither volume is in the nightly backup, so for now losing them loses the
diary. Two volumes need adding: `sparkyfitness/data-sparkyfitness-postgres-0`
(the database) and `sparkyfitness/sparkyfitness-data` (photos). Use the same
three pieces as for Mealie:

- the `restic-repo` Secret copied into this namespace, as
  `clusters/lab/backup/README.md` shows;
- a `RoleBinding` for `backup-driver` in `clusters/lab/backup/rbac.yaml`;
- the two targets in `BACKUP_TARGETS`.

A snapshot of a running Postgres is crash-consistent. That is the state
Postgres recovers from after a power cut, so it restores cleanly.
