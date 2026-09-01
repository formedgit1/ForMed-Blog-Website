"""Schema + queries for the role portals (student / author / admin).

Everything lives in the same ``users.db`` SQLite file as the accounts table,
so a single connection helper (imported from :mod:`auth_db`) is reused. This
module owns:

* the article taxonomy -- 6 career paths, 50 careers -- seeded on first boot;
* ``articles`` (an upload request and a published library entry are the same
  row at different ``status`` values: pending -> published / denied);
* ``saved_articles`` and ``reading_events`` for the student portal.

The full library / reading experience is built later; this is the storage and
API groundwork it will sit on.
"""

from datetime import date, datetime, timedelta, timezone

from auth_db import get_connection

# --- Career taxonomy ----------------------------------------------------
# 6 career paths; 50 careers total (12 + 9 + 8 + 7 + 7 + 7).

CAREER_STRUCTURE = {
    "Therapeutic Services": [
        "Physician", "Physician Assistant", "Registered Nurse",
        "Nurse Practitioner", "Physical Therapist", "Occupational Therapist",
        "Respiratory Therapist", "Speech-Language Pathologist", "Pharmacist",
        "Dentist", "Dental Hygienist", "Athletic Trainer",
    ],
    "Diagnostic Services": [
        "Radiologic Technologist", "Diagnostic Medical Sonographer",
        "MRI Technologist", "Clinical Laboratory Scientist", "Phlebotomist",
        "Cardiovascular Technologist", "Nuclear Medicine Technologist",
        "Pathologists' Assistant", "Electroneurodiagnostic Technologist",
    ],
    "Health Informatics": [
        "Health Information Manager", "Medical Coder", "Clinical Data Analyst",
        "Health IT Specialist", "Nurse Informaticist",
        "Medical Records Technician", "Epidemiology Data Specialist",
        "Healthcare Systems Administrator",
    ],
    "Support Services": [
        "Central Sterile Processing Technician", "Biomedical Equipment Technician",
        "Environmental Services Technician", "Hospital Facilities Manager",
        "Dietary Aide", "Patient Transporter", "Materials Management Coordinator",
    ],
    "Biotechnology Research & Development": [
        "Biomedical Engineer", "Clinical Research Coordinator", "Microbiologist",
        "Pharmaceutical Scientist", "Genetic Counselor", "Biostatistician",
        "Regulatory Affairs Specialist",
    ],
    "Public & Community Health": [
        "Public Health Educator", "Community Health Worker", "Epidemiologist",
        "Environmental Health Specialist", "Health Policy Analyst",
        "Global Health Program Coordinator", "School Health Coordinator",
    ],
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS career_paths (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS careers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    career_path_id INTEGER NOT NULL REFERENCES career_paths(id),
    UNIQUE (name, career_path_id)
);

CREATE TABLE IF NOT EXISTS articles (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    title              TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    author_id          INTEGER NOT NULL REFERENCES users(id),
    career_id          INTEGER REFERENCES careers(id),
    file_name          TEXT,          -- stored (unique) name on disk
    original_file_name TEXT,          -- name the author uploaded
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'published', 'denied')),
    created_at         TEXT NOT NULL,
    decided_at         TEXT,
    decided_by         INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS saved_articles (
    student_id INTEGER NOT NULL REFERENCES users(id),
    article_id INTEGER NOT NULL REFERENCES articles(id),
    saved_at   TEXT NOT NULL,
    PRIMARY KEY (student_id, article_id)
);

CREATE TABLE IF NOT EXISTS reading_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id),
    article_id INTEGER REFERENCES articles(id),
    read_at    TEXT NOT NULL
);
"""

# Columns shared by every "article as seen by a portal" query.
_ARTICLE_VIEW = """
    SELECT a.id, a.title, a.description, a.status, a.created_at, a.decided_at,
           a.original_file_name,
           a.author_id,
           u.first_name || ' ' || u.last_name AS author_name,
           c.name AS career_name,
           p.name AS career_path_name
    FROM articles a
    JOIN users u        ON u.id = a.author_id
    LEFT JOIN careers c      ON c.id = a.career_id
    LEFT JOIN career_paths p ON p.id = c.career_path_id
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    """Create portal tables and seed the taxonomy. Safe to call on every boot."""
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        _seed_careers(conn)


def _seed_careers(conn):
    already = conn.execute("SELECT COUNT(*) AS n FROM career_paths").fetchone()["n"]
    if already:
        return
    for path_name, careers in CAREER_STRUCTURE.items():
        cur = conn.execute(
            "INSERT INTO career_paths (name) VALUES (?)", (path_name,)
        )
        conn.executemany(
            "INSERT INTO careers (name, career_path_id) VALUES (?, ?)",
            [(name, cur.lastrowid) for name in careers],
        )


# --- Careers -----------------------------------------------------------

def list_careers():
    """All careers grouped under their path -- feeds the author's upload form."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.name, p.id AS path_id, p.name AS path_name
            FROM careers c
            JOIN career_paths p ON p.id = c.career_path_id
            ORDER BY p.name, c.name
            """
        ).fetchall()

    grouped = {}
    for r in rows:
        key = (r["path_id"], r["path_name"])
        grouped.setdefault(key, []).append({"id": r["id"], "name": r["name"]})
    return [
        {"path_id": pid, "path_name": pname, "careers": careers}
        for (pid, pname), careers in grouped.items()
    ]


# --- Articles / upload requests --------------------------------------

def articles_by_author(author_id):
    with get_connection() as conn:
        rows = conn.execute(
            _ARTICLE_VIEW + " WHERE a.author_id = ? ORDER BY a.created_at DESC",
            (author_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_article_request(author_id, title, description, career_id,
                           file_name, original_file_name):
    """Record an author's upload request as a ``pending`` article row."""
    title = (title or "").strip()
    description = (description or "").strip()

    if not title:
        return {"ok": False, "error": "An article name is required."}
    if not description:
        return {"ok": False, "error": "A short description is required."}

    with get_connection() as conn:
        valid_career = conn.execute(
            "SELECT 1 FROM careers WHERE id = ?", (career_id,)
        ).fetchone()
        if not valid_career:
            return {"ok": False, "error": "Please choose a career for this article."}

        cur = conn.execute(
            """
            INSERT INTO articles
                (title, description, author_id, career_id,
                 file_name, original_file_name, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (title, description, author_id, career_id,
             file_name, original_file_name, _now()),
        )
    return {"ok": True, "id": cur.lastrowid}


def pending_requests():
    with get_connection() as conn:
        rows = conn.execute(
            _ARTICLE_VIEW + " WHERE a.status = 'pending' ORDER BY a.created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def decide_request(article_id, decision, admin_id):
    """``decision`` is 'published' (approve -> library) or 'denied'."""
    if decision not in ("published", "denied"):
        return {"ok": False, "error": "Unknown decision."}

    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "Request not found."}
        if row["status"] != "pending":
            return {"ok": False, "error": "This request has already been decided."}

        conn.execute(
            "UPDATE articles SET status = ?, decided_at = ?, decided_by = ? WHERE id = ?",
            (decision, _now(), admin_id, article_id),
        )
    return {"ok": True}


def get_article_file(article_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT file_name, original_file_name FROM articles WHERE id = ?",
            (article_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_article(article_id):
    """Used to roll back a request row when its file save fails."""
    with get_connection() as conn:
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))


# --- Students (admin views) -----------------------------------------

def list_students():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.first_name, u.last_name, u.email, u.phone, u.created_at,
                   (SELECT COUNT(*) FROM saved_articles s WHERE s.student_id = u.id)
                       AS saved_count,
                   (SELECT COUNT(*) FROM reading_events r WHERE r.student_id = u.id)
                       AS reads_count
            FROM users u
            WHERE u.role = 'student'
            ORDER BY u.last_name, u.first_name
            """
        ).fetchall()
    return [dict(r) for r in rows]


def student_portal_info(student_id):
    """Everything the admin sees when opening one student: profile + portal."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, first_name, last_name, email, phone, created_at
            FROM users WHERE id = ? AND role = 'student'
            """,
            (student_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "profile": dict(row),
        "saved_articles": saved_articles(student_id),
        "reading_activity": reading_activity(student_id),
    }


# --- Saved articles + reading activity (student portal) ------------

def saved_articles(student_id):
    with get_connection() as conn:
        rows = conn.execute(
            _ARTICLE_VIEW
            + """
            JOIN saved_articles s ON s.article_id = a.id
            WHERE s.student_id = ?
            ORDER BY s.saved_at DESC
            """,
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_article(student_id, article_id):
    with get_connection() as conn:
        published = conn.execute(
            "SELECT 1 FROM articles WHERE id = ? AND status = 'published'",
            (article_id,),
        ).fetchone()
        if not published:
            return {"ok": False, "error": "That article is not in the library."}
        conn.execute(
            "INSERT OR IGNORE INTO saved_articles (student_id, article_id, saved_at) "
            "VALUES (?, ?, ?)",
            (student_id, article_id, _now()),
        )
    return {"ok": True}


def unsave_article(student_id, article_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM saved_articles WHERE student_id = ? AND article_id = ?",
            (student_id, article_id),
        )
    return {"ok": True}


def log_reading_event(student_id, article_id):
    with get_connection() as conn:
        published = conn.execute(
            "SELECT 1 FROM articles WHERE id = ? AND status = 'published'",
            (article_id,),
        ).fetchone()
        if not published:
            return {"ok": False, "error": "That article is not in the library."}
        conn.execute(
            "INSERT INTO reading_events (student_id, article_id, read_at) "
            "VALUES (?, ?, ?)",
            (student_id, article_id, _now()),
        )
    return {"ok": True}


# --- Library (all published articles) ------------------------------

def library_facets():
    """Career paths plus their published-article counts, for the filter row."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.name,
                   COUNT(CASE WHEN a.status = 'published' THEN 1 END) AS count
            FROM career_paths p
            LEFT JOIN careers c ON c.career_path_id = p.id
            LEFT JOIN articles a ON a.career_id = c.id
            GROUP BY p.id, p.name
            ORDER BY p.name
            """
        ).fetchall()
    return [dict(r) for r in rows]


def list_library_articles(query=None, path_ids=None, student_id=None):
    """Published articles, newest first, optionally text-searched / path-filtered.

    When ``student_id`` is given, each row carries a ``saved`` 0/1 flag.
    """
    params = []

    if student_id is not None:
        saved_select = ", (sa.article_id IS NOT NULL) AS saved"
        saved_join = ("LEFT JOIN saved_articles sa "
                      "ON sa.article_id = a.id AND sa.student_id = ?")
        params.append(student_id)
    else:
        saved_select = ", 0 AS saved"
        saved_join = ""

    sql = f"""
        SELECT a.id, a.title, a.description, a.created_at, a.decided_at,
               (u.first_name || ' ' || u.last_name) AS author_name,
               c.name AS career_name,
               p.id   AS career_path_id,
               p.name AS career_path_name
               {saved_select}
        FROM articles a
        JOIN users u ON u.id = a.author_id
        LEFT JOIN careers c      ON c.id = a.career_id
        LEFT JOIN career_paths p ON p.id = c.career_path_id
        {saved_join}
        WHERE a.status = 'published'
    """

    if query:
        like = f"%{query}%"
        sql += """
            AND (a.title LIKE ? OR a.description LIKE ?
                 OR (u.first_name || ' ' || u.last_name) LIKE ?
                 OR c.name LIKE ? OR p.name LIKE ?)
        """
        params += [like, like, like, like, like]

    if path_ids:
        sql += f" AND p.id IN ({','.join('?' for _ in path_ids)})"
        params += list(path_ids)

    sql += " ORDER BY COALESCE(a.decided_at, a.created_at) DESC, a.id DESC"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def reading_activity(student_id, days=14):
    """Articles-read count per calendar day for the last ``days`` days.

    Always returns one entry per day (zero-filled) so the line graph has a
    continuous x-axis.
    """
    days = max(1, min(days, 90))
    start = date.today() - timedelta(days=days - 1)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT substr(read_at, 1, 10) AS day, COUNT(*) AS count
            FROM reading_events
            WHERE student_id = ? AND substr(read_at, 1, 10) >= ?
            GROUP BY day
            """,
            (student_id, start.isoformat()),
        ).fetchall()

    by_day = {r["day"]: r["count"] for r in rows}
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "count": by_day.get((start + timedelta(days=i)).isoformat(), 0),
        }
        for i in range(days)
    ]
