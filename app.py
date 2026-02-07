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

        match = Match(
            player1_name=player1_name,
            player2_name=player2_name,
            winner=winner,
            score_p1=int(data.get("score_p1") or 0),
            score_p2=int(data.get("score_p2") or 0),
            stage=data.get("stage"),
            character_p1=data.get("character_p1"),
            character_p2=data.get("character_p2"),
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

    # --- HTML simple: ver data y formulario ---
    @app.route("/")
    def home():
        return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Maxxa Velada - Stats</title>
<style>body{font-family:sans-serif;max-width:600px;margin:2rem auto;padding:0 1rem;} a{color:#2563eb;}
h1{color:#333;} ul{line-height:2;}</style></head><body>
<h1>Maxxa Velada – Stats</h1>
<ul>
<li><a href="/matches">Ver partidas</a></li>
<li><a href="/leaderboard">Leaderboard</a></li>
<li><a href="/matches/new">Crear partida</a></li>
</ul>
<p>API: <a href="/api/matches">GET /api/matches</a> · <a href="/api/leaderboard">GET /api/leaderboard</a></p>
</body></html>"""

    @app.route("/matches")
    def page_matches():
        page = max(1, int(request.args.get("page", 1)))
        per_page = 20
        pagination = Match.query.order_by(Match.created_at.desc()).paginate(page=page, per_page=per_page)
        rows = ""
        for m in pagination.items:
            winner_name = m.player1_name if m.winner == "p1" else m.player2_name
            rows += f"<tr><td>{m.id}</td><td>{m.player1_name}</td><td>{m.player2_name}</td><td>{winner_name}</td><td>{m.score_p1}-{m.score_p2}</td><td>{m.stage or '-'}</td><td>{m.created_at.strftime('%Y-%m-%d %H:%M') if m.created_at else '-'}</td></tr>"
        prev_link = f'<a href="/matches?page={pagination.page - 1}">Anterior</a>' if pagination.has_prev else "Anterior"
        next_link = f'<a href="/matches?page={pagination.page + 1}">Siguiente</a>' if pagination.has_next else "Siguiente"
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Partidas</title>
<style>body{{font-family:sans-serif;margin:2rem auto;max-width:900px;padding:0 1rem;}}
table{{border-collapse:collapse;width:100%;}} th,td{{border:1px solid #ccc;padding:8px;text-align:left;}}
th{{background:#f0f0f0;}} a{{color:#2563eb;}} .nav{{margin-top:1rem;}}</style></head><body>
<h1>Partidas</h1>
<table><thead><tr><th>Id</th><th>P1</th><th>P2</th><th>Ganador</th><th>Score</th><th>Stage</th><th>Fecha</th></tr></thead><tbody>
{rows}
</tbody></table>
<p class="nav">{prev_link} — Página {pagination.page} de {pagination.pages or 1} — {next_link}</p>
<p><a href="/">Inicio</a> · <a href="/matches/new">Crear partida</a></p>
</body></html>"""

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
        rows = db.session.execute(db.text(sql), {"limit": limit}).fetchall()
        trs = "".join(
            f"<tr><td>{i+1}</td><td>{r.name}</td><td>{r.wins}</td><td>{r.losses}</td><td>{r.total_games}</td><td>{r.win_rate_pct or 0}%</td></tr>"
            for i, r in enumerate(rows)
        )
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Leaderboard</title>
<style>body{{font-family:sans-serif;margin:2rem auto;max-width:600px;padding:0 1rem;}}
table{{border-collapse:collapse;width:100%;}} th,td{{border:1px solid #ccc;padding:8px;}} th{{background:#f0f0f0;}} a{{color:#2563eb;}}</style></head><body>
<h1>Leaderboard</h1>
<table><thead><tr><th>#</th><th>Jugador</th><th>Wins</th><th>Losses</th><th>Partidas</th><th>Win rate</th></tr></thead><tbody>{trs}</tbody></table>
<p><a href="/">Inicio</a></p>
</body></html>"""

    @app.route("/matches/new", methods=["GET", "POST"])
    def page_new_match():
        if request.method == "POST":
            player1_name = (request.form.get("player1_name") or "").strip()
            player2_name = (request.form.get("player2_name") or "").strip()
            winner = request.form.get("winner")
            if not player1_name or not player2_name:
                return """<!DOCTYPE html><html><body><p>Faltan nombres. <a href="/matches/new">Volver</a></p></body></html>""", 400
            if winner not in ("p1", "p2"):
                winner = "p1"
            match = Match(
                player1_name=player1_name,
                player2_name=player2_name,
                winner=winner,
                score_p1=int(request.form.get("score_p1") or 0),
                score_p2=int(request.form.get("score_p2") or 0),
                stage=request.form.get("stage") or None,
                character_p1=request.form.get("character_p1") or None,
                character_p2=request.form.get("character_p2") or None,
                mode=request.form.get("mode") or None,
            )
            db.session.add(match)
            db.session.commit()
            return redirect(url_for("page_matches"))
        return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Crear partida</title>
<style>body{font-family:sans-serif;max-width:400px;margin:2rem auto;padding:0 1rem;}
label{display:block;margin-top:0.8rem;} input,select{width:100%;padding:6px;box-sizing:border-box;}
button{margin-top:1rem;padding:8px 16px;} a{color:#2563eb;}</style></head><body>
<h1>Crear partida</h1>
<form method="post" action="/matches/new">
<label>Jugador 1 <input name="player1_name" required></label>
<label>Jugador 2 <input name="player2_name" required></label>
<label>Ganador <select name="winner"><option value="p1">Jugador 1</option><option value="p2">Jugador 2</option></select></label>
<label>Score P1 <input type="number" name="score_p1" value="0" min="0"></label>
<label>Score P2 <input type="number" name="score_p2" value="0" min="0"></label>
<label>Stage <input name="stage" placeholder="opcional"></label>
<label>Personaje P1 <input name="character_p1" placeholder="opcional"></label>
<label>Personaje P2 <input name="character_p2" placeholder="opcional"></label>
<label>Modo <select name="mode"><option value="">—</option><option value="local">local</option><option value="online">online</option></select></label>
<button type="submit">Guardar partida</button>
</form>
<p><a href="/">Inicio</a> · <a href="/matches">Ver partidas</a></p>
</body></html>"""

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
