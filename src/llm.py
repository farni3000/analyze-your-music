from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import Any
from urllib.parse import urlparse

import requests


def _ollama_command(*args: str) -> list[str]:
    executable = shutil.which("ollama") or "ollama"
    return [executable, *args]


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    raise ValueError("No JSON object found in LLM response.")


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)


def _ollama_host_from_base_url(base_url: str) -> str:
    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    return parsed.netloc or parsed.path


def _ollama_is_healthy(base_url: str, timeout: float = 1.5) -> bool:
    try:
        response = requests.get(base_url.rstrip("/") + "/api/tags", timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


def _stop_ollama_server(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _start_ollama_server_if_needed(
    base_url: str,
    startup_timeout_seconds: float = 12.0,
) -> subprocess.Popen | None:
    if _ollama_is_healthy(base_url):
        return None

    env = {**os.environ}
    host = _ollama_host_from_base_url(base_url)
    if host:
        env["OLLAMA_HOST"] = host

    process = subprocess.Popen(
        _ollama_command("serve"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        close_fds=False,
    )
    deadline = time.time() + startup_timeout_seconds
    while time.time() < deadline:
        if process.poll() is not None:
            break
        if _ollama_is_healthy(base_url):
            return process
        time.sleep(0.25)

    _stop_ollama_server(process)
    raise RuntimeError(f"Could not start Ollama server on {base_url}")


def _chat_completion_json_ollama_cli(
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int,
) -> dict[str, Any]:
    prompt = (
        f"{system_prompt}\n\n"
        f"{user_prompt}\n\n"
        "Return strict JSON only. Do not include markdown fences."
    )
    env = None
    host = base_url.replace("http://", "").replace("https://", "").strip()
    if host:
        env = {**os.environ, "OLLAMA_HOST": host}

    result = subprocess.run(
        _ollama_command("run", model, "--format", "json", "--hidethinking", prompt),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=env,
        close_fds=False,
    )
    raw = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    cleaned = _strip_ansi(raw).strip()
    return _extract_json_object(cleaned)


def _chat_completion_json_openai(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int,
) -> dict[str, Any]:
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return _extract_json_object(content)


def _chat_completion_json_ollama(
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/chat"
    response = requests.post(
        url,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    content = ((payload.get("message") or {}).get("content") or "").strip()
    return _extract_json_object(content)


def chat_completion_json(
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int = 60,
    api_key: str = "",
    ollama_base_url: str = "http://localhost:11434",
) -> dict[str, Any]:
    provider = provider.strip().lower()
    if provider == "openai":
        return _chat_completion_json_openai(
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            timeout=timeout,
        )
    if provider == "ollama":
        started_server: subprocess.Popen | None = None
        try:
            started_server = _start_ollama_server_if_needed(ollama_base_url)
            return _chat_completion_json_ollama(
                base_url=ollama_base_url,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout=timeout,
            )
        except Exception:
            return _chat_completion_json_ollama_cli(
                base_url=ollama_base_url,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout=timeout,
            )
        finally:
            _stop_ollama_server(started_server)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def recommend_albums_with_llm(
    provider: str,
    model: str,
    week_profile: dict[str, Any],
    random_history_sample: dict[str, list[dict[str, Any]]],
    candidate_pool: list[dict[str, Any]],
    limit: int,
    timeout: int = 60,
    api_key: str = "",
    ollama_base_url: str = "http://localhost:11434",
) -> list[dict[str, Any]]:
    system = "Return only valid JSON. Do not echo the prompt."
    top_artists = (week_profile.get("top_artists") or [])[:8]
    history_artists = (random_history_sample.get("artists") or [])[:10]
    candidates = candidate_pool[:20]
    user_lines = [
        "Select album recommendations for this week.",
        f"Choose at most {limit} items.",
        "Only choose from the candidate list.",
        "Prefer stylistic fit to weekly artists, novelty, and artist diversity.",
        "",
        "Weekly top artists:",
    ]
    for row in top_artists:
        user_lines.append(f"- {row.get('artist', '')} ({row.get('plays', 0)} plays)")
    user_lines.append("")
    user_lines.append("Random history artists:")
    for row in history_artists:
        user_lines.append(f"- {row.get('artist', '')} ({row.get('playcount', 0)} plays)")
    user_lines.append("")
    user_lines.append("Candidate albums:")
    for idx, row in enumerate(candidates, start=1):
        user_lines.append(
            f"{idx}. {row.get('artist', '')} - {row.get('album', '')} "
            f"(heuristic={row.get('heuristic_score', 0)}, "
            f"artist_history={row.get('artist_history_playcount', 0)}, "
            f"album_history={row.get('album_history_playcount', 0)})"
        )
    user_lines.append("")
    user_lines.append(
        'Output JSON exactly like {"recommendations":[{"artist":"...","album":"...","fit_score":0-100,"reason":"..."}]}'
    )
    user_lines.append("Do not include markdown fences. Do not repeat the input.")
    user = "\n".join(user_lines)
    parsed = chat_completion_json(
        provider=provider,
        model=model,
        system_prompt=system,
        user_prompt=user,
        timeout=timeout,
        api_key=api_key,
        ollama_base_url=ollama_base_url,
    )
    rows = parsed.get("recommendations", [])
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        nested = parsed.get("result")
        if isinstance(nested, dict):
            rows = nested.get("recommendations", [])
            if isinstance(rows, dict):
                rows = [rows]
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        artist = str(row.get("artist", "")).strip()
        album = str(row.get("album", "")).strip()
        if not artist or not album:
            continue
        try:
            fit_score = float(row.get("fit_score", 0))
        except (TypeError, ValueError):
            fit_score = 0.0
        out.append(
            {
                "artist": artist,
                "album": album,
                "fit_score": max(0.0, min(100.0, fit_score)),
                "llm_reason": str(row.get("reason", "")).strip(),
            }
        )
    return out


def extract_release_rows_with_llm(
    provider: str,
    model: str,
    source_name: str,
    source_text: str,
    limit: int = 10,
    timeout: int = 60,
    api_key: str = "",
    ollama_base_url: str = "http://localhost:11434",
) -> list[dict[str, Any]]:
    system = (
        "Extract music release rows from noisy website text. "
        "Return strict JSON only. Do not invent entries."
    )
    user = json.dumps(
        {
            "source": source_name,
            "limit": limit,
            "task": (
                "Extract releases with artist, album, user score, user review count, "
                "critic score, critic review count, and URL."
            ),
            "text": source_text[:26000],
            "output_schema": {
                "releases": [
                    {
                        "artist": "string",
                        "album": "string",
                        "critic_score": "number or empty",
                        "critic_review_count": "integer if available else 0",
                        "user_score": "number or empty",
                        "user_review_count": "integer if available else 0",
                        "review_count": "integer if available else 0",
                        "url": "string if available else empty",
                    }
                ]
            },
        }
    )
    parsed = chat_completion_json(
        provider=provider,
        model=model,
        system_prompt=system,
        user_prompt=user,
        timeout=timeout,
        api_key=api_key,
        ollama_base_url=ollama_base_url,
    )
    rows = parsed.get("releases", [])
    if not isinstance(rows, list):
        return []

    cleaned: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        artist = str(row.get("artist", "")).strip() or "Unknown Artist"
        album = str(row.get("album", "")).strip()
        if not album:
            continue
        try:
            review_count = int(row.get("review_count", 0) or 0)
        except (TypeError, ValueError):
            review_count = 0
        try:
            user_review_count = int(row.get("user_review_count", review_count) or review_count)
        except (TypeError, ValueError):
            user_review_count = review_count
        try:
            critic_review_count = int(row.get("critic_review_count", 0) or 0)
        except (TypeError, ValueError):
            critic_review_count = 0
        cleaned.append(
            {
                "artist": artist,
                "album": album,
                "critic_score": row.get("critic_score"),
                "critic_review_count": critic_review_count,
                "user_score": row.get("user_score"),
                "user_review_count": user_review_count,
                "review_count": user_review_count if user_review_count else review_count,
                "url": str(row.get("url", "")).strip(),
            }
        )
    return cleaned
