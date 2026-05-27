from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth_service import get_request_user
from ..wardrobe_service import apply_client_snapshot, user_wardrobe_snapshot

wardrobe_bp = Blueprint("wardrobe", __name__)


@wardrobe_bp.post("/wardrobe/sync")
def sync_wardrobe():
    current_user = get_request_user()
    if current_user is None:
        return jsonify({"error": "Sign in to sync wardrobe."}), 401

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid wardrobe sync payload."}), 400

    user_id = int(current_user["id"])
    apply_client_snapshot(user_id, payload)
    return jsonify(user_wardrobe_snapshot(user_id))
