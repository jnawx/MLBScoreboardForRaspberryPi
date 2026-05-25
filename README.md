# Padres Pi Board

A Raspberry Pi friendly app that automatically switches between these modes:

- Live stream when a Padres game is live and you provide a legal stream URL.
- Live scoreboard + highlight loop when a game is live and no stream URL is set.
- Highlight loop when no live game is on.

It also supports a customizable slide deck that rotates through data-driven views (game pulse, previous game play-by-play, featured player breakdown) while the app runs in kiosk mode.

The kiosk system now supports hands-off automatic slide generation using templates and live data sources:

- Upcoming Padres schedule and opponent context.
- Active roster + season stats for Padres and upcoming opponent.
- Upcoming game weather (venue forecast).
- Auto-built slides for schedule, weather, team leaders, and player breakdowns.

## Why the live stream URL is optional

Directly embedding official MLB live game streams usually requires licensed access, account authentication, and DRM handling. This project intentionally does not bypass those restrictions.

If you have a legal stream source that provides an HLS or MP4 URL, add it in `LIVE_STREAM_URL`.

## Quick start

1. Create and activate a Python virtual environment.
2. Install dependencies.
3. Run the app.

```bash
python -m venv .venv
# Linux / Raspberry Pi
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
# Linux / Raspberry Pi
cp .env.example .env
# Windows PowerShell
# Copy-Item .env.example .env
python app.py
```

Then open `http://localhost:8080`.

Slides-only view:

- Open `http://localhost:8080/slides` for a full-screen slide page (no scoreboard/video panels).
- This page uses `/api/state/slides` and forces `player_breakdown` generation for all qualified players.
- `/slides` now defaults to a low-power mode (reduced motion + slower polling) tuned for Raspberry Pi playback smoothness.

## Docker / Portainer

This repo includes a Dockerfile and `portainer-stack.yml` for homelab deployment. The container runs the Flask app with Waitress on internal port `8080` and includes a `/health` endpoint for Docker health checks.

The GitHub Actions workflow at `.github/workflows/docker-image.yml` publishes a multi-arch image to GitHub Container Registry whenever `main` is pushed:

- `ghcr.io/jnawx/mlbscoreboardforraspberrypi:latest`
- `ghcr.io/jnawx/mlbscoreboardforraspberrypi:<commit-sha>`

Local Docker build:

```bash
docker build -t mlb-scoreboard-for-raspberry-pi:local .
```

The stack expects the external `homelab_network` Docker network, matching the InvestmentAlert deployment.

Portainer stack:

1. Create a new stack from this repository, or paste the contents of `portainer-stack.yml` into the Portainer web editor.
2. Use `portainer-stack.yml` as the compose path.
3. Set stack environment variables only if you want to override defaults.
4. Deploy the stack and open `https://mlbscoreboard.nawx.app`.

If the GitHub Container Registry package is private, add GHCR credentials in Portainer before deploying. Otherwise, make the package public in GitHub after the first workflow run creates it.

Useful stack variables:

- `MLB_SCOREBOARD_HOSTNAME`: Traefik hostname (default `mlbscoreboard.nawx.app`).
- `MLB_SCOREBOARD_UID` / `MLB_SCOREBOARD_GID`: Optional UID/GID for bind mount writes. The stack defaults to root, matching InvestmentAlert's bind mount behavior.
- `TEAM_ID`: MLB team id (default `135`).
- `TEAM_NAME`: Display name (default `San Diego Padres`).
- `LIVE_STREAM_URL`: Optional legal HLS/MP4 stream URL.
- `AUTO_UPDATE_ENABLED`: `1` keeps the local database fresh in the background, `0` disables it.
- `AUTO_UPDATE_RUN_ON_START`: `1` updates data when the container starts, `0` waits for the next interval.

Persistent bind mounts:

- `/mnt/data/mlb-scoreboard/data`: SQLite database at `/app/data/scoreboard.db`.
- `/mnt/data/mlb-scoreboard/config`: Editable kiosk/template JSON files at `/app/config`.

## Configuration

Set these environment variables in `.env` or your shell:

The app auto-loads `.env` at startup.

- `TEAM_ID`: Default is `135` for Padres.
- `TEAM_NAME`: Display name in the UI.
- `LIVE_STREAM_URL`: Optional. If empty, app falls back to highlights with scoreboard.
- `STATE_CACHE_TTL_SECONDS`: API cache time to reduce load.
- `LOOKBACK_DAYS`: How many days to scan for highlight clips.
- `MAX_HIGHLIGHTS`: Maximum clips in queue.
- `LIVE_GAME_HIGHLIGHT_MAX_AGE_HOURS`: Max clip age (hours) for live-game highlight panel clips (default `4`).
- `KIOSK_ENABLED`: `1` enables slide deck, `0` disables it.
- `KIOSK_LAYOUT_FILE`: Path to your slide layout JSON.
- `KIOSK_TEMPLATE_FILE`: Path to automatic slide template JSON.
- `FEATURED_PLAYER_NAME`: Name match used for featured-player slide.
- `FEATURED_PLAYER_ID`: Optional exact player ID override (use `0` to disable override).
- `HOT_STREAK_WINDOW`: Number of recent games used for hot streak meter.
- `MAX_PLAY_BY_PLAY_ITEMS`: Max items shown on previous-game play-by-play slide.
- `SCHEDULE_DAYS_AHEAD`: How far ahead to scan the Padres schedule for upcoming context.
- `AUTO_LEADER_COUNT`: Number of players to show in leader slides.
- `AUTO_PLAYER_SLIDE_COUNT`: Number of auto-generated player breakdown slides.
- `TEAM_STATS_CACHE_TTL_SECONDS`: Cache for roster/stat pulls to reduce API calls.
- `WEATHER_ENABLED`: `1` enables forecast lookups for the next game venue.
- `PLAYER_NEWS_MAX_HEADLINES`: Max number of news headlines returned by the player API endpoint.
- `BETTINGPROS_API_KEY`: Optional BettingPros API key.
- `BETTINGPROS_BASE_URL`: BettingPros API base URL (default `https://api.bettingpros.com/v3`).
- `BETTINGPROS_LOCATION`: Location parameter for BettingPros props (default `AZ`).
- `BETTINGPROS_BOOK_ID`: BettingPros `book_id` value (`0` = consensus lines).
- `BOVADA_ODDS_MLB_URL`: Bovada MLB endpoint used for game odds ingestion.
- `BETTING_ODDS_DAYS_AHEAD`: Number of days ahead to ingest BettingPros props/events (`0` = today only).
- `BETTING_ODDS_API_KEY`: Legacy alias for `BETTINGPROS_API_KEY`.
- `BETTING_ODDS_BASE_URL`: Legacy alias for `BETTINGPROS_BASE_URL`.
- `BETTING_ODDS_REGIONS`: Legacy alias for `BETTINGPROS_LOCATION`.
- `BETTING_ODDS_MARKETS`: Comma-separated markets for player prop odds.
- `BETTING_ODDS_PLAYER_MARKETS`: Comma-separated markets for `player_betting_odds` ingestion.
- `BETTING_ODDS_GAME_MARKETS`: Comma-separated markets for `game_betting_odds` ingestion.
- `BETTING_ODDS_BOOKMAKERS`: Legacy alias for `BETTINGPROS_BOOK_ID`.
- `DATA_TABLES`: Comma-separated table list for updater runs (for example `players,games,teams` or `game_betting_odds,player_betting_odds`).
- `DATABASE_PATH`: SQLite database file path for local data tables.
- `PLAYERS_SPORT_ID`: MLB sport id used by the players updater (`1` for MLB).
- `PLAYERS_ACTIVE_ONLY`: `1` keeps active players only, `0` keeps all players returned.
- `PLAYERS_PRUNE_MISSING`: `1` removes rows missing in the latest source pull.
- `SCHEDULE_SPORT_ID`: MLB sport id used by the schedule/games updater (`1` for MLB).
- `SCHEDULE_SEASONS`: Comma-separated seasons to ingest into `games` (example: `2025,2026`).
- `SCHEDULE_PRUNE_MISSING`: `1` removes stale `games` rows for requested seasons.
- `TEAMS_SPORT_ID`: MLB sport id used by team metadata lookups (`1` for MLB).
- `TEAMS_SEASONS`: Comma-separated seasons used to discover team IDs from `games`.
- `TEAMS_PRUNE_MISSING`: `1` removes teams not present in requested seasons.
- `TEAMS_INCLUDE_UNMAPPED`: `1` keeps teams from `games` even when MLB team metadata has no match.
- `STATS_SPORT_ID`: MLB sport id used for batter/pitcher split tables.
- `STATS_SEASON`: Season year for `*_stats_season`, `*_stats_last_ten_games`, `*_stats_vs_*` tables.
- `STATS_GAME_TYPE`: Game type filter for split stats (default `R`).
- `STATS_PAGE_SIZE`: Pagination size for bulk MLB stats pulls.
- `STATS_PRUNE_MISSING`: `1` removes stale rows from split stats tables for selected season.
- `BY_PARK_SEASONS`: Comma-separated seasons used for by-park, park, umpire, and batting-order tables.
- `BOXSCORE_GAME_TYPES`: Comma-separated game types to scan for boxscore-derived tables (default `R`).
- `PARKS_PRUNE_MISSING`: `1` removes parks not found in selected `BY_PARK_SEASONS` games.
- `BY_PARK_PRUNE_MISSING`: `1` removes stale rows from `batter_stats_by_park` and `pitcher_stats_by_park`.
- `UMPIRES_PRUNE_MISSING`: `1` removes stale rows from `umpires` for selected by-park seasons.
- `BATTING_ORDERS_PRUNE_MISSING`: `1` removes stale rows from `batting_orders` for selected by-park seasons.
- `ODDS_PRUNE_MISSING`: `1` removes stale rows from odds tables.
- `PORT`: Web server port.
- `AUTO_UPDATE_ENABLED`: `1` enables background updater runs while the Flask server is running (`0` disables).
- `AUTO_UPDATE_INTERVAL_SECONDS`: Seconds between background updater runs (default `86400`, once daily).
- `AUTO_UPDATE_RUN_ON_START`: `1` runs the updater once when the server starts before daily cadence begins.
- `AUTO_UPDATE_TIMEOUT_SECONDS`: Max seconds allowed for one updater run before it is aborted (default `3300`).
- `AUTO_UPDATE_SCRIPT_PATH`: Optional path override for updater script (default `scripts/update_data_tables.py`).
- `AUTO_UPDATE_EXTRA_ARGS`: Optional extra CLI args appended to updater runs (example `--tables games,teams --schedule-seasons 2026`).

## Data Table Updater

Run the updater script to create/update local database tables that will eventually back API responses.

```bash
python scripts/update_data_tables.py
```

What it does today:

- Creates SQLite DB at `DATABASE_PATH` (default: `data/scoreboard.db`).
- Creates these tables when selected:
	- `players`, `games`, `teams`
	- `batter_stats_season`, `batter_stats_last_ten_games`, `batter_stats_vs_rhp`, `batter_stats_vs_lhp`
	- `pitcher_stats_season`, `pitcher_stats_last_ten_games`, `pitcher_stats_vs_rhp`, `pitcher_stats_vs_lhp`
	- `batter_stats_by_park`, `pitcher_stats_by_park`
	- `parks`, `umpires`, `batting_orders`
	- `game_betting_odds`, `player_betting_odds`
- Upserts players using MLB player IDs as the table primary key (`players.id`).
- Pulls MLB schedule data for configured seasons and upserts rows into `games` (`games.game_pk` primary key).
- Builds `teams` from game rows (home/away IDs) and enriches via MLB team metadata.
- By default, only metadata-mapped teams are stored in `teams`; set `TEAMS_INCLUDE_UNMAPPED=1` to keep everything from schedule rows.
- Builds season, last-ten, and handedness split stat tables in bulk from MLB `/api/v1/stats`.
- Enriches `pitcher_stats_season.fip` from Fangraphs leaderboard data (matched by MLBAM player ID) after the MLB split ingest step.
- Builds by-park stats, umpires, and batting-order rows from game boxscores across selected seasons.
- Builds game and player betting odds tables from Bovada (game lines) and BettingPros (player props).
- Stores implied probability fields on odds rows (`implied_probability`, `implied_probability_percent`) for both game and player markets; two-way side pairs are no-vig normalized to total 100% when both sides are available.
- API side-pair summaries (`home/away`, `over/under`) are normalized to no-vig probabilities that total 100%, with raw pre-normalization values also exposed as `impliedProbabilityRaw` and `impliedProbabilityPercentRaw`.
- Stores key profile fields + full source payload (`raw_json`) for future expansions.

Useful options:

```bash
python scripts/update_data_tables.py --tables games --schedule-seasons 2026
python scripts/update_data_tables.py --tables teams --teams-seasons 2026
python scripts/update_data_tables.py --tables teams --teams-seasons 2026 --teams-include-unmapped
python scripts/update_data_tables.py --tables batter_stats_season,batter_stats_last_ten_games,batter_stats_vs_rhp,batter_stats_vs_lhp --stats-season 2026
python scripts/update_data_tables.py --tables pitcher_stats_season,pitcher_stats_last_ten_games,pitcher_stats_vs_rhp,pitcher_stats_vs_lhp --stats-season 2026
python scripts/update_data_tables.py --tables batter_stats_by_park,pitcher_stats_by_park,parks,umpires,batting_orders --by-park-seasons 2024,2025,2026
python scripts/update_data_tables.py --tables game_betting_odds,player_betting_odds --odds-game-markets h2h,spreads,totals --odds-player-markets batter_hits,pitcher_strikeouts
python scripts/update_data_tables.py --active-only
python scripts/update_data_tables.py --prune-missing
python scripts/update_data_tables.py --schedule-prune-missing
python scripts/update_data_tables.py --teams-prune-missing
python scripts/update_data_tables.py --db-path data/my-scoreboard.db
```

## Player API

Use `GET /api/player/<playerId>` to retrieve a comprehensive player payload.

Example:

```bash
curl "http://localhost:8080/api/player/592450"
```

Optional query param:

- `season`: MLB season year (defaults to current year), example:

```bash
curl "http://localhost:8080/api/player/592450?season=2026"
```

The endpoint includes:

- Profile and bio details (name, age, birthday, handedness, team, position, status).
- Player headshot URLs.
- MLB stats windows:
	- current season (standard + advanced)
	- past 2 weeks (standard + advanced)
	- previous game summary + by-date stat windows
	- full game log entries
- Highlight clips matched to the player.
- Relevant news headlines (Google News RSS search).
- Optional player prop odds pulled from BettingPros.

Notes:

- Odds data depends on third-party availability and market support; if unavailable, the response includes a reason/error in `odds`.
- MLB returns stat groups dynamically by player role and availability; response includes `allAvailableStatGroups`.

## Automatic Slide Templates

Edit `static/kiosk-templates.json` to control which auto-generated slide templates run and in what order.

Supported automatic `type` values:

- `status`
- `live_game_status`
- `schedule_overview`
- `upcoming_weather`
- `team_hitting_leaders`
- `team_pitching_leaders`
- `player_breakdowns`
- `previous_game_pbp`
- `featured_player`

Example:

```json
{
	"enabled": true,
	"defaultDurationSeconds": 14,
	"templates": [
		{
			"id": "status",
			"type": "status",
			"title": "Game Pulse",
			"durationSeconds": 10
		},
		{
			"id": "schedule",
			"type": "schedule_overview",
			"title": "Upcoming Schedule",
			"durationSeconds": 16,
			"maxGames": 6
		},
		{
			"id": "weather",
			"type": "upcoming_weather",
			"title": "Next Game Weather",
			"durationSeconds": 14
		},
		{
			"id": "padres-player-breakdowns",
			"type": "player_breakdowns",
			"team": "padres",
			"title": "Padres Breakdown",
			"durationSeconds": 20,
			"count": 3,
			"statPreset": "balanced",
			"missingStatValue": "N/A"
		}
	]
}
```

`player_breakdowns` supports optional stat-key controls:

- `statPreset`: quick preset for both hitters and pitchers (`balanced`, `advanced`, `power`).
- `hitterStatPreset` and `pitcherStatPreset`: side-specific preset override.
- `statKeys`: fallback list for both hitters and pitchers.
- `hitterStatKeys`: overrides stat list for hitter cards.
- `pitcherStatKeys`: overrides stat list for pitcher cards.
- `missingStatValue`: placeholder for unavailable metrics (default `N/A`).
- `statLabels`: custom label map, example `{ "strikeOuts": "K", "homeRuns": "HR" }`.
- `statSeparator`: joiner between metrics in `seasonLine`/`selectedStatsLine`.
- `statLabelValueSeparator`: joiner between label and value.

Priority order is: explicit key lists (`hitterStatKeys`/`pitcherStatKeys`) -> `statKeys` -> presets -> built-in defaults.

The backend now builds `payload.seasonLine` from these keys, so you can add/remove metrics without Python changes.

`live_game_status` notes:

- Only generates when a game is currently live.
- Includes live-feed fields such as score, inning, count, current batter/pitcher, on-deck/in-hole, and occupied bases.
- Includes a `highlights` array sourced from the current live game's MLB content feed.
- Live highlights are filtered by recency (default: last 4 hours) and ordered newest-first.
- Supports `pinWhenLive` (default `true`). When set to `true`, this live slide is exclusive while a game is active and other auto slides are temporarily hidden.
- Supports `highlightLimit` to cap the number of clips attached to the slide payload.

## Visual Scene Templates (Designer Mode)

The data templates above decide *what* slides are generated. The visual scene templates decide *how each slide looks and animates*.

Edit `static/visual-scene-templates.json` for:

- Slide background color/image/overlay.
- Exact element placement (`x`, `y`, `w`, `h`) using percentages or any CSS length.
- Per-element reveal timing (`enter.delayMs`) and exit timing/effects (`exit`).
- Slide transition choreography (`transitionIn`, `transitionOut`).

The browser polls this file every few seconds, so visual edits are reflected quickly without restarting Flask.

### Schema overview

```json
{
	"enabled": true,
	"slideTransitionMs": 720,
	"elementDefaults": {
		"enter": { "effect": "slide-up", "durationMs": 720, "delayMs": 0 },
		"exit": { "effect": "fade", "durationMs": 460, "delayMs": 0 }
	},
	"templates": {
		"status": {
			"background": {
				"color": "linear-gradient(...)",
				"image": "https://... or {{payload.someImage}}",
				"overlay": "linear-gradient(...)"
			},
			"transitionIn": { "effect": "slide-left", "durationMs": 760 },
			"transitionOut": { "effect": "fade", "durationMs": 520 },
			"elements": [
				{
					"kind": "text",
					"text": "{{payload.statusText}}",
					"x": "5%",
					"y": "16%",
					"w": "60%",
					"className": "scene-title",
					"enter": { "effect": "slide-right", "delayMs": 150, "durationMs": 840 },
					"exit": { "effect": "fade", "durationMs": 420 }
				}
			]
		}
	}
}
```

### Element kinds

- `text`: Headings, labels, metric callouts.
- `image`: Player headshots, logos, photos.
- `list`: Repeating rows from arrays (`itemsPath`, `itemTitleTemplate`, `itemSubtitleTemplate`).
- `bar`: Progress/meter bars (`valuePath`, `maxValue`, `labelTemplate`).

### Supported animation effects

- `fade`
- `slide-up`
- `slide-down`
- `slide-left`
- `slide-right`
- `zoom`

### Positioning and timing tips

- Use `%` for kiosk-friendly responsive placement.
- Start with `x`, `y`, and `w`; add `h` only when you need clipping or strict containers.
- Stagger elements with increasing `enter.delayMs` (example: 100, 220, 360, 520).
- Keep exit durations shorter than enter durations for a snappy handoff.

If a slide type has no matching entry in `visual-scene-templates.json`, the app falls back to the built-in renderer for that slide.

### GUI editor

You can edit scene templates in a browser GUI instead of hand-editing JSON:

- Open `http://localhost:8080/editor`
- Select a template key from the left panel.
- Drag element boxes on the canvas to reposition them.
- Drag the corner handle of a box to resize it.
- Use grid/snap controls for easier alignment.
- Update background, transitions, and timing in the form fields as needed.
- Use **Player Breakdown Data Controls** (when editing `player_breakdown`) to set stat presets/keys and formatting without hand-editing `kiosk-templates.json`.
- Use the **Data Keys** browser to find valid paths from live `/api/state` data.
- Click **Copy path** for path fields (like `itemsPath`) or **Copy {{ }}** for text templates.
- Use **Play Slide** to preview enter/exit animation timing from start to finish with current data.
- Click **Save JSON** (or press `Ctrl+S`) to persist both visual scene templates and player breakdown data controls.

The editor reads/writes the same file (`static/visual-scene-templates.json` by default), so the board view immediately picks up your changes through the template polling in the frontend.

Optional environment variable:

- `VISUAL_SCENE_TEMPLATE_FILE`: Override the scene template JSON file path used by `/editor` and `/api/visual-scenes`.

### Player Breakdown Payload Keys

For `player_breakdown` slides, each `payload` now includes direct stat keys you can reference in scene templates:

- `obp`, `ops`, `war`, `fip`
- `avg`, `era`, `whip`
- `seasonLine` (existing summary)
- `advancedLine` (OBP/OPS/WAR/FIP summary)
- `selectedStatKeys` (the final key list used for this slide)
- `selectedStatPreset` (preset used, when applicable)
- `selectedStats` (array of `{ key, label, value }`)
- `selectedStatsLine` (formatted line built from `selectedStats`)
- `selectedStatsMissingValue` (placeholder used for missing metrics)
- `hittingStats` and `pitchingStats` (raw stat dictionaries from MLB)

Examples you can drop into `static/visual-scene-templates.json`:

```json
{ "text": "OBP {{payload.obp}} | OPS {{payload.ops}} | WAR {{payload.war}} | FIP {{payload.fip}}" }
```

```json
{ "textPath": "payload.pitchingStats.fip" }
```

```json
{
	"kind": "list",
	"itemsPath": "payload.selectedStats",
	"itemTitleTemplate": "{{item.label}} {{item.value}}",
	"maxItems": 6
}
```

```json
{
	"id": "padres-player-breakdowns",
	"type": "player_breakdowns",
	"team": "padres",
	"title": "Padres Breakdown",
	"count": 3,
	"hitterStatPreset": "advanced",
	"pitcherStatPreset": "power",
	"missingStatValue": "-",
	"statLabels": { "strikeOuts": "K", "homeRuns": "HR" },
	"statSeparator": "  •  ",
	"statLabelValueSeparator": ": "
}
```

When a stat is unavailable in MLB data for that player/season, the payload value is set to `N/A`.

## Slides-Only Data

`GET /api/state/slides` returns a slides-focused state payload used by `/slides`.

- Keeps visual scene rendering and template behavior the same as the main board.
- Forces `player_breakdown` slides to include all qualified players (instead of the normal count-limited subset).

## Legacy Manual Layout

Edit `static/kiosk-slides.json` to control view order and durations.

Supported `type` values:

- `status`
- `previous_game_pbp`
- `featured_player`

Example:

```json
{
	"enabled": true,
	"rotationSeconds": 14,
	"slides": [
		{
			"id": "status",
			"type": "status",
			"title": "Game Pulse",
			"durationSeconds": 10
		},
		{
			"id": "featured-player",
			"type": "featured_player",
			"title": "Jake Cronenworth Breakdown",
			"durationSeconds": 24
		},
		{
			"id": "previous-game",
			"type": "previous_game_pbp",
			"title": "Last Night Inning Story",
			"durationSeconds": 18
		}
	]
}
```

When the featured-player slide is active, the video queue prioritizes highlights related to that player from the most recent final game.

## Raspberry Pi kiosk mode

Start Chromium in kiosk mode after the app starts:

```bash
chromium-browser --kiosk --autoplay-policy=no-user-gesture-required http://localhost:8080
```

## Optional systemd service (Raspberry Pi)

Create `/etc/systemd/system/padres-board.service`:

```ini
[Unit]
Description=Padres Pi Board
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/MLBScoreboardForRaspberryPi
EnvironmentFile=/home/pi/MLBScoreboardForRaspberryPi/.env
ExecStart=/home/pi/MLBScoreboardForRaspberryPi/.venv/bin/python /home/pi/MLBScoreboardForRaspberryPi/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable padres-board
sudo systemctl start padres-board
```

## Notes

- Highlight clips are pulled from MLB Stats API game content endpoints.
- UI is responsive for TV and smaller touch screens.
- Press `U` in the browser to toggle mute.
