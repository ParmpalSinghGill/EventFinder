"""Load and save notification secrets from a local .env file (not committed)."""

import os

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"
DISCORD_WEBHOOK_URL = "DISCORD_WEBHOOK_URL"


def _strip_value(raw: str) -> str:
    value = (raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_dotenv(path: str = ENV_FILE) -> dict:
    """Parse KEY=VALUE lines and export them into os.environ (without overwriting)."""
    env = {}
    if not os.path.exists(path):
        return env
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if not text or text.startswith("#") or "=" not in text:
                    continue
                key, raw = text.split("=", 1)
                key = key.strip()
                if not key:
                    continue
                value = _strip_value(raw)
                env[key] = value
                os.environ.setdefault(key, value)
    except Exception:
        pass
    return env


def env_get(*keys: str) -> str:
    """First non-empty value from .env, then process environment."""
    parsed = load_dotenv()
    for key in keys:
        value = (parsed.get(key) or os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def upsert_env(updates: dict, path: str = ENV_FILE):
    """Create or update keys in .env without dropping unrelated entries."""
    values = {}
    lines = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.rstrip("\n")
                stripped = raw.strip()
                if stripped and not stripped.startswith("#") and "=" in raw:
                    key, current = raw.split("=", 1)
                    key = key.strip()
                    values[key] = current
                    lines.append(("key", key))
                else:
                    lines.append(("raw", raw))

    for key, value in updates.items():
        if value is None:
            continue
        values[key] = str(value)
        if not any(kind == "key" and name == key for kind, name in lines):
            lines.append(("key", key))

    out = []
    written = set()
    for kind, payload in lines:
        if kind == "raw":
            out.append(payload)
        else:
            out.append(f"{payload}={values.get(payload, '')}")
            written.add(payload)
    for key, value in values.items():
        if key not in written:
            out.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip() + "\n")


def apply_telegram_secrets(conf: dict) -> dict:
    token = env_get(TELEGRAM_BOT_TOKEN)
    chat_id = env_get(TELEGRAM_CHAT_ID)
    if token:
        conf["bot_token"] = token
    if chat_id:
        conf["chat_id"] = chat_id
    return conf


def apply_discord_secrets(conf: dict) -> dict:
    url = env_get(DISCORD_WEBHOOK_URL)
    if url:
        conf["webhook_url"] = url
    return conf


def save_notification_secrets(telegram: dict | None = None, discord: dict | None = None):
    updates = {}
    if telegram:
        if "bot_token" in telegram:
            updates[TELEGRAM_BOT_TOKEN] = (telegram.get("bot_token") or "").strip()
        if "chat_id" in telegram:
            updates[TELEGRAM_CHAT_ID] = (telegram.get("chat_id") or "").strip()
    if discord and "webhook_url" in discord:
        updates[DISCORD_WEBHOOK_URL] = (discord.get("webhook_url") or "").strip()
    if updates:
        upsert_env(updates)
