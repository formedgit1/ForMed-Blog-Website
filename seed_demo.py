"""Populate the database with demo accounts and content so the portals have
something to show before the article/library features exist.

    python3 seed_demo.py

Safe to re-run: it skips anything already seeded. Demo accounts all use the
password below. Delete users.db (and the uploads/ folder) to start clean.
"""

import os
import random
from datetime import datetime, timedelta, timezone

import auth_db
import portal_db
from auth_db import get_connection

DEMO_PASSWORD = "password123"
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

DEMO_USERS = [
    ("student", "Maya", "Chen", "maya.student@demo.formed", "804-555-0100", None),
    ("student", "Devon", "Brooks", "devon.student@demo.formed", "804-555-0101", None),
    ("student", "Priya", "Nair", "priya.student@demo.formed", "804-555-0102", None),
    ("author", "Alex", "Rivera", "alex.author@demo.formed", "804-555-0110", "1111"),
    ("author", "Sam", "Okafor", "sam.author@demo.formed", "804-555-0111", "1111"),
    ("admin", "Jordan", "Lee", "jordan.admin@demo.formed", "804-555-0120", "2222"),
]

# (title, description, author email, career name, status)
ALEX = "alex.author@demo.formed"
SAM = "sam.author@demo.formed"

DEMO_ARTICLES = [
    # Therapeutic Services
    ("Demo: A Day in the Life of an ICU Nurse",
     "A first-hand walk through a 12-hour critical-care shift, from handoff to charting.",
     ALEX, "Registered Nurse", "published"),
    ("Demo: So You Want to Be a Physical Therapist",
     "Schooling, licensure, and the settings PTs actually work in.",
     SAM, "Physical Therapist", "published"),
    ("Demo: Inside the Hospital Pharmacy",
     "How a pharmacist checks, compounds, and clears every order that reaches a patient.",
     ALEX, "Pharmacist", "published"),
    ("Demo: Respiratory Therapy During a Code",
     "The RT's role when a patient stops breathing, minute by minute.",
     SAM, "Respiratory Therapist", "published"),
    ("Demo: What Athletic Trainers Do Before the Whistle",
     "Injury prevention, taping, and sideline decision-making in school sports.",
     ALEX, "Athletic Trainer", "published"),

    # Diagnostic Services
    ("Demo: How MRI Machines See Inside You",
     "The physics of magnetic resonance imaging, explained without the math.",
     ALEX, "MRI Technologist", "published"),
    ("Demo: Reading the Room: Diagnostic Sonography",
     "What a sonographer is looking for while the probe is moving.",
     SAM, "Diagnostic Medical Sonographer", "published"),
    ("Demo: The Phlebotomy Handbook",
     "Order of draw, difficult sticks, and keeping patients calm.",
     ALEX, "Phlebotomist", "published"),
    ("Demo: A Shift in the Clinical Lab",
     "From specimen login to a verified result on the chart.",
     SAM, "Clinical Laboratory Scientist", "published"),

    # Health Informatics
    ("Demo: Getting Started in Medical Coding",
     "Certifications, code sets, and what the daily work really looks like.",
     SAM, "Medical Coder", "published"),
    ("Demo: The Nurse Informaticist Bridge",
     "Translating between bedside nurses and the people who build the EHR.",
     ALEX, "Nurse Informaticist", "published"),
    ("Demo: Cleaning Data Nobody Wants to Clean",
     "A clinical data analyst on messy inputs and trustworthy dashboards.",
     SAM, "Clinical Data Analyst", "published"),

    # Support Services
    ("Demo: The Sterile Processing Pipeline",
     "How instruments are cleaned, packed, and tracked between surgeries.",
     SAM, "Central Sterile Processing Technician", "published"),
    ("Demo: Who Fixes the Ventilators?",
     "Biomedical equipment technicians and the gear that can't fail.",
     ALEX, "Biomedical Equipment Technician", "published"),
    ("Demo: Logistics of a Hospital Supply Room",
     "Par levels, expiry sweeps, and never running out of the one thing you need.",
     SAM, "Materials Management Coordinator", "published"),

    # Biotechnology Research & Development
    ("Demo: Running a Clinical Trial Site",
     "Consent, visit windows, and the binder that keeps a study auditable.",
     ALEX, "Clinical Research Coordinator", "published"),
    ("Demo: A Week at the Bench in Microbiology",
     "Plating, identifying, and reporting organisms that change treatment.",
     SAM, "Microbiologist", "published"),

    # Public & Community Health
    ("Demo: Health Education That People Actually Use",
     "Designing a diabetes workshop for a real neighbourhood.",
     ALEX, "Public Health Educator", "published"),
    ("Demo: Tracing an Outbreak",
     "How epidemiologists turn scattered case reports into a picture.",
     SAM, "Epidemiologist", "published"),

    # Pending -> land in the admin queue
    ("Demo: Careers in Genetic Counseling",
     "Training path, day-to-day sessions, and what patients are counselled on.",
     ALEX, "Genetic Counselor", "pending"),
    ("Demo: Community Health Workers on the Front Line",
     "Bridging clinics and the neighbourhoods they serve.",
     SAM, "Community Health Worker", "pending"),
]


def _now():
    return datetime.now(timezone.utc).isoformat()


def seed_users():
    made = 0
    for role, first, last, email, phone, code in DEMO_USERS:
        if auth_db.get_user_by_email(email):
            continue
        result = auth_db.create_user(
            role=role, first_name=first, last_name=last, email=email,
            phone=phone, password=DEMO_PASSWORD, security_code=code,
        )
        if not result["ok"]:
            print(f"  ! {email}: {result['error']}")
        else:
            made += 1
    print(f"users: {made} created, {len(DEMO_USERS) - made} already present")


def _career_id(conn, name):
    row = conn.execute("SELECT id FROM careers WHERE name = ?", (name,)).fetchone()
    return row["id"] if row else None


def seed_articles():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    made = 0
    with get_connection() as conn:
        for title, desc, author_email, career_name, status in DEMO_ARTICLES:
            if conn.execute("SELECT 1 FROM articles WHERE title = ?", (title,)).fetchone():
                continue
            author = auth_db.get_user_by_email(author_email)
            career_id = _career_id(conn, career_name)
            if not author or not career_id:
                print(f"  ! skipped {title!r} (missing author or career)")
                continue

            slug = title.split(":", 1)[1].strip().lower().replace(" ", "-")
            slug = "".join(ch for ch in slug if ch.isalnum() or ch == "-")
            original = f"{slug}.txt"
            stored = f"demo_{made}_{original}"
            with open(os.path.join(UPLOAD_DIR, stored), "w") as fh:
                fh.write(f"{title}\n\n{desc}\n\n(placeholder demo file)\n")

            decided_at = _now() if status != "pending" else None
            conn.execute(
                """
                INSERT INTO articles
                    (title, description, author_id, career_id, file_name,
                     original_file_name, status, created_at, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title, desc, author["id"], career_id, stored,
                 original, status, _now(), decided_at),
            )
            made += 1
    print(f"articles: {made} created, {len(DEMO_ARTICLES) - made} already present")


def seed_student_activity():
    with get_connection() as conn:
        students = conn.execute(
            "SELECT id FROM users WHERE role = 'student'"
        ).fetchall()
        published = conn.execute(
            "SELECT id FROM articles WHERE status = 'published'"
        ).fetchall()
        if not students or not published:
            print("activity: nothing to seed")
            return

        pub_ids = [r["id"] for r in published]
        saves = reads = 0
        rng = random.Random(42)

        for s in students:
            already_saved = conn.execute(
                "SELECT COUNT(*) AS n FROM saved_articles WHERE student_id = ?",
                (s["id"],),
            ).fetchone()["n"]
            if not already_saved:
                for aid in rng.sample(pub_ids, k=min(3, len(pub_ids))):
                    conn.execute(
                        "INSERT OR IGNORE INTO saved_articles "
                        "(student_id, article_id, saved_at) VALUES (?, ?, ?)",
                        (s["id"], aid, _now()),
                    )
                    saves += 1

            already_read = conn.execute(
                "SELECT COUNT(*) AS n FROM reading_events WHERE student_id = ?",
                (s["id"],),
            ).fetchone()["n"]
            if not already_read:
                for day_offset in range(14):
                    for _ in range(rng.randint(0, 3)):
                        when = datetime.now(timezone.utc) - timedelta(
                            days=day_offset, hours=rng.randint(0, 12)
                        )
                        conn.execute(
                            "INSERT INTO reading_events "
                            "(student_id, article_id, read_at) VALUES (?, ?, ?)",
                            (s["id"], rng.choice(pub_ids), when.isoformat()),
                        )
                        reads += 1
        print(f"activity: {saves} saves, {reads} reading events added")


if __name__ == "__main__":
    auth_db.init_db()
    portal_db.init_db()
    seed_users()
    seed_articles()
    seed_student_activity()
    print(f"\nDemo accounts -- password for all: {DEMO_PASSWORD}")
    for role, first, last, email, _phone, code in DEMO_USERS:
        extra = f"  (security code {code})" if code else ""
        print(f"  {role:8}  {email}{extra}")
