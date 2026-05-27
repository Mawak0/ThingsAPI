from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import FIREBASE_CREDENTIALS_JSON, FIREBASE_CREDENTIALS_PATH
from .db import get_db
from .time_utils import to_iso, utcnow

logger = logging.getLogger(__name__)

_firebase_initialized = False
_firebase_unavailable_reason: str | None = None


def normalize_push_token(raw_token: Any) -> str:
    return str(raw_token or "").strip()


def save_push_token(user_id: int, token: str, platform: str) -> None:
    now = to_iso(utcnow())
    get_db().execute(
        """
        INSERT INTO push_tokens (user_id, token, platform, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(token) DO UPDATE SET
            user_id = excluded.user_id,
            platform = excluded.platform,
            updated_at = excluded.updated_at
        """,
        (user_id, token, platform, now, now),
    )
    get_db().commit()


def delete_push_token(user_id: int, token: str) -> None:
    get_db().execute(
        """
        DELETE FROM push_tokens
        WHERE user_id = ? AND token = ?
        """,
        (user_id, token),
    )
    get_db().commit()


def follower_tokens_for_author(author_id: int) -> list[str]:
    rows = get_db().execute(
        """
        SELECT push_tokens.token
        FROM push_tokens
        INNER JOIN follows ON follows.follower_id = push_tokens.user_id
        WHERE follows.author_id = ?
        """,
        (author_id,),
    ).fetchall()
    return [str(row["token"]) for row in rows if row["token"]]


def firebase_is_ready() -> bool:
    global _firebase_initialized, _firebase_unavailable_reason
    if _firebase_initialized:
        return True
    if _firebase_unavailable_reason is not None:
        return False

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError as error:
        _firebase_unavailable_reason = f"firebase-admin is not installed: {error}"
        logger.warning(_firebase_unavailable_reason)
        return False

    try:
        if FIREBASE_CREDENTIALS_JSON.strip():
            cert = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
        else:
            credentials_path = Path(FIREBASE_CREDENTIALS_PATH)
            if not credentials_path.exists():
                _firebase_unavailable_reason = f"Firebase credentials not found: {credentials_path}"
                logger.warning(_firebase_unavailable_reason)
                return False
            cert = credentials.Certificate(str(credentials_path))

        firebase_admin.initialize_app(cert)
    except ValueError:
        pass
    except Exception as error:
        _firebase_unavailable_reason = f"Firebase init failed: {error}"
        logger.warning(_firebase_unavailable_reason)
        return False

    _firebase_initialized = True
    return True


def send_feed_publication_push(author_id: int, author_name: str, publication_id: int, publication_name: str) -> None:
    tokens = follower_tokens_for_author(author_id)
    if not tokens:
        return
    if not firebase_is_ready():
        return

    from firebase_admin import messaging

    message = messaging.MulticastMessage(
        tokens=tokens[:500],
        notification=messaging.Notification(
            title="Новый образ в ленте",
            body=f"{author_name}: {publication_name}",
        ),
        data={
            "type": "feed_publication",
            "publication_id": str(publication_id),
            "author_id": str(author_id),
        },
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="feed",
                click_action="OPEN_FEED",
            ),
        ),
    )

    try:
        response = messaging.send_each_for_multicast(message)
    except Exception as error:
        logger.warning("Failed to send feed push: %s", error)
        return

    invalid_tokens: list[str] = []
    for index, item in enumerate(response.responses):
        if item.success:
            continue
        error = item.exception
        error_code = getattr(error, "code", "")
        if error_code in {"registration-token-not-registered", "invalid-argument"}:
            invalid_tokens.append(tokens[index])
        logger.warning("Feed push token failed: %s", error)

    if invalid_tokens:
        placeholders = ",".join("?" for _ in invalid_tokens)
        get_db().execute(
            f"DELETE FROM push_tokens WHERE token IN ({placeholders})",
            invalid_tokens,
        )
        get_db().commit()
