from __future__ import annotations

from flask import Flask, jsonify

from .config import SECRET_KEY
from .db import init_app as init_db_app
from .db import init_db
from .routes.auth import auth_bp
from .routes.feed import feed_bp
from .routes.profile import profile_bp
from .routes.wardrobe import wardrobe_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY

    init_db_app(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(feed_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(wardrobe_bp)

    @app.get("/health")
    def health_check():
        return jsonify({"status": "ok"})

    init_db()
    return app
