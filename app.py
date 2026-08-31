import os

from flask import Flask, jsonify, request, send_from_directory, session

import auth_db

app = Flask(__name__)
# Used to sign the session cookie. Set a real value via env var in production.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

auth_db.init_db()


# --- Static pages -----------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.root_path, "index.html")


@app.route("/script.js")
def script_js():
    return send_from_directory(app.root_path, "script.js")


@app.route("/style.css")
def style_css():
    return send_from_directory(app.root_path, "style.css")


# --- Auth API -------------------------------------------------------------

@app.post("/api/signup")
def api_signup():
    data = request.get_json(silent=True) or {}
    result = auth_db.create_user(
        role=data.get("role"),
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        email=data.get("email"),
        phone=data.get("phone"),
        password=data.get("password"),
        security_code=data.get("security_code"),
    )
    return jsonify(result), (200 if result["ok"] else 400)


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    result = auth_db.authenticate(
        role=data.get("role"),
        email=data.get("email"),
        password=data.get("password"),
        security_code=data.get("security_code"),
    )
    if not result["ok"]:
        return jsonify(result), 401

    session.clear()
    session["user_id"] = result["user"]["id"]
    session["role"] = result["user"]["role"]
    return jsonify(result)


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False}), 401

    user = auth_db.get_user_by_id(user_id)
    if not user:
        session.clear()
        return jsonify({"ok": False}), 401

    return jsonify({"ok": True, "user": user})


if __name__ == "__main__":
    app.run(host="0.0.0.0")
