# Last.fm Weekly Listening Analyzer

This app builds a weekly listening report from Last.fm, adds recommendations, and includes Album of the Year weekly release highlights.

## Runtime

- Language/runtime: Python 3.9+
- Main dependencies: `requests`, `beautifulsoup4`
- Output: markdown report files in `reports/`
- Optional email delivery through Gmail SMTP

## Features

- Weekly summary of your listening period (rolling last 7 days to now)
- Top artists, top albums, top tracks, weekday activity, top taste tags
- Album recommendations (4 total): 1 local-LLM pick + 3 heuristic picks (with heuristic fill if needed)
- Top 8 most-reviewed releases from Album of the Year
- Rate Your Music enrichment: adds the RYM average score and rating count per release
- Monthly cached full listening-history sync (artist listen counts) in `.listening_history.json`
- New-release highlighting when you've listened to that artist at least 3 times
- Friday scheduler mode with configurable run time (default `19:00`)
- Optional email delivery when a report is generated
- Optional LLM parsing for resilient release extraction

## Setup

1. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment:

```bash
cp .env.example .env
```

3. Fill `.env`:

```bash
LASTFM_API_KEY=...
LASTFM_USERNAME=...
LASTFM_BASE_URL=http://ws.audioscrobbler.com/2.0/
APP_TIMEZONE=America/New_York
OUTPUT_DIR=reports
LOW_HISTORY_THRESHOLD=2
RECOMMENDATION_LIMIT=4
FRIDAY_RUN_HOUR=19
FRIDAY_RUN_MINUTE=0
AOTY_BASE_URL=https://www.albumoftheyear.org
RYM_ENABLED=true
RYM_BROWSER_TIMEOUT_SECONDS=40
RYM_MAX_ARTIST_LOOKUPS=15
LLM_ENABLED=true
LLM_PROVIDER=ollama
LLM_API_KEY=
LLM_MODEL=gpt-4.1-mini
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=LLaMA3.2:1B
LLM_TIMEOUT_SECONDS=60
LISTENING_HISTORY_PATH=.listening_history.json
LISTENING_HISTORY_REFRESH_DAYS=30
RELEASE_HIGHLIGHT_MIN_ARTIST_LISTENS=3

EMAIL_ENABLED=false
EMAIL_FROM=your_gmail_address@gmail.com
EMAIL_TO=recipient@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=your_gmail_address@gmail.com
SMTP_PASSWORD=your_gmail_app_password
```

## Run

Generate one report immediately:

```bash
python3 -m src.main
```

Run as scheduler loop:

```bash
python3 -m src.main --schedule
```

Scheduler behavior:
- Checks every minute by default
- Generates report on Fridays at or after `FRIDAY_RUN_HOUR:FRIDAY_RUN_MINUTE`
- Runs only once per ISO week (`.report_state.json`)
- Refreshes full Last.fm listening-history cache once every `LISTENING_HISTORY_REFRESH_DAYS` (default `30`)

## AOTY browsing notes

Album of the Year is behind a Cloudflare challenge, so the AOTY fetch drives a
real (headed) Chrome via `undetected-chromedriver`. Keep
`AOTY_BROWSER_HEADLESS=false`, otherwise it stays on the challenge.

On Apple Silicon the app selects the `mac-arm64` ChromeDriver, pins it to the
installed Chrome major version, and re-signs the patched driver, so Rosetta is
not required. If AOTY suddenly returns nothing after a macOS or Chrome update,
check the `## Debug` section of the newest report: the browser fallback status
and any driver error are recorded there.

## Rate Your Music notes

The RYM section adds an `RYM Score` and `RYM Ratings` column next to the AOTY
scores. RYM is behind Cloudflare too, and its direct `/release/` pages answer
automation with HTTP 503, so the scores come from pages that do render:

1. the `/new-music/` feed is fetched once and matched by artist + album;
2. for the remaining releases, each artist's discography page (`/artist/<slug>/`)
   is fetched and the album is matched against the per-release average rating.

Both steps reuse the same headed `undetected-chromedriver` browser as AOTY
(`RYM_ENABLED=true` requires `AOTY_BROWSER_ENABLED=true`). Because each artist
lookup is a separate browser launch, enrichment is the slowest part of a run
(roughly 20-70 s per unmatched artist). Cap it with `RYM_MAX_ARTIST_LOOKUPS`
(default `15`); set `RYM_ENABLED=false` to skip it entirely. Releases without a
RYM match are shown as `rym: n/a [0]`.

## Gmail notes

For Gmail SMTP you should use an App Password (not your regular account password). This requires 2-Step Verification enabled on your Google account.

## LLM notes

- Default setup uses local Ollama (`LLM_PROVIDER=ollama`) and calls `http://localhost:11434/api/chat`.
- Recommendations prompt includes:
  - this week's listening profile
  - a random sample from your long-term history (for variation)
  - candidate albums from Last.fm similarity expansion
- After LLM selection, albums are filtered out when your album playcount is greater than 20.
- You can still switch to OpenAI by setting `LLM_PROVIDER=openai` and adding `LLM_API_KEY`.
