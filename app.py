"""
Flask app para estadísticas de peleas (Maxxa Velada).
Copia este archivo en tu proyecto Flask o importa las rutas y el modelo.

Dependencias: flask, flask-sqlalchemy (y flask-cors si llamas desde otro origen).

  pip install flask flask-sqlalchemy flask-cors

Uso en tu proyecto:
  from fight_stats_app import create_app, db, Match
  app = create_app()
  # o registrar blueprints: app.register_blueprint(api_bp, url_prefix='/api')
"""

import os
from datetime import datetime
from flask import Flask, request, jsonify, redirect, url_for, render_template
from flask_sqlalchemy import SQLAlchemy

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'maxxa_velada.db')}")
if DATABASE_URI.startswith("postgres://"):
    DATABASE_URI = DATABASE_URI.replace("postgres://", "postgresql://", 1)

db = SQLAlchemy()


# --- Model ---
class Match(db.Model):
    __tablename__ = "match"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    player1_name = db.Column(db.String(120), nullable=False)
    player2_name = db.Column(db.String(120), nullable=False)
    winner = db.Column(db.String(2), nullable=False)  # 'p1' | 'p2'
    score_p1 = db.Column(db.Integer, default=0)
    score_p2 = db.Column(db.Integer, default=0)

    stage = db.Column(db.String(80), nullable=True)
    character_p1 = db.Column(db.String(80), nullable=True)
    character_p2 = db.Column(db.String(80), nullable=True)
    mode = db.Column(db.String(20), nullable=True)  # 'local' | 'online'

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "player1_name": self.player1_name,
            "player2_name": self.player2_name,
            "winner": self.winner,
            "score_p1": self.score_p1,
            "score_p2": self.score_p2,
            "stage": self.stage,
            "character_p1": self.character_p1,
            "character_p2": self.character_p2,
            "mode": self.mode,
        }


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    if config_overrides:
        app.config.update(config_overrides)

    db.init_app(app)

    try:
        from flask_cors import CORS
        CORS(app)
    except ImportError:
        pass

    # --- Routes ---

    @app.route("/api/matches", methods=["POST"])
    def post_match():
        data = request.get_json() or {}
        player1_name = (data.get("player1_name") or "").strip()
        player2_name = (data.get("player2_name") or "").strip()
        winner = data.get("winner")
        if not player1_name or not player2_name:
            return jsonify({"error": "player1_name and player2_name required"}), 400
        if winner not in ("p1", "p2"):
            return jsonify({"error": "winner must be 'p1' or 'p2'"}), 400

        def _upper(s):
            return (s or "").strip().upper() or None

        match = Match(
            player1_name=player1_name.upper(),
            player2_name=player2_name.upper(),
            winner=winner,
            score_p1=int(data.get("score_p1") or 0),
            score_p2=int(data.get("score_p2") or 0),
            stage=data.get("stage"),
            character_p1=_upper(data.get("character_p1")),
            character_p2=_upper(data.get("character_p2")),
            mode=data.get("mode"),
        )
        db.session.add(match)
        db.session.commit()
        return jsonify(match.to_dict()), 201

    @app.route("/api/leaderboard", methods=["GET"])
    def get_leaderboard():
        limit = min(int(request.args.get("limit", 10)), 100)
        min_games = max(0, int(request.args.get("min_games", 1)))

        # Raw SQL para wins/losses por jugador (cada partida cuenta para ambos)
        sql = """
        WITH combined AS (
            SELECT player1_name AS name, CASE WHEN winner = 'p1' THEN 1 ELSE 0 END AS won FROM match
            UNION ALL
            SELECT player2_name AS name, CASE WHEN winner = 'p2' THEN 1 ELSE 0 END AS won FROM match
        ),
        agg AS (
            SELECT name,
                   SUM(won) AS wins,
                   COUNT(*) AS total_games,
                   COUNT(*) - SUM(won) AS losses
            FROM combined
            GROUP BY name
        )
        SELECT name, wins, losses, total_games,
               ROUND(100.0 * wins / NULLIF(total_games, 0), 2) AS win_rate_pct
        FROM agg
        WHERE total_games >= :min_games
        ORDER BY wins DESC, total_games DESC
        LIMIT :limit
        """
        rows = db.session.execute(
            db.text(sql), {"min_games": min_games, "limit": limit}
        ).fetchall()

        leaderboard = [
            {
                "rank": i + 1,
                "name": r.name,
                "wins": r.wins,
                "losses": r.losses,
                "total_games": r.total_games,
                "win_rate": round(r.wins / r.total_games, 2) if r.total_games else 0,
                "win_rate_pct": float(r.win_rate_pct or 0),
            }
            for i, r in enumerate(rows)
        ]
        return jsonify(leaderboard)

    @app.route("/api/players/<name>/stats", methods=["GET"])
    def get_player_stats(name):
        name = (name or "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400

        sql = """
        WITH combined AS (
            SELECT player1_name AS name, CASE WHEN winner = 'p1' THEN 1 ELSE 0 END AS won FROM match
            UNION ALL
            SELECT player2_name AS name, CASE WHEN winner = 'p2' THEN 1 ELSE 0 END AS won FROM match
        )
        SELECT SUM(won) AS wins, COUNT(*) AS total_games
        FROM combined
        WHERE name = :name
        """
        row = db.session.execute(db.text(sql), {"name": name}).fetchone()
        if not row or row.total_games == 0:
            return jsonify({"name": name, "wins": 0, "losses": 0, "total_games": 0, "win_rate": 0.0})

        wins = row.wins or 0
        total = row.total_games
        losses = total - wins
        return jsonify({
            "name": name,
            "wins": wins,
            "losses": losses,
            "total_games": total,
            "win_rate": round(wins / total, 2),
        })

    # --- HTML: templates en templates/ ---
    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/matches")
    def page_matches():
        page = max(1, int(request.args.get("page", 1)))
        per_page = 20
        pagination = Match.query.order_by(Match.created_at.desc()).paginate(page=page, per_page=per_page)
        matches = []
        for m in pagination.items:
            winner_name = m.player1_name if m.winner == "p1" else m.player2_name
            created = m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else "-"
            matches.append({
                "id": m.id,
                "player1_name": m.player1_name,
                "player2_name": m.player2_name,
                "winner_name": winner_name,
                "score_p1": m.score_p1,
                "score_p2": m.score_p2,
                "stage": m.stage,
                "created_at": created,
            })
        return render_template(
            "matches.html",
            matches=matches,
            page=pagination.page,
            pages=pagination.pages or 1,
            has_prev=pagination.has_prev,
            has_next=pagination.has_next,
        )

    @app.route("/leaderboard")
    def page_leaderboard():
        limit = min(int(request.args.get("limit", 20)), 100)
        sql = """
        WITH combined AS (
            SELECT player1_name AS name, CASE WHEN winner = 'p1' THEN 1 ELSE 0 END AS won FROM match
            UNION ALL
            SELECT player2_name AS name, CASE WHEN winner = 'p2' THEN 1 ELSE 0 END AS won FROM match
        ),
        agg AS (
            SELECT name, SUM(won) AS wins, COUNT(*) AS total_games, COUNT(*) - SUM(won) AS losses
            FROM combined GROUP BY name
        )
        SELECT name, wins, losses, total_games, ROUND(100.0 * wins / NULLIF(total_games, 0), 1) AS win_rate_pct
        FROM agg ORDER BY wins DESC, total_games DESC LIMIT :limit
        """
        raw = db.session.execute(db.text(sql), {"limit": limit}).fetchall()
        rows = [
            {
                "rank": i + 1,
                "name": r.name,
                "wins": r.wins,
                "losses": r.losses,
                "total_games": r.total_games,
                "win_rate_pct": r.win_rate_pct or 0,
            }
            for i, r in enumerate(raw)
        ]
        return render_template("leaderboard.html", rows=rows)

    @app.route("/matches/new", methods=["GET", "POST"])
    def page_new_match():
        if request.method == "POST":
            player1_name = (request.form.get("player1_name") or "").strip()
            player2_name = (request.form.get("player2_name") or "").strip()
            winner = request.form.get("winner")
            if not player1_name or not player2_name:
                return render_template("error.html", message="Faltan nombres.", back_url="/matches/new"), 400
            if winner not in ("p1", "p2"):
                winner = "p1"

            def _upper(s):
                return (s or "").strip().upper() or None

            match = Match(
                player1_name=player1_name.upper(),
                player2_name=player2_name.upper(),
                winner=winner,
                score_p1=int(request.form.get("score_p1") or 0),
                score_p2=int(request.form.get("score_p2") or 0),
                stage=request.form.get("stage") or None,
                character_p1=_upper(request.form.get("character_p1")),
                character_p2=_upper(request.form.get("character_p2")),
                mode=request.form.get("mode") or None,
            )
            db.session.add(match)
            db.session.commit()
            return redirect(url_for("page_matches"))
        return render_template("match_form.html")

    @app.route("/api/matches", methods=["GET"])
    def list_matches():
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(50, max(1, int(request.args.get("per_page", 20))))
        pagination = Match.query.order_by(Match.created_at.desc()).paginate(page=page, per_page=per_page)
        return jsonify({
            "matches": [m.to_dict() for m in pagination.items],
            "total": pagination.total,
            "page": page,
            "per_page": per_page,
        })

    @app.route("/api/stats/summary", methods=["GET"])
    def stats_summary():
        total = db.session.query(db.func.count(Match.id)).scalar() or 0
        return jsonify({
            "total_matches": total,
        })

    with app.app_context():
        db.create_all()

    return app


# Instancia para Gunicorn / Render (app:app)
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
