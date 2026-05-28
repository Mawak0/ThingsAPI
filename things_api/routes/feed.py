from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth_service import get_request_user, get_user_by_id
from ..db import get_db
from ..feed_service import (
    get_followed_author_ids,
    publication_payload,
    publication_row,
    trim_text,
)
from ..push_service import send_feed_publication_push
from ..time_utils import to_iso, utcnow

feed_bp = Blueprint("feed", __name__)


@feed_bp.get("/feed")
def feed():
    current_user = get_request_user()
    current_user_id = int(current_user["id"]) if current_user is not None else None
    followed_author_ids = get_followed_author_ids(current_user_id)

    feed_filter = ""
    params: tuple[int, ...] = ()
    if current_user_id is not None:
        feed_filter = """
        WHERE publications.author_id = ?
           OR publications.author_id IN (
               SELECT author_id
               FROM follows
               WHERE follower_id = ?
           )
        """
        params = (current_user_id, current_user_id)

    rows = get_db().execute(
        f"""
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
        {feed_filter}
        ORDER BY publications.created_at DESC, publications.id DESC
        LIMIT 40
        """,
        params,
    ).fetchall()

    return jsonify(
        {
            "publications": [
                publication_payload(row, followed_author_ids, current_user_id)
                for row in rows
            ]
        }
    )


@feed_bp.get("/users/me/publications")
def my_publications():
    current_user = get_request_user()
    if current_user is None:
        return jsonify({"error": "Sign in to browse your publications."}), 401

    current_user_id = int(current_user["id"])
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
        WHERE publications.author_id = ?
        ORDER BY publications.created_at DESC, publications.id DESC
        LIMIT 80
        """,
        (current_user_id,),
    ).fetchall()

    return jsonify(
        {
            "publications": [
                publication_payload(row, followed_author_ids, current_user_id)
                for row in rows
            ]
        }
    )


@feed_bp.get("/authors")
def authors():
    current_user = get_request_user()
    if current_user is None:
        return jsonify({"error": "Sign in to browse authors."}), 401

    current_user_id = int(current_user["id"])
    followed_author_ids = get_followed_author_ids(current_user_id)
    rows = get_db().execute(
        """
        SELECT
            users.id,
            users.name,
            COUNT(publications.id) AS post_count
        FROM users
        LEFT JOIN publications ON publications.author_id = users.id
        WHERE users.is_guest = 0
        GROUP BY users.id, users.name
        ORDER BY post_count DESC, users.name COLLATE NOCASE ASC
        LIMIT 100
        """
    ).fetchall()

    return jsonify(
        {
            "authors": [
                {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "post_count": int(row["post_count"]),
                    "is_following": int(row["id"]) in followed_author_ids,
                    "is_own_author": int(row["id"]) == current_user_id,
                }
                for row in rows
            ]
        }
    )


@feed_bp.post("/publications")
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

    send_feed_publication_push(
        int(current_user["id"]),
        str(current_user["name"]),
        publication_id,
        str(row["name"]),
    )

    return jsonify(
        publication_payload(row, get_followed_author_ids(int(current_user["id"])), int(current_user["id"]))
    ), 201


@feed_bp.post("/publications/<int:publication_id>/view")
def count_publication_view(publication_id: int):
    current_user = get_request_user()
    if current_user is None:
        return jsonify({"error": "Sign in to count publication views."}), 401

    db = get_db()
    row = db.execute(
        """
        SELECT id, author_id, views
        FROM publications
        WHERE id = ?
        """,
        (publication_id,),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Публикация не найдена."}), 404

    current_views = int(row["views"])
    current_user_id = int(current_user["id"])
    if int(row["author_id"]) == current_user_id:
        return jsonify({"views": current_views, "counted": False})

    cursor = db.execute(
        """
        INSERT OR IGNORE INTO publication_views (publication_id, viewer_id, created_at)
        VALUES (?, ?, ?)
        """,
        (publication_id, current_user_id, to_iso(utcnow())),
    )
    counted = cursor.rowcount > 0
    if counted:
        db.execute(
            """
            UPDATE publications
            SET views = views + 1
            WHERE id = ?
            """,
            (publication_id,),
        )
        current_views += 1

    db.commit()
    return jsonify({"views": current_views, "counted": counted})


@feed_bp.post("/authors/<int:author_id>/follow")
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


@feed_bp.delete("/authors/<int:author_id>/follow")
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
