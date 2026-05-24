from __future__ import annotations

from flask import Blueprint, jsonify, request
from itsdangerous import BadSignature, SignatureExpired
from werkzeug.security import check_password_hash

from ..auth_service import (
    build_auth_payload,
    create_refresh_token,
    get_user_by_email,
    get_user_by_id,
    revoke_refresh_token,
    validate_access_token,
    validate_refresh_token,
)

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/auth/login")
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


@auth_bp.post("/auth/refresh")
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


@auth_bp.get("/auth/validate")
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
