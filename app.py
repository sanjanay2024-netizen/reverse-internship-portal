import os
import sqlite3
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    g
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "local-development-key"
)

# Database configuration
os.makedirs("instance", exist_ok=True)
DATABASE = os.path.join("instance", "portal.db")


# ---------------- DATABASE ----------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    db = get_db()

    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
                CHECK(role IN ('student', 'company'))
        );

        CREATE TABLE IF NOT EXISTS student_profiles (
            user_id INTEGER PRIMARY KEY,
            skills TEXT DEFAULT '',
            cgpa REAL,
            projects TEXT DEFAULT '',
            resume_link TEXT DEFAULT '',
            FOREIGN KEY(user_id)
                REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS internships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            skills TEXT NOT NULL,
            location TEXT DEFAULT 'Remote',
            FOREIGN KEY(company_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            internship_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending'
                CHECK(status IN ('Pending', 'Accepted', 'Rejected')),
            UNIQUE(internship_id, student_id),
            FOREIGN KEY(internship_id) REFERENCES internships(id),
            FOREIGN KEY(student_id) REFERENCES users(id)
        );
    """)

    db.commit()


@app.before_request
def setup_database():
    init_db()


# ---------------- ACCESS CONTROL ----------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.")
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") != role:
                flash("You don't have permission to access that page.")
                return redirect(url_for("dashboard"))

            return view(*args, **kwargs)

        return wrapped

    return decorator


# ---------------- HOME ----------------

@app.route("/")
def home():
    return render_template("home.html")


# ---------------- REGISTER ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")

        if not name or not email or len(password) < 8:
            flash(
                "Enter your name, email and a password "
                "of at least 8 characters."
            )
            return render_template("register.html")

        if role not in ("student", "company"):
            flash("Choose Student or Company.")
            return render_template("register.html")

        db = get_db()

        try:
            cur = db.execute(
                """
                INSERT INTO users(name, email, password, role)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, generate_password_hash(password), role)
            )

            user_id = cur.lastrowid

            if role == "student":
                db.execute(
                    """
                    INSERT INTO student_profiles(user_id)
                    VALUES (?)
                    """,
                    (user_id,)
                )

            db.commit()
            flash("Account created. Please log in.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("That email is already registered.")

    return render_template("register.html")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html")


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user_id = session["user_id"]

    if session["role"] == "student":
        profile = db.execute(
            """
            SELECT * FROM student_profiles
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        invitations = db.execute("""
            SELECT invitations.*, internships.title,
                   users.name AS company_name
            FROM invitations
            JOIN internships
                ON internships.id = invitations.internship_id
            JOIN users
                ON users.id = internships.company_id
            WHERE invitations.student_id = ?
            ORDER BY invitations.id DESC
        """, (user_id,)).fetchall()

        return render_template(
            "dashboard.html",
            profile=profile,
            invitations=invitations
        )

    internships = db.execute(
        """
        SELECT * FROM internships
        WHERE company_id = ?
        ORDER BY id DESC
        """,
        (user_id,)
    ).fetchall()

    return render_template(
        "dashboard.html",
        internships=internships
    )


# ---------------- STUDENT PROFILE ----------------

@app.route("/profile", methods=["GET", "POST"])
@role_required("student")
def profile():
    db = get_db()
    user_id = session["user_id"]

    if request.method == "POST":
        skills = request.form.get("skills", "").strip()
        projects = request.form.get("projects", "").strip()
        resume_link = request.form.get("resume_link", "").strip()
        cgpa_text = request.form.get("cgpa", "").strip()

        try:
            cgpa = float(cgpa_text) if cgpa_text else None

            if cgpa is not None and not 0 <= cgpa <= 10:
                raise ValueError

        except ValueError:
            flash("CGPA must be between 0 and 10.")
            return redirect(url_for("profile"))

        db.execute("""
            UPDATE student_profiles
            SET skills = ?, projects = ?, resume_link = ?, cgpa = ?
            WHERE user_id = ?
        """, (skills, projects, resume_link, cgpa, user_id))

        db.commit()
        flash("Profile saved.")

    student = db.execute("""
        SELECT users.name, users.email, student_profiles.*
        FROM users
        JOIN student_profiles
            ON users.id = student_profiles.user_id
        WHERE users.id = ?
    """, (user_id,)).fetchone()

    return render_template("profile.html", student=student)


# ---------------- COMPANY: POST INTERNSHIP ----------------

@app.route("/internship/new", methods=["GET", "POST"])
@role_required("company")
def internship_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        skills = request.form.get("skills", "").strip()
        location = request.form.get("location", "").strip() or "Remote"

        if not title or not description or not skills:
            flash("Fill in the title, description and required skills.")

        else:
            db = get_db()

            db.execute("""
                INSERT INTO internships(
                    company_id, title, description, skills, location
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                session["user_id"],
                title,
                description,
                skills,
                location
            ))

            db.commit()
            flash("Internship posted.")
            return redirect(url_for("dashboard"))

    return render_template("internship_new.html")


# ---------------- EXPLORE INTERNSHIPS ----------------

@app.route("/internships", endpoint="explore_internships")
@login_required
def explore_internships():
    db = get_db()

    internships = db.execute("""
        SELECT internships.*, users.name AS company_name
        FROM internships
        JOIN users ON users.id = internships.company_id
        ORDER BY internships.id DESC
    """).fetchall()

    return render_template(
        "internships.html",
        internships=internships
    )


# ---------------- COMPANY: FIND STUDENTS ----------------

@app.route("/students")
@role_required("company")
def students():
    search = request.args.get("skill", "").strip()
    db = get_db()

    query = """
        SELECT users.id, users.name, student_profiles.skills,
               student_profiles.cgpa, student_profiles.projects,
               student_profiles.resume_link
        FROM users
        JOIN student_profiles
            ON users.id = student_profiles.user_id
        WHERE users.role = 'student'
    """

    params = []

    if search:
        query += " AND student_profiles.skills LIKE ?"
        params.append("%" + search + "%")

    results = db.execute(
        query + " ORDER BY users.name",
        params
    ).fetchall()

    internships = db.execute(
        """
        SELECT id, title FROM internships
        WHERE company_id = ?
        """,
        (session["user_id"],)
    ).fetchall()

    return render_template(
        "students.html",
        students=results,
        internships=internships
    )


# ---------------- COMPANY: SEND INVITATION ----------------

@app.route("/invite/<int:student_id>", methods=["POST"])
@role_required("company")
def invite(student_id):
    internship_id = request.form.get("internship_id", type=int)
    db = get_db()

    internship = db.execute("""
        SELECT id FROM internships
        WHERE id = ? AND company_id = ?
    """, (internship_id, session["user_id"])).fetchone()

    student = db.execute("""
        SELECT id FROM users
        WHERE id = ? AND role = 'student'
    """, (student_id,)).fetchone()

    if not internship or not student:
        flash("Invalid student or internship.")

    else:
        try:
            db.execute("""
                INSERT INTO invitations(internship_id, student_id)
                VALUES (?, ?)
            """, (internship_id, student_id))

            db.commit()
            flash("Invitation sent.")

        except sqlite3.IntegrityError:
            flash("You have already invited this student.")

    return redirect(url_for("students"))


# ---------------- STUDENT: MY INVITATIONS ----------------

@app.route("/invitations")
@role_required("student")
def invitations():
    rows = get_db().execute("""
        SELECT invitations.id, invitations.status,
               internships.title, internships.description,
               internships.location,
               users.name AS company_name
        FROM invitations
        JOIN internships
            ON internships.id = invitations.internship_id
        JOIN users
            ON users.id = internships.company_id
        WHERE invitations.student_id = ?
        ORDER BY invitations.id DESC
    """, (session["user_id"],)).fetchall()

    return render_template(
        "invitations.html",
        invitations=rows
    )


# ---------------- ACCEPT OR REJECT INVITATION ----------------

@app.route(
    "/invitation/<int:invitation_id>/<action>",
    methods=["POST"]
)
@role_required("student")
def invitation_action(invitation_id, action):
    if action not in ("Accepted", "Rejected"):
        flash("Invalid action.")
        return redirect(url_for("invitations"))

    db = get_db()

    cur = db.execute("""
        UPDATE invitations
        SET status = ?
        WHERE id = ?
          AND student_id = ?
          AND status = 'Pending'
    """, (action, invitation_id, session["user_id"]))

    db.commit()

    if cur.rowcount:
        flash("Invitation " + action.lower() + ".")
    else:
        flash("Invitation could not be updated.")

    return redirect(url_for("invitations"))


# ---------------- START APPLICATION ----------------

if __name__ == "__main__":
    app.run(debug=True)