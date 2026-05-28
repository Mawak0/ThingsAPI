from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from flask import Flask, g
from werkzeug.security import generate_password_hash

from .config import (
    DATABASE_PATH,
    DEFAULT_USER_EMAIL,
    DEFAULT_USER_NAME,
    DEFAULT_USER_PASSWORD,
    STYLE_AUTHOR_EMAIL,
    STYLE_AUTHOR_NAME,
)
from .time_utils import to_iso, utcnow


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        connection = sqlite3.connect(DATABASE_PATH)
        connection.row_factory = sqlite3.Row
        g.db = connection
    return g.db


def close_db(_: Any) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)


def init_db() -> None:
    with closing(sqlite3.connect(DATABASE_PATH)) as db:
        db.row_factory = sqlite3.Row
        create_tables(db)
        db.commit()
        seed_default_user(db)
        seed_feed_author(db)
        seed_feed_publication(db)


def create_tables(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            is_guest INTEGER NOT NULL DEFAULT 0,
            avatar_data_url TEXT,
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
        CREATE TABLE IF NOT EXISTS publication_views (
            publication_id INTEGER NOT NULL,
            viewer_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(publication_id, viewer_id),
            FOREIGN KEY(publication_id) REFERENCES publications(id),
            FOREIGN KEY(viewer_id) REFERENCES users(id)
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
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS push_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS wardrobe_clothes (
            user_id INTEGER NOT NULL,
            local_id TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            season TEXT NOT NULL,
            color_scheme TEXT NOT NULL,
            image_url TEXT,
            emoji TEXT,
            fill_color TEXT,
            source TEXT NOT NULL,
            is_in_wardrobe INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, local_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS wardrobe_outfits (
            user_id INTEGER NOT NULL,
            local_id TEXT NOT NULL,
            name TEXT NOT NULL,
            style TEXT NOT NULL,
            season TEXT NOT NULL,
            color_scheme TEXT NOT NULL,
            image_url TEXT NOT NULL,
            views INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, local_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS wardrobe_outfit_items (
            user_id INTEGER NOT NULL,
            local_id TEXT NOT NULL,
            outfit_local_id TEXT NOT NULL,
            clothing_local_id TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, local_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS wardrobe_settings (
            user_id INTEGER PRIMARY KEY,
            language TEXT NOT NULL,
            theme TEXT NOT NULL,
            notifications_enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_publications_created ON publications(created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_push_tokens_user ON push_tokens(user_id)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_publication_items_publication ON publication_items(publication_id, sort_order)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_wardrobe_clothes_user ON wardrobe_clothes(user_id, sort_order)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_wardrobe_outfits_user ON wardrobe_outfits(user_id, sort_order)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_wardrobe_outfit_items_user ON wardrobe_outfit_items(user_id, outfit_local_id, sort_order)"
    )
    ensure_user_columns(db)


def ensure_user_columns(db: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "is_guest" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0")
    if "avatar_data_url" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN avatar_data_url TEXT")


def seed_default_user(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO users (email, password_hash, name, is_guest, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            DEFAULT_USER_EMAIL,
            generate_password_hash(DEFAULT_USER_PASSWORD),
            DEFAULT_USER_NAME,
            0,
            to_iso(utcnow()),
        ),
    )
    db.commit()


def seed_feed_author(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO users (email, password_hash, name, is_guest, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            STYLE_AUTHOR_EMAIL,
            generate_password_hash(DEFAULT_USER_PASSWORD),
            STYLE_AUTHOR_NAME,
            0,
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
