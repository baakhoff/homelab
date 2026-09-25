# Actual Budget

The household budget: accounts, envelope budgeting, recurring transactions,
reports. Each device keeps a full copy of the budget in the browser and syncs
through this server, so it keeps working offline and catches up afterwards.

At <https://budget.lab.baakhoff.com>, and on Homepage under Lab. Signing in is
Pocket ID, through Actual's own OpenID Connect support. There is no password
and no oauth2-proxy gate: every Actual account is a Pocket ID account, created
on its first login.

## Setup, in this order

The pod waits in `CreateContainerConfigError` until step 2 exists. That is not
a crash and does not alert. It starts by itself once the Secret reconciles.

**1. Create the OIDC client in Pocket ID** at `https://id.lab.baakhoff.com`,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Actual Budget |
| Callback URL | `https://budget.lab.baakhoff.com/openid/callback` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | the people who share the budget, e.g. `budget-users` |

Set the group before step 3. **The first account to sign in becomes Actual's
owner and admin**, the only one who can create budgets, manage users and share
budgets with them. That first login has to be yours.

**2. Create the Secret on the workstation**, entering the client ID and secret
Pocket ID shows. `read -rs` keeps both out of the shell history, and nothing
below prints them.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic actual-oidc \
  --namespace actual \
  --from-literal=ACTUAL_OPENID_CLIENT_ID="$CID" \
  --from-literal=ACTUAL_OPENID_CLIENT_SECRET="$CSEC" \
  --dry-run=client -o yaml > clusters/lab/actual/oidc.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/actual/oidc.sops.yaml
```

Commit and push. The pre-commit hook asserts the file is encrypted.

**3. Sign in**, yourself first. The server reads the Pocket ID settings at
start, so there is no setup page and no server password to choose. After your
login, create a budget or import one (from YNAB, nYNAB or an Actual export)
under the budget menu.

**4. Bring in the rest of the household.** Each person signs in once, which
creates their account. Then, as the owner, open the budget → **User Access**
and grant it to them. An account with no access sees no budgets.

## Things to know

- **A device stays signed in until it signs out.** Actual's session tokens do
  not expire by default. That suits a household's own phones; sign out on a
  borrowed device.
- **End-to-end encryption is optional**, under the budget's settings. With a
  password set, the server stores only ciphertext, and the password is needed
  on each new device. Lose it and the server's copy is unreadable, backup
  included.
- **Bank sync** (GoCardless, SimpleFIN and others) is off until configured, and
  would send credentials to that provider. Manual entry and file import (OFX,
  QIF, CSV) need nothing.

## Backup - not yet, and in this order

The same three pieces as Paperless, whose README has the reasoning:

1. **The `restic-repo` Secret in the `actual` namespace**, encrypted into
   `clusters/lab/backup/restic-repo-actual.sops.yaml`. It uses the same values
   as the other copies and differs only in `metadata.namespace`. The backup
   README has the commands.
2. **The `RoleBinding`**, already in `clusters/lab/backup/rbac.yaml` and
   harmless ahead of time.
3. **`actual/actual-data` in `BACKUP_TARGETS`**, last, after the Secret has
   reconciled. The driver fails the whole run on a target whose Secret is
   missing.
