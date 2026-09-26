# Firefly III

Household finances with real multi-currency: each account has its own
currency, a transfer between currencies records both amounts, and reports
convert everything to one primary currency at stored exchange rates. Budgets,
categories, recurring transactions, bills, piggy banks and reports.

At <https://firefly.lab.baakhoff.com>, and on Homepage under Lab.

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
a crash and does not alert.

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
only for pairs where both currencies are enabled under Options → Currencies.
A transaction between two currencies always stores both actual amounts, so a
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

## Not here, for now

- **The mobile apps and the data importer** use Firefly's API with a personal
  access token, and the API is behind the gate like the rest of the host, so
  they cannot reach it. That would need `/api` exempted from the gate and left
  to token auth, which is a separate decision.
- **Email** is not configured. Firefly logs what it would have sent.

## Backup - not yet, and in this order

The same three pieces as Paperless, whose README has the reasoning:

1. **The `restic-repo` Secret in the `firefly` namespace**, encrypted into
   `clusters/lab/backup/restic-repo-firefly.sops.yaml`. It uses the same values
   as the other copies and differs only in `metadata.namespace`.
2. **The `RoleBinding`**, already in `clusters/lab/backup/rbac.yaml`.
3. **`firefly/firefly-data` in `BACKUP_TARGETS`**, last, after the Secret has
   reconciled.
