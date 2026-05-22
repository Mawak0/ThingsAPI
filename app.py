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
STYLE_AUTHOR_EMAIL = "karolina@things.local"
STYLE_AUTHOR_NAME = "Каролина"

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
        db.row_factory = sqlite3.Row
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
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author_id INTEGER NOT NULL,
                source_outfit_id TEXT NOT NULL,
                name TEXT NOT NULL,
                style TEXT NOT NULL,
                season TEXT NOT NULL,
                color_scheme TEXT NOT NULL,
                views INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(author_id) REFERENCES users(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS publication_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publication_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                image_url TEXT,
                emoji TEXT,
                fill_color TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(publication_id) REFERENCES publications(id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS follows (
                follower_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(follower_id, author_id),
                FOREIGN KEY(follower_id) REFERENCES users(id),
                FOREIGN KEY(author_id) REFERENCES users(id)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_publications_created ON publications(created_at)")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_publication_items_publication ON publication_items(publication_id, sort_order)"
        )
        db.commit()
        seed_default_user(db)
        seed_feed_author(db)
        seed_feed_publication(db)


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


def seed_feed_author(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO users (email, password_hash, name, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            STYLE_AUTHOR_EMAIL,
            generate_password_hash(DEFAULT_USER_PASSWORD),
            STYLE_AUTHOR_NAME,
            to_iso(utcnow()),
        ),
    )
    db.commit()


def seed_feed_publication(db: sqlite3.Connection) -> None:
    existing_publication = db.execute(
        """
        SELECT id
        FROM publications
        LIMIT 1
        """
    ).fetchone()
    if existing_publication is not None:
        return

    author = db.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        """,
        (STYLE_AUTHOR_EMAIL,),
    ).fetchone()
    if author is None:
        return

    cursor = db.execute(
        """
        INSERT INTO publications (
            author_id,
            source_outfit_id,
            name,
            style,
            season,
            color_scheme,
            views,
            created_at
        )
        VALUES (?, 'seed-city', 'Городской слой', 'casual', 'spring', 'neutral', 12, ?)
        """,
        (int(author["id"]), to_iso(utcnow())),
    )
    publication_id = int(cursor.lastrowid)
    seed_items = [
        ("Белая футболка", "~/assets/baseClothes/white_tshirt.jpg"),
        ("Синие брюки", "~/assets/baseClothes/pants_blue.png"),
        ("Черные ботинки", "~/assets/baseClothes/boots.png"),
    ]

    for index, (name, image_url) in enumerate(seed_items):
        db.execute(
            """
            INSERT INTO publication_items (
                publication_id,
                name,
                image_url,
                sort_order
            )
            VALUES (?, ?, ?, ?)
            """,
            (publication_id, name, image_url, index),
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


def get_publication_items(publication_id: int) -> list[dict[str, Any]]:
    rows = get_db().execute(
        """
        SELECT id, name, image_url, emoji, fill_color
        FROM publication_items
        WHERE publication_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (publication_id,),
    ).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "image_url": row["image_url"],
            "emoji": row["emoji"],
            "fill_color": row["fill_color"],
        }
        for row in rows
    ]


def get_followed_author_ids(user_id: int | None) -> set[int]:
    if user_id is None:
        return set()

    rows = get_db().execute(
        """
        SELECT author_id
        FROM follows
        WHERE follower_id = ?
        """,
        (user_id,),
    ).fetchall()
    return {int(row["author_id"]) for row in rows}


def publication_payload(
    publication: sqlite3.Row,
    followed_author_ids: set[int],
    current_user_id: int | None,
) -> dict[str, Any]:
    author_id = int(publication["author_id"])
    return {
        "id": int(publication["id"]),
        "source_outfit_id": publication["source_outfit_id"],
        "name": publication["name"],
        "style": publication["style"],
        "season": publication["season"],
        "color_scheme": publication["color_scheme"],
        "views": int(publication["views"]),
        "created_at": publication["created_at"],
        "author": {
            "id": author_id,
            "name": publication["author_name"],
        },
        "is_following": author_id in followed_author_ids,
        "is_own_author": author_id == current_user_id,
        "items": get_publication_items(int(publication["id"])),
    }


def trim_text(value: Any, fallback: str, max_length: int = 120) -> str:
    next_value = str(value or "").strip()
    return next_value[:max_length] or fallback


def publication_row(publication_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        """
        SELECT
            publications.id,
            publications.author_id,
            publications.source_outfit_id,
            publications.name,
            publications.style,
            publications.season,
            publications.color_scheme,
            publications.views,
            publications.created_at,
            users.name AS author_name
        FROM publications
        INNER JOIN users ON users.id = publications.author_id
        WHERE publications.id = ?
        """,
        (publication_id,),
    ).fetchone()


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


@app.get("/feed")
def feed():
    current_user = get_request_user()
    current_user_id = int(current_user["id"]) if current_user is not None else None
    followed_author_ids = get_followed_author_ids(current_user_id)
    rows = get_db().execute(
        """
        SELECT
            publications.id,
            publications.author_id,
            publications.source_outfit_id,
            publications.name,
            publications.style,
            publications.season,
            publications.color_scheme,
            publications.views,
            publications.created_at,
            users.name AS author_name
        FROM publications
        INNER JOIN users ON users.id = publications.author_id
        ORDER BY publications.created_at DESC, publications.id DESC
        LIMIT 40
        """
    ).fetchall()

    return jsonify(
        {
            "publications": [
                publication_payload(row, followed_author_ids, current_user_id)
                for row in rows
            ]
        }
    )


@app.post("/publications")
def publish_outfit():
    current_user = get_request_user()
    if current_user is None:
        return jsonify({"error": "Войдите, чтобы опубликовать образ."}), 401

    payload = request.get_json(silent=True) or {}
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"error": "В публикации должна быть хотя бы одна вещь."}), 400

    db = get_db()
    created_at = to_iso(utcnow())
    cursor = db.execute(
        """
        INSERT INTO publications (
            author_id,
            source_outfit_id,
            name,
            style,
            season,
            color_scheme,
            views,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            int(current_user["id"]),
            trim_text(payload.get("source_outfit_id"), "local-outfit", 80),
            trim_text(payload.get("name"), "Новый образ"),
            trim_text(payload.get("style"), "casual", 32),
            trim_text(payload.get("season"), "summer", 32),
            trim_text(payload.get("color_scheme"), "neutral", 32),
            created_at,
        ),
    )
    publication_id = int(cursor.lastrowid)

    for index, item in enumerate(items[:8]):
        if not isinstance(item, dict):
            continue

        db.execute(
            """
            INSERT INTO publication_items (
                publication_id,
                name,
                image_url,
                emoji,
                fill_color,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                publication_id,
                trim_text(item.get("name"), f"Вещь {index + 1}"),
                str(item.get("image_url") or "").strip() or None,
                str(item.get("emoji") or "").strip() or None,
                str(item.get("fill_color") or "").strip() or None,
                index,
            ),
        )

    db.commit()
    row = publication_row(publication_id)
    if row is None:
        return jsonify({"error": "Публикация не найдена после сохранения."}), 500

    return jsonify(
        publication_payload(row, get_followed_author_ids(int(current_user["id"])), int(current_user["id"]))
    ), 201


@app.post("/publications/<int:publication_id>/view")
def count_publication_view(publication_id: int):
    db = get_db()
    db.execute(
        """
        UPDATE publications
        SET views = views + 1
        WHERE id = ?
        """,
        (publication_id,),
    )
    db.commit()

    row = db.execute(
        """
        SELECT views
        FROM publications
        WHERE id = ?
        """,
        (publication_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Публикация не найдена."}), 404

    return jsonify({"views": int(row["views"])})


@app.post("/authors/<int:author_id>/follow")
def follow_author(author_id: int):
    current_user = get_request_user()
    if current_user is None:
        return jsonify({"error": "Войдите, чтобы подписываться на авторов."}), 401

    follower_id = int(current_user["id"])
    if follower_id == author_id:
        return jsonify({"error": "Нельзя подписаться на себя."}), 400

    if get_user_by_id(author_id) is None:
        return jsonify({"error": "Автор не найден."}), 404

    get_db().execute(
        """
        INSERT OR IGNORE INTO follows (follower_id, author_id, created_at)
        VALUES (?, ?, ?)
        """,
        (follower_id, author_id, to_iso(utcnow())),
    )
    get_db().commit()
    return jsonify({"following": True})


@app.delete("/authors/<int:author_id>/follow")
def unfollow_author(author_id: int):
    current_user = get_request_user()
    if current_user is None:
        return jsonify({"error": "Войдите, чтобы управлять подписками."}), 401

    get_db().execute(
        """
        DELETE FROM follows
        WHERE follower_id = ? AND author_id = ?
        """,
        (int(current_user["id"]), author_id),
    )
    get_db().commit()
    return jsonify({"following": False})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
