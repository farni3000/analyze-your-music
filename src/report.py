from __future__ import annotations

import html
import os
from datetime import datetime

from .analyzer import WeeklySummary, WeeklyWindow
from .listening_history import artist_listen_count


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _bar(value: int, max_value: int) -> str:
    pct = 0 if max_value <= 0 else int(round((value / max_value) * 100))
    return (
        f"<div class='bar-wrap'><div class='bar-fill' style='width:{pct}%'></div>"
        f"<span class='bar-value'>{value}</span></div>"
    )


def _float_or_zero(value: object) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _score_text_with_marker(value: object, *, allow_hot: bool = True) -> str:
    text = str(value).strip() or "n/a"
    return f"{text} *" if allow_hot and _float_or_zero(text) > 84 else text


def _metric_chip_html(value: object, *, active: bool = False, hot: bool = False) -> str:
    text = str(value).strip() or "n/a"
    classes = ["metric-pill"]
    if active:
        classes.append("metric-hit")
    if hot:
        classes.append("score-hot")
    return f"<span class='{' '.join(classes)}'>{_esc(text)}</span>"


def _two_col_table_with_bars(items: list[tuple[str, int]], left_header: str, right_header: str) -> str:
    rows = [f"<tr><th>{_esc(left_header)}</th><th>{_esc(right_header)}</th></tr>"]
    max_val = max((value for _, value in items), default=0)
    for name, value in items:
        rows.append(f"<tr><td>{_esc(name)}</td><td>{_bar(value, max_val)}</td></tr>")
    return "".join(rows)


def _release_debug_suffix(release: dict) -> str:
    tags = release.get("tags") or []
    tag_text = ", ".join(str(tag) for tag in tags) or "-"
    source = str(release.get("tag_source", "none"))
    flags = [
        name
        for name, active in (
            ("artist", release.get("highlight_artist_plays")),
            ("user", release.get("highlight_user_score")),
            ("user_reviews", release.get("highlight_user_reviews")),
            ("critic", release.get("highlight_critic_score")),
        )
        if active
    ]
    return f" [debug: source={source}; flags={','.join(flags) or '-'}; tags={tag_text}]"


def _debug_lines(
    recommendations: list[dict],
    weekly_releases: list[dict],
    artist_listen_counts: dict[str, int],
    debug_notes: list[str] | None = None,
) -> list[str]:
    source_counts: dict[str, int] = {}
    metal_count = 0
    for release in weekly_releases:
        source = str(release.get("tag_source", "none"))
        source_counts[source] = source_counts.get(source, 0) + 1
        if release.get("is_metal_tagged"):
            metal_count += 1
    source_text = ", ".join(f"{key}={value}" for key, value in sorted(source_counts.items())) or "-"

    lines = ["## Debug", ""]
    for note in debug_notes or []:
        lines.append(f"- {note}")
    lines.append(f"- Included releases: {len(weekly_releases)}")
    lines.append(f"- Metal-tagged releases: {metal_count}")
    lines.append(f"- Tag sources: {source_text}")
    lines.append(f"- Recommendations: {len(recommendations)}")
    lines.append(f"- Cached artist listen counts: {len(artist_listen_counts)}")
    lines.append("")
    lines.append("### Per-release tags")
    lines.append("")
    for release in weekly_releases:
        artist = str(release.get("artist", "")).strip() or "Unknown Artist"
        album = str(release.get("album", "")).strip() or "Unknown Album"
        tags = release.get("tags") or []
        tag_text = ", ".join(str(tag) for tag in tags) or "-"
        source = str(release.get("tag_source", "none"))
        metal_flag = "METAL " if release.get("is_metal_tagged") else ""
        rym_score = str(release.get("rym_score", "")).strip() or "-"
        rym_count = int(release.get("rym_rating_count", 0) or 0)
        rym_source = str(release.get("rym_source", "")).strip() or "-"
        rym_album = str(release.get("rym_album", "")).strip()
        rym_detail = f"rym={rym_score}/{rym_count} ({rym_source}"
        if rym_album and rym_album.lower() != album.lower():
            rym_detail += f", matched={rym_album}"
        rym_detail += ")"
        lines.append(
            f"- {metal_flag}{artist} - {album} [source={source}; {rym_detail}]: {tag_text}"
        )
    return lines


def render_markdown(
    username: str,
    window: WeeklyWindow,
    summary: WeeklySummary,
    recommendations: list[dict],
    weekly_releases: list[dict],
    artist_listen_counts: dict[str, int] | None = None,
    release_highlight_min_artist_listens: int = 3,
    release_page_url: str = "https://rateyourmusic.com/new-music/",
    debug_notes: list[str] | None = None,
) -> str:
    lines: list[str] = []
    artist_listen_counts = artist_listen_counts or {}
    lines.append(f"# Weekly Last.fm Report for {username}")
    lines.append("")
    lines.append(
        f"Period: {window.start.strftime('%Y-%m-%d %H:%M %Z')} to {window.end.strftime('%Y-%m-%d %H:%M %Z')}"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Total scrobbles: {summary.total_scrobbles}")
    lines.append(f"- Unique artists: {summary.unique_artists}")
    lines.append(f"- Unique tracks: {summary.unique_tracks}")
    lines.append("")
    lines.append("## Top Artists")
    for i, (artist, plays) in enumerate(summary.top_artists[:7], start=1):
        lines.append(f"{i}. {artist} ({plays})")
    lines.append("")
    lines.append("## Top Albums")
    for i, (album, plays) in enumerate(summary.top_albums[:5], start=1):
        lines.append(f"{i}. {album} ({plays})")
    lines.append("")
    lines.append("## Top Tracks")
    for i, (track, plays) in enumerate(summary.top_tracks[:3], start=1):
        lines.append(f"{i}. {track} ({plays})")
    lines.append("")
    lines.append("## Activity By Day")
    for day, plays in summary.day_breakdown:
        lines.append(f"- {day}: {plays}")
    lines.append("")
    lines.append("## New Releases This Week (Album of the Year, filtered)")
    if not weekly_releases:
        lines.append("No releases matched the current inclusion rules this run.")
    else:
        for i, release in enumerate(weekly_releases, start=1):
            artist = release.get("artist", "").strip() or "Unknown Artist"
            album = release.get("album", "").strip() or "Unknown Album"
            artist_plays = int(release.get("artist_plays", artist_listen_count(artist_listen_counts, artist)) or 0)
            user_reviews = int(release.get("user_review_count", release.get("review_count", 0)) or 0)
            critic_reviews = int(release.get("critic_review_count", 0) or 0)
            critic_score = _score_text_with_marker(
                release.get("critic_score", ""),
                allow_hot=critic_reviews > 5,
            )
            user_score = _score_text_with_marker(
                release.get("user_score", ""),
                allow_hot=user_reviews > 30,
            )
            rym_score = str(release.get("rym_score", "")).strip() or "n/a"
            rym_count = int(release.get("rym_rating_count", 0) or 0)
            url = release.get("url", "").strip()
            metal_tag = " [METAL-TAGGED]" if bool(release.get("is_metal_tagged", False)) else ""
            debug_suffix = _release_debug_suffix(release)
            details = (
                f"(plays: {artist_plays}, user: {user_score} [{user_reviews}], "
                f"critic: {critic_score} [{critic_reviews}], rym: {rym_score} [{rym_count}])"
            )
            if url:
                lines.append(f"{i}. {artist} - {album}{metal_tag} {details} - {url}{debug_suffix}")
            else:
                lines.append(f"{i}. {artist} - {album}{metal_tag} {details}{debug_suffix}")
    lines.append("")
    lines.append("## Album Recommendations")
    if not recommendations:
        lines.append("No recommendations were generated this week.")
    else:
        for i, rec in enumerate(recommendations[:4], start=1):
            source = str(rec.get("source", rec.get("reason", "heuristic"))).strip() or "heuristic"
            url = str(rec.get("aoty_url", "")).strip()
            line = f"{i}. {rec['artist']} - {rec['album']} (source: {source})"
            if url:
                line += f" - {url}"
            lines.append(line)
    lines.append("")
    lines.extend(_debug_lines(recommendations, weekly_releases, artist_listen_counts, debug_notes))
    lines.append("")
    lines.append(f"_Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append("")
    lines.append(f"New releases page: {release_page_url}")
    return "\n".join(lines)


def render_email_html(
    username: str,
    window: WeeklyWindow,
    summary: WeeklySummary,
    recommendations: list[dict],
    weekly_releases: list[dict],
    artist_listen_counts: dict[str, int] | None = None,
    release_highlight_min_artist_listens: int = 3,
    release_page_url: str = "https://rateyourmusic.com/new-music/",
) -> str:
    artist_listen_counts = artist_listen_counts or {}
    top_artists_html = _two_col_table_with_bars(summary.top_artists[:7], "Artist", "Plays")
    top_albums_html = _two_col_table_with_bars(summary.top_albums[:5], "Album", "Plays")
    top_tracks_html = _two_col_table_with_bars(summary.top_tracks[:3], "Track", "Plays")
    day_html = _two_col_table_with_bars(summary.day_breakdown, "Day", "Scrobbles")

    release_rows: list[str] = []
    for release in weekly_releases:
        artist = release.get("artist", "").strip() or "Unknown Artist"
        album = release.get("album", "").strip() or "Unknown Album"
        artist_plays = int(release.get("artist_plays", artist_listen_count(artist_listen_counts, artist)) or 0)
        user_reviews = int(release.get("user_review_count", release.get("review_count", 0)) or 0)
        critic_reviews = int(release.get("critic_review_count", 0) or 0)
        critic_score = str(release.get("critic_score", "")).strip() or "n/a"
        user_score = str(release.get("user_score", "")).strip() or "n/a"
        rym_score = str(release.get("rym_score", "")).strip() or "n/a"
        rym_count = int(release.get("rym_rating_count", 0) or 0)
        rym_url = str(release.get("rym_url", "")).strip()
        url = release.get("url", "").strip()
        album_cell = _esc(album) if not url else f"<a href='{_esc(url)}'>{_esc(album)}</a>"
        rym_cell = _metric_chip_html(rym_score)
        if rym_url:
            rym_cell = f"<a href='{_esc(rym_url)}'>{rym_cell}</a>"
        row_classes: list[str] = []
        if bool(release.get("is_metal_tagged", False)):
            row_classes.append("metal-release")
        row_class_attr = f" class='{' '.join(row_classes)}'" if row_classes else ""
        user_score_hot = _float_or_zero(user_score) > 84 and user_reviews > 30
        critic_score_hot = _float_or_zero(critic_score) > 84 and critic_reviews > 5
        release_rows.append(
            f"<tr{row_class_attr}><td>{_esc(artist)}</td><td>{album_cell}</td>"
            f"<td>{_metric_chip_html(artist_plays, active=bool(release.get('highlight_artist_plays', False)), hot=bool(release.get('highlight_artist_plays_super', False)))}</td>"
            f"<td>{_metric_chip_html(user_score, active=bool(release.get('highlight_user_score', False)), hot=user_score_hot)}</td>"
            f"<td>{_metric_chip_html(user_reviews, active=bool(release.get('highlight_user_reviews', False)))}</td>"
            f"<td>{_metric_chip_html(critic_score, active=bool(release.get('highlight_critic_score', False)), hot=critic_score_hot)}</td>"
            f"<td>{_metric_chip_html(critic_reviews, active=bool(release.get('highlight_critic_reviews', False)))}</td>"
            f"<td>{rym_cell}</td>"
            f"<td>{_metric_chip_html(rym_count)}</td></tr>"
        )
    if not release_rows:
        release_rows.append("<tr><td colspan='9'>No releases matched the current inclusion rules this run.</td></tr>")

    rec_rows: list[str] = []
    for rec in recommendations[:4]:
        source = str(rec.get("source", rec.get("reason", "heuristic"))).strip() or "heuristic"
        url = str(rec.get("aoty_url", "")).strip()
        album_cell = _esc(rec.get("album", "")) if not url else f"<a href='{_esc(url)}'>{_esc(rec.get('album', ''))}</a>"
        rec_rows.append(
            "<tr>"
            f"<td>{_esc(rec.get('artist', ''))}</td>"
            f"<td>{album_cell}</td>"
            f"<td>{_esc(source)}</td>"
            "</tr>"
        )
    if not rec_rows:
        rec_rows.append("<tr><td colspan='3'>No recommendations generated this week.</td></tr>")

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    period = f"{window.start.strftime('%Y-%m-%d %H:%M %Z')} to {window.end.strftime('%Y-%m-%d %H:%M %Z')}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Weekly Music Report</title>
  <style>
    body {{
      margin: 0;
      padding: 18px;
      background: radial-gradient(circle at 20% 10%, #fff3e8 0%, #ffe2bf 45%, #ffd4a0 100%);
      font-family: 'Avenir Next', 'Trebuchet MS', 'Segoe UI', sans-serif;
      color: #3b2a1a;
    }}
    .container {{
      max-width: 980px;
      margin: 0 auto;
      border-radius: 18px;
      overflow: hidden;
      background: #fffdf9;
      box-shadow: 0 24px 48px rgba(167, 86, 13, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.9);
    }}
    .hero {{
      padding: 28px 26px;
      background: linear-gradient(120deg, #f97316 0%, #fb923c 35%, #fdba74 100%);
      color: #fff7ed;
      text-shadow: 0 1px 1px rgba(120, 53, 15, 0.35);
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: 30px;
      letter-spacing: 0.2px;
    }}
    .hero p {{
      margin: 0;
      opacity: 0.95;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      padding: 16px 22px;
      background: linear-gradient(180deg, #fff0dc 0%, #ffe5c0 100%);
    }}
    .stat {{
      background: linear-gradient(180deg, #fff8ef 0%, #fff1dd 100%);
      border: 1px solid #fed7aa;
      border-radius: 12px;
      padding: 12px;
      text-align: center;
      box-shadow: 0 7px 14px rgba(194, 65, 12, 0.13);
    }}
    .stat .label {{
      font-size: 12px;
      color: #9a3412;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .stat .value {{
      margin-top: 4px;
      font-size: 26px;
      color: #7c2d12;
      font-weight: 800;
    }}
    .section {{
      margin: 12px 18px;
      padding: 14px;
      border-radius: 14px;
      border: 1px solid #ffedd5;
      background: linear-gradient(180deg, #fff 0%, #fff7ed 100%);
      box-shadow: 0 8px 18px rgba(124, 45, 18, 0.08);
    }}
    .section h2 {{
      margin: 0 0 10px;
      color: #9a3412;
      font-size: 20px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      padding: 8px;
      border-bottom: 1px solid #ffedd5;
      vertical-align: top;
    }}
    th {{
      color: #7c2d12;
      background: #fff1db;
    }}
    a {{
      color: #c2410c;
      text-decoration: none;
      font-weight: 600;
    }}
    .metric-pill {{
      display: inline-block;
      min-width: 38px;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid #fcd6a8;
      background: #fff1db;
      color: #7c2d12;
      text-align: center;
      font-weight: 650;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.75);
    }}
    .metric-pill.metric-hit {{
      border-color: #ea580c;
      background: linear-gradient(180deg, #fed7aa 0%, #fdba74 100%);
      color: #7c2d12;
      box-shadow: 0 0 0 2px rgba(234, 88, 12, 0.12);
      font-weight: 800;
    }}
    .metric-pill.score-hot {{
      border-color: #ea580c;
      background: linear-gradient(180deg, #fec38f 0%, #fb923c 100%);
      color: #7c2d12;
      box-shadow: 0 0 0 2px rgba(234, 88, 12, 0.26), 0 6px 16px rgba(234, 88, 12, 0.34);
      font-weight: 800;
    }}
    .metal-release td {{
      color: #8b919d;
      background: linear-gradient(180deg, #f5f5f6 0%, #efeff1 100%);
      border-bottom-color: #d9d9dd;
    }}
    .metal-release a {{
      color: #7b818c;
    }}
    .bar-wrap {{
      position: relative;
      background: #ffe9cf;
      border-radius: 999px;
      height: 22px;
      overflow: hidden;
      min-width: 110px;
      box-shadow: inset 0 2px 4px rgba(154, 52, 18, 0.18);
    }}
    .bar-fill {{
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      background: linear-gradient(90deg, #f97316, #fb923c, #fdba74);
      box-shadow: 0 2px 8px rgba(194, 65, 12, 0.35);
    }}
    .bar-value {{
      position: absolute;
      right: 8px;
      top: 2px;
      font-size: 12px;
      color: #7c2d12;
      font-weight: 700;
    }}
    .footer {{
      padding: 14px 22px 24px;
      color: #9a3412;
      font-size: 12px;
    }}
    @media (max-width: 760px) {{
      .stats {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="hero">
      <h1>Weekly Music Report: {_esc(username)}</h1>
      <p>Period: {_esc(period)}</p>
    </div>
    <div class="stats">
      <div class="stat"><div class="label">Total Scrobbles</div><div class="value">{summary.total_scrobbles}</div></div>
      <div class="stat"><div class="label">Unique Artists</div><div class="value">{summary.unique_artists}</div></div>
      <div class="stat"><div class="label">Unique Tracks</div><div class="value">{summary.unique_tracks}</div></div>
    </div>
    <div class="section">
      <h2>New Releases This Week (Album of the Year, filtered)</h2>
      <table><tr><th>Artist</th><th>Album</th><th>Your Artist Plays</th><th>User Score</th><th>User Reviews</th><th>Critic Score</th><th>Critic Reviews</th><th>RYM Score</th><th>RYM Ratings</th></tr>{"".join(release_rows)}</table>
    </div>
    <div class="section"><h2>Top Artists</h2><table>{top_artists_html}</table></div>
    <div class="section"><h2>Top Albums</h2><table>{top_albums_html}</table></div>
    <div class="section"><h2>Top Tracks</h2><table>{top_tracks_html}</table></div>
    <div class="section"><h2>Activity By Day</h2><table>{day_html}</table></div>
    <div class="section">
      <h2>Album Recommendations</h2>
      <table><tr><th>Artist</th><th>Album</th><th>Source</th></tr>{"".join(rec_rows)}</table>
    </div>
    <div class="footer">Generated at {_esc(generated_at)}<br/>New releases page: <a href="{_esc(release_page_url)}">{_esc(release_page_url)}</a></div>
  </div>
</body>
</html>"""


def write_report(output_dir: str, window: WeeklyWindow, content: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"weekly_report_{window.end.strftime('%Y_%m_%d')}.md"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    return path
