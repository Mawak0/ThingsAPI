from __future__ import annotations

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / "things_api.sqlite3"
FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    str(BASE_DIR / "firebase-service-account.json"),
)
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON", "")

SECRET_KEY = "things-api-dev-secret"
ACCESS_TOKEN_TTL_SECONDS = 15 * 60
REFRESH_TOKEN_TTL_DAYS = 30
ACCESS_TOKEN_SALT = "things-api-access"

DEFAULT_USER_EMAIL = "demo@things.local"
DEFAULT_USER_PASSWORD = "Password123!"
DEFAULT_USER_NAME = "Demo User"

STYLE_AUTHOR_EMAIL = "karolina@things.local"
STYLE_AUTHOR_NAME = "Каролина"
