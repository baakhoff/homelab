# Steam

The Steam account's data, in the warehouse: `raw.steam`, then
`ods.steam_*`. One Airflow DAG, `ingest_steam` ([`dags/steam.py`](dags/steam.py)),
every 6 hours at :50, through Steam's [Web API](https://steamcommunity.com/dev)
with the account's own key.

| Model | One row per |
|---|---|
| `ods.steam_games` | game in the library: total playtime, per platform (Windows, Mac, Linux, Steam Deck) and offline, the last two weeks', when last played |
| `ods.steam_playtime_daily` | day and game played: the minutes its playtime grew by |
| `ods.steam_achievements` | achievement of every game played: unlocked or not, when, and the share of all players who have it |
| `ods.steam_friends` | friend: since when, their name, profile and country |
| `ods.steam_records` | the profile with its Steam level, each badge, each recently played game, as it came |

**Playtime per day is counted, not given.** Steam keeps only each game's
total. Every run sends the whole library, and the growth between two runs
is what was played in between. It is counted on the day of the later run,
in UTC, so a late evening's play can land on the next day. The history
starts with the first run. Steam keeps no record of earlier days, so
everything before that is in the totals only.

**Not here, and why.**
- **Purchases, the wallet, trades and the market**: not in the Web API. They
  exist only on Steam's store pages behind the login. Steam shows them at
  help.steampowered.com → *Data related to your Steam account*, with no
  file to export.
- **Chat**: not in the Web API either.
- **Workshop, reviews, screenshots**: not read.

## Setup

**1. The key.** <https://steamcommunity.com/dev/apikey>, signed in. The
domain it asks for can be anything, `localhost` for instance. Steam gives
keys only to accounts that are not limited, meaning ones that have spent
at least 5 USD in the store. A key reads what any visitor could read, and
makes no change to the account.

**2. Game details public.** Steam's API answers only what the profile
shows, even to the account's own key. On the profile: *Edit Profile* →
*Privacy Settings* → **Game details: Public**. Without it the library
comes back empty, and the DAG fails saying so. Anyone can then see the
library and the playtime. The friends list and the rest can stay as they
are. A private friends list leaves `ods.steam_friends` empty, and nothing
fails.

**3. Into the Secret.** On the workstation, from the repo root. Standard
library only:

```bash
python3 pipelines/tools/steam_key.py
```

It asks for the key, not echoed, and the SteamID64: the 17 digits in the
profile's address, `steamcommunity.com/profiles/7656...`. A profile with a
custom address has it on [steamid.io](https://steamid.io). It checks both
with Steam, says the account's name and how many games it sees, and writes
`STEAM_API_KEY` and `STEAM_ID` into `clusters/lab/airflow/sources.sops.yaml`
with `sops set`.

**4. Commit, push, restart.** Commit and push the Secret. Once Flux has
applied it, restart the scheduler, which reads its environment only at
start. Delete the pod rather than `rollout restart`, which Flux undoes:

```bash
kubectl -n airflow delete pod -l component=scheduler
kubectl -n data create job --from=cronjob/clickhouse-schema schema-steam
```

The second line creates the topic and `raw.steam` now rather than at the
hourly run.

**5. Run it.** In the Airflow UI, unpause `ingest_steam` and trigger it,
then `warehouse`. The first run reads every played game's achievements,
two calls a game. After that, only the games played since the run before.

```sql
SELECT name, round(playtime_minutes / 60) AS hours FROM ods.steam_games ORDER BY hours DESC LIMIT 20
```

## Things to know

- **The key does not expire.** It stops working if it is revoked on the
  key's page, which is also the way to cut the DAG off. Then run step 3
  again with a new one.
- **Steam's limit is 100,000 calls a day per key.** A run is a handful of
  calls, plus two for each game played since the last.
- **Achievements are read again only when a game's playtime moves.** The
  Variable `steam_playtime` holds what each game had at the last read.
  Deleting it makes the next run read every played game's again, which is
  how rarity is brought up to date.
- **The friends' names and profiles are other people's data**, as they
  show it publicly. They sit in ClickHouse, readable by its `admin` and
  `dbt` users, by CloudBeaver and by the `brand` agent, and in the nightly
  encrypted backup of `data/data-clickhouse-0`.
