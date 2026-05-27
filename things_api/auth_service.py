from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from flask import current_app, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from .config import ACCESS_TOKEN_SALT, ACCESS_TOKEN_TTL_SECONDS, REFRESH_TOKEN_TTL_DAYS
from .db import get_db
from .time_utils import parse_iso, to_iso, utcnow


def get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


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
        """
        SELECT id, email, password_hash, name, is_guest, avatar_data_url
        FROM users
        WHERE email = ?
        """,
        (email.lower().strip(),),
    ).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        """
        SELECT id, email, password_hash, name, is_guest, avatar_data_url
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


def create_user(email: str, password: str, name: str) -> sqlite3.Row:
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO users (email, password_hash, name, is_guest, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            email.lower().strip(),
            generate_password_hash(password),
            name.strip(),
            0,
            to_iso(utcnow()),
        ),
    )
    db.commit()
    user = get_user_by_id(int(cursor.lastrowid))
    if user is None:
        raise RuntimeError("User was not found after creation.")
    return user


def user_payload(user: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "avatar_data_url": user["avatar_data_url"],
    }


def update_user_avatar(user_id: int, avatar_data_url: str) -> sqlite3.Row | None:
    db = get_db()
    db.execute(
        """
        UPDATE users
        SET avatar_data_url = ?
        WHERE id = ?
        """,
        (avatar_data_url, user_id),
    )
    db.commit()
    return get_user_by_id(user_id)


def delete_user_avatar(user_id: int) -> sqlite3.Row | None:
    db = get_db()
    db.execute(
        """
        UPDATE users
        SET avatar_data_url = NULL
        WHERE id = ?
        """,
        (user_id,),
    )
    db.commit()
    return get_user_by_id(user_id)


def validate_refresh_token(raw_token: str) -> sqlite3.Row | None:
    row = get_db().execute(
        """
        SELECT id, user_id, token_hash, expires_at, created_at, revoked_at
        FROM refresh_tokens
        WHERE token_hash = ?
        """,
        (hash_token(raw_token),),
    ).fetchone()

    if row is None or row["revoked_at"] is not None:
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
        "user": user_payload(user),
    }


def validate_access_token(token: str) -> dict[str, Any]:
    serializer = get_serializer()
    return serializer.loads(token, salt=ACCESS_TOKEN_SALT, max_age=ACCESS_TOKEN_TTL_SECONDS)


def get_request_user() -> sqlite3.Row | None:
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer").strip()

    if not token:
        return None

    try:
        payload = validate_access_token(token)
    except (BadSignature, SignatureExpired):
        return None

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None

    return get_user_by_id(user_id)
