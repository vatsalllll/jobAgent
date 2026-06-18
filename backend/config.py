"""
Job Agent Configuration — all settings via environment variables.
Copy .env.example to .env and fill in your keys.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-5-20250514"
    openai_api_key: str = ""  # optional, for swarm consensus
    gemini_api_key: str = ""  # optional, for multi-model

    # ── Hugging Face ─────────────────────────────────────
    hf_api_key: str = ""
    hf_model: str = "Qwen/Qwen3-32B"
    hf_provider: str = "groq"

    # ── Contact finding ──────────────────────────────────
    hunter_api_key: str = ""

    # ── Gmail / Google Sheets ────────────────────────────
    google_credentials_json: str = ""  # path to OAuth client secret JSON
    tracking_sheet_id: str = ""  # Google Sheets spreadsheet ID
    google_token_path: str = "data/google_token.json"

    # ── Email ────────────────────────────────────────────
    sender_email: str = "vatsalomar1@gmail.com"
    sender_name: str = "Vatsal Omar"

    # ── Job filters ──────────────────────────────────────
    min_salary_inr: int = 50_000
    max_listing_age_days: int = 4
    target_locations: list[str] = ["Remote", "Bangalore", "Bengaluru", "Gurgaon", "Gurugram"]
    fallback_locations: list[str] = ["Hyderabad", "Pune"]

    # ── Paths ────────────────────────────────────────────
    base_resume_path: str = "data/base_resume.json"
    output_dir: str = "templates/outputs"
    resume_template_path: str = "templates/resume.html.j2"

    # ── Schedule ────────────────────────────────────────
    sweep_interval_hours: int = 4
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False


settings = Settings()

# Ensure output directory exists
Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
