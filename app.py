from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Flask, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "things_api.sqlite3"
ACCESS_TOKEN_TTL_SECONDS = 15 * 60
REFRESH_TOKEN_TTL_DAYS = 30
ACCESS_TOKEN_SALT = "things-api-access"
DEFAULT_USER_EMAIL = "demo@things.local"
DEFAULT_USER_PASSWORD = "Password123!"
DEFAULT_USER_NAME = "Demo User"

app = Flask(__name__)
app.config["SECRET_KEY"] = "things-api-dev-secret"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        connection = sqlite3.connect(DATABASE_PATH)
        connection.row_factory = sqlite3.Row
        g.db = connection
    return g.db


@app.teardown_appcontext
def close_db(_: Any) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    with closing(sqlite3.connect(DATABASE_PATH)) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        db.commit()
        seed_default_user(db)


def seed_default_user(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO users (email, password_hash, name, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            DEFAULT_USER_EMAIL,
            generate_password_hash(DEFAULT_USER_PASSWORD),
            DEFAULT_USER_NAME,
            to_iso(utcnow()),
        ),
    )
    db.commit()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user: sqlite3.Row) -> str:
    serializer = get_serializer()
    return serializer.dumps(
        {
            "sub": user["id"],
            "email": user["email"],
            "name": user["name"],
        },
        salt=ACCESS_TOKEN_SALT,
    )


def create_refresh_token(user_id: int) -> str:
    raw_token = secrets.token_urlsafe(48)
    db = get_db()
    db.execute(
        """
        INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at, revoked_at)
        VALUES (?, ?, ?, ?, NULL)
        """,
        (
            user_id,
            hash_token(raw_token),
            to_iso(utcnow() + timedelta(days=REFRESH_TOKEN_TTL_DAYS)),
            to_iso(utcnow()),
        ),
    )
    db.commit()
    return raw_token


def revoke_refresh_token(raw_token: str) -> None:
    db = get_db()
    db.execute(
        """
        UPDATE refresh_tokens
        SET revoked_at = ?
        WHERE token_hash = ? AND revoked_at IS NULL
        """,
        (to_iso(utcnow()), hash_token(raw_token)),
    )
    db.commit()


def get_user_by_email(email: str) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT id, email, password_hash, name FROM users WHERE email = ?",
        (email.lower().strip(),),
    ).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT id, email, password_hash, name FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def validate_refresh_token(raw_token: str) -> sqlite3.Row | None:
    row = get_db().execute(
        """
        SELECT id, user_id, token_hash, expires_at, created_at, revoked_at
        FROM refresh_tokens
        WHERE token_hash = ?
        """,
        (hash_token(raw_token),),
    ).fetchone()

    if row is None:
        return None

    if row["revoked_at"] is not None:
        return None

    if parse_iso(row["expires_at"]) <= utcnow():
        return None

    return row


def build_auth_payload(user: sqlite3.Row, refresh_token: str) -> dict[str, Any]:
    return {
        "access_token": create_access_token(user),
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
        },
    }


def validate_access_token(token: str) -> dict[str, Any]:
    serializer = get_serializer()
    return serializer.loads(token, salt=ACCESS_TOKEN_SALT, max_age=ACCESS_TOKEN_TTL_SECONDS)


@app.get("/health")
def health_check():
    return jsonify({"status": "ok"})


@app.post("/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    if not email or not password:
        return jsonify({"error": "Email и пароль обязательны."}), 400

    user = get_user_by_email(email)
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Неверный email или пароль."}), 401

    refresh_token = create_refresh_token(int(user["id"]))
    return jsonify(build_auth_payload(user, refresh_token))


@app.post("/auth/refresh")
def refresh():
    payload = request.get_json(silent=True) or {}
    raw_refresh_token = str(payload.get("refresh_token", "")).strip()

    if not raw_refresh_token:
        return jsonify({"error": "Refresh token обязателен."}), 400

    refresh_row = validate_refresh_token(raw_refresh_token)
    if refresh_row is None:
        return jsonify({"error": "Refresh token недействителен или истек."}), 401

    user = get_user_by_id(int(refresh_row["user_id"]))
    if user is None:
        return jsonify({"error": "Пользователь не найден."}), 404

    revoke_refresh_token(raw_refresh_token)
    next_refresh_token = create_refresh_token(int(user["id"]))
    return jsonify(build_auth_payload(user, next_refresh_token))


@app.get("/auth/validate")
def validate():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer").strip()

    if not token:
        return jsonify({"error": "Access token обязателен."}), 401

    try:
        payload = validate_access_token(token)
    except SignatureExpired:
        return jsonify({"error": "Access token истек."}), 401
    except BadSignature:
        return jsonify({"error": "Access token недействителен."}), 401

    return jsonify({"valid": True, "payload": payload})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
