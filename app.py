import atexit
import base64
import copy
import datetime as dt
import html
import json
import math
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, render_template, request

MLB_BASE_URL = "https://statsapi.mlb.com"
OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 12

load_dotenv()


def env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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

    try:
        return float(text)
    except ValueError:
        return default


def parse_numeric_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"n/a", "nan", "none", "null", ".---", "---"}:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    if text.startswith("."):
        text = f"0{text}"

    try:
        return float(text)
    except ValueError:
        return None


def first_numeric_field(row: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        key_text = str(key or "").strip()
        if not key_text or key_text not in row:
            continue
        parsed = parse_numeric_value(row.get(key_text))
        if parsed is not None:
            return parsed
    return None


def rate_percent(numerator: Optional[float], denominator: Optional[float], precision: int = 1) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    digits = max(0, min(4, int(precision)))
    return round((numerator / denominator) * 100.0, digits)


def add_k_bb_percentages(stat_row: Any, denominator_keys: Iterable[str]) -> None:
    if not isinstance(stat_row, dict):
        return

    denominator = first_numeric_field(stat_row, denominator_keys)
    strike_outs = first_numeric_field(stat_row, ["strike_outs", "strikeOuts", "strikeouts"])
    walks = first_numeric_field(stat_row, ["walks", "base_on_balls", "baseOnBalls"])

    k_percent = rate_percent(strike_outs, denominator, precision=1)
    bb_percent = rate_percent(walks, denominator, precision=1)

    if k_percent is not None:
        stat_row["k_percent"] = k_percent
    if bb_percent is not None:
        stat_row["bb_percent"] = bb_percent


def enrich_k_bb_percentages(stat_snapshot: Dict[str, Any]) -> None:
    if not isinstance(stat_snapshot, dict):
        return

    hitter_denominator_keys = ["plate_appearances", "plateAppearances", "at_bats", "atBats"]
    pitcher_denominator_keys = ["batters_faced", "battersFaced"]

    for split_key in ("batterSeason", "batterLastTenGames", "batterVsRhp", "batterVsLhp"):
        add_k_bb_percentages(stat_snapshot.get(split_key), hitter_denominator_keys)

    for split_key in ("pitcherSeason", "pitcherLastTenGames", "pitcherVsRhp", "pitcherVsLhp"):
        add_k_bb_percentages(stat_snapshot.get(split_key), pitcher_denominator_keys)

    for row in stat_snapshot.get("batterByPark", []) if isinstance(stat_snapshot.get("batterByPark"), list) else []:
        add_k_bb_percentages(row, hitter_denominator_keys)

    for row in stat_snapshot.get("pitcherByPark", []) if isinstance(stat_snapshot.get("pitcherByPark"), list) else []:
        add_k_bb_percentages(row, pitcher_denominator_keys)


def innings_to_decimal(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0
    if "." not in text:
        return safe_float(text, 0.0)

    whole, partial = text.split(".", 1)
    base = safe_int(whole, 0)
    if partial == "1":
        return base + (1.0 / 3.0)
    if partial == "2":
        return base + (2.0 / 3.0)
    return base + safe_float(f"0.{partial}", 0.0)


def stat_text(stats: Any, key: str, fallback: str = "N/A") -> str:
    if not isinstance(stats, dict):
        return fallback

    value = stats.get(key)
    if value is None:
        return fallback

    text = str(value).strip()
    if not text:
        return fallback

    return text


def normalize_stat_keys(raw_value: Any, fallback: List[str]) -> List[str]:
    tokens: List[str] = []
    if isinstance(raw_value, list):
        tokens = [str(item).strip() for item in raw_value]
    elif isinstance(raw_value, str):
        tokens = [part.strip() for part in raw_value.split(",")]

    seen = set()
    parsed: List[str] = []
    for token in tokens:
        if not token or token in seen:
            continue
        seen.add(token)
        parsed.append(token)

    if parsed:
        return parsed
    return list(fallback)


def stat_label_for_key(key: str) -> str:
    text = str(key or "").strip()
    if not text:
        return "STAT"
    if text in PLAYER_STAT_LABEL_OVERRIDES:
        return PLAYER_STAT_LABEL_OVERRIDES[text]

    text = text.replace("_", " ").replace("-", " ")
    chars: List[str] = []
    for index, char in enumerate(text):
        if index > 0 and char.isupper() and text[index - 1].islower():
            chars.append(" ")
        chars.append(char)

    compact = " ".join("".join(chars).split())
    return compact.title()


def player_stat_value(player_payload: Dict[str, Any], key: str) -> str:
    return player_stat_value_with_fallback(player_payload, key, "N/A")


def player_stat_value_with_fallback(player_payload: Dict[str, Any], key: str, missing_value: str) -> str:
    key_text = str(key or "").strip()
    if not key_text:
        return missing_value

    direct = player_payload.get(key_text)
    if direct is not None and str(direct).strip() != "":
        return str(direct).strip()

    stat_sources: List[str]
    if bool(player_payload.get("isPitcher")):
        stat_sources = ["pitchingStats", "hittingStats"]
    else:
        stat_sources = ["hittingStats", "pitchingStats"]

    for source_key in stat_sources:
        source = player_payload.get(source_key)
        if not isinstance(source, dict):
            continue
        value = source.get(key_text)
        if value is None:
            continue
        value_text = str(value).strip()
        if value_text:
            return value_text

    return missing_value


def build_player_stat_entries(
    player_payload: Dict[str, Any],
    stat_keys: List[str],
    missing_value: str,
    label_overrides: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    overrides = label_overrides if isinstance(label_overrides, dict) else {}
    entries: List[Dict[str, str]] = []
    for key in stat_keys:
        key_text = str(key or "").strip()
        if not key_text:
            continue

        label = str(overrides.get(key_text, "")).strip() if key_text in overrides else ""
        if not label:
            label = stat_label_for_key(key_text)

        entries.append(
            {
                "key": key_text,
                "label": label,
                "value": player_stat_value_with_fallback(player_payload, key_text, missing_value),
            }
        )
    return entries


def stat_line_from_entries(
    entries: List[Dict[str, str]],
    item_separator: str = " | ",
    label_value_separator: str = " ",
) -> str:
    parts: List[str] = []
    for entry in entries:
        label = str(entry.get("label", "")).strip()
        value = str(entry.get("value", "")).strip()
        if not label:
            continue
        parts.append(f"{label}{label_value_separator}{value}" if value else label)
    return item_separator.join(parts)


def normalize_preset_name(raw_value: Any) -> str:
    text = str(raw_value or "").strip().lower()
    if not text:
        return ""
    return text.replace("-", "_").replace(" ", "_")


def resolve_player_breakdown_preset(template: Dict[str, Any], is_pitcher: bool) -> Dict[str, Any]:
    scoped_name = normalize_preset_name(template.get("pitcherStatPreset") if is_pitcher else template.get("hitterStatPreset"))
    shared_name = normalize_preset_name(template.get("statPreset"))

    chosen_name = scoped_name or shared_name
    if not chosen_name:
        return {"name": "", "keys": []}

    preset = PLAYER_BREAKDOWN_STAT_PRESETS.get(chosen_name)
    if not isinstance(preset, dict):
        return {"name": "", "keys": []}

    key_source = preset.get("pitcher") if is_pitcher else preset.get("hitter")
    keys = normalize_stat_keys(key_source, [])
    if not keys:
        return {"name": "", "keys": []}

    return {"name": chosen_name, "keys": keys}


TEAM_ID = env_int("TEAM_ID", 135)
TEAM_NAME = os.getenv("TEAM_NAME", "San Diego Padres")
LIVE_STREAM_URL = os.getenv("LIVE_STREAM_URL", "").strip()
BOARD_TIMEZONE_NAME = (
    os.getenv("BOARD_TIMEZONE", os.getenv("APP_TIMEZONE", "America/Phoenix")).strip()
    or "America/Phoenix"
)
STATE_CACHE_TTL_SECONDS = env_int("STATE_CACHE_TTL_SECONDS", 45)
LOOKBACK_DAYS = env_int("LOOKBACK_DAYS", 10)
MAX_HIGHLIGHTS = env_int("MAX_HIGHLIGHTS", 24)
LIVE_GAME_HIGHLIGHT_MAX_AGE_HOURS = max(1, env_int("LIVE_GAME_HIGHLIGHT_MAX_AGE_HOURS", 4))

KIOSK_ENABLED = env_bool("KIOSK_ENABLED", True)
KIOSK_LAYOUT_FILE = os.getenv("KIOSK_LAYOUT_FILE", "static/kiosk-slides.json").strip()
KIOSK_TEMPLATE_FILE = os.getenv("KIOSK_TEMPLATE_FILE", "static/kiosk-templates.json").strip()
VISUAL_SCENE_TEMPLATE_FILE = os.getenv("VISUAL_SCENE_TEMPLATE_FILE", "static/visual-scene-templates.json").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/scoreboard.db").strip()

APP_ROOT = Path(__file__).resolve().parent
AUTO_UPDATE_ENABLED = env_bool("AUTO_UPDATE_ENABLED", True)
AUTO_UPDATE_INTERVAL_SECONDS = max(300, env_int("AUTO_UPDATE_INTERVAL_SECONDS", 86400))
AUTO_UPDATE_TIMEOUT_SECONDS = max(60, env_int("AUTO_UPDATE_TIMEOUT_SECONDS", 3300))
AUTO_UPDATE_RUN_ON_START = env_bool("AUTO_UPDATE_RUN_ON_START", True)
AUTO_UPDATE_EXTRA_ARGS = os.getenv("AUTO_UPDATE_EXTRA_ARGS", "").strip()
AUTO_UPDATE_SCRIPT_PATH = Path(
    os.getenv("AUTO_UPDATE_SCRIPT_PATH", "scripts/update_data_tables.py")
).expanduser()

FEATURED_PLAYER_NAME = os.getenv("FEATURED_PLAYER_NAME", "Jake Cronenworth").strip()
FEATURED_PLAYER_ID = env_int("FEATURED_PLAYER_ID", 0)
HOT_STREAK_WINDOW = env_int("HOT_STREAK_WINDOW", 5)
MAX_PLAY_BY_PLAY_ITEMS = env_int("MAX_PLAY_BY_PLAY_ITEMS", 8)

SCHEDULE_DAYS_AHEAD = env_int("SCHEDULE_DAYS_AHEAD", 7)
AUTO_LEADER_COUNT = env_int("AUTO_LEADER_COUNT", 5)
AUTO_PLAYER_SLIDE_COUNT = env_int("AUTO_PLAYER_SLIDE_COUNT", 3)
TEAM_STATS_CACHE_TTL_SECONDS = env_int("TEAM_STATS_CACHE_TTL_SECONDS", 1800)
WEATHER_ENABLED = env_bool("WEATHER_ENABLED", True)
PLAYER_NEWS_MAX_HEADLINES = env_int("PLAYER_NEWS_MAX_HEADLINES", 8)
PLAYER_GAME_LOG_FALLBACK_CACHE_TTL_SECONDS = env_int("PLAYER_GAME_LOG_FALLBACK_CACHE_TTL_SECONDS", 600)
PLAYER_PROPS_FALLBACK_CACHE_TTL_SECONDS = env_int("PLAYER_PROPS_FALLBACK_CACHE_TTL_SECONDS", 240)
PLAYER_DISPLAY_NAME_CACHE_TTL_SECONDS = env_int("PLAYER_DISPLAY_NAME_CACHE_TTL_SECONDS", 21600)

BETTINGPROS_API_KEY = os.getenv(
    "BETTINGPROS_API_KEY",
    os.getenv("BETTING_ODDS_API_KEY", ""),
).strip()
BETTINGPROS_BASE_URL = os.getenv(
    "BETTINGPROS_BASE_URL",
    os.getenv("BETTING_ODDS_BASE_URL", "https://api.bettingpros.com/v3"),
).strip().rstrip("/")
if not BETTINGPROS_BASE_URL or "the-odds-api" in BETTINGPROS_BASE_URL.lower():
    BETTINGPROS_BASE_URL = "https://api.bettingpros.com/v3"
BETTINGPROS_LOCATION = os.getenv("BETTINGPROS_LOCATION", os.getenv("BETTING_ODDS_REGIONS", "AZ")).strip() or "AZ"
BETTINGPROS_BOOK_ID = os.getenv("BETTINGPROS_BOOK_ID", os.getenv("BETTING_ODDS_BOOKMAKERS", "0")).strip() or "0"
BETTING_ODDS_DAYS_AHEAD = max(0, env_int("BETTING_ODDS_DAYS_AHEAD", 1))
BETTING_ODDS_MARKETS = (
    os.getenv(
        "BETTING_ODDS_MARKETS",
        "batter_home_runs,batter_hits,batter_total_bases,pitcher_strikeouts,pitcher_outs",
    )
    .strip()
)

PLAYER_STATS_GROUP_QUERY = "hitting,pitching,fielding,catching,running"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"

DEFAULT_PLAYER_BREAKDOWN_HITTER_STAT_KEYS = ["avg", "obp", "ops", "homeRuns", "rbi", "war"]
DEFAULT_PLAYER_BREAKDOWN_PITCHER_STAT_KEYS = ["era", "fip", "whip", "strikeOuts", "wins", "losses", "war"]

PLAYER_BREAKDOWN_STAT_PRESETS = {
    "balanced": {
        "hitter": ["avg", "obp", "ops", "homeRuns", "rbi", "war"],
        "pitcher": ["era", "fip", "whip", "strikeOuts", "wins", "losses", "war"],
    },
    "advanced": {
        "hitter": ["avg", "obp", "slugging", "ops", "war"],
        "pitcher": ["era", "fip", "whip", "strikeOuts", "war"],
    },
    "power": {
        "hitter": ["homeRuns", "rbi", "slugging", "ops", "hits", "runs"],
        "pitcher": ["strikeOuts", "wins", "losses", "era", "whip"],
    },
}

PLAYER_STAT_LABEL_OVERRIDES = {
    "atBats": "AB",
    "avg": "AVG",
    "bb_percent": "BB%",
    "bbPercent": "BB%",
    "era": "ERA",
    "fip": "FIP",
    "hits": "H",
    "homeRuns": "HR",
    "k_percent": "K%",
    "kPercent": "K%",
    "losses": "L",
    "obp": "OBP",
    "ops": "OPS",
    "rbi": "RBI",
    "runs": "R",
    "slugging": "SLG",
    "strikeOuts": "SO",
    "war": "WAR",
    "whip": "WHIP",
    "wins": "W",
}

HITTING_QUALIFYING_PA_PER_TEAM_GAME = safe_float(os.getenv("HITTING_QUALIFYING_PA_PER_TEAM_GAME"), 3.1)
PITCHING_QUALIFYING_IP_PER_TEAM_GAME = safe_float(os.getenv("PITCHING_QUALIFYING_IP_PER_TEAM_GAME"), 1.0)
RELIEF_PITCHING_QUALIFYING_IP_PER_TEAM_GAME = safe_float(os.getenv("RELIEF_PITCHING_QUALIFYING_IP_PER_TEAM_GAME"), 0.5)

DEFAULT_HITTING_LEADERBOARD_CATEGORIES = ["ops", "avg", "homeRuns", "kPercentLow"]
HITTING_LEADERBOARD_CATEGORY_ALIASES = {
    "ops": "ops",
    "avg": "avg",
    "hr": "homeRuns",
    "homeruns": "homeRuns",
    "home_runs": "homeRuns",
    "kpercent": "kPercentLow",
    "k_percent": "kPercentLow",
    "kpercentlow": "kPercentLow",
    "k_percent_low": "kPercentLow",
    "kplow": "kPercentLow",
}
HITTING_LEADERBOARD_CATEGORY_TITLES = {
    "ops": "OPS Leaders",
    "avg": "AVG Leaders",
    "homeRuns": "HR Leaders",
    "kPercentLow": "K% Leaders (Lowest)",
}

DEFAULT_PITCHING_LEADERBOARD_CATEGORIES = ["fip", "era", "strikeouts", "kPercentHigh"]
PITCHING_LEADERBOARD_CATEGORY_ALIASES = {
    "fip": "fip",
    "era": "era",
    "so": "strikeouts",
    "k": "strikeouts",
    "strikeout": "strikeouts",
    "strikeouts": "strikeouts",
    "strike_outs": "strikeouts",
    "kpercent": "kPercentHigh",
    "k_percent": "kPercentHigh",
    "kpct": "kPercentHigh",
    "kpercenthigh": "kPercentHigh",
    "k_percent_high": "kPercentHigh",
    "khigh": "kPercentHigh",
}
PITCHING_LEADERBOARD_CATEGORY_TITLES = {
    "fip": "FIP Leaders",
    "era": "ERA Leaders",
    "strikeouts": "Strikeout Leaders",
    "kPercentHigh": "K% Leaders (Highest)",
}

PLAYBACK_PRIORITY = [
    "mp4Avc",
    "HTTP_CLOUD_WIRED_60",
    "HTTP_CLOUD_WIRED",
    "hlsCloud",
    "highBit",
]

ALLOWED_LAYOUT_SLIDE_TYPES = {
    "status",
    "live_game_status",
    "game_today",
    "previous_game_pbp",
    "featured_player",
    "schedule_overview",
    "upcoming_weather",
    "team_hitting_leaders",
    "team_pitching_leaders",
    "player_breakdown",
}

ALLOWED_TEMPLATE_TYPES = {
    "status",
    "live_game_status",
    "game_today",
    "schedule_overview",
    "upcoming_weather",
    "team_hitting_leaders",
    "team_pitching_leaders",
    "player_breakdowns",
    "previous_game_pbp",
    "featured_player",
}

DEFAULT_KIOSK_LAYOUT: Dict[str, Any] = {
    "enabled": True,
    "rotationSeconds": 14,
    "slides": [
        {"id": "status", "type": "status", "title": "Game Pulse", "durationSeconds": 10},
        {
            "id": "previous-game",
            "type": "previous_game_pbp",
            "title": "Previous Game Story",
            "durationSeconds": 18,
        },
        {
            "id": "featured-player",
            "type": "featured_player",
            "title": "Featured Player Breakdown",
            "durationSeconds": 22,
        },
    ],
}

DEFAULT_SLIDE_TEMPLATE_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "defaultDurationSeconds": 14,
    "templates": [
        {"id": "status", "type": "status", "title": "Game Pulse", "durationSeconds": 10},
        {
            "id": "live-game-status",
            "type": "live_game_status",
            "title": "Live Game Center",
            "durationSeconds": 30,
            "pinWhenLive": True,
            "highlightLimit": 12,
        },
        {
            "id": "game-today",
            "type": "game_today",
            "title": "Game Today",
            "durationSeconds": 14,
            "maxGames": 2,
        },
        {
            "id": "schedule",
            "type": "schedule_overview",
            "title": "Upcoming Schedule",
            "durationSeconds": 16,
            "maxGames": 6,
        },
        {
            "id": "weather",
            "type": "upcoming_weather",
            "title": "Next Game Weather",
            "durationSeconds": 14,
        },
        {
            "id": "padres-bats",
            "type": "team_hitting_leaders",
            "team": "padres",
            "title": "Padres Hitting Leaders",
            "durationSeconds": 30,
            "count": 5,
        },
        {
            "id": "padres-arms",
            "type": "team_pitching_leaders",
            "team": "padres",
            "title": "Padres Pitching Leaders",
            "durationSeconds": 30,
            "count": 5,
        },
        {
            "id": "opp-bats",
            "type": "team_hitting_leaders",
            "team": "opponent",
            "title": "Opponent Hitting Leaders",
            "durationSeconds": 30,
            "count": 5,
        },
        {
            "id": "opp-arms",
            "type": "team_pitching_leaders",
            "team": "opponent",
            "title": "Opponent Pitching Leaders",
            "durationSeconds": 30,
            "count": 5,
        },
        {
            "id": "padres-player-cards",
            "type": "player_breakdowns",
            "team": "padres",
            "title": "Padres Breakdown",
            "durationSeconds": 20,
            "count": 3,
            "statPreset": "balanced",
            "missingStatValue": "N/A",
        },
    ],
}

DEFAULT_VISUAL_SCENE_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "slideTransitionMs": 650,
    "elementDefaults": {
        "enter": {
            "effect": "slide-up",
            "durationMs": 700,
            "delayMs": 0,
            "easing": "cubic-bezier(0.22, 1, 0.36, 1)",
        },
        "exit": {
            "effect": "fade",
            "durationMs": 460,
            "delayMs": 0,
            "easing": "ease",
        },
    },
    "templates": {},
}

app = Flask(__name__)
_state_lock = threading.Lock()
_state_cache: Dict[str, Any] = {"updated_at": 0.0, "data": None}

_team_stats_lock = threading.Lock()
_team_stats_cache: Dict[int, Dict[str, Any]] = {}

_player_game_log_fallback_lock = threading.Lock()
_player_game_log_fallback_cache: Dict[str, Dict[str, Any]] = {}

_player_props_fallback_lock = threading.Lock()
_player_props_fallback_cache: Dict[str, Dict[str, Any]] = {}

_player_display_name_lock = threading.Lock()
_player_display_name_cache: Dict[int, Dict[str, Any]] = {}

_data_updater_lock = threading.Lock()
_data_updater_stop_event = threading.Event()
_data_updater_thread: Optional[threading.Thread] = None


def resolve_auto_update_script_path() -> Path:
    configured_path = AUTO_UPDATE_SCRIPT_PATH
    if configured_path.is_absolute():
        return configured_path
    return (APP_ROOT / configured_path).resolve()


def summarize_command_output(raw_text: str, max_lines: int = 12) -> str:
    lines = [line for line in str(raw_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def run_data_updater_once(trigger_reason: str = "scheduled") -> None:
    script_path = resolve_auto_update_script_path()
    if not script_path.exists():
        app.logger.warning(
            "Background data updater skipped (%s): script not found at %s",
            trigger_reason,
            script_path,
        )
        return

    command = [sys.executable, str(script_path)]
    if AUTO_UPDATE_EXTRA_ARGS:
        try:
            command.extend(shlex.split(AUTO_UPDATE_EXTRA_ARGS))
        except ValueError as exc:
            app.logger.error("Background data updater args parse error: %s", exc)
            return

    with _data_updater_lock:
        started_at = time.monotonic()
        app.logger.info("Starting background data updater (%s).", trigger_reason)

        try:
            completed = subprocess.run(
                command,
                cwd=str(APP_ROOT),
                capture_output=True,
                text=True,
                timeout=AUTO_UPDATE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_seconds = time.monotonic() - started_at
            app.logger.error(
                "Background data updater timed out after %.1fs (limit=%ss).",
                duration_seconds,
                AUTO_UPDATE_TIMEOUT_SECONDS,
            )

            stdout_summary = summarize_command_output(exc.stdout or "")
            stderr_summary = summarize_command_output(exc.stderr or "")
            if stdout_summary:
                app.logger.error("Updater stdout (tail):\n%s", stdout_summary)
            if stderr_summary:
                app.logger.error("Updater stderr (tail):\n%s", stderr_summary)
            return
        except Exception:
            app.logger.exception("Background data updater failed to start.")
            return

        duration_seconds = time.monotonic() - started_at
        stdout_summary = summarize_command_output(completed.stdout)
        stderr_summary = summarize_command_output(completed.stderr)

        if completed.returncode == 0:
            app.logger.info("Background data updater finished in %.1fs.", duration_seconds)
            if stdout_summary:
                app.logger.info("Updater output (tail):\n%s", stdout_summary)
            return

        app.logger.error(
            "Background data updater failed with exit code %s after %.1fs.",
            completed.returncode,
            duration_seconds,
        )
        if stdout_summary:
            app.logger.error("Updater stdout (tail):\n%s", stdout_summary)
        if stderr_summary:
            app.logger.error("Updater stderr (tail):\n%s", stderr_summary)


def data_updater_scheduler_loop() -> None:
    app.logger.info(
        "Background data updater enabled: interval=%ss, run_on_start=%s",
        AUTO_UPDATE_INTERVAL_SECONDS,
        AUTO_UPDATE_RUN_ON_START,
    )

    if AUTO_UPDATE_RUN_ON_START:
        run_data_updater_once("startup")

    next_run_time = time.monotonic() + AUTO_UPDATE_INTERVAL_SECONDS
    while not _data_updater_stop_event.is_set():
        wait_seconds = max(0.5, next_run_time - time.monotonic())
        if _data_updater_stop_event.wait(wait_seconds):
            break

        run_data_updater_once("scheduled")
        next_run_time += AUTO_UPDATE_INTERVAL_SECONDS

        now = time.monotonic()
        if next_run_time < now:
            next_run_time = now + AUTO_UPDATE_INTERVAL_SECONDS


def start_background_data_updater() -> None:
    global _data_updater_thread

    if not AUTO_UPDATE_ENABLED:
        app.logger.info("Background data updater disabled (AUTO_UPDATE_ENABLED=0).")
        return

    if _data_updater_thread and _data_updater_thread.is_alive():
        return

    _data_updater_stop_event.clear()
    _data_updater_thread = threading.Thread(
        target=data_updater_scheduler_loop,
        name="background-data-updater",
        daemon=True,
    )
    _data_updater_thread.start()


def stop_background_data_updater() -> None:
    _data_updater_stop_event.set()
    thread = _data_updater_thread
    if thread and thread.is_alive():
        thread.join(timeout=1.5)


atexit.register(stop_background_data_updater)


def mlb_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{MLB_BASE_URL}{path}"
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "PadresPiBoard/1.0"},
    )
    response.raise_for_status()
    return response.json()


def weather_get(params: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.get(
        OPEN_METEO_BASE_URL,
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "PadresPiBoard/1.0"},
    )
    response.raise_for_status()
    return response.json()


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_board_timezone() -> dt.tzinfo:
    try:
        return ZoneInfo(BOARD_TIMEZONE_NAME)
    except ZoneInfoNotFoundError:
        local_timezone = dt.datetime.now().astimezone().tzinfo
        return local_timezone or dt.timezone.utc


def board_now() -> dt.datetime:
    return dt.datetime.now(resolve_board_timezone())


def board_today() -> dt.date:
    return board_now().date()


def board_season() -> int:
    return board_today().year


def utc_timestamp_iso(unix_seconds: float) -> str:
    return dt.datetime.fromtimestamp(unix_seconds, dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_date(raw_value: Any) -> Optional[dt.date]:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_iso_datetime(raw_value: Any) -> Optional[dt.datetime]:
    text = str(raw_value or "").strip()
    if not text:
        return None

    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                parsed = dt.datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def parse_bool_value(raw_value: Any, default: bool = False) -> bool:
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return bool(raw_value)
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def resolve_database_path() -> Path:
    candidate = Path(DATABASE_PATH or "data/scoreboard.db")
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parent / candidate


def open_database_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(str(resolve_database_path()))
    connection.row_factory = sqlite3.Row
    return connection


def decode_json_text(raw_value: Any) -> Optional[Any]:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def normalize_database_row(row: Dict[str, Any], include_raw_json: bool = False) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in row.items():
        if key == "raw_json" and not include_raw_json:
            continue

        if key.endswith("_json"):
            parsed = decode_json_text(value)
            if parsed is not None:
                normalized[key[: -len("_json")]] = parsed
            elif value not in {None, ""}:
                normalized[key] = value
            continue

        normalized[key] = value

    return normalized


def row_to_dict(row: Optional[sqlite3.Row], include_raw_json: bool = False) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return normalize_database_row(dict(row), include_raw_json=include_raw_json)


def rows_to_dicts(rows: List[sqlite3.Row], include_raw_json: bool = False) -> List[Dict[str, Any]]:
    return [normalize_database_row(dict(row), include_raw_json=include_raw_json) for row in rows]


def sqlite_table_names(connection: sqlite3.Connection) -> set:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = set()
    for row in rows:
        if isinstance(row, sqlite3.Row):
            names.add(str(row["name"]))
        elif isinstance(row, (list, tuple)) and row:
            names.add(str(row[0]))
    return names


def sqlite_table_columns(connection: sqlite3.Connection, table_name: str) -> set:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    columns = set()
    for row in rows:
        if isinstance(row, sqlite3.Row):
            column_name = str(row["name"] or "").strip()
        elif isinstance(row, (list, tuple)) and len(row) > 1:
            column_name = str(row[1] or "").strip()
        else:
            column_name = ""

        if column_name:
            columns.add(column_name)

    return columns


def summarize_player_odds_by_market(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        market_key = str(row.get("market_key") or "").strip() or "unknown"
        selection_name = str(row.get("selection_name") or "").strip()
        side_token = selection_name.lower()
        if side_token.startswith("over"):
            side = "over"
        elif side_token.startswith("under"):
            side = "under"
        else:
            side = "other"

        current_bucket = summary.setdefault(
            market_key,
            {
                "marketKey": market_key,
                "over": None,
                "under": None,
                "other": [],
            },
        )

        implied_probability, implied_probability_percent = normalize_implied_probability_values(
            row.get("implied_probability"),
            row.get("implied_probability_percent"),
            row.get("odds_price"),
        )

        normalized = {
            "selectionName": selection_name,
            "line": row.get("line"),
            "oddsPrice": row.get("odds_price"),
            "impliedProbability": implied_probability,
            "impliedProbabilityPercent": implied_probability_percent,
            "impliedProbabilityRaw": implied_probability,
            "impliedProbabilityPercentRaw": implied_probability_percent,
            "bookmaker": row.get("bookmaker_title") or row.get("bookmaker_key"),
            "commenceTime": row.get("commence_time"),
        }

        if side == "other":
            current_bucket["other"].append(normalized)
            continue

        existing = current_bucket.get(side)
        existing_price = safe_int(existing.get("oddsPrice"), -99999) if isinstance(existing, dict) else -99999
        candidate_price = safe_int(normalized.get("oddsPrice"), -99999)
        if not existing or candidate_price > existing_price:
            current_bucket[side] = normalized

    for market_bucket in summary.values():
        if not isinstance(market_bucket, dict):
            continue
        apply_no_vig_pair_probabilities(market_bucket.get("over"), market_bucket.get("under"))

    return summary


MLB_TEAM_COLOR_PALETTES: Dict[int, Dict[str, str]] = {
    108: {"primary": "#BA0021", "secondary": "#003263", "accent": "#869397"},
    109: {"primary": "#A71930", "secondary": "#E3D4AD", "accent": "#000000"},
    110: {"primary": "#DF4601", "secondary": "#000000", "accent": "#FFFFFF"},
    111: {"primary": "#BD3039", "secondary": "#0C2340", "accent": "#C4CED4"},
    112: {"primary": "#0E3386", "secondary": "#CC3433", "accent": "#FFFFFF"},
    113: {"primary": "#C6011F", "secondary": "#000000", "accent": "#FFFFFF"},
    114: {"primary": "#0C2340", "secondary": "#E31937", "accent": "#9EA2A2"},
    115: {"primary": "#33006F", "secondary": "#C4CED4", "accent": "#000000"},
    116: {"primary": "#0C2340", "secondary": "#FA4616", "accent": "#FFFFFF"},
    117: {"primary": "#002D62", "secondary": "#EB6E1F", "accent": "#FFFFFF"},
    118: {"primary": "#004687", "secondary": "#BD9B60", "accent": "#FFFFFF"},
    119: {"primary": "#005A9C", "secondary": "#EF3E42", "accent": "#FFFFFF"},
    120: {"primary": "#AB0003", "secondary": "#14225A", "accent": "#FFFFFF"},
    121: {"primary": "#002D72", "secondary": "#FF5910", "accent": "#FFFFFF"},
    133: {"primary": "#003831", "secondary": "#EFB21E", "accent": "#FFFFFF"},
    134: {"primary": "#27251F", "secondary": "#FDB827", "accent": "#FFFFFF"},
    135: {"primary": "#2F241D", "secondary": "#FFC425", "accent": "#A2AAAD"},
    136: {"primary": "#0C2C56", "secondary": "#005C5C", "accent": "#C4CED4"},
    137: {"primary": "#FD5A1E", "secondary": "#27251F", "accent": "#FFFFFF"},
    138: {"primary": "#C41E3A", "secondary": "#0C2340", "accent": "#FEDB00"},
    139: {"primary": "#092C5C", "secondary": "#8FBCE6", "accent": "#FFFFFF"},
    140: {"primary": "#003278", "secondary": "#C0111F", "accent": "#FFFFFF"},
    141: {"primary": "#134A8E", "secondary": "#1D2D5C", "accent": "#E8291C"},
    142: {"primary": "#002B5C", "secondary": "#D31145", "accent": "#B9975B"},
    143: {"primary": "#E81828", "secondary": "#002D72", "accent": "#FFFFFF"},
    144: {"primary": "#CE1141", "secondary": "#13274F", "accent": "#FFFFFF"},
    145: {"primary": "#27251F", "secondary": "#C4CED4", "accent": "#FFFFFF"},
    146: {"primary": "#00A3E0", "secondary": "#EF3340", "accent": "#000000"},
    147: {"primary": "#003087", "secondary": "#E4002B", "accent": "#C4CED4"},
    158: {"primary": "#12284B", "secondary": "#FFC52F", "accent": "#FFFFFF"},
}


def normalize_hex_color(raw_value: Any, fallback: str = "#1A334B") -> str:
    text = str(raw_value or "").strip()
    if not text:
        return fallback

    if text.startswith("#"):
        text = text[1:]

    if len(text) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in text):
        text = "".join(ch * 2 for ch in text)

    if len(text) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        return fallback

    return f"#{text.upper()}"


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    normalized = normalize_hex_color(color)
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def rgb_to_hex(red: float, green: float, blue: float) -> str:
    bounded_red = max(0, min(255, int(round(red))))
    bounded_green = max(0, min(255, int(round(green))))
    bounded_blue = max(0, min(255, int(round(blue))))
    return f"#{bounded_red:02X}{bounded_green:02X}{bounded_blue:02X}"


def mix_hex(color_a: str, color_b: str, ratio: float) -> str:
    red_a, green_a, blue_a = hex_to_rgb(color_a)
    red_b, green_b, blue_b = hex_to_rgb(color_b)
    blend = max(0.0, min(1.0, float(ratio)))

    return rgb_to_hex(
        red_a + ((red_b - red_a) * blend),
        green_a + ((green_b - green_a) * blend),
        blue_a + ((blue_b - blue_a) * blend),
    )


def complementary_hex(color: str) -> str:
    red, green, blue = hex_to_rgb(color)
    return rgb_to_hex(255 - red, 255 - green, 255 - blue)


def relative_luminance(color: str) -> float:
    red, green, blue = hex_to_rgb(color)

    def linearize(channel: int) -> float:
        scaled = max(0.0, min(255.0, float(channel))) / 255.0
        if scaled <= 0.03928:
            return scaled / 12.92
        return ((scaled + 0.055) / 1.055) ** 2.4

    linear_red = linearize(red)
    linear_green = linearize(green)
    linear_blue = linearize(blue)
    return (0.2126 * linear_red) + (0.7152 * linear_green) + (0.0722 * linear_blue)


def contrast_ratio(color_a: str, color_b: str) -> float:
    luminance_a = relative_luminance(color_a)
    luminance_b = relative_luminance(color_b)
    lighter = max(luminance_a, luminance_b)
    darker = min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_text_color(background_color: str, light: str = "#F8FBFF", dark: str = "#10171F") -> str:
    normalized_background = normalize_hex_color(background_color)
    normalized_light = normalize_hex_color(light, "#F8FBFF")
    normalized_dark = normalize_hex_color(dark, "#10171F")

    light_score = contrast_ratio(normalized_background, normalized_light)
    dark_score = contrast_ratio(normalized_background, normalized_dark)
    return normalized_light if light_score >= dark_score else normalized_dark


def rgba_from_hex(color: str, alpha: float) -> str:
    red, green, blue = hex_to_rgb(color)
    bounded_alpha = max(0.0, min(1.0, float(alpha)))
    return f"rgba({red}, {green}, {blue}, {bounded_alpha:.3f})"


def darken_hex(color: str, amount: float) -> str:
    red, green, blue = hex_to_rgb(color)
    factor = max(0.0, min(1.0, float(amount)))
    return "#{:02X}{:02X}{:02X}".format(
        int(round(red * (1.0 - factor))),
        int(round(green * (1.0 - factor))),
        int(round(blue * (1.0 - factor))),
    )


def team_theme_colors(team_id: int) -> Dict[str, Any]:
    palette = MLB_TEAM_COLOR_PALETTES.get(team_id) or {
        "primary": "#1A334B",
        "secondary": "#2B5C57",
        "accent": "#9EB3C8",
    }

    primary = normalize_hex_color(palette.get("primary"), "#1A334B")
    secondary = normalize_hex_color(palette.get("secondary"), "#2B5C57")
    accent = normalize_hex_color(palette.get("accent"), "#9EB3C8")

    primary_dark = darken_hex(primary, 0.42)
    secondary_dark = darken_hex(secondary, 0.36)
    accent_dark = darken_hex(accent, 0.52)

    gradient = (
        "linear-gradient(138deg, "
        f"{primary_dark} 0%, "
        f"{secondary_dark} 44%, "
        f"{accent_dark} 100%)"
    )
    overlay = (
        "linear-gradient(92deg, "
        f"{rgba_from_hex(darken_hex(primary, 0.84), 0.92)} 0%, "
        f"{rgba_from_hex(darken_hex(secondary, 0.86), 0.72)} 46%, "
        f"{rgba_from_hex(darken_hex(accent, 0.88), 0.28)} 100%)"
    )

    complementary_primary = complementary_hex(primary)
    complementary_secondary = complementary_hex(secondary)
    complementary_accent = complementary_hex(accent)

    title_text = contrast_text_color(primary_dark)
    # Body copy appears on darkened gradients/overlays, so contrast against a blended scene backdrop.
    body_text = contrast_text_color(mix_hex(primary_dark, secondary_dark, 0.50))
    muted_text = mix_hex(title_text, accent if title_text == "#F8FBFF" else secondary, 0.26)
    highlight_text = mix_hex(accent, title_text, 0.35)

    panel_background = rgba_from_hex(darken_hex(primary, 0.78), 0.44)
    panel_border = rgba_from_hex(mix_hex(accent, title_text, 0.30), 0.48)
    stat_background = rgba_from_hex(darken_hex(primary, 0.80), 0.62)
    stat_border = rgba_from_hex(mix_hex(accent, title_text, 0.28), 0.62)

    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "gradient": gradient,
        "overlay": overlay,
        "text": {
            "title": title_text,
            "body": body_text,
            "muted": muted_text,
            "highlight": highlight_text,
            "onPrimary": contrast_text_color(primary),
            "onSecondary": contrast_text_color(secondary),
            "onAccent": contrast_text_color(accent),
            "onComplementaryPrimary": contrast_text_color(complementary_primary),
        },
        "complementary": {
            "primary": complementary_primary,
            "secondary": complementary_secondary,
            "accent": complementary_accent,
        },
        "cards": {
            "panelBackground": panel_background,
            "panelBorder": panel_border,
            "statBackground": stat_background,
            "statBorder": stat_border,
        },
    }


def fallback_team_abbreviation(team_name: Any) -> str:
    text = str(team_name or "").strip()
    if not text:
        return ""

    tokens = [token for token in text.split(" ") if token]
    if len(tokens) >= 2:
        initials = "".join(token[0] for token in tokens[:3]).upper()
        if len(initials) >= 2:
            return initials

    cleaned = re.sub(r"[^A-Za-z0-9]", "", text)
    return cleaned[:3].upper()


def team_logo_urls(team_id: int) -> Dict[str, str]:
    if team_id <= 0:
        return {}

    return {
        "primary": f"https://www.mlbstatic.com/team-logos/{team_id}.svg",
        "capOnDark": f"https://www.mlbstatic.com/team-logos/team-cap-on-dark/{team_id}.svg",
        "capOnLight": f"https://www.mlbstatic.com/team-logos/team-cap-on-light/{team_id}.svg",
    }


def svg_data_uri(svg_markup: str) -> str:
    encoded = base64.b64encode(str(svg_markup or "").encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def build_live_dot_icon(active: bool, active_fill: str) -> str:
    fill = active_fill if active else "#1f2937"
    fill_opacity = "0.96" if active else "0.42"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">'
        f'<circle cx="24" cy="24" r="16" fill="{fill}" fill-opacity="{fill_opacity}" stroke="#d9e2f3" stroke-opacity="0.82" stroke-width="3"/>'
        "</svg>"
    )
    return svg_data_uri(svg)


def build_live_base_icon(occupied: bool) -> str:
    fill = "#ffd166" if occupied else "#1d2634"
    fill_opacity = "0.98" if occupied else "0.44"
    occupied_inner = (
        '<circle cx="24" cy="24" r="6" fill="#fff7d1" fill-opacity="0.96"/>' if occupied else ""
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">'
        f'<rect x="10" y="10" width="28" height="28" transform="rotate(45 24 24)" fill="{fill}" fill-opacity="{fill_opacity}" stroke="#d9e2f3" stroke-opacity="0.86" stroke-width="3"/>'
        f"{occupied_inner}"
        "</svg>"
    )
    return svg_data_uri(svg)


def build_live_count_indicator_slots(value: Any, slot_count: int, active_fill: str) -> List[Dict[str, Any]]:
    current = max(0, min(slot_count, safe_int(value, 0)))
    slots: List[Dict[str, Any]] = []
    for index in range(slot_count):
        is_active = index < current
        slots.append(
            {
                "slot": index + 1,
                "active": is_active,
                "icon": build_live_dot_icon(is_active, active_fill),
            }
        )
    return slots


def normalize_runner_last_name(raw_name: Any) -> str:
    full_name = str(raw_name or "").strip()
    if not full_name or full_name == "--":
        return "--"

    parts = [part for part in full_name.replace(",", " ").split(" ") if part]
    if not parts:
        return "--"

    last_token = parts[-1]
    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    normalized_last = last_token.lower().rstrip(".")
    if normalized_last in suffixes and len(parts) >= 2:
        last_token = parts[-2]

    return last_token


def build_live_base_indicator_payload(base_runners: Dict[str, Any]) -> Dict[str, Any]:
    first_runner = base_runners.get("first")
    second_runner = base_runners.get("second")
    third_runner = base_runners.get("third")

    first_occupied = bool(first_runner)
    second_occupied = bool(second_runner)
    third_occupied = bool(third_runner)
    first_runner_name = str((first_runner or {}).get("fullName") or "--").strip()
    second_runner_name = str((second_runner or {}).get("fullName") or "--").strip()
    third_runner_name = str((third_runner or {}).get("fullName") or "--").strip()

    return {
        "first": {
            "occupied": first_occupied,
            "icon": build_live_base_icon(first_occupied),
            "runner": first_runner_name,
            "runnerLastName": normalize_runner_last_name(first_runner_name),
        },
        "second": {
            "occupied": second_occupied,
            "icon": build_live_base_icon(second_occupied),
            "runner": second_runner_name,
            "runnerLastName": normalize_runner_last_name(second_runner_name),
        },
        "third": {
            "occupied": third_occupied,
            "icon": build_live_base_icon(third_occupied),
            "runner": third_runner_name,
            "runnerLastName": normalize_runner_last_name(third_runner_name),
        },
    }


def build_live_indicator_payload(balls: Any, strikes: Any, outs: Any, base_runners: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "count": {
            "balls": build_live_count_indicator_slots(balls, 4, "#65d9ff"),
            "strikes": build_live_count_indicator_slots(strikes, 3, "#ff9f43"),
            "outs": build_live_count_indicator_slots(outs, 3, "#ff5f76"),
        },
        "bases": build_live_base_indicator_payload(base_runners),
    }


def display_value(raw_value: Any, fallback: str = "--") -> str:
    if raw_value is None:
        return fallback

    text = str(raw_value).strip()
    if not text:
        return fallback
    if text.lower() in {"none", "null", "nan"}:
        return fallback
    return text


STAT_DECIMAL_PRECISION_BY_KEY: Dict[str, int] = {
    "avg": 3,
    "obp": 3,
    "ops": 3,
    "slg": 3,
    "era": 2,
    "fip": 2,
    "whip": 2,
}


def format_decimal_stat_value(stat_key: Any, raw_value: Any) -> Any:
    key_text = str(stat_key or "").strip().lower()
    precision = STAT_DECIMAL_PRECISION_BY_KEY.get(key_text)
    if precision is None:
        return raw_value

    numeric_value = parse_numeric_value(raw_value)
    if numeric_value is None:
        return raw_value

    return f"{numeric_value:.{precision}f}"


def apply_stat_decimal_precision(value: Any, current_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: apply_stat_decimal_precision(child_value, str(key or ""))
            for key, child_value in value.items()
        }

    if isinstance(value, list):
        return [apply_stat_decimal_precision(item, current_key) for item in value]

    return format_decimal_stat_value(current_key, value)


def display_stat_value(row: Any, key: str, fallback: str = "--") -> str:
    if not isinstance(row, dict):
        return fallback

    formatted = format_decimal_stat_value(key, row.get(key))
    return display_value(formatted, fallback)


def display_odds_price(raw_value: Any, fallback: str = "--") -> str:
    if raw_value is None:
        return fallback

    try:
        numeric = int(raw_value)
    except (TypeError, ValueError):
        return display_value(raw_value, fallback)

    return f"{numeric:+d}"


def implied_probability_from_american_odds(raw_value: Any) -> Optional[float]:
    if raw_value is None:
        return None

    odds: Optional[int] = None
    try:
        odds = int(raw_value)
    except (TypeError, ValueError):
        text = str(raw_value).strip().upper()
        if text == "EVEN":
            odds = 100

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


def implied_probability_percent_from_american_odds(raw_value: Any) -> Optional[float]:
    probability = implied_probability_from_american_odds(raw_value)
    if probability is None:
        return None
    return round(float(probability) * 100.0, 4)


def normalize_implied_probability_values(
    raw_probability: Any,
    raw_probability_percent: Any,
    raw_odds_price: Any,
) -> tuple[Optional[float], Optional[float]]:
    implied_probability = parse_numeric_value(raw_probability)
    if implied_probability is None:
        implied_probability = implied_probability_from_american_odds(raw_odds_price)

    implied_probability_percent = parse_numeric_value(raw_probability_percent)
    if implied_probability_percent is None:
        if implied_probability is not None:
            implied_probability_percent = round(float(implied_probability) * 100.0, 4)
        else:
            implied_probability_percent = implied_probability_percent_from_american_odds(raw_odds_price)

    return implied_probability, implied_probability_percent


def apply_no_vig_pair_probabilities(
    first: Optional[Dict[str, Any]],
    second: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return

    first_probability = parse_numeric_value(first.get("impliedProbabilityRaw"))
    if first_probability is None:
        first_probability = parse_numeric_value(first.get("impliedProbability"))

    second_probability = parse_numeric_value(second.get("impliedProbabilityRaw"))
    if second_probability is None:
        second_probability = parse_numeric_value(second.get("impliedProbability"))

    if first_probability is None or second_probability is None:
        return

    if first_probability <= 0 or second_probability <= 0:
        return

    total = first_probability + second_probability
    if total <= 0 or not math.isfinite(total):
        return

    first_no_vig = round(first_probability / total, 6)
    second_no_vig = round(second_probability / total, 6)

    first["impliedProbability"] = first_no_vig
    first["impliedProbabilityPercent"] = round(first_no_vig * 100.0, 4)
    second["impliedProbability"] = second_no_vig
    second["impliedProbabilityPercent"] = round(second_no_vig * 100.0, 4)


def summarize_market_line(
    odds_by_market: Dict[str, Any],
    market_keys: Iterable[str],
    label: str,
) -> str:
    if not isinstance(odds_by_market, dict):
        return ""

    for market_key in market_keys:
        market = odds_by_market.get(str(market_key or "").strip())
        if not isinstance(market, dict):
            continue

        for side_key, side_label in (("over", "O"), ("under", "U")):
            side = market.get(side_key)
            if not isinstance(side, dict):
                continue

            line_text = display_value(side.get("line"), "--")
            odds_text = display_odds_price(side.get("oddsPrice"), "--")
            return f"{label} {side_label} {line_text} ({odds_text})"

        others = market.get("other")
        if isinstance(others, list) and others:
            first_other = others[0] if isinstance(others[0], dict) else {}
            line_text = display_value(first_other.get("line"), "--")
            odds_text = display_odds_price(first_other.get("oddsPrice"), "--")
            return f"{label} {line_text} ({odds_text})"

    return ""


def has_any_market_lines(odds_by_market: Dict[str, Any], market_keys: Iterable[str]) -> bool:
    if not isinstance(odds_by_market, dict):
        return False

    for market_key in market_keys:
        market = odds_by_market.get(str(market_key or "").strip())
        if not isinstance(market, dict):
            continue
        if isinstance(market.get("over"), dict) or isinstance(market.get("under"), dict):
            return True
        others = market.get("other")
        if isinstance(others, list) and bool(others):
            return True

    return False


def build_batter_stat_rows(stat_snapshot: Dict[str, Any], odds_by_market: Dict[str, Any]) -> List[Dict[str, str]]:
    batter_season = stat_snapshot.get("batterSeason") if isinstance(stat_snapshot, dict) else None
    batter_last_ten = stat_snapshot.get("batterLastTenGames") if isinstance(stat_snapshot, dict) else None
    batter_vs_rhp = stat_snapshot.get("batterVsRhp") if isinstance(stat_snapshot, dict) else None
    batter_vs_lhp = stat_snapshot.get("batterVsLhp") if isinstance(stat_snapshot, dict) else None
    pitcher_season = stat_snapshot.get("pitcherSeason") if isinstance(stat_snapshot, dict) else None

    props_candidates = [
        ("Hits", ["batter_hits"]),
        ("HR", ["batter_home_runs"]),
        ("TB", ["batter_total_bases"]),
        ("RBI", ["batter_rbis"]),
        ("Runs", ["batter_runs"]),
        ("SB", ["batter_stolen_bases"]),
        ("R+H+RBI", ["batter_runs_hits_rbis"]),
    ]

    props_lines: List[str] = []
    for label, market_keys in props_candidates:
        summary_line = summarize_market_line(odds_by_market, market_keys, label)
        if summary_line:
            props_lines.append(summary_line)
        if len(props_lines) >= 3:
            break

    props_text = " | ".join(props_lines) if props_lines else "No posted props for this player right now"

    rows: List[Dict[str, str]] = [
        {
            "label": "Season",
            "value": (
                f"AVG {display_stat_value(batter_season, 'avg')} | "
                f"OBP {display_stat_value(batter_season, 'obp')} | "
                f"OPS {display_stat_value(batter_season, 'ops')} | "
                f"HR {display_stat_value(batter_season, 'home_runs')} | "
                f"RBI {display_stat_value(batter_season, 'rbi')}"
            ),
        },
        {
            "label": "Last 10",
            "value": (
                f"AVG {display_stat_value(batter_last_ten, 'avg')} | "
                f"OPS {display_stat_value(batter_last_ten, 'ops')} | "
                f"AB {display_stat_value(batter_last_ten, 'at_bats')} | "
                f"H {display_stat_value(batter_last_ten, 'hits')}"
            ),
        },
        {
            "label": "Splits",
            "value": (
                f"vs RHP {display_stat_value(batter_vs_rhp, 'avg')} | "
                f"vs LHP {display_stat_value(batter_vs_lhp, 'avg')}"
            ),
        },
        {
            "label": "Props",
            "value": props_text,
        },
    ]

    pitcher_era = display_stat_value(pitcher_season, "era")
    pitcher_whip = display_stat_value(pitcher_season, "whip")
    pitcher_so = display_stat_value(pitcher_season, "strike_outs")
    if pitcher_era != "--" or pitcher_whip != "--" or pitcher_so != "--":
        rows.append(
            {
                "label": "Pitching",
                "value": f"ERA {pitcher_era} | WHIP {pitcher_whip} | K {pitcher_so}",
            }
        )

    return rows


def outs_to_innings_text(total_outs: Any) -> str:
    outs = max(0, safe_int(total_outs, 0))
    whole = outs // 3
    remainder = outs % 3
    return f"{whole}.{remainder}"


def build_pitcher_last_ten_games_snapshot(player_id: int, season: int, limit: int = 10) -> Optional[Dict[str, Any]]:
    game_log_section = fetch_player_stats_type(player_id, "gameLog", season)
    game_log_payload = game_log_section.get("raw", {}) if isinstance(game_log_section, dict) else {}
    entries = parse_player_game_log_entries(game_log_payload if isinstance(game_log_payload, dict) else {})
    if not entries:
        return None

    pitching_splits: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        by_group = entry.get("byGroup", {}) if isinstance(entry.get("byGroup"), dict) else {}
        pitching = by_group.get("pitching", {}) if isinstance(by_group.get("pitching"), dict) else {}
        if not pitching:
            continue

        innings_value = innings_to_decimal(pitching.get("inningsPitched"))
        outs_recorded = safe_int(pitching.get("outs"), 0)
        batters_faced = safe_int(pitching.get("battersFaced"), 0)
        games_pitched = safe_int(pitching.get("gamesPitched"), 0)
        if innings_value <= 0 and outs_recorded <= 0 and batters_faced <= 0 and games_pitched <= 0:
            continue

        pitching_splits.append(pitching)
        if len(pitching_splits) >= max(1, limit):
            break

    if not pitching_splits:
        return None

    total_outs = 0
    total_earned_runs = 0
    total_hits_allowed = 0
    total_home_runs = 0
    total_walks = 0
    total_hit_batters = 0
    total_strike_outs = 0
    total_wins = 0
    total_losses = 0
    total_batters_faced = 0

    for split in pitching_splits:
        outs_recorded = safe_int(split.get("outs"), 0)
        if outs_recorded <= 0:
            innings_value = innings_to_decimal(split.get("inningsPitched"))
            if innings_value > 0:
                outs_recorded = int(round(innings_value * 3.0))
        total_outs += max(0, outs_recorded)

        total_earned_runs += max(0, safe_int(split.get("earnedRuns"), 0))
        total_hits_allowed += max(0, safe_int(split.get("hits"), 0))
        total_home_runs += max(0, safe_int(split.get("homeRuns"), 0))
        total_walks += max(0, safe_int(split.get("baseOnBalls"), 0))
        total_hit_batters += max(0, safe_int(split.get("hitBatsmen"), 0))
        total_strike_outs += max(0, safe_int(split.get("strikeOuts"), 0))
        total_wins += max(0, safe_int(split.get("wins"), 0))
        total_losses += max(0, safe_int(split.get("losses"), 0))
        total_batters_faced += max(0, safe_int(split.get("battersFaced"), 0))

    if total_batters_faced <= 0:
        total_batters_faced = total_outs + total_hits_allowed + total_walks + total_hit_batters

    innings_pitched_text = outs_to_innings_text(total_outs)

    era = round((total_earned_runs * 27.0) / total_outs, 2) if total_outs > 0 else None
    whip = round(((total_walks + total_hits_allowed) * 3.0) / total_outs, 2) if total_outs > 0 else None
    fip = (
        round(
            (((13.0 * total_home_runs) + (3.0 * (total_walks + total_hit_batters)) - (2.0 * total_strike_outs)) * 3.0)
            / total_outs
            + 3.2,
            2,
        )
        if total_outs > 0
        else None
    )

    return {
        "season": season,
        "games_played": len(pitching_splits),
        "games_pitched": len(pitching_splits),
        "innings_pitched": innings_pitched_text,
        "outs": total_outs,
        "earned_runs": total_earned_runs,
        "hits": total_hits_allowed,
        "home_runs": total_home_runs,
        "walks": total_walks,
        "hit_batsmen": total_hit_batters,
        "strike_outs": total_strike_outs,
        "wins": total_wins,
        "losses": total_losses,
        "batters_faced": total_batters_faced,
        "era": era,
        "whip": whip,
        "fip": fip,
        "k_percent": rate_percent(total_strike_outs, total_batters_faced, precision=1),
        "bb_percent": rate_percent(total_walks, total_batters_faced, precision=1),
        "source": "mlb_game_log_fallback",
    }


def fetch_player_hitting_game_log_rows(player_id: int, season: int, limit: int = 8) -> List[Dict[str, Any]]:
    game_log_section = fetch_player_stats_type(player_id, "gameLog", season)
    game_log_payload = game_log_section.get("raw", {}) if isinstance(game_log_section, dict) else {}
    entries = parse_player_game_log_entries(game_log_payload if isinstance(game_log_payload, dict) else {})
    if not entries:
        return []

    parsed_rows: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        by_group = entry.get("byGroup", {}) if isinstance(entry.get("byGroup"), dict) else {}
        raw_splits = entry.get("rawSplitsByGroup", {}) if isinstance(entry.get("rawSplitsByGroup"), dict) else {}

        hitting = by_group.get("hitting", {}) if isinstance(by_group.get("hitting"), dict) else {}
        pitching = by_group.get("pitching", {}) if isinstance(by_group.get("pitching"), dict) else {}
        fielding = by_group.get("fielding", {}) if isinstance(by_group.get("fielding"), dict) else {}
        running = by_group.get("running", {}) if isinstance(by_group.get("running"), dict) else {}

        position_abbreviation = ""
        for group_key in ("hitting", "fielding", "pitching", "running", "catching"):
            split = raw_splits.get(group_key, {}) if isinstance(raw_splits.get(group_key), dict) else {}
            positions = split.get("positionsPlayed", [])
            if not isinstance(positions, list) or not positions:
                continue
            first_position = positions[0] if isinstance(positions[0], dict) else {}
            position_abbreviation = str(first_position.get("abbreviation") or "").strip()
            if position_abbreviation:
                break

        hitting_summary = str(hitting.get("summary") or "").strip()
        if not hitting_summary:
            hits = safe_int(hitting.get("hits"), 0)
            at_bats = safe_int(hitting.get("atBats"), 0)
            rbi = safe_int(hitting.get("rbi"), 0)
            walks = safe_int(hitting.get("baseOnBalls"), 0)
            hit_by_pitch = safe_int(hitting.get("hitByPitch"), 0)
            strikeouts = safe_int(hitting.get("strikeOuts"), 0)
            stolen_bases = safe_int(running.get("stolenBases"), 0)
            caught_stealing = safe_int(running.get("caughtStealing"), 0)

            had_batting_or_running_activity = any(
                value > 0 for value in [hits, at_bats, rbi, walks, hit_by_pitch, strikeouts, stolen_bases, caught_stealing]
            )
            if had_batting_or_running_activity:
                detail_bits: List[str] = []
                if rbi > 0:
                    detail_bits.append(f"{rbi} RBI")
                if walks > 0:
                    detail_bits.append(f"{walks} BB")
                if hit_by_pitch > 0:
                    detail_bits.append(f"{hit_by_pitch} HBP")
                if strikeouts > 0:
                    detail_bits.append(f"{strikeouts} SO")
                if stolen_bases > 0:
                    detail_bits.append(f"{stolen_bases} SB")
                if caught_stealing > 0:
                    detail_bits.append(f"{caught_stealing} CS")

                hitting_summary = f"{hits}-{at_bats}"
                if detail_bits:
                    hitting_summary = f"{hitting_summary} | {' | '.join(detail_bits)}"

        innings_text = str(pitching.get("inningsPitched") or "").strip()
        pitched = innings_to_decimal(innings_text) > 0
        if not pitched and safe_int(pitching.get("battersFaced"), 0) > 0:
            pitched = True

        pitching_summary = ""
        if pitched:
            strikeouts = safe_int(pitching.get("strikeOuts"), 0)
            earned_runs = safe_int(pitching.get("earnedRuns"), 0)
            hits_allowed = safe_int(pitching.get("hits"), 0)
            walks_allowed = safe_int(pitching.get("baseOnBalls"), 0)

            pitching_bits = [f"IP {innings_text or '0.0'}", f"SO {strikeouts}"]
            if earned_runs > 0:
                pitching_bits.append(f"ER {earned_runs}")
            if hits_allowed > 0:
                pitching_bits.append(f"H {hits_allowed}")
            if walks_allowed > 0:
                pitching_bits.append(f"BB {walks_allowed}")
            pitching_summary = " | ".join(pitching_bits)

        defensive_summary = ""
        put_outs = safe_int(fielding.get("putOuts"), 0)
        assists = safe_int(fielding.get("assists"), 0)
        fielding_chances = safe_int(fielding.get("chances"), 0)
        if fielding_chances > 0 or put_outs > 0 or assists > 0:
            defensive_summary = f"DEF PO {put_outs} | A {assists}"

        summary_parts = [part for part in [hitting_summary, pitching_summary, defensive_summary] if part]
        summary = " | ".join(summary_parts) if summary_parts else "Appeared in game"

        team = entry.get("team", {}) if isinstance(entry.get("team"), dict) else {}
        opponent = entry.get("opponent", {}) if isinstance(entry.get("opponent"), dict) else {}
        parsed_rows.append(
            {
                "game_pk": safe_int(entry.get("gamePk"), 0),
                "official_date": str(entry.get("date") or "").strip(),
                "team_id": safe_int(team.get("id"), 0),
                "team_name": str(team.get("name") or "").strip(),
                "team_logo_urls": team_logo_urls(safe_int(team.get("id"), 0)),
                "opponent_id": safe_int(opponent.get("id"), 0),
                "opponent_name": str(opponent.get("name") or "").strip(),
                "opponent_logo_urls": team_logo_urls(safe_int(opponent.get("id"), 0)),
                "lineup_slot": "-",
                "position_abbreviation": position_abbreviation,
                "batting_summary": summary,
                "home_away": "vs" if bool(entry.get("isHome")) else "@",
                "source": "mlb_game_log",
            }
        )

    parsed_rows.sort(
        key=lambda row: (parse_iso_date(row.get("official_date")) or dt.date.min, safe_int(row.get("game_pk"), 0)),
        reverse=True,
    )
    return parsed_rows[: max(1, limit)]


def get_player_hitting_game_log_rows_cached(player_id: int, season: int, limit: int = 8) -> List[Dict[str, Any]]:
    cache_key = f"{player_id}:{season}:{limit}"
    now = time.time()

    with _player_game_log_fallback_lock:
        cached = _player_game_log_fallback_cache.get(cache_key)
        if cached:
            age_seconds = now - safe_float(cached.get("updated_at"), 0.0)
            if age_seconds < PLAYER_GAME_LOG_FALLBACK_CACHE_TTL_SECONDS:
                return copy.deepcopy(cached.get("rows", []))

    rows = fetch_player_hitting_game_log_rows(player_id, season, limit=limit)

    with _player_game_log_fallback_lock:
        _player_game_log_fallback_cache[cache_key] = {
            "updated_at": now,
            "rows": rows,
        }

    return copy.deepcopy(rows)


def calculate_age_from_birthdate(raw_birth_date: Any) -> Optional[int]:
    birth_date = parse_iso_date(raw_birth_date)
    if not birth_date:
        return None

    today = board_today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def normalize_person_text(raw_value: Any) -> str:
    lowered = str(raw_value or "").lower()
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return " ".join(cleaned.split())


def get_player_display_name(player_id: int, fallback_name: Any = "") -> str:
    fallback_text = str(fallback_name or "").strip()
    if player_id <= 0:
        return fallback_text

    now = time.time()
    with _player_display_name_lock:
        cached = _player_display_name_cache.get(player_id)
        if cached:
            age_seconds = now - safe_float(cached.get("updated_at"), 0.0)
            if age_seconds < PLAYER_DISPLAY_NAME_CACHE_TTL_SECONDS:
                cached_name = str(cached.get("display_name") or "").strip()
                if cached_name:
                    return cached_name

    display_name = fallback_text
    try:
        payload = mlb_get(f"/api/v1/people/{player_id}")
        people = payload.get("people", []) if isinstance(payload, dict) else []
        if isinstance(people, list) and people:
            person = people[0] if isinstance(people[0], dict) else {}
            fetched_name = str(person.get("fullName") or "").strip()
            if fetched_name:
                display_name = fetched_name
    except requests.RequestException:
        pass

    with _player_display_name_lock:
        _player_display_name_cache[player_id] = {
            "updated_at": now,
            "display_name": display_name,
        }

    return display_name or fallback_text


def is_player_name_match(candidate_text: Any, normalized_full_name: str, normalized_last_name: str) -> bool:
    candidate = normalize_person_text(candidate_text)
    if not candidate:
        return False

    if normalized_full_name and normalized_full_name in candidate:
        return True

    candidate_tokens = set(candidate.split(" "))
    if normalized_last_name and normalized_last_name in candidate_tokens:
        return True

    if normalized_full_name and candidate in normalized_full_name and len(candidate) >= 6:
        return True

    return False


def mlb_group_key(stats_row: Dict[str, Any]) -> str:
    group = stats_row.get("group", {}) if isinstance(stats_row, dict) else {}
    display_name = group.get("displayName") or group.get("name") or group.get("abbreviation") or "unknown"
    return normalize_person_text(display_name).replace(" ", "_") or "unknown"


def summarize_stats_payload(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    stats_rows = raw_payload.get("stats", []) if isinstance(raw_payload, dict) else []

    by_group_rows: Dict[str, Any] = {}
    by_group_stats: Dict[str, Any] = {}
    split_count = 0

    for row in stats_rows:
        if not isinstance(row, dict):
            continue

        group_key = mlb_group_key(row)
        by_group_rows[group_key] = copy.deepcopy(row)

        splits = row.get("splits", [])
        if not isinstance(splits, list):
            continue

        split_count += len(splits)
        if len(splits) != 1 or not isinstance(splits[0], dict):
            continue

        stat_blob = splits[0].get("stat")
        if isinstance(stat_blob, dict):
            by_group_stats[group_key] = copy.deepcopy(stat_blob)

    return {
        "groupCount": len(by_group_rows),
        "splitCount": split_count,
        "byGroupRows": by_group_rows,
        "byGroupStats": by_group_stats,
    }


def fetch_player_stats_type(
    player_id: int,
    stats_type: str,
    season: int,
    start_date: Optional[dt.date] = None,
    end_date: Optional[dt.date] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {
        "stats": stats_type,
        "group": PLAYER_STATS_GROUP_QUERY,
        "season": season,
    }
    if start_date and end_date:
        query["startDate"] = start_date.isoformat()
        query["endDate"] = end_date.isoformat()

    section: Dict[str, Any] = {
        "query": copy.deepcopy(query),
        "raw": {},
        "summary": {
            "groupCount": 0,
            "splitCount": 0,
            "byGroupRows": {},
            "byGroupStats": {},
        },
    }

    try:
        payload = mlb_get(f"/api/v1/people/{player_id}/stats", params=query)
    except requests.RequestException as exc:
        section["error"] = str(exc)
        return section

    section["raw"] = payload
    section["summary"] = summarize_stats_payload(payload)
    return section


def empty_stats_section() -> Dict[str, Any]:
    return {
        "query": {},
        "raw": {},
        "summary": {
            "groupCount": 0,
            "splitCount": 0,
            "byGroupRows": {},
            "byGroupStats": {},
        },
    }


def parse_player_game_log_entries(game_log_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    stats_rows = game_log_payload.get("stats", []) if isinstance(game_log_payload, dict) else []
    index: Dict[str, Dict[str, Any]] = {}

    for row in stats_rows:
        if not isinstance(row, dict):
            continue

        group_key = mlb_group_key(row)
        splits = row.get("splits", [])
        if not isinstance(splits, list):
            continue

        for split in splits:
            if not isinstance(split, dict):
                continue

            date_text = str(split.get("date", "")).strip()
            game = split.get("game", {}) if isinstance(split.get("game"), dict) else {}
            game_pk = safe_int(game.get("gamePk"), 0)

            if not date_text and game_pk <= 0:
                continue

            entry_key = f"{date_text}:{game_pk}"
            if entry_key not in index:
                index[entry_key] = {
                    "date": date_text,
                    "gamePk": game_pk,
                    "gameType": split.get("gameType", ""),
                    "isHome": split.get("isHome"),
                    "isWin": split.get("isWin"),
                    "opponent": copy.deepcopy(split.get("opponent", {})),
                    "team": copy.deepcopy(split.get("team", {})),
                    "game": copy.deepcopy(game),
                    "byGroup": {},
                    "rawSplitsByGroup": {},
                }

            entry = index[entry_key]
            entry["byGroup"][group_key] = copy.deepcopy(split.get("stat", {}))
            entry["rawSplitsByGroup"][group_key] = copy.deepcopy(split)

            if not entry.get("opponent") and isinstance(split.get("opponent"), dict):
                entry["opponent"] = copy.deepcopy(split.get("opponent"))
            if not entry.get("team") and isinstance(split.get("team"), dict):
                entry["team"] = copy.deepcopy(split.get("team"))

    entries = list(index.values())
    entries.sort(
        key=lambda row: (parse_iso_date(row.get("date")) or dt.date.min, safe_int(row.get("gamePk"), 0)),
        reverse=True,
    )
    return entries


def player_photo_urls(player_id: int) -> Dict[str, str]:
    base = "https://img.mlbstatic.com/mlb-photos/image/upload"
    return {
        "headshot": f"{base}/w_400,q_auto:best/v1/people/{player_id}/headshot/67/current",
        "headshotHighRes": f"{base}/w_800,q_auto:best/v1/people/{player_id}/headshot/67/current",
    }


def rss_item_text(item_node: ET.Element, tag_name: str) -> str:
    for child in list(item_node):
        child_tag = str(child.tag).split("}")[-1]
        if child_tag == tag_name:
            return str(child.text or "").strip()
    return ""


def fetch_player_news_headlines(player_name: str, team_name: str, max_items: int) -> Dict[str, Any]:
    query_bits = [f'"{player_name}"', "MLB"]
    if team_name:
        query_bits.append(team_name)

    query = " ".join(bit for bit in query_bits if bit).strip()
    payload = {
        "available": False,
        "source": "Google News RSS",
        "query": query,
        "headlines": [],
    }

    try:
        response = requests.get(
            GOOGLE_NEWS_RSS_URL,
            params={
                "q": query,
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": "PadresPiBoard/1.0"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        payload["error"] = str(exc)
        return payload

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        payload["error"] = f"Unable to parse news feed: {exc}"
        return payload

    items = root.findall(".//item")
    headlines: List[Dict[str, Any]] = []
    for item in items:
        title_text = html.unescape(rss_item_text(item, "title"))
        link_text = rss_item_text(item, "link")
        published_text = rss_item_text(item, "pubDate")

        source_name = ""
        source_url = ""
        for child in list(item):
            child_tag = str(child.tag).split("}")[-1]
            if child_tag != "source":
                continue
            source_name = str(child.text or "").strip()
            source_url = str(child.attrib.get("url", "")).strip()
            break

        if not title_text and not link_text:
            continue

        headlines.append(
            {
                "title": title_text,
                "url": link_text,
                "publishedAt": published_text,
                "source": source_name,
                "sourceUrl": source_url,
            }
        )

        if len(headlines) >= max(1, max_items):
            break

    payload["available"] = bool(headlines)
    payload["headlines"] = headlines
    return payload


def build_player_highlights(player_name: str, game_entries: List[Dict[str, Any]], limit: int = 24) -> List[Dict[str, Any]]:
    if not game_entries:
        return []

    clips: List[Dict[str, Any]] = []
    seen_urls = set()

    for entry in game_entries[:20]:
        game_pk = safe_int(entry.get("gamePk"), 0)
        if game_pk <= 0:
            continue

        game_highlights = get_game_highlights(game_pk, limit=10)
        related = select_highlights_for_player(player_name, game_highlights, limit=4)

        for clip in related:
            clip_url = clip.get("url")
            if not clip_url or clip_url in seen_urls:
                continue

            seen_urls.add(clip_url)
            row = dict(clip)
            row["gameDate"] = entry.get("date", "")
            clips.append(row)

            if len(clips) >= max(1, limit):
                return clips

    return clips


PLAYER_ODDS_MARKET_ALIASES = {
    "batter_hits": "hits",
    "hits": "hits",
    "batter_home_runs": "home_runs",
    "home_runs": "home_runs",
    "batter_total_bases": "total_bases",
    "total_bases": "total_bases",
    "pitcher_strikeouts": "strikeouts",
    "strikeouts": "strikeouts",
    "pitcher_outs": "outs_recorded",
    "outs": "outs_recorded",
    "outs_recorded": "outs_recorded",
    "runs": "runs",
    "rbis": "rbis",
    "runs_hits_rbis": "runs_hits_rbis",
    "stolen_bases": "stolen_bases",
    "hits_allowed": "hits_allowed",
}

PLAYER_ODDS_MARKET_STORAGE_KEYS = {
    "hits": "batter_hits",
    "home_runs": "batter_home_runs",
    "total_bases": "batter_total_bases",
    "strikeouts": "pitcher_strikeouts",
    "outs_recorded": "pitcher_outs",
    "runs": "batter_runs",
    "rbis": "batter_rbis",
    "runs_hits_rbis": "batter_runs_hits_rbis",
    "stolen_bases": "batter_stolen_bases",
    "hits_allowed": "pitcher_hits_allowed",
}


def normalize_player_odds_market_token(raw_value: Any) -> str:
    token = str(raw_value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return PLAYER_ODDS_MARKET_ALIASES.get(token, token)


def player_odds_market_storage_key(canonical_market_key: str) -> str:
    return PLAYER_ODDS_MARKET_STORAGE_KEYS.get(canonical_market_key, canonical_market_key)


def bettingpros_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.bettingpros.com",
        "Referer": "https://www.bettingpros.com/",
        "User-Agent": "PadresPiBoard/1.0",
    }
    if BETTINGPROS_API_KEY:
        headers["x-api-key"] = BETTINGPROS_API_KEY
    return headers


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

    return text


def bettingpros_event_team_name(event: Dict[str, Any], abbreviation: str) -> str:
    target = str(abbreviation or "").strip().upper()
    participants = event.get("participants") if isinstance(event.get("participants"), list) else []
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        team = participant.get("team") if isinstance(participant.get("team"), dict) else {}
        team_abbreviation = str(team.get("abbreviation") or "").strip().upper()
        if team_abbreviation != target:
            continue

        city = str(team.get("city") or "").strip()
        nickname = str(participant.get("name") or "").strip()
        combined = f"{city} {nickname}".strip()
        if combined:
            return combined
    return target


def parse_american_odds(raw_value: Any) -> Optional[int]:
    text = str(raw_value or "").strip().upper()
    if not text:
        return None
    if text == "EVEN":
        return 100
    return safe_int(text, 0) if text not in {"", "-"} else None


def fetch_player_prop_odds(player_name: str) -> Dict[str, Any]:
    markets_requested = [token.strip() for token in BETTING_ODDS_MARKETS.split(",") if token.strip()]
    requested_market_keys = {
        normalize_player_odds_market_token(token)
        for token in markets_requested
        if normalize_player_odds_market_token(token)
    }

    payload: Dict[str, Any] = {
        "available": False,
        "source": "BettingPros",
        "marketsRequested": markets_requested,
        "results": [],
    }

    normalized_full_name = normalize_person_text(player_name)
    if not normalized_full_name:
        payload["reason"] = "Player name is empty."
        return payload

    normalized_last_name = normalized_full_name.split(" ")[-1] if normalized_full_name else ""

    date_values = [(board_today() + dt.timedelta(days=offset)).isoformat() for offset in range(BETTING_ODDS_DAYS_AHEAD + 1)]
    event_map: Dict[str, Dict[str, Any]] = {}
    props: List[Dict[str, Any]] = []

    try:
        for event_date in date_values:
            events_response = requests.get(
                f"{BETTINGPROS_BASE_URL}/events",
                params={
                    "sport": "MLB",
                    "date": event_date,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers=bettingpros_headers(),
            )
            events_response.raise_for_status()
            events_payload = events_response.json()
            if not isinstance(events_payload, dict):
                raise ValueError(f"Unexpected BettingPros events payload type: {type(events_payload)!r}")

            for event in events_payload.get("events", []):
                if not isinstance(event, dict):
                    continue

                event_id = str(event.get("id") or "").strip()
                if not event_id:
                    continue

                home_abbreviation = str(event.get("home") or "").strip()
                away_abbreviation = str(event.get("visitor") or "").strip()
                home_team = bettingpros_event_team_name(event, home_abbreviation)
                away_team = bettingpros_event_team_name(event, away_abbreviation)

                event_map[event_id] = {
                    "eventId": event_id,
                    "homeTeam": home_team,
                    "awayTeam": away_team,
                    "eventName": f"{away_team} @ {home_team}".strip(),
                    "commenceTime": bettingpros_parse_scheduled_to_iso(event.get("scheduled")),
                }

            props_response = requests.get(
                f"{BETTINGPROS_BASE_URL}/props",
                params={
                    "sport": "MLB",
                    "date": event_date,
                    "location": BETTINGPROS_LOCATION,
                    "book_id": BETTINGPROS_BOOK_ID,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers=bettingpros_headers(),
            )
            props_response.raise_for_status()
            props_payload = props_response.json()
            if not isinstance(props_payload, dict):
                raise ValueError(f"Unexpected BettingPros props payload type: {type(props_payload)!r}")

            for row in props_payload.get("props", []):
                if isinstance(row, dict):
                    props.append(row)
    except requests.RequestException as exc:
        payload["error"] = str(exc)
        return payload
    except ValueError as exc:
        payload["error"] = str(exc)
        return payload

    matches: List[Dict[str, Any]] = []

    for prop in props:
        participant = prop.get("participant") if isinstance(prop.get("participant"), dict) else {}
        participant_name = str(participant.get("name") or "").strip()
        if not is_player_name_match(participant_name, normalized_full_name, normalized_last_name):
            continue

        links = prop.get("links") if isinstance(prop.get("links"), dict) else {}
        odds_link = str(links.get("odds") or "").strip()
        odds_link_tokens = odds_link.strip("/").split("/")
        market_slug = odds_link_tokens[-1] if odds_link_tokens else ""
        market_key_canonical = normalize_player_odds_market_token(market_slug)
        if market_key_canonical not in requested_market_keys:
            continue

        market_key = player_odds_market_storage_key(market_key_canonical)

        event_id = str(prop.get("event_id") or "").strip()
        event_info = event_map.get(event_id, {})
        event_name = str(event_info.get("eventName") or event_id or "MLB Event")
        commence_time = str(event_info.get("commenceTime") or "")

        for side_name in ("over", "under"):
            side = prop.get(side_name)
            if not isinstance(side, dict):
                continue

            line_value = side.get("line")
            if line_value is None:
                line_value = side.get("consensus_line")

            odds_value = parse_american_odds(side.get("odds"))
            if odds_value is None:
                odds_value = parse_american_odds(side.get("consensus_odds"))

            bookmaker_raw = str(side.get("book") or "").strip()
            if bookmaker_raw in {"", "0"}:
                bookmaker_key = "consensus"
                bookmaker_title = "Consensus"
            else:
                bookmaker_key = f"book_{bookmaker_raw}"
                bookmaker_title = f"Book {bookmaker_raw}"

            outcome = {
                "name": side_name.title(),
                "description": participant_name,
                "point": line_value,
                "price": odds_value,
            }

            matches.append(
                {
                    "eventId": event_id,
                    "eventName": event_name,
                    "commenceTime": commence_time,
                    "bookmakerKey": bookmaker_key,
                    "bookmakerTitle": bookmaker_title,
                    "marketKey": market_key,
                    "marketLastUpdate": utc_now_iso(),
                    "outcome": outcome,
                }
            )

            if len(matches) >= 250:
                break

        if len(matches) >= 250:
            break

    payload["available"] = bool(matches)
    payload["eventCountScanned"] = len(event_map)
    payload["propsScanned"] = len(props)
    payload["results"] = matches
    return payload


def bettingpros_matches_to_player_odds_rows(matches: Any) -> List[Dict[str, Any]]:
    if not isinstance(matches, list):
        return []

    rows: List[Dict[str, Any]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue

        outcome = match.get("outcome") if isinstance(match.get("outcome"), dict) else {}
        selection_name = str(outcome.get("name") or "").strip().title()
        market_key = str(match.get("marketKey") or "").strip()
        if not selection_name or not market_key:
            continue

        rows.append(
            {
                "game_pk": safe_int(match.get("gamePk"), 0),
                "market_key": market_key,
                "selection_name": selection_name,
                "line": outcome.get("point"),
                "odds_price": outcome.get("price"),
                "bookmaker_key": match.get("bookmakerKey"),
                "bookmaker_title": match.get("bookmakerTitle"),
                "commence_time": match.get("commenceTime"),
                "event_name": match.get("eventName"),
                "market_last_update": match.get("marketLastUpdate"),
                "source": "bettingpros_live_fallback",
            }
        )

    return rows


def get_live_player_prop_odds_rows_cached(player_name: str) -> List[Dict[str, Any]]:
    cache_key = normalize_person_text(player_name)
    if not cache_key:
        return []

    now = time.time()
    with _player_props_fallback_lock:
        cached = _player_props_fallback_cache.get(cache_key)
        if cached:
            age_seconds = now - safe_float(cached.get("updated_at"), 0.0)
            if age_seconds < PLAYER_PROPS_FALLBACK_CACHE_TTL_SECONDS:
                return copy.deepcopy(cached.get("rows", []))

    payload = fetch_player_prop_odds(player_name)
    rows = bettingpros_matches_to_player_odds_rows(payload.get("results"))

    with _player_props_fallback_lock:
        _player_props_fallback_cache[cache_key] = {
            "updated_at": now,
            "rows": rows,
        }

    return copy.deepcopy(rows)


def get_today_games(team_id: int) -> List[Dict[str, Any]]:
    today = board_today().isoformat()
    payload = mlb_get(
        "/api/v1/schedule",
        params={
            "sportId": 1,
            "teamId": team_id,
            "date": today,
            "hydrate": "linescore",
        },
    )
    dates = payload.get("dates", [])
    if not dates:
        return []
    return dates[0].get("games", [])


def get_recent_games(team_id: int, lookback_days: int) -> List[Dict[str, Any]]:
    end_date = board_today()
    start_date = end_date - dt.timedelta(days=lookback_days)

    payload = mlb_get(
        "/api/v1/schedule",
        params={
            "sportId": 1,
            "teamId": team_id,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        },
    )

    rows: List[Dict[str, Any]] = []
    for date_entry in payload.get("dates", []):
        for game in date_entry.get("games", []):
            status = game.get("status", {})
            teams = game.get("teams", {})
            away_name = teams.get("away", {}).get("team", {}).get("name", "Away")
            home_name = teams.get("home", {}).get("team", {}).get("name", "Home")
            rows.append(
                {
                    "gamePk": safe_int(game.get("gamePk")),
                    "gameDate": game.get("gameDate", ""),
                    "officialDate": game.get("officialDate", ""),
                    "abstractState": status.get("abstractGameState", ""),
                    "detailedState": status.get("detailedState", ""),
                    "awayName": away_name,
                    "homeName": home_name,
                }
            )

    return sorted(rows, key=lambda row: row["gameDate"], reverse=True)


def normalize_league_record(raw_record: Any) -> Dict[str, Any]:
    if not isinstance(raw_record, dict):
        return {}

    wins = safe_int(raw_record.get("wins"), 0)
    losses = safe_int(raw_record.get("losses"), 0)
    pct = str(raw_record.get("pct") or "").strip()
    total_games = wins + losses
    if not pct and total_games > 0:
        pct = f"{wins / total_games:.3f}".lstrip("0")

    return {
        "wins": wins,
        "losses": losses,
        "pct": pct,
    }


def normalize_person_reference(raw_person: Any) -> Dict[str, Any]:
    if not isinstance(raw_person, dict):
        return {}

    person_id = safe_int(raw_person.get("id"), 0)
    full_name = str(raw_person.get("fullName") or raw_person.get("name") or "").strip()
    link = str(raw_person.get("link") or "").strip()
    if person_id <= 0 and not full_name and not link:
        return {}

    payload = {
        "id": person_id,
        "fullName": full_name,
        "name": full_name,
        "link": link,
    }
    if person_id > 0:
        payload["photoUrls"] = player_photo_urls(person_id)
    return payload


def empty_batting_order_spot(slot: int) -> Dict[str, Any]:
    slot_number = max(1, safe_int(slot, 1))
    return {
        "slot": slot_number,
        "player_id": 0,
        "id": 0,
        "full_name": "",
        "fullName": "",
        "name": "",
        "link": "",
        "position_abbreviation": "",
        "position_name": "",
        "batting_summary": "",
        "season": 0,
        "seasonStatsAvailable": False,
        "season_stats_available": False,
        "seasonAvg": "",
        "season_avg": "",
        "seasonObp": "",
        "season_obp": "",
        "seasonSlg": "",
        "season_slg": "",
        "seasonOps": "",
        "season_ops": "",
        "seasonHomeRuns": "",
        "season_home_runs": "",
        "seasonRbi": "",
        "season_rbi": "",
        "seasonHits": "",
        "season_hits": "",
        "seasonAtBats": "",
        "season_at_bats": "",
        "seasonGamesPlayed": "",
        "season_games_played": "",
        "seasonPlateAppearances": "",
        "season_plate_appearances": "",
        "seasonLine": "",
        "season_line": "",
        "seasonStats": {},
        "season_stats": {},
        "photoUrls": {},
        "confirmed": False,
    }


def build_batting_order_spot_map(players: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    spot_map: Dict[str, Dict[str, Any]] = {
        f"spot_{slot}": empty_batting_order_spot(slot)
        for slot in range(1, 10)
    }

    for player in players:
        slot = safe_int(player.get("slot"), 0)
        if slot < 1 or slot > 9:
            continue

        player_id = safe_int(player.get("playerId"), 0)
        person = player.get("person") if isinstance(player.get("person"), dict) else {}
        position = player.get("position") if isinstance(player.get("position"), dict) else {}
        photo_urls = person.get("photoUrls") if isinstance(person.get("photoUrls"), dict) else {}
        season_stats = player.get("seasonStats") if isinstance(player.get("seasonStats"), dict) else {}
        if not season_stats and isinstance(player.get("season_stats"), dict):
            season_stats = player.get("season_stats")
        season_line = str(player.get("seasonLine") or player.get("season_line") or "").strip()

        full_name = str(person.get("fullName") or person.get("name") or player.get("name") or "").strip()

        spot_map[f"spot_{slot}"] = {
            "slot": slot,
            "player_id": player_id,
            "id": player_id,
            "full_name": full_name,
            "fullName": full_name,
            "name": full_name,
            "link": str(person.get("link") or "").strip(),
            "position_abbreviation": str(position.get("abbreviation") or "").strip(),
            "position_name": str(position.get("name") or "").strip(),
            "batting_summary": str(player.get("battingSummary") or "").strip(),
            "seasonLine": season_line,
            "season_line": season_line,
            "seasonStats": copy.deepcopy(season_stats),
            "season_stats": copy.deepcopy(season_stats),
            "photoUrls": copy.deepcopy(photo_urls),
            "confirmed": bool(full_name or player_id > 0),
        }

    return spot_map


def empty_batting_order_payload() -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "confirmed": False,
        "count": 0,
        "playerIds": [],
        "players": [],
    }
    payload.update(build_batting_order_spot_map([]))
    return payload


def serialize_schedule_game(game: Dict[str, Any], team_id: int) -> Dict[str, Any]:
    status = game.get("status", {})
    teams = game.get("teams", {})
    away_team_block = teams.get("away", {}) if isinstance(teams.get("away"), dict) else {}
    home_team_block = teams.get("home", {}) if isinstance(teams.get("home"), dict) else {}

    away_team = away_team_block.get("team", {}) if isinstance(away_team_block.get("team"), dict) else {}
    home_team = home_team_block.get("team", {}) if isinstance(home_team_block.get("team"), dict) else {}
    game_number = safe_int(game.get("gameNumber"), 0)
    double_header_flag = str(game.get("doubleHeader", "N") or "N").strip().upper()

    away_id = safe_int(away_team.get("id"), 0)
    home_id = safe_int(home_team.get("id"), 0)
    away_abbreviation = str(away_team.get("abbreviation") or fallback_team_abbreviation(away_team.get("name"))).strip().upper()
    home_abbreviation = str(home_team.get("abbreviation") or fallback_team_abbreviation(home_team.get("name"))).strip().upper()

    away_record = normalize_league_record(away_team_block.get("leagueRecord"))
    home_record = normalize_league_record(home_team_block.get("leagueRecord"))
    away_probable = normalize_person_reference(away_team_block.get("probablePitcher"))
    home_probable = normalize_person_reference(home_team_block.get("probablePitcher"))
    status_abstract = str(status.get("abstractGameState") or "").strip()
    status_detailed = str(status.get("detailedState") or "").strip()

    is_team_home = home_id == team_id
    opponent = away_team if is_team_home else home_team
    opponent_id = safe_int(opponent.get("id"), 0)

    linescore = game.get("linescore", {}) if isinstance(game.get("linescore"), dict) else {}
    line_teams = linescore.get("teams", {}) if isinstance(linescore.get("teams"), dict) else {}
    away_line = line_teams.get("away", {}) if isinstance(line_teams.get("away"), dict) else {}
    home_line = line_teams.get("home", {}) if isinstance(line_teams.get("home"), dict) else {}

    away_runs = safe_int(away_line.get("runs"), 0)
    away_hits = safe_int(away_line.get("hits"), 0)
    away_errors = safe_int(away_line.get("errors"), 0)
    home_runs = safe_int(home_line.get("runs"), 0)
    home_hits = safe_int(home_line.get("hits"), 0)
    home_errors = safe_int(home_line.get("errors"), 0)

    default_batting_order = empty_batting_order_payload()

    away_payload = {
        "id": away_id,
        "name": away_team.get("name", "Away"),
        "abbreviation": away_abbreviation,
        "runs": away_runs,
        "hits": away_hits,
        "errors": away_errors,
        "logoUrls": team_logo_urls(away_id),
        "theme": team_theme_colors(away_id),
        "record": away_record,
        "probablePitcher": away_probable,
        "battingOrder": copy.deepcopy(default_batting_order),
    }

    home_payload = {
        "id": home_id,
        "name": home_team.get("name", "Home"),
        "abbreviation": home_abbreviation,
        "runs": home_runs,
        "hits": home_hits,
        "errors": home_errors,
        "logoUrls": team_logo_urls(home_id),
        "theme": team_theme_colors(home_id),
        "record": home_record,
        "probablePitcher": home_probable,
        "battingOrder": copy.deepcopy(default_batting_order),
    }

    team_payload = home_payload if is_team_home else away_payload
    opponent_payload = away_payload if is_team_home else home_payload

    score_payload = {
        "available": True,
        "isLive": status_abstract == "Live",
        "status": {
            "abstract": status_abstract,
            "detailed": status_detailed,
        },
        "away": {
            "id": away_id,
            "name": away_payload.get("name", "Away"),
            "abbreviation": away_abbreviation,
            "runs": away_runs,
            "hits": away_hits,
            "errors": away_errors,
        },
        "home": {
            "id": home_id,
            "name": home_payload.get("name", "Home"),
            "abbreviation": home_abbreviation,
            "runs": home_runs,
            "hits": home_hits,
            "errors": home_errors,
        },
        "inning": {
            "state": str(linescore.get("inningState") or "").strip(),
            "half": str(linescore.get("inningHalf") or "").strip(),
            "number": safe_int(linescore.get("currentInning"), 0),
        },
        "count": {
            "balls": safe_int(linescore.get("balls"), 0),
            "strikes": safe_int(linescore.get("strikes"), 0),
            "outs": safe_int(linescore.get("outs"), 0),
        },
    }

    return {
        "gamePk": safe_int(game.get("gamePk"), 0),
        "gameDate": game.get("gameDate", ""),
        "officialDate": game.get("officialDate", ""),
        "dayNight": str(game.get("dayNight", "")),
        "gameNumber": game_number,
        "doubleHeader": double_header_flag,
        "isDoubleHeader": double_header_flag == "Y",
        "status": {
            "abstract": status_abstract,
            "detailed": status_detailed,
        },
        "homeAway": "Home" if is_team_home else "Away",
        "matchup": f"{away_team.get('name', 'Away')} at {home_team.get('name', 'Home')}",
        "venue": game.get("venue", {}).get("name", ""),
        "venueId": safe_int(game.get("venue", {}).get("id"), 0),
        "score": score_payload,
        "scoreboard": copy.deepcopy(score_payload),
        "away": away_payload,
        "home": home_payload,
        "team": team_payload,
        "opponent": {
            "id": opponent_id,
            "name": opponent.get("name", "Opponent"),
            "abbreviation": str(opponent.get("abbreviation") or fallback_team_abbreviation(opponent.get("name"))).strip().upper(),
            "logoUrls": team_logo_urls(opponent_id),
            "theme": team_theme_colors(opponent_id),
            "record": opponent_payload.get("record", {}),
            "probablePitcher": opponent_payload.get("probablePitcher", {}),
            "runs": safe_int(opponent_payload.get("runs"), 0),
            "hits": safe_int(opponent_payload.get("hits"), 0),
            "errors": safe_int(opponent_payload.get("errors"), 0),
            "battingOrder": copy.deepcopy(opponent_payload.get("battingOrder", default_batting_order)),
        },
        "startingPitchers": {
            "away": away_probable,
            "home": home_probable,
            "team": team_payload.get("probablePitcher", {}),
            "opponent": opponent_payload.get("probablePitcher", {}),
        },
        "teamRecord": team_payload.get("record", {}),
        "opponentRecord": opponent_payload.get("record", {}),
    }


def get_team_games_for_date(team_id: int, game_date: dt.date) -> List[Dict[str, Any]]:
    payload = mlb_get(
        "/api/v1/schedule",
        params={
            "sportId": 1,
            "teamId": team_id,
            "date": game_date.isoformat(),
            "hydrate": "linescore,team,probablePitcher",
        },
    )

    games: List[Dict[str, Any]] = []
    for date_entry in payload.get("dates", []):
        for game in date_entry.get("games", []):
            games.append(serialize_schedule_game(game, team_id))

    return sorted(
        games,
        key=lambda row: (
            row.get("gameDate", ""),
            safe_int(row.get("gameNumber"), 0),
        ),
    )


def build_batting_order_payload(players: List[Dict[str, Any]], player_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    normalized_players: List[Dict[str, Any]] = []
    seen_slots = set()

    for player in players:
        if not isinstance(player, dict):
            continue

        slot = safe_int(player.get("slot"), 0)
        if slot < 1 or slot > 9 or slot in seen_slots:
            continue

        seen_slots.add(slot)
        normalized_players.append(player)

    normalized_players = sorted(normalized_players, key=lambda row: safe_int(row.get("slot"), 99))

    ids_source = player_ids if isinstance(player_ids, list) and player_ids else [row.get("playerId") for row in normalized_players]
    normalized_player_ids = [safe_int(value, 0) for value in ids_source if safe_int(value, 0) > 0]

    payload: Dict[str, Any] = {
        "confirmed": bool(normalized_players),
        "count": len(normalized_players),
        "playerIds": normalized_player_ids,
        "players": normalized_players,
    }

    payload.update(build_batting_order_spot_map(normalized_players))
    return payload


def serialize_batting_order(team_boxscore: Any) -> Dict[str, Any]:
    team_block = team_boxscore if isinstance(team_boxscore, dict) else {}
    order_source = team_block.get("battingOrder") if isinstance(team_block.get("battingOrder"), list) else []
    players_source = team_block.get("players") if isinstance(team_block.get("players"), dict) else {}

    player_ids: List[int] = []
    players: List[Dict[str, Any]] = []

    for index, raw_player_id in enumerate(order_source):
        player_id = safe_int(raw_player_id, 0)
        if player_id <= 0:
            continue

        player_ids.append(player_id)
        player_row = players_source.get(f"ID{player_id}", {}) if isinstance(players_source, dict) else {}
        person = normalize_person_reference(player_row.get("person"))
        position = player_row.get("position") if isinstance(player_row.get("position"), dict) else {}
        stats_blob = player_row.get("stats") if isinstance(player_row.get("stats"), dict) else {}
        batting = stats_blob.get("batting") if isinstance(stats_blob.get("batting"), dict) else {}
        full_name = str(person.get("fullName") or person.get("name") or "").strip()

        players.append(
            {
                "slot": index + 1,
                "playerId": player_id,
                "name": full_name,
                "fullName": full_name,
                "full_name": full_name,
                "person": person,
                "position": {
                    "abbreviation": str(position.get("abbreviation") or "").strip(),
                    "name": str(position.get("name") or "").strip(),
                },
                "battingSummary": str(batting.get("summary") or "").strip(),
            }
        )

    return build_batting_order_payload(players, player_ids)


def parse_lineup_slot_number(raw_value: Any) -> int:
    text = str(raw_value or "").strip()
    if not text or text in {"-", "--", "N/A", "n/a"}:
        return 0

    try:
        return int(text)
    except ValueError:
        pass

    try:
        return int(float(text))
    except ValueError:
        pass

    match = re.search(r"\d+", text)
    if not match:
        return 0
    return safe_int(match.group(0), 0)


def serialize_batting_order_from_db_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    players: List[Dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        if parse_bool_value(row.get("is_substitute"), False):
            continue

        slot = parse_lineup_slot_number(row.get("lineup_slot"))
        if slot < 1 or slot > 9:
            continue

        player_id = safe_int(row.get("player_id"), 0)
        player_name = str(row.get("player_name") or "").strip()

        person_source: Dict[str, Any] = {}
        if player_id > 0:
            person_source["id"] = player_id
        if player_name:
            person_source["fullName"] = player_name

        person = normalize_person_reference(person_source) if person_source else {}

        players.append(
            {
                "slot": slot,
                "playerId": player_id,
                "name": player_name,
                "fullName": player_name,
                "full_name": player_name,
                "person": person,
                "position": {
                    "abbreviation": str(row.get("position_abbreviation") or "").strip(),
                    "name": str(row.get("position_name") or "").strip(),
                },
                "battingSummary": str(row.get("batting_summary") or "").strip(),
            }
        )

    return build_batting_order_payload(players)


def load_batting_order_rows_by_game_pk(game_pks: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    unique_ids = sorted({safe_int(game_pk, 0) for game_pk in game_pks if safe_int(game_pk, 0) > 0})
    if not unique_ids:
        return {}

    database_path = resolve_database_path()
    if not database_path.exists():
        return {}

    try:
        with open_database_connection() as connection:
            tables = sqlite_table_names(connection)
            if "batting_orders" not in tables:
                return {}

            placeholders = ",".join("?" for _ in unique_ids)
            rows = rows_to_dicts(
                connection.execute(
                    f"""
                    SELECT
                        game_pk,
                        team_id,
                        lineup_slot,
                        player_id,
                        player_name,
                        position_abbreviation,
                        position_name,
                        batting_summary,
                        is_substitute
                    FROM batting_orders
                    WHERE game_pk IN ({placeholders})
                    ORDER BY game_pk,
                             team_id,
                             COALESCE(CAST(lineup_slot AS INTEGER), 99),
                             COALESCE(lineup_slot, '')
                    """,
                    tuple(unique_ids),
                ).fetchall()
            )
    except sqlite3.Error:
        return {}

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        game_pk = safe_int(row.get("game_pk"), 0)
        if game_pk <= 0:
            continue
        grouped.setdefault(game_pk, []).append(row)

    return grouped


def pick_preferred_batting_order(
    db_order: Optional[Dict[str, Any]],
    live_order: Optional[Dict[str, Any]],
    default_order: Dict[str, Any],
) -> Dict[str, Any]:
    def has_players(order: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(order, dict):
            return False
        return bool(order.get("confirmed")) or safe_int(order.get("count"), 0) > 0

    if has_players(db_order):
        return copy.deepcopy(db_order)
    if has_players(live_order):
        return copy.deepcopy(live_order)
    return copy.deepcopy(default_order)


def first_present_stat_value(stat_row: Optional[Dict[str, Any]], keys: Iterable[str], fallback: str = "--") -> str:
    if not isinstance(stat_row, dict):
        return fallback

    for key in keys:
        key_text = str(key or "").strip()
        if not key_text:
            continue
        value_text = display_value(format_decimal_stat_value(key_text, stat_row.get(key_text)), "")
        if value_text:
            return value_text

    return fallback


def build_lineup_batter_season_stats_payload(stat_row: Optional[Dict[str, Any]], season: int) -> Dict[str, Any]:
    season_value = safe_int(stat_row.get("season"), season) if isinstance(stat_row, dict) else season

    avg_value = first_present_stat_value(stat_row, ["avg"])
    obp_value = first_present_stat_value(stat_row, ["obp"])
    slg_value = first_present_stat_value(stat_row, ["slg"])
    ops_value = first_present_stat_value(stat_row, ["ops"])
    home_runs_value = first_present_stat_value(stat_row, ["home_runs", "homeRuns"])
    rbi_value = first_present_stat_value(stat_row, ["rbi"])
    hits_value = first_present_stat_value(stat_row, ["hits"])
    at_bats_value = first_present_stat_value(stat_row, ["at_bats", "atBats"])
    games_played_value = first_present_stat_value(stat_row, ["games_played", "gamesPlayed"])
    plate_appearances_value = first_present_stat_value(stat_row, ["plate_appearances", "plateAppearances"])

    summary_available = any(value != "--" for value in (avg_value, ops_value, home_runs_value, rbi_value))
    summary_line = ""
    if summary_available:
        summary_line = (
            f"AVG {avg_value} | "
            f"OBP {obp_value} | "
            f"OPS {ops_value} | "
            f"HR {home_runs_value} | "
            f"RBI {rbi_value}"
        )

    return {
        "available": summary_available,
        "season": season_value,
        "gamesPlayed": games_played_value,
        "games_played": games_played_value,
        "plateAppearances": plate_appearances_value,
        "plate_appearances": plate_appearances_value,
        "atBats": at_bats_value,
        "at_bats": at_bats_value,
        "hits": hits_value,
        "avg": avg_value,
        "obp": obp_value,
        "slg": slg_value,
        "ops": ops_value,
        "homeRuns": home_runs_value,
        "home_runs": home_runs_value,
        "rbi": rbi_value,
        "line": summary_line,
    }


def load_lineup_batter_season_stats_by_player_ids(player_ids: List[int], season: int) -> Dict[int, Dict[str, Any]]:
    unique_ids = sorted({safe_int(player_id, 0) for player_id in player_ids if safe_int(player_id, 0) > 0})
    if not unique_ids:
        return {}

    stats_rows_by_player: Dict[int, Dict[str, Any]] = {}
    database_path = resolve_database_path()

    if database_path.exists():
        try:
            with open_database_connection() as connection:
                tables = sqlite_table_names(connection)
                if "batter_stats_season" in tables:
                    placeholders = ",".join("?" for _ in unique_ids)
                    rows_for_season = rows_to_dicts(
                        connection.execute(
                            f"""
                            SELECT *
                            FROM batter_stats_season
                            WHERE player_id IN ({placeholders})
                              AND season = ?
                            ORDER BY player_id ASC,
                                     COALESCE(games_played, 0) DESC
                            """,
                            tuple(unique_ids) + (season,),
                        ).fetchall()
                    )

                    for row in rows_for_season:
                        player_id = safe_int(row.get("player_id"), 0)
                        if player_id > 0 and player_id not in stats_rows_by_player:
                            stats_rows_by_player[player_id] = row

                    missing_ids = [player_id for player_id in unique_ids if player_id not in stats_rows_by_player]
                    if missing_ids:
                        missing_placeholders = ",".join("?" for _ in missing_ids)
                        fallback_rows = rows_to_dicts(
                            connection.execute(
                                f"""
                                SELECT *
                                FROM batter_stats_season
                                WHERE player_id IN ({missing_placeholders})
                                ORDER BY player_id ASC,
                                         season DESC,
                                         COALESCE(games_played, 0) DESC
                                """,
                                tuple(missing_ids),
                            ).fetchall()
                        )

                        for row in fallback_rows:
                            player_id = safe_int(row.get("player_id"), 0)
                            if player_id > 0 and player_id not in stats_rows_by_player:
                                stats_rows_by_player[player_id] = row
        except sqlite3.Error:
            stats_rows_by_player = {}

    unresolved_ids = [player_id for player_id in unique_ids if player_id not in stats_rows_by_player]
    if unresolved_ids:
        people_by_id = fetch_people_with_stats(unresolved_ids, season)
        for player_id in unresolved_ids:
            person = people_by_id.get(player_id) if isinstance(people_by_id.get(player_id), dict) else {}
            hitting = extract_group_stat(person, "hitting") if isinstance(person, dict) else {}
            if not isinstance(hitting, dict) or not hitting:
                continue

            stats_rows_by_player[player_id] = {
                "player_id": player_id,
                "season": season,
                "games_played": hitting.get("gamesPlayed"),
                "plate_appearances": hitting.get("plateAppearances"),
                "at_bats": hitting.get("atBats"),
                "hits": hitting.get("hits"),
                "home_runs": hitting.get("homeRuns"),
                "rbi": hitting.get("rbi"),
                "avg": hitting.get("avg"),
                "obp": hitting.get("obp"),
                "slg": hitting.get("slg"),
                "ops": hitting.get("ops"),
            }

    stats_payload_by_player: Dict[int, Dict[str, Any]] = {}
    for player_id in unique_ids:
        stats_payload_by_player[player_id] = build_lineup_batter_season_stats_payload(
            stats_rows_by_player.get(player_id),
            season,
        )

    return stats_payload_by_player


def attach_batter_season_stats(
    target: Optional[Dict[str, Any]],
    stats_payload: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(target, dict):
        return

    stats = copy.deepcopy(stats_payload) if isinstance(stats_payload, dict) else {}
    season_line = str(stats.get("line") or "").strip()

    target["seasonStats"] = copy.deepcopy(stats)
    target["season_stats"] = copy.deepcopy(stats)
    target["seasonLine"] = season_line
    target["season_line"] = season_line

    season_avg = str(stats.get("avg") or "").strip()
    season_obp = str(stats.get("obp") or "").strip()
    season_slg = str(stats.get("slg") or "").strip()
    season_ops = str(stats.get("ops") or "").strip()
    season_home_runs = str(stats.get("homeRuns") or stats.get("home_runs") or "").strip()
    season_rbi = str(stats.get("rbi") or "").strip()
    season_hits = str(stats.get("hits") or "").strip()
    season_at_bats = str(stats.get("atBats") or stats.get("at_bats") or "").strip()
    season_games_played = str(stats.get("gamesPlayed") or stats.get("games_played") or "").strip()
    season_plate_appearances = str(
        stats.get("plateAppearances") or stats.get("plate_appearances") or ""
    ).strip()

    target["season"] = safe_int(stats.get("season"), 0)
    target["seasonStatsAvailable"] = bool(stats.get("available"))
    target["season_stats_available"] = bool(stats.get("available"))

    target["seasonAvg"] = season_avg
    target["season_avg"] = season_avg
    target["seasonObp"] = season_obp
    target["season_obp"] = season_obp
    target["seasonSlg"] = season_slg
    target["season_slg"] = season_slg
    target["seasonOps"] = season_ops
    target["season_ops"] = season_ops
    target["seasonHomeRuns"] = season_home_runs
    target["season_home_runs"] = season_home_runs
    target["seasonRbi"] = season_rbi
    target["season_rbi"] = season_rbi
    target["seasonHits"] = season_hits
    target["season_hits"] = season_hits
    target["seasonAtBats"] = season_at_bats
    target["season_at_bats"] = season_at_bats
    target["seasonGamesPlayed"] = season_games_played
    target["season_games_played"] = season_games_played
    target["seasonPlateAppearances"] = season_plate_appearances
    target["season_plate_appearances"] = season_plate_appearances


def attach_lineup_batter_season_stats(
    batting_order: Optional[Dict[str, Any]],
    stats_payload_by_player: Dict[int, Dict[str, Any]],
) -> None:
    if not isinstance(batting_order, dict):
        return

    players = batting_order.get("players") if isinstance(batting_order.get("players"), list) else []

    for player in players:
        if not isinstance(player, dict):
            continue

        player_id = safe_int(player.get("playerId"), 0)
        stats_payload = (
            copy.deepcopy(stats_payload_by_player.get(player_id))
            if player_id > 0 and isinstance(stats_payload_by_player.get(player_id), dict)
            else {}
        )
        attach_batter_season_stats(player, stats_payload)

    for slot in range(1, 10):
        key = f"spot_{slot}"
        spot = batting_order.get(key)
        if not isinstance(spot, dict):
            continue

        player_id = safe_int(spot.get("player_id"), safe_int(spot.get("id"), 0))
        stats_payload = (
            copy.deepcopy(stats_payload_by_player.get(player_id))
            if player_id > 0 and isinstance(stats_payload_by_player.get(player_id), dict)
            else {}
        )
        attach_batter_season_stats(spot, stats_payload)


def build_probable_pitcher_season_stats_payload(pitching_stats: Optional[Dict[str, Any]], season: int) -> Dict[str, Any]:
    era_value = first_present_stat_value(pitching_stats, ["era"], fallback="")
    fip_value = first_present_stat_value(pitching_stats, ["fip"], fallback="")
    whip_value = first_present_stat_value(pitching_stats, ["whip"], fallback="")

    available = bool(era_value or fip_value or whip_value)
    stat_line = ""
    if available:
        stat_line = (
            f"ERA {era_value or '--'} | "
            f"FIP {fip_value or '--'} | "
            f"WHIP {whip_value or '--'}"
        )

    return {
        "available": available,
        "season": season,
        "era": era_value,
        "fip": fip_value,
        "whip": whip_value,
        "line": stat_line,
    }


def load_probable_pitcher_stats_by_player_ids(player_ids: List[int], season: int) -> Dict[int, Dict[str, Any]]:
    unique_ids = sorted({safe_int(player_id, 0) for player_id in player_ids if safe_int(player_id, 0) > 0})
    if not unique_ids:
        return {}

    stats_rows_by_pitcher: Dict[int, Dict[str, Any]] = {}
    database_path = resolve_database_path()

    if database_path.exists():
        try:
            with open_database_connection() as connection:
                tables = sqlite_table_names(connection)
                if "pitcher_stats_season" in tables:
                    placeholders = ",".join("?" for _ in unique_ids)
                    rows_for_season = rows_to_dicts(
                        connection.execute(
                            f"""
                            SELECT *
                            FROM pitcher_stats_season
                            WHERE player_id IN ({placeholders})
                              AND season = ?
                            ORDER BY player_id ASC,
                                     COALESCE(games_played, 0) DESC
                            """,
                            tuple(unique_ids) + (season,),
                        ).fetchall()
                    )

                    for row in rows_for_season:
                        player_id = safe_int(row.get("player_id"), 0)
                        if player_id > 0 and player_id not in stats_rows_by_pitcher:
                            stats_rows_by_pitcher[player_id] = row

                    missing_ids = [player_id for player_id in unique_ids if player_id not in stats_rows_by_pitcher]
                    if missing_ids:
                        missing_placeholders = ",".join("?" for _ in missing_ids)
                        fallback_rows = rows_to_dicts(
                            connection.execute(
                                f"""
                                SELECT *
                                FROM pitcher_stats_season
                                WHERE player_id IN ({missing_placeholders})
                                ORDER BY player_id ASC,
                                         season DESC,
                                         COALESCE(games_played, 0) DESC
                                """,
                                tuple(missing_ids),
                            ).fetchall()
                        )

                        for row in fallback_rows:
                            player_id = safe_int(row.get("player_id"), 0)
                            if player_id > 0 and player_id not in stats_rows_by_pitcher:
                                stats_rows_by_pitcher[player_id] = row
        except sqlite3.Error:
            stats_rows_by_pitcher = {}

    unresolved_ids = [player_id for player_id in unique_ids if player_id not in stats_rows_by_pitcher]
    if unresolved_ids:
        people_by_id = fetch_people_with_stats(unresolved_ids, season, include_advanced=True)
        for player_id in unresolved_ids:
            person = people_by_id.get(player_id) if isinstance(people_by_id.get(player_id), dict) else {}
            pitching_standard = extract_group_stat(person, "pitching", "season") if isinstance(person, dict) else {}
            pitching_advanced = extract_group_stat(person, "pitching", "seasonadvanced") if isinstance(person, dict) else {}

            merged_pitching_stats: Dict[str, Any] = copy.deepcopy(pitching_standard) if isinstance(pitching_standard, dict) else {}
            if isinstance(pitching_advanced, dict):
                for key, value in pitching_advanced.items():
                    value_text = str(value).strip() if value is not None else ""
                    if value is None or not value_text:
                        continue
                    merged_pitching_stats[str(key)] = value

            if merged_pitching_stats:
                stats_rows_by_pitcher[player_id] = merged_pitching_stats

    stats_by_pitcher: Dict[int, Dict[str, Any]] = {}
    for player_id in unique_ids:
        stats_by_pitcher[player_id] = build_probable_pitcher_season_stats_payload(
            stats_rows_by_pitcher.get(player_id),
            season,
        )

    return stats_by_pitcher


def attach_probable_pitcher_stats(
    probable_pitcher: Optional[Dict[str, Any]],
    stats_by_pitcher: Dict[int, Dict[str, Any]],
) -> None:
    if not isinstance(probable_pitcher, dict):
        return

    pitcher_id = safe_int(probable_pitcher.get("id"), 0)
    stats_payload = (
        copy.deepcopy(stats_by_pitcher.get(pitcher_id))
        if pitcher_id > 0 and isinstance(stats_by_pitcher.get(pitcher_id), dict)
        else {}
    )

    era_value = str(stats_payload.get("era") or "").strip()
    fip_value = str(stats_payload.get("fip") or "").strip()
    whip_value = str(stats_payload.get("whip") or "").strip()
    season_line = str(stats_payload.get("line") or "").strip()

    probable_pitcher["era"] = era_value
    probable_pitcher["fip"] = fip_value
    probable_pitcher["whip"] = whip_value
    probable_pitcher["seasonStats"] = copy.deepcopy(stats_payload)
    probable_pitcher["season_stats"] = copy.deepcopy(stats_payload)
    probable_pitcher["seasonLine"] = season_line
    probable_pitcher["season_line"] = season_line
    probable_pitcher["statsAvailable"] = bool(stats_payload.get("available"))
    probable_pitcher["stats_available"] = bool(stats_payload.get("available"))


def summarize_live_base_state(
    first_runner: Optional[Dict[str, Any]],
    second_runner: Optional[Dict[str, Any]],
    third_runner: Optional[Dict[str, Any]],
) -> str:
    occupied = []
    if first_runner:
        occupied.append("1st")
    if second_runner:
        occupied.append("2nd")
    if third_runner:
        occupied.append("3rd")

    if not occupied:
        return "Bases empty"
    if len(occupied) == 3:
        return "Bases loaded"
    if len(occupied) == 1:
        return f"Runner on {occupied[0]}"
    return f"Runners on {' and '.join(occupied)}"


def extract_live_game_context(feed: Optional[Dict[str, Any]], team_id: int) -> Dict[str, Any]:
    empty_order = empty_batting_order_payload()
    empty_orders = {
        "away": copy.deepcopy(empty_order),
        "home": copy.deepcopy(empty_order),
        "team": copy.deepcopy(empty_order),
        "opponent": copy.deepcopy(empty_order),
    }

    if not isinstance(feed, dict):
        return {
            "available": False,
            "inning": {"state": "", "half": "", "number": 0},
            "count": {"balls": 0, "strikes": 0, "outs": 0},
            "atBatTeam": {},
            "fieldingTeam": {},
            "currentBatter": None,
            "currentPitcher": None,
            "onDeck": None,
            "inHole": None,
            "baseRunners": {
                "first": None,
                "second": None,
                "third": None,
                "occupiedCount": 0,
                "occupancyCode": "000",
                "summary": "Bases empty",
            },
            "teamCurrentBatter": None,
            "teamCurrentPitcher": None,
            "opponentCurrentBatter": None,
            "opponentCurrentPitcher": None,
            "battingOrders": empty_orders,
            "currentMatchup": None,
        }

    live_data = feed.get("liveData") if isinstance(feed.get("liveData"), dict) else {}
    linescore = live_data.get("linescore") if isinstance(live_data.get("linescore"), dict) else {}
    offense = linescore.get("offense") if isinstance(linescore.get("offense"), dict) else {}
    defense = linescore.get("defense") if isinstance(linescore.get("defense"), dict) else {}

    at_bat_team = offense.get("team") if isinstance(offense.get("team"), dict) else {}
    fielding_team = defense.get("team") if isinstance(defense.get("team"), dict) else {}
    at_bat_team_id = safe_int(at_bat_team.get("id"), 0)
    fielding_team_id = safe_int(fielding_team.get("id"), 0)

    current_batter = normalize_person_reference(offense.get("batter"))
    current_pitcher = normalize_person_reference(defense.get("pitcher"))
    on_deck = normalize_person_reference(offense.get("onDeck"))
    in_hole = normalize_person_reference(offense.get("inHole"))
    first_runner = normalize_person_reference(offense.get("first"))
    second_runner = normalize_person_reference(offense.get("second"))
    third_runner = normalize_person_reference(offense.get("third"))

    current_batter_payload = current_batter if current_batter else None
    current_pitcher_payload = current_pitcher if current_pitcher else None
    on_deck_payload = on_deck if on_deck else None
    in_hole_payload = in_hole if in_hole else None
    first_runner_payload = first_runner if first_runner else None
    second_runner_payload = second_runner if second_runner else None
    third_runner_payload = third_runner if third_runner else None

    base_occupancy_code = "".join(
        "1" if runner is not None else "0"
        for runner in (first_runner_payload, second_runner_payload, third_runner_payload)
    )
    base_runners = {
        "first": first_runner_payload,
        "second": second_runner_payload,
        "third": third_runner_payload,
        "occupiedCount": sum(
            1 for runner in (first_runner_payload, second_runner_payload, third_runner_payload) if runner is not None
        ),
        "occupancyCode": base_occupancy_code,
        "summary": summarize_live_base_state(first_runner_payload, second_runner_payload, third_runner_payload),
    }

    boxscore = live_data.get("boxscore") if isinstance(live_data.get("boxscore"), dict) else {}
    boxscore_teams = boxscore.get("teams") if isinstance(boxscore.get("teams"), dict) else {}
    away_boxscore = boxscore_teams.get("away") if isinstance(boxscore_teams.get("away"), dict) else {}
    home_boxscore = boxscore_teams.get("home") if isinstance(boxscore_teams.get("home"), dict) else {}

    away_order = serialize_batting_order(away_boxscore)
    home_order = serialize_batting_order(home_boxscore)

    away_team_blob = away_boxscore.get("team") if isinstance(away_boxscore.get("team"), dict) else {}
    home_team_blob = home_boxscore.get("team") if isinstance(home_boxscore.get("team"), dict) else {}
    away_team_id = safe_int(away_team_blob.get("id"), 0)
    home_team_id = safe_int(home_team_blob.get("id"), 0)

    if team_id > 0 and team_id == away_team_id:
        team_order = away_order
        opponent_order = home_order
    elif team_id > 0 and team_id == home_team_id:
        team_order = home_order
        opponent_order = away_order
    else:
        team_order = copy.deepcopy(empty_order)
        opponent_order = copy.deepcopy(empty_order)

    team_current_batter = current_batter_payload if at_bat_team_id == team_id else None
    team_current_pitcher = current_pitcher_payload if fielding_team_id == team_id else None
    opponent_current_batter = current_batter_payload if at_bat_team_id > 0 and at_bat_team_id != team_id else None
    opponent_current_pitcher = current_pitcher_payload if fielding_team_id > 0 and fielding_team_id != team_id else None

    current_matchup = None
    if current_batter_payload or current_pitcher_payload:
        current_matchup = {
            "battingTeam": {
                "id": at_bat_team_id,
                "name": str(at_bat_team.get("name") or "").strip(),
            },
            "fieldingTeam": {
                "id": fielding_team_id,
                "name": str(fielding_team.get("name") or "").strip(),
            },
            "batter": current_batter_payload,
            "pitcher": current_pitcher_payload,
            "onDeck": on_deck_payload,
            "inHole": in_hole_payload,
            "baseRunners": copy.deepcopy(base_runners),
            "battingOrderSpot": safe_int(offense.get("battingOrder"), 0),
        }

    return {
        "available": True,
        "inning": {
            "state": str(linescore.get("inningState") or "").strip(),
            "half": str(linescore.get("inningHalf") or "").strip(),
            "number": safe_int(linescore.get("currentInning"), 0),
        },
        "count": {
            "balls": safe_int(linescore.get("balls"), 0),
            "strikes": safe_int(linescore.get("strikes"), 0),
            "outs": safe_int(linescore.get("outs"), 0),
        },
        "atBatTeam": {
            "id": at_bat_team_id,
            "name": str(at_bat_team.get("name") or "").strip(),
        },
        "fieldingTeam": {
            "id": fielding_team_id,
            "name": str(fielding_team.get("name") or "").strip(),
        },
        "currentBatter": current_batter_payload,
        "currentPitcher": current_pitcher_payload,
        "onDeck": on_deck_payload,
        "inHole": in_hole_payload,
        "baseRunners": base_runners,
        "teamCurrentBatter": team_current_batter,
        "teamCurrentPitcher": team_current_pitcher,
        "opponentCurrentBatter": opponent_current_batter,
        "opponentCurrentPitcher": opponent_current_pitcher,
        "battingOrders": {
            "away": away_order,
            "home": home_order,
            "team": team_order,
            "opponent": opponent_order,
        },
        "currentMatchup": current_matchup,
    }


def load_game_odds_rows_by_game_pk(game_pks: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    unique_ids = sorted({safe_int(game_pk, 0) for game_pk in game_pks if safe_int(game_pk, 0) > 0})
    if not unique_ids:
        return {}

    database_path = resolve_database_path()
    if not database_path.exists():
        return {}

    try:
        with open_database_connection() as connection:
            tables = sqlite_table_names(connection)
            if "game_betting_odds" not in tables:
                return {}

            table_columns = sqlite_table_columns(connection, "game_betting_odds")
            implied_probability_sql = (
                "implied_probability"
                if "implied_probability" in table_columns
                else "NULL AS implied_probability"
            )
            implied_probability_percent_sql = (
                "implied_probability_percent"
                if "implied_probability_percent" in table_columns
                else "NULL AS implied_probability_percent"
            )

            placeholders = ",".join("?" for _ in unique_ids)
            rows = rows_to_dicts(
                connection.execute(
                    f"""
                    SELECT
                        game_pk,
                        market_key,
                        selection_name,
                        selection_description,
                        line,
                        odds_price,
                        {implied_probability_sql},
                        {implied_probability_percent_sql},
                        bookmaker_key,
                        bookmaker_title,
                        market_last_update,
                        commence_time
                    FROM game_betting_odds
                    WHERE game_pk IN ({placeholders})
                    ORDER BY COALESCE(commence_time, '') DESC,
                             bookmaker_key,
                             market_key,
                             selection_name
                    """,
                    tuple(unique_ids),
                ).fetchall()
            )
    except sqlite3.Error:
        return {}

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        game_pk = safe_int(row.get("game_pk"), 0)
        if game_pk <= 0:
            continue
        grouped.setdefault(game_pk, []).append(row)

    return grouped


def format_game_odds_row(row: Dict[str, Any]) -> Dict[str, Any]:
    implied_probability, implied_probability_percent = normalize_implied_probability_values(
        row.get("implied_probability"),
        row.get("implied_probability_percent"),
        row.get("odds_price"),
    )

    return {
        "marketKey": str(row.get("market_key") or "").strip(),
        "selectionName": str(row.get("selection_name") or "").strip(),
        "selectionDescription": str(row.get("selection_description") or "").strip(),
        "line": row.get("line"),
        "oddsPrice": row.get("odds_price"),
        "oddsPriceDisplay": display_odds_price(row.get("odds_price"), "--"),
        "impliedProbability": implied_probability,
        "impliedProbabilityPercent": implied_probability_percent,
        "bookmakerKey": str(row.get("bookmaker_key") or "").strip(),
        "bookmakerTitle": str(row.get("bookmaker_title") or "").strip(),
        "marketLastUpdate": str(row.get("market_last_update") or "").strip(),
        "commenceTime": str(row.get("commence_time") or "").strip(),
    }


def summarize_game_odds_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "moneyline": {"home": None, "away": None},
            "runLine": {"home": None, "away": None},
            "total": {"line": None, "over": None, "under": None},
        }

    def is_full_game_row(row: Dict[str, Any]) -> bool:
        selection_name = str(row.get("selection_name") or "")
        return " - " not in selection_name

    def row_rank(row: Dict[str, Any]) -> tuple:
        bookmaker_key = str(row.get("bookmaker_key") or "").strip().lower()
        preferred_rank = 0 if bookmaker_key == "bovada" else 1
        updated_at = str(row.get("market_last_update") or "")
        return (preferred_rank, bookmaker_key, updated_at)

    def choose_row(market_key: str, selection_description: str = "", selection_name: str = "") -> Optional[Dict[str, Any]]:
        market_token = market_key.strip().lower()
        description_token = selection_description.strip().lower()
        selection_token = selection_name.strip().lower()

        candidates: List[Dict[str, Any]] = []
        for row in rows:
            if str(row.get("market_key") or "").strip().lower() != market_token:
                continue
            if not is_full_game_row(row):
                continue

            if description_token:
                current_description = str(row.get("selection_description") or "").strip().lower()
                if current_description != description_token:
                    continue

            if selection_token:
                current_selection = str(row.get("selection_name") or "").strip().lower()
                if current_selection != selection_token:
                    continue

            candidates.append(row)

        if not candidates:
            return None

        candidates = sorted(candidates, key=row_rank)
        return candidates[0]

    def summarize_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(row, dict):
            return None

        implied_probability, implied_probability_percent = normalize_implied_probability_values(
            row.get("implied_probability"),
            row.get("implied_probability_percent"),
            row.get("odds_price"),
        )

        return {
            "selection": str(row.get("selection_name") or "").strip(),
            "line": row.get("line"),
            "price": row.get("odds_price"),
            "priceDisplay": display_odds_price(row.get("odds_price"), "--"),
            "impliedProbability": implied_probability,
            "impliedProbabilityPercent": implied_probability_percent,
            "impliedProbabilityRaw": implied_probability,
            "impliedProbabilityPercentRaw": implied_probability_percent,
            "bookmakerKey": str(row.get("bookmaker_key") or "").strip(),
            "bookmakerTitle": str(row.get("bookmaker_title") or "").strip(),
            "marketLastUpdate": str(row.get("market_last_update") or "").strip(),
        }

    moneyline_home = choose_row("h2h", selection_description="home")
    moneyline_away = choose_row("h2h", selection_description="away")
    runline_home = choose_row("spreads", selection_description="home")
    runline_away = choose_row("spreads", selection_description="away")
    total_over = choose_row("totals", selection_name="over")
    total_under = choose_row("totals", selection_name="under")

    total_line = None
    if isinstance(total_over, dict) and total_over.get("line") is not None:
        total_line = total_over.get("line")
    elif isinstance(total_under, dict) and total_under.get("line") is not None:
        total_line = total_under.get("line")

    moneyline_home_summary = summarize_row(moneyline_home)
    moneyline_away_summary = summarize_row(moneyline_away)
    runline_home_summary = summarize_row(runline_home)
    runline_away_summary = summarize_row(runline_away)
    total_over_summary = summarize_row(total_over)
    total_under_summary = summarize_row(total_under)

    apply_no_vig_pair_probabilities(moneyline_home_summary, moneyline_away_summary)
    apply_no_vig_pair_probabilities(runline_home_summary, runline_away_summary)
    apply_no_vig_pair_probabilities(total_over_summary, total_under_summary)

    return {
        "moneyline": {
            "home": moneyline_home_summary,
            "away": moneyline_away_summary,
        },
        "runLine": {
            "home": runline_home_summary,
            "away": runline_away_summary,
        },
        "total": {
            "line": total_line,
            "over": total_over_summary,
            "under": total_under_summary,
        },
    }


def build_game_odds_payload(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    empty_summary = summarize_game_odds_rows([])
    if not rows:
        return {
            "available": False,
            "source": "game_betting_odds",
            "bookmakers": [],
            "markets": [],
            "summary": empty_summary,
            "rows": [],
            "bovada": {
                "available": False,
                "summary": empty_summary,
                "rows": [],
            },
            "bovadaAvailable": False,
            "bovadaSummary": empty_summary,
            "bovadaRows": [],
        }

    bookmakers = sorted(
        {
            str(row.get("bookmaker_title") or row.get("bookmaker_key") or "").strip()
            for row in rows
            if str(row.get("bookmaker_title") or row.get("bookmaker_key") or "").strip()
        }
    )
    markets = sorted(
        {
            str(row.get("market_key") or "").strip()
            for row in rows
            if str(row.get("market_key") or "").strip()
        }
    )

    normalized_rows = [row for row in rows if isinstance(row, dict)]
    bovada_rows = [
        row
        for row in normalized_rows
        if str(row.get("bookmaker_key") or "").strip().lower() == "bovada"
    ]

    all_rows_payload = [format_game_odds_row(row) for row in normalized_rows]
    bovada_rows_payload = [format_game_odds_row(row) for row in bovada_rows]
    overall_summary = summarize_game_odds_rows(normalized_rows)
    bovada_summary = summarize_game_odds_rows(bovada_rows)

    return {
        "available": True,
        "source": "game_betting_odds",
        "bookmakers": bookmakers,
        "markets": markets,
        "summary": overall_summary,
        "rows": all_rows_payload,
        "bovada": {
            "available": bool(bovada_rows),
            "summary": bovada_summary,
            "rows": bovada_rows_payload,
        },
        "bovadaAvailable": bool(bovada_rows),
        "bovadaSummary": bovada_summary,
        "bovadaRows": bovada_rows_payload,
    }


def build_game_score_payload(game: Dict[str, Any], feed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    status = game.get("status") if isinstance(game.get("status"), dict) else {}
    status_abstract = str(status.get("abstract") or "").strip()
    status_detailed = str(status.get("detailed") or "").strip()

    away_team = game.get("away") if isinstance(game.get("away"), dict) else {}
    home_team = game.get("home") if isinstance(game.get("home"), dict) else {}
    score_source = game.get("score") if isinstance(game.get("score"), dict) else {}
    inning_source = score_source.get("inning") if isinstance(score_source.get("inning"), dict) else {}
    count_source = score_source.get("count") if isinstance(score_source.get("count"), dict) else {}

    score_payload = {
        "available": True,
        "isLive": status_abstract == "Live",
        "status": {
            "abstract": status_abstract,
            "detailed": status_detailed,
        },
        "away": {
            "id": safe_int(away_team.get("id"), 0),
            "name": str(away_team.get("name") or "Away").strip(),
            "abbreviation": str(away_team.get("abbreviation") or away_team.get("abbrev") or "").strip(),
            "runs": safe_int(away_team.get("runs"), 0),
            "hits": safe_int(away_team.get("hits"), 0),
            "errors": safe_int(away_team.get("errors"), 0),
        },
        "home": {
            "id": safe_int(home_team.get("id"), 0),
            "name": str(home_team.get("name") or "Home").strip(),
            "abbreviation": str(home_team.get("abbreviation") or home_team.get("abbrev") or "").strip(),
            "runs": safe_int(home_team.get("runs"), 0),
            "hits": safe_int(home_team.get("hits"), 0),
            "errors": safe_int(home_team.get("errors"), 0),
        },
        "inning": {
            "state": str(inning_source.get("state") or "").strip(),
            "half": str(inning_source.get("half") or "").strip(),
            "number": safe_int(inning_source.get("number"), 0),
        },
        "count": {
            "balls": safe_int(count_source.get("balls"), 0),
            "strikes": safe_int(count_source.get("strikes"), 0),
            "outs": safe_int(count_source.get("outs"), 0),
        },
    }

    if not isinstance(feed, dict):
        return score_payload

    game_data = feed.get("gameData") if isinstance(feed.get("gameData"), dict) else {}
    game_data_status = game_data.get("status") if isinstance(game_data.get("status"), dict) else {}
    game_data_teams = game_data.get("teams") if isinstance(game_data.get("teams"), dict) else {}
    away_team_data = game_data_teams.get("away") if isinstance(game_data_teams.get("away"), dict) else {}
    home_team_data = game_data_teams.get("home") if isinstance(game_data_teams.get("home"), dict) else {}

    abstract_override = str(game_data_status.get("abstractGameState") or "").strip()
    detailed_override = str(game_data_status.get("detailedState") or "").strip()
    if abstract_override:
        score_payload["status"]["abstract"] = abstract_override
    if detailed_override:
        score_payload["status"]["detailed"] = detailed_override

    away_name_override = str(away_team_data.get("name") or "").strip()
    away_abbrev_override = str(away_team_data.get("abbreviation") or "").strip()
    home_name_override = str(home_team_data.get("name") or "").strip()
    home_abbrev_override = str(home_team_data.get("abbreviation") or "").strip()

    if away_name_override:
        score_payload["away"]["name"] = away_name_override
    if away_abbrev_override:
        score_payload["away"]["abbreviation"] = away_abbrev_override
    if home_name_override:
        score_payload["home"]["name"] = home_name_override
    if home_abbrev_override:
        score_payload["home"]["abbreviation"] = home_abbrev_override

    live_data = feed.get("liveData") if isinstance(feed.get("liveData"), dict) else {}
    linescore = live_data.get("linescore") if isinstance(live_data.get("linescore"), dict) else {}
    line_teams = linescore.get("teams") if isinstance(linescore.get("teams"), dict) else {}
    away_line = line_teams.get("away") if isinstance(line_teams.get("away"), dict) else {}
    home_line = line_teams.get("home") if isinstance(line_teams.get("home"), dict) else {}

    score_payload["away"]["runs"] = safe_int(away_line.get("runs"), score_payload["away"]["runs"])
    score_payload["away"]["hits"] = safe_int(away_line.get("hits"), score_payload["away"]["hits"])
    score_payload["away"]["errors"] = safe_int(away_line.get("errors"), score_payload["away"]["errors"])
    score_payload["home"]["runs"] = safe_int(home_line.get("runs"), score_payload["home"]["runs"])
    score_payload["home"]["hits"] = safe_int(home_line.get("hits"), score_payload["home"]["hits"])
    score_payload["home"]["errors"] = safe_int(home_line.get("errors"), score_payload["home"]["errors"])

    score_payload["inning"]["state"] = str(linescore.get("inningState") or score_payload["inning"]["state"]).strip()
    score_payload["inning"]["half"] = str(linescore.get("inningHalf") or score_payload["inning"]["half"]).strip()
    score_payload["inning"]["number"] = safe_int(linescore.get("currentInning"), score_payload["inning"]["number"])
    score_payload["count"]["balls"] = safe_int(linescore.get("balls"), score_payload["count"]["balls"])
    score_payload["count"]["strikes"] = safe_int(linescore.get("strikes"), score_payload["count"]["strikes"])
    score_payload["count"]["outs"] = safe_int(linescore.get("outs"), score_payload["count"]["outs"])

    score_payload["isLive"] = str(score_payload.get("status", {}).get("abstract") or "").strip() == "Live"
    return score_payload


def enrich_team_games_endpoint_payload(team_id: int, games: List[Dict[str, Any]]) -> None:
    if not games:
        return

    game_pks = [safe_int(game.get("gamePk"), 0) for game in games if isinstance(game, dict)]
    odds_by_game_pk = load_game_odds_rows_by_game_pk(game_pks)
    batting_rows_by_game_pk = load_batting_order_rows_by_game_pk(game_pks)

    feed_cache: Dict[int, Optional[Dict[str, Any]]] = {}
    weather_cache: Dict[str, Dict[str, Any]] = {}
    default_batting_order = empty_batting_order_payload()
    season = board_season()
    lineup_stats_by_player_cache: Dict[int, Dict[str, Any]] = {}

    probable_pitcher_ids: List[int] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        for side_key in ("away", "home"):
            side_blob = game.get(side_key) if isinstance(game.get(side_key), dict) else {}
            probable_pitcher = side_blob.get("probablePitcher") if isinstance(side_blob.get("probablePitcher"), dict) else {}
            probable_pitcher_id = safe_int(probable_pitcher.get("id"), 0)
            if probable_pitcher_id > 0:
                probable_pitcher_ids.append(probable_pitcher_id)

    probable_pitcher_stats_by_player = load_probable_pitcher_stats_by_player_ids(
        sorted(set(probable_pitcher_ids)),
        season,
    )
    pitcher_stats_by_player_cache: Dict[int, Dict[str, Any]] = dict(probable_pitcher_stats_by_player)

    for game in games:
        if not isinstance(game, dict):
            continue

        game_pk = safe_int(game.get("gamePk"), 0)
        odds_rows = odds_by_game_pk.get(game_pk, [])
        odds_payload = build_game_odds_payload(odds_rows)
        game["odds"] = odds_payload
        game["bovadaOdds"] = copy.deepcopy(odds_payload.get("bovada", {"available": False, "summary": summarize_game_odds_rows([]), "rows": []}))

        feed = get_game_feed_cached(game_pk, feed_cache) if game_pk > 0 else None

        score_payload = build_game_score_payload(game, feed)
        game["score"] = score_payload
        game["scoreboard"] = copy.deepcopy(score_payload)

        away_score = score_payload.get("away") if isinstance(score_payload.get("away"), dict) else {}
        home_score = score_payload.get("home") if isinstance(score_payload.get("home"), dict) else {}
        away_blob = game.get("away") if isinstance(game.get("away"), dict) else None
        home_blob = game.get("home") if isinstance(game.get("home"), dict) else None
        team_blob = game.get("team") if isinstance(game.get("team"), dict) else None
        opponent_blob = game.get("opponent") if isinstance(game.get("opponent"), dict) else None
        away_id = safe_int(away_blob.get("id"), 0) if isinstance(away_blob, dict) else 0
        home_id = safe_int(home_blob.get("id"), 0) if isinstance(home_blob, dict) else 0

        theme_team_id = safe_int(team_blob.get("id"), 0) if isinstance(team_blob, dict) else 0
        if theme_team_id <= 0:
            theme_team_id = team_id if team_id > 0 else away_id or home_id
        if theme_team_id > 0:
            game["theme"] = team_theme_colors(theme_team_id)

        for blob in (away_blob, home_blob, team_blob, opponent_blob):
            if not isinstance(blob, dict):
                continue
            probable_pitcher = blob.get("probablePitcher") if isinstance(blob.get("probablePitcher"), dict) else None
            attach_probable_pitcher_stats(probable_pitcher, probable_pitcher_stats_by_player)

        starting_pitchers = game.get("startingPitchers") if isinstance(game.get("startingPitchers"), dict) else None
        if isinstance(starting_pitchers, dict):
            for pitcher_key in ("away", "home", "team", "opponent"):
                pitcher_blob = starting_pitchers.get(pitcher_key)
                if isinstance(pitcher_blob, dict):
                    attach_probable_pitcher_stats(pitcher_blob, probable_pitcher_stats_by_player)

        if isinstance(away_blob, dict):
            away_blob["runs"] = safe_int(away_score.get("runs"), safe_int(away_blob.get("runs"), 0))
            away_blob["hits"] = safe_int(away_score.get("hits"), safe_int(away_blob.get("hits"), 0))
            away_blob["errors"] = safe_int(away_score.get("errors"), safe_int(away_blob.get("errors"), 0))

        if isinstance(home_blob, dict):
            home_blob["runs"] = safe_int(home_score.get("runs"), safe_int(home_blob.get("runs"), 0))
            home_blob["hits"] = safe_int(home_score.get("hits"), safe_int(home_blob.get("hits"), 0))
            home_blob["errors"] = safe_int(home_score.get("errors"), safe_int(home_blob.get("errors"), 0))

        weather_key = f"{safe_int(game.get('venueId'), 0)}|{str(game.get('gameDate') or '').strip()}"
        if weather_key not in weather_cache:
            weather_payload = get_weather_for_scheduled_game(game)
            if isinstance(weather_payload, dict):
                weather_cache[weather_key] = copy.deepcopy(weather_payload)
            else:
                weather_cache[weather_key] = empty_game_weather_payload()
        game["weather"] = copy.deepcopy(weather_cache[weather_key])

        live_context = extract_live_game_context(feed, team_id)
        current_batter = (
            live_context.get("currentBatter")
            if isinstance(live_context.get("currentBatter"), dict)
            else None
        )
        current_pitcher = (
            live_context.get("currentPitcher")
            if isinstance(live_context.get("currentPitcher"), dict)
            else None
        )

        current_batter_id = safe_int(current_batter.get("id"), 0) if isinstance(current_batter, dict) else 0
        if current_batter_id > 0 and current_batter_id not in lineup_stats_by_player_cache:
            lineup_stats_by_player_cache.update(
                load_lineup_batter_season_stats_by_player_ids([current_batter_id], season)
            )
        if isinstance(current_batter, dict):
            attach_batter_season_stats(current_batter, lineup_stats_by_player_cache.get(current_batter_id, {}))

        current_pitcher_id = safe_int(current_pitcher.get("id"), 0) if isinstance(current_pitcher, dict) else 0
        if current_pitcher_id > 0 and current_pitcher_id not in pitcher_stats_by_player_cache:
            pitcher_stats_by_player_cache.update(
                load_probable_pitcher_stats_by_player_ids([current_pitcher_id], season)
            )
        if isinstance(current_pitcher, dict):
            attach_probable_pitcher_stats(current_pitcher, pitcher_stats_by_player_cache)

        game["live"] = live_context
        game["currentMatchup"] = live_context.get("currentMatchup")
        game["currentBatter"] = live_context.get("currentBatter")
        game["currentPitcher"] = live_context.get("currentPitcher")
        game["teamCurrentBatter"] = live_context.get("teamCurrentBatter")
        game["teamCurrentPitcher"] = live_context.get("teamCurrentPitcher")
        game["opponentCurrentBatter"] = live_context.get("opponentCurrentBatter")
        game["opponentCurrentPitcher"] = live_context.get("opponentCurrentPitcher")

        live_batting_orders = live_context.get("battingOrders") if isinstance(live_context.get("battingOrders"), dict) else {}
        live_away_order = live_batting_orders.get("away") if isinstance(live_batting_orders.get("away"), dict) else None
        live_home_order = live_batting_orders.get("home") if isinstance(live_batting_orders.get("home"), dict) else None
        live_team_order = live_batting_orders.get("team") if isinstance(live_batting_orders.get("team"), dict) else None
        live_opponent_order = live_batting_orders.get("opponent") if isinstance(live_batting_orders.get("opponent"), dict) else None

        db_rows = batting_rows_by_game_pk.get(game_pk, [])
        db_rows_by_team: Dict[int, List[Dict[str, Any]]] = {}
        for row in db_rows:
            if not isinstance(row, dict):
                continue
            team_row_id = safe_int(row.get("team_id"), 0)
            if team_row_id <= 0:
                continue
            db_rows_by_team.setdefault(team_row_id, []).append(row)

        db_away_order = serialize_batting_order_from_db_rows(db_rows_by_team.get(away_id, []))
        db_home_order = serialize_batting_order_from_db_rows(db_rows_by_team.get(home_id, []))

        away_batting_order = pick_preferred_batting_order(db_away_order, live_away_order, default_batting_order)
        home_batting_order = pick_preferred_batting_order(db_home_order, live_home_order, default_batting_order)

        if team_id > 0 and team_id == away_id:
            team_batting_order = copy.deepcopy(away_batting_order)
            opponent_batting_order = copy.deepcopy(home_batting_order)
        elif team_id > 0 and team_id == home_id:
            team_batting_order = copy.deepcopy(home_batting_order)
            opponent_batting_order = copy.deepcopy(away_batting_order)
        else:
            team_batting_order = pick_preferred_batting_order(None, live_team_order, default_batting_order)
            opponent_batting_order = pick_preferred_batting_order(None, live_opponent_order, default_batting_order)

        lineup_player_ids: List[int] = []
        for order in (away_batting_order, home_batting_order, team_batting_order, opponent_batting_order):
            if not isinstance(order, dict):
                continue
            players = order.get("players") if isinstance(order.get("players"), list) else []
            for player in players:
                player_id = safe_int(player.get("playerId"), 0) if isinstance(player, dict) else 0
                if player_id > 0:
                    lineup_player_ids.append(player_id)

        missing_player_ids = [
            player_id
            for player_id in sorted(set(lineup_player_ids))
            if player_id not in lineup_stats_by_player_cache
        ]
        if missing_player_ids:
            loaded_stats = load_lineup_batter_season_stats_by_player_ids(missing_player_ids, season)
            lineup_stats_by_player_cache.update(loaded_stats)

        attach_lineup_batter_season_stats(away_batting_order, lineup_stats_by_player_cache)
        attach_lineup_batter_season_stats(home_batting_order, lineup_stats_by_player_cache)
        attach_lineup_batter_season_stats(team_batting_order, lineup_stats_by_player_cache)
        attach_lineup_batter_season_stats(opponent_batting_order, lineup_stats_by_player_cache)

        game["battingOrders"] = {
            "away": copy.deepcopy(away_batting_order),
            "home": copy.deepcopy(home_batting_order),
            "team": copy.deepcopy(team_batting_order),
            "opponent": copy.deepcopy(opponent_batting_order),
        }

        if isinstance(away_blob, dict):
            away_blob["battingOrder"] = copy.deepcopy(away_batting_order)

        if isinstance(home_blob, dict):
            home_blob["battingOrder"] = copy.deepcopy(home_batting_order)

        team_id_in_game = safe_int(team_blob.get("id"), 0) if isinstance(team_blob, dict) else 0
        opponent_id_in_game = safe_int(opponent_blob.get("id"), 0) if isinstance(opponent_blob, dict) else 0

        if isinstance(team_blob, dict):
            team_blob["battingOrder"] = copy.deepcopy(team_batting_order)
            if team_id_in_game == away_id:
                team_blob["runs"] = safe_int(away_score.get("runs"), safe_int(team_blob.get("runs"), 0))
                team_blob["hits"] = safe_int(away_score.get("hits"), safe_int(team_blob.get("hits"), 0))
                team_blob["errors"] = safe_int(away_score.get("errors"), safe_int(team_blob.get("errors"), 0))
            elif team_id_in_game == home_id:
                team_blob["runs"] = safe_int(home_score.get("runs"), safe_int(team_blob.get("runs"), 0))
                team_blob["hits"] = safe_int(home_score.get("hits"), safe_int(team_blob.get("hits"), 0))
                team_blob["errors"] = safe_int(home_score.get("errors"), safe_int(team_blob.get("errors"), 0))

        if isinstance(opponent_blob, dict):
            opponent_blob["battingOrder"] = copy.deepcopy(opponent_batting_order)
            if opponent_id_in_game == away_id:
                opponent_blob["runs"] = safe_int(away_score.get("runs"), safe_int(opponent_blob.get("runs"), 0))
                opponent_blob["hits"] = safe_int(away_score.get("hits"), safe_int(opponent_blob.get("hits"), 0))
                opponent_blob["errors"] = safe_int(away_score.get("errors"), safe_int(opponent_blob.get("errors"), 0))
            elif opponent_id_in_game == home_id:
                opponent_blob["runs"] = safe_int(home_score.get("runs"), safe_int(opponent_blob.get("runs"), 0))
                opponent_blob["hits"] = safe_int(home_score.get("hits"), safe_int(opponent_blob.get("hits"), 0))
                opponent_blob["errors"] = safe_int(home_score.get("errors"), safe_int(opponent_blob.get("errors"), 0))


def get_upcoming_schedule(
    team_id: int,
    days_ahead: int,
    start_date: Optional[dt.date] = None,
) -> List[Dict[str, Any]]:
    anchor_date = start_date or board_today()
    end_date = anchor_date + dt.timedelta(days=max(1, days_ahead))

    payload = mlb_get(
        "/api/v1/schedule",
        params={
            "sportId": 1,
            "teamId": team_id,
            "startDate": anchor_date.isoformat(),
            "endDate": end_date.isoformat(),
            "hydrate": "linescore,team,probablePitcher",
        },
    )

    games: List[Dict[str, Any]] = []
    for date_entry in payload.get("dates", []):
        for game in date_entry.get("games", []):
            games.append(serialize_schedule_game(game, team_id))

    return sorted(games, key=lambda row: row.get("gameDate", ""))


def find_next_or_live_game(schedule_games: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not schedule_games:
        return None

    live_games = [game for game in schedule_games if game.get("status", {}).get("abstract") == "Live"]
    if live_games:
        return live_games[0]

    preview_games = [game for game in schedule_games if game.get("status", {}).get("abstract") == "Preview"]
    if preview_games:
        return preview_games[0]

    return schedule_games[0]


def extract_unique_game_ids(game_rows: List[Dict[str, Any]]) -> List[int]:
    unique_ids: List[int] = []
    seen = set()
    for row in game_rows:
        game_pk = safe_int(row.get("gamePk"), 0)
        if game_pk <= 0 or game_pk in seen:
            continue
        seen.add(game_pk)
        unique_ids.append(game_pk)
    return unique_ids


def choose_relevant_game(games: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not games:
        return None

    def game_state(game: Dict[str, Any]) -> str:
        return game.get("status", {}).get("abstractGameState", "")

    live_games = [g for g in games if game_state(g) == "Live"]
    if live_games:
        return sorted(live_games, key=lambda g: g.get("gameDate", ""))[0]

    preview_games = [g for g in games if game_state(g) == "Preview"]
    if preview_games:
        return sorted(preview_games, key=lambda g: g.get("gameDate", ""))[0]

    return sorted(games, key=lambda g: g.get("gameDate", ""), reverse=True)[0]


def parse_scoreboard(game: Dict[str, Any], feed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    status = game.get("status", {})
    teams = game.get("teams", {})
    away_team = teams.get("away", {}).get("team", {})
    home_team = teams.get("home", {}).get("team", {})

    linescore = game.get("linescore", {})
    line_teams = linescore.get("teams", {})
    away_line = line_teams.get("away", {})
    home_line = line_teams.get("home", {})

    scoreboard = {
        "gamePk": game.get("gamePk"),
        "isLive": status.get("abstractGameState") == "Live",
        "status": {
            "abstract": status.get("abstractGameState"),
            "detailed": status.get("detailedState"),
        },
        "startTime": game.get("gameDate"),
        "venue": game.get("venue", {}).get("name"),
        "away": {
            "name": away_team.get("name", "Away"),
            "abbrev": away_team.get("name", "AWY")[:3].upper(),
            "runs": safe_int(away_line.get("runs")),
            "hits": safe_int(away_line.get("hits")),
            "errors": safe_int(away_line.get("errors")),
        },
        "home": {
            "name": home_team.get("name", "Home"),
            "abbrev": home_team.get("name", "HME")[:3].upper(),
            "runs": safe_int(home_line.get("runs")),
            "hits": safe_int(home_line.get("hits")),
            "errors": safe_int(home_line.get("errors")),
        },
        "inning": {
            "state": linescore.get("inningState"),
            "number": safe_int(linescore.get("currentInning"), 0),
        },
        "count": {
            "balls": safe_int(linescore.get("balls")),
            "strikes": safe_int(linescore.get("strikes")),
            "outs": safe_int(linescore.get("outs")),
        },
    }

    if not feed:
        return scoreboard

    feed_game_data = feed.get("gameData", {})
    feed_teams = feed_game_data.get("teams", {})
    feed_linescore = feed.get("liveData", {}).get("linescore", {})
    feed_line_teams = feed_linescore.get("teams", {})
    feed_away = feed_line_teams.get("away", {})
    feed_home = feed_line_teams.get("home", {})

    away_data = feed_teams.get("away", {})
    home_data = feed_teams.get("home", {})

    scoreboard["away"]["name"] = away_data.get("name", scoreboard["away"]["name"])
    scoreboard["away"]["abbrev"] = away_data.get("abbreviation", scoreboard["away"]["abbrev"])
    scoreboard["home"]["name"] = home_data.get("name", scoreboard["home"]["name"])
    scoreboard["home"]["abbrev"] = home_data.get("abbreviation", scoreboard["home"]["abbrev"])

    scoreboard["away"]["runs"] = safe_int(feed_away.get("runs"), scoreboard["away"]["runs"])
    scoreboard["away"]["hits"] = safe_int(feed_away.get("hits"), scoreboard["away"]["hits"])
    scoreboard["away"]["errors"] = safe_int(feed_away.get("errors"), scoreboard["away"]["errors"])

    scoreboard["home"]["runs"] = safe_int(feed_home.get("runs"), scoreboard["home"]["runs"])
    scoreboard["home"]["hits"] = safe_int(feed_home.get("hits"), scoreboard["home"]["hits"])
    scoreboard["home"]["errors"] = safe_int(feed_home.get("errors"), scoreboard["home"]["errors"])

    scoreboard["inning"]["state"] = feed_linescore.get("inningState", scoreboard["inning"]["state"])
    scoreboard["inning"]["number"] = safe_int(
        feed_linescore.get("currentInning"),
        scoreboard["inning"]["number"],
    )
    scoreboard["count"]["balls"] = safe_int(feed_linescore.get("balls"), scoreboard["count"]["balls"])
    scoreboard["count"]["strikes"] = safe_int(
        feed_linescore.get("strikes"),
        scoreboard["count"]["strikes"],
    )
    scoreboard["count"]["outs"] = safe_int(feed_linescore.get("outs"), scoreboard["count"]["outs"])

    return scoreboard


def select_playback_url(playbacks: List[Dict[str, Any]]) -> Optional[str]:
    by_name = {}
    for item in playbacks:
        name = item.get("name")
        url = item.get("url")
        if name and url:
            by_name[name] = url

    for preferred in PLAYBACK_PRIORITY:
        if preferred in by_name:
            return by_name[preferred]

    for item in playbacks:
        url = item.get("url")
        if url:
            return url

    return None


def get_game_feed(game_pk: int) -> Optional[Dict[str, Any]]:
    try:
        return mlb_get(f"/api/v1.1/game/{game_pk}/feed/live")
    except requests.RequestException:
        return None


def get_game_feed_cached(game_pk: int, feed_cache: Dict[int, Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if game_pk in feed_cache:
        return feed_cache[game_pk]

    feed = get_game_feed(game_pk)
    feed_cache[game_pk] = feed
    return feed


def get_game_highlights(game_pk: int, limit: int = 10, max_age_hours: Optional[int] = None) -> List[Dict[str, Any]]:
    try:
        payload = mlb_get(f"/api/v1/game/{game_pk}/content")
    except requests.RequestException:
        return []

    highlights_root = payload.get("highlights") if isinstance(payload, dict) else None
    if not isinstance(highlights_root, dict):
        return []

    highlights_group = highlights_root.get("highlights")
    if not isinstance(highlights_group, dict):
        return []

    items = highlights_group.get("items")
    if not isinstance(items, list):
        return []

    clips: List[Dict[str, Any]] = []
    max_age_delta: Optional[dt.timedelta] = None
    if max_age_hours is not None and safe_int(max_age_hours, 0) > 0:
        max_age_delta = dt.timedelta(hours=max_age_hours)
    now_utc = dt.datetime.now(dt.timezone.utc)

    for item in items:
        if not isinstance(item, dict):
            continue

        published_at = str(item.get("date") or "").strip()
        published_dt = parse_iso_datetime(published_at)
        if max_age_delta is not None:
            if published_dt is None:
                continue
            clip_age = now_utc - published_dt
            if clip_age > max_age_delta:
                continue

        playbacks = item.get("playbacks")
        if not isinstance(playbacks, list):
            playbacks = []

        playback_url = select_playback_url(playbacks)
        if not playback_url:
            continue

        clips.append(
            {
                "id": item.get("id") or f"{game_pk}-{len(clips) + 1}",
                "title": item.get("headline") or "Padres highlight",
                "description": item.get("description") or "",
                "url": playback_url,
                "duration": item.get("duration") or "",
                "publishedAt": published_at,
                "gamePk": game_pk,
                "_publishedTs": published_dt.timestamp() if isinstance(published_dt, dt.datetime) else 0.0,
            }
        )

    clips.sort(key=lambda clip: safe_float(clip.get("_publishedTs"), 0.0), reverse=True)
    for clip in clips:
        clip.pop("_publishedTs", None)

    return clips[: max(1, limit)]


def recent_game_ids(team_id: int, lookback_days: int) -> List[int]:
    rows = get_recent_games(team_id, lookback_days)
    return extract_unique_game_ids(rows)


def build_highlight_pool(current_game_pk: Optional[int], recent_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    clips: List[Dict[str, Any]] = []
    seen_urls = set()

    def add_clips(items: List[Dict[str, Any]]) -> None:
        for clip in items:
            clip_url = clip.get("url")
            if not clip_url or clip_url in seen_urls:
                continue
            seen_urls.add(clip_url)
            clips.append(clip)
            if len(clips) >= MAX_HIGHLIGHTS:
                return

    if current_game_pk:
        add_clips(get_game_highlights(current_game_pk, limit=12))

    game_ids = recent_ids if recent_ids is not None else recent_game_ids(TEAM_ID, LOOKBACK_DAYS)
    for game_pk in game_ids:
        if len(clips) >= MAX_HIGHLIGHTS:
            break
        if current_game_pk and game_pk == current_game_pk:
            continue
        add_clips(get_game_highlights(game_pk, limit=6))

    return clips[:MAX_HIGHLIGHTS]


def find_most_recent_final_game(recent_games: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for game in recent_games:
        if game.get("abstractState") == "Final" and safe_int(game.get("gamePk"), 0) > 0:
            return game
    return None


def build_previous_game_story(game_meta: Dict[str, Any], feed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    story = {
        "gamePk": game_meta.get("gamePk"),
        "date": game_meta.get("officialDate") or game_meta.get("gameDate", "")[:10],
        "opponent": "",
        "venue": "",
        "result": game_meta.get("detailedState", "Final"),
        "padresLine": "",
        "playByPlay": [],
    }

    if not feed:
        return story

    game_data = feed.get("gameData", {})
    teams = game_data.get("teams", {})
    away_team = teams.get("away", {})
    home_team = teams.get("home", {})

    away_id = safe_int(away_team.get("id"), 0)
    padres_away = away_id == TEAM_ID

    story["opponent"] = home_team.get("name", "Opponent") if padres_away else away_team.get("name", "Opponent")
    story["venue"] = game_data.get("venue", {}).get("name", "")

    linescore = feed.get("liveData", {}).get("linescore", {})
    line_teams = linescore.get("teams", {})
    away_runs = safe_int(line_teams.get("away", {}).get("runs"), 0)
    home_runs = safe_int(line_teams.get("home", {}).get("runs"), 0)

    padres_runs = away_runs if padres_away else home_runs
    opponent_runs = home_runs if padres_away else away_runs
    result_letter = "W" if padres_runs > opponent_runs else "L" if padres_runs < opponent_runs else "T"
    story["result"] = f"{result_letter} {padres_runs}-{opponent_runs}"
    story["padresLine"] = f"Padres {padres_runs} - {opponent_runs} {story['opponent']}"

    plays_data = feed.get("liveData", {}).get("plays", {})
    all_plays = plays_data.get("allPlays", [])
    scoring_play_indexes = plays_data.get("scoringPlays", [])

    selected_plays: List[Dict[str, Any]] = []
    if scoring_play_indexes:
        for raw_index in scoring_play_indexes[-MAX_PLAY_BY_PLAY_ITEMS:]:
            index = safe_int(raw_index, -1)
            if 0 <= index < len(all_plays):
                selected_plays.append(all_plays[index])

    if not selected_plays:
        selected_plays = all_plays[-MAX_PLAY_BY_PLAY_ITEMS:]

    pbp_rows = []
    for play in selected_plays:
        about = play.get("about", {})
        result = play.get("result", {})
        batter = play.get("matchup", {}).get("batter", {})

        inning_num = safe_int(about.get("inning"), 0)
        half_inning = str(about.get("halfInning", "")).title()
        inning_label = f"{half_inning} {inning_num}".strip()

        pbp_rows.append(
            {
                "inning": inning_label,
                "event": result.get("event") or "Play",
                "batter": batter.get("fullName", ""),
                "description": result.get("description") or "",
            }
        )

    story["playByPlay"] = pbp_rows
    return story


def build_last_game_player_map(feed: Optional[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    if not feed:
        return {}

    players_map: Dict[int, Dict[str, Any]] = {}
    teams = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})

    for side in ("away", "home"):
        team_players = teams.get(side, {}).get("players", {})
        for player in team_players.values():
            person = player.get("person", {})
            player_id = safe_int(person.get("id"), 0)
            if player_id <= 0:
                continue

            batting = player.get("stats", {}).get("batting", {})
            at_bats = safe_int(batting.get("atBats"), 0)
            hits = safe_int(batting.get("hits"), 0)
            rbi = safe_int(batting.get("rbi"), 0)
            walks = safe_int(batting.get("baseOnBalls"), 0)
            strikeouts = safe_int(batting.get("strikeOuts"), 0)

            line = "Did not bat"
            if at_bats > 0:
                line = f"{hits}-{at_bats}"

            players_map[player_id] = {
                "line": line,
                "hits": hits,
                "atBats": at_bats,
                "rbi": rbi,
                "walks": walks,
                "strikeouts": strikeouts,
            }

    return players_map


def chunk_list(values: List[int], size: int) -> Iterable[List[int]]:
    if size <= 0:
        size = 1
    for index in range(0, len(values), size):
        yield values[index : index + size]


def get_team_roster(team_id: int) -> List[Dict[str, Any]]:
    try:
        payload = mlb_get(f"/api/v1/teams/{team_id}/roster", params={"rosterType": "active"})
    except requests.RequestException:
        return []

    roster = []
    for row in payload.get("roster", []):
        person = row.get("person", {})
        position = row.get("position", {})
        player_id = safe_int(person.get("id"), 0)
        if player_id <= 0:
            continue

        roster.append(
            {
                "playerId": player_id,
                "name": person.get("fullName", ""),
                "position": position.get("abbreviation", ""),
                "positionType": position.get("type", ""),
            }
        )

    return roster


def extract_group_stat(person: Dict[str, Any], group_name: str, stats_type: str = "") -> Dict[str, Any]:
    normalized_group = str(group_name or "").strip().lower()
    normalized_type = str(stats_type or "").strip().lower()

    for row in person.get("stats", []):
        group = row.get("group", {}) if isinstance(row.get("group"), dict) else {}
        display_name = str(group.get("displayName") or group.get("name") or "").strip().lower()
        if display_name != normalized_group:
            continue

        if normalized_type:
            row_type = row.get("type", {}) if isinstance(row.get("type"), dict) else {}
            type_name = str(row_type.get("displayName") or row_type.get("name") or "").strip().lower()
            if type_name != normalized_type:
                continue

        splits = row.get("splits", [])
        if splits:
            return splits[0].get("stat", {})

    return {}


def fetch_people_with_stats(person_ids: List[int], season: int, include_advanced: bool = False) -> Dict[int, Dict[str, Any]]:
    people_by_id: Dict[int, Dict[str, Any]] = {}
    if not person_ids:
        return people_by_id

    for chunk in chunk_list(person_ids, 25):
        person_ids_text = ",".join(str(player_id) for player_id in chunk)
        stats_types = "season,seasonAdvanced" if include_advanced else "season"
        params = {
            "personIds": person_ids_text,
            "hydrate": f"stats(group=[hitting,pitching],type=[{stats_types}],season=[{season}])",
        }

        try:
            payload = mlb_get("/api/v1/people", params=params)
        except requests.RequestException:
            continue

        for person in payload.get("people", []):
            person_id = safe_int(person.get("id"), 0)
            if person_id <= 0:
                continue
            people_by_id[person_id] = person

    return people_by_id


def build_team_player_stats(team_id: int, fallback_team_name: str) -> Dict[str, Any]:
    roster = get_team_roster(team_id)
    roster_ids = [row["playerId"] for row in roster if row.get("playerId")]
    season = board_season()
    people_by_id = fetch_people_with_stats(roster_ids, season, include_advanced=True)

    team_name = fallback_team_name
    for person in people_by_id.values():
        for stats_row in person.get("stats", []):
            splits = stats_row.get("splits", [])
            if not splits:
                continue
            candidate = splits[0].get("team", {}).get("name")
            if candidate:
                team_name = candidate
                break
        if team_name != fallback_team_name:
            break

    players: List[Dict[str, Any]] = []
    for row in roster:
        player_id = safe_int(row.get("playerId"), 0)
        person = people_by_id.get(player_id, {})

        full_name = person.get("fullName") or row.get("name") or "Unknown Player"
        hitting_standard = extract_group_stat(person, "hitting", "season")
        pitching_standard = extract_group_stat(person, "pitching", "season")
        hitting_advanced = extract_group_stat(person, "hitting", "seasonadvanced")
        pitching_advanced = extract_group_stat(person, "pitching", "seasonadvanced")

        if not hitting_standard:
            hitting_standard = extract_group_stat(person, "hitting")
        if not pitching_standard:
            pitching_standard = extract_group_stat(person, "pitching")

        hitting = copy.deepcopy(hitting_standard) if isinstance(hitting_standard, dict) else {}
        pitching = copy.deepcopy(pitching_standard) if isinstance(pitching_standard, dict) else {}

        if isinstance(hitting_advanced, dict):
            for key, value in hitting_advanced.items():
                if key not in hitting or hitting.get(key) in (None, "", "--"):
                    hitting[key] = value

        if isinstance(pitching_advanced, dict):
            for key, value in pitching_advanced.items():
                if key not in pitching or pitching.get(key) in (None, "", "--"):
                    pitching[key] = value

        players.append(
            {
                "playerId": player_id,
                "name": full_name,
                "displayName": full_name,
                "position": row.get("position", ""),
                "positionType": row.get("positionType", ""),
                "hitting": hitting,
                "pitching": pitching,
                "headshotUrl": (
                    "https://img.mlbstatic.com/mlb-photos/image/upload/"
                    f"w_400,q_auto:best/v1/people/{player_id}/headshot/67/current"
                ),
            }
        )

    players = sorted(players, key=lambda player: player.get("name", ""))
    return {
        "teamId": team_id,
        "teamName": team_name,
        "players": players,
    }


def build_hitting_leaders(players: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for player in players:
        hitting = player.get("hitting", {})
        at_bats = safe_int(hitting.get("atBats"), 0)
        if at_bats <= 0:
            continue

        avg_text = str(hitting.get("avg") or ".000")
        ops_text = str(hitting.get("ops") or ".000")
        rows.append(
            {
                "playerId": player.get("playerId"),
                "name": player.get("name", ""),
                "displayName": player.get("displayName", player.get("name", "")),
                "position": player.get("position", ""),
                "avg": avg_text,
                "ops": ops_text,
                "homeRuns": safe_int(hitting.get("homeRuns"), 0),
                "rbi": safe_int(hitting.get("rbi"), 0),
                "hits": safe_int(hitting.get("hits"), 0),
                "atBats": at_bats,
                "_ops": parse_rate(ops_text, 0.0),
                "_avg": parse_rate(avg_text, 0.0),
            }
        )

    rows = sorted(rows, key=lambda row: (row["_ops"], row["_avg"], row["hits"]), reverse=True)
    top_rows = rows[: max(1, limit)]
    for row in top_rows:
        row.pop("_ops", None)
        row.pop("_avg", None)
    return top_rows


def build_pitching_leaders(players: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for player in players:
        pitching = player.get("pitching", {})
        innings_text = str(pitching.get("inningsPitched") or "0.0")
        innings_value = innings_to_decimal(innings_text)
        if innings_value <= 0:
            continue

        era_text = str(pitching.get("era") or "9.99")
        whip_text = str(pitching.get("whip") or "1.99")

        rows.append(
            {
                "playerId": player.get("playerId"),
                "name": player.get("name", ""),
                "displayName": player.get("displayName", player.get("name", "")),
                "position": player.get("position", ""),
                "era": era_text,
                "whip": whip_text,
                "strikeouts": safe_int(pitching.get("strikeOuts"), 0),
                "wins": safe_int(pitching.get("wins"), 0),
                "losses": safe_int(pitching.get("losses"), 0),
                "inningsPitched": innings_text,
                "_era": parse_rate(era_text, 99.0),
                "_ip": innings_value,
            }
        )

    rows = sorted(rows, key=lambda row: (row["_era"], -row["_ip"], -row["strikeouts"]))
    top_rows = rows[: max(1, limit)]
    for row in top_rows:
        row.pop("_era", None)
        row.pop("_ip", None)
    return top_rows


def team_games_played_fallback_from_players(players: List[Dict[str, Any]]) -> int:
    max_games = 0
    for player in players:
        if not isinstance(player, dict):
            continue

        hitting = player.get("hitting") if isinstance(player.get("hitting"), dict) else {}
        pitching = player.get("pitching") if isinstance(player.get("pitching"), dict) else {}

        max_games = max(max_games, safe_int(hitting.get("gamesPlayed"), 0), safe_int(pitching.get("gamesPlayed"), 0))

    return max_games


def get_team_games_played_for_season(team_id: int, season: int) -> int:
    if team_id <= 0 or season <= 0:
        return 0

    try:
        payload = mlb_get(
            "/api/v1/standings",
            params={
                "leagueId": "103,104",
                "season": season,
                "standingsTypes": "regularSeason",
            },
        )
    except requests.RequestException:
        return 0

    for record in payload.get("records", []) if isinstance(payload, dict) else []:
        if not isinstance(record, dict):
            continue
        for team_record in record.get("teamRecords", []):
            if not isinstance(team_record, dict):
                continue
            current_team_id = safe_int(team_record.get("team", {}).get("id"), 0)
            if current_team_id != team_id:
                continue

            games_played = safe_int(team_record.get("gamesPlayed"), 0)
            if games_played > 0:
                return games_played

            wins = safe_int(team_record.get("wins"), 0)
            losses = safe_int(team_record.get("losses"), 0)
            total_games = wins + losses
            if total_games > 0:
                return total_games

    return 0


def parse_hitting_leaderboard_categories(raw_value: Any) -> List[str]:
    text = str(raw_value or "").strip()
    if not text:
        return list(DEFAULT_HITTING_LEADERBOARD_CATEGORIES)

    chosen: List[str] = []
    seen = set()
    for token in text.split(","):
        normalized = str(token or "").strip().lower().replace("-", "").replace("_", "")
        if not normalized:
            continue

        canonical = HITTING_LEADERBOARD_CATEGORY_ALIASES.get(normalized)
        if not canonical or canonical in seen:
            continue

        seen.add(canonical)
        chosen.append(canonical)

    if chosen:
        return chosen
    return list(DEFAULT_HITTING_LEADERBOARD_CATEGORIES)


def parse_pitching_leaderboard_categories(raw_value: Any) -> List[str]:
    text = str(raw_value or "").strip()
    if not text:
        return list(DEFAULT_PITCHING_LEADERBOARD_CATEGORIES)

    chosen: List[str] = []
    seen = set()
    for token in text.split(","):
        raw_token = str(token or "").strip().lower().replace("-", "").replace("_", "")
        if not raw_token:
            continue

        canonical = ""
        if "%" in raw_token:
            percent_token = raw_token.replace("%", "")
            if percent_token in {"k", "kpct", "kpercent", "kpercenthigh", "khigh"}:
                canonical = "kPercentHigh"

        normalized = raw_token.replace("%", "")
        if not canonical:
            canonical = PITCHING_LEADERBOARD_CATEGORY_ALIASES.get(normalized)

        if not canonical or canonical in seen:
            continue

        seen.add(canonical)
        chosen.append(canonical)

    if chosen:
        return chosen
    return list(DEFAULT_PITCHING_LEADERBOARD_CATEGORIES)


def build_hitting_leader_rows(
    players: List[Dict[str, Any]],
    team_name: str,
    team_games_played: int,
    qualified_only: bool,
) -> Dict[str, Any]:
    min_plate_appearances = round(
        max(0.0, float(team_games_played) * max(0.0, HITTING_QUALIFYING_PA_PER_TEAM_GAME)),
        1,
    )

    rows: List[Dict[str, Any]] = []
    for player in players:
        if not isinstance(player, dict):
            continue

        hitting = player.get("hitting") if isinstance(player.get("hitting"), dict) else {}
        if not hitting:
            continue

        plate_appearances = safe_int(hitting.get("plateAppearances"), safe_int(hitting.get("plate_appearances"), 0))
        at_bats = safe_int(hitting.get("atBats"), safe_int(hitting.get("at_bats"), 0))
        if plate_appearances <= 0 and at_bats <= 0:
            continue

        strike_outs = safe_int(hitting.get("strikeOuts"), safe_int(hitting.get("strike_outs"), 0))
        k_percent = (strike_outs / plate_appearances) if plate_appearances > 0 else None

        qualified_hitter = plate_appearances >= min_plate_appearances if min_plate_appearances > 0 else plate_appearances > 0
        if qualified_only and not qualified_hitter:
            continue

        avg_text = str(hitting.get("avg") or ".000")
        ops_text = str(hitting.get("ops") or ".000")

        rows.append(
            {
                "playerId": safe_int(player.get("playerId"), 0),
                "name": player.get("name", ""),
                "displayName": player.get("displayName", player.get("name", "")),
                "position": player.get("position", ""),
                "teamName": team_name,
                "headshotUrl": str(player.get("headshotUrl") or "").strip(),
                "gamesPlayed": safe_int(hitting.get("gamesPlayed"), safe_int(hitting.get("games_played"), 0)),
                "plateAppearances": plate_appearances,
                "plate_appearances": plate_appearances,
                "atBats": at_bats,
                "avg": avg_text,
                "ops": ops_text,
                "homeRuns": safe_int(hitting.get("homeRuns"), safe_int(hitting.get("home_runs"), 0)),
                "rbi": safe_int(hitting.get("rbi"), 0),
                "hits": safe_int(hitting.get("hits"), 0),
                "strikeOuts": strike_outs,
                "kPercent": round(k_percent, 4) if k_percent is not None else None,
                "k_percent": round(k_percent, 4) if k_percent is not None else None,
                "kPercentDisplay": f"{(k_percent * 100.0):.1f}%" if k_percent is not None else "--",
                "qualifiedHitter": qualified_hitter,
                "qualificationThresholdPA": min_plate_appearances,
            }
        )

    return {
        "rows": rows,
        "minPlateAppearances": min_plate_appearances,
    }


def sort_hitting_rows_for_category(rows: List[Dict[str, Any]], category: str) -> List[Dict[str, Any]]:
    if category == "ops":
        return sorted(
            rows,
            key=lambda row: (
                parse_rate(row.get("ops"), 0.0),
                parse_rate(row.get("avg"), 0.0),
                safe_int(row.get("plateAppearances"), 0),
                safe_int(row.get("homeRuns"), 0),
            ),
            reverse=True,
        )

    if category == "avg":
        return sorted(
            rows,
            key=lambda row: (
                parse_rate(row.get("avg"), 0.0),
                parse_rate(row.get("ops"), 0.0),
                safe_int(row.get("hits"), 0),
                safe_int(row.get("plateAppearances"), 0),
            ),
            reverse=True,
        )

    if category == "homeRuns":
        return sorted(
            rows,
            key=lambda row: (
                safe_int(row.get("homeRuns"), 0),
                safe_int(row.get("rbi"), 0),
                parse_rate(row.get("ops"), 0.0),
                safe_int(row.get("plateAppearances"), 0),
            ),
            reverse=True,
        )

    if category == "kPercentLow":
        def k_percent_sort_value(row: Dict[str, Any]) -> float:
            parsed = parse_numeric_value(row.get("kPercent"))
            return parsed if parsed is not None else 9.99

        return sorted(
            rows,
            key=lambda row: (
                k_percent_sort_value(row),
                -safe_int(row.get("plateAppearances"), 0),
                -parse_rate(row.get("ops"), 0.0),
                -safe_int(row.get("homeRuns"), 0),
            ),
        )

    return list(rows)


def build_visual_scene_hitting_leaderboards_payload(
    team_id: int,
    count: int,
    qualified_only: bool,
    categories: List[str],
    season: int,
) -> Dict[str, Any]:
    fallback_team_name = TEAM_NAME if team_id == TEAM_ID else f"Team {team_id}"
    base = get_team_base_data_cached(team_id, fallback_team_name, max(count, AUTO_LEADER_COUNT))

    resolved_team_id = safe_int(base.get("teamId"), team_id)
    resolved_team_name = str(base.get("teamName") or fallback_team_name).strip() or fallback_team_name
    players = base.get("players") if isinstance(base.get("players"), list) else []

    team_games_played = get_team_games_played_for_season(resolved_team_id, season)
    if team_games_played <= 0:
        team_games_played = team_games_played_fallback_from_players(players)

    normalized_categories = categories if categories else list(DEFAULT_HITTING_LEADERBOARD_CATEGORIES)
    row_result = build_hitting_leader_rows(players, resolved_team_name, team_games_played, qualified_only)
    rows = row_result.get("rows") if isinstance(row_result.get("rows"), list) else []
    min_plate_appearances = safe_float(row_result.get("minPlateAppearances"), 0.0)

    leaderboards: List[Dict[str, Any]] = []
    leaders_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for category in normalized_categories:
        sorted_rows = sort_hitting_rows_for_category(rows, category)
        leaders = [copy.deepcopy(row) for row in sorted_rows[:count]]

        leaderboards.append(
            {
                "category": category,
                "title": HITTING_LEADERBOARD_CATEGORY_TITLES.get(category, category),
                "leaders": leaders,
            }
        )
        leaders_by_category[category] = leaders

    primary_leaders = copy.deepcopy(leaderboards[0].get("leaders", [])) if leaderboards else []

    starter_min_ip = round(max(0.0, float(team_games_played) * max(0.0, PITCHING_QUALIFYING_IP_PER_TEAM_GAME)), 1)
    reliever_min_ip = round(max(0.0, float(team_games_played) * max(0.0, RELIEF_PITCHING_QUALIFYING_IP_PER_TEAM_GAME)), 1)

    return {
        "generatedAtUtc": utc_now_iso(),
        "teamId": resolved_team_id,
        "teamName": resolved_team_name,
        "leaderType": "hitting",
        "season": season,
        "count": count,
        "qualifiedOnly": qualified_only,
        "categories": normalized_categories,
        "teamGamesPlayed": team_games_played,
        "qualification": {
            "qualifiedOnly": qualified_only,
            "hitter": {
                "plateAppearancesPerTeamGame": HITTING_QUALIFYING_PA_PER_TEAM_GAME,
                "teamGamesPlayed": team_games_played,
                "minPlateAppearances": min_plate_appearances,
            },
            "pitcher": {
                "inningsPerTeamGame": PITCHING_QUALIFYING_IP_PER_TEAM_GAME,
                "relieverInningsPerTeamGame": RELIEF_PITCHING_QUALIFYING_IP_PER_TEAM_GAME,
                "teamGamesPlayed": team_games_played,
                "starterMinInningsPitched": starter_min_ip,
                "relieverMinInningsPitched": reliever_min_ip,
            },
        },
        "theme": team_theme_colors(resolved_team_id),
        "logoUrls": team_logo_urls(resolved_team_id),
        "leaders": primary_leaders,
        "leadersByCategory": leaders_by_category,
        "leaderboards": leaderboards,
    }


def load_pitcher_season_rows_by_player_ids(player_ids: List[int], season: int) -> Dict[int, Dict[str, Any]]:
    unique_ids = sorted({safe_int(player_id, 0) for player_id in player_ids if safe_int(player_id, 0) > 0})
    if not unique_ids:
        return {}

    database_path = resolve_database_path()
    if not database_path.exists():
        return {}

    rows_by_player: Dict[int, Dict[str, Any]] = {}
    try:
        with open_database_connection() as connection:
            tables = sqlite_table_names(connection)
            if "pitcher_stats_season" not in tables:
                return {}

            columns = sqlite_table_columns(connection, "pitcher_stats_season")
            if "player_id" not in columns:
                return {}

            placeholders = ",".join("?" for _ in unique_ids)
            has_season = "season" in columns
            has_games_played = "games_played" in columns
            games_order = "COALESCE(games_played, 0) DESC" if has_games_played else "player_id ASC"

            if has_season:
                rows_for_season = rows_to_dicts(
                    connection.execute(
                        f"""
                        SELECT *
                        FROM pitcher_stats_season
                        WHERE player_id IN ({placeholders})
                          AND season = ?
                        ORDER BY player_id ASC,
                                 {games_order}
                        """,
                        tuple(unique_ids) + (season,),
                    ).fetchall()
                )
            else:
                rows_for_season = rows_to_dicts(
                    connection.execute(
                        f"""
                        SELECT *
                        FROM pitcher_stats_season
                        WHERE player_id IN ({placeholders})
                        ORDER BY player_id ASC,
                                 {games_order}
                        """,
                        tuple(unique_ids),
                    ).fetchall()
                )

            for row in rows_for_season:
                player_id = safe_int(row.get("player_id"), 0)
                if player_id > 0 and player_id not in rows_by_player:
                    rows_by_player[player_id] = row

            if has_season:
                missing_ids = [player_id for player_id in unique_ids if player_id not in rows_by_player]
                if missing_ids:
                    missing_placeholders = ",".join("?" for _ in missing_ids)
                    fallback_rows = rows_to_dicts(
                        connection.execute(
                            f"""
                            SELECT *
                            FROM pitcher_stats_season
                            WHERE player_id IN ({missing_placeholders})
                            ORDER BY player_id ASC,
                                     season DESC,
                                     {games_order}
                            """,
                            tuple(missing_ids),
                        ).fetchall()
                    )

                    for row in fallback_rows:
                        player_id = safe_int(row.get("player_id"), 0)
                        if player_id > 0 and player_id not in rows_by_player:
                            rows_by_player[player_id] = row
    except sqlite3.Error:
        return {}

    return rows_by_player


def build_pitching_leader_rows(
    players: List[Dict[str, Any]],
    team_name: str,
    team_games_played: int,
    qualified_only: bool,
    season: int,
) -> Dict[str, Any]:
    starter_min_innings = round(
        max(0.0, float(team_games_played) * max(0.0, PITCHING_QUALIFYING_IP_PER_TEAM_GAME)),
        1,
    )
    reliever_min_innings = round(
        max(0.0, float(team_games_played) * max(0.0, RELIEF_PITCHING_QUALIFYING_IP_PER_TEAM_GAME)),
        1,
    )
    active_min_innings = reliever_min_innings

    player_ids = [safe_int(player.get("playerId"), 0) for player in players if isinstance(player, dict)]
    db_pitching_rows = load_pitcher_season_rows_by_player_ids(player_ids, season)

    rows: List[Dict[str, Any]] = []
    for player in players:
        if not isinstance(player, dict):
            continue

        player_id = safe_int(player.get("playerId"), 0)
        db_pitching = (
            db_pitching_rows.get(player_id)
            if player_id > 0 and isinstance(db_pitching_rows.get(player_id), dict)
            else {}
        )

        pitching = player.get("pitching") if isinstance(player.get("pitching"), dict) else {}
        if not pitching and not db_pitching:
            continue

        innings_text = str(
            first_present_stat_value(
                pitching,
                ["inningsPitched", "innings_pitched"],
                fallback=first_present_stat_value(db_pitching, ["inningsPitched", "innings_pitched"], fallback="0.0"),
            )
            or "0.0"
        )
        innings_value = innings_to_decimal(innings_text)
        if innings_value <= 0:
            continue

        qualified_pitcher = innings_value >= active_min_innings if active_min_innings > 0 else innings_value > 0
        if qualified_only and not qualified_pitcher:
            continue

        era_text = str(
            first_present_stat_value(
                pitching,
                ["era"],
                fallback=first_present_stat_value(db_pitching, ["era"], fallback="--"),
            )
            or "--"
        )
        # Prefer DB/Fangraphs FIP when available; MLB roster payload is often missing or less reliable for FIP.
        fip_text = str(
            first_present_stat_value(
                db_pitching,
                ["fip"],
                fallback=first_present_stat_value(pitching, ["fip"], fallback="--"),
            )
            or "--"
        ).strip() or "--"
        whip_text = str(
            first_present_stat_value(
                pitching,
                ["whip"],
                fallback=first_present_stat_value(db_pitching, ["whip"], fallback="--"),
            )
            or "--"
        )
        strikeouts = safe_int(
            first_present_stat_value(
                pitching,
                ["strikeOuts", "strike_outs"],
                fallback=first_present_stat_value(db_pitching, ["strikeOuts", "strike_outs"], fallback=0),
            ),
            0,
        )
        batters_faced = safe_int(
            first_present_stat_value(
                pitching,
                ["battersFaced", "batters_faced"],
                fallback=first_present_stat_value(db_pitching, ["battersFaced", "batters_faced"], fallback=0),
            ),
            0,
        )
        raw_k_percent = parse_numeric_value(
            first_present_stat_value(
                pitching,
                ["kPercent", "k_percent", "strikeoutPercentage", "strikeout_percentage"],
                fallback=first_present_stat_value(
                    db_pitching,
                    ["kPercent", "k_percent", "strikeoutPercentage", "strikeout_percentage"],
                    fallback=None,
                ),
            )
        )
        k_percent_value = None
        if raw_k_percent is not None:
            k_percent_value = raw_k_percent / 100.0 if raw_k_percent > 1.0 else raw_k_percent
        elif batters_faced > 0:
            k_percent_value = strikeouts / batters_faced

        if k_percent_value is not None:
            k_percent_value = max(0.0, min(1.0, k_percent_value))

        wins = safe_int(
            first_present_stat_value(
                pitching,
                ["wins"],
                fallback=first_present_stat_value(db_pitching, ["wins"], fallback=0),
            ),
            0,
        )
        losses = safe_int(
            first_present_stat_value(
                pitching,
                ["losses"],
                fallback=first_present_stat_value(db_pitching, ["losses"], fallback=0),
            ),
            0,
        )

        rows.append(
            {
                "playerId": player_id,
                "name": player.get("name", ""),
                "displayName": player.get("displayName", player.get("name", "")),
                "position": player.get("position", ""),
                "teamName": team_name,
                "headshotUrl": str(player.get("headshotUrl") or "").strip(),
                "gamesPlayed": safe_int(pitching.get("gamesPlayed"), safe_int(pitching.get("games_played"), 0)),
                "inningsPitched": innings_text,
                "era": era_text,
                "fip": fip_text,
                "whip": whip_text,
                "strikeouts": strikeouts,
                "battersFaced": batters_faced,
                "kPercent": round(k_percent_value, 4) if k_percent_value is not None else None,
                "k_percent": round(k_percent_value, 4) if k_percent_value is not None else None,
                "kPercentDisplay": f"{(k_percent_value * 100.0):.1f}%" if k_percent_value is not None else "--",
                "wins": wins,
                "losses": losses,
                "qualifiedPitcher": qualified_pitcher,
                "qualificationThresholdIP": active_min_innings,
                "starterQualificationThresholdIP": starter_min_innings,
                "relieverQualificationThresholdIP": reliever_min_innings,
            }
        )

    return {
        "rows": rows,
        "starterMinInningsPitched": starter_min_innings,
        "relieverMinInningsPitched": reliever_min_innings,
        "activeMinInningsPitched": active_min_innings,
    }


def sort_pitching_rows_for_category(rows: List[Dict[str, Any]], category: str) -> List[Dict[str, Any]]:
    def k_percent_sort_value(row: Dict[str, Any]) -> float:
        parsed = parse_numeric_value(row.get("kPercent"))
        return parsed if parsed is not None else -1.0

    if category == "fip":
        return sorted(
            rows,
            key=lambda row: (
                parse_rate(row.get("fip"), 999.0),
                -safe_int(row.get("strikeouts"), 0),
                -innings_to_decimal(str(row.get("inningsPitched") or "0.0")),
                parse_rate(row.get("era"), 999.0),
            ),
        )

    if category == "era":
        return sorted(
            rows,
            key=lambda row: (
                parse_rate(row.get("era"), 999.0),
                -safe_int(row.get("strikeouts"), 0),
                -innings_to_decimal(str(row.get("inningsPitched") or "0.0")),
                parse_rate(row.get("fip"), 999.0),
            ),
        )

    if category == "strikeouts":
        return sorted(
            rows,
            key=lambda row: (
                safe_int(row.get("strikeouts"), 0),
                k_percent_sort_value(row),
                innings_to_decimal(str(row.get("inningsPitched") or "0.0")),
                parse_rate(row.get("fip"), -1.0),
                parse_rate(row.get("era"), -1.0),
            ),
            reverse=True,
        )

    if category == "kPercentHigh":
        return sorted(
            rows,
            key=lambda row: (
                k_percent_sort_value(row),
                safe_int(row.get("strikeouts"), 0),
                innings_to_decimal(str(row.get("inningsPitched") or "0.0")),
                parse_rate(row.get("fip"), -1.0),
                parse_rate(row.get("era"), -1.0),
            ),
            reverse=True,
        )

    return list(rows)


def build_visual_scene_pitching_leaderboards_payload(
    team_id: int,
    count: int,
    qualified_only: bool,
    categories: List[str],
    season: int,
) -> Dict[str, Any]:
    fallback_team_name = TEAM_NAME if team_id == TEAM_ID else f"Team {team_id}"
    base = get_team_base_data_cached(team_id, fallback_team_name, max(count, AUTO_LEADER_COUNT))

    resolved_team_id = safe_int(base.get("teamId"), team_id)
    resolved_team_name = str(base.get("teamName") or fallback_team_name).strip() or fallback_team_name
    players = base.get("players") if isinstance(base.get("players"), list) else []

    team_games_played = get_team_games_played_for_season(resolved_team_id, season)
    if team_games_played <= 0:
        team_games_played = team_games_played_fallback_from_players(players)

    normalized_categories = categories if categories else list(DEFAULT_PITCHING_LEADERBOARD_CATEGORIES)
    row_result = build_pitching_leader_rows(players, resolved_team_name, team_games_played, qualified_only, season)
    rows = row_result.get("rows") if isinstance(row_result.get("rows"), list) else []
    starter_min_ip = safe_float(row_result.get("starterMinInningsPitched"), 0.0)
    reliever_min_ip = safe_float(row_result.get("relieverMinInningsPitched"), 0.0)
    active_min_ip = safe_float(row_result.get("activeMinInningsPitched"), 0.0)

    leaderboards: List[Dict[str, Any]] = []
    leaders_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for category in normalized_categories:
        sorted_rows = sort_pitching_rows_for_category(rows, category)
        leaders = [copy.deepcopy(row) for row in sorted_rows[:count]]

        leaderboards.append(
            {
                "category": category,
                "title": PITCHING_LEADERBOARD_CATEGORY_TITLES.get(category, category),
                "leaders": leaders,
            }
        )
        leaders_by_category[category] = leaders

    primary_leaders = copy.deepcopy(leaderboards[0].get("leaders", [])) if leaderboards else []
    min_plate_appearances = round(
        max(0.0, float(team_games_played) * max(0.0, HITTING_QUALIFYING_PA_PER_TEAM_GAME)),
        1,
    )

    return {
        "generatedAtUtc": utc_now_iso(),
        "teamId": resolved_team_id,
        "teamName": resolved_team_name,
        "leaderType": "pitching",
        "season": season,
        "count": count,
        "qualifiedOnly": qualified_only,
        "categories": normalized_categories,
        "teamGamesPlayed": team_games_played,
        "qualification": {
            "qualifiedOnly": qualified_only,
            "hitter": {
                "plateAppearancesPerTeamGame": HITTING_QUALIFYING_PA_PER_TEAM_GAME,
                "teamGamesPlayed": team_games_played,
                "minPlateAppearances": min_plate_appearances,
            },
            "pitcher": {
                "inningsPerTeamGame": PITCHING_QUALIFYING_IP_PER_TEAM_GAME,
                "relieverInningsPerTeamGame": RELIEF_PITCHING_QUALIFYING_IP_PER_TEAM_GAME,
                "teamGamesPlayed": team_games_played,
                "starterMinInningsPitched": starter_min_ip,
                "relieverMinInningsPitched": reliever_min_ip,
                "activeMinInningsPitched": active_min_ip,
            },
        },
        "theme": team_theme_colors(resolved_team_id),
        "logoUrls": team_logo_urls(resolved_team_id),
        "leaders": primary_leaders,
        "leadersByCategory": leaders_by_category,
        "leaderboards": leaderboards,
    }


def hot_meter_label(score: int) -> str:
    if score >= 85:
        return "Scorching"
    if score >= 65:
        return "Hot"
    if score >= 45:
        return "Warm"
    if score >= 25:
        return "Cool"
    return "Cold"


def select_highlights_for_player(player_name: str, highlights: List[Dict[str, Any]], limit: int = 4) -> List[Dict[str, Any]]:
    if not highlights:
        return []

    lowered_name = player_name.lower().strip()
    lowered_last = lowered_name.split(" ")[-1] if lowered_name else ""

    chosen: List[Dict[str, Any]] = []
    for clip in highlights:
        haystack = f"{clip.get('title', '')} {clip.get('description', '')}".lower()
        if lowered_name and lowered_name in haystack:
            chosen.append(clip)
        elif lowered_last and lowered_last in haystack:
            chosen.append(clip)

        if len(chosen) >= limit:
            return chosen[:limit]

    return highlights[:limit]


def build_player_breakdown_stat_snapshot_from_team_row(
    is_pitcher: bool,
    hitting_stats: Any,
    pitching_stats: Any,
) -> Dict[str, Any]:
    hitting = hitting_stats if isinstance(hitting_stats, dict) else {}
    pitching = pitching_stats if isinstance(pitching_stats, dict) else {}

    batter_season = {
        "plate_appearances": first_present_stat_value(hitting, ["plateAppearances", "plate_appearances"], ""),
        "games_played": first_present_stat_value(hitting, ["gamesPlayed", "games_played"], ""),
        "avg": first_present_stat_value(hitting, ["avg"], ""),
        "obp": first_present_stat_value(hitting, ["obp"], ""),
        "slg": first_present_stat_value(hitting, ["slg"], ""),
        "ops": first_present_stat_value(hitting, ["ops"], ""),
        "home_runs": first_present_stat_value(hitting, ["homeRuns", "home_runs"], ""),
        "k_percent": first_present_stat_value(hitting, ["kPercent", "k_percent"], ""),
        "bb_percent": first_present_stat_value(hitting, ["bbPercent", "bb_percent"], ""),
    }

    pitcher_season = {
        "era": first_present_stat_value(pitching, ["era"], ""),
        "whip": first_present_stat_value(pitching, ["whip"], ""),
        "fip": first_present_stat_value(pitching, ["fip"], ""),
        "strike_outs": first_present_stat_value(pitching, ["strikeOuts", "strike_outs"], ""),
        "k_percent": first_present_stat_value(pitching, ["kPercent", "k_percent"], ""),
        "bb_percent": first_present_stat_value(pitching, ["bbPercent", "bb_percent"], ""),
        "wins": first_present_stat_value(pitching, ["wins"], ""),
        "losses": first_present_stat_value(pitching, ["losses"], ""),
        "innings_pitched": first_present_stat_value(pitching, ["inningsPitched", "innings_pitched"], ""),
    }

    return {
        "isPitcher": bool(is_pitcher),
        "batterSeason": batter_season,
        "pitcherSeason": pitcher_season,
        # Runtime template fetches may fail intermittently; keep shape stable in slide payload.
        "batterLastTenGames": {},
        "pitcherLastTenGames": {},
    }


def build_player_breakdowns(
    players: List[Dict[str, Any]],
    previous_player_map: Dict[int, Dict[str, Any]],
    highlight_pool: List[Dict[str, Any]],
    count: int,
    team_name: str,
) -> List[Dict[str, Any]]:
    if count <= 0:
        return []

    hitter_rows: List[Dict[str, Any]] = []
    for player in players:
        hitting = player.get("hitting", {})
        pitching = player.get("pitching", {})
        at_bats = safe_int(hitting.get("atBats"), 0)
        if at_bats <= 0:
            continue

        ops_text = stat_text(hitting, "ops", ".000")
        avg_text = stat_text(hitting, "avg", ".000")
        obp_text = stat_text(hitting, "obp", ".000")
        war_text = stat_text(hitting, "war", "N/A")
        fip_text = stat_text(pitching, "fip", "N/A")
        home_runs = safe_int(hitting.get("homeRuns"), 0)
        rbi = safe_int(hitting.get("rbi"), 0)
        hits = safe_int(hitting.get("hits"), 0)

        ops_value = parse_rate(ops_text, 0.0)
        meter = max(0, min(100, int(round(ops_value * 100))))

        player_id = safe_int(player.get("playerId"), 0)
        player_display_name = str(player.get("displayName") or player.get("name") or "").strip()
        previous = previous_player_map.get(player_id, {})
        previous_bits = []
        if previous.get("line"):
            previous_bits.append(previous["line"])
        if safe_int(previous.get("rbi"), 0) > 0:
            previous_bits.append(f"{safe_int(previous.get('rbi'), 0)} RBI")
        if safe_int(previous.get("walks"), 0) > 0:
            previous_bits.append(f"{safe_int(previous.get('walks'), 0)} BB")
        if safe_int(previous.get("strikeouts"), 0) > 0:
            previous_bits.append(f"{safe_int(previous.get('strikeouts'), 0)} SO")

        hitter_rows.append(
            {
                "playerId": player_id,
                "name": player_display_name,
                "displayName": player_display_name,
                "position": player.get("position", ""),
                "teamName": team_name,
                "headshotUrl": player.get("headshotUrl", ""),
                "isPitcher": False,
                "avg": avg_text,
                "obp": obp_text,
                "ops": ops_text,
                "war": war_text,
                "fip": fip_text,
                "hittingStats": hitting if isinstance(hitting, dict) else {},
                "pitchingStats": pitching if isinstance(pitching, dict) else {},
                "stats": build_player_breakdown_stat_snapshot_from_team_row(False, hitting, pitching),
                "seasonLine": f"AVG {avg_text} | OPS {ops_text} | HR {home_runs} | RBI {rbi}",
                "advancedLine": f"OBP {obp_text} | OPS {ops_text} | WAR {war_text} | FIP {fip_text}",
                "lastGameLine": " | ".join(previous_bits) if previous_bits else "No previous game line available",
                "hotMeter": meter,
                "hotLabel": hot_meter_label(meter),
                "highlights": select_highlights_for_player(player_display_name, highlight_pool, limit=4),
                "_score": (ops_value * 1000.0) + (rbi * 2.0) + hits,
            }
        )

    hitter_rows = sorted(hitter_rows, key=lambda row: row["_score"], reverse=True)

    if len(hitter_rows) < count:
        pitcher_rows: List[Dict[str, Any]] = []
        for player in players:
            pitching = player.get("pitching", {})
            hitting = player.get("hitting", {})
            innings_text = str(pitching.get("inningsPitched") or "0.0")
            innings_value = innings_to_decimal(innings_text)
            if innings_value <= 0:
                continue

            era_text = stat_text(pitching, "era", "N/A")
            whip_text = stat_text(pitching, "whip", "N/A")
            fip_text = stat_text(pitching, "fip", "N/A")
            war_text = stat_text(pitching, "war", stat_text(hitting, "war", "N/A"))
            obp_text = stat_text(hitting, "obp", "N/A")
            ops_text = stat_text(hitting, "ops", "N/A")
            strikeouts = safe_int(pitching.get("strikeOuts"), 0)

            era_value = parse_rate(era_text, 9.99)
            meter = max(0, min(100, int(round(((5.5 - era_value) / 5.5) * 100.0))))

            player_id = safe_int(player.get("playerId"), 0)
            player_display_name = str(player.get("displayName") or player.get("name") or "").strip()
            pitcher_rows.append(
                {
                    "playerId": player_id,
                    "name": player_display_name,
                    "displayName": player_display_name,
                    "position": player.get("position", ""),
                    "teamName": team_name,
                    "headshotUrl": player.get("headshotUrl", ""),
                    "isPitcher": True,
                    "era": era_text,
                    "whip": whip_text,
                    "obp": obp_text,
                    "ops": ops_text,
                    "war": war_text,
                    "fip": fip_text,
                    "hittingStats": hitting if isinstance(hitting, dict) else {},
                    "pitchingStats": pitching if isinstance(pitching, dict) else {},
                    "stats": build_player_breakdown_stat_snapshot_from_team_row(True, hitting, pitching),
                    "seasonLine": f"ERA {era_text} | WHIP {whip_text} | SO {strikeouts}",
                    "advancedLine": f"OBP {obp_text} | OPS {ops_text} | WAR {war_text} | FIP {fip_text}",
                    "lastGameLine": previous_player_map.get(player_id, {}).get("line", "No previous game line available"),
                    "hotMeter": meter,
                    "hotLabel": hot_meter_label(meter),
                    "highlights": select_highlights_for_player(player_display_name, highlight_pool, limit=4),
                    "_score": (100.0 - (era_value * 12.0)) + strikeouts,
                }
            )

        pitcher_rows = sorted(pitcher_rows, key=lambda row: row["_score"], reverse=True)
        for row in pitcher_rows:
            hitter_rows.append(row)
            if len(hitter_rows) >= count:
                break

    selected_rows = hitter_rows[:count]
    for row in selected_rows:
        row.pop("_score", None)
    return selected_rows


def build_all_qualified_player_breakdowns(
    players: List[Dict[str, Any]],
    previous_player_map: Dict[int, Dict[str, Any]],
    highlight_pool: List[Dict[str, Any]],
    team_name: str,
    team_id: int,
    season: int,
) -> List[Dict[str, Any]]:
    if not players:
        return []

    team_games_played = get_team_games_played_for_season(team_id, season)
    if team_games_played <= 0:
        team_games_played = team_games_played_fallback_from_players(players)

    hitting_result = build_hitting_leader_rows(players, team_name, team_games_played, qualified_only=False)
    pitching_result = build_pitching_leader_rows(
        players,
        team_name,
        team_games_played,
        qualified_only=False,
        season=season,
    )

    qualified_player_ids = {
        safe_int(row.get("playerId"), 0)
        for row in (hitting_result.get("rows") if isinstance(hitting_result.get("rows"), list) else [])
        if row.get("qualifiedHitter")
    }
    qualified_player_ids.update(
        safe_int(row.get("playerId"), 0)
        for row in (pitching_result.get("rows") if isinstance(pitching_result.get("rows"), list) else [])
        if row.get("qualifiedPitcher")
    )
    qualified_player_ids.discard(0)

    if not qualified_player_ids:
        return []

    candidate_count = max(1, len(players) * 3)
    candidates = build_player_breakdowns(players, previous_player_map, highlight_pool, candidate_count, team_name)

    selected: List[Dict[str, Any]] = []
    seen_ids = set()
    for player_payload in candidates:
        player_id = safe_int(player_payload.get("playerId"), 0)
        if player_id <= 0 or player_id in seen_ids or player_id not in qualified_player_ids:
            continue
        seen_ids.add(player_id)
        selected.append(player_payload)

    selected.sort(key=lambda row: str(row.get("displayName") or row.get("name") or "").lower())
    return selected


def apply_player_breakdown_stat_preferences(player_payload: Dict[str, Any], template: Dict[str, Any]) -> Dict[str, Any]:
    payload = copy.deepcopy(player_payload)
    is_pitcher = bool(payload.get("isPitcher"))

    missing_value = str(template.get("missingStatValue", "N/A")).strip() or "N/A"
    item_separator = str(template.get("statSeparator", " | "))
    label_value_separator = str(template.get("statLabelValueSeparator", " "))

    label_overrides: Dict[str, str] = {}
    raw_labels = template.get("statLabels")
    if isinstance(raw_labels, dict):
        for key, value in raw_labels.items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            value_text = str(value or "").strip()
            if not value_text:
                continue
            label_overrides[key_text] = value_text

    default_keys = (
        DEFAULT_PLAYER_BREAKDOWN_PITCHER_STAT_KEYS if is_pitcher else DEFAULT_PLAYER_BREAKDOWN_HITTER_STAT_KEYS
    )

    preset = resolve_player_breakdown_preset(template, is_pitcher)
    preset_keys = preset.get("keys") if isinstance(preset, dict) else []
    preset_name = str(preset.get("name", "")).strip() if isinstance(preset, dict) else ""

    base_keys = normalize_stat_keys(template.get("statKeys"), preset_keys if preset_keys else default_keys)
    scoped_key_source = template.get("pitcherStatKeys") if is_pitcher else template.get("hitterStatKeys")
    selected_keys = normalize_stat_keys(scoped_key_source, base_keys)

    entries = build_player_stat_entries(payload, selected_keys, missing_value, label_overrides)
    line = stat_line_from_entries(entries, item_separator, label_value_separator)

    payload["selectedStatPreset"] = preset_name
    payload["selectedStatKeys"] = selected_keys
    payload["selectedStats"] = entries
    payload["selectedStatsLine"] = line
    payload["selectedStatsMissingValue"] = missing_value

    if line:
        payload["seasonLine"] = line

    return payload


def build_team_base_data(team_id: int, fallback_team_name: str, leader_count: int) -> Dict[str, Any]:
    team_data = build_team_player_stats(team_id, fallback_team_name)
    players = team_data.get("players", [])

    return {
        "teamId": team_data.get("teamId", team_id),
        "teamName": team_data.get("teamName", fallback_team_name),
        "players": players,
        "hittingLeaders": build_hitting_leaders(players, limit=leader_count),
        "pitchingLeaders": build_pitching_leaders(players, limit=leader_count),
    }


def get_team_base_data_cached(team_id: int, fallback_team_name: str, leader_count: int) -> Dict[str, Any]:
    now = time.time()
    with _team_stats_lock:
        cached = _team_stats_cache.get(team_id)
        if cached:
            age = now - safe_float(cached.get("updated_at"), 0.0)
            cached_leader_count = safe_int(cached.get("leaderCount"), leader_count)
            if age < TEAM_STATS_CACHE_TTL_SECONDS and cached_leader_count == leader_count:
                return copy.deepcopy(cached.get("data", {}))

    fresh = build_team_base_data(team_id, fallback_team_name, leader_count)
    with _team_stats_lock:
        _team_stats_cache[team_id] = {
            "updated_at": now,
            "leaderCount": leader_count,
            "data": fresh,
        }

    return copy.deepcopy(fresh)


def build_team_bundle(
    team_id: int,
    fallback_team_name: str,
    previous_player_map: Dict[int, Dict[str, Any]],
    highlight_pool: List[Dict[str, Any]],
    leader_count: int,
    player_slide_count: int,
    include_all_qualified_player_breakdowns: bool = False,
    season: int = 0,
) -> Dict[str, Any]:
    base = get_team_base_data_cached(team_id, fallback_team_name, leader_count)

    resolved_team_id = safe_int(base.get("teamId"), team_id)
    resolved_team_name = str(base.get("teamName") or fallback_team_name).strip() or fallback_team_name
    players = base.get("players", []) if isinstance(base.get("players"), list) else []
    resolved_season = season if season > 0 else board_season()

    if include_all_qualified_player_breakdowns:
        player_breakdowns = build_all_qualified_player_breakdowns(
            players,
            previous_player_map,
            highlight_pool,
            resolved_team_name,
            resolved_team_id,
            resolved_season,
        )
    else:
        player_breakdowns = build_player_breakdowns(
            players,
            previous_player_map,
            highlight_pool,
            player_slide_count,
            resolved_team_name,
        )

    base["playerBreakdowns"] = player_breakdowns
    return base


def get_venue_with_location(venue_id: int) -> Optional[Dict[str, Any]]:
    if venue_id <= 0:
        return None

    try:
        payload = mlb_get("/api/v1/venues", params={"venueIds": venue_id, "hydrate": "location"})
    except requests.RequestException:
        return None

    venues = payload.get("venues", [])
    if not venues:
        return None
    return venues[0]


def weather_code_label(code: int) -> str:
    labels = {
        0: "Clear",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Freezing fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Heavy drizzle",
        61: "Light rain",
        63: "Rain",
        65: "Heavy rain",
        71: "Light snow",
        73: "Snow",
        75: "Heavy snow",
        80: "Rain showers",
        81: "Rain showers",
        82: "Heavy showers",
        95: "Thunderstorm",
    }
    return labels.get(code, "Unknown")


def empty_game_weather_payload() -> Dict[str, Any]:
    return {
        "available": False,
        "message": "Weather forecast unavailable",
        "venue": "",
        "cityState": "",
        "forecastTimeLocal": "",
        "temperatureC": None,
        "temperatureF": None,
        "feelsLikeC": None,
        "feelsLikeF": None,
        "precipProbability": None,
        "windSpeedKph": None,
        "weatherCode": None,
        "condition": "",
    }


def get_weather_for_scheduled_game(scheduled_game: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not WEATHER_ENABLED or not scheduled_game:
        return None

    game_date_text = str(scheduled_game.get("gameDate", ""))
    if not game_date_text:
        return None

    venue_id = safe_int(scheduled_game.get("venueId"), 0)
    venue = get_venue_with_location(venue_id)
    if not venue:
        return None

    location = venue.get("location", {})
    coords = location.get("defaultCoordinates", {})
    latitude = safe_float(coords.get("latitude"), 0.0)
    longitude = safe_float(coords.get("longitude"), 0.0)
    if latitude == 0.0 and longitude == 0.0:
        return None

    try:
        game_dt_utc = dt.datetime.fromisoformat(game_date_text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if game_dt_utc.tzinfo is None:
        game_dt_utc = game_dt_utc.replace(tzinfo=dt.timezone.utc)
    else:
        game_dt_utc = game_dt_utc.astimezone(dt.timezone.utc)

    try:
        weather_payload = weather_get(
            {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": "temperature_2m,apparent_temperature,precipitation_probability,weather_code,wind_speed_10m",
                "timezone": "auto",
                "forecast_days": 3,
            }
        )
    except requests.RequestException:
        return None

    hourly = weather_payload.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return None

    utc_offset_seconds = safe_int(weather_payload.get("utc_offset_seconds"), 0)

    closest_index = 0
    closest_seconds = float("inf")
    for index, raw_time in enumerate(times):
        try:
            local_time = dt.datetime.fromisoformat(str(raw_time))
        except ValueError:
            continue

        as_utc = local_time - dt.timedelta(seconds=utc_offset_seconds)
        as_utc = as_utc.replace(tzinfo=dt.timezone.utc)
        diff = abs((as_utc - game_dt_utc).total_seconds())
        if diff < closest_seconds:
            closest_seconds = diff
            closest_index = index

    temperature_c = safe_float(hourly.get("temperature_2m", [0])[closest_index], 0.0)
    feels_like_c = safe_float(hourly.get("apparent_temperature", [temperature_c])[closest_index], temperature_c)
    precip_probability = safe_int(hourly.get("precipitation_probability", [0])[closest_index], 0)
    weather_code = safe_int(hourly.get("weather_code", [0])[closest_index], 0)
    wind_speed_kph = safe_float(hourly.get("wind_speed_10m", [0])[closest_index], 0.0)

    location_bits = [location.get("city", ""), location.get("stateAbbrev", "")]
    city_state = ", ".join(bit for bit in location_bits if bit)

    return {
        "available": True,
        "venue": venue.get("name", ""),
        "cityState": city_state,
        "forecastTimeLocal": times[closest_index],
        "temperatureC": round(temperature_c, 1),
        "temperatureF": round((temperature_c * 9.0 / 5.0) + 32.0, 1),
        "feelsLikeC": round(feels_like_c, 1),
        "feelsLikeF": round((feels_like_c * 9.0 / 5.0) + 32.0, 1),
        "precipProbability": precip_probability,
        "windSpeedKph": round(wind_speed_kph, 1),
        "weatherCode": weather_code,
        "condition": weather_code_label(weather_code),
    }


def get_weather_for_next_game(next_game: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return get_weather_for_scheduled_game(next_game)


def find_player_in_feed_by_id(feed: Dict[str, Any], player_id: int) -> Optional[Dict[str, Any]]:
    boxscore_teams = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    for side in ("away", "home"):
        players = boxscore_teams.get(side, {}).get("players", {})
        for player in players.values():
            person = player.get("person", {})
            if safe_int(person.get("id"), 0) == player_id:
                return player
    return None


def find_featured_player_in_feed(feed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    boxscore_teams = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})

    for side in ("away", "home"):
        players = boxscore_teams.get(side, {}).get("players", {})
        for player in players.values():
            person = player.get("person", {})
            player_name = str(person.get("fullName", "")).strip()
            player_id = safe_int(person.get("id"), 0)

            if FEATURED_PLAYER_ID > 0 and player_id == FEATURED_PLAYER_ID:
                return player

            if FEATURED_PLAYER_ID <= 0 and FEATURED_PLAYER_NAME and FEATURED_PLAYER_NAME.lower() in player_name.lower():
                return player

    return None


def player_plate_appearance_events(feed: Dict[str, Any], player_id: int, limit: int = 8) -> List[str]:
    events: List[str] = []
    all_plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
    for play in all_plays:
        batter_id = safe_int(play.get("matchup", {}).get("batter", {}).get("id"), 0)
        if batter_id != player_id:
            continue

        result = play.get("result", {})
        event_name = result.get("event") or result.get("eventType") or "Plate Appearance"
        events.append(str(event_name).title())
        if len(events) >= limit:
            break

    return events


def calculate_player_trends(
    player_id: int,
    recent_games: List[Dict[str, Any]],
    feed_cache: Dict[int, Optional[Dict[str, Any]]],
) -> Dict[str, Any]:
    final_games = [game for game in recent_games if game.get("abstractState") == "Final"]
    samples: List[Dict[str, int]] = []

    for game in final_games[:10]:
        game_pk = safe_int(game.get("gamePk"), 0)
        if game_pk <= 0:
            continue

        feed = get_game_feed_cached(game_pk, feed_cache)
        if not feed:
            continue

        player = find_player_in_feed_by_id(feed, player_id)
        if not player:
            continue

        batting = player.get("stats", {}).get("batting", {})
        at_bats = safe_int(batting.get("atBats"), 0)
        hits = safe_int(batting.get("hits"), 0)

        if at_bats <= 0 and hits <= 0:
            continue

        samples.append({"hits": hits, "atBats": at_bats})

    streak = 0
    for sample in samples:
        if sample["hits"] > 0:
            streak += 1
        else:
            break

    hot_window = samples[: max(1, HOT_STREAK_WINDOW)]
    total_hits = sum(sample["hits"] for sample in hot_window)
    total_at_bats = sum(sample["atBats"] for sample in hot_window)
    average = (total_hits / total_at_bats) if total_at_bats > 0 else 0.0
    meter = max(0, min(100, int(round((average / 0.400) * 100))))

    return {
        "hitStreak": streak,
        "hotMeter": meter,
        "hotLabel": hot_meter_label(meter),
        "recentAverage": f"{average:.3f}",
        "windowGames": len(hot_window),
    }


def build_featured_player_card(
    game_meta: Optional[Dict[str, Any]],
    feed: Optional[Dict[str, Any]],
    recent_games: List[Dict[str, Any]],
    feed_cache: Dict[int, Optional[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if not game_meta or not feed:
        return None

    player = find_featured_player_in_feed(feed)
    if not player:
        return None

    person = player.get("person", {})
    player_id = safe_int(person.get("id"), 0)
    player_name = person.get("fullName", FEATURED_PLAYER_NAME or "Featured Player")

    batting = player.get("stats", {}).get("batting", {})
    at_bats = safe_int(batting.get("atBats"), 0)
    hits = safe_int(batting.get("hits"), 0)
    rbi = safe_int(batting.get("rbi"), 0)
    walks = safe_int(batting.get("baseOnBalls"), 0)
    strikeouts = safe_int(batting.get("strikeOuts"), 0)
    doubles = safe_int(batting.get("doubles"), 0)
    triples = safe_int(batting.get("triples"), 0)
    home_runs = safe_int(batting.get("homeRuns"), 0)

    events = player_plate_appearance_events(feed, player_id, limit=8)
    trends = calculate_player_trends(player_id, recent_games, feed_cache)

    game_pk = safe_int(game_meta.get("gamePk"), 0)
    highlight_candidates = get_game_highlights(game_pk, limit=16) if game_pk > 0 else []
    related_highlights = select_highlights_for_player(player_name, highlight_candidates, limit=6)

    headshot_url = ""
    if player_id > 0:
        headshot_url = (
            "https://img.mlbstatic.com/mlb-photos/image/upload/"
            f"w_400,q_auto:best/v1/people/{player_id}/headshot/67/current"
        )

    return {
        "playerId": player_id,
        "name": player_name,
        "date": game_meta.get("officialDate") or game_meta.get("gameDate", "")[:10],
        "line": f"{hits}-{at_bats}",
        "hits": hits,
        "atBats": at_bats,
        "rbi": rbi,
        "walks": walks,
        "strikeouts": strikeouts,
        "doubles": doubles,
        "triples": triples,
        "homeRuns": home_runs,
        "events": events,
        "hitStreak": trends.get("hitStreak", 0),
        "hotStreakMeter": trends.get("hotMeter", 0),
        "hotStreakLabel": trends.get("hotLabel", "Warm"),
        "recentAverage": trends.get("recentAverage", "0.000"),
        "hotWindowGames": trends.get("windowGames", 0),
        "headshotUrl": headshot_url,
        "highlights": related_highlights,
    }


def resolve_kiosk_layout_path() -> Path:
    candidate = Path(KIOSK_LAYOUT_FILE or "static/kiosk-slides.json")
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parent / candidate


def load_kiosk_layout() -> Dict[str, Any]:
    layout = {
        "enabled": bool(DEFAULT_KIOSK_LAYOUT["enabled"]),
        "rotationSeconds": safe_int(DEFAULT_KIOSK_LAYOUT["rotationSeconds"], 14),
        "slides": [dict(slide) for slide in DEFAULT_KIOSK_LAYOUT["slides"]],
    }

    if not KIOSK_ENABLED:
        layout["enabled"] = False
        layout["slides"] = []
        return layout

    layout_path = resolve_kiosk_layout_path()
    if not layout_path.exists():
        return layout

    try:
        raw_data = json.loads(layout_path.read_text(encoding="utf-8"))
    except Exception:
        return layout

    if not isinstance(raw_data, dict):
        return layout

    layout["enabled"] = bool(raw_data.get("enabled", layout["enabled"]))
    layout["rotationSeconds"] = max(5, safe_int(raw_data.get("rotationSeconds"), layout["rotationSeconds"]))

    incoming_slides = raw_data.get("slides")
    if not isinstance(incoming_slides, list) or not incoming_slides:
        return layout

    parsed_slides = []
    for index, slide in enumerate(incoming_slides):
        if not isinstance(slide, dict):
            continue

        slide_type = str(slide.get("type", "")).strip()
        if slide_type not in ALLOWED_LAYOUT_SLIDE_TYPES:
            continue

        parsed_slides.append(
            {
                "id": str(slide.get("id", f"slide-{index + 1}")),
                "type": slide_type,
                "title": str(slide.get("title", slide_type.replace("_", " ").title())),
                "durationSeconds": max(5, safe_int(slide.get("durationSeconds"), layout["rotationSeconds"])),
            }
        )

    if parsed_slides:
        layout["slides"] = parsed_slides

    return layout


def resolve_template_file_path() -> Path:
    candidate = Path(KIOSK_TEMPLATE_FILE or "static/kiosk-templates.json")
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parent / candidate


def resolve_visual_scene_template_path() -> Path:
    candidate = Path(VISUAL_SCENE_TEMPLATE_FILE or "static/visual-scene-templates.json")
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parent / candidate


def load_visual_scene_template_config() -> Dict[str, Any]:
    config = copy.deepcopy(DEFAULT_VISUAL_SCENE_CONFIG)
    config_path = resolve_visual_scene_template_path()
    if not config_path.exists():
        return config

    try:
        raw_data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return config

    if not isinstance(raw_data, dict):
        return config

    merged = copy.deepcopy(config)
    for key, value in raw_data.items():
        merged[key] = value

    if not isinstance(merged.get("templates"), (dict, list)):
        merged["templates"] = copy.deepcopy(config["templates"])
    if not isinstance(merged.get("elementDefaults"), dict):
        merged["elementDefaults"] = copy.deepcopy(config["elementDefaults"])

    return merged


def validate_visual_scene_template_config(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return "Config must be a JSON object."

    templates = payload.get("templates")
    if not isinstance(templates, (dict, list)):
        return "Config must include a 'templates' object or array."

    if "slideTransitionMs" in payload and not isinstance(payload.get("slideTransitionMs"), (int, float)):
        return "'slideTransitionMs' must be numeric when provided."

    return None


def save_visual_scene_template_config(payload: Dict[str, Any]) -> Path:
    config_path = resolve_visual_scene_template_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = json.dumps(payload, indent=2)
    temp_path = config_path.with_suffix(f"{config_path.suffix}.tmp")
    temp_path.write_text(f"{serialized}\n", encoding="utf-8")
    temp_path.replace(config_path)

    return config_path


def load_kiosk_template_editor_config() -> Dict[str, Any]:
    config = copy.deepcopy(DEFAULT_SLIDE_TEMPLATE_CONFIG)
    template_path = resolve_template_file_path()
    if not template_path.exists():
        return config

    try:
        raw_data = json.loads(template_path.read_text(encoding="utf-8"))
    except Exception:
        return config

    if not isinstance(raw_data, dict):
        return config

    config["enabled"] = bool(raw_data.get("enabled", config["enabled"]))
    config["defaultDurationSeconds"] = max(
        5,
        safe_int(raw_data.get("defaultDurationSeconds"), safe_int(config["defaultDurationSeconds"], 14)),
    )

    incoming_templates = raw_data.get("templates")
    if not isinstance(incoming_templates, list):
        return config

    parsed_templates: List[Dict[str, Any]] = []
    for index, template in enumerate(incoming_templates):
        if not isinstance(template, dict):
            continue

        template_type = str(template.get("type", "")).strip()
        if template_type not in ALLOWED_TEMPLATE_TYPES:
            continue

        parsed = dict(template)
        parsed["id"] = str(template.get("id", f"template-{index + 1}"))
        parsed["type"] = template_type
        parsed["enabled"] = bool(template.get("enabled", True))
        parsed["durationSeconds"] = max(
            5,
            safe_int(template.get("durationSeconds"), safe_int(config["defaultDurationSeconds"], 14)),
        )
        parsed_templates.append(parsed)

    config["templates"] = parsed_templates
    return config


def validate_kiosk_template_config(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return "Config must be a JSON object."

    if "defaultDurationSeconds" in payload and not isinstance(payload.get("defaultDurationSeconds"), (int, float)):
        return "'defaultDurationSeconds' must be numeric when provided."

    templates = payload.get("templates")
    if not isinstance(templates, list):
        return "Config must include a 'templates' array."

    for index, template in enumerate(templates):
        if not isinstance(template, dict):
            return f"Template at index {index} must be an object."

        template_type = str(template.get("type", "")).strip()
        if template_type not in ALLOWED_TEMPLATE_TYPES:
            return f"Template at index {index} has unsupported type '{template_type}'."

    return None


def save_kiosk_template_config(payload: Dict[str, Any]) -> Path:
    template_path = resolve_template_file_path()
    template_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = json.dumps(payload, indent=2)
    temp_path = template_path.with_suffix(f"{template_path.suffix}.tmp")
    temp_path.write_text(f"{serialized}\n", encoding="utf-8")
    temp_path.replace(template_path)

    return template_path


def load_slide_templates() -> Dict[str, Any]:
    config = copy.deepcopy(DEFAULT_SLIDE_TEMPLATE_CONFIG)
    if not KIOSK_ENABLED:
        config["enabled"] = False
        config["templates"] = []
        return config

    template_path = resolve_template_file_path()
    if not template_path.exists():
        return config

    try:
        raw_data = json.loads(template_path.read_text(encoding="utf-8"))
    except Exception:
        return config

    if not isinstance(raw_data, dict):
        return config

    config["enabled"] = bool(raw_data.get("enabled", config["enabled"]))
    config["defaultDurationSeconds"] = max(
        5,
        safe_int(raw_data.get("defaultDurationSeconds"), safe_int(config["defaultDurationSeconds"], 14)),
    )

    incoming_templates = raw_data.get("templates")
    if not isinstance(incoming_templates, list) or not incoming_templates:
        return config

    parsed_templates: List[Dict[str, Any]] = []
    for index, template in enumerate(incoming_templates):
        if not isinstance(template, dict):
            continue

        template_type = str(template.get("type", "")).strip()
        if template_type not in ALLOWED_TEMPLATE_TYPES:
            continue

        parsed = dict(template)
        parsed["id"] = str(template.get("id", f"template-{index + 1}"))
        parsed["type"] = template_type
        parsed["enabled"] = bool(template.get("enabled", True))
        parsed["durationSeconds"] = max(
            5,
            safe_int(template.get("durationSeconds"), safe_int(config["defaultDurationSeconds"], 14)),
        )
        parsed_templates.append(parsed)

    if parsed_templates:
        config["templates"] = parsed_templates

    return config


def enabled_template_types(template_config: Dict[str, Any]) -> set:
    enabled_types = set()
    for template in template_config.get("templates", []):
        if not isinstance(template, dict):
            continue
        if bool(template.get("enabled", True)):
            enabled_types.add(str(template.get("type", "")))
    return enabled_types


def template_title_for_type(template_type: str) -> str:
    fallback = {
        "status": "Game Pulse",
        "live_game_status": "Live Game Center",
        "game_today": "Game Today",
        "schedule_overview": "Upcoming Schedule",
        "upcoming_weather": "Next Game Weather",
        "team_hitting_leaders": "Hitting Leaders",
        "team_pitching_leaders": "Pitching Leaders",
        "player_breakdowns": "Player Breakdowns",
        "previous_game_pbp": "Previous Game Story",
        "featured_player": "Featured Player Breakdown",
    }
    return fallback.get(template_type, template_type.replace("_", " ").title())


def build_live_game_status_payload(live_game: Dict[str, Any], highlight_limit: int = 12) -> Dict[str, Any]:
    score_blob = live_game.get("score") if isinstance(live_game.get("score"), dict) else {}
    live_blob = live_game.get("live") if isinstance(live_game.get("live"), dict) else {}
    status_blob = live_game.get("status") if isinstance(live_game.get("status"), dict) else {}
    score_status_blob = score_blob.get("status") if isinstance(score_blob.get("status"), dict) else {}

    away_blob = live_game.get("away") if isinstance(live_game.get("away"), dict) else {}
    home_blob = live_game.get("home") if isinstance(live_game.get("home"), dict) else {}
    team_blob = live_game.get("team") if isinstance(live_game.get("team"), dict) else {}
    opponent_blob = live_game.get("opponent") if isinstance(live_game.get("opponent"), dict) else {}

    inning_blob = score_blob.get("inning") if isinstance(score_blob.get("inning"), dict) else {}
    count_blob = score_blob.get("count") if isinstance(score_blob.get("count"), dict) else {}
    live_inning_blob = live_blob.get("inning") if isinstance(live_blob.get("inning"), dict) else {}
    live_count_blob = live_blob.get("count") if isinstance(live_blob.get("count"), dict) else {}

    inning_state = str(live_inning_blob.get("state") or inning_blob.get("state") or "").strip()
    inning_number = safe_int(live_inning_blob.get("number"), safe_int(inning_blob.get("number"), 0))
    balls = safe_int(live_count_blob.get("balls"), safe_int(count_blob.get("balls"), 0))
    strikes = safe_int(live_count_blob.get("strikes"), safe_int(count_blob.get("strikes"), 0))
    outs = safe_int(live_count_blob.get("outs"), safe_int(count_blob.get("outs"), 0))

    inning_label = f"{inning_state} {inning_number}".strip() if inning_state or inning_number > 0 else "Inning TBD"
    count_label = f"B {balls} | S {strikes} | O {outs}"

    status_abstract = str(score_status_blob.get("abstract") or status_blob.get("abstract") or "").strip()
    status_detailed = str(score_status_blob.get("detailed") or status_blob.get("detailed") or "").strip()
    is_live = bool(score_blob.get("isLive")) or status_abstract == "Live"

    base_runners = live_blob.get("baseRunners") if isinstance(live_blob.get("baseRunners"), dict) else {}
    if not base_runners:
        base_runners = {
            "first": None,
            "second": None,
            "third": None,
            "occupiedCount": 0,
            "occupancyCode": "000",
            "summary": "Bases empty",
        }

    indicator_payload = build_live_indicator_payload(balls, strikes, outs, base_runners)

    game_pk = safe_int(live_game.get("gamePk"), 0)
    highlights = (
        get_game_highlights(
            game_pk,
            limit=max(1, min(24, highlight_limit)),
            max_age_hours=LIVE_GAME_HIGHLIGHT_MAX_AGE_HOURS,
        )
        if game_pk > 0
        else []
    )

    theme_team_id = safe_int(team_blob.get("id"), 0) or TEAM_ID
    theme_payload = team_theme_colors(theme_team_id)
    at_bat_team = live_blob.get("atBatTeam") if isinstance(live_blob.get("atBatTeam"), dict) else {}
    fielding_team = live_blob.get("fieldingTeam") if isinstance(live_blob.get("fieldingTeam"), dict) else {}

    return {
        "gamePk": game_pk,
        "gameDate": str(live_game.get("gameDate") or "").strip(),
        "officialDate": str(live_game.get("officialDate") or "").strip(),
        "venue": str(live_game.get("venue") or "").strip(),
        "matchup": str(live_game.get("matchup") or "").strip(),
        "isLive": is_live,
        "status": {
            "abstract": status_abstract,
            "detailed": status_detailed,
        },
        "score": copy.deepcopy(score_blob),
        "inning": {
            "state": inning_state,
            "number": inning_number,
            "label": inning_label,
        },
        "count": {
            "balls": balls,
            "strikes": strikes,
            "outs": outs,
            "label": count_label,
        },
        "away": copy.deepcopy(away_blob),
        "home": copy.deepcopy(home_blob),
        "team": copy.deepcopy(team_blob),
        "opponent": copy.deepcopy(opponent_blob),
        "atBatTeam": copy.deepcopy(at_bat_team),
        "fieldingTeam": copy.deepcopy(fielding_team),
        "currentBatter": copy.deepcopy(live_blob.get("currentBatter")),
        "currentPitcher": copy.deepcopy(live_blob.get("currentPitcher")),
        "onDeck": copy.deepcopy(live_blob.get("onDeck")),
        "inHole": copy.deepcopy(live_blob.get("inHole")),
        "baseRunners": copy.deepcopy(base_runners),
        "basesSummary": str(base_runners.get("summary") or "Bases empty").strip(),
        "indicators": indicator_payload,
        "highlights": highlights,
        "hasHighlights": bool(highlights),
        "highlightCount": len(highlights),
        "theme": theme_payload,
        "logoUrls": team_logo_urls(theme_team_id),
    }


def generate_slides_from_templates(
    context: Dict[str, Any],
    template_config: Dict[str, Any],
    force_all_qualified_player_breakdowns: bool = False,
) -> List[Dict[str, Any]]:
    if not bool(template_config.get("enabled", True)):
        return []

    templates = template_config.get("templates", [])
    if not isinstance(templates, list):
        return []

    scoreboard = context.get("scoreboard") or {}
    today_games = context.get("todayGames") or []
    upcoming_games = context.get("upcomingGames") or []
    weather = context.get("weather")
    live_game = context.get("liveGame") if isinstance(context.get("liveGame"), dict) else None
    previous_game = context.get("previousGame")
    featured_player = context.get("featuredPlayer")
    team_bundles = context.get("teamBundles") or {}

    slides: List[Dict[str, Any]] = []

    for index, template in enumerate(templates):
        if not isinstance(template, dict):
            continue
        if not bool(template.get("enabled", True)):
            continue

        template_type = str(template.get("type", "")).strip()
        if template_type not in ALLOWED_TEMPLATE_TYPES:
            continue

        slide_id = str(template.get("id", f"template-slide-{index + 1}"))
        duration = max(5, safe_int(template.get("durationSeconds"), safe_int(template_config.get("defaultDurationSeconds"), 14)))
        title = str(template.get("title", template_title_for_type(template_type)))

        if template_type == "status":
            payload = {
                "statusText": scoreboard.get("status", {}).get("detailed") or "No live game right now",
                "inningState": scoreboard.get("inning", {}).get("state") or "",
                "inningNumber": safe_int(scoreboard.get("inning", {}).get("number"), 0),
                "count": scoreboard.get("count") or {"balls": 0, "strikes": 0, "outs": 0},
            }
            slides.append(
                {
                    "id": slide_id,
                    "type": "status",
                    "title": title,
                    "durationSeconds": duration,
                    "payload": payload,
                }
            )
            continue

        if template_type == "live_game_status":
            if not live_game:
                continue

            highlight_limit = max(1, min(24, safe_int(template.get("highlightLimit"), 12)))
            payload = build_live_game_status_payload(live_game, highlight_limit=highlight_limit)
            if not payload.get("isLive"):
                continue

            slides.append(
                {
                    "id": slide_id,
                    "type": "live_game_status",
                    "title": title,
                    "durationSeconds": duration,
                    "pinWhileActive": bool(template.get("pinWhenLive", True)),
                    "payload": payload,
                }
            )
            continue

        if template_type == "game_today":
            max_games = min(2, max(1, safe_int(template.get("maxGames"), 2)))
            selected_games = [copy.deepcopy(game) for game in today_games[:max_games] if isinstance(game, dict)]
            game_count = len(selected_games)
            if game_count > 1:
                headline = "Doubleheader Today"
            elif game_count == 1:
                headline = "Game Today"
            else:
                headline = "No Game Today"

            theme_team_id = TEAM_ID
            if selected_games:
                first_game = selected_games[0] if isinstance(selected_games[0], dict) else {}
                first_team_blob = first_game.get("team") if isinstance(first_game.get("team"), dict) else {}
                derived_team_id = safe_int(first_team_blob.get("id"), 0)
                if derived_team_id > 0:
                    theme_team_id = derived_team_id

            payload = {
                "date": board_today().isoformat(),
                "headline": headline,
                "hasGameToday": game_count > 0,
                "isDoubleheader": game_count > 1,
                "gameCount": game_count,
                "totalGamesToday": len(today_games),
                "games": selected_games,
                "theme": team_theme_colors(theme_team_id),
            }

            slides.append(
                {
                    "id": slide_id,
                    "type": "game_today",
                    "title": title,
                    "durationSeconds": duration,
                    "payload": payload,
                }
            )
            continue

        if template_type == "schedule_overview":
            max_games = max(2, safe_int(template.get("maxGames"), 6))
            theme_team_id = TEAM_ID
            team_name = TEAM_NAME

            first_upcoming = next((game for game in upcoming_games if isinstance(game, dict)), None)
            if first_upcoming:
                team_blob = first_upcoming.get("team") if isinstance(first_upcoming.get("team"), dict) else {}
                derived_team_id = safe_int(team_blob.get("id"), 0)
                if derived_team_id > 0:
                    theme_team_id = derived_team_id

                derived_team_name = str(team_blob.get("name") or "").strip()
                if derived_team_name:
                    team_name = derived_team_name

            payload_games = []
            for game in upcoming_games[:max_games]:
                if not isinstance(game, dict):
                    continue

                team_blob = game.get("team") if isinstance(game.get("team"), dict) else {}
                opponent_blob = game.get("opponent") if isinstance(game.get("opponent"), dict) else {}
                status_blob = game.get("status") if isinstance(game.get("status"), dict) else {}

                payload_games.append(
                    {
                        "gamePk": safe_int(game.get("gamePk"), 0),
                        "gameDate": game.get("gameDate", ""),
                        "officialDate": game.get("officialDate", ""),
                        "homeAway": game.get("homeAway", ""),
                        "opponentName": opponent_blob.get("name", "Opponent"),
                        "opponentAbbreviation": opponent_blob.get("abbreviation", ""),
                        "opponentLogoUrls": copy.deepcopy(opponent_blob.get("logoUrls", {})),
                        "opponentRecord": copy.deepcopy(game.get("opponentRecord", {})),
                        "teamName": team_blob.get("name", team_name),
                        "teamAbbreviation": team_blob.get("abbreviation", ""),
                        "teamLogoUrls": copy.deepcopy(team_blob.get("logoUrls", {})),
                        "teamRecord": copy.deepcopy(game.get("teamRecord", {})),
                        "status": status_blob.get("detailed", ""),
                        "statusAbstract": status_blob.get("abstract", ""),
                        "matchup": game.get("matchup", ""),
                        "venue": game.get("venue", ""),
                    }
                )

            slides.append(
                {
                    "id": slide_id,
                    "type": "schedule_overview",
                    "title": title,
                    "durationSeconds": duration,
                    "payload": {
                        "teamId": theme_team_id,
                        "teamName": team_name,
                        "theme": team_theme_colors(theme_team_id),
                        "logoUrls": team_logo_urls(theme_team_id),
                        "games": payload_games,
                        "empty": not bool(payload_games),
                    },
                }
            )
            continue

        if template_type == "upcoming_weather":
            payload = weather or {"unavailable": True, "message": "Weather forecast unavailable"}
            slides.append(
                {
                    "id": slide_id,
                    "type": "upcoming_weather",
                    "title": title,
                    "durationSeconds": duration,
                    "payload": payload,
                }
            )
            continue

        if template_type in {"team_hitting_leaders", "team_pitching_leaders", "player_breakdowns"}:
            team_key = str(template.get("team", "padres")).lower()
            if team_key == "opponent":
                team_bundle = team_bundles.get("opponent")
            elif team_key == "padres":
                team_bundle = team_bundles.get("padres")
            else:
                team_bundle = None
            if not team_bundle:
                continue

            count = max(1, safe_int(template.get("count"), AUTO_LEADER_COUNT))
            team_id_for_bundle = safe_int(team_bundle.get("teamId"), TEAM_ID)
            team_theme = team_theme_colors(team_id_for_bundle)
            team_logos = team_logo_urls(team_id_for_bundle)

            if template_type == "team_hitting_leaders":
                leaders = (team_bundle.get("hittingLeaders") or [])[:count]
                slides.append(
                    {
                        "id": slide_id,
                        "type": "team_hitting_leaders",
                        "title": title,
                        "durationSeconds": duration,
                        "payload": {
                            "teamId": team_id_for_bundle,
                            "teamName": team_bundle.get("teamName", "Team"),
                            "theme": team_theme,
                            "logoUrls": team_logos,
                            "leaders": leaders,
                        },
                    }
                )
                continue

            if template_type == "team_pitching_leaders":
                leaders = (team_bundle.get("pitchingLeaders") or [])[:count]
                slides.append(
                    {
                        "id": slide_id,
                        "type": "team_pitching_leaders",
                        "title": title,
                        "durationSeconds": duration,
                        "payload": {
                            "teamId": team_id_for_bundle,
                            "teamName": team_bundle.get("teamName", "Team"),
                            "theme": team_theme,
                            "logoUrls": team_logos,
                            "leaders": leaders,
                        },
                    }
                )
                continue

            if template_type == "player_breakdowns":
                players_source = team_bundle.get("playerBreakdowns") or []
                players = players_source if force_all_qualified_player_breakdowns else players_source[:count]
                for player_index, player_payload in enumerate(players):
                    slide_payload = apply_player_breakdown_stat_preferences(player_payload, template)
                    player_name = str(slide_payload.get("name", "Player"))
                    slides.append(
                        {
                            "id": f"{slide_id}-{player_index + 1}",
                            "type": "player_breakdown",
                            "title": f"{title}: {player_name}",
                            "durationSeconds": duration,
                            "payload": slide_payload,
                        }
                    )
                continue

        if template_type == "previous_game_pbp":
            if previous_game:
                slides.append(
                    {
                        "id": slide_id,
                        "type": "previous_game_pbp",
                        "title": title,
                        "durationSeconds": duration,
                        "payload": previous_game,
                    }
                )
            continue

        if template_type == "featured_player":
            if featured_player:
                slides.append(
                    {
                        "id": slide_id,
                        "type": "featured_player",
                        "title": title,
                        "durationSeconds": duration,
                        "payload": featured_player,
                    }
                )
            continue

    if scoreboard.get("isLive"):
        for slide in slides:
            if str(slide.get("type") or "").strip() != "live_game_status":
                continue
            if bool(slide.get("pinWhileActive", True)):
                return [slide]

    return slides


def build_kiosk_data(
    recent_games: List[Dict[str, Any]],
    highlights: List[Dict[str, Any]],
    scoreboard: Optional[Dict[str, Any]],
    force_all_qualified_player_breakdowns: bool = False,
    player_slide_count_override: Optional[int] = None,
) -> Dict[str, Any]:
    manual_layout = load_kiosk_layout()
    template_config = load_slide_templates()
    template_types = enabled_template_types(template_config)

    upcoming_games = get_upcoming_schedule(TEAM_ID, SCHEDULE_DAYS_AHEAD)
    today_games = [
        copy.deepcopy(game)
        for game in upcoming_games
        if isinstance(game, dict) and str(game.get("officialDate", "")) == board_today().isoformat()
    ]
    if today_games:
        enrich_team_games_endpoint_payload(TEAM_ID, today_games)

    live_game = next(
        (
            game
            for game in today_games
            if isinstance(game, dict)
            and (
                str((game.get("status") or {}).get("abstract") or "").strip() == "Live"
                or bool((game.get("score") or {}).get("isLive"))
            )
        ),
        None,
    )

    next_game = find_next_or_live_game(upcoming_games)
    weather = get_weather_for_next_game(next_game)

    recent_final_game = find_most_recent_final_game(recent_games)
    feed_cache: Dict[int, Optional[Dict[str, Any]]] = {}
    previous_feed = None
    previous_story = None
    previous_player_map: Dict[int, Dict[str, Any]] = {}

    if recent_final_game:
        game_pk = safe_int(recent_final_game.get("gamePk"), 0)
        previous_feed = get_game_feed_cached(game_pk, feed_cache) if game_pk > 0 else None
        previous_story = build_previous_game_story(recent_final_game, previous_feed)
        previous_player_map = build_last_game_player_map(previous_feed)

    featured_player = None
    if "featured_player" in template_types and recent_final_game and previous_feed:
        featured_player = build_featured_player_card(recent_final_game, previous_feed, recent_games, feed_cache)

    team_bundles: Dict[str, Dict[str, Any]] = {}
    current_season = board_season()
    resolved_player_slide_count = (
        max(1, safe_int(player_slide_count_override, AUTO_PLAYER_SLIDE_COUNT))
        if player_slide_count_override is not None
        else AUTO_PLAYER_SLIDE_COUNT
    )

    padres_bundle = build_team_bundle(
        TEAM_ID,
        TEAM_NAME,
        previous_player_map,
        highlights,
        AUTO_LEADER_COUNT,
        resolved_player_slide_count,
        include_all_qualified_player_breakdowns=force_all_qualified_player_breakdowns,
        season=current_season,
    )
    team_bundles["padres"] = padres_bundle

    if next_game:
        home_id = safe_int(next_game.get("home", {}).get("id"), 0)
        away_id = safe_int(next_game.get("away", {}).get("id"), 0)
        opponent_id = away_id if home_id == TEAM_ID else home_id
        opponent_name = next_game.get("opponent", {}).get("name", "Opponent")
        if opponent_id > 0 and opponent_id != TEAM_ID:
            opponent_bundle = build_team_bundle(
                opponent_id,
                opponent_name,
                previous_player_map,
                highlights,
                AUTO_LEADER_COUNT,
                resolved_player_slide_count,
                include_all_qualified_player_breakdowns=force_all_qualified_player_breakdowns,
                season=current_season,
            )
            team_bundles["opponent"] = opponent_bundle

    context = {
        "scoreboard": scoreboard,
        "todayGames": today_games,
        "upcomingGames": upcoming_games,
        "liveGame": live_game,
        "nextGame": next_game,
        "weather": weather,
        "previousGame": previous_story,
        "featuredPlayer": featured_player,
        "teamBundles": team_bundles,
    }

    auto_slides = generate_slides_from_templates(
        context,
        template_config,
        force_all_qualified_player_breakdowns=force_all_qualified_player_breakdowns,
    )
    if auto_slides:
        layout = {
            "enabled": True,
            "rotationSeconds": max(5, safe_int(template_config.get("defaultDurationSeconds"), 14)),
            "slides": [
                {
                    "id": slide.get("id", ""),
                    "type": slide.get("type", ""),
                    "title": slide.get("title", ""),
                    "durationSeconds": safe_int(slide.get("durationSeconds"), 14),
                }
                for slide in auto_slides
            ],
        }
        slide_source = "auto_templates"
    else:
        layout = manual_layout
        auto_slides = []
        slide_source = "manual_layout"

    return {
        "layout": layout,
        "slides": auto_slides,
        "templateSource": slide_source,
        "previousGame": previous_story,
        "featuredPlayer": featured_player,
        "todayGames": today_games,
        "nextGame": next_game,
        "weather": weather,
        "schedule": upcoming_games[:8],
        "teams": {
            "padres": {
                "teamId": padres_bundle.get("teamId", TEAM_ID),
                "teamName": padres_bundle.get("teamName", TEAM_NAME),
                "rosterSize": len(padres_bundle.get("players", [])),
            },
            "opponent": {
                "teamId": team_bundles.get("opponent", {}).get("teamId", 0),
                "teamName": team_bundles.get("opponent", {}).get("teamName", ""),
                "rosterSize": len(team_bundles.get("opponent", {}).get("players", [])),
            },
        },
    }


def build_state() -> Dict[str, Any]:
    games = get_today_games(TEAM_ID)
    game = choose_relevant_game(games)

    recent_games = get_recent_games(TEAM_ID, LOOKBACK_DAYS)
    recent_ids = extract_unique_game_ids(recent_games)

    scoreboard = None
    mode = "highlights"
    stream_url = ""
    current_game_pk = None

    if game:
        current_game_pk = safe_int(game.get("gamePk"), 0) or None
        feed = get_game_feed(current_game_pk) if current_game_pk else None

        scoreboard = parse_scoreboard(game, feed)

        if scoreboard.get("isLive") and LIVE_STREAM_URL:
            mode = "live_stream"
            stream_url = LIVE_STREAM_URL
        elif scoreboard.get("isLive"):
            mode = "highlights_with_scoreboard"
        else:
            mode = "highlights"

    highlights = build_highlight_pool(current_game_pk, recent_ids=recent_ids)
    kiosk = build_kiosk_data(recent_games, highlights, scoreboard)

    return apply_stat_decimal_precision(
        {
        "generatedAtUtc": utc_now_iso(),
        "localDate": board_today().isoformat(),
        "boardTimezone": BOARD_TIMEZONE_NAME,
        "teamId": TEAM_ID,
        "teamName": TEAM_NAME,
        "mode": mode,
        "streamUrl": stream_url,
        "scoreboard": scoreboard,
        "highlights": highlights,
        "kiosk": kiosk,
        "config": {
            "hasLiveStreamUrl": bool(LIVE_STREAM_URL),
            "lookbackDays": LOOKBACK_DAYS,
            "maxHighlights": MAX_HIGHLIGHTS,
            "featuredPlayerName": FEATURED_PLAYER_NAME,
            "kioskEnabled": KIOSK_ENABLED,
            "kioskTemplateFile": KIOSK_TEMPLATE_FILE,
            "visualSceneTemplateFile": VISUAL_SCENE_TEMPLATE_FILE,
            "scheduleDaysAhead": SCHEDULE_DAYS_AHEAD,
            "autoLeaderCount": AUTO_LEADER_COUNT,
            "autoPlayerSlideCount": AUTO_PLAYER_SLIDE_COUNT,
            "weatherEnabled": WEATHER_ENABLED,
            "playerNewsMaxHeadlines": PLAYER_NEWS_MAX_HEADLINES,
            "bettingOddsConfigured": bool(BETTINGPROS_BASE_URL),
            "bettingOddsSource": "BettingPros",
            "bettingOddsBaseUrl": BETTINGPROS_BASE_URL,
            "bettingOddsLocation": BETTINGPROS_LOCATION,
            "bettingOddsBookId": BETTINGPROS_BOOK_ID,
            "bettingOddsMarkets": BETTING_ODDS_MARKETS,
            "defaultPlayerBreakdownHitterStatKeys": list(DEFAULT_PLAYER_BREAKDOWN_HITTER_STAT_KEYS),
            "defaultPlayerBreakdownPitcherStatKeys": list(DEFAULT_PLAYER_BREAKDOWN_PITCHER_STAT_KEYS),
            "playerBreakdownStatPresets": copy.deepcopy(PLAYER_BREAKDOWN_STAT_PRESETS),
            "playerStatLabelOverrides": copy.deepcopy(PLAYER_STAT_LABEL_OVERRIDES),
        },
        }
    )


def get_state_cached() -> Dict[str, Any]:
    now = time.time()
    with _state_lock:
        cached_data = _state_cache.get("data")
        updated_at = _state_cache.get("updated_at", 0.0)
        if cached_data and (now - updated_at) < STATE_CACHE_TTL_SECONDS:
            return cached_data

    fresh_state = build_state()

    with _state_lock:
        _state_cache["data"] = fresh_state
        _state_cache["updated_at"] = now

    return fresh_state


def build_slides_state() -> Dict[str, Any]:
    games = get_today_games(TEAM_ID)
    game = choose_relevant_game(games)

    recent_games = get_recent_games(TEAM_ID, LOOKBACK_DAYS)
    scoreboard = None
    mode = "highlights"
    stream_url = ""

    if game:
        current_game_pk = safe_int(game.get("gamePk"), 0) or None
        feed = get_game_feed(current_game_pk) if current_game_pk else None
        scoreboard = parse_scoreboard(game, feed)
        if scoreboard.get("isLive") and LIVE_STREAM_URL:
            mode = "live_stream"
            stream_url = LIVE_STREAM_URL
        elif scoreboard.get("isLive"):
            mode = "highlights_with_scoreboard"

    kiosk = build_kiosk_data(
        recent_games,
        [],
        scoreboard,
        force_all_qualified_player_breakdowns=True,
    )

    return apply_stat_decimal_precision(
        {
            "generatedAtUtc": utc_now_iso(),
            "localDate": board_today().isoformat(),
            "boardTimezone": BOARD_TIMEZONE_NAME,
            "teamId": TEAM_ID,
            "teamName": TEAM_NAME,
            "mode": mode,
            "streamUrl": stream_url,
            "scoreboard": scoreboard,
            "highlights": [],
            "kiosk": kiosk,
            "config": {
                "kioskEnabled": KIOSK_ENABLED,
                "kioskTemplateFile": KIOSK_TEMPLATE_FILE,
                "visualSceneTemplateFile": VISUAL_SCENE_TEMPLATE_FILE,
                "slidesOnly": True,
                "playerBreakdownsAllQualified": True,
                "defaultPlayerBreakdownHitterStatKeys": list(DEFAULT_PLAYER_BREAKDOWN_HITTER_STAT_KEYS),
                "defaultPlayerBreakdownPitcherStatKeys": list(DEFAULT_PLAYER_BREAKDOWN_PITCHER_STAT_KEYS),
                "playerBreakdownStatPresets": copy.deepcopy(PLAYER_BREAKDOWN_STAT_PRESETS),
                "playerStatLabelOverrides": copy.deepcopy(PLAYER_STAT_LABEL_OVERRIDES),
            },
        }
    )


def get_slides_state_cached() -> Dict[str, Any]:
    now = time.time()
    with _state_lock:
        cached_data = _state_cache.get("slides_data")
        updated_at = _state_cache.get("slides_updated_at", 0.0)
        if cached_data and (now - updated_at) < STATE_CACHE_TTL_SECONDS:
            return cached_data

    fresh_state = build_slides_state()

    with _state_lock:
        _state_cache["slides_data"] = fresh_state
        _state_cache["slides_updated_at"] = now

    return fresh_state


def build_player_database_payload(
    player_id: int,
    season: int,
    requested_date: dt.date,
    requested_game_pk: int,
) -> Optional[Dict[str, Any]]:
    database_path = resolve_database_path()
    if not database_path.exists():
        raise FileNotFoundError(f"Database file not found: {database_path}")

    with open_database_connection() as connection:
        tables = sqlite_table_names(connection)
        if "players" not in tables:
            raise sqlite3.OperationalError("Missing required 'players' table in scoreboard database.")

        player_row = row_to_dict(connection.execute("SELECT * FROM players WHERE id = ? LIMIT 1", (player_id,)).fetchone())
        if not player_row:
            return None

        for bool_field in ("active", "is_player", "is_verified"):
            if bool_field in player_row:
                player_row[bool_field] = parse_bool_value(player_row.get(bool_field), False)

        team_id = safe_int(player_row.get("current_team_id"), 0)
        player_name_text = str(player_row.get("full_name") or "").strip()
        player_display_name = get_player_display_name(player_id, player_name_text)
        if player_display_name:
            player_row["display_name"] = player_display_name
            player_row["full_name_display"] = player_display_name

        team_lookup: Dict[int, Dict[str, Any]] = {}
        if "teams" in tables:
            team_lookup_rows = rows_to_dicts(
                connection.execute("SELECT id, name, abbreviation FROM teams").fetchall()
            )
            for team_row_value in team_lookup_rows:
                lookup_id = safe_int(team_row_value.get("id"), 0)
                if lookup_id > 0:
                    team_lookup[lookup_id] = team_row_value

        def resolve_team_metadata(team_id_value: Any, fallback_name: Any = "") -> Dict[str, Any]:
            resolved_id = safe_int(team_id_value, 0)
            lookup_row = team_lookup.get(resolved_id, {})

            team_name = str(
                fallback_name
                or lookup_row.get("name")
                or ""
            ).strip()
            abbreviation = str(lookup_row.get("abbreviation") or "").strip().upper()
            if not abbreviation and team_name:
                abbreviation = fallback_team_abbreviation(team_name)

            return {
                "id": resolved_id,
                "name": team_name,
                "abbreviation": abbreviation,
                "logoUrls": team_logo_urls(resolved_id),
                "theme": team_theme_colors(resolved_id),
            }

        player_team_meta = resolve_team_metadata(team_id, player_row.get("current_team_name"))
        team_logo_map = player_team_meta.get("logoUrls", {})
        team_theme = player_team_meta.get("theme", {})

        team_row = None
        if team_id > 0 and "teams" in tables:
            team_row = row_to_dict(connection.execute("SELECT * FROM teams WHERE id = ? LIMIT 1", (team_id,)).fetchone())
            if team_row and "active" in team_row:
                team_row["active"] = parse_bool_value(team_row.get("active"), False)
            if team_row is not None:
                if not str(team_row.get("abbreviation") or "").strip():
                    team_row["abbreviation"] = player_team_meta.get("abbreviation", "")
                team_row["logoUrls"] = team_logo_map
                team_row["theme"] = team_theme

        player_row["teamLogoUrls"] = team_logo_map
        player_row["teamTheme"] = team_theme

        target_game = None
        recent_games: List[Dict[str, Any]] = []
        upcoming_games: List[Dict[str, Any]] = []

        if "games" in tables and (team_id > 0 or requested_game_pk > 0):
            if requested_game_pk > 0:
                target_game = row_to_dict(
                    connection.execute("SELECT * FROM games WHERE game_pk = ? LIMIT 1", (requested_game_pk,)).fetchone()
                )

            if not target_game and team_id > 0:
                target_game = row_to_dict(
                    connection.execute(
                        """
                        SELECT *
                        FROM games
                        WHERE home_team_id = ? OR away_team_id = ?
                        ORDER BY ABS(julianday(COALESCE(official_date, substr(game_date, 1, 10))) - julianday(?)) ASC,
                                 COALESCE(game_date, '') DESC
                        LIMIT 1
                        """,
                        (team_id, team_id, requested_date.isoformat()),
                    ).fetchone()
                )

            if team_id > 0:
                recent_games = rows_to_dicts(
                    connection.execute(
                        """
                        SELECT *
                        FROM games
                        WHERE (home_team_id = ? OR away_team_id = ?)
                          AND COALESCE(official_date, substr(game_date, 1, 10)) <= ?
                        ORDER BY COALESCE(official_date, substr(game_date, 1, 10)) DESC,
                                 COALESCE(game_date, '') DESC
                        LIMIT 10
                        """,
                        (team_id, team_id, requested_date.isoformat()),
                    ).fetchall()
                )

                upcoming_games = rows_to_dicts(
                    connection.execute(
                        """
                        SELECT *
                        FROM games
                        WHERE (home_team_id = ? OR away_team_id = ?)
                          AND COALESCE(official_date, substr(game_date, 1, 10)) >= ?
                        ORDER BY COALESCE(official_date, substr(game_date, 1, 10)) ASC,
                                 COALESCE(game_date, '') ASC
                        LIMIT 10
                        """,
                        (team_id, team_id, requested_date.isoformat()),
                    ).fetchall()
                )

        def enrich_game_matchup_row(game_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not isinstance(game_row, dict):
                return game_row

            away_meta = resolve_team_metadata(game_row.get("away_team_id"), game_row.get("away_team_name"))
            home_meta = resolve_team_metadata(game_row.get("home_team_id"), game_row.get("home_team_name"))

            game_row["away_team_abbreviation"] = away_meta.get("abbreviation", "")
            game_row["home_team_abbreviation"] = home_meta.get("abbreviation", "")
            game_row["away_logo_urls"] = away_meta.get("logoUrls", {})
            game_row["home_logo_urls"] = home_meta.get("logoUrls", {})
            game_row["away_theme"] = away_meta.get("theme", {})
            game_row["home_theme"] = home_meta.get("theme", {})
            return game_row

        target_game = enrich_game_matchup_row(target_game)
        recent_games = [enrich_game_matchup_row(row) or row for row in recent_games]
        upcoming_games = [enrich_game_matchup_row(row) or row for row in upcoming_games]

        resolved_game_pk = safe_int(target_game.get("game_pk"), 0) if target_game else requested_game_pk

        def fetch_season_stat_row(table_name: str) -> Optional[Dict[str, Any]]:
            if table_name not in tables:
                return None

            row = row_to_dict(
                connection.execute(
                    f"""
                    SELECT *
                    FROM {table_name}
                    WHERE player_id = ? AND season = ?
                    ORDER BY COALESCE(games_played, 0) DESC
                    LIMIT 1
                    """,
                    (player_id, season),
                ).fetchone()
            )
            if row:
                return row

            return row_to_dict(
                connection.execute(
                    f"""
                    SELECT *
                    FROM {table_name}
                    WHERE player_id = ?
                    ORDER BY season DESC, COALESCE(games_played, 0) DESC
                    LIMIT 1
                    """,
                    (player_id,),
                ).fetchone()
            )

        def fetch_player_rows(table_name: str, limit: int = 10) -> List[Dict[str, Any]]:
            if table_name not in tables:
                return []
            return rows_to_dicts(
                connection.execute(
                    f"""
                    SELECT *
                    FROM {table_name}
                    WHERE player_id = ?
                    ORDER BY COALESCE(games_played, 0) DESC
                    LIMIT ?
                    """,
                    (player_id, max(1, limit)),
                ).fetchall()
            )

        primary_position_type = normalize_person_text(player_row.get("primary_position_type"))
        primary_position_abbreviation = str(player_row.get("primary_position_abbreviation") or "").strip().upper()
        is_pitcher_profile = primary_position_type == "pitcher" or primary_position_abbreviation == "P"

        stat_snapshot = {
            "batterSeason": fetch_season_stat_row("batter_stats_season"),
            "pitcherSeason": fetch_season_stat_row("pitcher_stats_season"),
            "batterLastTenGames": fetch_season_stat_row("batter_stats_last_ten_games"),
            "pitcherLastTenGames": fetch_season_stat_row("pitcher_stats_last_ten_games"),
            "batterVsRhp": fetch_season_stat_row("batter_stats_vs_rhp"),
            "batterVsLhp": fetch_season_stat_row("batter_stats_vs_lhp"),
            "pitcherVsRhp": fetch_season_stat_row("pitcher_stats_vs_rhp"),
            "pitcherVsLhp": fetch_season_stat_row("pitcher_stats_vs_lhp"),
            "batterByPark": fetch_player_rows("batter_stats_by_park", limit=8),
            "pitcherByPark": fetch_player_rows("pitcher_stats_by_park", limit=8),
        }

        pitcher_season = stat_snapshot.get("pitcherSeason") if isinstance(stat_snapshot.get("pitcherSeason"), dict) else {}
        if not is_pitcher_profile and pitcher_season:
            pitching_signal_keys = [
                "innings_pitched",
                "batters_faced",
                "games_pitched",
                "games_started",
                "strike_outs",
                "saves",
                "wins",
            ]
            for signal_key in pitching_signal_keys:
                signal_value = parse_numeric_value(pitcher_season.get(signal_key))
                if signal_value is not None and signal_value > 0:
                    is_pitcher_profile = True
                    break

        if is_pitcher_profile and not isinstance(stat_snapshot.get("pitcherLastTenGames"), dict):
            fallback_last_ten = build_pitcher_last_ten_games_snapshot(player_id, season, limit=10)
            if isinstance(fallback_last_ten, dict):
                stat_snapshot["pitcherLastTenGames"] = fallback_last_ten
                if safe_int(fallback_last_ten.get("games_pitched"), 0) > 0:
                    is_pitcher_profile = True

        stat_snapshot["isPitcher"] = is_pitcher_profile

        enrich_k_bb_percentages(stat_snapshot)

        batting_order_rows: List[Dict[str, Any]] = []
        lineup_source = "database"
        lineup_message = ""
        if "batting_orders" in tables:
            batting_order_rows = rows_to_dicts(
                connection.execute(
                    """
                    SELECT *
                    FROM batting_orders
                    WHERE player_id = ?
                    ORDER BY COALESCE(official_date, '') DESC, COALESCE(lineup_slot, 99) ASC
                    LIMIT 14
                    """,
                    (player_id,),
                ).fetchall()
            )

            if not batting_order_rows and player_name_text:
                if team_id > 0:
                    batting_order_rows = rows_to_dicts(
                        connection.execute(
                            """
                            SELECT *
                            FROM batting_orders
                            WHERE lower(player_name) = lower(?)
                              AND team_id = ?
                            ORDER BY COALESCE(official_date, '') DESC, COALESCE(lineup_slot, 99) ASC
                            LIMIT 14
                            """,
                            (player_name_text, team_id),
                        ).fetchall()
                    )
                else:
                    batting_order_rows = rows_to_dicts(
                        connection.execute(
                            """
                            SELECT *
                            FROM batting_orders
                            WHERE lower(player_name) = lower(?)
                            ORDER BY COALESCE(official_date, '') DESC, COALESCE(lineup_slot, 99) ASC
                            LIMIT 14
                            """,
                            (player_name_text,),
                        ).fetchall()
                    )

        fallback_rows = get_player_hitting_game_log_rows_cached(player_id, season, limit=14)

        if not batting_order_rows:
            if fallback_rows:
                batting_order_rows = fallback_rows
                lineup_source = "mlb_game_log_fallback"
                lineup_message = "Using MLB game log fallback while local batting_orders data catches up."
            else:
                lineup_source = "unavailable"
                lineup_message = "No recent lineup data found in local DB or MLB game log."
        elif fallback_rows:
            existing_keys = {
                (safe_int(row.get("game_pk"), 0), str(row.get("official_date") or "").strip())
                for row in batting_order_rows
                if isinstance(row, dict)
            }

            added_rows = 0
            for row in fallback_rows:
                if not isinstance(row, dict):
                    continue
                key = (safe_int(row.get("game_pk"), 0), str(row.get("official_date") or "").strip())
                if key in existing_keys:
                    continue
                batting_order_rows.append(row)
                existing_keys.add(key)
                added_rows += 1

            if added_rows > 0:
                lineup_source = "database_plus_mlb_game_log"
                lineup_message = (
                    "Supplemented with MLB game log appearances for games where the player appeared "
                    "without a starting-lineup row."
                )

        def lineup_row_sort_key(row: Dict[str, Any]) -> Tuple[int, int, int]:
            game_date = parse_iso_date(row.get("official_date"))
            date_ordinal = game_date.toordinal() if game_date else 0
            game_pk = safe_int(row.get("game_pk"), 0)
            lineup_slot = parse_lineup_slot_number(row.get("lineup_slot"))
            lineup_slot_for_sort = lineup_slot if lineup_slot > 0 else 99
            return (-date_ordinal, -game_pk, lineup_slot_for_sort)

        batting_order_rows = [row for row in batting_order_rows if isinstance(row, dict)]
        batting_order_rows.sort(key=lineup_row_sort_key)
        batting_order_rows = batting_order_rows[:14]

        lineup_game_index: Dict[int, Dict[str, Any]] = {}
        lineup_game_ids = sorted(
            {
                safe_int(row.get("game_pk"), 0)
                for row in batting_order_rows
                if isinstance(row, dict) and safe_int(row.get("game_pk"), 0) > 0
            }
        )
        if lineup_game_ids and "games" in tables:
            placeholders = ",".join("?" for _ in lineup_game_ids)
            lineup_game_rows = rows_to_dicts(
                connection.execute(
                    f"""
                    SELECT game_pk, official_date, game_date, home_team_id, home_team_name, away_team_id, away_team_name
                    FROM games
                    WHERE game_pk IN ({placeholders})
                    """,
                    tuple(lineup_game_ids),
                ).fetchall()
            )
            for game_row in lineup_game_rows:
                game_pk = safe_int(game_row.get("game_pk"), 0)
                if game_pk > 0:
                    lineup_game_index[game_pk] = game_row

        for row in batting_order_rows:
            if not isinstance(row, dict):
                continue

            row.setdefault("source", "database")

            row_team_id = safe_int(row.get("team_id"), 0)
            if row_team_id <= 0 and team_id > 0:
                row_team_id = team_id
                row["team_id"] = row_team_id

            if not str(row.get("team_name") or "").strip() and player_team_meta.get("name"):
                row["team_name"] = player_team_meta.get("name")

            game_pk = safe_int(row.get("game_pk"), 0)
            game_row = lineup_game_index.get(game_pk)
            if isinstance(game_row, dict):
                home_id = safe_int(game_row.get("home_team_id"), 0)
                away_id = safe_int(game_row.get("away_team_id"), 0)
                is_team_home = row_team_id > 0 and row_team_id == home_id

                opponent_id = away_id if is_team_home else home_id
                opponent_name = game_row.get("away_team_name") if is_team_home else game_row.get("home_team_name")

                if opponent_id > 0:
                    row["opponent_id"] = opponent_id
                if opponent_name and not str(row.get("opponent_name") or "").strip():
                    row["opponent_name"] = str(opponent_name).strip()
                if not str(row.get("official_date") or "").strip():
                    row["official_date"] = str(
                        game_row.get("official_date")
                        or str(game_row.get("game_date") or "")[:10]
                    ).strip()

                if row_team_id > 0:
                    row["home_away"] = "vs" if is_team_home else "@"

            opponent_meta = resolve_team_metadata(row.get("opponent_id"), row.get("opponent_name"))
            row["opponent_abbreviation"] = opponent_meta.get("abbreviation", "")
            row["opponent_logo_urls"] = opponent_meta.get("logoUrls", {})

            team_meta = resolve_team_metadata(row_team_id, row.get("team_name"))
            row["team_abbreviation"] = team_meta.get("abbreviation", "")
            row["team_logo_urls"] = team_meta.get("logoUrls", {})

            if not str(row.get("position_abbreviation") or "").strip():
                row["position_abbreviation"] = "-"
            if not str(row.get("batting_summary") or "").strip():
                row["batting_summary"] = "No batting line"

        player_odds_all: List[Dict[str, Any]] = []
        player_odds_source = "database"
        if "player_betting_odds" in tables:
            player_odds_all = rows_to_dicts(
                connection.execute(
                    """
                    SELECT *
                    FROM player_betting_odds
                    WHERE player_id = ?
                    ORDER BY COALESCE(commence_time, '') DESC, market_key, bookmaker_key
                    LIMIT 220
                    """,
                    (player_id,),
                ).fetchall()
            )

        if not player_odds_all and player_name_text:
            fallback_live_rows = get_live_player_prop_odds_rows_cached(player_name_text)
            if fallback_live_rows:
                player_odds_all = fallback_live_rows
                player_odds_source = "bettingpros_live_fallback"
            else:
                player_odds_source = "unavailable"

        player_odds = list(player_odds_all)
        if resolved_game_pk > 0:
            scoped = [row for row in player_odds_all if safe_int(row.get("game_pk"), 0) == resolved_game_pk]
            if scoped:
                player_odds = scoped
        else:
            same_date = []
            for row in player_odds_all:
                commence = parse_iso_datetime(row.get("commence_time"))
                if commence and commence.date() == requested_date:
                    same_date.append(row)
            if same_date:
                player_odds = same_date

        player_odds_by_market = summarize_player_odds_by_market(player_odds)

        if player_name_text and not has_any_market_lines(
            player_odds_by_market,
            ["batter_hits", "batter_home_runs", "batter_total_bases"],
        ):
            fallback_live_rows = get_live_player_prop_odds_rows_cached(player_name_text)
            if fallback_live_rows:
                seen_rows = {
                    (
                        str(row.get("market_key") or ""),
                        str(row.get("selection_name") or ""),
                        str(row.get("line") or ""),
                        str(row.get("odds_price") or ""),
                        str(row.get("commence_time") or ""),
                        str(row.get("bookmaker_key") or ""),
                    )
                    for row in player_odds
                    if isinstance(row, dict)
                }

                merged_odds = list(player_odds)
                merged = False
                for row in fallback_live_rows:
                    if not isinstance(row, dict):
                        continue

                    identity = (
                        str(row.get("market_key") or ""),
                        str(row.get("selection_name") or ""),
                        str(row.get("line") or ""),
                        str(row.get("odds_price") or ""),
                        str(row.get("commence_time") or ""),
                        str(row.get("bookmaker_key") or ""),
                    )
                    if identity in seen_rows:
                        continue

                    merged_odds.append(row)
                    seen_rows.add(identity)
                    merged = True

                if merged:
                    player_odds = merged_odds
                    player_odds_by_market = summarize_player_odds_by_market(player_odds)
                    if player_odds_source == "database":
                        player_odds_source = "database_plus_live_fallback"
                    elif player_odds_source == "unavailable":
                        player_odds_source = "bettingpros_live_fallback"

        related_game_ids = sorted(
            {
                safe_int(row.get("game_pk"), 0)
                for row in player_odds
                if safe_int(row.get("game_pk"), 0) > 0
            }
        )
        if resolved_game_pk > 0 and resolved_game_pk not in related_game_ids:
            related_game_ids.insert(0, resolved_game_pk)

        game_odds: List[Dict[str, Any]] = []
        if related_game_ids and "game_betting_odds" in tables:
            placeholders = ",".join("?" for _ in related_game_ids)
            game_odds = rows_to_dicts(
                connection.execute(
                    f"""
                    SELECT *
                    FROM game_betting_odds
                    WHERE game_pk IN ({placeholders})
                    ORDER BY COALESCE(commence_time, '') DESC, market_key, bookmaker_key
                    LIMIT 240
                    """,
                    tuple(related_game_ids),
                ).fetchall()
            )

        batter_display_rows = build_batter_stat_rows(stat_snapshot, player_odds_by_market)

        player_row["photoUrls"] = player_photo_urls(player_id)

        return {
            "generatedAtUtc": utc_now_iso(),
            "playerId": player_id,
            "query": {
                "season": season,
                "date": requested_date.isoformat(),
                "gamePk": resolved_game_pk,
            },
            "profile": player_row,
            "team": team_row
            or {
                "id": team_id,
                "name": str(player_row.get("current_team_name", "")),
                "abbreviation": player_team_meta.get("abbreviation", ""),
                "logoUrls": team_logo_map,
                "theme": team_theme,
            },
            "theme": team_theme,
            "stats": stat_snapshot,
            "display": {
                "batterRows": batter_display_rows,
            },
            "games": {
                "target": target_game,
                "recent": recent_games,
                "upcoming": upcoming_games,
            },
            "lineups": {
                "recentBattingOrders": batting_order_rows,
                "source": lineup_source,
                "message": lineup_message,
            },
            "odds": {
                "player": player_odds,
                "playerByMarket": player_odds_by_market,
                "game": game_odds,
                "playerSource": player_odds_source,
            },
            "sources": {
                "databasePath": str(database_path),
                "apiPlayerEndpoint": f"/api/player/{player_id}?season={season}",
                "oddsSource": "BettingPros+Bovada",
            },
        }


def player_endpoint_response(player_id: int):
    season = safe_int(request.args.get("season"), board_season())
    if season <= 0:
        season = board_season()

    requested_date = parse_iso_date(request.args.get("date")) or board_today()
    requested_game_pk = safe_int(request.args.get("gameId") or request.args.get("gamePk"), 0)

    try:
        payload = build_player_database_payload(player_id, season, requested_date, requested_game_pk)
    except FileNotFoundError as exc:
        return (
            jsonify(
                {
                    "error": "Database unavailable",
                    "detail": str(exc),
                }
            ),
            500,
        )
    except sqlite3.Error as exc:
        return (
            jsonify(
                {
                    "error": "Database query failed",
                    "detail": str(exc),
                }
            ),
            500,
        )

    if payload is None:
        return (
            jsonify(
                {
                    "error": "Player not found",
                    "detail": f"No player row found for id {player_id}.",
                }
            ),
            404,
        )

    return jsonify(apply_stat_decimal_precision(payload))


@app.route("/player")
def player_endpoint_query():
    player_id = safe_int(request.args.get("id") or request.args.get("playerId"), 0)
    if player_id <= 0:
        return (
            jsonify(
                {
                    "error": "Missing player id",
                    "detail": "Provide id or playerId query parameter, for example /player?id=592450.",
                }
            ),
            400,
        )

    return player_endpoint_response(player_id)


@app.route("/player/<int:player_id>")
def player_endpoint_by_id(player_id: int):
    return player_endpoint_response(player_id)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


def render_slides_page():
    slides_asset_version = str(int(dt.datetime.now(tz=dt.timezone.utc).timestamp()))
    response = make_response(
        render_template(
            "slides.html",
            team_name=TEAM_NAME,
            slides_asset_version=slides_asset_version,
        )
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
@app.route("/slides")
def slides_only():
    return render_slides_page()


@app.route("/api/player/<int:player_id>")
def api_player(player_id: int):
    season = safe_int(request.args.get("season"), board_season())
    if season <= 0:
        season = board_season()

    end_date = board_today()
    start_date = end_date - dt.timedelta(days=13)

    profile_params = {
        "hydrate": "currentTeam,team,rosterEntries,social,awards,education,draft",
    }

    try:
        profile_payload = mlb_get(f"/api/v1/people/{player_id}", params=profile_params)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code == 404:
            return (
                jsonify(
                    {
                        "error": "Player not found",
                        "detail": f"No MLB player found for id {player_id}.",
                    }
                ),
                404,
            )

        return (
            jsonify(
                {
                    "error": "MLB API request failed",
                    "detail": str(exc),
                }
            ),
            502,
        )
    except requests.RequestException as exc:
        return (
            jsonify(
                {
                    "error": "MLB API request failed",
                    "detail": str(exc),
                }
            ),
            502,
        )

    people = profile_payload.get("people", []) if isinstance(profile_payload, dict) else []
    if not people:
        return (
            jsonify(
                {
                    "error": "Player not found",
                    "detail": f"No MLB player found for id {player_id}.",
                }
            ),
            404,
        )

    person = people[0] if isinstance(people[0], dict) else {}
    player_name = str(person.get("fullName") or f"Player {player_id}")

    current_team = person.get("currentTeam") if isinstance(person.get("currentTeam"), dict) else {}
    if not current_team and isinstance(person.get("team"), dict):
        current_team = copy.deepcopy(person.get("team"))

    birth_date_text = str(person.get("birthDate", "")).strip()
    computed_age = calculate_age_from_birthdate(birth_date_text)
    current_age = safe_int(person.get("currentAge"), computed_age if computed_age is not None else 0)

    season_standard = fetch_player_stats_type(player_id, "season", season)
    season_advanced = fetch_player_stats_type(player_id, "seasonAdvanced", season)
    two_week_standard = fetch_player_stats_type(player_id, "byDateRange", season, start_date, end_date)
    two_week_advanced = fetch_player_stats_type(player_id, "byDateRangeAdvanced", season, start_date, end_date)
    game_log_standard = fetch_player_stats_type(player_id, "gameLog", season)

    game_log_entries = parse_player_game_log_entries(game_log_standard.get("raw", {}))
    previous_game_summary = game_log_entries[0] if game_log_entries else None

    previous_game_standard = empty_stats_section()
    previous_game_advanced = empty_stats_section()
    if previous_game_summary:
        previous_game_date = parse_iso_date(previous_game_summary.get("date"))
        if previous_game_date:
            previous_game_standard = fetch_player_stats_type(
                player_id,
                "byDateRange",
                season,
                previous_game_date,
                previous_game_date,
            )
            previous_game_advanced = fetch_player_stats_type(
                player_id,
                "byDateRangeAdvanced",
                season,
                previous_game_date,
                previous_game_date,
            )

    highlights = build_player_highlights(player_name, game_log_entries, limit=30)
    news = fetch_player_news_headlines(player_name, str(current_team.get("name", "")), PLAYER_NEWS_MAX_HEADLINES)
    odds = fetch_player_prop_odds(player_name)

    stat_group_keys = set()
    for section in [
        season_standard,
        season_advanced,
        two_week_standard,
        two_week_advanced,
        game_log_standard,
        previous_game_standard,
        previous_game_advanced,
    ]:
        summary = section.get("summary", {}) if isinstance(section, dict) else {}
        by_group_rows = summary.get("byGroupRows", {}) if isinstance(summary, dict) else {}
        if isinstance(by_group_rows, dict):
            stat_group_keys.update(by_group_rows.keys())

    if previous_game_summary and isinstance(previous_game_summary.get("byGroup"), dict):
        stat_group_keys.update(previous_game_summary.get("byGroup", {}).keys())

    response_payload = {
        "generatedAtUtc": utc_now_iso(),
        "playerId": player_id,
        "season": season,
        "timeWindows": {
            "currentSeason": {
                "season": season,
            },
            "lastTwoWeeks": {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
            },
            "previousGame": {
                "date": previous_game_summary.get("date", "") if previous_game_summary else "",
                "gamePk": safe_int(previous_game_summary.get("gamePk"), 0) if previous_game_summary else 0,
            },
        },
        "player": {
            "id": player_id,
            "name": player_name,
            "age": current_age,
            "birthDate": birth_date_text,
            "birthCity": str(person.get("birthCity", "")),
            "birthStateProvince": str(person.get("birthStateProvince", "")),
            "birthCountry": str(person.get("birthCountry", "")),
            "height": str(person.get("height", "")),
            "weight": safe_int(person.get("weight"), 0),
            "active": bool(person.get("active", False)),
            "primaryNumber": str(person.get("primaryNumber", "")),
            "nickname": str(person.get("nickName", "")),
            "strikeZoneTop": person.get("strikeZoneTop"),
            "strikeZoneBottom": person.get("strikeZoneBottom"),
            "mlbDebutDate": str(person.get("mlbDebutDate", "")),
            "handedness": {
                "bat": str(person.get("batSide", {}).get("description", "")),
                "pitch": str(person.get("pitchHand", {}).get("description", "")),
            },
            "primaryPosition": copy.deepcopy(person.get("primaryPosition", {})),
            "status": copy.deepcopy(person.get("status", {})),
            "team": {
                "id": safe_int(current_team.get("id"), 0),
                "name": str(current_team.get("name", "")),
                "abbreviation": str(current_team.get("abbreviation", "")),
                "link": str(current_team.get("link", "")),
                "league": copy.deepcopy(current_team.get("league", {})),
                "division": copy.deepcopy(current_team.get("division", {})),
                "venue": copy.deepcopy(current_team.get("venue", {})),
            },
            "photoUrls": player_photo_urls(player_id),
        },
        "stats": {
            "allAvailableStatGroups": sorted(stat_group_keys),
            "currentSeason": {
                "standard": season_standard,
                "advanced": season_advanced,
            },
            "lastTwoWeeks": {
                "standard": two_week_standard,
                "advanced": two_week_advanced,
            },
            "previousGame": {
                "summary": previous_game_summary,
                "byDateRange": previous_game_standard,
                "advancedByDateRange": previous_game_advanced,
            },
            "gameLog": {
                "standard": game_log_standard,
                "entries": game_log_entries,
            },
        },
        "news": news,
        "highlights": {
            "count": len(highlights),
            "clips": highlights,
        },
        "odds": odds,
        "sources": {
            "mlbStatsApiBaseUrl": MLB_BASE_URL,
            "newsSource": "Google News RSS",
            "oddsSource": "BettingPros",
        },
        "raw": {
            "profile": profile_payload,
        },
    }

    return jsonify(apply_stat_decimal_precision(response_payload))


def resolve_team_name_from_schedule_games(team_id: int, games: List[Dict[str, Any]], fallback: str = "") -> str:
    team_name = str(fallback or "").strip()
    for game in games:
        if not isinstance(game, dict):
            continue

        team_blob = game.get("team") if isinstance(game.get("team"), dict) else {}
        if safe_int(team_blob.get("id"), 0) == team_id:
            candidate = str(team_blob.get("name") or "").strip()
            if candidate:
                return candidate

        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        if safe_int(home.get("id"), 0) == team_id:
            candidate = str(home.get("name") or "").strip()
            if candidate:
                return candidate
        if safe_int(away.get("id"), 0) == team_id:
            candidate = str(away.get("name") or "").strip()
            if candidate:
                return candidate

    return team_name


def build_visual_scene_leaderboard_payload(team_id: int, category: str, count: int) -> Dict[str, Any]:
    normalized_category = str(category or "").strip().lower()
    leader_key = "hittingLeaders" if normalized_category == "hitting" else "pitchingLeaders"

    fallback_team_name = TEAM_NAME if team_id == TEAM_ID else f"Team {team_id}"
    base = get_team_base_data_cached(team_id, fallback_team_name, max(count, AUTO_LEADER_COUNT))

    players = base.get("players") if isinstance(base.get("players"), list) else []
    player_by_id: Dict[int, Dict[str, Any]] = {}
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = safe_int(player.get("playerId"), 0)
        if player_id <= 0:
            continue
        player_by_id[player_id] = player

    source_leaders = base.get(leader_key) if isinstance(base.get(leader_key), list) else []
    leaders: List[Dict[str, Any]] = []
    for row in source_leaders[:count]:
        if not isinstance(row, dict):
            continue

        copied = copy.deepcopy(row)
        player_id = safe_int(copied.get("playerId"), 0)
        player_blob = player_by_id.get(player_id, {})
        headshot_url = str(player_blob.get("headshotUrl") or "").strip()
        if not headshot_url and player_id > 0:
            headshot_url = (
                "https://img.mlbstatic.com/mlb-photos/image/upload/"
                f"w_400,q_auto:best/v1/people/{player_id}/headshot/67/current"
            )
        copied["headshotUrl"] = headshot_url
        leaders.append(copied)

    resolved_team_id = safe_int(base.get("teamId"), team_id)
    resolved_team_name = str(base.get("teamName") or fallback_team_name).strip() or fallback_team_name

    return {
        "generatedAtUtc": utc_now_iso(),
        "teamId": resolved_team_id,
        "teamName": resolved_team_name,
        "leaderType": normalized_category,
        "count": len(leaders),
        "theme": team_theme_colors(resolved_team_id),
        "logoUrls": team_logo_urls(resolved_team_id),
        "leaders": leaders,
    }


@app.route("/api/visual-scenes/team/<int:team_id>/schedule-overview")
def api_visual_scene_team_schedule_overview(team_id: int):
    if team_id <= 0:
        return (
            jsonify(
                {
                    "error": "Invalid team id",
                    "detail": "Team id must be a positive integer.",
                }
            ),
            400,
        )

    requested_start_raw = str(request.args.get("startDate") or request.args.get("date") or "").strip()
    if requested_start_raw:
        start_date = parse_iso_date(requested_start_raw)
        if start_date is None:
            return (
                jsonify(
                    {
                        "error": "Invalid start date",
                        "detail": "Provide startDate in ISO format YYYY-MM-DD.",
                    }
                ),
                400,
            )
    else:
        start_date = board_today()

    days_ahead = max(1, min(45, safe_int(request.args.get("daysAhead"), SCHEDULE_DAYS_AHEAD)))
    max_games = max(1, min(12, safe_int(request.args.get("maxGames"), 6)))

    try:
        games = get_upcoming_schedule(team_id, days_ahead, start_date=start_date)
    except requests.RequestException as exc:
        return (
            jsonify(
                {
                    "error": "MLB API request failed",
                    "detail": str(exc),
                }
            ),
            502,
        )

    fallback_name = TEAM_NAME if team_id == TEAM_ID else ""
    team_name = resolve_team_name_from_schedule_games(team_id, games, fallback=fallback_name)

    payload_games: List[Dict[str, Any]] = []
    for game in games[:max_games]:
        if not isinstance(game, dict):
            continue

        team_blob = game.get("team") if isinstance(game.get("team"), dict) else {}
        opponent_blob = game.get("opponent") if isinstance(game.get("opponent"), dict) else {}
        status_blob = game.get("status") if isinstance(game.get("status"), dict) else {}

        payload_games.append(
            {
                "gamePk": safe_int(game.get("gamePk"), 0),
                "gameDate": game.get("gameDate", ""),
                "officialDate": game.get("officialDate", ""),
                "homeAway": game.get("homeAway", ""),
                "status": status_blob.get("detailed", ""),
                "statusAbstract": status_blob.get("abstract", ""),
                "matchup": game.get("matchup", ""),
                "venue": game.get("venue", ""),
                "teamName": team_blob.get("name", team_name),
                "teamAbbreviation": team_blob.get("abbreviation", ""),
                "teamLogoUrls": copy.deepcopy(team_blob.get("logoUrls", {})),
                "teamRecord": copy.deepcopy(game.get("teamRecord", {})),
                "opponentName": opponent_blob.get("name", "Opponent"),
                "opponentAbbreviation": opponent_blob.get("abbreviation", ""),
                "opponentLogoUrls": copy.deepcopy(opponent_blob.get("logoUrls", {})),
                "opponentRecord": copy.deepcopy(game.get("opponentRecord", {})),
            }
        )

    first_team_record = {}
    if payload_games:
        first_team_record = copy.deepcopy(payload_games[0].get("teamRecord", {}))

    response_payload = {
        "generatedAtUtc": utc_now_iso(),
        "teamId": team_id,
        "teamName": team_name,
        "theme": team_theme_colors(team_id),
        "logoUrls": team_logo_urls(team_id),
        "startDate": start_date.isoformat(),
        "daysAhead": days_ahead,
        "maxGames": max_games,
        "gameCount": len(payload_games),
        "empty": not bool(payload_games),
        "teamRecord": first_team_record,
        "games": payload_games,
    }

    return jsonify(apply_stat_decimal_precision(response_payload))


@app.route("/api/visual-scenes/team/<int:team_id>/hitting-leaders")
def api_visual_scene_team_hitting_leaders(team_id: int):
    if team_id <= 0:
        return (
            jsonify(
                {
                    "error": "Invalid team id",
                    "detail": "Team id must be a positive integer.",
                }
            ),
            400,
        )

    count = max(1, min(12, safe_int(request.args.get("count"), AUTO_LEADER_COUNT)))
    qualified_only = parse_bool_value(request.args.get("qualified"), True)
    categories = parse_hitting_leaderboard_categories(request.args.get("categories"))

    requested_season = safe_int(request.args.get("season"), board_season())
    season = requested_season if requested_season > 0 else board_season()

    try:
        payload = build_visual_scene_hitting_leaderboards_payload(
            team_id,
            count,
            qualified_only,
            categories,
            season,
        )
    except requests.RequestException as exc:
        return (
            jsonify(
                {
                    "error": "MLB API request failed",
                    "detail": str(exc),
                }
            ),
            502,
        )

    return jsonify(apply_stat_decimal_precision(payload))


@app.route("/api/visual-scenes/team/<int:team_id>/pitching-leaders")
def api_visual_scene_team_pitching_leaders(team_id: int):
    if team_id <= 0:
        return (
            jsonify(
                {
                    "error": "Invalid team id",
                    "detail": "Team id must be a positive integer.",
                }
            ),
            400,
        )

    count = max(1, min(12, safe_int(request.args.get("count"), AUTO_LEADER_COUNT)))
    qualified_only = parse_bool_value(request.args.get("qualified"), False)
    categories = parse_pitching_leaderboard_categories(request.args.get("categories"))

    requested_season = safe_int(request.args.get("season"), board_season())
    season = requested_season if requested_season > 0 else board_season()

    try:
        payload = build_visual_scene_pitching_leaderboards_payload(
            team_id,
            count,
            qualified_only,
            categories,
            season,
        )
    except requests.RequestException as exc:
        return (
            jsonify(
                {
                    "error": "MLB API request failed",
                    "detail": str(exc),
                }
            ),
            502,
        )

    return jsonify(apply_stat_decimal_precision(payload))


@app.route("/api/team/<int:team_id>/games")
def api_team_games_for_date(team_id: int):
    if team_id <= 0:
        return (
            jsonify(
                {
                    "error": "Invalid team id",
                    "detail": "Team id must be a positive integer.",
                }
            ),
            400,
        )

    requested_date_raw = str(request.args.get("date") or "").strip()
    if requested_date_raw:
        requested_date = parse_iso_date(requested_date_raw)
        if requested_date is None:
            return (
                jsonify(
                    {
                        "error": "Invalid date",
                        "detail": "Provide date in ISO format YYYY-MM-DD.",
                    }
                ),
                400,
            )
    else:
        requested_date = board_today()

    try:
        games = get_team_games_for_date(team_id, requested_date)
    except requests.RequestException as exc:
        return (
            jsonify(
                {
                    "error": "MLB API request failed",
                    "detail": str(exc),
                }
            ),
            502,
        )

    enrich_team_games_endpoint_payload(team_id, games)

    team_name = TEAM_NAME if team_id == TEAM_ID else ""
    for game in games:
        home = game.get("home") if isinstance(game, dict) else {}
        away = game.get("away") if isinstance(game, dict) else {}
        if safe_int(home.get("id"), 0) == team_id:
            team_name = str(home.get("name") or "").strip()
            break
        if safe_int(away.get("id"), 0) == team_id:
            team_name = str(away.get("name") or "").strip()
            break

    response_payload = {
        "generatedAtUtc": utc_now_iso(),
        "teamId": team_id,
        "teamName": team_name,
        "theme": team_theme_colors(team_id),
        "date": requested_date.isoformat(),
        "gameCount": len(games),
        "isDoubleheader": len(games) > 1,
        "games": games,
    }
    # Backward compatibility for older clients that read payload.games.
    response_payload["payload"] = {
        "teamId": response_payload["teamId"],
        "teamName": response_payload["teamName"],
        "theme": response_payload["theme"],
        "date": response_payload["date"],
        "gameCount": response_payload["gameCount"],
        "isDoubleheader": response_payload["isDoubleheader"],
        "games": response_payload["games"],
    }

    return jsonify(apply_stat_decimal_precision(response_payload))


@app.route("/api/state")
def api_state():
    try:
        payload = get_state_cached()
        return jsonify(apply_stat_decimal_precision(payload))
    except requests.RequestException as exc:
        return (
            jsonify(
                {
                    "error": "MLB API request failed",
                    "detail": str(exc),
                }
            ),
            502,
        )
    except Exception as exc:  # pragma: no cover
        return (
            jsonify(
                {
                    "error": "Unexpected server error",
                    "detail": str(exc),
                }
            ),
            500,
        )


@app.route("/api/state/slides")
def api_state_slides():
    try:
        payload = get_slides_state_cached()
        return jsonify(apply_stat_decimal_precision(payload))
    except requests.RequestException as exc:
        return (
            jsonify(
                {
                    "error": "MLB API request failed",
                    "detail": str(exc),
                }
            ),
            502,
        )
    except Exception as exc:  # pragma: no cover
        return (
            jsonify(
                {
                    "error": "Unexpected server error",
                    "detail": str(exc),
                }
            ),
            500,
        )


@app.route("/api/visual-scenes")
def api_visual_scenes_get():
    try:
        config_path = resolve_visual_scene_template_path()
        config = load_visual_scene_template_config()
        modified_at = ""
        if config_path.exists():
            modified_at = utc_timestamp_iso(config_path.stat().st_mtime)

        return jsonify(
            {
                "config": config,
                "filePath": str(config_path),
                "exists": config_path.exists(),
                "updatedAtUtc": modified_at,
            }
        )
    except Exception as exc:  # pragma: no cover
        return (
            jsonify(
                {
                    "error": "Unable to load visual scene templates",
                    "detail": str(exc),
                }
            ),
            500,
        )


@app.route("/api/visual-scenes", methods=["PUT"])
def api_visual_scenes_put():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Invalid request body",
                    "detail": "Request body must be a JSON object.",
                }
            ),
            400,
        )

    incoming_config = body.get("config", body)
    validation_error = validate_visual_scene_template_config(incoming_config)
    if validation_error:
        return (
            jsonify(
                {
                    "error": "Invalid visual scene config",
                    "detail": validation_error,
                }
            ),
            400,
        )

    try:
        config_path = save_visual_scene_template_config(incoming_config)
    except Exception as exc:  # pragma: no cover
        return (
            jsonify(
                {
                    "error": "Unable to save visual scene templates",
                    "detail": str(exc),
                }
            ),
            500,
        )

    return jsonify(
        {
            "saved": True,
            "filePath": str(config_path),
            "updatedAtUtc": utc_now_iso(),
            "config": incoming_config,
        }
    )


@app.route("/api/kiosk-templates")
def api_kiosk_templates_get():
    try:
        config_path = resolve_template_file_path()
        config = load_kiosk_template_editor_config()
        modified_at = ""
        if config_path.exists():
            modified_at = utc_timestamp_iso(config_path.stat().st_mtime)

        return jsonify(
            {
                "config": config,
                "filePath": str(config_path),
                "exists": config_path.exists(),
                "updatedAtUtc": modified_at,
                "presets": copy.deepcopy(PLAYER_BREAKDOWN_STAT_PRESETS),
                "defaultHitterStatKeys": list(DEFAULT_PLAYER_BREAKDOWN_HITTER_STAT_KEYS),
                "defaultPitcherStatKeys": list(DEFAULT_PLAYER_BREAKDOWN_PITCHER_STAT_KEYS),
                "labelOverrides": copy.deepcopy(PLAYER_STAT_LABEL_OVERRIDES),
            }
        )
    except Exception as exc:  # pragma: no cover
        return (
            jsonify(
                {
                    "error": "Unable to load kiosk templates",
                    "detail": str(exc),
                }
            ),
            500,
        )


@app.route("/api/kiosk-templates", methods=["PUT"])
def api_kiosk_templates_put():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return (
            jsonify(
                {
                    "error": "Invalid request body",
                    "detail": "Request body must be a JSON object.",
                }
            ),
            400,
        )

    incoming_config = body.get("config", body)
    validation_error = validate_kiosk_template_config(incoming_config)
    if validation_error:
        return (
            jsonify(
                {
                    "error": "Invalid kiosk template config",
                    "detail": validation_error,
                }
            ),
            400,
        )

    try:
        config_path = save_kiosk_template_config(incoming_config)
    except Exception as exc:  # pragma: no cover
        return (
            jsonify(
                {
                    "error": "Unable to save kiosk templates",
                    "detail": str(exc),
                }
            ),
            500,
        )

    return jsonify(
        {
            "saved": True,
            "filePath": str(config_path),
            "updatedAtUtc": utc_now_iso(),
            "config": incoming_config,
        }
    )


if __name__ == "__main__":
    port = env_int("PORT", 8080)
    start_background_data_updater()
    app.run(host="0.0.0.0", port=port, debug=False)
