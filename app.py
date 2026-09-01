import os
import uuid
from functools import wraps

from flask import (
    Flask, g, jsonify, request, send_from_directory, session,
)
from werkzeug.utils import secure_filename

import auth_db
import portal_db

app = Flask(__name__)
# Signs the session cookie. Set a real value via env var in production.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB uploads

UPLOAD_DIR = os.path.join(app.root_path, "uploads")
ALLOWED_UPLOAD_EXT = {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"}

auth_db.init_db()
portal_db.init_db()


# --- Static pages -----------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.root_path, "index.html")


@app.route("/<any(script.js, portal.js, style.css):asset>")
def static_asset(asset):
    return send_from_directory(app.root_path, asset)


# --- Auth helpers -----------------------------------------------------

def require_role(*roles):
    """Guard a route: must be signed in, and (if roles given) hold one of them.

    On success the resolved user dict is available as ``g.user``.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = session.get("user_id")
            user = auth_db.get_user_by_id(user_id) if user_id else None
            if user is None:
                session.clear()
                return jsonify({"ok": False, "error": "Please sign in."}), 401
            if roles and user["role"] not in roles:
                return jsonify({"ok": False, "error": "Not authorized."}), 403
            g.user = user
            return view(*args, **kwargs)
        return wrapped
    return decorator


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
    user = auth_db.get_user_by_id(user_id) if user_id else None
    if user is None:
        session.clear()
        return jsonify({"ok": False}), 401
    return jsonify({"ok": True, "user": user})


# --- Shared -----------------------------------------------------------

@app.get("/api/careers")
@require_role()
def api_careers():
    return jsonify({"ok": True, "career_paths": portal_db.list_careers()})


# --- Library (any signed-in role) -----------------------------------

@app.get("/api/library/facets")
@require_role()
def api_library_facets():
    return jsonify({"ok": True, "career_paths": portal_db.library_facets()})


@app.get("/api/library/articles")
@require_role()
def api_library_articles():
    query = (request.args.get("q") or "").strip()
    raw_paths = (request.args.get("paths") or "").strip()
    path_ids = [int(x) for x in raw_paths.split(",") if x.strip().isdigit()]
    student_id = g.user["id"] if g.user["role"] == "student" else None
    return jsonify({
        "ok": True,
        "articles": portal_db.list_library_articles(
            query=query or None,
            path_ids=path_ids or None,
            student_id=student_id,
        ),
    })


# --- Student portal ---------------------------------------------------

@app.get("/api/student/saved-articles")
@require_role("student")
def api_student_saved():
    return jsonify({"ok": True, "articles": portal_db.saved_articles(g.user["id"])})


@app.post("/api/student/saved-articles")
@require_role("student")
def api_student_save():
    data = request.get_json(silent=True) or {}
    result = portal_db.save_article(g.user["id"], data.get("article_id"))
    return jsonify(result), (200 if result["ok"] else 400)


@app.delete("/api/student/saved-articles/<int:article_id>")
@require_role("student")
def api_student_unsave(article_id):
    return jsonify(portal_db.unsave_article(g.user["id"], article_id))


@app.get("/api/student/reading-activity")
@require_role("student")
def api_student_reading():
    days = request.args.get("days", default=14, type=int)
    return jsonify({
        "ok": True,
        "activity": portal_db.reading_activity(g.user["id"], days=days),
    })


@app.post("/api/student/reading-events")
@require_role("student")
def api_student_log_read():
    data = request.get_json(silent=True) or {}
    result = portal_db.log_reading_event(g.user["id"], data.get("article_id"))
    return jsonify(result), (200 if result["ok"] else 400)


# --- Author portal ---------------------------------------------------

@app.get("/api/author/articles")
@require_role("author")
def api_author_articles():
    return jsonify({
        "ok": True,
        "articles": portal_db.articles_by_author(g.user["id"]),
    })


@app.post("/api/author/article-requests")
@require_role("author")
def api_author_request_upload():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"ok": False, "error": "Please attach a file."}), 400

    ext = os.path.splitext(upload.filename)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        return jsonify({
            "ok": False,
            "error": "Unsupported file type. Upload a PDF, Word, text, or Markdown file.",
        }), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{secure_filename(upload.filename) or ('file' + ext)}"

    result = portal_db.create_article_request(
        author_id=g.user["id"],
        title=request.form.get("title"),
        description=request.form.get("description"),
        career_id=request.form.get("career_id", type=int),
        file_name=stored_name,
        original_file_name=upload.filename,
    )
    if not result["ok"]:
        return jsonify(result), 400

    # Only touch the disk once the row is safely in.
    try:
        upload.save(os.path.join(UPLOAD_DIR, stored_name))
    except OSError:
        portal_db.delete_article(result["id"])
        return jsonify({"ok": False, "error": "Could not store the uploaded file."}), 500

    return jsonify(result)


# --- Admin portal ---------------------------------------------------

@app.get("/api/admin/students")
@require_role("admin")
def api_admin_students():
    return jsonify({"ok": True, "students": portal_db.list_students()})


@app.get("/api/admin/students/<int:student_id>")
@require_role("admin")
def api_admin_student_detail(student_id):
    info = portal_db.student_portal_info(student_id)
    if info is None:
        return jsonify({"ok": False, "error": "Student not found."}), 404
    return jsonify({"ok": True, **info})


@app.get("/api/admin/article-requests")
@require_role("admin")
def api_admin_requests():
    return jsonify({"ok": True, "requests": portal_db.pending_requests()})


@app.get("/api/admin/article-requests/<int:article_id>/file")
@require_role("admin")
def api_admin_request_file(article_id):
    info = portal_db.get_article_file(article_id)
    if info is None or not info["file_name"]:
        return jsonify({"ok": False, "error": "No file on this request."}), 404
    return send_from_directory(
        UPLOAD_DIR, info["file_name"],
        as_attachment=True,
        download_name=info["original_file_name"] or info["file_name"],
    )


@app.post("/api/admin/article-requests/<int:article_id>/approve")
@require_role("admin")
def api_admin_approve(article_id):
    result = portal_db.decide_request(article_id, "published", g.user["id"])
    return jsonify(result), (200 if result["ok"] else 400)


@app.post("/api/admin/article-requests/<int:article_id>/deny")
@require_role("admin")
def api_admin_deny(article_id):
    result = portal_db.decide_request(article_id, "denied", g.user["id"])
    return jsonify(result), (200 if result["ok"] else 400)


@app.errorhandler(413)
def too_large(_err):
    return jsonify({"ok": False, "error": "That file is too large (10 MB max)."}), 413


if __name__ == "__main__":
    # Port 5000 is taken by AirPlay Receiver on macOS, so default to 8000.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
