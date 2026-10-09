import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    username: str
    base_url: str
    output_dir: str = "reports"
    timezone: str = "America/New_York"
    low_history_threshold: int = 2
    recommendation_limit: int = 4
    friday_run_hour: int = 19
    friday_run_minute: int = 0
    email_enabled: bool = False
    email_from: str = ""
    email_to: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    aoty_base_url: str = "https://www.albumoftheyear.org"
    aoty_browser_enabled: bool = True
    aoty_browser_headless: bool = False
    aoty_browser_timeout_seconds: int = 40
    rym_enabled: bool = True
    rym_browser_timeout_seconds: int = 40
    rym_max_artist_lookups: int = 15
    llm_enabled: bool = False
    llm_provider: str = "ollama"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "LLaMA3.2:3B"
    llm_timeout_seconds: int = 60
    listening_history_path: str = ".listening_history.json"
    listening_history_refresh_days: int = 30
    release_highlight_min_artist_listens: int = 3


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def load_config() -> AppConfig:
    _load_dotenv()
    api_key = os.getenv("LASTFM_API_KEY", "").strip()
    username = os.getenv("LASTFM_USERNAME", "").strip()
    base_url = os.getenv("LASTFM_BASE_URL", "http://ws.audioscrobbler.com/2.0/").strip()
    output_dir = os.getenv("OUTPUT_DIR", "reports").strip()
    timezone = os.getenv("APP_TIMEZONE", "America/New_York").strip()
    low_history_threshold = int(os.getenv("LOW_HISTORY_THRESHOLD", "2"))
    recommendation_limit = int(os.getenv("RECOMMENDATION_LIMIT", "4"))
    friday_run_hour = int(os.getenv("FRIDAY_RUN_HOUR", "19"))
    friday_run_minute = int(os.getenv("FRIDAY_RUN_MINUTE", "0"))
    email_enabled = os.getenv("EMAIL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    email_from = os.getenv("EMAIL_FROM", "").strip()
    email_to = os.getenv("EMAIL_TO", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    aoty_base_url = os.getenv("AOTY_BASE_URL", "https://www.albumoftheyear.org").strip()
    aoty_browser_enabled = os.getenv("AOTY_BROWSER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    aoty_browser_headless = os.getenv("AOTY_BROWSER_HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"}
    aoty_browser_timeout_seconds = int(os.getenv("AOTY_BROWSER_TIMEOUT_SECONDS", "40"))
    rym_enabled = os.getenv("RYM_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    rym_browser_timeout_seconds = int(os.getenv("RYM_BROWSER_TIMEOUT_SECONDS", "40"))
    rym_max_artist_lookups = int(os.getenv("RYM_MAX_ARTIST_LOOKUPS", "15"))
    llm_enabled = os.getenv("LLM_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    llm_provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    llm_api_key = os.getenv("LLM_API_KEY", "").strip()
    llm_model = os.getenv("LLM_MODEL", "gpt-4.1-mini").strip()
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
    ollama_model = os.getenv("OLLAMA_MODEL", "LLaMA3.2:1B").strip()
    llm_timeout_seconds = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    listening_history_path = os.getenv("LISTENING_HISTORY_PATH", ".listening_history.json").strip()
    listening_history_refresh_days = int(os.getenv("LISTENING_HISTORY_REFRESH_DAYS", "30"))
    release_highlight_min_artist_listens = int(os.getenv("RELEASE_HIGHLIGHT_MIN_ARTIST_LISTENS", "3"))

    if not api_key:
        raise ValueError("LASTFM_API_KEY is required.")
    if not username:
        raise ValueError("LASTFM_USERNAME is required.")
    if not base_url:
        raise ValueError("LASTFM_BASE_URL is required.")
    if not 0 <= friday_run_hour <= 23:
        raise ValueError("FRIDAY_RUN_HOUR must be in range 0..23.")
    if not 0 <= friday_run_minute <= 59:
        raise ValueError("FRIDAY_RUN_MINUTE must be in range 0..59.")
    if email_enabled:
        required = {
            "EMAIL_FROM": email_from,
            "EMAIL_TO": email_to,
            "SMTP_HOST": smtp_host,
            "SMTP_USERNAME": smtp_username,
            "SMTP_PASSWORD": smtp_password,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"EMAIL_ENABLED=true but missing: {', '.join(missing)}")
    if llm_provider not in {"ollama", "openai"}:
        raise ValueError("LLM_PROVIDER must be one of: ollama, openai.")
    if llm_enabled and llm_provider == "openai" and not llm_api_key:
        raise ValueError("LLM_ENABLED=true and LLM_PROVIDER=openai require LLM_API_KEY.")
    if aoty_browser_timeout_seconds <= 0:
        raise ValueError("AOTY_BROWSER_TIMEOUT_SECONDS must be greater than 0.")
    if rym_browser_timeout_seconds <= 0:
        raise ValueError("RYM_BROWSER_TIMEOUT_SECONDS must be greater than 0.")
    if rym_max_artist_lookups < 0:
        raise ValueError("RYM_MAX_ARTIST_LOOKUPS must be zero or greater.")
    if listening_history_refresh_days <= 0:
        raise ValueError("LISTENING_HISTORY_REFRESH_DAYS must be greater than 0.")
    if release_highlight_min_artist_listens <= 0:
        raise ValueError("RELEASE_HIGHLIGHT_MIN_ARTIST_LISTENS must be greater than 0.")

    return AppConfig(
        api_key=api_key,
        username=username,
        base_url=base_url,
        output_dir=output_dir,
        timezone=timezone,
        low_history_threshold=low_history_threshold,
        recommendation_limit=recommendation_limit,
        friday_run_hour=friday_run_hour,
        friday_run_minute=friday_run_minute,
        email_enabled=email_enabled,
        email_from=email_from,
        email_to=email_to,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        aoty_base_url=aoty_base_url,
        aoty_browser_enabled=aoty_browser_enabled,
        aoty_browser_headless=aoty_browser_headless,
        aoty_browser_timeout_seconds=aoty_browser_timeout_seconds,
        rym_enabled=rym_enabled,
        rym_browser_timeout_seconds=rym_browser_timeout_seconds,
        rym_max_artist_lookups=rym_max_artist_lookups,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        llm_timeout_seconds=llm_timeout_seconds,
        listening_history_path=listening_history_path,
        listening_history_refresh_days=listening_history_refresh_days,
        release_highlight_min_artist_listens=release_highlight_min_artist_listens,
    )
