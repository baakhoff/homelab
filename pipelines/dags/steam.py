"""The Steam account's data, into Kafka topic raw.steam.

Steam's Web API, with the account's own key (steamcommunity.com/dev/apikey):
every game in the library with its playtime, recently played games, the
profile, level and badges, the friends list with the friends' names, and
every game's achievements with their global rarity. Records go out in
ingest.py's envelope, masked first like every other source.

Steam reports playtime only as totals. Every run sends the whole library,
and raw keeps every run, so the difference between two runs is what was
played in between: ods.steam_playtime_daily. That history starts with the
first run; Steam keeps no record of earlier days.

Achievements are a call or two per game, so a game's are read again only
when its playtime has moved since the last time - Variable steam_playtime
holds the playtime each game had then - and the ods model keeps every
achievement's newest copy across runs.

STEAM_API_KEY and STEAM_ID (the account's SteamID64) come from the
airflow-sources Secret, put there by pipelines/tools/steam_key.py. The key
travels in the query string, so no error here prints a URL.
Steam answers only what the profile shows: "Game details" must be public,
or the library comes back empty and the run fails saying so. Setup:
pipelines/steam.md.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pendulum
import requests
from airflow.sdk import Variable, dag, task

# Secrets and identity numbers masked before anything leaves for Kafka -
# sensitive.py beside this file. Airflow puts the DAG folder, pipelines/, on
# the import path, not dags/, so the directory this file is in goes on first.
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sensitive import mask_record  # noqa: E402

KAFKA_BOOTSTRAP = "kafka.data.svc.cluster.local:9092"
TOPIC = "raw.steam"
API = "https://api.steampowered.com"
TIMEOUT = 60
SETUP = "pipelines/steam.md"
PLAYTIME = "steam_playtime"
# Between two calls. Steam allows 100,000 a day per key; the first run's
# achievements are a few hundred.
PAUSE = 0.3
# Most of at least this many games answering 500 is Steam itself down. Under
# it the games that always answer 500, asked again every run, can be most of
# a quiet run's games on their own.
BROKEN_QUORUM = 10


class _NoStats(Exception):
    """Steam's answer for a game without achievements, or one hidden."""


class _StatsBroken(Exception):
    """A server error for one game's stats. Steam answers 500 for some games
    every time - delisted ones, ones whose achievements were taken away - so
    it is that game's, not Steam being down."""


class _Steam:
    def __init__(self):
        self.key = os.environ.get("STEAM_API_KEY", "")
        self.steamid = os.environ.get("STEAM_ID", "")
        if not self.key or not self.steamid:
            raise RuntimeError(f"STEAM_API_KEY or STEAM_ID not set - see {SETUP}")
        self.session = requests.Session()

    def get(self, method: str, **params) -> dict:
        """One Web API method's JSON. Errors name the method, never the URL,
        which holds the key."""
        time.sleep(PAUSE)
        stats = "ISteamUserStats" in method
        for attempt in range(5):
            try:
                r = self.session.get(f"{API}/{method}", timeout=TIMEOUT,
                                     params={"key": self.key, "steamid": self.steamid, **params})
            except requests.RequestException as e:
                if attempt == 4:
                    raise RuntimeError(f"{method}: {type(e).__name__}") from None
                time.sleep(2 ** attempt)
                continue
            # A game's stats answering 500 is tried once more, not four times.
            if r.status_code in (429, 500, 502, 503) and attempt < (1 if stats and r.status_code == 500 else 4):
                time.sleep(min(2 ** attempt * 5, 60))
                continue
            if r.status_code in (400, 403) and stats:
                raise _NoStats()
            if r.status_code >= 500 and stats:
                raise _StatsBroken()
            if r.status_code == 401:
                raise RuntimeError(f"{method}: Steam refused the request (401) - the key is wrong, "
                                   f"or this part of the profile is private ({SETUP})")
            if not r.ok:
                raise RuntimeError(f"{method}: Steam answered {r.status_code}")
            return r.json()
        raise RuntimeError(f"{method}: Steam kept answering {r.status_code}")


class _Raw:
    """Envelopes to raw.steam, the way ingest.py writes them."""

    def __init__(self, run_id: str):
        from confluent_kafka import Producer

        self._producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "compression.type": "zstd",
            "linger.ms": 50,
        })
        self._errors: list[str] = []
        self._run_id = run_id
        self._extracted_at = datetime.now(timezone.utc).isoformat()
        self.counts: dict[str, int] = {}

    def _delivered(self, err, _msg):
        if err is not None:
            self._errors.append(str(err))

    def send(self, endpoint: str, rid, record) -> None:
        record, flags = mask_record(record)
        value = json.dumps({
            "source": "steam",
            "endpoint": endpoint,
            "extracted_at": self._extracted_at,
            "run_id": self._run_id,
            "id": str(rid),
            "record": record,
            **flags,
        }, ensure_ascii=False).encode()
        while True:
            try:
                self._producer.produce(TOPIC, key=f"{endpoint}:{rid}".encode(), value=value,
                                       on_delivery=self._delivered)
                break
            except BufferError:
                self._producer.poll(1)
        self._producer.poll(0)
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1

    def flush(self) -> None:
        left = self._producer.flush(120)
        if left or self._errors:
            raise RuntimeError(f"{left} undelivered, errors: {self._errors[:3]}")
        for endpoint, n in sorted(self.counts.items()):
            print(f"steam/{endpoint}: {n} records to {TOPIC}")


def _run_id() -> str:
    from airflow.sdk import get_current_context

    return get_current_context()["run_id"]


@dag(
    dag_id="ingest_steam",
    description="The Steam account into raw.steam: library and playtime, achievements, profile, friends",
    schedule="50 */6 * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["ingest", "steam"],
    default_args={"retries": 2, "retry_delay": pendulum.duration(minutes=5)},
)
def ingest_steam():
    @task
    def library() -> None:
        s, raw = _Steam(), _Raw(_run_id())
        owned = s.get("IPlayerService/GetOwnedGames/v1", include_appinfo=1,
                      include_played_free_games=1, skip_unvetted_apps=0).get("response", {})
        if "games" not in owned:
            raise RuntimeError("Steam listed no games: the profile's 'Game details' are not "
                               f"public - {SETUP}")
        for g in owned["games"]:
            raw.send("owned_games", g["appid"], g)
        recent = s.get("IPlayerService/GetRecentlyPlayedGames/v1").get("response", {})
        for g in recent.get("games", []):
            raw.send("recently_played", g["appid"], g)
        raw.flush()

    @task
    def profile() -> None:
        s, raw = _Steam(), _Raw(_run_id())
        players = s.get("ISteamUser/GetPlayerSummaries/v2", steamids=s.steamid)
        for p in players.get("response", {}).get("players", []):
            level = s.get("IPlayerService/GetSteamLevel/v1").get("response", {})
            raw.send("profile", p["steamid"], {**p, "player_level": level.get("player_level")})
        badges = s.get("IPlayerService/GetBadges/v1").get("response", {})
        for b in badges.get("badges", []):
            raw.send("badges", f"{b.get('appid', 0)}/{b['badgeid']}", b)
        # A private friends list answers 401: skipped, not failed.
        try:
            friends = s.get("ISteamUser/GetFriendList/v1", relationship="friend")
        except RuntimeError as e:
            if "(401)" not in str(e):
                raise
            print("friends: the friends list is private - skipped")
            friends = {}
        ids = [f["steamid"] for f in friends.get("friendslist", {}).get("friends", [])]
        for f in friends.get("friendslist", {}).get("friends", []):
            raw.send("friends", f["steamid"], f)
        for i in range(0, len(ids), 100):
            batch = s.get("ISteamUser/GetPlayerSummaries/v2", steamids=",".join(ids[i:i + 100]))
            for p in batch.get("response", {}).get("players", []):
                raw.send("friend_profiles", p["steamid"], p)
        raw.flush()

    @task(execution_timeout=timedelta(hours=2))
    def achievements() -> None:
        s, raw = _Steam(), _Raw(_run_id())
        seen = Variable.get(PLAYTIME, default=None, deserialize_json=True) or {}
        owned = s.get("IPlayerService/GetOwnedGames/v1", include_appinfo=1,
                      include_played_free_games=1).get("response", {}).get("games", [])
        games = [g for g in owned if g.get("playtime_forever", 0) > 0
                 and seen.get(str(g["appid"])) != g["playtime_forever"]]
        print(f"achievements: {len(games)} of {len(owned)} games played since last time")
        broken: list[str] = []
        for g in games:
            appid = g["appid"]
            try:
                stats = s.get("ISteamUserStats/GetPlayerAchievements/v1", appid=appid, l="english")
                mine = stats.get("playerstats", {}).get("achievements", [])
            except _NoStats:
                mine = []
            except _StatsBroken:
                # Not marked as read: the next run asks again.
                broken.append(f"{g.get('name')} ({appid})")
                continue
            if mine:
                try:
                    pct = s.get("ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2", gameid=appid)
                    # A number in some answers, a string in others.
                    rarity = {a["name"]: float(a["percent"])
                              for a in pct.get("achievementpercentages", {}).get("achievements", [])
                              if a.get("percent") is not None}
                except (_NoStats, _StatsBroken):
                    rarity = {}
                for a in mine:
                    raw.send("achievements", f"{appid}/{a['apiname']}",
                             {**a, "appid": appid, "game": g.get("name"),
                              "global_percent": rarity.get(a["apiname"])})
            seen[str(appid)] = g["playtime_forever"]
        raw.flush()
        # Only once Kafka has them: a failed run reads the same games again.
        Variable.set(PLAYTIME, seen, serialize_json=True)
        if broken:
            print(f"achievements: Steam answered 500 for {len(broken)}, asked again next run: "
                  + ", ".join(broken))
        # Most games failing is Steam itself, and worth a red run.
        if len(games) >= BROKEN_QUORUM and len(broken) > len(games) / 2:
            raise RuntimeError(f"Steam answered 500 for {len(broken)} of {len(games)} games")

    library()
    profile()
    achievements()


ingest_steam()
