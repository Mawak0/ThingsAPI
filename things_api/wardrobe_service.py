from __future__ import annotations

import sqlite3
from typing import Any

from .db import get_db
from .time_utils import to_iso, utcnow


def trim_text(value: Any, fallback: str, max_length: int = 160) -> str:
    next_value = str(value or "").strip()
    return next_value[:max_length] or fallback


def trim_nullable_text(value: Any, max_length: int = 2048) -> str | None:
    next_value = str(value or "").strip()
    return next_value[:max_length] or None


def int_flag(value: Any) -> int:
    return 1 if bool(value) else 0


def should_accept_client_row(existing: sqlite3.Row | None, client_updated_at: str) -> bool:
    if existing is None:
        return True
    return client_updated_at >= str(existing["updated_at"])


def normalize_timestamp(value: Any) -> str:
    next_value = str(value or "").strip()
    return next_value or to_iso(utcnow())


def upsert_clothing(user_id: int, item: dict[str, Any], sort_order: int) -> None:
    local_id = trim_text(item.get("id"), "", 120)
    if not local_id:
        return

    updated_at = normalize_timestamp(item.get("updated_at"))
    db = get_db()
    existing = db.execute(
        """
        SELECT updated_at
        FROM wardrobe_clothes
        WHERE user_id = ? AND local_id = ?
        """,
        (user_id, local_id),
    ).fetchone()
    if not should_accept_client_row(existing, updated_at):
        return

    db.execute(
        """
        INSERT INTO wardrobe_clothes (
            user_id,
            local_id,
            name,
            category,
            season,
            color_scheme,
            image_url,
            emoji,
            fill_color,
            source,
            is_in_wardrobe,
            is_deleted,
            sort_order,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, local_id) DO UPDATE SET
            name = excluded.name,
            category = excluded.category,
            season = excluded.season,
            color_scheme = excluded.color_scheme,
            image_url = excluded.image_url,
            emoji = excluded.emoji,
            fill_color = excluded.fill_color,
            source = excluded.source,
            is_in_wardrobe = excluded.is_in_wardrobe,
            is_deleted = excluded.is_deleted,
            sort_order = excluded.sort_order,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            local_id,
            trim_text(item.get("name"), "Clothing"),
            trim_text(item.get("category"), "tops", 32),
            trim_text(item.get("season"), "summer", 32),
            trim_text(item.get("color_scheme"), "neutral", 32),
            trim_nullable_text(item.get("image_url")),
            trim_nullable_text(item.get("emoji"), 16),
            trim_nullable_text(item.get("fill_color"), 32),
            trim_text(item.get("source"), "user", 32),
            int_flag(item.get("is_in_wardrobe")),
            int_flag(item.get("is_deleted")),
            int(item.get("sort_order") or sort_order),
            normalize_timestamp(item.get("created_at")),
            updated_at,
        ),
    )


def upsert_outfit(user_id: int, outfit: dict[str, Any], sort_order: int) -> None:
    local_id = trim_text(outfit.get("id"), "", 120)
    if not local_id:
        return

    updated_at = normalize_timestamp(outfit.get("updated_at"))
    db = get_db()
    existing = db.execute(
        """
        SELECT updated_at
        FROM wardrobe_outfits
        WHERE user_id = ? AND local_id = ?
        """,
        (user_id, local_id),
    ).fetchone()
    if not should_accept_client_row(existing, updated_at):
        return

    db.execute(
        """
        INSERT INTO wardrobe_outfits (
            user_id,
            local_id,
            name,
            style,
            season,
            color_scheme,
            image_url,
            views,
            is_deleted,
            sort_order,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, local_id) DO UPDATE SET
            name = excluded.name,
            style = excluded.style,
            season = excluded.season,
            color_scheme = excluded.color_scheme,
            image_url = excluded.image_url,
            views = excluded.views,
            is_deleted = excluded.is_deleted,
            sort_order = excluded.sort_order,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            local_id,
            trim_text(outfit.get("name"), "Outfit"),
            trim_text(outfit.get("style"), "casual", 32),
            trim_text(outfit.get("season"), "summer", 32),
            trim_text(outfit.get("color_scheme"), "neutral", 32),
            trim_text(outfit.get("image_url"), "~/assets/baseClothes/white_tshirt.jpg", 2048),
            int(outfit.get("views") or 0),
            int_flag(outfit.get("is_deleted")),
            int(outfit.get("sort_order") or sort_order),
            normalize_timestamp(outfit.get("created_at")),
            updated_at,
        ),
    )


def replace_outfit_items(user_id: int, outfit: dict[str, Any]) -> None:
    local_outfit_id = trim_text(outfit.get("id"), "", 120)
    if not local_outfit_id:
        return

    items = outfit.get("items")
    if not isinstance(items, list):
        items = []

    db = get_db()
    db.execute(
        """
        DELETE FROM wardrobe_outfit_items
        WHERE user_id = ? AND outfit_local_id = ?
        """,
        (user_id, local_outfit_id),
    )

    for index, clothing_id in enumerate(items):
        clothing_local_id = trim_text(clothing_id, "", 120)
        if not clothing_local_id:
            continue

        now = normalize_timestamp(outfit.get("updated_at"))
        local_id = f"{local_outfit_id}:{clothing_local_id}:{index}"
        db.execute(
            """
            INSERT INTO wardrobe_outfit_items (
                user_id,
                local_id,
                outfit_local_id,
                clothing_local_id,
                sort_order,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, local_id, local_outfit_id, clothing_local_id, index, now, now),
        )


def upsert_settings(user_id: int, settings: dict[str, Any] | None) -> None:
    if not isinstance(settings, dict):
        return

    updated_at = normalize_timestamp(settings.get("updated_at"))
    db = get_db()
    existing = db.execute(
        """
        SELECT updated_at
        FROM wardrobe_settings
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if not should_accept_client_row(existing, updated_at):
        return

    db.execute(
        """
        INSERT INTO wardrobe_settings (
            user_id,
            language,
            theme,
            notifications_enabled,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            language = excluded.language,
            theme = excluded.theme,
            notifications_enabled = excluded.notifications_enabled,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            trim_text(settings.get("language"), "ru", 16),
            trim_text(settings.get("theme"), "light", 32),
            int_flag(settings.get("notifications_enabled", True)),
            updated_at,
        ),
    )


def apply_client_snapshot(user_id: int, payload: dict[str, Any]) -> None:
    db = get_db()
    with db:
        for index, item in enumerate(payload.get("clothes") or []):
            if isinstance(item, dict):
                upsert_clothing(user_id, item, index)

        for index, outfit in enumerate(payload.get("outfits") or []):
            if isinstance(outfit, dict):
                upsert_outfit(user_id, outfit, index)
                replace_outfit_items(user_id, outfit)

        upsert_settings(user_id, payload.get("settings"))


def user_wardrobe_snapshot(user_id: int) -> dict[str, Any]:
    db = get_db()
    clothes = db.execute(
        """
        SELECT
            local_id,
            name,
            category,
            season,
            color_scheme,
            image_url,
            emoji,
            fill_color,
            source,
            is_in_wardrobe,
            is_deleted,
            sort_order,
            created_at,
            updated_at
        FROM wardrobe_clothes
        WHERE user_id = ?
        ORDER BY sort_order ASC, local_id ASC
        """,
        (user_id,),
    ).fetchall()
    outfits = db.execute(
        """
        SELECT
            local_id,
            name,
            style,
            season,
            color_scheme,
            image_url,
            views,
            is_deleted,
            sort_order,
            created_at,
            updated_at
        FROM wardrobe_outfits
        WHERE user_id = ?
        ORDER BY sort_order ASC, local_id ASC
        """,
        (user_id,),
    ).fetchall()
    item_rows = db.execute(
        """
        SELECT outfit_local_id, clothing_local_id
        FROM wardrobe_outfit_items
        WHERE user_id = ?
        ORDER BY outfit_local_id ASC, sort_order ASC
        """,
        (user_id,),
    ).fetchall()
    settings = db.execute(
        """
        SELECT language, theme, notifications_enabled, updated_at
        FROM wardrobe_settings
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    items_by_outfit: dict[str, list[str]] = {}
    for item in item_rows:
        items_by_outfit.setdefault(str(item["outfit_local_id"]), []).append(str(item["clothing_local_id"]))

    return {
        "clothes": [
            {
                "id": row["local_id"],
                "name": row["name"],
                "category": row["category"],
                "season": row["season"],
                "color_scheme": row["color_scheme"],
                "image_url": row["image_url"],
                "emoji": row["emoji"],
                "fill_color": row["fill_color"],
                "source": row["source"],
                "is_in_wardrobe": bool(row["is_in_wardrobe"]),
                "is_deleted": bool(row["is_deleted"]),
                "sort_order": int(row["sort_order"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in clothes
        ],
        "outfits": [
            {
                "id": row["local_id"],
                "name": row["name"],
                "style": row["style"],
                "season": row["season"],
                "color_scheme": row["color_scheme"],
                "image_url": row["image_url"],
                "views": int(row["views"]),
                "items": items_by_outfit.get(str(row["local_id"]), []),
                "is_deleted": bool(row["is_deleted"]),
                "sort_order": int(row["sort_order"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in outfits
        ],
        "settings": {
            "language": settings["language"] if settings is not None else "ru",
            "theme": settings["theme"] if settings is not None else "light",
            "notifications_enabled": bool(settings["notifications_enabled"]) if settings is not None else True,
            "updated_at": settings["updated_at"] if settings is not None else to_iso(utcnow()),
        },
    }
