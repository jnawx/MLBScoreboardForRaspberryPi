import argparse
import datetime as dt
import json
import math
import os
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Set, Tuple

import requests
from dotenv import load_dotenv

MLB_BASE_URL = "https://statsapi.mlb.com"
REQUEST_TIMEOUT_SECONDS = 20

BETTINGPROS_DEFAULT_API_KEY = ""
BETTINGPROS_DEFAULT_BASE_URL = "https://api.bettingpros.com/v3"
BOVADA_DEFAULT_MLB_URL = "https://www.bovada.lv/services/sports/event/coupon/events/A/description/baseball/mlb"
FANGRAPHS_LEADERS_BASE_URL = "https://www.fangraphs.com/api/leaders/major-league/data"

PLAYER_MARKET_ALIASES: Dict[str, str] = {
    "batter_hits": "hits",
    "hits": "hits",
    "batter_home_runs": "home_runs",
    "home_runs": "home_runs",
    "batter_total_bases": "total_bases",
    "total_bases": "total_bases",
    "batter_runs": "runs",
    "runs": "runs",
    "batter_rbis": "rbis",
    "rbis": "rbis",
    "batter_runs_hits_rbis": "runs_hits_rbis",
    "runs_hits_rbis": "runs_hits_rbis",
    "batter_stolen_bases": "stolen_bases",
    "stolen_bases": "stolen_bases",
    "pitcher_strikeouts": "strikeouts",
    "strikeouts": "strikeouts",
    "pitcher_outs": "outs_recorded",
    "outs": "outs_recorded",
    "outs_recorded": "outs_recorded",
    "pitcher_hits_allowed": "hits_allowed",
    "hits_allowed": "hits_allowed",
    "pitcher_earned_runs": "earned_runs",
    "earned_runs": "earned_runs",
}

PLAYER_MARKET_STORAGE_KEYS: Dict[str, str] = {
    "hits": "batter_hits",
    "home_runs": "batter_home_runs",
    "total_bases": "batter_total_bases",
    "runs": "batter_runs",
    "rbis": "batter_rbis",
    "runs_hits_rbis": "batter_runs_hits_rbis",
    "stolen_bases": "batter_stolen_bases",
    "strikeouts": "pitcher_strikeouts",
    "outs_recorded": "pitcher_outs",
    "hits_allowed": "pitcher_hits_allowed",
    "earned_runs": "pitcher_earned_runs",
}

GAME_MARKET_ALIASES: Dict[str, str] = {
    "h2h": "h2h",
    "moneyline": "h2h",
    "money_line": "h2h",
    "spreads": "spreads",
    "spread": "spreads",
    "runline": "spreads",
    "run_line": "spreads",
    "totals": "totals",
    "total": "totals",
    "total_runs": "totals",
}

BOVADA_MARKET_DESCRIPTION_TO_KEY: Dict[str, str] = {
    "moneyline": "h2h",
    "runline": "spreads",
    "total": "totals",
}


def env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def parse_csv_tokens(raw_value: Any) -> List[str]:
    if isinstance(raw_value, str):
        return [token.strip().lower() for token in raw_value.split(",") if token.strip()]

    if isinstance(raw_value, (list, tuple, set)):
        parsed: List[str] = []
        for item in raw_value:
            token = str(item).strip().lower()
            if token:
                parsed.append(token)
        return parsed

    token = str(raw_value or "").strip().lower()
    return [token] if token else []


def parse_int_csv(raw_value: str, fallback: List[int]) -> List[int]:
    parsed: List[int] = []
    seen = set()

    for token in parse_csv_tokens(raw_value):
        try:
            number = int(token)
        except ValueError:
            continue
        if number <= 0 or number in seen:
            continue
        seen.add(number)
        parsed.append(number)

    return parsed if parsed else list(fallback)


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_int_or_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_rate(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if text in {"", ".---", "---", "N/A"}:
        return default
    if text.startswith("."):
        text = f"0{text}"

    return safe_float(text, default)


def innings_to_outs(value: Any) -> int:
    if value is None:
        return 0

    if isinstance(value, int):
        return value * 3
    if isinstance(value, float):
        whole = int(math.floor(value))
        fractional = round(value - whole, 1)
        if abs(fractional - 0.1) < 0.01:
            return whole * 3 + 1
        if abs(fractional - 0.2) < 0.01:
            return whole * 3 + 2
        return int(round(value * 3))

    text = str(value).strip()
    if not text:
        return 0
    if "." not in text:
        return safe_int(text, 0) * 3

    whole_text, partial_text = text.split(".", 1)
    whole = safe_int(whole_text, 0)
    partial_text = partial_text.strip()
    if partial_text == "1":
        return whole * 3 + 1
    if partial_text == "2":
        return whole * 3 + 2
    return whole * 3


def outs_to_innings_decimal(outs: int) -> float:
    whole = outs // 3
    rem = outs % 3
    if rem == 0:
        return float(whole)
    if rem == 1:
        return whole + 0.1
    return whole + 0.2


def round_or_none(value: float, digits: int = 3) -> Any:
    if not math.isfinite(value):
        return None
    return round(value, digits)


def chunked(items: List[Any], size: int) -> Iterator[List[Any]]:
    if size <= 0:
        size = 1
    for index in range(0, len(items), size):
        yield items[index : index + size]


def parse_iso_datetime(raw_value: Any) -> dt.datetime | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_person_name(raw_value: Any) -> str:
    text = str(raw_value or "").strip().lower()
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    return " ".join(normalized.split())


def bool_as_int(value: Any, allow_none: bool = False) -> Any:
    if value is None and allow_none:
        return None
    return 1 if bool(value) else 0


def utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def mlb_get(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{MLB_BASE_URL}{path}"
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "PadresPiBoard/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Expected object JSON from MLB endpoint, got: {type(payload)!r}")


def parse_american_odds(raw_value: Any) -> Any:
    text = str(raw_value or "").strip().upper()
    if not text:
        return None
    if text == "EVEN":
        return 100
    return safe_int_or_none(text)


def implied_probability_from_american_odds(raw_value: Any) -> Any:
    odds = parse_american_odds(raw_value)
    if odds is None or odds == 0:
        return None

    if odds > 0:
        probability = 100.0 / (float(odds) + 100.0)
    else:
        absolute_odds = abs(float(odds))
        probability = absolute_odds / (absolute_odds + 100.0)

    if not math.isfinite(probability):
        return None

    return round(probability, 6)


def implied_probability_percent_from_american_odds(raw_value: Any) -> Any:
    probability = implied_probability_from_american_odds(raw_value)
    if probability is None:
        return None
    return round(float(probability) * 100.0, 4)


def normalize_line_group_key(market_key: str, line: Any, line_key: Any) -> str:
    token = parse_market_token(market_key)
    line_text = str(line_key or "").strip()

    if token == "spreads":
        point = safe_float(line, float("nan"))
        if math.isfinite(point):
            return f"{abs(point):.4f}".rstrip("0").rstrip(".")
        if line_text.startswith("+") or line_text.startswith("-"):
            return line_text[1:]
        return line_text

    if token == "totals":
        point = safe_float(line, float("nan"))
        if math.isfinite(point):
            return f"{point:.4f}".rstrip("0").rstrip(".")
        return line_text

    return line_text


def apply_no_vig_pair_to_odds_rows(first: Dict[str, Any], second: Dict[str, Any]) -> None:
    first_probability = implied_probability_from_american_odds(first.get("odds_price"))
    second_probability = implied_probability_from_american_odds(second.get("odds_price"))
    if first_probability is None or second_probability is None:
        return

    total = first_probability + second_probability
    if total <= 0 or not math.isfinite(total):
        return

    first_no_vig = round(first_probability / total, 6)
    second_no_vig = round(second_probability / total, 6)
    first["implied_probability"] = first_no_vig
    first["implied_probability_percent"] = round(first_no_vig * 100.0, 4)
    second["implied_probability"] = second_no_vig
    second["implied_probability_percent"] = round(second_no_vig * 100.0, 4)


def apply_no_vig_to_game_odds_rows(rows: List[Dict[str, Any]]) -> None:
    grouped: Dict[Tuple[str, str, str, str], Dict[str, Dict[str, Any]]] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        probability = implied_probability_from_american_odds(row.get("odds_price"))
        probability_percent = implied_probability_percent_from_american_odds(row.get("odds_price"))
        row["implied_probability"] = probability
        row["implied_probability_percent"] = probability_percent

        market_key = parse_market_token(row.get("market_key"))
        side = ""
        if market_key in {"h2h", "spreads"}:
            description = str(row.get("selection_description") or "").strip().lower()
            if description.startswith("home"):
                side = "home"
            elif description.startswith("away"):
                side = "away"
        elif market_key == "totals":
            selection_name = str(row.get("selection_name") or "").strip().lower()
            if selection_name.startswith("over"):
                side = "over"
            elif selection_name.startswith("under"):
                side = "under"

        if not side:
            continue

        group_key = (
            str(row.get("event_id") or "").strip(),
            str(row.get("bookmaker_key") or "").strip().lower(),
            market_key,
            normalize_line_group_key(market_key, row.get("line"), row.get("line_key")),
        )
        bucket = grouped.setdefault(group_key, {})
        if side not in bucket:
            bucket[side] = row

    for bucket in grouped.values():
        if "home" in bucket and "away" in bucket:
            apply_no_vig_pair_to_odds_rows(bucket["home"], bucket["away"])
        if "over" in bucket and "under" in bucket:
            apply_no_vig_pair_to_odds_rows(bucket["over"], bucket["under"])


def apply_no_vig_to_player_odds_rows(rows: List[Dict[str, Any]]) -> None:
    grouped: Dict[Tuple[str, str, str, str, str], Dict[str, Dict[str, Any]]] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue

        probability = implied_probability_from_american_odds(row.get("odds_price"))
        probability_percent = implied_probability_percent_from_american_odds(row.get("odds_price"))
        row["implied_probability"] = probability
        row["implied_probability_percent"] = probability_percent

        selection_name = str(row.get("selection_name") or "").strip().lower()
        if selection_name.startswith("over"):
            side = "over"
        elif selection_name.startswith("under"):
            side = "under"
        else:
            continue

        player_token = str(row.get("player_id") or row.get("player_name_normalized") or "").strip().lower()
        group_key = (
            str(row.get("event_id") or "").strip(),
            str(row.get("bookmaker_key") or "").strip().lower(),
            parse_market_token(row.get("market_key")),
            player_token,
            normalize_line_group_key(str(row.get("market_key") or ""), row.get("line"), row.get("line_key")),
        )
        bucket = grouped.setdefault(group_key, {})
        if side not in bucket:
            bucket[side] = row

    for bucket in grouped.values():
        if "over" in bucket and "under" in bucket:
            apply_no_vig_pair_to_odds_rows(bucket["over"], bucket["under"])


def parse_market_token(raw_value: Any) -> str:
    return str(raw_value or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_player_market_token(raw_value: Any) -> str:
    token = parse_market_token(raw_value)
    return PLAYER_MARKET_ALIASES.get(token, token)


def player_market_storage_key(canonical_key: str) -> str:
    return PLAYER_MARKET_STORAGE_KEYS.get(canonical_key, canonical_key)


def normalize_game_market_token(raw_value: Any) -> str:
    token = parse_market_token(raw_value)
    return GAME_MARKET_ALIASES.get(token, token)


def normalize_bettingpros_market_slug(raw_value: Any) -> str:
    slug = parse_market_token(raw_value)
    return PLAYER_MARKET_ALIASES.get(slug, slug)


def bettingpros_headers(api_key: str) -> Dict[str, str]:
    resolved_api_key = str(api_key or BETTINGPROS_DEFAULT_API_KEY).strip()
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.bettingpros.com",
        "Referer": "https://www.bettingpros.com/",
        "User-Agent": "PadresPiBoard/1.0",
    }
    if resolved_api_key:
        headers["x-api-key"] = resolved_api_key
    return headers


def bettingpros_get(
    base_url: str,
    endpoint: str,
    params: Dict[str, Any],
    api_key: str,
) -> Dict[str, Any]:
    response = requests.get(
        f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers=bettingpros_headers(api_key),
    )
    response.raise_for_status()

    payload = response.json()
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Expected object JSON from BettingPros endpoint, got: {type(payload)!r}")


def bettingpros_parse_scheduled_to_iso(raw_value: Any) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = dt.datetime.strptime(text, fmt)
            parsed = parsed.replace(tzinfo=dt.UTC)
            return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue

    parsed_iso = parse_iso_datetime(text)
    if not parsed_iso:
        return ""
    if parsed_iso.tzinfo is None:
        parsed_iso = parsed_iso.replace(tzinfo=dt.UTC)
    return parsed_iso.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp_millis_to_iso(raw_value: Any) -> str:
    stamp = safe_int(raw_value, 0)
    if stamp <= 0:
        return ""
    parsed = dt.datetime.fromtimestamp(stamp / 1000.0, tz=dt.UTC)
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bettingpros_team_name(event: Dict[str, Any], side: str) -> str:
    target_abbreviation = str(event.get(side) or "").strip().upper()
    participants = event.get("participants") if isinstance(event.get("participants"), list) else []
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        team = participant.get("team") if isinstance(participant.get("team"), dict) else {}
        abbreviation = str(team.get("abbreviation") or "").strip().upper()
        if abbreviation != target_abbreviation:
            continue

        city = str(team.get("city") or "").strip()
        nickname = str(participant.get("name") or "").strip()
        full_name = f"{city} {nickname}".strip()
        if full_name:
            return full_name
    return target_abbreviation


def resolve_team_id(team_map: Dict[str, int], *candidates: Any) -> int:
    for candidate in candidates:
        normalized = normalize_person_name(candidate)
        if not normalized:
            continue
        resolved = safe_int(team_map.get(normalized), 0)
        if resolved > 0:
            return resolved
    return 0


def bettingpros_collect_event_map(
    base_url: str,
    api_key: str,
    days_ahead: int,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    event_map: Dict[str, Dict[str, Any]] = {}
    dates_scanned: List[str] = []

    total_days = max(0, safe_int(days_ahead, 1))
    for offset in range(total_days + 1):
        event_date = (dt.date.today() + dt.timedelta(days=offset)).isoformat()
        dates_scanned.append(event_date)
        payload = bettingpros_get(
            base_url=base_url,
            endpoint="events",
            params={"sport": "MLB", "date": event_date},
            api_key=api_key,
        )
        for event in payload.get("events", []):
            if not isinstance(event, dict):
                continue

            event_id = str(event.get("id") or "").strip()
            if not event_id:
                continue

            home_abbreviation = str(event.get("home") or "").strip()
            away_abbreviation = str(event.get("visitor") or "").strip()
            event_map[event_id] = {
                "event_id": event_id,
                "sport_key": "baseball_mlb",
                "sport_title": "MLB",
                "commence_time": bettingpros_parse_scheduled_to_iso(event.get("scheduled")),
                "home_team": bettingpros_team_name(event, "home") or home_abbreviation,
                "away_team": bettingpros_team_name(event, "visitor") or away_abbreviation,
                "home_abbreviation": home_abbreviation,
                "away_abbreviation": away_abbreviation,
                "raw_event": event,
            }

    return event_map, dates_scanned


def bettingpros_collect_props(
    base_url: str,
    api_key: str,
    days_ahead: int,
    location: str,
    book_id: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    props: List[Dict[str, Any]] = []
    dates_scanned: List[str] = []

    total_days = max(0, safe_int(days_ahead, 1))
    for offset in range(total_days + 1):
        event_date = (dt.date.today() + dt.timedelta(days=offset)).isoformat()
        dates_scanned.append(event_date)

        params: Dict[str, Any] = {
            "sport": "MLB",
            "date": event_date,
        }
        if location:
            params["location"] = location
        if book_id:
            params["book_id"] = book_id

        payload = bettingpros_get(
            base_url=base_url,
            endpoint="props",
            params=params,
            api_key=api_key,
        )
        for row in payload.get("props", []):
            if isinstance(row, dict):
                props.append(row)

    return props, dates_scanned


def bovada_get_mlb_events(base_url: str) -> List[Dict[str, Any]]:
    response = requests.get(
        base_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={
            "User-Agent": "PadresPiBoard/1.0",
            "Accept": "application/json",
        },
    )
    response.raise_for_status()

    payload = response.json()
    events: List[Dict[str, Any]] = []

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_events = item.get("events") if isinstance(item.get("events"), list) else []
            for event in item_events:
                if isinstance(event, dict):
                    events.append(event)
    elif isinstance(payload, dict):
        for event in payload.get("events", []):
            if isinstance(event, dict):
                events.append(event)
    else:
        raise ValueError(f"Expected list or object JSON from Bovada endpoint, got: {type(payload)!r}")

    return events


def ensure_table_columns(connection: sqlite3.Connection, table_name: str, column_definitions: Dict[str, str]) -> None:
    existing_columns = {
        str(row[1]).strip().lower()
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        if isinstance(row, (list, tuple)) and len(row) > 1
    }

    for column_name, column_type in column_definitions.items():
        normalized_name = str(column_name).strip().lower()
        if not normalized_name or normalized_name in existing_columns:
            continue
        column_sql = f"{column_name} {column_type}".strip()
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            use_name TEXT,
            use_last_name TEXT,
            boxscore_name TEXT,
            primary_number TEXT,
            birth_date TEXT,
            current_age INTEGER,
            birth_city TEXT,
            birth_state_province TEXT,
            birth_country TEXT,
            height TEXT,
            weight INTEGER,
            active INTEGER NOT NULL DEFAULT 0,
            is_player INTEGER NOT NULL DEFAULT 1,
            is_verified INTEGER NOT NULL DEFAULT 0,
            draft_year INTEGER,
            mlb_debut_date TEXT,
            bat_side_code TEXT,
            bat_side_description TEXT,
            pitch_hand_code TEXT,
            pitch_hand_description TEXT,
            primary_position_code TEXT,
            primary_position_name TEXT,
            primary_position_type TEXT,
            primary_position_abbreviation TEXT,
            current_team_id INTEGER,
            current_team_name TEXT,
            current_team_link TEXT,
            last_synced_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_players_full_name ON players(full_name)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_players_team_id ON players(current_team_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_players_active ON players(active)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            game_pk INTEGER PRIMARY KEY,
            game_guid TEXT,
            link TEXT,
            game_type TEXT,
            season INTEGER NOT NULL,
            season_display TEXT,
            game_date TEXT,
            official_date TEXT,
            day_night TEXT,
            game_number INTEGER,
            double_header TEXT,
            gameday_type TEXT,
            tiebreaker TEXT,
            calendar_event_id TEXT,
            public_facing INTEGER,
            is_tie INTEGER,
            status_abstract TEXT,
            status_abstract_code TEXT,
            status_coded TEXT,
            status_code TEXT,
            status_detailed TEXT,
            start_time_tbd INTEGER,
            away_team_id INTEGER,
            away_team_name TEXT,
            away_team_score INTEGER,
            away_is_winner INTEGER,
            home_team_id INTEGER,
            home_team_name TEXT,
            home_team_score INTEGER,
            home_is_winner INTEGER,
            venue_id INTEGER,
            venue_name TEXT,
            content_link TEXT,
            last_synced_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_games_season ON games(season)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_games_official_date ON games(official_date)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_games_away_team_id ON games(away_team_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_games_home_team_id ON games(home_team_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_games_status_abstract ON games(status_abstract)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            abbreviation TEXT,
            team_code TEXT,
            file_code TEXT,
            franchise_name TEXT,
            club_name TEXT,
            short_name TEXT,
            location_name TEXT,
            team_name TEXT,
            first_year_of_play TEXT,
            active INTEGER NOT NULL DEFAULT 0,
            all_star_status TEXT,
            league_id INTEGER,
            league_name TEXT,
            division_id INTEGER,
            division_name TEXT,
            sport_id INTEGER,
            sport_name TEXT,
            venue_id INTEGER,
            venue_name TEXT,
            spring_venue_id INTEGER,
            spring_venue_name TEXT,
            last_synced_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_teams_name ON teams(name)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_teams_league_id ON teams(league_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_teams_division_id ON teams(division_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_teams_active ON teams(active)")

    batting_split_tables = [
        "batter_stats_season",
        "batter_stats_last_ten_games",
        "batter_stats_vs_rhp",
        "batter_stats_vs_lhp",
    ]
    for table_name in batting_split_tables:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                player_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                team_id INTEGER NOT NULL DEFAULT 0,
                team_name TEXT,
                player_name TEXT,
                split_code TEXT NOT NULL DEFAULT '',
                split_description TEXT,
                games_played INTEGER,
                at_bats INTEGER,
                plate_appearances INTEGER,
                runs INTEGER,
                hits INTEGER,
                doubles INTEGER,
                triples INTEGER,
                home_runs INTEGER,
                rbi INTEGER,
                strike_outs INTEGER,
                walks INTEGER,
                intentional_walks INTEGER,
                hit_by_pitch INTEGER,
                stolen_bases INTEGER,
                caught_stealing INTEGER,
                avg REAL,
                obp REAL,
                slg REAL,
                ops REAL,
                last_synced_utc TEXT NOT NULL,
                stat_json TEXT NOT NULL,
                PRIMARY KEY (player_id, season, team_id, split_code)
            )
            """
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_team ON {table_name}(team_id)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_player ON {table_name}(player_name)"
        )

    pitching_split_tables = [
        "pitcher_stats_season",
        "pitcher_stats_last_ten_games",
        "pitcher_stats_vs_rhp",
        "pitcher_stats_vs_lhp",
    ]
    for table_name in pitching_split_tables:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                player_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                team_id INTEGER NOT NULL DEFAULT 0,
                team_name TEXT,
                player_name TEXT,
                split_code TEXT NOT NULL DEFAULT '',
                split_description TEXT,
                games_played INTEGER,
                games_started INTEGER,
                wins INTEGER,
                losses INTEGER,
                saves INTEGER,
                holds INTEGER,
                outs_recorded INTEGER,
                innings_pitched REAL,
                hits INTEGER,
                runs INTEGER,
                earned_runs INTEGER,
                home_runs INTEGER,
                strike_outs INTEGER,
                walks INTEGER,
                intentional_walks INTEGER,
                hit_batters INTEGER,
                batters_faced INTEGER,
                pitches_thrown INTEGER,
                era REAL,
                fip REAL,
                whip REAL,
                strikeouts_per9 REAL,
                walks_per9 REAL,
                last_synced_utc TEXT NOT NULL,
                stat_json TEXT NOT NULL,
                PRIMARY KEY (player_id, season, team_id, split_code)
            )
            """
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_team ON {table_name}(team_id)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_player ON {table_name}(player_name)"
        )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS batter_stats_by_park (
            player_id INTEGER NOT NULL,
            player_name TEXT,
            park_id INTEGER NOT NULL,
            park_name TEXT,
            window_start_season INTEGER NOT NULL,
            window_end_season INTEGER NOT NULL,
            games_played INTEGER,
            at_bats INTEGER,
            plate_appearances INTEGER,
            runs INTEGER,
            hits INTEGER,
            doubles INTEGER,
            triples INTEGER,
            home_runs INTEGER,
            rbi INTEGER,
            strike_outs INTEGER,
            walks INTEGER,
            hit_by_pitch INTEGER,
            sac_flies INTEGER,
            total_bases INTEGER,
            stolen_bases INTEGER,
            caught_stealing INTEGER,
            avg REAL,
            obp REAL,
            slg REAL,
            ops REAL,
            seasons_covered_json TEXT,
            team_ids_json TEXT,
            last_synced_utc TEXT NOT NULL,
            totals_json TEXT NOT NULL,
            PRIMARY KEY (player_id, park_id, window_start_season, window_end_season)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_batter_stats_by_park_park ON batter_stats_by_park(park_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_batter_stats_by_park_player ON batter_stats_by_park(player_name)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS pitcher_stats_by_park (
            player_id INTEGER NOT NULL,
            player_name TEXT,
            park_id INTEGER NOT NULL,
            park_name TEXT,
            window_start_season INTEGER NOT NULL,
            window_end_season INTEGER NOT NULL,
            games_played INTEGER,
            games_started INTEGER,
            outs_recorded INTEGER,
            innings_pitched REAL,
            hits INTEGER,
            runs INTEGER,
            earned_runs INTEGER,
            home_runs INTEGER,
            strike_outs INTEGER,
            walks INTEGER,
            hit_batters INTEGER,
            batters_faced INTEGER,
            pitches_thrown INTEGER,
            era REAL,
            whip REAL,
            strikeouts_per9 REAL,
            walks_per9 REAL,
            seasons_covered_json TEXT,
            team_ids_json TEXT,
            last_synced_utc TEXT NOT NULL,
            totals_json TEXT NOT NULL,
            PRIMARY KEY (player_id, park_id, window_start_season, window_end_season)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_pitcher_stats_by_park_park ON pitcher_stats_by_park(park_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_pitcher_stats_by_park_player ON pitcher_stats_by_park(player_name)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS parks (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            active INTEGER,
            season TEXT,
            city TEXT,
            state TEXT,
            country TEXT,
            latitude REAL,
            longitude REAL,
            time_zone_id TEXT,
            time_zone_offset INTEGER,
            time_zone_tz TEXT,
            capacity INTEGER,
            turf_type TEXT,
            roof_type TEXT,
            left_line INTEGER,
            left_field INTEGER,
            left_center INTEGER,
            center_field INTEGER,
            right_center INTEGER,
            right_field INTEGER,
            right_line INTEGER,
            last_synced_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_parks_name ON parks(name)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS umpires (
            game_pk INTEGER NOT NULL,
            season INTEGER NOT NULL,
            official_date TEXT,
            official_type TEXT NOT NULL,
            umpire_id INTEGER NOT NULL,
            umpire_name TEXT,
            umpire_link TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            park_id INTEGER,
            last_synced_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            PRIMARY KEY (game_pk, official_type, umpire_id)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_umpires_umpire_id ON umpires(umpire_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_umpires_season ON umpires(season)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS batting_orders (
            game_pk INTEGER NOT NULL,
            season INTEGER NOT NULL,
            official_date TEXT,
            team_id INTEGER NOT NULL,
            team_name TEXT,
            park_id INTEGER,
            batting_order_code INTEGER NOT NULL,
            lineup_slot INTEGER,
            player_id INTEGER NOT NULL,
            player_name TEXT,
            position_abbreviation TEXT,
            position_name TEXT,
            batting_summary TEXT,
            is_substitute INTEGER NOT NULL DEFAULT 0,
            last_synced_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            PRIMARY KEY (game_pk, team_id, batting_order_code, player_id)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_batting_orders_player_id ON batting_orders(player_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_batting_orders_team_id ON batting_orders(team_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_batting_orders_season ON batting_orders(season)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS game_betting_odds (
            event_id TEXT NOT NULL,
            game_pk INTEGER,
            sport_key TEXT,
            sport_title TEXT,
            commence_time TEXT,
            home_team TEXT,
            away_team TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            bookmaker_key TEXT NOT NULL,
            bookmaker_title TEXT,
            market_key TEXT NOT NULL,
            market_last_update TEXT,
            selection_name TEXT NOT NULL,
            selection_description TEXT NOT NULL DEFAULT '',
            line REAL,
            line_key TEXT NOT NULL DEFAULT '',
            odds_price INTEGER,
            implied_probability REAL,
            implied_probability_percent REAL,
            last_synced_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            PRIMARY KEY (
                event_id,
                bookmaker_key,
                market_key,
                selection_name,
                selection_description,
                line_key
            )
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_game_betting_odds_game_pk ON game_betting_odds(game_pk)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_game_betting_odds_commence ON game_betting_odds(commence_time)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_game_betting_odds_market ON game_betting_odds(market_key)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS player_betting_odds (
            event_id TEXT NOT NULL,
            game_pk INTEGER,
            sport_key TEXT,
            sport_title TEXT,
            commence_time TEXT,
            home_team TEXT,
            away_team TEXT,
            home_team_id INTEGER,
            away_team_id INTEGER,
            player_id INTEGER,
            player_name TEXT NOT NULL,
            player_name_normalized TEXT NOT NULL,
            bookmaker_key TEXT NOT NULL,
            bookmaker_title TEXT,
            market_key TEXT NOT NULL,
            market_last_update TEXT,
            selection_name TEXT NOT NULL,
            line REAL,
            line_key TEXT NOT NULL DEFAULT '',
            odds_price INTEGER,
            implied_probability REAL,
            implied_probability_percent REAL,
            last_synced_utc TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            PRIMARY KEY (
                event_id,
                bookmaker_key,
                market_key,
                player_name_normalized,
                selection_name,
                line_key
            )
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_player_betting_odds_game_pk ON player_betting_odds(game_pk)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_player_betting_odds_player_id ON player_betting_odds(player_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_player_betting_odds_market ON player_betting_odds(market_key)")

    for table_name in [
        "pitcher_stats_season",
        "pitcher_stats_last_ten_games",
        "pitcher_stats_vs_rhp",
        "pitcher_stats_vs_lhp",
    ]:
        ensure_table_columns(connection, table_name, {"fip": "REAL"})

    for table_name in ["game_betting_odds", "player_betting_odds"]:
        ensure_table_columns(
            connection,
            table_name,
            {
                "implied_probability": "REAL",
                "implied_probability_percent": "REAL",
            },
        )
        connection.execute(
            f"""
            UPDATE {table_name}
            SET
                implied_probability = CASE
                    WHEN odds_price > 0 THEN ROUND(100.0 / (odds_price + 100.0), 6)
                    WHEN odds_price < 0 THEN ROUND(ABS(odds_price) / (ABS(odds_price) + 100.0), 6)
                    ELSE NULL
                END,
                implied_probability_percent = CASE
                    WHEN odds_price > 0 THEN ROUND((100.0 / (odds_price + 100.0)) * 100.0, 4)
                    WHEN odds_price < 0 THEN ROUND((ABS(odds_price) / (ABS(odds_price) + 100.0)) * 100.0, 4)
                    ELSE NULL
                END
            WHERE odds_price IS NOT NULL
              AND (implied_probability IS NULL OR implied_probability_percent IS NULL)
            """
        )


PLAYER_COLUMNS: List[str] = [
    "id",
    "full_name",
    "first_name",
    "last_name",
    "use_name",
    "use_last_name",
    "boxscore_name",
    "primary_number",
    "birth_date",
    "current_age",
    "birth_city",
    "birth_state_province",
    "birth_country",
    "height",
    "weight",
    "active",
    "is_player",
    "is_verified",
    "draft_year",
    "mlb_debut_date",
    "bat_side_code",
    "bat_side_description",
    "pitch_hand_code",
    "pitch_hand_description",
    "primary_position_code",
    "primary_position_name",
    "primary_position_type",
    "primary_position_abbreviation",
    "current_team_id",
    "current_team_name",
    "current_team_link",
    "last_synced_utc",
    "raw_json",
]

UPSERT_PLAYERS_SQL = f"""
INSERT INTO players ({', '.join(PLAYER_COLUMNS)})
VALUES ({', '.join('?' for _ in PLAYER_COLUMNS)})
ON CONFLICT(id) DO UPDATE SET
{', '.join(f'{column}=excluded.{column}' for column in PLAYER_COLUMNS if column != 'id')}
"""


GAME_COLUMNS: List[str] = [
    "game_pk",
    "game_guid",
    "link",
    "game_type",
    "season",
    "season_display",
    "game_date",
    "official_date",
    "day_night",
    "game_number",
    "double_header",
    "gameday_type",
    "tiebreaker",
    "calendar_event_id",
    "public_facing",
    "is_tie",
    "status_abstract",
    "status_abstract_code",
    "status_coded",
    "status_code",
    "status_detailed",
    "start_time_tbd",
    "away_team_id",
    "away_team_name",
    "away_team_score",
    "away_is_winner",
    "home_team_id",
    "home_team_name",
    "home_team_score",
    "home_is_winner",
    "venue_id",
    "venue_name",
    "content_link",
    "last_synced_utc",
    "raw_json",
]

UPSERT_GAMES_SQL = f"""
INSERT INTO games ({', '.join(GAME_COLUMNS)})
VALUES ({', '.join('?' for _ in GAME_COLUMNS)})
ON CONFLICT(game_pk) DO UPDATE SET
{', '.join(f'{column}=excluded.{column}' for column in GAME_COLUMNS if column != 'game_pk')}
"""


TEAM_COLUMNS: List[str] = [
    "id",
    "name",
    "abbreviation",
    "team_code",
    "file_code",
    "franchise_name",
    "club_name",
    "short_name",
    "location_name",
    "team_name",
    "first_year_of_play",
    "active",
    "all_star_status",
    "league_id",
    "league_name",
    "division_id",
    "division_name",
    "sport_id",
    "sport_name",
    "venue_id",
    "venue_name",
    "spring_venue_id",
    "spring_venue_name",
    "last_synced_utc",
    "raw_json",
]

UPSERT_TEAMS_SQL = f"""
INSERT INTO teams ({', '.join(TEAM_COLUMNS)})
VALUES ({', '.join('?' for _ in TEAM_COLUMNS)})
ON CONFLICT(id) DO UPDATE SET
{', '.join(f'{column}=excluded.{column}' for column in TEAM_COLUMNS if column != 'id')}
"""


BATTER_SPLIT_COLUMNS: List[str] = [
    "player_id",
    "season",
    "team_id",
    "team_name",
    "player_name",
    "split_code",
    "split_description",
    "games_played",
    "at_bats",
    "plate_appearances",
    "runs",
    "hits",
    "doubles",
    "triples",
    "home_runs",
    "rbi",
    "strike_outs",
    "walks",
    "intentional_walks",
    "hit_by_pitch",
    "stolen_bases",
    "caught_stealing",
    "avg",
    "obp",
    "slg",
    "ops",
    "last_synced_utc",
    "stat_json",
]

PITCHER_SPLIT_COLUMNS: List[str] = [
    "player_id",
    "season",
    "team_id",
    "team_name",
    "player_name",
    "split_code",
    "split_description",
    "games_played",
    "games_started",
    "wins",
    "losses",
    "saves",
    "holds",
    "outs_recorded",
    "innings_pitched",
    "hits",
    "runs",
    "earned_runs",
    "home_runs",
    "strike_outs",
    "walks",
    "intentional_walks",
    "hit_batters",
    "batters_faced",
    "pitches_thrown",
    "era",
    "fip",
    "whip",
    "strikeouts_per9",
    "walks_per9",
    "last_synced_utc",
    "stat_json",
]

BATTER_BY_PARK_COLUMNS: List[str] = [
    "player_id",
    "player_name",
    "park_id",
    "park_name",
    "window_start_season",
    "window_end_season",
    "games_played",
    "at_bats",
    "plate_appearances",
    "runs",
    "hits",
    "doubles",
    "triples",
    "home_runs",
    "rbi",
    "strike_outs",
    "walks",
    "hit_by_pitch",
    "sac_flies",
    "total_bases",
    "stolen_bases",
    "caught_stealing",
    "avg",
    "obp",
    "slg",
    "ops",
    "seasons_covered_json",
    "team_ids_json",
    "last_synced_utc",
    "totals_json",
]

PITCHER_BY_PARK_COLUMNS: List[str] = [
    "player_id",
    "player_name",
    "park_id",
    "park_name",
    "window_start_season",
    "window_end_season",
    "games_played",
    "games_started",
    "outs_recorded",
    "innings_pitched",
    "hits",
    "runs",
    "earned_runs",
    "home_runs",
    "strike_outs",
    "walks",
    "hit_batters",
    "batters_faced",
    "pitches_thrown",
    "era",
    "whip",
    "strikeouts_per9",
    "walks_per9",
    "seasons_covered_json",
    "team_ids_json",
    "last_synced_utc",
    "totals_json",
]

PARK_COLUMNS: List[str] = [
    "id",
    "name",
    "active",
    "season",
    "city",
    "state",
    "country",
    "latitude",
    "longitude",
    "time_zone_id",
    "time_zone_offset",
    "time_zone_tz",
    "capacity",
    "turf_type",
    "roof_type",
    "left_line",
    "left_field",
    "left_center",
    "center_field",
    "right_center",
    "right_field",
    "right_line",
    "last_synced_utc",
    "raw_json",
]

UMPIRE_COLUMNS: List[str] = [
    "game_pk",
    "season",
    "official_date",
    "official_type",
    "umpire_id",
    "umpire_name",
    "umpire_link",
    "home_team_id",
    "away_team_id",
    "park_id",
    "last_synced_utc",
    "raw_json",
]

BATTING_ORDER_COLUMNS: List[str] = [
    "game_pk",
    "season",
    "official_date",
    "team_id",
    "team_name",
    "park_id",
    "batting_order_code",
    "lineup_slot",
    "player_id",
    "player_name",
    "position_abbreviation",
    "position_name",
    "batting_summary",
    "is_substitute",
    "last_synced_utc",
    "raw_json",
]

GAME_BETTING_ODDS_COLUMNS: List[str] = [
    "event_id",
    "game_pk",
    "sport_key",
    "sport_title",
    "commence_time",
    "home_team",
    "away_team",
    "home_team_id",
    "away_team_id",
    "bookmaker_key",
    "bookmaker_title",
    "market_key",
    "market_last_update",
    "selection_name",
    "selection_description",
    "line",
    "line_key",
    "odds_price",
    "implied_probability",
    "implied_probability_percent",
    "last_synced_utc",
    "raw_json",
]

PLAYER_BETTING_ODDS_COLUMNS: List[str] = [
    "event_id",
    "game_pk",
    "sport_key",
    "sport_title",
    "commence_time",
    "home_team",
    "away_team",
    "home_team_id",
    "away_team_id",
    "player_id",
    "player_name",
    "player_name_normalized",
    "bookmaker_key",
    "bookmaker_title",
    "market_key",
    "market_last_update",
    "selection_name",
    "line",
    "line_key",
    "odds_price",
    "implied_probability",
    "implied_probability_percent",
    "last_synced_utc",
    "raw_json",
]


def build_upsert_sql(table_name: str, columns: List[str], conflict_columns: List[str]) -> str:
    conflict_sql = ", ".join(conflict_columns)
    update_columns = [column for column in columns if column not in set(conflict_columns)]
    update_sql = ", ".join(f"{column}=excluded.{column}" for column in update_columns)
    return (
        f"INSERT INTO {table_name} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT({conflict_sql}) DO UPDATE SET {update_sql}"
    )


UPSERT_BATTER_SPLIT_SQL_BY_TABLE: Dict[str, str] = {
    table_name: build_upsert_sql(table_name, BATTER_SPLIT_COLUMNS, ["player_id", "season", "team_id", "split_code"])
    for table_name in [
        "batter_stats_season",
        "batter_stats_last_ten_games",
        "batter_stats_vs_rhp",
        "batter_stats_vs_lhp",
    ]
}

UPSERT_PITCHER_SPLIT_SQL_BY_TABLE: Dict[str, str] = {
    table_name: build_upsert_sql(table_name, PITCHER_SPLIT_COLUMNS, ["player_id", "season", "team_id", "split_code"])
    for table_name in [
        "pitcher_stats_season",
        "pitcher_stats_last_ten_games",
        "pitcher_stats_vs_rhp",
        "pitcher_stats_vs_lhp",
    ]
}

UPSERT_BATTER_BY_PARK_SQL = build_upsert_sql(
    "batter_stats_by_park",
    BATTER_BY_PARK_COLUMNS,
    ["player_id", "park_id", "window_start_season", "window_end_season"],
)

UPSERT_PITCHER_BY_PARK_SQL = build_upsert_sql(
    "pitcher_stats_by_park",
    PITCHER_BY_PARK_COLUMNS,
    ["player_id", "park_id", "window_start_season", "window_end_season"],
)

UPSERT_PARK_SQL = build_upsert_sql("parks", PARK_COLUMNS, ["id"])
UPSERT_UMPIRE_SQL = build_upsert_sql("umpires", UMPIRE_COLUMNS, ["game_pk", "official_type", "umpire_id"])
UPSERT_BATTING_ORDER_SQL = build_upsert_sql(
    "batting_orders",
    BATTING_ORDER_COLUMNS,
    ["game_pk", "team_id", "batting_order_code", "player_id"],
)

UPSERT_GAME_BETTING_ODDS_SQL = build_upsert_sql(
    "game_betting_odds",
    GAME_BETTING_ODDS_COLUMNS,
    [
        "event_id",
        "bookmaker_key",
        "market_key",
        "selection_name",
        "selection_description",
        "line_key",
    ],
)

UPSERT_PLAYER_BETTING_ODDS_SQL = build_upsert_sql(
    "player_betting_odds",
    PLAYER_BETTING_ODDS_COLUMNS,
    [
        "event_id",
        "bookmaker_key",
        "market_key",
        "player_name_normalized",
        "selection_name",
        "line_key",
    ],
)


def person_to_row(person: Dict[str, Any], sync_stamp: str) -> Tuple[Any, ...]:
    bat_side = person.get("batSide") if isinstance(person.get("batSide"), dict) else {}
    pitch_hand = person.get("pitchHand") if isinstance(person.get("pitchHand"), dict) else {}
    primary_position = person.get("primaryPosition") if isinstance(person.get("primaryPosition"), dict) else {}
    current_team = person.get("currentTeam") if isinstance(person.get("currentTeam"), dict) else {}

    row_map: Dict[str, Any] = {
        "id": safe_int(person.get("id"), 0),
        "full_name": str(person.get("fullName") or "").strip(),
        "first_name": str(person.get("firstName") or "").strip(),
        "last_name": str(person.get("lastName") or "").strip(),
        "use_name": str(person.get("useName") or "").strip(),
        "use_last_name": str(person.get("useLastName") or "").strip(),
        "boxscore_name": str(person.get("boxscoreName") or "").strip(),
        "primary_number": str(person.get("primaryNumber") or "").strip(),
        "birth_date": str(person.get("birthDate") or "").strip(),
        "current_age": safe_int(person.get("currentAge"), 0),
        "birth_city": str(person.get("birthCity") or "").strip(),
        "birth_state_province": str(person.get("birthStateProvince") or "").strip(),
        "birth_country": str(person.get("birthCountry") or "").strip(),
        "height": str(person.get("height") or "").strip(),
        "weight": safe_int(person.get("weight"), 0),
        "active": 1 if bool(person.get("active", False)) else 0,
        "is_player": 1 if bool(person.get("isPlayer", True)) else 0,
        "is_verified": 1 if bool(person.get("isVerified", False)) else 0,
        "draft_year": safe_int(person.get("draftYear"), 0),
        "mlb_debut_date": str(person.get("mlbDebutDate") or "").strip(),
        "bat_side_code": str(bat_side.get("code") or "").strip(),
        "bat_side_description": str(bat_side.get("description") or "").strip(),
        "pitch_hand_code": str(pitch_hand.get("code") or "").strip(),
        "pitch_hand_description": str(pitch_hand.get("description") or "").strip(),
        "primary_position_code": str(primary_position.get("code") or "").strip(),
        "primary_position_name": str(primary_position.get("name") or "").strip(),
        "primary_position_type": str(primary_position.get("type") or "").strip(),
        "primary_position_abbreviation": str(primary_position.get("abbreviation") or "").strip(),
        "current_team_id": safe_int(current_team.get("id"), 0),
        "current_team_name": str(current_team.get("name") or "").strip(),
        "current_team_link": str(current_team.get("link") or "").strip(),
        "last_synced_utc": sync_stamp,
        "raw_json": json.dumps(person, separators=(",", ":"), sort_keys=True),
    }

    return tuple(row_map[column] for column in PLAYER_COLUMNS)


def fetch_players_payload(sport_id: int) -> List[Dict[str, Any]]:
    payload = mlb_get(f"/api/v1/sports/{sport_id}/players")
    people = payload.get("people", []) if isinstance(payload, dict) else []
    if not isinstance(people, list):
        return []
    return [person for person in people if isinstance(person, dict)]


def fetch_schedule_payload(sport_id: int, season: int) -> Tuple[int, List[Dict[str, Any]]]:
    payload = mlb_get(
        "/api/v1/schedule",
        params={
            "sportId": sport_id,
            "season": season,
        },
    )

    dates = payload.get("dates", []) if isinstance(payload, dict) else []
    if not isinstance(dates, list):
        return 0, []

    games: List[Dict[str, Any]] = []
    for date_entry in dates:
        if not isinstance(date_entry, dict):
            continue
        for game in date_entry.get("games", []):
            if isinstance(game, dict):
                games.append(game)

    return len(dates), games


def fetch_teams_metadata_payload(sport_id: int, season: int) -> List[Dict[str, Any]]:
    payload = mlb_get(
        "/api/v1/teams",
        params={
            "sportId": sport_id,
            "season": season,
        },
    )

    teams = payload.get("teams", []) if isinstance(payload, dict) else []
    if not isinstance(teams, list):
        return []
    return [team for team in teams if isinstance(team, dict)]


def load_team_sources_from_games(
    connection: sqlite3.Connection,
    seasons: Iterable[int],
) -> Tuple[Dict[int, Dict[str, Any]], int]:
    requested_seasons = [season for season in seasons if season > 0]
    if not requested_seasons:
        requested_seasons = [dt.date.today().year]

    placeholders = ", ".join("?" for _ in requested_seasons)
    query = f"""
        SELECT team_id, team_name, season
        FROM (
            SELECT home_team_id AS team_id, home_team_name AS team_name, season
            FROM games
            WHERE season IN ({placeholders})

            UNION ALL

            SELECT away_team_id AS team_id, away_team_name AS team_name, season
            FROM games
            WHERE season IN ({placeholders})
        ) team_rows
        WHERE team_id IS NOT NULL AND team_id > 0
    """

    source_map: Dict[int, Dict[str, Any]] = {}
    scanned_rows = 0
    params = tuple(requested_seasons) + tuple(requested_seasons)

    for team_id_value, team_name, season in connection.execute(query, params):
        scanned_rows += 1
        team_id = safe_int(team_id_value, 0)
        if team_id <= 0:
            continue

        row = source_map.setdefault(team_id, {"names": set(), "seasons": set()})
        if isinstance(team_name, str) and team_name.strip():
            row["names"].add(team_name.strip())

        season_value = safe_int(season, 0)
        if season_value > 0:
            row["seasons"].add(season_value)

    return source_map, scanned_rows


def team_payload_to_row(team_id: int, team_payload: Dict[str, Any], fallback_name: str, sync_stamp: str) -> Tuple[Any, ...]:
    payload = team_payload if isinstance(team_payload, dict) else {}
    league = payload.get("league") if isinstance(payload.get("league"), dict) else {}
    division = payload.get("division") if isinstance(payload.get("division"), dict) else {}
    sport = payload.get("sport") if isinstance(payload.get("sport"), dict) else {}
    venue = payload.get("venue") if isinstance(payload.get("venue"), dict) else {}
    spring_venue = payload.get("springVenue") if isinstance(payload.get("springVenue"), dict) else {}

    row_map: Dict[str, Any] = {
        "id": team_id,
        "name": str(payload.get("name") or fallback_name or f"Team {team_id}").strip(),
        "abbreviation": str(payload.get("abbreviation") or "").strip(),
        "team_code": str(payload.get("teamCode") or "").strip(),
        "file_code": str(payload.get("fileCode") or "").strip(),
        "franchise_name": str(payload.get("franchiseName") or "").strip(),
        "club_name": str(payload.get("clubName") or "").strip(),
        "short_name": str(payload.get("shortName") or "").strip(),
        "location_name": str(payload.get("locationName") or "").strip(),
        "team_name": str(payload.get("teamName") or "").strip(),
        "first_year_of_play": str(payload.get("firstYearOfPlay") or "").strip(),
        "active": bool_as_int(payload.get("active"), allow_none=False),
        "all_star_status": str(payload.get("allStarStatus") or "").strip(),
        "league_id": safe_int_or_none(league.get("id")),
        "league_name": str(league.get("name") or "").strip(),
        "division_id": safe_int_or_none(division.get("id")),
        "division_name": str(division.get("name") or "").strip(),
        "sport_id": safe_int_or_none(sport.get("id")),
        "sport_name": str(sport.get("name") or "").strip(),
        "venue_id": safe_int_or_none(venue.get("id")),
        "venue_name": str(venue.get("name") or "").strip(),
        "spring_venue_id": safe_int_or_none(spring_venue.get("id")),
        "spring_venue_name": str(spring_venue.get("name") or "").strip(),
        "last_synced_utc": sync_stamp,
        "raw_json": json.dumps(payload, separators=(",", ":"), sort_keys=True),
    }

    return tuple(row_map[column] for column in TEAM_COLUMNS)


def fetch_stats_splits_paginated(
    sport_id: int,
    season: int,
    group: str,
    stats_type: str,
    game_type: str,
    sit_code: str,
    page_size: int,
) -> Dict[str, Any]:
    splits: List[Dict[str, Any]] = []
    total_splits = 0
    offset = 0
    page_size = max(1, page_size)
    pages = 0

    while True:
        params: Dict[str, Any] = {
            "sportIds": sport_id,
            "season": season,
            "group": group,
            "stats": stats_type,
            "playerPool": "ALL",
            "limit": page_size,
            "offset": offset,
        }
        if game_type:
            params["gameType"] = game_type
        if sit_code:
            params["sitCodes"] = sit_code

        payload = mlb_get("/api/v1/stats", params=params)
        stats_rows = payload.get("stats", []) if isinstance(payload, dict) else []
        row = stats_rows[0] if stats_rows and isinstance(stats_rows[0], dict) else {}
        page_splits = row.get("splits", []) if isinstance(row.get("splits"), list) else []

        pages += 1
        total_splits = max(total_splits, safe_int(row.get("totalSplits"), 0))
        splits.extend(split for split in page_splits if isinstance(split, dict))

        if not page_splits:
            break

        offset += len(page_splits)
        if total_splits > 0 and offset >= total_splits:
            break
        if len(page_splits) < page_size and total_splits == 0:
            break

    return {
        "splits": splits,
        "totalSplits": total_splits,
        "pages": pages,
    }


def batter_split_to_row(
    split: Dict[str, Any],
    season: int,
    split_code_override: str,
    split_description_override: str,
    sync_stamp: str,
) -> Tuple[Any, ...] | None:
    player = split.get("player") if isinstance(split.get("player"), dict) else {}
    team = split.get("team") if isinstance(split.get("team"), dict) else {}
    split_blob = split.get("split") if isinstance(split.get("split"), dict) else {}
    stat = split.get("stat") if isinstance(split.get("stat"), dict) else {}

    player_id = safe_int(player.get("id"), 0)
    if player_id <= 0:
        return None

    team_id = safe_int(team.get("id"), 0)
    split_code = str(split_code_override or split_blob.get("code") or "").strip()
    split_description = str(split_description_override or split_blob.get("description") or "").strip()

    at_bats = safe_int(stat.get("atBats"), 0)
    walks = safe_int(stat.get("baseOnBalls"), 0)
    hit_by_pitch = safe_int(stat.get("hitByPitch"), 0)
    sac_flies = safe_int(stat.get("sacFlies"), 0)

    plate_appearances = safe_int(stat.get("plateAppearances"), 0)
    if plate_appearances <= 0:
        plate_appearances = at_bats + walks + hit_by_pitch + sac_flies

    avg = parse_rate(stat.get("avg"), 0.0)
    obp = parse_rate(stat.get("obp"), parse_rate(stat.get("onBasePercentage"), 0.0))
    slg = parse_rate(stat.get("slg"), parse_rate(stat.get("sluggingPercentage"), 0.0))
    ops = parse_rate(stat.get("ops"), 0.0)

    if avg <= 0 and at_bats > 0:
        avg = safe_int(stat.get("hits"), 0) / at_bats
    if obp <= 0 and plate_appearances > 0:
        obp = (safe_int(stat.get("hits"), 0) + walks + hit_by_pitch) / plate_appearances
    if slg <= 0 and at_bats > 0:
        total_bases = safe_int(stat.get("totalBases"), 0)
        if total_bases <= 0:
            total_bases = (
                safe_int(stat.get("hits"), 0)
                + safe_int(stat.get("doubles"), 0)
                + (2 * safe_int(stat.get("triples"), 0))
                + (3 * safe_int(stat.get("homeRuns"), 0))
            )
        slg = total_bases / at_bats
    if ops <= 0:
        ops = obp + slg

    row_map = {
        "player_id": player_id,
        "season": season,
        "team_id": team_id,
        "team_name": str(team.get("name") or "").strip(),
        "player_name": str(player.get("fullName") or "").strip(),
        "split_code": split_code,
        "split_description": split_description,
        "games_played": safe_int(stat.get("gamesPlayed"), 0),
        "at_bats": at_bats,
        "plate_appearances": plate_appearances,
        "runs": safe_int(stat.get("runs"), 0),
        "hits": safe_int(stat.get("hits"), 0),
        "doubles": safe_int(stat.get("doubles"), 0),
        "triples": safe_int(stat.get("triples"), 0),
        "home_runs": safe_int(stat.get("homeRuns"), 0),
        "rbi": safe_int(stat.get("rbi"), 0),
        "strike_outs": safe_int(stat.get("strikeOuts"), 0),
        "walks": walks,
        "intentional_walks": safe_int(stat.get("intentionalWalks"), 0),
        "hit_by_pitch": hit_by_pitch,
        "stolen_bases": safe_int(stat.get("stolenBases"), 0),
        "caught_stealing": safe_int(stat.get("caughtStealing"), 0),
        "avg": round_or_none(avg, 4),
        "obp": round_or_none(obp, 4),
        "slg": round_or_none(slg, 4),
        "ops": round_or_none(ops, 4),
        "last_synced_utc": sync_stamp,
        "stat_json": json.dumps(stat, separators=(",", ":"), sort_keys=True),
    }

    return tuple(row_map[column] for column in BATTER_SPLIT_COLUMNS)


def pitcher_split_to_row(
    split: Dict[str, Any],
    season: int,
    split_code_override: str,
    split_description_override: str,
    sync_stamp: str,
) -> Tuple[Any, ...] | None:
    player = split.get("player") if isinstance(split.get("player"), dict) else {}
    team = split.get("team") if isinstance(split.get("team"), dict) else {}
    split_blob = split.get("split") if isinstance(split.get("split"), dict) else {}
    stat = split.get("stat") if isinstance(split.get("stat"), dict) else {}

    player_id = safe_int(player.get("id"), 0)
    if player_id <= 0:
        return None

    team_id = safe_int(team.get("id"), 0)
    split_code = str(split_code_override or split_blob.get("code") or "").strip()
    split_description = str(split_description_override or split_blob.get("description") or "").strip()

    outs_recorded = safe_int(stat.get("outs"), 0)
    if outs_recorded <= 0:
        outs_recorded = innings_to_outs(stat.get("inningsPitched"))

    innings_pitched = outs_to_innings_decimal(outs_recorded)
    innings_for_rates = outs_recorded / 3.0 if outs_recorded > 0 else 0.0

    era = parse_rate(stat.get("era"), 0.0)
    if era <= 0 and innings_for_rates > 0:
        era = (safe_int(stat.get("earnedRuns"), 0) * 9.0) / innings_for_rates

    # MLB StatsAPI often omits FIP for season splits; keep it null instead of forcing 0.0.
    fip = parse_rate(stat.get("fip"), math.nan)

    whip = parse_rate(stat.get("whip"), 0.0)
    if whip <= 0 and innings_for_rates > 0:
        whip = (safe_int(stat.get("hits"), 0) + safe_int(stat.get("baseOnBalls"), 0)) / innings_for_rates

    strikeouts_per9 = parse_rate(stat.get("strikeoutsPer9Inn"), 0.0)
    if strikeouts_per9 <= 0 and innings_for_rates > 0:
        strikeouts_per9 = (safe_int(stat.get("strikeOuts"), 0) * 9.0) / innings_for_rates

    walks_per9 = parse_rate(stat.get("walksPer9Inn"), 0.0)
    if walks_per9 <= 0 and innings_for_rates > 0:
        walks_per9 = (safe_int(stat.get("baseOnBalls"), 0) * 9.0) / innings_for_rates

    row_map = {
        "player_id": player_id,
        "season": season,
        "team_id": team_id,
        "team_name": str(team.get("name") or "").strip(),
        "player_name": str(player.get("fullName") or "").strip(),
        "split_code": split_code,
        "split_description": split_description,
        "games_played": safe_int(stat.get("gamesPlayed"), 0),
        "games_started": safe_int(stat.get("gamesStarted"), 0),
        "wins": safe_int(stat.get("wins"), 0),
        "losses": safe_int(stat.get("losses"), 0),
        "saves": safe_int(stat.get("saves"), 0),
        "holds": safe_int(stat.get("holds"), 0),
        "outs_recorded": outs_recorded,
        "innings_pitched": round_or_none(innings_pitched, 1),
        "hits": safe_int(stat.get("hits"), 0),
        "runs": safe_int(stat.get("runs"), 0),
        "earned_runs": safe_int(stat.get("earnedRuns"), 0),
        "home_runs": safe_int(stat.get("homeRuns"), 0),
        "strike_outs": safe_int(stat.get("strikeOuts"), 0),
        "walks": safe_int(stat.get("baseOnBalls"), 0),
        "intentional_walks": safe_int(stat.get("intentionalWalks"), 0),
        "hit_batters": safe_int(stat.get("hitByPitch"), 0),
        "batters_faced": safe_int(stat.get("battersFaced"), 0),
        "pitches_thrown": safe_int(stat.get("numberOfPitches"), safe_int(stat.get("pitchesThrown"), 0)),
        "era": round_or_none(era, 4),
        "fip": round_or_none(fip, 4),
        "whip": round_or_none(whip, 4),
        "strikeouts_per9": round_or_none(strikeouts_per9, 4),
        "walks_per9": round_or_none(walks_per9, 4),
        "last_synced_utc": sync_stamp,
        "stat_json": json.dumps(stat, separators=(",", ":"), sort_keys=True),
    }

    return tuple(row_map[column] for column in PITCHER_SPLIT_COLUMNS)


def update_batter_split_table(
    connection: sqlite3.Connection,
    table_name: str,
    sport_id: int,
    season: int,
    stats_type: str,
    game_type: str,
    sit_code: str,
    split_code_override: str,
    split_description_override: str,
    page_size: int,
    prune_missing: bool,
) -> Dict[str, Any]:
    sync_stamp = utc_now_iso()
    existing_keys = {
        tuple(row)
        for row in connection.execute(
            f"SELECT player_id, season, team_id, split_code FROM {table_name} WHERE season = ?",
            (season,),
        )
    }

    fetched = fetch_stats_splits_paginated(
        sport_id=sport_id,
        season=season,
        group="hitting",
        stats_type=stats_type,
        game_type=game_type,
        sit_code=sit_code,
        page_size=page_size,
    )

    inserted = 0
    updated = 0
    skipped = 0

    upsert_sql = UPSERT_BATTER_SPLIT_SQL_BY_TABLE[table_name]
    for split in fetched["splits"]:
        row = batter_split_to_row(
            split,
            season=season,
            split_code_override=split_code_override,
            split_description_override=split_description_override,
            sync_stamp=sync_stamp,
        )
        if not row:
            skipped += 1
            continue

        key = (row[0], row[1], row[2], row[5])
        if key in existing_keys:
            updated += 1
        else:
            inserted += 1
            existing_keys.add(key)

        connection.execute(upsert_sql, row)

    deleted = 0
    if prune_missing:
        cursor = connection.execute(
            f"DELETE FROM {table_name} WHERE season = ? AND last_synced_utc <> ?",
            (season, sync_stamp),
        )
        deleted = max(cursor.rowcount, 0)

    return {
        "season": season,
        "sportId": sport_id,
        "statsType": stats_type,
        "sitCode": sit_code,
        "totalSplits": fetched["totalSplits"],
        "fetchedSplits": len(fetched["splits"]),
        "pages": fetched["pages"],
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "pruneMissing": prune_missing,
        "syncedAtUtc": sync_stamp,
    }


def update_pitcher_split_table(
    connection: sqlite3.Connection,
    table_name: str,
    sport_id: int,
    season: int,
    stats_type: str,
    game_type: str,
    sit_code: str,
    split_code_override: str,
    split_description_override: str,
    page_size: int,
    prune_missing: bool,
) -> Dict[str, Any]:
    sync_stamp = utc_now_iso()
    existing_keys = {
        tuple(row)
        for row in connection.execute(
            f"SELECT player_id, season, team_id, split_code FROM {table_name} WHERE season = ?",
            (season,),
        )
    }

    fetched = fetch_stats_splits_paginated(
        sport_id=sport_id,
        season=season,
        group="pitching",
        stats_type=stats_type,
        game_type=game_type,
        sit_code=sit_code,
        page_size=page_size,
    )

    inserted = 0
    updated = 0
    skipped = 0

    upsert_sql = UPSERT_PITCHER_SPLIT_SQL_BY_TABLE[table_name]
    for split in fetched["splits"]:
        row = pitcher_split_to_row(
            split,
            season=season,
            split_code_override=split_code_override,
            split_description_override=split_description_override,
            sync_stamp=sync_stamp,
        )
        if not row:
            skipped += 1
            continue

        key = (row[0], row[1], row[2], row[5])
        if key in existing_keys:
            updated += 1
        else:
            inserted += 1
            existing_keys.add(key)

        connection.execute(upsert_sql, row)

    deleted = 0
    if prune_missing:
        cursor = connection.execute(
            f"DELETE FROM {table_name} WHERE season = ? AND last_synced_utc <> ?",
            (season, sync_stamp),
        )
        deleted = max(cursor.rowcount, 0)

    return {
        "season": season,
        "sportId": sport_id,
        "statsType": stats_type,
        "sitCode": sit_code,
        "totalSplits": fetched["totalSplits"],
        "fetchedSplits": len(fetched["splits"]),
        "pages": fetched["pages"],
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "pruneMissing": prune_missing,
        "syncedAtUtc": sync_stamp,
    }


def fetch_fangraphs_pitching_fip_by_player_id(season: int, page_size: int = 1000) -> Dict[int, float]:
    fip_by_player_id: Dict[int, float] = {}
    page_number = 1
    page_size = max(1, page_size)

    while True:
        response = requests.get(
            FANGRAPHS_LEADERS_BASE_URL,
            params={
                "pos": "all",
                "stats": "pit",
                "lg": "all",
                "qual": "0",
                "type": "8",
                "season": season,
                "season1": season,
                "month": "0",
                "ind": "0",
                "team": "0",
                "players": "0",
                "pageitems": page_size,
                "pagenum": page_number,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "User-Agent": "PadresPiBoard/1.0",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected object JSON from Fangraphs leaders endpoint, got: {type(payload)!r}")

        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise ValueError(f"Expected list row payload from Fangraphs leaders endpoint, got: {type(rows)!r}")

        for row in rows:
            if not isinstance(row, dict):
                continue

            player_id = safe_int(row.get("xMLBAMID"), 0)
            if player_id <= 0:
                continue

            fip_value = parse_rate(row.get("FIP"), math.nan)
            if not math.isfinite(fip_value):
                continue

            fip_by_player_id[player_id] = round(fip_value, 4)

        if len(rows) < page_size:
            break

        page_number += 1

    return fip_by_player_id


def update_pitcher_season_fip_from_fangraphs(connection: sqlite3.Connection, season: int) -> Dict[str, Any]:
    ensure_table_columns(connection, "pitcher_stats_season", {"fip": "REAL"})

    existing_player_ids = {
        safe_int(row[0], 0)
        for row in connection.execute(
            "SELECT DISTINCT player_id FROM pitcher_stats_season WHERE season = ?",
            (season,),
        ).fetchall()
    }
    existing_player_ids.discard(0)

    if not existing_player_ids:
        return {
            "season": season,
            "source": "fangraphs",
            "rowsInPitcherSeasonTable": 0,
            "fetchedPlayers": 0,
            "matchedPlayers": 0,
            "missingPlayers": 0,
            "updatedRows": 0,
            "note": "No pitcher_stats_season rows found for selected season.",
        }

    fip_by_player_id = fetch_fangraphs_pitching_fip_by_player_id(season=season)

    matched_players = 0
    updated_rows = 0
    for player_id in sorted(existing_player_ids):
        fip_value = fip_by_player_id.get(player_id)
        if fip_value is None:
            continue

        matched_players += 1
        cursor = connection.execute(
            """
            UPDATE pitcher_stats_season
            SET fip = ?
            WHERE season = ?
              AND player_id = ?
            """,
            (fip_value, season, player_id),
        )
        updated_rows += max(cursor.rowcount, 0)

    return {
        "season": season,
        "source": "fangraphs",
        "rowsInPitcherSeasonTable": len(existing_player_ids),
        "fetchedPlayers": len(fip_by_player_id),
        "matchedPlayers": matched_players,
        "missingPlayers": max(0, len(existing_player_ids) - matched_players),
        "updatedRows": updated_rows,
    }


def game_to_row(game: Dict[str, Any], sync_stamp: str, default_season: int) -> Tuple[Any, ...]:
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    teams = game.get("teams") if isinstance(game.get("teams"), dict) else {}

    away_row = teams.get("away") if isinstance(teams.get("away"), dict) else {}
    home_row = teams.get("home") if isinstance(teams.get("home"), dict) else {}
    away_team = away_row.get("team") if isinstance(away_row.get("team"), dict) else {}
    home_team = home_row.get("team") if isinstance(home_row.get("team"), dict) else {}

    venue = game.get("venue") if isinstance(game.get("venue"), dict) else {}
    content = game.get("content") if isinstance(game.get("content"), dict) else {}

    row_map: Dict[str, Any] = {
        "game_pk": safe_int(game.get("gamePk"), 0),
        "game_guid": str(game.get("gameGuid") or "").strip(),
        "link": str(game.get("link") or "").strip(),
        "game_type": str(game.get("gameType") or "").strip(),
        "season": safe_int(game.get("season"), default_season),
        "season_display": str(game.get("seasonDisplay") or "").strip(),
        "game_date": str(game.get("gameDate") or "").strip(),
        "official_date": str(game.get("officialDate") or "").strip(),
        "day_night": str(game.get("dayNight") or "").strip(),
        "game_number": safe_int_or_none(game.get("gameNumber")),
        "double_header": str(game.get("doubleHeader") or "").strip(),
        "gameday_type": str(game.get("gamedayType") or "").strip(),
        "tiebreaker": str(game.get("tiebreaker") or "").strip(),
        "calendar_event_id": str(game.get("calendarEventID") or "").strip(),
        "public_facing": bool_as_int(game.get("publicFacing"), allow_none=True),
        "is_tie": bool_as_int(game.get("isTie"), allow_none=True),
        "status_abstract": str(status.get("abstractGameState") or "").strip(),
        "status_abstract_code": str(status.get("abstractGameCode") or "").strip(),
        "status_coded": str(status.get("codedGameState") or "").strip(),
        "status_code": str(status.get("statusCode") or "").strip(),
        "status_detailed": str(status.get("detailedState") or "").strip(),
        "start_time_tbd": bool_as_int(status.get("startTimeTBD"), allow_none=True),
        "away_team_id": safe_int_or_none(away_team.get("id")),
        "away_team_name": str(away_team.get("name") or "").strip(),
        "away_team_score": safe_int_or_none(away_row.get("score")),
        "away_is_winner": bool_as_int(away_row.get("isWinner"), allow_none=True),
        "home_team_id": safe_int_or_none(home_team.get("id")),
        "home_team_name": str(home_team.get("name") or "").strip(),
        "home_team_score": safe_int_or_none(home_row.get("score")),
        "home_is_winner": bool_as_int(home_row.get("isWinner"), allow_none=True),
        "venue_id": safe_int_or_none(venue.get("id")),
        "venue_name": str(venue.get("name") or "").strip(),
        "content_link": str(content.get("link") or "").strip(),
        "last_synced_utc": sync_stamp,
        "raw_json": json.dumps(game, separators=(",", ":"), sort_keys=True),
    }

    return tuple(row_map[column] for column in GAME_COLUMNS)


def load_games_for_boxscore_processing(
    connection: sqlite3.Connection,
    seasons: Iterable[int],
    game_types: Iterable[str],
) -> List[Dict[str, Any]]:
    requested_seasons = [season for season in seasons if season > 0]
    if not requested_seasons:
        requested_seasons = [dt.date.today().year]

    normalized_game_types = [str(token).strip().upper() for token in game_types if str(token).strip()]
    if not normalized_game_types:
        normalized_game_types = ["R"]

    season_placeholders = ", ".join("?" for _ in requested_seasons)
    game_type_placeholders = ", ".join("?" for _ in normalized_game_types)

    query = f"""
        SELECT
            game_pk,
            season,
            official_date,
            game_type,
            status_abstract,
            venue_id,
            venue_name,
            home_team_id,
            home_team_name,
            away_team_id,
            away_team_name
        FROM games
        WHERE season IN ({season_placeholders})
          AND game_type IN ({game_type_placeholders})
          AND status_abstract IN ('Final', 'Live')
        ORDER BY season, official_date, game_pk
    """

    params = tuple(requested_seasons) + tuple(normalized_game_types)
    rows: List[Dict[str, Any]] = []
    for record in connection.execute(query, params):
        (
            game_pk,
            season,
            official_date,
            game_type,
            status_abstract,
            venue_id,
            venue_name,
            home_team_id,
            home_team_name,
            away_team_id,
            away_team_name,
        ) = record

        rows.append(
            {
                "game_pk": safe_int(game_pk, 0),
                "season": safe_int(season, 0),
                "official_date": str(official_date or "").strip(),
                "game_type": str(game_type or "").strip(),
                "status_abstract": str(status_abstract or "").strip(),
                "venue_id": safe_int(venue_id, 0),
                "venue_name": str(venue_name or "").strip(),
                "home_team_id": safe_int(home_team_id, 0),
                "home_team_name": str(home_team_name or "").strip(),
                "away_team_id": safe_int(away_team_id, 0),
                "away_team_name": str(away_team_name or "").strip(),
            }
        )

    return rows


def fetch_venues_metadata_map(venue_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    unique_ids = sorted({safe_int(venue_id, 0) for venue_id in venue_ids if safe_int(venue_id, 0) > 0})
    if not unique_ids:
        return {}

    metadata_map: Dict[int, Dict[str, Any]] = {}
    for batch in chunked(unique_ids, 100):
        payload = mlb_get(
            "/api/v1/venues",
            params={
                "venueIds": ",".join(str(value) for value in batch),
                "hydrate": "location,timeZone,fieldInfo",
            },
        )
        venues = payload.get("venues", []) if isinstance(payload, dict) else []
        for venue in venues:
            if not isinstance(venue, dict):
                continue
            venue_id = safe_int(venue.get("id"), 0)
            if venue_id <= 0:
                continue
            metadata_map[venue_id] = venue

    return metadata_map


def venue_payload_to_row(venue_id: int, payload: Dict[str, Any], fallback_name: str, sync_stamp: str) -> Tuple[Any, ...]:
    venue = payload if isinstance(payload, dict) else {}
    location = venue.get("location") if isinstance(venue.get("location"), dict) else {}
    coords = location.get("defaultCoordinates") if isinstance(location.get("defaultCoordinates"), dict) else {}
    time_zone = venue.get("timeZone") if isinstance(venue.get("timeZone"), dict) else {}
    field_info = venue.get("fieldInfo") if isinstance(venue.get("fieldInfo"), dict) else {}

    raw_payload = venue if venue else {"id": venue_id, "name": fallback_name}
    row_map = {
        "id": venue_id,
        "name": str(venue.get("name") or fallback_name or f"Park {venue_id}").strip(),
        "active": bool_as_int(venue.get("active"), allow_none=True),
        "season": str(venue.get("season") or "").strip(),
        "city": str(location.get("city") or "").strip(),
        "state": str(location.get("state") or location.get("stateAbbrev") or "").strip(),
        "country": str(location.get("country") or "").strip(),
        "latitude": safe_float(coords.get("latitude"), 0.0),
        "longitude": safe_float(coords.get("longitude"), 0.0),
        "time_zone_id": str(time_zone.get("id") or "").strip(),
        "time_zone_offset": safe_int_or_none(time_zone.get("offset")),
        "time_zone_tz": str(time_zone.get("tz") or "").strip(),
        "capacity": safe_int_or_none(field_info.get("capacity")),
        "turf_type": str(field_info.get("turfType") or "").strip(),
        "roof_type": str(field_info.get("roofType") or "").strip(),
        "left_line": safe_int_or_none(field_info.get("leftLine")),
        "left_field": safe_int_or_none(field_info.get("left")),
        "left_center": safe_int_or_none(field_info.get("leftCenter")),
        "center_field": safe_int_or_none(field_info.get("center")),
        "right_center": safe_int_or_none(field_info.get("rightCenter")),
        "right_field": safe_int_or_none(field_info.get("right")),
        "right_line": safe_int_or_none(field_info.get("rightLine")),
        "last_synced_utc": sync_stamp,
        "raw_json": json.dumps(raw_payload, separators=(",", ":"), sort_keys=True),
    }

    return tuple(row_map[column] for column in PARK_COLUMNS)


def update_parks_table(
    connection: sqlite3.Connection,
    venue_fallback_names: Dict[int, str],
    prune_missing: bool,
) -> Dict[str, Any]:
    sync_stamp = utc_now_iso()
    venue_ids = sorted(venue_fallback_names.keys())
    existing_ids = {row[0] for row in connection.execute("SELECT id FROM parks")}

    inserted = 0
    updated = 0
    metadata_errors: List[str] = []
    metadata_map: Dict[int, Dict[str, Any]] = {}

    if venue_ids:
        try:
            metadata_map = fetch_venues_metadata_map(venue_ids)
        except requests.RequestException as exc:
            metadata_errors.append(str(exc))

    for venue_id in venue_ids:
        fallback_name = venue_fallback_names.get(venue_id, "")
        payload = metadata_map.get(venue_id, {})
        row = venue_payload_to_row(venue_id, payload, fallback_name, sync_stamp)

        if venue_id in existing_ids:
            updated += 1
        else:
            inserted += 1
            existing_ids.add(venue_id)

        connection.execute(UPSERT_PARK_SQL, row)

    deleted = 0
    if prune_missing and venue_ids:
        placeholders = ", ".join("?" for _ in venue_ids)
        cursor = connection.execute(
            f"DELETE FROM parks WHERE id NOT IN ({placeholders})",
            tuple(venue_ids),
        )
        deleted = max(cursor.rowcount, 0)

    return {
        "sourceVenueCount": len(venue_ids),
        "metadataRows": len(metadata_map),
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "metadataErrors": metadata_errors,
        "pruneMissing": prune_missing,
        "syncedAtUtc": sync_stamp,
    }


def update_batter_park_aggregate(
    aggregate: Dict[Tuple[int, int], Dict[str, Any]],
    player_id: int,
    player_name: str,
    park_id: int,
    park_name: str,
    season: int,
    team_id: int,
    batting_stats: Dict[str, Any],
) -> None:
    key = (player_id, park_id)
    entry = aggregate.setdefault(
        key,
        {
            "player_name": player_name,
            "park_name": park_name,
            "seasons": set(),
            "team_ids": set(),
            "games_played": 0,
            "at_bats": 0,
            "plate_appearances": 0,
            "runs": 0,
            "hits": 0,
            "doubles": 0,
            "triples": 0,
            "home_runs": 0,
            "rbi": 0,
            "strike_outs": 0,
            "walks": 0,
            "hit_by_pitch": 0,
            "sac_flies": 0,
            "total_bases": 0,
            "stolen_bases": 0,
            "caught_stealing": 0,
        },
    )

    if not entry["player_name"] and player_name:
        entry["player_name"] = player_name
    if not entry["park_name"] and park_name:
        entry["park_name"] = park_name

    entry["seasons"].add(season)
    if team_id > 0:
        entry["team_ids"].add(team_id)

    at_bats = safe_int(batting_stats.get("atBats"), 0)
    walks = safe_int(batting_stats.get("baseOnBalls"), 0)
    hit_by_pitch = safe_int(batting_stats.get("hitByPitch"), 0)
    sac_flies = safe_int(batting_stats.get("sacFlies"), 0)

    plate_appearances = safe_int(batting_stats.get("plateAppearances"), 0)
    if plate_appearances <= 0:
        plate_appearances = at_bats + walks + hit_by_pitch + sac_flies

    total_bases = safe_int(batting_stats.get("totalBases"), 0)
    if total_bases <= 0:
        total_bases = (
            safe_int(batting_stats.get("hits"), 0)
            + safe_int(batting_stats.get("doubles"), 0)
            + (2 * safe_int(batting_stats.get("triples"), 0))
            + (3 * safe_int(batting_stats.get("homeRuns"), 0))
        )

    entry["games_played"] += safe_int(batting_stats.get("gamesPlayed"), 0)
    entry["at_bats"] += at_bats
    entry["plate_appearances"] += plate_appearances
    entry["runs"] += safe_int(batting_stats.get("runs"), 0)
    entry["hits"] += safe_int(batting_stats.get("hits"), 0)
    entry["doubles"] += safe_int(batting_stats.get("doubles"), 0)
    entry["triples"] += safe_int(batting_stats.get("triples"), 0)
    entry["home_runs"] += safe_int(batting_stats.get("homeRuns"), 0)
    entry["rbi"] += safe_int(batting_stats.get("rbi"), 0)
    entry["strike_outs"] += safe_int(batting_stats.get("strikeOuts"), 0)
    entry["walks"] += walks
    entry["hit_by_pitch"] += hit_by_pitch
    entry["sac_flies"] += sac_flies
    entry["total_bases"] += total_bases
    entry["stolen_bases"] += safe_int(batting_stats.get("stolenBases"), 0)
    entry["caught_stealing"] += safe_int(batting_stats.get("caughtStealing"), 0)


def update_pitcher_park_aggregate(
    aggregate: Dict[Tuple[int, int], Dict[str, Any]],
    player_id: int,
    player_name: str,
    park_id: int,
    park_name: str,
    season: int,
    team_id: int,
    pitching_stats: Dict[str, Any],
) -> None:
    key = (player_id, park_id)
    entry = aggregate.setdefault(
        key,
        {
            "player_name": player_name,
            "park_name": park_name,
            "seasons": set(),
            "team_ids": set(),
            "games_played": 0,
            "games_started": 0,
            "outs_recorded": 0,
            "hits": 0,
            "runs": 0,
            "earned_runs": 0,
            "home_runs": 0,
            "strike_outs": 0,
            "walks": 0,
            "hit_batters": 0,
            "batters_faced": 0,
            "pitches_thrown": 0,
        },
    )

    if not entry["player_name"] and player_name:
        entry["player_name"] = player_name
    if not entry["park_name"] and park_name:
        entry["park_name"] = park_name

    entry["seasons"].add(season)
    if team_id > 0:
        entry["team_ids"].add(team_id)

    outs_recorded = safe_int(pitching_stats.get("outs"), 0)
    if outs_recorded <= 0:
        outs_recorded = innings_to_outs(pitching_stats.get("inningsPitched"))

    entry["games_played"] += safe_int(pitching_stats.get("gamesPlayed"), 0)
    entry["games_started"] += safe_int(pitching_stats.get("gamesStarted"), 0)
    entry["outs_recorded"] += outs_recorded
    entry["hits"] += safe_int(pitching_stats.get("hits"), 0)
    entry["runs"] += safe_int(pitching_stats.get("runs"), 0)
    entry["earned_runs"] += safe_int(pitching_stats.get("earnedRuns"), 0)
    entry["home_runs"] += safe_int(pitching_stats.get("homeRuns"), 0)
    entry["strike_outs"] += safe_int(pitching_stats.get("strikeOuts"), 0)
    entry["walks"] += safe_int(pitching_stats.get("baseOnBalls"), 0)
    entry["hit_batters"] += safe_int(pitching_stats.get("hitByPitch"), 0)
    entry["batters_faced"] += safe_int(pitching_stats.get("battersFaced"), 0)
    entry["pitches_thrown"] += safe_int(
        pitching_stats.get("numberOfPitches"),
        safe_int(pitching_stats.get("pitchesThrown"), 0),
    )


def update_boxscore_derived_tables(
    connection: sqlite3.Connection,
    seasons: Iterable[int],
    game_types: Iterable[str],
    include_tables: Set[str],
    park_prune_missing: bool,
    by_park_prune_missing: bool,
    umpire_prune_missing: bool,
    batting_order_prune_missing: bool,
) -> Dict[str, Dict[str, Any]]:
    requested_seasons = [season for season in seasons if season > 0]
    if not requested_seasons:
        requested_seasons = [dt.date.today().year]

    game_rows = load_games_for_boxscore_processing(connection, requested_seasons, game_types)
    venue_fallback_names = {
        row["venue_id"]: row["venue_name"]
        for row in game_rows
        if safe_int(row.get("venue_id"), 0) > 0 and str(row.get("venue_name") or "").strip()
    }

    results: Dict[str, Dict[str, Any]] = {}

    if "parks" in include_tables:
        results["parks"] = update_parks_table(
            connection=connection,
            venue_fallback_names=venue_fallback_names,
            prune_missing=park_prune_missing,
        )

    needs_boxscore_scan = bool(
        {"batter_stats_by_park", "pitcher_stats_by_park", "umpires", "batting_orders"}.intersection(include_tables)
    )
    if not needs_boxscore_scan:
        return results

    sync_stamp = utc_now_iso()
    window_start_season = min(requested_seasons)
    window_end_season = max(requested_seasons)

    existing_umpire_keys: Set[Tuple[Any, ...]] = set()
    existing_batting_order_keys: Set[Tuple[Any, ...]] = set()
    existing_batter_by_park_keys: Set[Tuple[Any, ...]] = set()
    existing_pitcher_by_park_keys: Set[Tuple[Any, ...]] = set()

    if "umpires" in include_tables:
        placeholders = ", ".join("?" for _ in requested_seasons)
        existing_umpire_keys = {
            tuple(row)
            for row in connection.execute(
                f"SELECT game_pk, official_type, umpire_id FROM umpires WHERE season IN ({placeholders})",
                tuple(requested_seasons),
            )
        }

    if "batting_orders" in include_tables:
        placeholders = ", ".join("?" for _ in requested_seasons)
        existing_batting_order_keys = {
            tuple(row)
            for row in connection.execute(
                f"SELECT game_pk, team_id, batting_order_code, player_id FROM batting_orders WHERE season IN ({placeholders})",
                tuple(requested_seasons),
            )
        }

    if "batter_stats_by_park" in include_tables:
        existing_batter_by_park_keys = {
            tuple(row)
            for row in connection.execute(
                """
                SELECT player_id, park_id, window_start_season, window_end_season
                FROM batter_stats_by_park
                WHERE window_start_season = ? AND window_end_season = ?
                """,
                (window_start_season, window_end_season),
            )
        }

    if "pitcher_stats_by_park" in include_tables:
        existing_pitcher_by_park_keys = {
            tuple(row)
            for row in connection.execute(
                """
                SELECT player_id, park_id, window_start_season, window_end_season
                FROM pitcher_stats_by_park
                WHERE window_start_season = ? AND window_end_season = ?
                """,
                (window_start_season, window_end_season),
            )
        }

    batter_aggregate: Dict[Tuple[int, int], Dict[str, Any]] = {}
    pitcher_aggregate: Dict[Tuple[int, int], Dict[str, Any]] = {}

    boxscores_fetched = 0
    boxscore_errors = 0
    umpires_inserted = 0
    umpires_updated = 0
    umpires_skipped = 0
    batting_inserted = 0
    batting_updated = 0
    batting_skipped = 0

    for game_row in game_rows:
        game_pk = safe_int(game_row.get("game_pk"), 0)
        if game_pk <= 0:
            continue

        try:
            boxscore = mlb_get(f"/api/v1/game/{game_pk}/boxscore")
            boxscores_fetched += 1
        except requests.RequestException:
            boxscore_errors += 1
            continue

        if "umpires" in include_tables:
            officials = boxscore.get("officials", []) if isinstance(boxscore, dict) else []
            for official_row in officials:
                if not isinstance(official_row, dict):
                    umpires_skipped += 1
                    continue

                official = official_row.get("official") if isinstance(official_row.get("official"), dict) else {}
                umpire_id = safe_int(official.get("id"), 0)
                official_type = str(official_row.get("officialType") or "").strip()
                if umpire_id <= 0 or not official_type:
                    umpires_skipped += 1
                    continue

                key = (game_pk, official_type, umpire_id)
                if key in existing_umpire_keys:
                    umpires_updated += 1
                else:
                    umpires_inserted += 1
                    existing_umpire_keys.add(key)

                row_map = {
                    "game_pk": game_pk,
                    "season": safe_int(game_row.get("season"), 0),
                    "official_date": str(game_row.get("official_date") or "").strip(),
                    "official_type": official_type,
                    "umpire_id": umpire_id,
                    "umpire_name": str(official.get("fullName") or "").strip(),
                    "umpire_link": str(official.get("link") or "").strip(),
                    "home_team_id": safe_int(game_row.get("home_team_id"), 0),
                    "away_team_id": safe_int(game_row.get("away_team_id"), 0),
                    "park_id": safe_int(game_row.get("venue_id"), 0),
                    "last_synced_utc": sync_stamp,
                    "raw_json": json.dumps(official_row, separators=(",", ":"), sort_keys=True),
                }
                connection.execute(UPSERT_UMPIRE_SQL, tuple(row_map[column] for column in UMPIRE_COLUMNS))

        teams_block = boxscore.get("teams", {}) if isinstance(boxscore, dict) else {}
        for side in ["away", "home"]:
            side_block = teams_block.get(side, {}) if isinstance(teams_block.get(side), dict) else {}
            team_blob = side_block.get("team", {}) if isinstance(side_block.get("team"), dict) else {}

            fallback_team_id = safe_int(game_row.get(f"{side}_team_id"), 0)
            fallback_team_name = str(game_row.get(f"{side}_team_name") or "").strip()

            team_id = safe_int(team_blob.get("id"), fallback_team_id)
            team_name = str(team_blob.get("name") or fallback_team_name).strip()

            players = side_block.get("players", {}) if isinstance(side_block.get("players"), dict) else {}
            for player_row in players.values():
                if not isinstance(player_row, dict):
                    continue

                person = player_row.get("person") if isinstance(player_row.get("person"), dict) else {}
                player_id = safe_int(person.get("id"), 0)
                if player_id <= 0:
                    continue

                player_name = str(person.get("fullName") or "").strip()
                stats_blob = player_row.get("stats") if isinstance(player_row.get("stats"), dict) else {}
                batting_stats = stats_blob.get("batting") if isinstance(stats_blob.get("batting"), dict) else {}
                pitching_stats = stats_blob.get("pitching") if isinstance(stats_blob.get("pitching"), dict) else {}

                if "batting_orders" in include_tables:
                    batting_order_code = safe_int_or_none(player_row.get("battingOrder"))
                    if batting_order_code is None or batting_order_code <= 0:
                        batting_skipped += 1
                    else:
                        key = (game_pk, team_id, batting_order_code, player_id)
                        if key in existing_batting_order_keys:
                            batting_updated += 1
                        else:
                            batting_inserted += 1
                            existing_batting_order_keys.add(key)

                        position = player_row.get("position") if isinstance(player_row.get("position"), dict) else {}
                        row_map = {
                            "game_pk": game_pk,
                            "season": safe_int(game_row.get("season"), 0),
                            "official_date": str(game_row.get("official_date") or "").strip(),
                            "team_id": team_id,
                            "team_name": team_name,
                            "park_id": safe_int(game_row.get("venue_id"), 0),
                            "batting_order_code": batting_order_code,
                            "lineup_slot": batting_order_code // 100,
                            "player_id": player_id,
                            "player_name": player_name,
                            "position_abbreviation": str(position.get("abbreviation") or "").strip(),
                            "position_name": str(position.get("name") or "").strip(),
                            "batting_summary": str((batting_stats.get("summary") if batting_stats else "") or "").strip(),
                            "is_substitute": 1 if (batting_order_code % 100) != 0 else 0,
                            "last_synced_utc": sync_stamp,
                            "raw_json": json.dumps(player_row, separators=(",", ":"), sort_keys=True),
                        }
                        connection.execute(
                            UPSERT_BATTING_ORDER_SQL,
                            tuple(row_map[column] for column in BATTING_ORDER_COLUMNS),
                        )

                if "batter_stats_by_park" in include_tables and batting_stats:
                    update_batter_park_aggregate(
                        aggregate=batter_aggregate,
                        player_id=player_id,
                        player_name=player_name,
                        park_id=safe_int(game_row.get("venue_id"), 0),
                        park_name=str(game_row.get("venue_name") or "").strip(),
                        season=safe_int(game_row.get("season"), 0),
                        team_id=team_id,
                        batting_stats=batting_stats,
                    )

                if "pitcher_stats_by_park" in include_tables and pitching_stats:
                    update_pitcher_park_aggregate(
                        aggregate=pitcher_aggregate,
                        player_id=player_id,
                        player_name=player_name,
                        park_id=safe_int(game_row.get("venue_id"), 0),
                        park_name=str(game_row.get("venue_name") or "").strip(),
                        season=safe_int(game_row.get("season"), 0),
                        team_id=team_id,
                        pitching_stats=pitching_stats,
                    )

    if "umpires" in include_tables:
        deleted = 0
        if umpire_prune_missing:
            placeholders = ", ".join("?" for _ in requested_seasons)
            cursor = connection.execute(
                f"DELETE FROM umpires WHERE season IN ({placeholders}) AND last_synced_utc <> ?",
                tuple(requested_seasons) + (sync_stamp,),
            )
            deleted = max(cursor.rowcount, 0)

        results["umpires"] = {
            "seasons": requested_seasons,
            "gameRowsScanned": len(game_rows),
            "boxscoresFetched": boxscores_fetched,
            "boxscoreErrors": boxscore_errors,
            "inserted": umpires_inserted,
            "updated": umpires_updated,
            "deleted": deleted,
            "skipped": umpires_skipped,
            "pruneMissing": umpire_prune_missing,
            "syncedAtUtc": sync_stamp,
        }

    if "batting_orders" in include_tables:
        deleted = 0
        if batting_order_prune_missing:
            placeholders = ", ".join("?" for _ in requested_seasons)
            cursor = connection.execute(
                f"DELETE FROM batting_orders WHERE season IN ({placeholders}) AND last_synced_utc <> ?",
                tuple(requested_seasons) + (sync_stamp,),
            )
            deleted = max(cursor.rowcount, 0)

        results["batting_orders"] = {
            "seasons": requested_seasons,
            "gameRowsScanned": len(game_rows),
            "boxscoresFetched": boxscores_fetched,
            "boxscoreErrors": boxscore_errors,
            "inserted": batting_inserted,
            "updated": batting_updated,
            "deleted": deleted,
            "skipped": batting_skipped,
            "pruneMissing": batting_order_prune_missing,
            "syncedAtUtc": sync_stamp,
        }

    if "batter_stats_by_park" in include_tables:
        inserted = 0
        updated = 0
        skipped = 0
        for (player_id, park_id), totals in batter_aggregate.items():
            if player_id <= 0 or park_id <= 0:
                skipped += 1
                continue

            at_bats = totals["at_bats"]
            hits = totals["hits"]
            walks = totals["walks"]
            hit_by_pitch = totals["hit_by_pitch"]
            sac_flies = totals["sac_flies"]
            plate_appearances = totals["plate_appearances"]
            if plate_appearances <= 0:
                plate_appearances = at_bats + walks + hit_by_pitch + sac_flies

            total_bases = totals["total_bases"]
            if total_bases <= 0:
                total_bases = hits + totals["doubles"] + (2 * totals["triples"]) + (3 * totals["home_runs"])

            avg = (hits / at_bats) if at_bats > 0 else 0.0
            obp_denominator = at_bats + walks + hit_by_pitch + sac_flies
            obp = ((hits + walks + hit_by_pitch) / obp_denominator) if obp_denominator > 0 else 0.0
            slg = (total_bases / at_bats) if at_bats > 0 else 0.0
            ops = obp + slg

            row_map = {
                "player_id": player_id,
                "player_name": totals["player_name"],
                "park_id": park_id,
                "park_name": totals["park_name"],
                "window_start_season": window_start_season,
                "window_end_season": window_end_season,
                "games_played": totals["games_played"],
                "at_bats": at_bats,
                "plate_appearances": plate_appearances,
                "runs": totals["runs"],
                "hits": hits,
                "doubles": totals["doubles"],
                "triples": totals["triples"],
                "home_runs": totals["home_runs"],
                "rbi": totals["rbi"],
                "strike_outs": totals["strike_outs"],
                "walks": walks,
                "hit_by_pitch": hit_by_pitch,
                "sac_flies": sac_flies,
                "total_bases": total_bases,
                "stolen_bases": totals["stolen_bases"],
                "caught_stealing": totals["caught_stealing"],
                "avg": round_or_none(avg, 4),
                "obp": round_or_none(obp, 4),
                "slg": round_or_none(slg, 4),
                "ops": round_or_none(ops, 4),
                "seasons_covered_json": json.dumps(sorted(totals["seasons"]), separators=(",", ":")),
                "team_ids_json": json.dumps(sorted(totals["team_ids"]), separators=(",", ":")),
                "last_synced_utc": sync_stamp,
                "totals_json": json.dumps(
                    {
                        key: value
                        for key, value in totals.items()
                        if key not in {"player_name", "park_name", "seasons", "team_ids"}
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }

            row = tuple(row_map[column] for column in BATTER_BY_PARK_COLUMNS)
            key = (player_id, park_id, window_start_season, window_end_season)
            if key in existing_batter_by_park_keys:
                updated += 1
            else:
                inserted += 1
                existing_batter_by_park_keys.add(key)

            connection.execute(UPSERT_BATTER_BY_PARK_SQL, row)

        deleted = 0
        if by_park_prune_missing:
            cursor = connection.execute(
                """
                DELETE FROM batter_stats_by_park
                WHERE window_start_season = ?
                  AND window_end_season = ?
                  AND last_synced_utc <> ?
                """,
                (window_start_season, window_end_season, sync_stamp),
            )
            deleted = max(cursor.rowcount, 0)

        results["batter_stats_by_park"] = {
            "seasons": requested_seasons,
            "windowStartSeason": window_start_season,
            "windowEndSeason": window_end_season,
            "gameRowsScanned": len(game_rows),
            "boxscoresFetched": boxscores_fetched,
            "boxscoreErrors": boxscore_errors,
            "aggregatedRows": len(batter_aggregate),
            "inserted": inserted,
            "updated": updated,
            "deleted": deleted,
            "skipped": skipped,
            "pruneMissing": by_park_prune_missing,
            "syncedAtUtc": sync_stamp,
        }

    if "pitcher_stats_by_park" in include_tables:
        inserted = 0
        updated = 0
        skipped = 0
        for (player_id, park_id), totals in pitcher_aggregate.items():
            if player_id <= 0 or park_id <= 0:
                skipped += 1
                continue

            outs_recorded = totals["outs_recorded"]
            innings_for_rates = outs_recorded / 3.0 if outs_recorded > 0 else 0.0
            innings_pitched = outs_to_innings_decimal(outs_recorded)

            era = (totals["earned_runs"] * 9.0 / innings_for_rates) if innings_for_rates > 0 else 0.0
            whip = ((totals["walks"] + totals["hits"]) / innings_for_rates) if innings_for_rates > 0 else 0.0
            strikeouts_per9 = (totals["strike_outs"] * 9.0 / innings_for_rates) if innings_for_rates > 0 else 0.0
            walks_per9 = (totals["walks"] * 9.0 / innings_for_rates) if innings_for_rates > 0 else 0.0

            row_map = {
                "player_id": player_id,
                "player_name": totals["player_name"],
                "park_id": park_id,
                "park_name": totals["park_name"],
                "window_start_season": window_start_season,
                "window_end_season": window_end_season,
                "games_played": totals["games_played"],
                "games_started": totals["games_started"],
                "outs_recorded": outs_recorded,
                "innings_pitched": round_or_none(innings_pitched, 1),
                "hits": totals["hits"],
                "runs": totals["runs"],
                "earned_runs": totals["earned_runs"],
                "home_runs": totals["home_runs"],
                "strike_outs": totals["strike_outs"],
                "walks": totals["walks"],
                "hit_batters": totals["hit_batters"],
                "batters_faced": totals["batters_faced"],
                "pitches_thrown": totals["pitches_thrown"],
                "era": round_or_none(era, 4),
                "whip": round_or_none(whip, 4),
                "strikeouts_per9": round_or_none(strikeouts_per9, 4),
                "walks_per9": round_or_none(walks_per9, 4),
                "seasons_covered_json": json.dumps(sorted(totals["seasons"]), separators=(",", ":")),
                "team_ids_json": json.dumps(sorted(totals["team_ids"]), separators=(",", ":")),
                "last_synced_utc": sync_stamp,
                "totals_json": json.dumps(
                    {
                        key: value
                        for key, value in totals.items()
                        if key not in {"player_name", "park_name", "seasons", "team_ids"}
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }

            row = tuple(row_map[column] for column in PITCHER_BY_PARK_COLUMNS)
            key = (player_id, park_id, window_start_season, window_end_season)
            if key in existing_pitcher_by_park_keys:
                updated += 1
            else:
                inserted += 1
                existing_pitcher_by_park_keys.add(key)

            connection.execute(UPSERT_PITCHER_BY_PARK_SQL, row)

        deleted = 0
        if by_park_prune_missing:
            cursor = connection.execute(
                """
                DELETE FROM pitcher_stats_by_park
                WHERE window_start_season = ?
                  AND window_end_season = ?
                  AND last_synced_utc <> ?
                """,
                (window_start_season, window_end_season, sync_stamp),
            )
            deleted = max(cursor.rowcount, 0)

        results["pitcher_stats_by_park"] = {
            "seasons": requested_seasons,
            "windowStartSeason": window_start_season,
            "windowEndSeason": window_end_season,
            "gameRowsScanned": len(game_rows),
            "boxscoresFetched": boxscores_fetched,
            "boxscoreErrors": boxscore_errors,
            "aggregatedRows": len(pitcher_aggregate),
            "inserted": inserted,
            "updated": updated,
            "deleted": deleted,
            "skipped": skipped,
            "pruneMissing": by_park_prune_missing,
            "syncedAtUtc": sync_stamp,
        }

    return results


def load_player_name_to_id_map(connection: sqlite3.Connection) -> Dict[str, int]:
    candidate_to_ids: Dict[str, Set[int]] = {}
    rows = connection.execute(
        """
        SELECT
            id,
            full_name,
            first_name,
            last_name,
            use_name,
            use_last_name,
            boxscore_name
        FROM players
        """
    )

    for row in rows:
        (
            player_id,
            full_name,
            first_name,
            last_name,
            use_name,
            use_last_name,
            boxscore_name,
        ) = row

        player_id = safe_int(player_id, 0)
        if player_id <= 0:
            continue

        candidates = [
            str(full_name or "").strip(),
            str(boxscore_name or "").strip(),
        ]

        first_name = str(first_name or "").strip()
        last_name = str(last_name or "").strip()
        if first_name and last_name:
            candidates.append(f"{first_name} {last_name}".strip())

        use_name = str(use_name or "").strip()
        use_last_name = str(use_last_name or "").strip()
        if use_name and use_last_name:
            candidates.append(f"{use_name} {use_last_name}".strip())

        for candidate in candidates:
            normalized = normalize_person_name(candidate)
            if not normalized:
                continue
            candidate_to_ids.setdefault(normalized, set()).add(player_id)

    resolved: Dict[str, int] = {}
    for candidate, ids in candidate_to_ids.items():
        if len(ids) == 1:
            resolved[candidate] = next(iter(ids))

    return resolved


def load_player_name_team_to_id_map(connection: sqlite3.Connection) -> Dict[Tuple[str, int], int]:
    candidate_to_ids: Dict[Tuple[str, int], Set[int]] = {}
    rows = connection.execute(
        """
        SELECT
            id,
            full_name,
            first_name,
            last_name,
            use_name,
            use_last_name,
            boxscore_name,
            current_team_id
        FROM players
        """
    )

    for row in rows:
        (
            player_id,
            full_name,
            first_name,
            last_name,
            use_name,
            use_last_name,
            boxscore_name,
            current_team_id,
        ) = row

        player_id = safe_int(player_id, 0)
        team_id = safe_int(current_team_id, 0)
        if player_id <= 0 or team_id <= 0:
            continue

        candidates = [
            str(full_name or "").strip(),
            str(boxscore_name or "").strip(),
        ]

        first_name = str(first_name or "").strip()
        last_name = str(last_name or "").strip()
        if first_name and last_name:
            candidates.append(f"{first_name} {last_name}".strip())

        use_name = str(use_name or "").strip()
        use_last_name = str(use_last_name or "").strip()
        if use_name and use_last_name:
            candidates.append(f"{use_name} {use_last_name}".strip())

        for candidate in candidates:
            normalized = normalize_person_name(candidate)
            if not normalized:
                continue
            candidate_to_ids.setdefault((normalized, team_id), set()).add(player_id)

    resolved: Dict[Tuple[str, int], int] = {}
    for candidate, ids in candidate_to_ids.items():
        if len(ids) == 1:
            resolved[candidate] = next(iter(ids))

    return resolved


def load_team_name_to_id_map(connection: sqlite3.Connection) -> Dict[str, int]:
    candidate_to_ids: Dict[str, Set[int]] = {}
    rows = connection.execute(
        """
        SELECT
            id,
            name,
            abbreviation,
            franchise_name,
            short_name,
            location_name,
            team_name
        FROM teams
        """
    )

    for row in rows:
        team_id = safe_int(row[0], 0)
        if team_id <= 0:
            continue

        for raw_value in row[1:]:
            normalized = normalize_person_name(raw_value)
            if not normalized:
                continue
            candidate_to_ids.setdefault(normalized, set()).add(team_id)

    resolved: Dict[str, int] = {}
    for candidate, ids in candidate_to_ids.items():
        if len(ids) == 1:
            resolved[candidate] = next(iter(ids))

    return resolved


def lookup_game_pk_for_odds_event(
    connection: sqlite3.Connection,
    home_team_id: int,
    away_team_id: int,
    commence_time: str,
) -> int:
    if home_team_id <= 0 or away_team_id <= 0:
        return 0

    commence_dt = parse_iso_datetime(commence_time)
    if not commence_dt:
        return 0

    candidates = list(
        connection.execute(
            """
            SELECT game_pk, game_date
            FROM games
            WHERE home_team_id = ?
              AND away_team_id = ?
            ORDER BY official_date DESC
            LIMIT 8
            """,
            (home_team_id, away_team_id),
        )
    )
    if not candidates:
        return 0

    best_game_pk = 0
    best_delta = None
    for game_pk, game_date in candidates:
        game_dt = parse_iso_datetime(game_date)
        if not game_dt:
            continue

        compare_commence = commence_dt
        compare_game = game_dt
        if compare_commence.tzinfo is None and compare_game.tzinfo is not None:
            compare_commence = compare_commence.replace(tzinfo=dt.UTC)
        elif compare_commence.tzinfo is not None and compare_game.tzinfo is None:
            compare_game = compare_game.replace(tzinfo=dt.UTC)

        delta_seconds = abs((compare_commence - compare_game).total_seconds())
        if best_delta is None or delta_seconds < best_delta:
            best_delta = delta_seconds
            best_game_pk = safe_int(game_pk, 0)

    if best_delta is None:
        return 0
    if best_delta > 60 * 60 * 36:
        return 0
    return best_game_pk


def odds_line_and_key(raw_point: Any) -> Tuple[Any, str]:
    if raw_point is None:
        return None, ""
    text = str(raw_point).strip()
    if not text:
        return None, ""

    point = safe_float(raw_point, float("nan"))
    if not math.isfinite(point):
        return None, ""

    point_text = f"{point:.4f}".rstrip("0").rstrip(".")
    return point, point_text


def update_game_betting_odds_table(
    connection: sqlite3.Connection,
    markets: str,
    bovada_base_url: str,
    prune_missing: bool,
) -> Dict[str, Any]:
    requested_market_tokens = parse_csv_tokens(markets)
    market_tokens = list(dict.fromkeys(normalize_game_market_token(token) for token in requested_market_tokens))
    market_tokens = [token for token in market_tokens if token]
    if not market_tokens:
        return {
            "available": False,
            "reason": "No game odds markets were configured.",
        }

    sync_stamp = utc_now_iso()
    existing_keys = {
        tuple(row)
        for row in connection.execute(
            """
            SELECT
                event_id,
                bookmaker_key,
                market_key,
                selection_name,
                selection_description,
                line_key
            FROM game_betting_odds
            """
        )
    }

    team_map = load_team_name_to_id_map(connection)
    try:
        events = bovada_get_mlb_events(bovada_base_url)
    except requests.RequestException as exc:
        return {
            "available": False,
            "reason": str(exc),
            "source": "Bovada",
        }
    except ValueError as exc:
        return {
            "available": False,
            "reason": str(exc),
            "source": "Bovada",
        }

    inserted = 0
    updated = 0
    skipped = 0

    for event in events:
        event_id = str(event.get("id") or "").strip()
        competitors = event.get("competitors") if isinstance(event.get("competitors"), list) else []

        home_team = ""
        away_team = ""
        home_short_name = ""
        away_short_name = ""
        for competitor in competitors:
            if not isinstance(competitor, dict):
                continue
            is_home = bool(competitor.get("home"))
            name = str(competitor.get("name") or "").strip()
            short_name = str(competitor.get("shortName") or "").strip()
            if is_home:
                home_team = name
                home_short_name = short_name
            else:
                away_team = name
                away_short_name = short_name

        commence_time = timestamp_millis_to_iso(event.get("startTime"))
        event_last_modified = timestamp_millis_to_iso(event.get("lastModified"))

        if not event_id:
            skipped += 1
            continue

        home_team_id = resolve_team_id(team_map, home_team, home_short_name)
        away_team_id = resolve_team_id(team_map, away_team, away_short_name)
        game_pk = lookup_game_pk_for_odds_event(connection, home_team_id, away_team_id, commence_time)

        for display_group in event.get("displayGroups", []):
            if not isinstance(display_group, dict):
                continue

            for market in display_group.get("markets", []):
                if not isinstance(market, dict):
                    continue

                market_description = parse_market_token(market.get("description"))
                market_key = BOVADA_MARKET_DESCRIPTION_TO_KEY.get(market_description, "")
                if not market_key or market_key not in market_tokens:
                    continue

                market_last_update = (
                    timestamp_millis_to_iso(market.get("lastModified"))
                    or event_last_modified
                    or sync_stamp
                )
                market_rows: List[Dict[str, Any]] = []
                for outcome in market.get("outcomes", []):
                    if not isinstance(outcome, dict):
                        continue

                    selection_name = str(outcome.get("name") or "").strip()
                    if not selection_name:
                        selection_name = str(outcome.get("description") or "").strip()

                    outcome_type = str(outcome.get("type") or "").strip().upper()
                    if market_key == "totals":
                        selection_description = "Over/Under"
                    elif outcome_type == "H":
                        selection_description = "Home"
                    elif outcome_type == "A":
                        selection_description = "Away"
                    else:
                        selection_description = ""

                    if not selection_name and not selection_description:
                        skipped += 1
                        continue

                    price = outcome.get("price") if isinstance(outcome.get("price"), dict) else {}
                    line, line_key = odds_line_and_key(price.get("handicap"))
                    odds_price = parse_american_odds(price.get("american"))

                    row_map = {
                        "event_id": event_id,
                        "game_pk": game_pk if game_pk > 0 else None,
                        "sport_key": "baseball_mlb",
                        "sport_title": "MLB",
                        "commence_time": commence_time,
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_team_id": home_team_id if home_team_id > 0 else None,
                        "away_team_id": away_team_id if away_team_id > 0 else None,
                        "bookmaker_key": "bovada",
                        "bookmaker_title": "Bovada",
                        "market_key": market_key,
                        "market_last_update": market_last_update,
                        "selection_name": selection_name,
                        "selection_description": selection_description,
                        "line": line,
                        "line_key": line_key,
                        "odds_price": odds_price,
                        "implied_probability": None,
                        "implied_probability_percent": None,
                        "last_synced_utc": sync_stamp,
                        "raw_json": json.dumps(
                            {
                                "eventId": event_id,
                                "bookmaker": "bovada",
                                "market": market_key,
                                "displayGroup": display_group,
                                "outcome": outcome,
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    }

                    market_rows.append(row_map)

                apply_no_vig_to_game_odds_rows(market_rows)

                for row_map in market_rows:

                    key = (
                        row_map["event_id"],
                        row_map["bookmaker_key"],
                        row_map["market_key"],
                        row_map["selection_name"],
                        row_map["selection_description"],
                        row_map["line_key"],
                    )
                    if key in existing_keys:
                        updated += 1
                    else:
                        inserted += 1
                        existing_keys.add(key)

                    connection.execute(
                        UPSERT_GAME_BETTING_ODDS_SQL,
                        tuple(row_map[column] for column in GAME_BETTING_ODDS_COLUMNS),
                    )

    deleted = 0
    if prune_missing:
        today_iso = dt.date.today().isoformat()
        cursor = connection.execute(
            """
            DELETE FROM game_betting_odds
            WHERE last_synced_utc <> ?
                AND (
                    commence_time IS NULL
                    OR SUBSTR(commence_time, 1, 10) >= ?
                )
            """,
            (sync_stamp, today_iso),
        )
        deleted = max(cursor.rowcount, 0)

    return {
        "available": True,
        "source": "Bovada",
        "markets": market_tokens,
        "eventsFetched": len(events),
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "pruneMissing": prune_missing,
        "syncedAtUtc": sync_stamp,
    }


def update_player_betting_odds_table(
    connection: sqlite3.Connection,
    api_key: str,
    base_url: str,
    location: str,
    book_id: str,
    markets: str,
    days_ahead: int,
    prune_missing: bool,
) -> Dict[str, Any]:
    requested_market_tokens = parse_csv_tokens(markets)
    market_tokens = list(dict.fromkeys(normalize_player_market_token(token) for token in requested_market_tokens))
    market_tokens = [token for token in market_tokens if token]
    if not market_tokens:
        return {
            "available": False,
            "reason": "No player odds markets were configured.",
        }

    sync_stamp = utc_now_iso()
    existing_keys = {
        tuple(row)
        for row in connection.execute(
            """
            SELECT
                event_id,
                bookmaker_key,
                market_key,
                player_name_normalized,
                selection_name,
                line_key
            FROM player_betting_odds
            """
        )
    }

    player_map = load_player_name_to_id_map(connection)
    player_team_map = load_player_name_team_to_id_map(connection)
    team_map = load_team_name_to_id_map(connection)
    try:
        event_map, event_dates = bettingpros_collect_event_map(
            base_url=base_url,
            api_key=api_key,
            days_ahead=days_ahead,
        )
        props, props_dates = bettingpros_collect_props(
            base_url=base_url,
            api_key=api_key,
            days_ahead=days_ahead,
            location=location,
            book_id=book_id,
        )
    except requests.RequestException as exc:
        return {
            "available": False,
            "reason": str(exc),
            "source": "BettingPros",
        }
    except ValueError as exc:
        return {
            "available": False,
            "reason": str(exc),
            "source": "BettingPros",
        }

    inserted = 0
    updated = 0
    skipped = 0

    for prop in props:
        event_id = str(prop.get("event_id") or "").strip()
        event_info = event_map.get(event_id, {})

        if not event_id:
            skipped += 1
            continue

        home_team = str(event_info.get("home_team") or "").strip()
        away_team = str(event_info.get("away_team") or "").strip()
        home_abbreviation = str(event_info.get("home_abbreviation") or "").strip()
        away_abbreviation = str(event_info.get("away_abbreviation") or "").strip()
        commence_time = str(event_info.get("commence_time") or "").strip()

        links = prop.get("links") if isinstance(prop.get("links"), dict) else {}
        odds_link = str(links.get("odds") or "").strip()
        odds_link_tokens = odds_link.strip("/").split("/")
        market_slug = odds_link_tokens[-1] if odds_link_tokens else ""
        market_key_canonical = normalize_bettingpros_market_slug(market_slug)
        if market_key_canonical not in market_tokens:
            continue

        market_key = player_market_storage_key(market_key_canonical)

        participant = prop.get("participant") if isinstance(prop.get("participant"), dict) else {}
        player_name = str(participant.get("name") or "").strip()
        player_name_normalized = normalize_person_name(player_name)
        if not player_name_normalized:
            skipped += 1
            continue

        participant_player = participant.get("player") if isinstance(participant.get("player"), dict) else {}
        participant_team_abbreviation = str(participant_player.get("team") or "").strip()
        participant_team_id = resolve_team_id(team_map, participant_team_abbreviation)

        home_team_id = resolve_team_id(team_map, home_team, home_abbreviation)
        away_team_id = resolve_team_id(team_map, away_team, away_abbreviation)
        game_pk = lookup_game_pk_for_odds_event(connection, home_team_id, away_team_id, commence_time)
        player_id = player_map.get(player_name_normalized)
        if not player_id and participant_team_id > 0:
            player_id = player_team_map.get((player_name_normalized, participant_team_id))

        prop_rows: List[Dict[str, Any]] = []
        for side_name in ("over", "under"):
            side = prop.get(side_name)
            if not isinstance(side, dict):
                continue

            line_raw = side.get("line")
            if line_raw is None:
                line_raw = side.get("consensus_line")

            line, line_key = odds_line_and_key(line_raw)
            odds_price = parse_american_odds(side.get("odds"))
            if odds_price is None:
                odds_price = parse_american_odds(side.get("consensus_odds"))

            bookmaker_raw = str(side.get("book") or "").strip()
            if bookmaker_raw in {"", "0"}:
                bookmaker_key = "consensus"
                bookmaker_title = "Consensus"
            else:
                bookmaker_key = f"book_{bookmaker_raw}"
                bookmaker_title = f"Book {bookmaker_raw}"

            row_map = {
                "event_id": event_id,
                "game_pk": game_pk if game_pk > 0 else None,
                "sport_key": str(event_info.get("sport_key") or "baseball_mlb"),
                "sport_title": str(event_info.get("sport_title") or "MLB"),
                "commence_time": commence_time,
                "home_team": home_team,
                "away_team": away_team,
                "home_team_id": home_team_id if home_team_id > 0 else None,
                "away_team_id": away_team_id if away_team_id > 0 else None,
                "player_id": player_id,
                "player_name": player_name,
                "player_name_normalized": player_name_normalized,
                "bookmaker_key": bookmaker_key,
                "bookmaker_title": bookmaker_title,
                "market_key": market_key,
                "market_last_update": sync_stamp,
                "selection_name": side_name.title(),
                "line": line,
                "line_key": line_key,
                "odds_price": odds_price,
                "implied_probability": None,
                "implied_probability_percent": None,
                "last_synced_utc": sync_stamp,
                "raw_json": json.dumps(
                    {
                        "eventId": event_id,
                        "bookmaker": bookmaker_key,
                        "market": market_key,
                        "prop": prop,
                        "event": event_info.get("raw_event", {}),
                        "side": side_name,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }

            prop_rows.append(row_map)

        apply_no_vig_to_player_odds_rows(prop_rows)

        for row_map in prop_rows:

            key = (
                row_map["event_id"],
                row_map["bookmaker_key"],
                row_map["market_key"],
                row_map["player_name_normalized"],
                row_map["selection_name"],
                row_map["line_key"],
            )
            if key in existing_keys:
                updated += 1
            else:
                inserted += 1
                existing_keys.add(key)

            connection.execute(
                UPSERT_PLAYER_BETTING_ODDS_SQL,
                tuple(row_map[column] for column in PLAYER_BETTING_ODDS_COLUMNS),
            )

    deleted = 0
    if prune_missing:
        today_iso = dt.date.today().isoformat()
        cursor = connection.execute(
            """
            DELETE FROM player_betting_odds
            WHERE last_synced_utc <> ?
                AND (
                    commence_time IS NULL
                    OR SUBSTR(commence_time, 1, 10) >= ?
                )
            """,
            (sync_stamp, today_iso),
        )
        deleted = max(cursor.rowcount, 0)

    return {
        "available": True,
        "source": "BettingPros",
        "markets": [player_market_storage_key(token) for token in market_tokens],
        "eventsFetched": len(event_map),
        "propsFetched": len(props),
        "eventDates": event_dates,
        "propDates": props_dates,
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "pruneMissing": prune_missing,
        "syncedAtUtc": sync_stamp,
    }


def update_players_table(
    connection: sqlite3.Connection,
    sport_id: int,
    active_only: bool,
    prune_missing: bool,
) -> Dict[str, Any]:
    people = fetch_players_payload(sport_id)
    fetched_count = len(people)

    if active_only:
        people = [person for person in people if bool(person.get("active", False))]

    sync_stamp = utc_now_iso()
    existing_ids = {row[0] for row in connection.execute("SELECT id FROM players")}
    seen_ids: Set[int] = set()

    inserted = 0
    updated = 0
    skipped = 0

    for person in people:
        player_id = safe_int(person.get("id"), 0)
        full_name = str(person.get("fullName") or "").strip()
        if player_id <= 0 or not full_name:
            skipped += 1
            continue

        seen_ids.add(player_id)
        if player_id in existing_ids:
            updated += 1
        else:
            inserted += 1

        connection.execute(UPSERT_PLAYERS_SQL, person_to_row(person, sync_stamp))

    deleted = 0
    if prune_missing:
        if seen_ids:
            placeholders = ", ".join("?" for _ in seen_ids)
            cursor = connection.execute(
                f"DELETE FROM players WHERE id NOT IN ({placeholders})",
                tuple(sorted(seen_ids)),
            )
        else:
            cursor = connection.execute("DELETE FROM players")
        deleted = max(cursor.rowcount, 0)

    return {
        "fetched": fetched_count,
        "processed": len(people),
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "activeOnly": active_only,
        "pruneMissing": prune_missing,
        "syncedAtUtc": sync_stamp,
    }


def update_games_table(
    connection: sqlite3.Connection,
    sport_id: int,
    seasons: Iterable[int],
    prune_missing: bool,
) -> Dict[str, Any]:
    requested_seasons = [season for season in seasons if season > 0]
    if not requested_seasons:
        requested_seasons = [dt.date.today().year]

    existing_ids = {row[0] for row in connection.execute("SELECT game_pk FROM games")}
    sync_stamp = utc_now_iso()

    fetched_date_count = 0
    fetched_game_count = 0
    inserted = 0
    updated = 0
    skipped = 0
    duplicate_game_pk_rows = 0
    seen_in_payload: Set[int] = set()

    for season in requested_seasons:
        date_count, games = fetch_schedule_payload(sport_id=sport_id, season=season)
        fetched_date_count += date_count
        fetched_game_count += len(games)

        for game in games:
            game_pk = safe_int(game.get("gamePk"), 0)
            if game_pk <= 0:
                skipped += 1
                continue

            if game_pk in seen_in_payload:
                duplicate_game_pk_rows += 1
            else:
                seen_in_payload.add(game_pk)

            if game_pk in existing_ids:
                updated += 1
            else:
                inserted += 1
                existing_ids.add(game_pk)

            connection.execute(UPSERT_GAMES_SQL, game_to_row(game, sync_stamp, season))

    deleted = 0
    if prune_missing and requested_seasons:
        placeholders = ", ".join("?" for _ in requested_seasons)
        cursor = connection.execute(
            f"DELETE FROM games WHERE season IN ({placeholders}) AND last_synced_utc <> ?",
            tuple(requested_seasons) + (sync_stamp,),
        )
        deleted = max(cursor.rowcount, 0)

    return {
        "sportId": sport_id,
        "seasons": requested_seasons,
        "fetchedDateEntries": fetched_date_count,
        "fetchedGames": fetched_game_count,
        "uniqueGamePkInPayload": len(seen_in_payload),
        "duplicateGamePkRows": duplicate_game_pk_rows,
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
        "pruneMissing": prune_missing,
        "syncedAtUtc": sync_stamp,
    }


def update_teams_table(
    connection: sqlite3.Connection,
    sport_id: int,
    seasons: Iterable[int],
    prune_missing: bool,
    include_unmapped: bool,
) -> Dict[str, Any]:
    requested_seasons = [season for season in seasons if season > 0]
    if not requested_seasons:
        requested_seasons = [dt.date.today().year]

    source_map, source_rows = load_team_sources_from_games(connection, requested_seasons)
    source_team_ids = sorted(source_map.keys())

    if not source_team_ids:
        return {
            "sportId": sport_id,
            "seasons": requested_seasons,
            "sourceGameTeamRows": source_rows,
            "sourceTeamCount": 0,
            "metadataTeamPayloadRows": 0,
            "metadataMappedTeams": 0,
            "inserted": 0,
            "updated": 0,
            "deleted": 0,
            "missingMetadataTeams": 0,
            "metadataErrors": [],
            "pruneMissing": prune_missing,
            "syncedAtUtc": utc_now_iso(),
            "note": "No games rows found for requested seasons. Run games ingest first.",
        }

    metadata_by_team_id: Dict[int, Dict[str, Any]] = {}
    metadata_payload_rows = 0
    metadata_errors: List[str] = []

    for season in requested_seasons:
        try:
            teams = fetch_teams_metadata_payload(sport_id=sport_id, season=season)
        except requests.RequestException as exc:
            metadata_errors.append(f"season={season}: {exc}")
            continue

        metadata_payload_rows += len(teams)
        for team in teams:
            team_id = safe_int(team.get("id"), 0)
            if team_id <= 0 or team_id not in source_map:
                continue
            metadata_by_team_id[team_id] = team

    existing_ids = {row[0] for row in connection.execute("SELECT id FROM teams")}
    sync_stamp = utc_now_iso()
    inserted = 0
    updated = 0
    missing_metadata_teams = 0
    skipped_unmapped = 0
    target_team_ids: List[int] = []

    for team_id in source_team_ids:
        metadata_payload = metadata_by_team_id.get(team_id, {})
        fallback_names = sorted(source_map.get(team_id, {}).get("names", set()))
        fallback_name = fallback_names[0] if fallback_names else ""

        if not metadata_payload and not include_unmapped:
            missing_metadata_teams += 1
            skipped_unmapped += 1
            continue

        if team_id in existing_ids:
            updated += 1
        else:
            inserted += 1
            existing_ids.add(team_id)

        target_team_ids.append(team_id)

        if not metadata_payload:
            missing_metadata_teams += 1

        connection.execute(
            UPSERT_TEAMS_SQL,
            team_payload_to_row(team_id, metadata_payload, fallback_name, sync_stamp),
        )

    deleted = 0
    if prune_missing and target_team_ids:
        placeholders = ", ".join("?" for _ in target_team_ids)
        cursor = connection.execute(
            f"DELETE FROM teams WHERE id NOT IN ({placeholders})",
            tuple(target_team_ids),
        )
        deleted = max(cursor.rowcount, 0)

    return {
        "sportId": sport_id,
        "seasons": requested_seasons,
        "sourceGameTeamRows": source_rows,
        "sourceTeamCount": len(source_team_ids),
        "metadataTeamPayloadRows": metadata_payload_rows,
        "metadataMappedTeams": len(metadata_by_team_id),
        "missingMetadataTeams": missing_metadata_teams,
        "skippedUnmappedTeams": skipped_unmapped,
        "includeUnmapped": include_unmapped,
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "metadataErrors": metadata_errors,
        "pruneMissing": prune_missing,
        "syncedAtUtc": sync_stamp,
    }


def parse_args() -> argparse.Namespace:
    current_year = dt.date.today().year
    default_three_year_window = f"{current_year - 2},{current_year - 1},{current_year}"

    parser = argparse.ArgumentParser(
        description="Update local data tables from MLB API (players, games, teams, stats, parks, umpires, batting orders, betting odds)."
    )
    parser.add_argument(
        "--tables",
        default=os.getenv("DATA_TABLES", "players,games,teams"),
        help=(
            "Comma-separated table list to update. Supported: "
            "players,games,teams,"
            "batter_stats_season,batter_stats_last_ten_games,batter_stats_vs_rhp,batter_stats_vs_lhp,"
            "pitcher_stats_season,pitcher_stats_last_ten_games,pitcher_stats_vs_rhp,pitcher_stats_vs_lhp,"
            "batter_stats_by_park,pitcher_stats_by_park,parks,umpires,batting_orders,"
            "game_betting_odds,player_betting_odds"
        ),
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("DATABASE_PATH", "data/scoreboard.db"),
        help="SQLite database path. Default: DATABASE_PATH env var or data/scoreboard.db",
    )
    parser.add_argument(
        "--players-sport-id",
        "--sport-id",
        dest="players_sport_id",
        type=int,
        default=env_int("PLAYERS_SPORT_ID", 1),
        help="MLB Stats API sport id used for player pull. Default: 1",
    )
    parser.add_argument(
        "--active-only",
        action=argparse.BooleanOptionalAction,
        default=env_bool("PLAYERS_ACTIVE_ONLY", False),
        help="When enabled, only keep active players from the source payload.",
    )
    parser.add_argument(
        "--prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("PLAYERS_PRUNE_MISSING", False),
        help="When enabled, delete players not present in the latest source pull.",
    )
    parser.add_argument(
        "--schedule-sport-id",
        type=int,
        default=env_int("SCHEDULE_SPORT_ID", 1),
        help="MLB Stats API sport id used for schedule/game pulls. Default: 1",
    )
    parser.add_argument(
        "--schedule-seasons",
        default=os.getenv("SCHEDULE_SEASONS", str(dt.date.today().year)),
        help="Comma-separated season years for games ingest. Example: 2025,2026",
    )
    parser.add_argument(
        "--schedule-prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("SCHEDULE_PRUNE_MISSING", False),
        help="When enabled, remove games for requested seasons that are missing in latest source pull.",
    )
    parser.add_argument(
        "--teams-sport-id",
        type=int,
        default=env_int("TEAMS_SPORT_ID", 1),
        help="MLB Stats API sport id used for team metadata pulls. Default: 1",
    )
    parser.add_argument(
        "--teams-seasons",
        default=os.getenv("TEAMS_SEASONS", os.getenv("SCHEDULE_SEASONS", str(dt.date.today().year))),
        help="Comma-separated seasons used to discover teams from games table. Example: 2025,2026",
    )
    parser.add_argument(
        "--teams-prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("TEAMS_PRUNE_MISSING", False),
        help="When enabled, remove teams not present in requested seasons from games table.",
    )
    parser.add_argument(
        "--teams-include-unmapped",
        action=argparse.BooleanOptionalAction,
        default=env_bool("TEAMS_INCLUDE_UNMAPPED", False),
        help="When enabled, include teams seen in games even if MLB team metadata lookup has no match.",
    )
    parser.add_argument(
        "--stats-sport-id",
        type=int,
        default=env_int("STATS_SPORT_ID", 1),
        help="MLB Stats API sport id used for batter/pitcher split tables. Default: 1",
    )
    parser.add_argument(
        "--stats-season",
        type=int,
        default=env_int("STATS_SEASON", current_year),
        help="Season year used for season/last-ten/handedness split stats tables.",
    )
    parser.add_argument(
        "--stats-game-type",
        default=os.getenv("STATS_GAME_TYPE", "R"),
        help="Game type filter for split stats tables (default R).",
    )
    parser.add_argument(
        "--stats-page-size",
        type=int,
        default=env_int("STATS_PAGE_SIZE", 500),
        help="Pagination page size for /api/v1/stats pulls.",
    )
    parser.add_argument(
        "--stats-prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("STATS_PRUNE_MISSING", False),
        help="When enabled, remove stale rows from split stats tables for the selected season.",
    )
    parser.add_argument(
        "--by-park-seasons",
        default=os.getenv("BY_PARK_SEASONS", default_three_year_window),
        help="Comma-separated seasons for by-park, park, umpire, and batting-order tables.",
    )
    parser.add_argument(
        "--boxscore-game-types",
        default=os.getenv("BOXSCORE_GAME_TYPES", "R"),
        help="Comma-separated gameType filters for boxscore-derived tables (default R).",
    )
    parser.add_argument(
        "--parks-prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("PARKS_PRUNE_MISSING", False),
        help="When enabled, remove parks not found in selected by-park seasons.",
    )
    parser.add_argument(
        "--by-park-prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("BY_PARK_PRUNE_MISSING", False),
        help="When enabled, remove stale rows in batter or pitcher by-park tables for selected window.",
    )
    parser.add_argument(
        "--umpires-prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("UMPIRES_PRUNE_MISSING", False),
        help="When enabled, remove stale umpire rows for selected by-park seasons.",
    )
    parser.add_argument(
        "--batting-orders-prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("BATTING_ORDERS_PRUNE_MISSING", False),
        help="When enabled, remove stale batting-order rows for selected by-park seasons.",
    )
    parser.add_argument(
        "--odds-api-key",
        default=os.getenv("BETTINGPROS_API_KEY", os.getenv("BETTING_ODDS_API_KEY", BETTINGPROS_DEFAULT_API_KEY)).strip(),
        help="Optional BettingPros API key override (defaults to embedded public key used by the web client).",
    )
    parser.add_argument(
        "--odds-base-url",
        default=os.getenv("BETTINGPROS_BASE_URL", os.getenv("BETTING_ODDS_BASE_URL", BETTINGPROS_DEFAULT_BASE_URL)).strip().rstrip("/"),
        help="Base URL for BettingPros requests.",
    )
    parser.add_argument(
        "--odds-location",
        "--odds-regions",
        dest="odds_location",
        default=os.getenv("BETTINGPROS_LOCATION", os.getenv("BETTING_ODDS_REGIONS", "AZ")).strip() or "AZ",
        help="BettingPros location parameter (for example AZ).",
    )
    parser.add_argument(
        "--odds-book-id",
        "--odds-bookmakers",
        dest="odds_book_id",
        default=os.getenv("BETTINGPROS_BOOK_ID", os.getenv("BETTING_ODDS_BOOKMAKERS", "0")).strip() or "0",
        help="BettingPros book_id value (0 is consensus).",
    )
    parser.add_argument(
        "--bovada-base-url",
        default=os.getenv("BOVADA_ODDS_MLB_URL", BOVADA_DEFAULT_MLB_URL).strip(),
        help="Bovada MLB coupon endpoint used for game-line odds ingestion.",
    )
    parser.add_argument(
        "--odds-days-ahead",
        type=int,
        default=env_int("BETTING_ODDS_DAYS_AHEAD", 1),
        help="How many days ahead to include when pulling BettingPros props/events (0 = today only).",
    )
    parser.add_argument(
        "--odds-game-markets",
        default=os.getenv("BETTING_ODDS_GAME_MARKETS", "h2h,spreads,totals"),
        help="Comma-separated game-level odds markets.",
    )
    parser.add_argument(
        "--odds-player-markets",
        default=os.getenv(
            "BETTING_ODDS_PLAYER_MARKETS",
            os.getenv(
                "BETTING_ODDS_MARKETS",
                "batter_home_runs,batter_hits,batter_total_bases,pitcher_strikeouts,pitcher_outs",
            ),
        ),
        help="Comma-separated player-prop odds markets.",
    )
    parser.add_argument(
        "--odds-prune-missing",
        action=argparse.BooleanOptionalAction,
        default=env_bool("ODDS_PRUNE_MISSING", False),
        help="When enabled, remove stale rows from odds tables.",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    selected_tables = parse_csv_tokens(args.tables)
    if not selected_tables:
        selected_tables = ["players", "games", "teams"]
    selected_tables = list(dict.fromkeys(selected_tables))

    supported_tables = {
        "players",
        "games",
        "teams",
        "batter_stats_season",
        "batter_stats_last_ten_games",
        "batter_stats_vs_rhp",
        "batter_stats_vs_lhp",
        "pitcher_stats_season",
        "pitcher_stats_last_ten_games",
        "pitcher_stats_vs_rhp",
        "pitcher_stats_vs_lhp",
        "batter_stats_by_park",
        "pitcher_stats_by_park",
        "parks",
        "umpires",
        "batting_orders",
        "game_betting_odds",
        "player_betting_odds",
    }
    invalid_tables = [name for name in selected_tables if name not in supported_tables]
    if invalid_tables:
        raise SystemExit(f"Unsupported table names: {', '.join(invalid_tables)}")

    schedule_seasons = parse_int_csv(args.schedule_seasons, [dt.date.today().year])
    teams_seasons = parse_int_csv(args.teams_seasons, schedule_seasons)
    by_park_seasons = parse_int_csv(
        args.by_park_seasons,
        [dt.date.today().year - 2, dt.date.today().year - 1, dt.date.today().year],
    )
    boxscore_game_types = [token.upper() for token in parse_csv_tokens(args.boxscore_game_types)]
    if not boxscore_game_types:
        boxscore_game_types = ["R"]

    stats_season = max(1900, safe_int(args.stats_season, dt.date.today().year))
    stats_page_size = max(1, safe_int(args.stats_page_size, 500))
    stats_game_type = str(args.stats_game_type or "").strip().upper()

    odds_base_url = str(args.odds_base_url or "").strip().rstrip("/")
    if not odds_base_url or "the-odds-api" in odds_base_url.lower():
        odds_base_url = BETTINGPROS_DEFAULT_BASE_URL

    bovada_base_url = str(args.bovada_base_url or "").strip()
    if not bovada_base_url:
        bovada_base_url = BOVADA_DEFAULT_MLB_URL

    db_path = Path(args.db_path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    results: Dict[str, Dict[str, Any]] = {}

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        ensure_schema(connection)

        with connection:
            if "players" in selected_tables:
                results["players"] = update_players_table(
                    connection=connection,
                    sport_id=max(1, int(args.players_sport_id)),
                    active_only=bool(args.active_only),
                    prune_missing=bool(args.prune_missing),
                )

            if "games" in selected_tables:
                results["games"] = update_games_table(
                    connection=connection,
                    sport_id=max(1, int(args.schedule_sport_id)),
                    seasons=schedule_seasons,
                    prune_missing=bool(args.schedule_prune_missing),
                )

            if "teams" in selected_tables:
                results["teams"] = update_teams_table(
                    connection=connection,
                    sport_id=max(1, int(args.teams_sport_id)),
                    seasons=teams_seasons,
                    prune_missing=bool(args.teams_prune_missing),
                    include_unmapped=bool(args.teams_include_unmapped),
                )

            batter_split_configs = {
                "batter_stats_season": {
                    "stats_type": "season",
                    "sit_code": "",
                    "split_code_override": "",
                    "split_description_override": "",
                },
                "batter_stats_last_ten_games": {
                    "stats_type": "lastXGames",
                    "sit_code": "",
                    "split_code_override": "last10",
                    "split_description_override": "Last Ten Games",
                },
                "batter_stats_vs_rhp": {
                    "stats_type": "statSplits",
                    "sit_code": "vr",
                    "split_code_override": "vr",
                    "split_description_override": "vs Right",
                },
                "batter_stats_vs_lhp": {
                    "stats_type": "statSplits",
                    "sit_code": "vl",
                    "split_code_override": "vl",
                    "split_description_override": "vs Left",
                },
            }
            for table_name, config in batter_split_configs.items():
                if table_name not in selected_tables:
                    continue
                results[table_name] = update_batter_split_table(
                    connection=connection,
                    table_name=table_name,
                    sport_id=max(1, int(args.stats_sport_id)),
                    season=stats_season,
                    stats_type=config["stats_type"],
                    game_type=stats_game_type,
                    sit_code=config["sit_code"],
                    split_code_override=config["split_code_override"],
                    split_description_override=config["split_description_override"],
                    page_size=stats_page_size,
                    prune_missing=bool(args.stats_prune_missing),
                )

            pitcher_split_configs = {
                "pitcher_stats_season": {
                    "stats_type": "season",
                    "sit_code": "",
                    "split_code_override": "",
                    "split_description_override": "",
                },
                "pitcher_stats_last_ten_games": {
                    "stats_type": "lastXGames",
                    "sit_code": "",
                    "split_code_override": "last10",
                    "split_description_override": "Last Ten Games",
                },
                "pitcher_stats_vs_rhp": {
                    "stats_type": "statSplits",
                    "sit_code": "vr",
                    "split_code_override": "vr",
                    "split_description_override": "vs Right",
                },
                "pitcher_stats_vs_lhp": {
                    "stats_type": "statSplits",
                    "sit_code": "vl",
                    "split_code_override": "vl",
                    "split_description_override": "vs Left",
                },
            }
            for table_name, config in pitcher_split_configs.items():
                if table_name not in selected_tables:
                    continue
                results[table_name] = update_pitcher_split_table(
                    connection=connection,
                    table_name=table_name,
                    sport_id=max(1, int(args.stats_sport_id)),
                    season=stats_season,
                    stats_type=config["stats_type"],
                    game_type=stats_game_type,
                    sit_code=config["sit_code"],
                    split_code_override=config["split_code_override"],
                    split_description_override=config["split_description_override"],
                    page_size=stats_page_size,
                    prune_missing=bool(args.stats_prune_missing),
                )

            if "pitcher_stats_season" in selected_tables:
                results["pitcher_stats_season_fip_ingest"] = update_pitcher_season_fip_from_fangraphs(
                    connection=connection,
                    season=stats_season,
                )

            boxscore_tables_selected = set(selected_tables).intersection(
                {"batter_stats_by_park", "pitcher_stats_by_park", "parks", "umpires", "batting_orders"}
            )
            if boxscore_tables_selected:
                boxscore_results = update_boxscore_derived_tables(
                    connection=connection,
                    seasons=by_park_seasons,
                    game_types=boxscore_game_types,
                    include_tables=boxscore_tables_selected,
                    park_prune_missing=bool(args.parks_prune_missing),
                    by_park_prune_missing=bool(args.by_park_prune_missing),
                    umpire_prune_missing=bool(args.umpires_prune_missing),
                    batting_order_prune_missing=bool(args.batting_orders_prune_missing),
                )
                results.update(boxscore_results)

            if "game_betting_odds" in selected_tables:
                results["game_betting_odds"] = update_game_betting_odds_table(
                    connection=connection,
                    markets=str(args.odds_game_markets or "").strip(),
                    bovada_base_url=bovada_base_url,
                    prune_missing=bool(args.odds_prune_missing),
                )

            if "player_betting_odds" in selected_tables:
                results["player_betting_odds"] = update_player_betting_odds_table(
                    connection=connection,
                    api_key=str(args.odds_api_key or "").strip(),
                    base_url=odds_base_url,
                    location=str(args.odds_location or "").strip(),
                    book_id=str(args.odds_book_id or "").strip(),
                    markets=str(args.odds_player_markets or "").strip(),
                    days_ahead=max(0, safe_int(args.odds_days_ahead, 1)),
                    prune_missing=bool(args.odds_prune_missing),
                )

    print(f"Database path: {db_path}")
    if not results:
        print("No tables were selected to update.")
        return 0

    for table_name, table_result in results.items():
        print(f"Table: {table_name}")
        print(json.dumps(table_result, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
