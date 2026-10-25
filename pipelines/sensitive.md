# Masking sensitive data

Secrets and identity numbers are masked before anything reaches the
warehouse. A card number in a chat, a private key pasted into a note, a
password in a scanned letter or a token in a pod's log line never lands in
Kafka, ClickHouse, Loki, their backups, or an agent that reads them.

Two places do it, with the same rules:

- **`dags/sensitive.py`**, in every ingest job (Telegram, Proton Mail,
  Google, VK, Outline, Paperless, Firefly, Mealie, Vikunja, SparkyFitness, Dawarich, Immich, Plex, Radarr, Sonarr, CloudBeaver).
  Every string in a record, however deep, goes through it before the record
  is sent.
- **`mask_secrets` in `clusters/lab/logging/alloy.yaml`**, in the
  collectors, for every pod log line and Kubernetes event, before they split
  to Loki and Kafka.

Not covered: Home Assistant's state changes, which Home Assistant pushes to
Kafka itself. They are sensor states, not text people type.

## What is masked

What a mask keeps is enough to recognise the thing, never enough to use it.

**Recognised by shape** (both places):

| Kind | Example after masking |
|---|---|
| `card`: 13-19 digits that pass Luhn and start like a real card (Visa, Mastercard, Amex, Maestro, Mir, UnionPay, JCB, Discover, DinaCard) | `**** **** **** 4242` |
| `card_security_code`, `card_expiry`: after `CVV`/`CVC`, `exp`/`valid thru`/`važi do` | `cvv ***`, `exp *****` |
| `private_key`: PEM blocks (SSH, RSA, EC, PGP), PuTTY keys | `-----BEGIN OPENSSH PRIVATE KEY----- [masked] -----END ...` |
| `age_key`, `github_token`, `gitlab_token`, `aws_access_key`, `aws_secret_key`, `google_api_key`, `google_oauth`, `slack_token`, `slack_webhook`, `stripe_key`, `anthropic_key`, `openai_key`, `npm_token`, `pypi_token`, `sendgrid_key`, `huggingface_token`, `digitalocean_token`, `tailscale_key`, `telegram_bot_token`, `jwt`, `bearer_token` (an `Authorization: Bearer` header) | `ghp_a1B****cdef`: the first 7 and the last 4 characters |
| `url_password`: `scheme://user:password@host` | `postgres://app:****@db` |

**Recognised by the words around them**, in English, Russian, Serbian (both
scripts), Kazakh and Danish:

| Kind | Triggered by | Masked |
|---|---|---|
| `password` | `password`, `пароль`, `лозинка`/`lozinka`, `šifra`, `құпия сөз`, `adgangskode` ... then `:` `=` `-` or "is" | the whole value |
| `secret` | `token`, `secret`, `api key`, `ключ`/`кључ` ... then a value of 16+ characters that looks random | first 7 + last 4 |
| `one_time_code` | `login code`, `код`, `kod`, `PIN`, `OTP` ... then 4-8 digits; or "123456 is your ... code" | the whole code |
| `seed_phrase` | 12-24 words in a row, all from the BIP-39 list | `[seed phrase masked]` |

**Bank accounts and identity numbers**, each with its checksum (ingest
jobs only - RE2 in the collectors cannot compute one):

| Kind | What | Masked |
|---|---|---|
| `iban` | any IBAN that passes mod 97 | country + last 4 |
| `bank_account` | Serbian domestic account, `160-0000000123456-78`, with its check digits | last 4 |
| `national_id` | Serbian JMBG (13 digits, check digit), Danish CPR (`DDMMYY-XXXX`) | all |
| `passport` | a number after `passport`, `пасош`/`pasoš`, `паспорт` | all |

**Text aimed at a machine, not a person** (both places; the collectors
without the per-language checks):

| Kind | What | Becomes |
|---|---|---|
| `invisible_text` | characters that do not show but that a language model reads: the Unicode tag block (a known way to smuggle invisible instructions), zero-width spaces, direction overrides that make `invoice\u202Efdp.exe` display as `invoiceexe.pdf` | removed. The emoji joiner stays, or family and flag emoji would break |
| `encoded_blob` | long base64 (120+ characters, mixed case and digits) or hex (128+), `data:` URIs, `<script>` blocks, `javascript:` links, PowerShell `-EncodedCommand` | `[base64 blob, 1.4 KB, masked]`, `[script removed]` |
| `prompt_injection` | instructions to an AI: "ignore/disregard/forget previous instructions", "new instructions:", "you are now ...", "system prompt", "do not tell the user", in English, Russian, Serbian (both scripts), Kazakh and Danish; and chat-model role markers such as `<\|im_start\|>` and `[INST]` | `[instruction to an AI removed]` |

These are a speed bump, not a defence. They stop the copy-pasted attack and
the hidden one, and flag the record so whatever reads it can distrust it;
someone who rephrases gets through. What actually limits a misled agent is
what it is allowed to reach and send.

**Not masked, on purpose:** phone numbers, e-mail addresses, usernames.
They are how people are told apart across sources.

The collectors carry the patterns that need no checksum: keys, tokens, JWTs,
private keys, URL and `password:` values, bearer headers, cards written in
groups of four, invisible characters, scripts, base64 of 200+ characters,
and the AI-instruction phrases in English, Russian and Serbian. A web
request's path and User-Agent are written by whoever sends it, which is why
logs get these too.

## The flags

Every record from an ingest job carries three fields beside it in its
envelope:

- `sensitive`: true if anything was masked.
- `sensitive_kinds`: which kinds, e.g. `["card", "password"]`.
- `sensitive_fingerprints`: one per masked value, an HMAC-SHA256 under
  `SENSITIVE_FINGERPRINT_KEY`, cut to 16 hex characters. The same secret
  gives the same fingerprint in every source, so "where else did this key
  appear?" has an answer. Without the key nobody can test a guess against
  it, which matters for a four-digit PIN. If the key is missing, the
  masking still happens and the list stays empty.

Log lines and events carry `sensitive` and `sensitive_kinds` as attributes
(no fingerprints: the collectors have no key). `ods.logs` and
`ods.k8s_events` have both as columns.

`ods.sensitive_findings` puts all of it in one table:

```sql
SELECT source, arrayJoin(kinds) AS kind, count()
FROM ods.sensitive_findings GROUP BY source, kind ORDER BY count() DESC;

-- where else did this value turn up?
SELECT * FROM ods.sensitive_findings WHERE has(fingerprints, '0123456789abcdef');
```

## Setup: the fingerprint key

Once, on the workstation from the repo root, before this change merges:

```bash
sops set clusters/lab/airflow/sources.sops.yaml '["data"]["SENSITIVE_FINGERPRINT_KEY"]' "\"$(openssl rand -hex 32 | tr -d '\n' | base64 | tr -d '\n')\""
```

Commit and push. Never change it afterwards: a new key gives every secret a
new fingerprint, and old and new no longer match.

## Testing

```bash
uv run --with pytest pytest pipelines/tests
```

`tests/test_sensitive.py` has a masked and a left-alone example for every
kind - test cards, documentation keys, random strings of the right shape -
and phone numbers, dates, order numbers and ordinary sentences that must
come through unchanged. A new kind or a false alarm seen in the warehouse
is one more line there.

## Refetching what is already stored

Data stored before this change is unmasked. The sources that can be read
again are dropped and fetched again; the procedure is in the pull request
that added this file and in `ods.sensitive_findings` afterwards. Restic
snapshots of `data/data-clickhouse-0` taken before it keep the unmasked
data until the retention policy ages them out, six months at most.
