# AGENTS.md

Guidance for AI coding agents working in this repository. Read this first.

## What this is

"Last.fm Weekly Listening Analyzer" – a Python 3.9+ CLI app that builds a weekly
listening report from the Last.fm API, enriches it with Album of the Year (AOTY)
weekly releases, adds album recommendations (heuristic + optional LLM), writes
markdown (and optional HTML) to `reports/`, and can email the result via Gmail
SMTP. Run once or as a Friday scheduler loop.

## Runtime & setup

- Python 3.9+. Deps (pinned): `requests`, `beautifulsoup4`, `python-dateutil`.
  Tests additionally need `pytest` (not in `requirements.txt`).
- Virtualenv: `.venv/`. Never rely on system packages. If `.venv/` is broken
  (it has pointed at a stale absolute path before), recreate it:
  ```bash
  rm -rf .venv && /usr/bin/python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt pytest
  ```
- All settings come from environment variables loaded from `.env` (copied from
  `.env.example`) and parsed in `src/config.py` into a frozen `AppConfig`
  dataclass. `LASTFM_API_KEY` and `LASTFM_USERNAME` are required.

## Commands

```bash
source .venv/bin/activate
python3 -m src.main                          # generate one report now
python3 -m src.main --schedule               # Friday scheduler loop
python3 -m pytest                            # run tests (pytest + unittest)
```

Entry point is `src/main.py`. Modules are imported package-relative
(`from .lastfm import LastFMClient`), so always run as `python3 -m src.main`,
never `python3 src/main.py`.

### Run the app and inspect the output (do this after non-trivial changes)

The generated markdown in `reports/` is **not** meant for human reading — treat
it as the primary debug log. After changing analysis/reporting code, run one
report and read the newest file:

```bash
python3 -m src.main
ls -t reports | head -1
```

Every markdown report ends with a `## Debug` section containing: AOTY fetch
status, releases before filtering, LLM/email flags, included releases, metal-tag
counts, tag-source distribution (`album`/`artist`/`none`), recommendation count,
and a per-release tag dump. Add debug fields here rather than printing to stdout.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/config.py` | `.env` parsing → frozen `AppConfig`; validation errors raise `ValueError` |
| `src/main.py` | Orchestration: `run_once()`, state file, Friday `run_scheduler()` |
| `src/lastfm.py` | `LastFMClient`: all Last.fm API calls; retries + DNS-wait logic |
| `src/analyzer.py` | Rolling 7-day window, `WeeklySummary` dataclass, top lists, day breakdown |
| `src/listening_history.py` | Cached long-term artist listen counts (`.listening_history.json`) |
| `src/recommender.py` | Similar-artist expansion + heuristic scoring + LLM album picks |
| `src/aoty.py` | AOTY scraper: browser → HTML → JSON-LD → Jina fallbacks; dedupe/rank |
| `src/rym.py` | Rate Your Music enrichment: new-music feed + per-artist discography lookup |
| `src/browser_fetch.py` | Isolated undetected-chromedriver worker for Cloudflare-protected AOTY/RYM |
| `src/llm.py` | Chat-completion helpers for Ollama + OpenAI; JSON-only responses |
| `src/report.py` | Markdown + HTML rendering; `write_report()` saves under `reports/` |
| `src/emailer.py` | `send_report_email()` via `smtplib.SMTP_SSL` (Gmail app password) |
| `tests/` | `test_aoty.py` + `test_metal_filter.py` + `test_rym.py` (pytest style), `test_listening_history.py` (unittest) |

Runtime artifacts (gitignored): `reports/`, `.report_state.json`,
`.listening_history.json`, `.env`.

## Data flow of one run (`run_once`)

1. `current_week_window` → 7-day rolling window; `summarize_week` pulls recent tracks.
2. `fetch_top_weekly_releases` (AOTY, limit 200) → filtered/annotated via
   `_annotate_and_filter_releases` (inclusion flags + metal-tag check).
3. `get_rym_ratings` (if `RYM_ENABLED`) enriches those rows with `rym_score`/
   `rym_rating_count`/`rym_url`: RYM `/new-music/` first, then per-artist
   discography for the rest (`_attach_rym_ratings`).
4. `get_artist_listen_counts` (cache read, refresh if older than refresh_days).
5. `recommend_albums` → candidates from similar artists, optional LLM pick on top,
   heuristic fill; drops albums with `album_playcount > 20` (`KNOWN_ALBUM_PLAYS_THRESHOLD`).
6. Recommendations dropped when already in the release section; enriched with AOTY scores/URLs.
7. `render_markdown` / `render_email_html` → `write_report` → optional email.

## Key conventions & invariants

- Artist/album normalization: lowercase, strip parentheticals, non-alnum → space.
  `normalize_album_key(artist, album)` in `src/aoty.py` (form `"artist::album"`);
  `normalize_artist_name` in `src/listening_history.py`. Reuse these instead of
  rolling new string matching.
- Release rows carry both `user_review_count`/`review_count` (back-compat alias)
  and `critic_review_count`; several helpers read either — keep both in sync.
- Scraper output is fragile: AOTY may serve Cloudflare blocks or switch layout.
  Parsing prefers HTML album blocks, falls back to JSON-LD, then Jina markdown.
  Guard against empty/fragmented data everywhere.
- **AOTY sits behind a Cloudflare Turnstile challenge.** Direct `requests`,
  browser-UA `curl`, `curl_cffi`, the `r.jina.ai` proxy and plain Playwright all
  get HTTP 403 / "Just a moment...". The working access path is
  `src/browser_fetch.py`, which drives a real **headed** Chrome via
  `undetected-chromedriver` in a separate subprocess. It returns the rendered
  HTML once its `ready_marker` appears (default `div.albumBlock` for AOTY).
  Headless is detected and stays on the challenge, so `AOTY_BROWSER_HEADLESS=false`
  is required.
- **Apple Silicon driver handling** (added after an empty-tab regression): uc
  3.5.5 hardcodes the `mac-x64` ChromeDriver, which needs Rosetta (often broken
  after a macOS update) on an arm64 Mac. `src/browser_fetch.py` fixes three
  things before launching: (1) forces `platform_name="mac-arm64"`, (2) passes
  the installed Chrome major (read from `Info.plist`) as `version_main`, because
  uc otherwise fetches CF-Testing *Stable* which may be ahead of the installed
  browser, and (3) wraps `Patcher.patch_exe` to re-sign the driver ad-hoc with
  `codesign --force --sign -`, since uc's in-place binary patch invalidates the
  code signature and arm64 macOS then SIGKILLs it (status -9). An "empty tab with
  nothing happening" after a macOS/Chrome update means the driver failed to
  start; the worker now writes the traceback to `page.html.err`, which
  `fetch_with_browser` prints to stderr.
- The browser worker is spawned with `close_fds=False` so that `subprocess`
  uses `posix_spawn` instead of `fork`. Forking after the app has done network
  I/O crashes on macOS (`nw_settings_child_has_forked` SIGSEGV in the worker).
  The worker ends with `os._exit(0)` to skip undetected-chromedriver's
  segfault-prone shutdown. Do not "simplify" these two details away.
- Related macOS trap: `subprocess.run(["bare-name", ...])` with the default
  `close_fds=True` also falls back to `fork()` (CPython only uses `posix_spawn`
  when the executable path has a directory and `close_fds=False`), producing the
  same SIGSEGV crash reports. The old `curl` fallbacks were removed for this
  reason; `src/llm.py` starts `ollama` via `_ollama_command()` (absolute path
  from `shutil.which`) with `close_fds=False`. If you add a `subprocess` call,
  pass an absolute path and `close_fds=False`.
- If the browser fallback is disabled / unavailable, `fetch_top_weekly_releases`
  returns `[]` and the debug section reports `AOTY fetch: empty (blocked or no
  releases)`. That is an access problem, not a parser problem.
- **RYM is also Cloudflare-protected, and its `/release/` pages return HTTP 503
  to automation** (confirmed with the same headed uc browser). The pages that do
  render are `/new-music/` (25 items with `.newreleases_avg_rating_stat`), the
  per-artist discography (`/artist/<slug>/`, `.disco_release` rows with
  `.disco_avg_rating`/`.disco_ratings`) and `/search`. `src/rym.py` therefore
  enriches in two steps: match against the new-music feed, then look up the
  remaining artists via their discography (slug guess, `/search` fallback).
  Matching uses `_match_key` (lowercase, non-alnum → space, **parentheticals kept**)
  so deluxe/`(Continued)` editions are not fuzzily conflated; `rym_album` is kept
  for verification. The browser worker takes a `ready_marker` argument
  (default `albumblock` for AOTY; RYM passes `newreleases_itembox`/`disco_release`/
  `page_search_results`), so it no longer waits the full timeout on RYM.
- `RYM_MAX_ARTIST_LOOKUPS` caps the per-artist browser launches (each ~20–70 s);
  `RYM_ENABLED=false` skips enrichment. If the browser fallback is off, RYM
  enrichment reports `skipped (browser fallback disabled)`.
- Network is unreliable: `LastFMClient._get` retries up to 8 times (429/5xx/DNS).
  New fetch code should degrade gracefully (empty list) rather than crash the run.
- LLM output must be strict JSON (`{"recommendations": [...]}`); `_extract_json_object`
  tolerates markdown fences / stray text. Never assume an LLM call succeeds.
- Every run must be reproducible without the LLM: if LLM is disabled/fails the
  heuristic path still fills recommendations.
- Timezone-aware datetimes everywhere (`zoneinfo.ZoneInfo`, from config `APP_TIMEZONE`).
- Match existing style: `from __future__ import annotations`, type hints, dataclasses
  for grouped data, no third-party deps beyond the pinned three.
- Do NOT add comments to code unless the change genuinely needs one.
- Never commit `.env`, API keys, or app passwords.

## Metal / graying filter (release rows)

Releases that look metal-ish are rendered with the `metal-release` CSS class
(HTML) / a `[METAL-TAGGED]` marker (markdown). Logic:

- `METAL_TAG_KEYWORDS` in `src/main.py` (currently `metal`, `doom`, `sludge`,
  `stoner`, `grunge`, `djent`, `grindcore`, `deathcore`) is matched
  case-insensitively as a substring against **every** tag.
- Tags are the de-duplicated union of
  `LastFMClient.get_album_tags(..., limit=ALBUM_TAG_LIMIT=50)` and
  `get_artist_tags(..., limit=ARTIST_TAG_LIMIT=20)`. Album tags alone are often
  junk (a single year such as `2026`), so both sources are always consulted.
  `tag_source` is stored on the row as `album+artist` / `album` / `artist` /
  `none`.
- `_is_metal_tagged(tags)` is the single source of truth; add new keywords there
  and cover them in `tests/test_metal_filter.py`.
- If a release is not grayed out, first check its `tags`/`tag_source` in the
  report's `### Per-release tags` dump before touching the matching logic.

## Config surface to know

Config fields live in `src/config.py` (`AppConfig`). Notable knobs:
`RECOMMENDATION_LIMIT` (default 4), `LOW_HISTORY_THRESHOLD`,
`RELEASE_HIGHLIGHT_MIN_ARTIST_LISTENS`, `AOTY_BROWSER_ENABLED` /
`AOTY_BROWSER_HEADLESS` / `AOTY_BROWSER_TIMEOUT_SECONDS`, `RYM_ENABLED` /
`RYM_BROWSER_TIMEOUT_SECONDS` / `RYM_MAX_ARTIST_LOOKUPS`, `LLM_PROVIDER`
(`ollama`|`openai`), `OLLAMA_*`, `EMAIL_ENABLED` + `SMTP_*`. When adding a
setting, add the field to `AppConfig`, read it in `load_config()`, and mirror it
in `.env.example`.

## Useful search hints

The `.opencode/` directory (if present) holds opencode agent definitions; this
file is instructions for coding assistants. `just_another_training_app` was moved
out of this repo (separate project). The `src/__pycache__/` dirs and
`.pytest_cache/` are noise.
