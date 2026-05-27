from __future__ import annotations

import base64
import re

from flask import Blueprint, jsonify, request

from ..auth_service import (
    delete_user_avatar,
    get_request_user,
    update_user_avatar,
    user_payload,
)

profile_bp = Blueprint("profile", __name__)

MAX_AVATAR_BYTES = 256 * 1024
MAX_AVATAR_DATA_URL_LENGTH = 380 * 1024
AVATAR_DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg|jpg|webp));base64,([A-Za-z0-9+/=\s]+)$")


def current_user_or_error():
    user = get_request_user()
    if user is None:
        return None, (jsonify({"error": "Войдите в аккаунт, чтобы управлять профилем."}), 401)

    return user, None


def normalize_avatar_data_url(payload: dict) -> tuple[str | None, str | None]:
    data_url = str(payload.get("avatar_data_url", "")).strip()

    if not data_url:
        mime = str(payload.get("avatar_mime", "image/jpeg")).strip().lower()
        raw_base64 = str(payload.get("avatar_base64", "")).strip()
        if raw_base64:
            data_url = f"data:{mime};base64,{raw_base64}"

    if not data_url:
        return None, "Передайте аватарку в формате base64."

    if len(data_url) > MAX_AVATAR_DATA_URL_LENGTH:
        return None, "Аватарка слишком большая."

    match = AVATAR_DATA_URL_RE.match(data_url)
    if match is None:
        return None, "Аватарка должна быть data URL с png, jpeg или webp."

    mime, raw_base64 = match.groups()
    compact_base64 = "".join(raw_base64.split())

    try:
        decoded = base64.b64decode(compact_base64, validate=True)
    except ValueError:
        return None, "Base64 аватарки поврежден."

    if not decoded:
        return None, "Аватарка пустая."

    if len(decoded) > MAX_AVATAR_BYTES:
        return None, "Аватарка должна быть меньше 256 КБ."

    return f"data:{mime};base64,{compact_base64}", None


@profile_bp.get("/users/me")
def me():
    user, error = current_user_or_error()
    if error is not None:
        return error

    return jsonify({"user": user_payload(user)})


@profile_bp.put("/users/me/avatar")
def update_avatar():
    user, error = current_user_or_error()
    if error is not None:
        return error

    payload = request.get_json(silent=True) or {}
    avatar_data_url, avatar_error = normalize_avatar_data_url(payload)
    if avatar_error is not None:
        return jsonify({"error": avatar_error}), 400

    updated_user = update_user_avatar(int(user["id"]), avatar_data_url)
    if updated_user is None:
        return jsonify({"error": "Пользователь не найден."}), 404

    return jsonify({"user": user_payload(updated_user)})


@profile_bp.delete("/users/me/avatar")
def delete_avatar():
    user, error = current_user_or_error()
    if error is not None:
        return error

    updated_user = delete_user_avatar(int(user["id"]))
    if updated_user is None:
        return jsonify({"error": "Пользователь не найден."}), 404

    return jsonify({"user": user_payload(updated_user)})
