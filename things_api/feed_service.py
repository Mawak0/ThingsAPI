from __future__ import annotations

import sqlite3
from typing import Any

from .db import get_db


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
