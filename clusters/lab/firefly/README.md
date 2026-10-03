# Firefly III

Household finances with real multi-currency: each account has its own
currency, a transfer between currencies records both amounts, and reports
convert everything to one primary currency at stored exchange rates. Budgets,
categories, recurring transactions, bills, piggy banks and reports.

At <https://firefly.lab.baakhoff.com>, and on Homepage under Home.

## How login works

Pocket ID through oauth2-proxy, and no Firefly password. The gate hands
Firefly the signed-in user's email (ingress.yaml), and Firefly logs that user
in, creating the account on first visit. **The first account is the owner**,
the admin of the instance. Who may get through at all is the oauth2-proxy
client's *Allowed User Groups* in Pocket ID, the same setting as every other
gated host.

Every account starts with its own separate books. Sharing one set of books is
a *financial administration* in Firefly: the owner invites another user into
theirs under Options → Administrations.

Trusting a header is safe only if nothing but the gate can set it. Two things
make that true, and neither may be removed:

- ingress-nginx overwrites `X-Auth-Request-Email` with oauth2-proxy's answer,
  whatever the browser sent;
- `networkpolicy.yaml` lets only ingress-nginx, and the cron Job with no
  header, reach the pod.

## Setup, in this order

The pod waits in `CreateContainerConfigError` until step 1 exists. That is not
a crash, but not silent either: the not-ready warnings (KubePodNotReady,
replicas mismatch, rollout stuck) fire after 15 minutes; they clear the moment
the Secret lands.

**1. Create the Secret on the workstation**, in the repository. Both values are
random and generated here, so nothing needs pasting:

```bash
kubectl create secret generic firefly-env \
  --namespace firefly \
  --from-literal=APP_KEY="$(openssl rand -hex 16)" \
  --from-literal=STATIC_CRON_TOKEN="$(openssl rand -hex 16)" \
  --dry-run=client -o yaml > clusters/lab/firefly/env.sops.yaml

sops --encrypt --in-place clusters/lab/firefly/env.sops.yaml
```

Commit and push. Both must be exactly 32 characters, which is what 16 random
bytes in hex are. `APP_KEY` encrypts session data and some stored values;
changing it later logs everyone out and can make those values unreadable, so
it is generated once and lives in git, encrypted. `STATIC_CRON_TOKEN`
authorises the daily call in `cronjob.yaml`.

**2. Sign in yourself first** at <https://firefly.lab.baakhoff.com>. The first
account becomes the owner. The first-run wizard asks for the primary
currency, the one reports convert to, and a first account.

**3. Turn on exchange rates**, as the owner, under Administration →
Configuration: *Enable exchange rates*, and *Download exchange rates* if the
daily download should keep them current. Ticking it fetches nothing by
itself: the download is part of the nightly cron below. It comes from files
Firefly's author publishes weekly, which cover EUR, USD, RUB, RSD and KZT
among others, and each rate is dated the Monday of its week. A rate is saved
only for pairs where both currencies are enabled under Options → Currencies,
in the books doing the converting: every account's own books count
separately. See [below](#exchange-rates-and-the-rate-currencies-container)
for the Firefly bug that otherwise stops the download. A transaction between two currencies always stores both actual amounts, so a
missing rate only affects reports, never the balances.

**4. Add accounts** in whichever currencies they are held in, under Accounts →
Asset accounts → Create, choosing the currency on each.

## The daily cron

`cronjob.yaml` calls Firefly's cron endpoint at 03:15, straight to the
Service, with the token from the Secret. That run creates recurring
transactions, sends bill reminders and downloads exchange rates. If
recurring transactions stop appearing:

```bash
kubectl -n firefly get jobs
kubectl -n firefly logs job/<latest firefly-cron job>
```

The log is Firefly's JSON reply, one section per task. To run it now rather
than at 03:15:

```bash
kubectl -n firefly create job --from=cronjob/firefly-cron firefly-cron-manual
kubectl -n firefly logs -f job/firefly-cron-manual
kubectl -n firefly delete job firefly-cron-manual
```

Firefly downloads rates at most once per 12 hours, so a manual run soon
after another skips them. As the owner, from inside the pod, and for last
week's files when this week's are not published yet (a Monday, usually):

```bash
kubectl -n firefly exec deploy/firefly -c firefly -- \
  php /var/www/html/artisan firefly-iii:cron --download-cer --force --date=<yesterday>
```

### Exchange rates and the rate-currencies container

"Exchange rates cron job fired successfully" says nothing about whether any
rate was saved. A failed download is a warning in the Firefly container's
log, and a skipped one is silent.

A Firefly bug made every download skip every currency: the download fetches
only currencies carrying an old site-wide flag, and enabling or editing a
currency in the app clears that flag. The `rate-currencies` container in
`deployment.yaml` sets it again within ten minutes on every currency some
books use, and logs a line when it does. Remove it once Firefly's download
reads the per-books setting. To see what is stored:

```bash
kubectl -n firefly exec -i deploy/firefly -c firefly -- php <<'PHP'
<?php
$db = new PDO('sqlite:/var/www/html/storage/database/database.sqlite', null, null, [PDO::SQLITE_ATTR_OPEN_FLAGS => PDO::SQLITE_OPEN_READONLY]);
foreach ($db->query("SELECT user_group_id AS grp, date(date) AS week_of, count(*) AS n FROM currency_exchange_rates WHERE deleted_at IS NULL GROUP BY 1, 2 ORDER BY 2 DESC LIMIT 10", PDO::FETCH_ASSOC) as $r) echo implode(' | ', $r), "\n";
PHP
```

## Not here, for now

- **The mobile apps and the data importer** use Firefly's API with a personal
  access token, and the API is behind the gate like the rest of the host, so
  they cannot reach it. That would need `/api` exempted from the gate and left
  to token auth, which is a separate decision. The one token client that
  exists today does not go through the gate at all: the CFO seat's access
  runs through `clusters/lab/firefly-broker/`, a lab-side broker that carries
  the token without the agent host ever seeing it. This host's public surface
  is unchanged by that.
- **Email** is not configured. Firefly logs what it would have sent.

## Backup

`firefly/firefly-data` is in the nightly backup (`clusters/lab/backup/`),
second after Vaultwarden: the SQLite database, attachments and the exchange
rates, from a CSI snapshot so the database is copied at one moment. It
matters more than it did, because the Firefly broker lets an agent delete
(`clusters/lab/firefly-broker/`) and Firefly has no recycle bin - a restore
from here is the undo.
