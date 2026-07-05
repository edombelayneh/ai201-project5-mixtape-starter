"""
app.py — Mixtape

Flask application factory and database setup.
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()


def create_app(config=None):
    app = Flask(__name__)

    # Default configuration
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///mixtape.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

    if config:
        app.config.update(config)

    db.init_app(app)

    # Register blueprints
    from routes.songs import songs_bp
    from routes.playlists import playlists_bp
    from routes.users import users_bp
    from routes.feed import feed_bp

    app.register_blueprint(songs_bp, url_prefix="/songs")
    app.register_blueprint(playlists_bp, url_prefix="/playlists")
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(feed_bp, url_prefix="/feed")

    # --- Dev testing console (NOT part of the app's real API) -----------------
    # A browser harness for exercising the live endpoints while bug-hunting.
    # These two routes are read-only conveniences to populate the UI; they do
    # not alter any existing behavior.
    @app.route("/")
    def console():
        return app.send_static_file("console.html")

    @app.route("/dev/bootstrap")
    def dev_bootstrap():
        from models import User, Playlist
        users = [{"id": u.id, "username": u.username} for u in db.session.query(User).all()]
        playlists = [{"id": p.id, "name": p.name} for p in db.session.query(Playlist).all()]
        return {"users": users, "playlists": playlists}

    @app.route("/dev/friends/<user_id>")
    def dev_friends(user_id):
        from models import User
        user = db.session.get(User, user_id)
        if not user:
            return {"error": "User not found"}, 404
        friends = [{"id": f.id, "username": f.username} for f in user.friends]
        return {"friends": friends, "count": len(friends)}

    @app.route("/dev/listening/<user_id>")
    def dev_listening(user_id):
        from models import ListeningEvent, Song
        from sqlalchemy import desc
        events = (
            db.session.query(ListeningEvent)
            .filter(ListeningEvent.user_id == user_id)
            .order_by(desc(ListeningEvent.listened_at))
            .all()
        )
        history = []
        for e in events:
            song = db.session.get(Song, e.song_id)
            history.append({
                "song": song.to_dict() if song else None,
                "listened_at": e.listened_at.isoformat(),
            })
        return {"history": history, "count": len(history)}
    # --------------------------------------------------------------------------

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
