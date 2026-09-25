# n8n

Visual automation: a trigger (a schedule, a new email, an RSS item, a
webhook) runs a chain of steps (call an API, transform data, ask a model,
branch) that end in actions (send a Telegram message, file a document in
Paperless, write a row somewhere). About 400 built-in integrations, and
JavaScript or Python where they run out.

At <https://n8n.lab.baakhoff.com>, and on Homepage under Lab.

## How login works

Two sign-ins. The oauth2-proxy gate asks for a Pocket ID passkey first, like
every other gated host, and decides who gets through at all. Then n8n's own
account login: single sign-on is in n8n's paid edition only, and the free one
cannot switch its login off. **The first person to open it creates the owner
account**, so that should be you, right after this reconciles.

The owner invites anyone else under Settings → Users. Workflows and
credentials are per user unless shared.

## Setup

Nothing to create beforehand: no Secret. n8n generates the key that
encrypts every stored credential on first start, into `~/.n8n/config` on the
volume beside the database. That key and the database are only useful
together, and one volume keeps them together in every snapshot and backup.
Lose both and the workflows are gone anyway; restore both and everything
decrypts.

1. Open <https://n8n.lab.baakhoff.com>, pass the gate, and create the owner
   account. Use a real password and keep it in Vaultwarden.
2. The offer of a free licence key is optional: it unlocks a few extra
   features in exchange for an email address, and n8n works fully without it.

## Reaching things, and being reached

- **n8n calling out** works for anything: other lab services by their
  in-cluster address (`http://paperless.paperless.svc.cluster.local`, and so
  on), and anything on the internet.
- **Lab services calling n8n** (Alertmanager, a Paperless workflow) use the
  Service, not the Ingress, which skips the gate:
  `http://n8n.n8n.svc.cluster.local/webhook/<path>`. The editor shows webhook
  URLs with the public host; swap the host for that one.
- **A phone or laptop calling a webhook** goes through the gate, so only a
  browser with a Pocket ID session gets through.
- **The internet calling n8n** (a Telegram bot, GitHub events) does not work:
  the lab is only on the LAN and the tailnet. Triggers that poll (Schedule,
  IMAP email, RSS, most "on new item" triggers) need none of that.

## Upgrades

Renovate proposes new versions; majors wait for approval on the dependency
dashboard. n8n tags its weekly pre-releases with plain version numbers too,
so the newest minor can be a beta for a week before it is promoted. Check the
[release notes](https://github.com/n8n-io/n8n/releases) before merging a
minor bump, and read the migration guide before any major.

## Backup - not yet, and in this order

The same three pieces as Paperless, whose README has the reasoning:

1. **The `restic-repo` Secret in the `n8n` namespace**, encrypted into
   `clusters/lab/backup/restic-repo-n8n.sops.yaml`. It uses the same values
   as the other copies and differs only in `metadata.namespace`.
2. **The `RoleBinding`**, already in `clusters/lab/backup/rbac.yaml`.
3. **`n8n/n8n-data` in `BACKUP_TARGETS`**, last, after the Secret has
   reconciled.
