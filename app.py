import webbrowser
import threading
from werkzeug.security import check_password_hash, generate_password_hash
from attendance_notifications import notify_today_absentees
import inspect
from apscheduler.schedulers.background import BackgroundScheduler
print(
    "notify_today_absentees loaded from:",
    inspect.getsourcefile(notify_today_absentees)
)

print(
    inspect.signature(notify_today_absentees)
)
from attendance_notifications import (
    notify_completed_timetable_absentees
)

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash,
    send_file
)

from io import BytesIO
import re
from flask import send_file, abort
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

import sqlite3
import os
import base64
import cv2
import numpy as np
import os
from flask_mail import Mail, Message
from datetime import datetime, date, timedelta
from functools import wraps
from io import BytesIO
from enrollstudents import enroll_bp

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer
)
from attendance_notifications import (
    notify_completed_timetable_absentees
)
import attendance_notifications

print(
    "ATTENDANCE NOTIFICATIONS FILE:",
    attendance_notifications.__file__
)

print(
    "notify_today_absentees:",
    attendance_notifications.notify_today_absentees
)
# ============================================================
# FLASK CONFIGURATION
# ============================================================

app = Flask(__name__)
app.register_blueprint(enroll_bp)
app.config.update(
    MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.getenv("MAIL_USERNAME"),
)

mail = Mail(app)

# ============================================================
# TEMPLATE TIME FORMATTER
# ============================================================

def format_time_12h(value):
    if not value:
        return ""

    value = str(value).strip()

    for fmt in (
        "%H:%M:%S",
        "%H:%M",
        "%I:%M %p",
        "%I:%M:%S %p"
    ):
        try:
            return datetime.strptime(
                value,
                fmt
            ).strftime("%I:%M %p").lstrip("0")

        except ValueError:
            continue

    return value


app.jinja_env.filters["time12"] = format_time_12h


app.secret_key = "intelligent_attendance_system_secret_key"

DATABASE_PATH = r"D:\student_attendance\attendance.db"

ACADEMIC_START_DATE = "2026-07-01"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_table_columns(table_name):
    conn = get_db_connection()

    try:
        rows = conn.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()

        return {row["name"] for row in rows}

    finally:
        conn.close()


# ============================================================
# DAY ALIASES
# ============================================================

DAY_ALIASES = {
    "Mon": ["mon", "monday"],
    "Tue": ["tue", "tuesday"],
    "Wed": ["wed", "wednesday"],
    "Thu": ["thu", "thursday"],
    "Fri": ["fri", "friday"],
    "Sat": ["sat", "saturday"],
    "Sun": ["sun", "sunday"]
}



def get_day_aliases(selected_date):
    try:
        selected_day = datetime.strptime(
            str(selected_date).strip(),
            "%Y-%m-%d"
        ).strftime("%a")

        return DAY_ALIASES.get(selected_day, [])

    except (ValueError, TypeError):
        return []


# ============================================================
# AUTHENTICATION
# ============================================================

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


def role_required(required_role):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))

            if session.get("role") != required_role:
                return redirect(url_for("login"))

            return func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================
# LOGGED-IN FACULTY
# ============================================================


def get_logged_in_faculty():
    if session.get("role") != "faculty":
        return None

    conn = get_db_connection()

    try:
        faculty_columns = get_table_columns("faculty")

        if "username" not in faculty_columns:
            return None

        query = """
            SELECT *
            FROM faculty
            WHERE username = ?
        """

        # If the table supports active status, only allow active accounts.
        if "active" in faculty_columns:
            query += " AND active = 1"

        faculty = conn.execute(
            query,
            (session.get("username"),)
        ).fetchone()

        if faculty is None:
            # Prevent an old session from accessing faculty pages.
            session.clear()

        return faculty

    finally:
        conn.close()


# ============================================================
# LOGGED-IN STUDENT
# ============================================================

def get_logged_in_student():
    if session.get("role") != "student":
        return None

    conn = get_db_connection()

    try:
        return conn.execute(
            """
            SELECT *
            FROM students
            WHERE student_id = ?
            """,
            (session.get("username"),)
        ).fetchone()

    finally:
        conn.close()




# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template(
                "login.html",
                error="Please enter your username and password."
            )

        conn = get_db_connection()

        try:
            user = conn.execute(
                """
                SELECT *
                FROM users
                WHERE username = ?
                """,
                (username,)
            ).fetchone()
        finally:
            conn.close()

        if user is None:
            return render_template(
                "login.html",
                error="Invalid username or password."
            )

        stored_password = user["password_hash"]
        password_valid = False

        # Verify hashed passwords.
        try:
            from werkzeug.security import check_password_hash

            password_valid = check_password_hash(
                stored_password,
                password
            )
        except (ValueError, TypeError):
            password_valid = False

        # Legacy plain-text password compatibility.
        if not password_valid and stored_password == password:
            password_valid = True

        if not password_valid:
            return render_template(
                "login.html",
                error="Invalid username or password."
            )

        # Prevent inactive or missing faculty accounts from logging in.
        if user["role"] == "faculty":
            check_conn = get_db_connection()

            try:
                faculty_columns = get_table_columns("faculty")

                if "username" not in faculty_columns:
                    return render_template(
                        "login.html",
                        error="Unable to verify this faculty account. Please contact the administrator."
                    )

                if "active" in faculty_columns:
                    faculty_account = check_conn.execute(
                        """
                        SELECT active
                        FROM faculty
                        WHERE username = ?
                        """,
                        (username,)
                    ).fetchone()

                    if (
                        faculty_account is None
                        or not faculty_account["active"]
                    ):
                        return render_template(
                            "login.html",
                            error="This faculty account is inactive or unavailable. Please contact the administrator."
                        )
                else:
                    faculty_account = check_conn.execute(
                        """
                        SELECT id
                        FROM faculty
                        WHERE username = ?
                        """,
                        (username,)
                    ).fetchone()

                    if faculty_account is None:
                        return render_template(
                            "login.html",
                            error="Faculty account not found. Please contact the administrator."
                        )

            finally:
                check_conn.close()

        # Create a fresh session after successful authentication.
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]

        # Redirect based on user role.
        if user["role"] == "admin":
            return redirect(url_for("dashboard"))

        elif user["role"] == "faculty":
            return redirect(url_for("faculty_dashboard"))

        elif user["role"] == "student":
            return redirect(url_for("student_dashboard"))

        # Clear the session if the role is not recognized.
        session.clear()

        return render_template(
            "login.html",
            error="Unknown user role."
        )

    return render_template("login.html")


# ============================================================
# LOGOUT
# ============================================================


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    if session.get("user_id"):
        role = session.get("role")

        if role == "admin":
            return redirect(url_for("dashboard"))

        if role == "faculty":
            return redirect(url_for("faculty_dashboard"))

        if role == "student":
            return redirect(url_for("student_dashboard"))

        session.clear()

    return redirect(url_for("login"))


# ============================================================
# CAMERA CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_DIR = os.path.join(BASE_DIR, "models")

YUNET_MODEL_PATH = os.path.join(
    MODEL_DIR,
    "face_detection_yunet_2026may.onnx"
)

SFACE_MODEL_PATH = os.path.join(
    MODEL_DIR,
    "face_recognition_sface_2021dec.onnx"
)

FACE_SIMILARITY_THRESHOLD = 0.40

# Attendance window end is always the timetable class end time.
CAMERA_MINUTES_BEFORE_CLASS = 5

_camera_detector = None
_camera_recognizer = None


def get_camera_models():
    global _camera_detector, _camera_recognizer

    if (
        _camera_detector is not None
        and _camera_recognizer is not None
    ):
        return _camera_detector, _camera_recognizer

    if not os.path.isfile(YUNET_MODEL_PATH):
        raise FileNotFoundError(
            f"YuNet model not found: {YUNET_MODEL_PATH}"
        )

    if not os.path.isfile(SFACE_MODEL_PATH):
        raise FileNotFoundError(
            f"SFace model not found: {SFACE_MODEL_PATH}"
        )

    _camera_detector = cv2.FaceDetectorYN.create(
        YUNET_MODEL_PATH,
        "",
        (640, 480),
        0.9,
        0.3,
        5000
    )

    _camera_recognizer = cv2.FaceRecognizerSF.create(
        SFACE_MODEL_PATH,
        ""
    )

    return _camera_detector, _camera_recognizer


# ============================================================
# FACE EMBEDDINGS
# ============================================================

def load_enrolled_face_embeddings():

    conn = get_db_connection()

    try:
        rows = conn.execute(
            """
            SELECT id, student_id, name, face_encoding
            FROM students
            WHERE face_encoding IS NOT NULL
            ORDER BY student_id
            """
        ).fetchall()

    finally:
        conn.close()

    enrolled = []

    for row in rows:
        try:
            raw = row["face_encoding"]

            if raw is None:
                continue

            embedding = np.frombuffer(
                raw,
                dtype=np.float32
            ).copy()

            norm = float(np.linalg.norm(embedding))

            if embedding.size == 0 or norm == 0:
                continue

            embedding /= norm

            enrolled.append({
                "database_id": row["id"],
                "student_id": row["student_id"],
                "name": row["name"],
                "embedding": embedding
            })

        except (TypeError, ValueError):
            app.logger.warning(
                "Skipping invalid student face encoding."
            )

    return enrolled


def browser_face_position(face, frame_width):

    x = float(face[0])
    face_width = float(face[2])

    center_ratio = (
        x + face_width / 2.0
    ) / float(frame_width)

    if center_ratio < 0.35:
        return "LEFT"

    if center_ratio > 0.65:
        return "RIGHT"

    return "CENTER"


# ============================================================
# TIME HELPERS
# ============================================================

def _time_value(value):
    """Parse common timetable time formats safely.

    Handles SQLite strings such as 09:00, 09:00:00, 9:00 AM,
    09:00AM, 9.00 AM and datetime.time values. Invalid/missing
    values return None so the schedule matcher can skip that row.
    """
    if value is None:
        return None

    if hasattr(value, "hour") and hasattr(value, "minute"):
        try:
            from datetime import time as _time
            return _time(
                int(value.hour), int(value.minute),
                int(getattr(value, "second", 0)),
            )
        except (TypeError, ValueError, OverflowError):
            return None

    text_value = str(value).strip().upper()
    if not text_value:
        return None

    # Normalize common database/user-entered variations.
    text_value = re.sub(r"\s+", " ", text_value)
    text_value = re.sub(r"(?<=\d)(AM|PM)$", r" \1", text_value)
    text_value = text_value.replace(".", ":") if re.search(r"^\d{1,2}\.\d{2}(?:\s*(?:AM|PM))?$", text_value) else text_value
    text_value = re.sub(r"\s*(AM|PM)$", r" \1", text_value).strip()

    for fmt in (
        "%H:%M", "%H:%M:%S", "%H:%M:%S.%f",
        "%I:%M %p", "%I:%M:%S %p", "%I:%M:%S.%f %p",
        "%I %p", "%H.%M", "%H.%M.%S",
    ):
        try:
            return datetime.strptime(text_value, fmt).time()
        except ValueError:
            continue

    return None


def _normalize_weekday(value):
    """Normalize short/full weekday names and common weekday spellings."""
    day = str(value or "").strip().lower().rstrip(".")
    day = re.sub(r"\s+", " ", day)
    # Permit values like 'Friday (Week 1)' or 'Friday - Lab'.
    day = re.split(r"[(/-]", day, maxsplit=1)[0].strip()
    aliases = {
        "mon": "monday", "monday": "monday",
        "tue": "tuesday", "tues": "tuesday", "tuesday": "tuesday",
        "wed": "wednesday", "weds": "wednesday", "wednesday": "wednesday",
        "thu": "thursday", "thur": "thursday", "thurs": "thursday", "thursday": "thursday",
        "fri": "friday", "friday": "friday",
        "sat": "saturday", "saturday": "saturday",
        "sun": "sunday", "sunday": "sunday",
    }
    return aliases.get(day, day)


def _timetable_day_value(item):
    for key in ("day", "weekday", "day_of_week", "class_day"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return value
    return ""


def _timetable_time_value(item, kind):
    keys = (("start_time", "from_time", "start", "time_from")
            if kind == "start" else
            ("end_time", "to_time", "end", "time_to"))
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return value
    return ""


def _timetable_row_is_active(item):
    for key in ("active", "is_active"):
        if key in item and item.get(key) is not None:
            value = str(item.get(key)).strip().lower()
            return value not in ("0", "false", "no", "inactive", "disabled")
    return True


def get_camera_window_for_class(
    timetable_row,
    selected_date=None
):

    if timetable_row is None:
        return None

    selected_date = (
        selected_date or date.today().isoformat()
    )

    try:
        class_date = date.fromisoformat(selected_date)

    except (TypeError, ValueError):
        return None

    aliases = {
        item.lower()
        for item in get_day_aliases(selected_date)
    }

    if (
        str(timetable_row["day"] or "").strip().lower()
        not in aliases
    ):
        return None

    start_time = _time_value(
        timetable_row["start_time"]
    )

    if start_time is None:
        return None

    class_start = datetime.combine(
        class_date,
        start_time
    )

    # Attendance may open a few minutes before class, but it must
    # remain available for the WHOLE scheduled class. Do not calculate
    # the end from CAMERA_WINDOW_MINUTES: that created a 25-minute
    # window (e.g. 1:25-1:50) for a 1:30-2:30 class.
    window_start = class_start - timedelta(
        minutes=CAMERA_MINUTES_BEFORE_CLASS
    )

    window_end = datetime.combine(
        class_date,
        _time_value(timetable_row["end_time"])
    )

    return {
        "start": window_start,
        "end": window_end,
        "start_text": window_start.strftime("%H:%M"),
        "end_text": window_end.strftime("%H:%M")
    }


def get_current_timetable_class(now=None):
    now = now or datetime.now()

    aliases = get_day_aliases(now.date().isoformat())
    if not aliases:
        return None

    placeholders = ",".join("?" for _ in aliases)
    conn = get_db_connection()

    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM timetable
            WHERE lower(trim(day)) IN ({placeholders})
              AND (active = 1 OR active IS NULL)
            ORDER BY start_time, id
            """,
            tuple(value.lower() for value in aliases)
        ).fetchall()

        for row in rows:
            item = dict(row)

            start_value = item.get("start_time")
            end_value = item.get("end_time")

            start_time = _time_value(start_value)
            end_time = _time_value(end_value)

            if start_time is None or end_time is None:
                app.logger.warning(
                    "Invalid timetable times for class %s: %s - %s",
                    item.get("id"), start_value, end_value
                )
                continue

            class_start = datetime.combine(now.date(), start_time)
            class_end = datetime.combine(now.date(), end_time)

            if class_start <= now < class_end:
                item["camera_start_time"] = class_start.strftime("%H:%M:%S")
                item["camera_end_time"] = class_end.strftime("%H:%M:%S")
                item["camera_window_start"] = class_start
                item["camera_window_end"] = class_end
                return item

        return None

    finally:
        conn.close()
# ============================================================
# CLASS STUDENTS
# ============================================================

def get_class_students(conn, timetable_row):

    students = conn.execute(
        """
        SELECT
            id,
            student_id,
            name,
            department,
            year,
            section
        FROM students
        WHERE COALESCE(active, 1) = 1
          AND student_id NOT IN (
              '23321A0465',
              '23321A0466'
          )
        ORDER BY student_id
        """
    ).fetchall()

    def norm(value):
        return str(value or "").strip().casefold()

    filters = [
        (field, norm(timetable_row[field]))
        for field in (
            "department",
            "year",
            "section"
        )
        if (
            field in timetable_row.keys()
            and norm(timetable_row[field])
        )
    ]

    if not filters:
        return students

    return [
        student
        for student in students
        if all(
            norm(student[field]) == expected
            for field, expected in filters
        )
    ]

# ============================================================
# CLASS ATTENDANCE ROWS
# ============================================================



def _class_attendance_rows(conn, timetable_row, selected_date):
    """
    Return the selected class roster with attendance details.

    Missing attendance is Unmarked until the scheduled class has ended.
    Absent is only the displayed default for a completed class.
    """

    students = get_class_students(conn, timetable_row)
    student_columns = get_table_columns("students")

    rows = []

    subject_name = timetable_subject(timetable_row)
    faculty_name = (
        timetable_row["faculty_name"]
        if "faculty_name" in timetable_row.keys()
        and timetable_row["faculty_name"]
        else (
            timetable_row["faculty"]
            if "faculty" in timetable_row.keys()
            else "-"
        )
    )

    for student in students:
        attendance = conn.execute(
            """
            SELECT status, time, confidence
            FROM attendance
            WHERE student_id = ?
              AND timetable_id = ?
              AND date = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                student["id"],
                timetable_row["id"],
                selected_date
            )
        ).fetchone()

        email = "-"

        if "email" in student_columns:
            email_row = conn.execute(
                """
                SELECT email
                FROM students
                WHERE id = ?
                """,
                (student["id"],)
            ).fetchone()

            if email_row and email_row["email"]:
                email = email_row["email"]

        student_code = student["student_id"] or "-"
        student_name = student["name"] or "-"

        rows.append({
            "id": student["id"],
            "student_database_id": student["id"],

            "student_id": student_code,
            "student_code": student_code,

            "name": student_name,
            "student_name": student_name,
            "email": email,

            "timetable_id": timetable_row["id"],
            "subject_name": subject_name,
            "course_code": (
                timetable_row["course_code"]
                if "course_code" in timetable_row.keys()
                else ""
            ),
            "faculty_name": faculty_name,
            "start_time": (
                timetable_row["start_time"]
                if "start_time" in timetable_row.keys()
                else ""
            ),
            "end_time": (
                timetable_row["end_time"]
                if "end_time" in timetable_row.keys()
                else ""
            ),
            "room_no": timetable_room(timetable_row),
            "date": selected_date,

            "time": (
                attendance["time"]
                if attendance and attendance["time"]
                else ""
            ),
            "status": (
                attendance["status"]
                if attendance and attendance["status"]
                else "Unmarked"
            ),
            "confidence": (
                attendance["confidence"]
                if attendance
                else None
            )
        })

    # Do not show Absent until the scheduled class has ended. This also
    # hides any stale/premature Absent rows while a class is future/ongoing.
    try:
        selected_day = date.fromisoformat(str(selected_date))
    except (TypeError, ValueError):
        selected_day = date.today()

    today = date.today()
    if selected_day > today:
        class_state = "future"
    elif selected_day < today:
        class_state = "past"
    else:
        start_time = _time_value(
            timetable_row["start_time"]
            if "start_time" in timetable_row.keys() else None
        )
        end_time = _time_value(
            timetable_row["end_time"]
            if "end_time" in timetable_row.keys() else None
        )
        current_time = datetime.now().time()
        if start_time is not None and current_time < start_time:
            class_state = "future"
        elif end_time is not None and current_time >= end_time:
            class_state = "past"
        else:
            class_state = "ongoing"

    for row in rows:
        raw_status = str(row.get("status") or "").strip().lower()
        if class_state == "future":
            row["status"] = "Unmarked"
        elif class_state == "ongoing":
            if raw_status in ("present", "p"):
                row["status"] = "Present"
            elif raw_status in ("late", "l"):
                row["status"] = "Late"
            else:
                row["status"] = "Unmarked"
        else:
            if raw_status in ("present", "p"):
                row["status"] = "Present"
            elif raw_status in ("late", "l"):
                row["status"] = "Late"
            elif raw_status in ("absent", "a"):
                row["status"] = "Absent"
            else:
                row["status"] = "Absent"

    rows.sort(
        key=lambda row: (
            0 if str(row["status"]).strip().lower() == "absent" else
            1 if str(row["status"]).strip().lower() in ("present", "late") else 2,
            str(row["student_id"]).casefold()
        )
    )

    return rows



# ============================================================
# FINALIZE ONE CLASS ATTENDANCE
# ============================================================

# ============================================================
# FINALIZE CLASS ATTENDANCE
# ============================================================

def finalize_class_attendance(
    timetable_id,
    display_date,
    session_end=None
):
    selected_date = str(display_date).strip()

    if selected_date != date.today().isoformat():
        return {
            "success": False,
            "message": "Only today's attendance can be finalized."
        }, 400

    conn = get_db_connection()

    try:
        timetable = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE id = ?
              AND (active = 1 OR active IS NULL)
            """,
            (timetable_id,)
        ).fetchone()

        if timetable is None:
            return {
                "success": False,
                "message": "The selected timetable class was not found."
            }, 404

        aliases = {
            value.lower()
            for value in get_day_aliases(selected_date)
        }

        if str(timetable["day"] or "").strip().lower() not in aliases:
            return {
                "success": False,
                "message": "This class is not scheduled for today."
            }, 400

        start_time = _time_value(timetable["start_time"])
        end_time = _time_value(timetable["end_time"])

        if start_time is None or end_time is None:
            return {
                "success": False,
                "message": "The timetable has invalid start/end times."
            }, 400

        class_end = datetime.combine(
            date.fromisoformat(selected_date),
            end_time
        )

        if datetime.now() < class_end:
            return {
                "success": False,
                "message": "The class has not ended yet.",
                "finalize_at": class_end.strftime("%H:%M:%S")
            }, 409

        finalized_at = datetime.now().strftime("%H:%M:%S")
        absent_added = 0

        conn.execute("BEGIN")

        for student in get_class_students(conn, timetable):
            exists = conn.execute(
                """
                SELECT id
                FROM attendance
                WHERE student_id = ?
                  AND timetable_id = ?
                  AND date = ?
                LIMIT 1
                """,
                (
                    student["id"],
                    timetable_id,
                    selected_date
                )
            ).fetchone()

            if exists:
                continue

            conn.execute(
                """
                INSERT INTO attendance
                    (student_id, timetable_id, date, time,
                     status, confidence)
                VALUES (?, ?, ?, ?, 'Absent', NULL)
                """,
                (
                    student["id"],
                    timetable_id,
                    selected_date,
                    finalized_at
                )
            )

            absent_added += 1

        conn.commit()

        return {
            "success": True,
            "message": "Attendance finalized.",
            "timetable_id": int(timetable_id),
            "date": selected_date,
            "finalized_at": finalized_at,
            "absent_added": absent_added,
            "records": _class_attendance_rows(
                conn, timetable, selected_date
            )
        }, 200

    except Exception:
        conn.rollback()
        app.logger.exception(
            "Failed to finalize attendance for timetable %s",
            timetable_id
        )
        return {
            "success": False,
            "message": "Attendance finalization failed. Check server logs."
        }, 500

    finally:
        conn.close()
# ============================================================
# MARK BROWSER ATTENDANCE
# ============================================================

def mark_browser_attendance(
    student_database_id,
    timetable_id,
    similarity
):
    """Mark a recognized student once for this class/date.

    Existing Present/Late rows are preserved on resume. If an Absent row was
    created prematurely while the class is still active, recognition corrects
    that row instead of treating the student as already attended.
    """
    now = datetime.now()
    attendance_date = now.strftime("%Y-%m-%d")
    attendance_time = now.strftime("%H:%M:%S")

    conn = get_db_connection()
    try:
        timetable_columns = get_table_columns("timetable")
        status = "Present"

        if "late_after" in timetable_columns:
            late_row = conn.execute(
                "SELECT late_after FROM timetable WHERE id = ?",
                (timetable_id,)
            ).fetchone()
            if late_row and late_row["late_after"]:
                try:
                    hour, minute = map(
                        int, late_row["late_after"].split(":")[:2]
                    )
                    if now.hour * 60 + now.minute > hour * 60 + minute:
                        status = "Late"
                except (ValueError, AttributeError):
                    app.logger.warning(
                        "Invalid late_after value for timetable %s",
                        timetable_id
                    )

        existing = conn.execute(
            """
            SELECT id, status
            FROM attendance
            WHERE student_id = ?
              AND timetable_id = ?
              AND date = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (student_database_id, timetable_id, attendance_date)
        ).fetchone()

        if existing:
            old_status = str(existing["status"] or "").strip().lower()

            if old_status in ("absent", "a", "unmarked", ""):
                conn.execute(
                    """
                    UPDATE attendance
                    SET status = ?, time = ?, confidence = ?
                    WHERE id = ?
                    """,
                    (status, attendance_time, float(similarity), existing["id"])
                )
                conn.commit()
                return {
                    "message": "Attendance updated to Present for this class.",
                    "status": status,
                    "already_marked": False,
                    "updated_existing": True
                }

            # A student who was already Present/Late stays marked and is not
            # inserted a second time when monitoring resumes.
            return {
                "message": "Attendance was already marked for this class today.",
                "status": existing["status"],
                "already_marked": True
            }

        conn.execute(
            """
            INSERT INTO attendance
                (student_id, timetable_id, date, time, status, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                student_database_id,
                timetable_id,
                attendance_date,
                attendance_time,
                status,
                float(similarity)
            )
        )
        conn.commit()
        return {
            "message": "Attendance marked successfully.",
            "status": status,
            "already_marked": False
        }
    finally:
        conn.close()


# ============================================================
# CAMERA START PAGE
# FULL CLASS ATTENDANCE
# ============================================================

@app.route("/start-attendance")
@role_required("admin")
def start_attendance_page():

    return render_template(
        "start_attendance.html"
    )



# ============================================================
# CAMERA START API
# FULL SCHEDULED CLASS WINDOW
# ============================================================

@app.route(
    "/api/attendance/camera/start",
    methods=["POST"]
)
@role_required("admin")
def browser_camera_start():

    now = datetime.now()
    today = date.today()

    print()
    print("=" * 70)
    print("DEBUG CAMERA START")
    print("NOW:", now)
    print("DATE:", today)
    print("=" * 70)

    # ========================================================
    # FIND TODAY'S DAY ALIASES
    # ========================================================

    day_aliases = {
        str(value).strip().lower()
        for value in get_day_aliases(today)
    }

    print(
        "DEBUG DAY ALIASES:",
        day_aliases
    )

    # ========================================================
    # LOAD TODAY'S TIMETABLE
    # ========================================================

    conn = get_db_connection()

    try:

        rows = all_timetable_rows(conn)

        timetable_rows = [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()

    print(
        "DEBUG TOTAL TIMETABLE ROWS:",
        len(timetable_rows)
    )

    # ========================================================
    # FIND THE CLASS CURRENTLY RUNNING
    #
    # Example:
    #
    # 15:30 - 16:30
    #
    # 15:30 -> active
    # 15:45 -> active
    # 16:29 -> active
    # 16:30 -> ended
    # ========================================================

    current_class = None

    for item in timetable_rows:

        # ----------------------------------------------------
        # ACTIVE FLAG
        # ----------------------------------------------------

        if not _timetable_row_is_active(item):
            continue

        # ----------------------------------------------------
        # DAY
        # ----------------------------------------------------

        item_day = _normalize_weekday(_timetable_day_value(item))
        normalized_today = {_normalize_weekday(day) for day in day_aliases}
        if item_day not in normalized_today:
            continue

        # ----------------------------------------------------
        # START TIME
        # ----------------------------------------------------

        start_time_value = _timetable_time_value(item, "start")

        # ----------------------------------------------------
        # END TIME
        # ----------------------------------------------------

        end_time_value = _timetable_time_value(item, "end")

        if (
            not start_time_value
            or not end_time_value
        ):
            continue

        # ----------------------------------------------------
        # PARSE TIMES
        # ----------------------------------------------------

        start_time_obj = _time_value(
            start_time_value
        )

        end_time_obj = _time_value(
            end_time_value
        )

        if (
            start_time_obj is None
            or end_time_obj is None
        ):

            print(
                "DEBUG INVALID TIME:",
                item.get("id"),
                start_time_value,
                end_time_value
            )

            continue

        # ----------------------------------------------------
        # BUILD TODAY'S DATETIME VALUES
        # ----------------------------------------------------

        class_start = datetime.combine(
            today,
            start_time_obj
        )

        class_end = datetime.combine(
            today,
            end_time_obj
        )

        # ----------------------------------------------------
        # INVALID CLASS RANGE
        # ----------------------------------------------------

        if class_end <= class_start:
            continue

        # ----------------------------------------------------
        # IS THIS CLASS CURRENTLY RUNNING?
        # ----------------------------------------------------

        if class_start <= now < class_end:

            current_class = item.copy()

            current_class["_class_start"] = (
                class_start
            )

            current_class["_class_end"] = (
                class_end
            )

            print(
                "DEBUG CURRENT CLASS FOUND:"
            )

            print(
                "  ID:",
                current_class.get("id")
            )

            print(
                "  START:",
                class_start
            )

            print(
                "  END:",
                class_end
            )

            break

    # ========================================================
    # NO CURRENT CLASS
    # ========================================================

    if current_class is None:

        print(
            "DEBUG: NO CURRENT CLASS FOUND"
        )

        return jsonify({

            "success": False,

            "has_active_class": False,

            "message": (
                "No class is currently scheduled "
                "for attendance."
            )

        }), 409

    # ========================================================
    # GET TIMETABLE ID
    # ========================================================

    timetable_id = current_class.get("id")

    if timetable_id is None:

        return jsonify({

            "success": False,

            "message": (
                "The scheduled class does not "
                "have a timetable ID."
            )

        }), 500

    try:

        timetable_id = int(
            timetable_id
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({

            "success": False,

            "message": (
                "Invalid timetable ID."
            )

        }), 500

    # ========================================================
    # GET SCHEDULED CLASS TIMES
    # ========================================================

    class_start = (
        current_class["_class_start"]
    )

    class_end = (
        current_class["_class_end"]
    )

    # ========================================================
    # CLASS DETAILS
    # ========================================================

    class_name = (
        current_class.get(
            "class_name"
        )
        or current_class.get(
            "class_section"
        )
        or current_class.get(
            "section"
        )
        or ""
    )

    subject = (
        current_class.get(
            "subject_name"
        )
        or current_class.get(
            "subject"
        )
        or current_class.get(
            "course_name"
        )
        or current_class.get(
            "course_code"
        )
        or ""
    )

    faculty = (
        current_class.get(
            "faculty_name"
        )
        or current_class.get(
            "faculty"
        )
        or "-"
    )

    # ========================================================
    # HANDLE EXISTING CAMERA SESSION
    #
    # IMPORTANT:
    #
    # SAME CLASS:
    #     Reuse the existing session.
    #
    # OLD CLASS:
    #     Clear it and start the new class.
    #
    # THIS PREVENTS:
    # "A camera attendance session is already active."
    # ========================================================

    existing_active = bool(
        session.get(
            "camera_session_active",
            False
        )
    )

    if existing_active:

        existing_timetable_id = (
            session.get(
                "camera_timetable_id"
            )
        )

        existing_end_text = (
            session.get(
                "camera_session_end"
            )
        )

        existing_end = None

        if existing_end_text:

            try:

                existing_end = (
                    datetime.fromisoformat(
                        existing_end_text
                    )
                )

            except (
                TypeError,
                ValueError
            ):

                existing_end = None

        same_class = False

        try:

            same_class = (
                existing_timetable_id
                is not None
                and int(
                    existing_timetable_id
                ) == timetable_id
            )

        except (
            TypeError,
            ValueError
        ):

            same_class = False

        # ----------------------------------------------------
        # SAME CLASS + STILL INSIDE SCHEDULED WINDOW
        # ----------------------------------------------------

        if (
            same_class
            and existing_end is not None
            and now < existing_end
        ):

            print(
                "DEBUG: EXISTING SESSION BELONGS "
                "TO CURRENT CLASS."
            )

            print(
                "DEBUG: REUSING EXISTING SESSION."
            )

            # ------------------------------------------------
            # IMPORTANT:
            #
            # Always use timetable times.
            #
            # Never use the button-click time as the
            # camera schedule.
            # ------------------------------------------------

            return jsonify({

                "success": True,

                "already_active": True,

                "has_active_class": True,

                "message": (
                    "Camera attendance is already "
                    "active for this scheduled class."
                ),

                "class_name": class_name,

                "subject": subject,

                "faculty": faculty,

                "timetable_id": timetable_id,

                "start_time": (
                    class_start.strftime(
                        "%H:%M:%S"
                    )
                ),

                "end_time": (
                    class_end.strftime(
                        "%H:%M:%S"
                    )
                ),

                "camera_start_time": (
                    class_start.strftime(
                        "%H:%M:%S"
                    )
                ),

                "camera_end_time": (
                    class_end.strftime(
                        "%H:%M:%S"
                    )
                ),

                "session_start": (
                    class_start.isoformat()
                ),

                "session_end": (
                    class_end.isoformat()
                ),

                "duration_minutes": int(
                    (
                        class_end
                        - class_start
                    ).total_seconds()
                    // 60
                )

            })

        # ----------------------------------------------------
        # OLD / EXPIRED / CORRUPTED SESSION
        # ----------------------------------------------------

        print(
            "DEBUG: CLEARING OLD CAMERA SESSION."
        )

        print(
            "DEBUG OLD TIMETABLE:",
            existing_timetable_id
        )

        print(
            "DEBUG NEW TIMETABLE:",
            timetable_id
        )

        session[
            "camera_session_active"
        ] = False

        for key in (
            "camera_timetable_id",
            "camera_session_date",
            "camera_session_start",
            "camera_session_end",
            "camera_class_name",
            "camera_subject"
        ):

            session.pop(
                key,
                None
            )

        session[
            "camera_session_finalized"
        ] = True

    # ========================================================
    # INITIALIZE FACE RECOGNITION
    # ========================================================

    try:

        get_camera_models()

        enrolled = (
            load_enrolled_face_embeddings()
        )

        if not enrolled:

            return jsonify({

                "success": False,

                "message": (
                    "No enrolled face encodings "
                    "were found."
                )

            }), 400

    except Exception as exc:

        app.logger.exception(
            "Unable to initialize browser "
            "camera attendance"
        )

        return jsonify({

            "success": False,

            "message": (
                "Camera attendance could not "
                "initialize. Check the model "
                "files and server logs."
            ),

            "error": str(exc)

        }), 500

    # ========================================================
    # CREATE CAMERA SESSION
    #
    # VERY IMPORTANT:
    #
    # SESSION START = SCHEDULED CLASS START
    # SESSION END   = SCHEDULED CLASS END
    #
    # Example:
    #
    # Timetable:
    #     15:30 - 16:30
    #
    # Admin clicks Start:
    #     15:42
    #
    # Camera session:
    #     15:30 - 16:30
    #
    # NOT:
    #     15:42 - 16:30
    # ========================================================

    session[
        "camera_session_active"
    ] = True

    session[
        "camera_timetable_id"
    ] = timetable_id

    session[
        "camera_session_date"
    ] = today.isoformat()

    session[
        "camera_session_start"
    ] = class_start.isoformat()

    session[
        "camera_session_end"
    ] = class_end.isoformat()

    session[
        "camera_session_finalized"
    ] = False

    session[
        "camera_class_name"
    ] = class_name

    session[
        "camera_subject"
    ] = subject

    # ========================================================
    # CLASS DURATION
    # ========================================================

    duration_seconds = max(
        0,
        int(
            (
                class_end
                - class_start
            ).total_seconds()
        )
    )

    duration_minutes = (
        duration_seconds // 60
    )

    # ========================================================
    # DEBUG
    # ========================================================

    print(
        "DEBUG: CAMERA ATTENDANCE STARTED"
    )

    print(
        "DEBUG TIMETABLE ID:",
        timetable_id
    )

    print(
        "DEBUG SCHEDULED START:",
        class_start
    )

    print(
        "DEBUG SCHEDULED END:",
        class_end
    )

    print(
        "DEBUG CAMERA SESSION START:",
        session[
            "camera_session_start"
        ]
    )

    print(
        "DEBUG CAMERA SESSION END:",
        session[
            "camera_session_end"
        ]
    )

    # ========================================================
    # RESPONSE
    # ========================================================

    return jsonify({

        "success": True,

        "already_active": False,

        "has_active_class": True,

        "message": (
            "Camera attendance started. "
            "Attendance is active for the "
            "complete scheduled class window."
        ),

        "class_name": class_name,

        "subject": subject,

        "faculty": faculty,

        "timetable_id": timetable_id,

        # ----------------------------------------------------
        # SCHEDULED CLASS TIMES
        # ----------------------------------------------------

        "start_time": (
            class_start.strftime(
                "%H:%M:%S"
            )
        ),

        "end_time": (
            class_end.strftime(
                "%H:%M:%S"
            )
        ),

        # ----------------------------------------------------
        # CAMERA TIMES
        #
        # These are ALSO the scheduled times.
        # ----------------------------------------------------

        "camera_start_time": (
            class_start.strftime(
                "%H:%M:%S"
            )
        ),

        "camera_end_time": (
            class_end.strftime(
                "%H:%M:%S"
            )
        ),

        "session_start": (
            class_start.isoformat()
        ),

        "session_end": (
            class_end.isoformat()
        ),

        "duration_minutes": (
            duration_minutes
        )
    })


# ============================================================
# CAMERA SCHEDULE API
# FULL SCHEDULED CLASS WINDOW
# ============================================================

@app.route(
    "/api/attendance/camera/schedule"
)
@role_required("admin")
def browser_camera_schedule():

    now = datetime.now()
    today = date.today()

    app.logger.info(
        "CAMERA SCHEDULE CHECK: now=%s date=%s",
        now.isoformat(timespec="seconds"),
        today.isoformat(),
    )

    # ========================================================
    # TODAY'S DAY ALIASES
    # ========================================================

    day_aliases = {
        str(value).strip().lower()
        for value in get_day_aliases(today)
    }

    # ========================================================
    # LOAD TIMETABLE
    # ========================================================

    conn = get_db_connection()

    try:

        rows = all_timetable_rows(conn)

        timetable_rows = [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()

    app.logger.info(
        "CAMERA SCHEDULE TIMETABLE ROWS: %s; weekday aliases=%s",
        len(timetable_rows),
        sorted(day_aliases),
    )

    # ========================================================
    # FIND CURRENT CLASS
    # ========================================================

    current_class = None

    for item in timetable_rows:

        # ----------------------------------------------------
        # ACTIVE FLAG
        # ----------------------------------------------------

        if not _timetable_row_is_active(item):
            continue

        # ----------------------------------------------------
        # DAY
        # ----------------------------------------------------

        item_day = _normalize_weekday(_timetable_day_value(item))
        normalized_today = {_normalize_weekday(day) for day in day_aliases}
        if item_day not in normalized_today:
            continue

        # ----------------------------------------------------
        # TIMES
        # ----------------------------------------------------

        start_time_value = _timetable_time_value(item, "start")

        end_time_value = _timetable_time_value(item, "end")

        if (
            not start_time_value
            or not end_time_value
        ):
            continue

        # ----------------------------------------------------
        # PARSE
        # ----------------------------------------------------

        start_time_obj = _time_value(
            start_time_value
        )

        end_time_obj = _time_value(
            end_time_value
        )

        if (
            start_time_obj is None
            or end_time_obj is None
        ):
            continue

        # ----------------------------------------------------
        # BUILD DATETIME
        # ----------------------------------------------------

        class_start = datetime.combine(
            today,
            start_time_obj
        )

        class_end = datetime.combine(
            today,
            end_time_obj
        )

        if class_end <= class_start:
            continue

        # ----------------------------------------------------
        # CURRENT CLASS
        # ----------------------------------------------------

        if class_start <= now < class_end:

            current_class = item.copy()

            current_class[
                "_class_start"
            ] = class_start

            current_class[
                "_class_end"
            ] = class_end

            break

    # ========================================================
    # NO ACTIVE CLASS
    # ========================================================

    if current_class is None:

        app.logger.info(
            "CAMERA SCHEDULE: no class matches current weekday/time (%s)",
            now.strftime("%A %H:%M:%S"),
        )

        return jsonify({

            "success": True,

            "has_active_class": False,

            "message": (
                "No class is currently running. "
                "Waiting for the next scheduled class."
            ),

            "date": today.isoformat(),

            "now": now.isoformat()

        })

    # ========================================================
    # CLASS DETAILS
    # ========================================================

    timetable_id = current_class.get(
        "id"
    )

    if timetable_id is None:

        return jsonify({

            "success": False,

            "has_active_class": False,

            "message": (
                "The current timetable entry "
                "has no ID."
            )

        }), 500

    timetable_id = int(
        timetable_id
    )

    class_name = (
        current_class.get(
            "class_name"
        )
        or current_class.get(
            "class_section"
        )
        or current_class.get(
            "section"
        )
        or ""
    )

    subject = (
        current_class.get(
            "subject_name"
        )
        or current_class.get(
            "subject"
        )
        or current_class.get(
            "course_name"
        )
        or current_class.get(
            "course_code"
        )
        or "-"
    )

    faculty = (
        current_class.get(
            "faculty_name"
        )
        or current_class.get(
            "faculty"
        )
        or "-"
    )

    start_time = (
        current_class.get(
            "start_time"
        )
        or current_class.get(
            "from_time"
        )
        or current_class.get(
            "start"
        )
        or ""
    )

    end_time = (
        current_class.get(
            "end_time"
        )
        or current_class.get(
            "to_time"
        )
        or current_class.get(
            "end"
        )
        or ""
    )

    class_start = current_class[
        "_class_start"
    ]

    class_end = current_class[
        "_class_end"
    ]

    # ========================================================
    # RETURN ACTIVE CLASS
    # ========================================================

    return jsonify({

        "success": True,

        "has_active_class": True,

        "timetable_id": timetable_id,

        "class_name": class_name,

        "subject": subject,

        "faculty": faculty,

        # ACTUAL TIMETABLE TIMES
        "start_time": (
            class_start.strftime(
                "%H:%M:%S"
            )
        ),

        "end_time": (
            class_end.strftime(
                "%H:%M:%S"
            )
        ),

        # CAMERA TIMES MUST MATCH TIMETABLE
        "camera_start_time": (
            class_start.strftime(
                "%H:%M:%S"
            )
        ),

        "camera_end_time": (
            class_end.strftime(
                "%H:%M:%S"
            )
        ),

        "date": today.isoformat(),

        "now": now.isoformat(),

        "session_start": (
            class_start.isoformat()
        ),

        "session_end": (
            class_end.isoformat()
        ),

        "duration_minutes": int(
            (
                class_end
                - class_start
            ).total_seconds()
            // 60
        )
    })
# ============================================================
# CAMERA FINALIZE API
# FINALIZE ATTENDANCE + SEND SAME ABSENT EMAIL TO EACH ABSENT
# ============================================================

@app.route(
    "/api/attendance/camera/finalize",
    methods=["POST"]
)
@role_required("admin")
def browser_camera_finalize():

    # ========================================================
    # GET LOCKED CAMERA SESSION
    # ========================================================

    locked_timetable_id = (
        session.get(
            "camera_timetable_id"
        )
    )

    session_date = (
        session.get(
            "camera_session_date"
        )
    )

    session_end_text = (
        session.get(
            "camera_session_end"
        )
    )

    # ========================================================
    # VALIDATE CAMERA SESSION
    # ========================================================

    if not all([
        locked_timetable_id,
        session_date,
        session_end_text
    ]):

        return jsonify({

            "success": False,

            "message": (
                "No valid camera session was found. "
                "Please start attendance first."
            )

        }), 400

    # ========================================================
    # READ REQUEST
    # ========================================================

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    # ========================================================
    # VALIDATE TIMETABLE ID
    # ========================================================

    try:

        requested_timetable_id = int(
            payload.get(
                "timetable_id"
            )
        )

        timetable_id = int(
            locked_timetable_id
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({

            "success": False,

            "message": (
                "Invalid timetable ID."
            )

        }), 400

    # ========================================================
    # NEVER TRUST FRONTEND TIMETABLE ID
    # ========================================================

    if requested_timetable_id != timetable_id:

        return jsonify({

            "success": False,

            "message": (
                "The requested class does not "
                "match the active camera session."
            )

        }), 400

    # ========================================================
    # VALIDATE DATE
    # ========================================================

    selected_date = str(
        payload.get(
            "date"
        )
        or session_date
    )

    if selected_date != session_date:

        return jsonify({

            "success": False,

            "message": (
                "The requested date does not "
                "match the camera session date."
            )

        }), 400

    if selected_date != date.today().isoformat():

        return jsonify({

            "success": False,

            "message": (
                "Only today's camera session "
                "can be finalized."
            )

        }), 400

    # ========================================================
    # VALIDATE CLASS END TIME
    # ========================================================

    try:

        session_end = datetime.fromisoformat(
            session_end_text
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({

            "success": False,

            "message": (
                "Invalid camera session "
                "end time."
            )

        }), 400

    # ========================================================
    # DO NOT FINALIZE EARLY
    # ========================================================

    if datetime.now() < session_end:

        return jsonify({

            "success": False,

            "message": (
                "The class has not ended yet."
            ),

            "finalize_at": (
                session_end.strftime(
                    "%H:%M:%S"
                )
            ),

            "timetable_id": timetable_id

        }), 409

    # ========================================================
    # FINALIZE ATTENDANCE
    # ========================================================

    try:

        result, status_code = (
            finalize_class_attendance(
                timetable_id,
                selected_date,
                session_end=session_end
            )
        )

    except Exception:

        app.logger.exception(
            "Attendance finalization failed "
            "for timetable %s",
            timetable_id
        )

        return jsonify({

            "success": False,

            "message": (
                "Attendance finalization failed."
            )

        }), 500

    # ========================================================
    # STOP IF ATTENDANCE FINALIZATION FAILED
    #
    # IMPORTANT:
    # Do NOT send absence emails if the attendance
    # finalization itself failed.
    # ========================================================

    if (
        status_code != 200
        or not result.get(
            "success"
        )
    ):

        return jsonify(
            result
        ), status_code

    # ========================================================
    # SEND SAME EMAIL TO ALL ABSENTEES
    #
    # No student name is included in the body.
    #
    # Example:
    #
    # Dear Student,
    #
    # You were marked absent for the scheduled class.
    #
    # Subject: Professional Practice, Law & Ethics
    # Faculty: Ms Y Sagarika
    # Date: 2026-10-26
    # Time: 15:30 - 16:30
    # ========================================================

    email_result = {

        "status": "failed",

        "total_absentees": 0,

        "emails_sent": 0,

        "emails_failed": 0,

        "skipped": 0,

        "details": []

    }

    try:

        email_result = (
            notify_completed_timetable_absentees(

                get_db_connection_function=
                    get_db_connection,

                timetable_id=
                    timetable_id,

                attendance_date=
                    date.fromisoformat(
                        selected_date
                    ),

                send_email=True,

                send_whatsapp=False
            )
        )

        # ====================================================
        # PROTECT AGAINST BAD RETURN VALUE
        # ====================================================

        if not isinstance(
            email_result,
            dict
        ):

            app.logger.error(

                "Unexpected email notification "
                "result for timetable %s: %r",

                timetable_id,

                email_result
            )

            email_result = {

                "status": "failed",

                "total_absentees": 0,

                "emails_sent": 0,

                "emails_failed": 0,

                "skipped": 0,

                "details": [],

                "reason": (
                    "Unexpected notification result."
                )

            }

        app.logger.info(

            "CLASS ABSENT EMAIL RESULT: "
            "timetable=%s result=%s",

            timetable_id,

            email_result
        )

    except Exception as exc:

        app.logger.exception(

            "Absent-student email notification "
            "failed for timetable %s",

            timetable_id
        )

        email_result = {

            "status": "failed",

            "total_absentees": 0,

            "emails_sent": 0,

            "emails_failed": 0,

            "skipped": 0,

            "details": [],

            "reason": str(exc)

        }

    # ========================================================
    # CLEAR CAMERA SESSION
    #
    # This is done ONLY after the class has actually ended
    # and attendance finalization has succeeded.
    # ========================================================

    session[
        "camera_session_active"
    ] = False

    session[
        "camera_session_finalized"
    ] = True

    for key in (

        "camera_timetable_id",

        "camera_session_date",

        "camera_session_start",

        "camera_session_end",

        "camera_class_name",

        "camera_subject"

    ):

        session.pop(
            key,
            None
        )

    # ========================================================
    # ATTACH EMAIL RESULT
    # ========================================================

    result[
        "email_notification"
    ] = {

        "status":
            email_result.get(
                "status",
                "failed"
            ),

        "total_absentees":
            email_result.get(
                "total_absentees",
                0
            ),

        "emails_sent":
            email_result.get(
                "emails_sent",
                0
            ),

        "emails_failed":
            email_result.get(
                "emails_failed",
                0
            ),

        "skipped":
            email_result.get(
                "skipped",
                0
            ),

        "details":
            email_result.get(
                "details",
                []
            ),

        "reason":
            email_result.get(
                "reason"
            )
    }

    # ========================================================
    # FINAL RESULT
    # ========================================================

    result[
        "finalized_timetable_id"
    ] = timetable_id

    result[
        "finalized_date"
    ] = selected_date

    result[
        "finalized_at"
    ] = datetime.now().isoformat(
        timespec="seconds"
    )

    return jsonify(
        result
    ), status_code

# ============================================================
# CAMERA FRAME API
# FULL SCHEDULED CLASS DURATION
# ============================================================

@app.route(
    "/api/attendance/camera/frame",
    methods=["POST"]
)
@role_required("admin")
def browser_camera_frame():

    # ========================================================
    # STEP 1: VERIFY ACTIVE CAMERA SESSION
    # ========================================================

    if not session.get(
        "camera_session_active",
        False
    ):

        return jsonify({

            "success": False,

            "state": "no_session",

            "message": (
                "Start a camera attendance session first."
            )

        }), 400

    # ========================================================
    # STEP 2: GET LOCKED SESSION INFORMATION
    #
    # These values were created by browser_camera_start().
    #
    # IMPORTANT:
    # We do NOT call get_current_timetable_class()
    # here.
    #
    # The camera session already belongs to the timetable
    # class that was locked when attendance was started.
    # ========================================================

    timetable_id = session.get(
        "camera_timetable_id"
    )

    session_date = session.get(
        "camera_session_date"
    )

    session_start_text = session.get(
        "camera_session_start"
    )

    session_end_text = session.get(
        "camera_session_end"
    )

    # ========================================================
    # STEP 3: VALIDATE SESSION DATA
    # ========================================================

    if not all([
        timetable_id,
        session_date,
        session_start_text,
        session_end_text
    ]):

        session["camera_session_active"] = False

        return jsonify({

            "success": False,

            "state": "invalid_session",

            "message": (
                "Camera session information is incomplete. "
                "Please start a new camera attendance session."
            )

        }), 400

    # ========================================================
    # STEP 4: CONVERT SESSION TIMESTAMPS
    # ========================================================

    try:

        session_start = datetime.fromisoformat(
            str(session_start_text)
        )

        session_end = datetime.fromisoformat(
            str(session_end_text)
        )

        timetable_id = int(
            timetable_id
        )

    except (
        TypeError,
        ValueError
    ):

        session["camera_session_active"] = False

        return jsonify({

            "success": False,

            "state": "invalid_session",

            "message": (
                "Invalid camera session timestamps. "
                "Please start a new camera session."
            )

        }), 400

    # ========================================================
    # STEP 5: VALIDATE SESSION DATE
    # ========================================================

    today = date.today()

    if session_date != today.isoformat():

        session["camera_session_active"] = False

        return jsonify({

            "success": False,

            "state": "session_expired",

            "message": (
                "This camera attendance session is "
                "no longer valid for today."
            )

        }), 410

    # ========================================================
    # STEP 6: VALIDATE TIME RANGE
    # ========================================================

    if session_end <= session_start:

        session["camera_session_active"] = False

        return jsonify({

            "success": False,

            "state": "invalid_session",

            "message": (
                "The camera session has an invalid "
                "scheduled time range."
            )

        }), 400

    # ========================================================
    # STEP 7: CURRENT TIME
    # ========================================================

    now = datetime.now()

    # ========================================================
    # STEP 8: BEFORE CLASS START
    #
    # This normally should not happen because the start API
    # only allows starting during the scheduled class.
    #
    # We still protect the endpoint.
    # ========================================================

    if now < session_start:

        return jsonify({

            "success": False,

            "state": "before_class",

            "message": (
                "The scheduled class has not started yet."
            ),

            "timetable_id": timetable_id,

            "session_start": (
                session_start.isoformat()
            ),

            "session_end": (
                session_end.isoformat()
            )

        }), 409

    # ========================================================
    # STEP 9: CLASS HAS ENDED
    #
    # IMPORTANT:
    #
    # Do NOT clear camera_session_active here.
    #
    # The finalize endpoint needs the session information
    # in order to finalize the complete class and send
    # absent-student notifications.
    #
    # The frontend should call:
    #
    # /api/attendance/camera/finalize
    #
    # after receiving this state.
    # ========================================================

    if now >= session_end:

        return jsonify({

            "success": False,

            "state": "class_ended",

            "message": (
                "The scheduled class has ended. "
                "Attendance must now be finalized."
            ),

            "timetable_id": timetable_id,

            "session_start": (
                session_start.isoformat()
            ),

            "session_end": (
                session_end.isoformat()
            )

        }), 410

    # ========================================================
    # STEP 10: READ CAMERA IMAGE
    # ========================================================

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    image_data = (
        payload.get(
            "image",
            ""
        )
    )

    if not image_data:

        return jsonify({

            "success": False,

            "state": "no_image",

            "message": (
                "No camera image was received."
            )

        }), 400

    # ========================================================
    # STEP 11: PROCESS CAMERA IMAGE
    # ========================================================

    try:

        # ----------------------------------------------------
        # REMOVE DATA URL PREFIX
        # ----------------------------------------------------

        if "," in image_data:

            image_data = (
                image_data.split(
                    ",",
                    1
                )[1]
            )

        # ----------------------------------------------------
        # DECODE BASE64
        # ----------------------------------------------------

        image_bytes = base64.b64decode(
            image_data,
            validate=True
        )

        # ----------------------------------------------------
        # CONVERT TO OPENCV IMAGE
        # ----------------------------------------------------

        frame = cv2.imdecode(

            np.frombuffer(
                image_bytes,
                dtype=np.uint8
            ),

            cv2.IMREAD_COLOR
        )

        if frame is None:

            return jsonify({

                "success": False,

                "state": "invalid_image",

                "message": (
                    "The camera image could not "
                    "be decoded."
                )

            }), 400

        # ====================================================
        # STEP 12: LOAD FACE RECOGNITION MODELS
        # ====================================================

        detector, recognizer = (
            get_camera_models()
        )

        # ====================================================
        # STEP 13: SET DETECTOR INPUT SIZE
        # ====================================================

        height, width = (
            frame.shape[:2]
        )

        detector.setInputSize(
            (
                width,
                height
            )
        )

        # ====================================================
        # STEP 14: DETECT FACES
        # ====================================================

        _, faces = detector.detect(
            frame
        )

        if (
            faces is None
            or len(faces) == 0
        ):

            return jsonify({

                "success": True,

                "state": "no_face",

                "message": (
                    "No face detected. "
                    "Please look toward the camera."
                ),

                "timetable_id": timetable_id,

                "session_start": (
                    session_start.isoformat()
                ),

                "session_end": (
                    session_end.isoformat()
                )

            })

        # ====================================================
        # STEP 15: SELECT LARGEST FACE
        # ====================================================

        face = max(

            faces,

            key=lambda item:
                float(
                    item[2] * item[3]
                )
        )

        # ====================================================
        # STEP 16: ALIGN FACE
        # ====================================================

        aligned = (
            recognizer.alignCrop(
                frame,
                face
            )
        )

        # ====================================================
        # STEP 17: EXTRACT FACE FEATURE
        # ====================================================

        feature = (
            recognizer.feature(
                aligned
            ).flatten()
        )

        # ====================================================
        # STEP 18: NORMALIZE FEATURE
        # ====================================================

        feature_norm = float(
            np.linalg.norm(
                feature
            )
        )

        if feature_norm == 0:

            return jsonify({

                "success": True,

                "state": "unrecognized",

                "message": (
                    "Could not extract a usable "
                    "face feature."
                ),

                "timetable_id": timetable_id

            })

        feature /= feature_norm

        # ====================================================
        # STEP 19: LOAD ENROLLED STUDENTS
        # ====================================================

        enrolled = load_enrolled_face_embeddings()

        if not enrolled:
            return jsonify({
                "success": False,
                "state": "no_enrollment",
                "message": "No enrolled face encodings were found."
            }), 400

        # Resume-safe behavior: only keep candidates whose attendance is not
        # already Present/Late for this class/date. Database writes are still
        # idempotent in mark_browser_attendance() as a second layer of safety.
        conn = get_db_connection()
        try:
            marked_rows = conn.execute(
                """
                SELECT DISTINCT student_id
                FROM attendance
                WHERE timetable_id = ?
                  AND date = ?
                  AND lower(trim(COALESCE(status, ''))) IN ('present', 'late', 'p', 'l')
                """,
                (timetable_id, session_date)
            ).fetchall()
            already_present_ids = {int(row["student_id"]) for row in marked_rows}
        finally:
            conn.close()

        remaining_enrolled = [
            student for student in enrolled
            if student.get("database_id") is not None
            and int(student["database_id"]) not in already_present_ids
        ]

        if not remaining_enrolled:
            return jsonify({
                "success": True,
                "state": "all_present",
                "message": (
                    "All students with enrolled face data are already marked "
                    "Present/Late for this class. Waiting for the scheduled class to end."
                ),
                "timetable_id": timetable_id,
                "session_start": session_start.isoformat(),
                "session_end": session_end.isoformat()
            })

        enrolled = remaining_enrolled

        # ====================================================
        # STEP 20: FIND BEST FACE MATCH
        # ====================================================

        best_student = None

        best_similarity = -1.0

        for student in enrolled:

            embedding = student.get(
                "embedding"
            )

            if embedding is None:

                continue

            if (
                embedding.shape
                != feature.shape
            ):

                continue

            similarity = float(

                np.dot(
                    feature,
                    embedding
                )
            )

            if similarity > best_similarity:

                best_student = student

                best_similarity = (
                    similarity
                )

        # ====================================================
        # STEP 21: FACE NOT RECOGNIZED
        # ====================================================

        if (

            best_student is None

            or

            best_similarity
            < FACE_SIMILARITY_THRESHOLD

        ):

            return jsonify({

                "success": True,

                "state": "unrecognized",

                "message": (
                    "Face not recognized. "
                    "Please try again."
                ),

                "timetable_id": timetable_id,

                "similarity": round(
                    best_similarity,
                    3
                )

            })

        # ====================================================
        # STEP 22: FINAL TIME CHECK
        #
        # Camera processing can take a little time.
        #
        # Check again immediately before writing attendance
        # so attendance can NEVER be recorded after the
        # scheduled class has ended.
        # ====================================================

        now = datetime.now()

        if now >= session_end:

            return jsonify({

                "success": False,

                "state": "class_ended",

                "message": (
                    "The scheduled class has ended. "
                    "Attendance must now be finalized."
                ),

                "timetable_id": timetable_id,

                "session_start": (
                    session_start.isoformat()
                ),

                "session_end": (
                    session_end.isoformat()
                )

            }), 410

        # ====================================================
        # STEP 23: MARK ATTENDANCE
        #
        # IMPORTANT:
        #
        # Use the timetable ID locked when the camera
        # session started.
        #
        # DO NOT use get_current_timetable_class().
        #
        # This guarantees that a student detected at:
        #
        # 15:35
        #
        # is recorded against the 15:30-16:30 class that
        # owns this camera session.
        # ========================================================

        result = mark_browser_attendance(

            best_student[
                "database_id"
            ],

            timetable_id,

            best_similarity
        )

        # ====================================================
        # STEP 24: RETURN RESULT
        # ====================================================

        return jsonify({

            "success": True,

            "state": "marked",

            "message": (
                result.get(
                    "message"
                )
                or "Attendance processed."
            ),

            "name": (
                best_student.get(
                    "name",
                    ""
                )
            ),

            "roll_number": (
                best_student.get(
                    "student_id",
                    ""
                )
            ),

            "status": (
                result.get(
                    "status",
                    "Present"
                )
            ),

            "similarity": round(
                best_similarity,
                3
            ),

            "already_marked": bool(
                result.get(
                    "already_marked",
                    False
                )
            ),

            "timetable_id": timetable_id,

            # These are the SCHEDULED class boundaries,
            # not the button-click time.
            "session_start": (
                session_start.isoformat()
            ),

            "session_end": (
                session_end.isoformat()
            ),

            "now": (
                now.isoformat()
            )

        })

    # ========================================================
    # STEP 25: UNEXPECTED ERROR
    # ========================================================

    except Exception:

        app.logger.exception(
            "Browser camera frame processing failed"
        )

        return jsonify({

            "success": False,

            "state": "processing_error",

            "message": (
                "Unable to process this camera frame. "
                "Check the server logs."
            )

        }), 500

# ============================================================
# ADMIN RESET CAMERA ATTENDANCE SESSION
# TEMPORARY DEBUG/RECOVERY ROUTE
# ============================================================

@app.route("/admin/reset-camera-session")
@role_required("admin")
def reset_camera_session():

    session["camera_session_active"] = False

    session.pop(
        "camera_timetable_id",
        None
    )

    session.pop(
        "camera_session_date",
        None
    )

    session.pop(
        "camera_session_start",
        None
    )

    session.pop(
        "camera_session_end",
        None
    )

    session["camera_session_finalized"] = True

    return jsonify({
        "success": True,
        "message": "Camera attendance session reset."
    })


# NOTE:
# The Flask server is started once at the end of this file.
# Do not start app.run() before the remaining routes/helpers are defined.
# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@role_required("admin")
def dashboard():

    conn = get_db_connection()

    try:

        # ========================================================
        # COUNT ACTIVE STUDENTS
        # ========================================================

        student_columns = get_table_columns("students")

        if "active" in student_columns:

            student_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM students
                WHERE active = 1
                """
            ).fetchone()["count"]

        else:

            student_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM students
                """
            ).fetchone()["count"]


        # ========================================================
        # COUNT ACTIVE FACULTY
        # ========================================================

        faculty_columns = get_table_columns("faculty")

        if "active" in faculty_columns:

            faculty_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM faculty
                WHERE active = 1
                """
            ).fetchone()["count"]

        else:

            faculty_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM faculty
                """
            ).fetchone()["count"]


        # ========================================================
        # COUNT ACTIVE TIMETABLE CLASSES
        # ========================================================

        timetable_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM timetable
            WHERE COALESCE(active, 1) = 1
            """
        ).fetchone()["count"]


        # ========================================================
        # TOTAL ATTENDANCE RECORDS
        # ========================================================

        attendance_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM attendance
            """
        ).fetchone()["count"]


    finally:

        conn.close()


    # ============================================================
    # RENDER ADMIN DASHBOARD
    # ============================================================

    return render_template(
        "dashboard.html",

        student_count=student_count,

        faculty_count=faculty_count,

        timetable_count=timetable_count,

        attendance_count=attendance_count
    )

# ============================================================
# ADMIN STUDENTS
# ============================================================


@app.route("/admin/students")
@role_required("admin")
def admin_students():

    conn = get_db_connection()

    try:

        students = conn.execute(
            """
            SELECT *
            FROM students
            WHERE active = 1
              AND student_id NOT IN (
                  '23321A0465',
                  '23321A0466'
              )
            ORDER BY student_id
            """
        ).fetchall()

    finally:
        conn.close()

    return render_template(
        "students.html",
        students=students,
        username=session.get("username", "Admin"),
        role=session.get("role", "admin")
    )


# ============================================================
# ADMIN FACULTY
# ============================================================

@app.route("/admin/students/add", methods=["POST"])
@role_required("admin")
def add_student():
    student_id = request.form.get("student_id", "").strip()
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    email = request.form.get("email", "").strip()
    department = request.form.get("department", "").strip()
    year_value = request.form.get("year", "").strip()
    section = request.form.get("section", "").strip()
    password = request.form.get("password", "")

    if not all([student_id, name, password]):
        flash("Roll number, name, and initial password are required.", "error")
        return redirect(url_for("admin_students"))

    if len(password) < 8:
        flash("The initial password must be at least 8 characters.", "error")
        return redirect(url_for("admin_students"))

    year = None
    if year_value:
        try:
            year = int(year_value)
            if year < 1 or year > 6:
                raise ValueError
        except ValueError:
            flash("Year must be a number between 1 and 6.", "error")
            return redirect(url_for("admin_students"))

    conn = get_db_connection()

    try:
        # Prevent duplicate student IDs or login usernames.
        student_exists = conn.execute(
            "SELECT id FROM students WHERE student_id = ?",
            (student_id,)
        ).fetchone()

        user_exists = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (student_id,)
        ).fetchone()

        if student_exists:
            flash("A student with that roll number already exists.", "error")
            return redirect(url_for("admin_students"))

        if user_exists:
            flash(
                "That username already exists. Check existing accounts first.",
                "error"
            )
            return redirect(url_for("admin_students"))

        # Create the student and login account as one transaction.
        conn.execute("BEGIN")

        conn.execute(
            """
            INSERT INTO students
                (student_id, name, mobile, email, department, year, section)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (student_id, name, mobile, email, department, year, section)
        )

        conn.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, 'student')
            """,
            (student_id, generate_password_hash(password))
        )

        conn.commit()
        flash("Student and login account created successfully.", "success")

    except sqlite3.IntegrityError:
        conn.rollback()
        flash(
            "Could not create the student because a duplicate or database constraint was detected.",
            "error"
        )

    except Exception:
        conn.rollback()
        app.logger.exception("Failed to add student")
        flash("An unexpected error occurred while adding the student.", "error")

    finally:
        conn.close()

    return redirect(url_for("admin_students"))

@app.route("/admin/students/edit/<int:student_db_id>", methods=["POST"])
@role_required("admin")
def edit_student(student_db_id):
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    email = request.form.get("email", "").strip()
    department = request.form.get("department", "").strip()
    year_value = request.form.get("year", "").strip()
    section = request.form.get("section", "").strip()

    if not name:
        flash("Student name is required.", "error")
        return redirect(url_for("admin_students"))

    year = None
    if year_value:
        try:
            year = int(year_value)
            if year < 1 or year > 6:
                raise ValueError
        except ValueError:
            flash("Year must be between 1 and 6.", "error")
            return redirect(url_for("admin_students"))

    conn = get_db_connection()
    try:
        student = conn.execute(
            "SELECT id FROM students WHERE id = ?",
            (student_db_id,)
        ).fetchone()

        if not student:
            flash("Student not found.", "error")
            return redirect(url_for("admin_students"))

        conn.execute(
            """
            UPDATE students
            SET name = ?, mobile = ?, email = ?,
                department = ?, year = ?, section = ?
            WHERE id = ?
            """,
            (name, mobile, email, department, year, section, student_db_id)
        )
        conn.commit()
        flash("Student details updated successfully.", "success")

    except sqlite3.Error:
        conn.rollback()
        app.logger.exception("Failed to edit student")
        flash("Could not update student details.", "error")

    finally:
        conn.close()

    return redirect(url_for("admin_students"))


@app.route("/admin/students/remove/<int:student_db_id>", methods=["POST"])
@role_required("admin")
def remove_student(student_db_id):


    conn = get_db_connection()

    try:

        # ========================================================
        # GET STUDENT
        # ========================================================

        student = conn.execute(
            """
            SELECT
                id,
                student_id,
                name
            FROM students
            WHERE id = ?
            """,
            (student_db_id,)
        ).fetchone()

        if not student:

            flash(
                "Student not found.",
                "error"
            )

            return redirect(
                url_for("admin_students")
            )

        # ========================================================
        # PERMANENT DELETE
        #
        # Delete related attendance first because attendance
        # uses students.id as student_id.
        # ========================================================

        conn.execute("BEGIN")

        # --------------------------------------------------------
        # 1. DELETE ATTENDANCE RECORDS
        # --------------------------------------------------------

        conn.execute(
            """
            DELETE FROM attendance
            WHERE student_id = ?
            """,
            (student_db_id,)
        )

        # --------------------------------------------------------
        # 2. DELETE STUDENT LOGIN ACCOUNT
        # --------------------------------------------------------

        conn.execute(
            """
            DELETE FROM users
            WHERE username = ?
              AND role = 'student'
            """,
            (student["student_id"],)
        )

        # --------------------------------------------------------
        # 3. PERMANENTLY DELETE STUDENT
        # --------------------------------------------------------

        conn.execute(
            """
            DELETE FROM students
            WHERE id = ?
            """,
            (student_db_id,)
        )

        # --------------------------------------------------------
        # COMMIT
        # --------------------------------------------------------

        conn.commit()

        flash(
            f"Student '{student['student_id']}' "
            "and all related attendance records were permanently deleted.",
            "success"
        )

    except sqlite3.Error as exc:

        conn.rollback()

        app.logger.exception(
            "Failed to permanently delete student"
        )

        flash(
            f"Could not permanently delete the student: {exc}",
            "error"
        )

    finally:

        conn.close()

    return redirect(
        url_for("admin_students")
    )

@app.route("/admin/cleanup-unwanted-students", methods=["POST"])
@role_required("admin")
def cleanup_unwanted_students():

    unwanted_roll_numbers = [
        "23321A0465",
        "23321A0466",
    ]

    conn = get_db_connection()

    try:

        placeholders = ",".join(
            "?" for _ in unwanted_roll_numbers
        )

        # Find students
        students = conn.execute(
            f"""
            SELECT id, student_id, name
            FROM students
            WHERE student_id IN ({placeholders})
            """,
            unwanted_roll_numbers
        ).fetchall()

        student_ids = [
            row["id"]
            for row in students
        ]

        if student_ids:

            id_placeholders = ",".join(
                "?" for _ in student_ids
            )

            # Delete attendance
            conn.execute(
                f"""
                DELETE FROM attendance
                WHERE student_id IN ({id_placeholders})
                """,
                student_ids
            )

            # Delete login accounts
            conn.execute(
                f"""
                DELETE FROM users
                WHERE username IN ({placeholders})
                  AND role = 'student'
                """,
                unwanted_roll_numbers
            )

            # Delete students permanently
            conn.execute(
                f"""
                DELETE FROM students
                WHERE id IN ({id_placeholders})
                """,
                student_ids
            )

        conn.commit()

        flash(
            "Unwanted students were permanently deleted.",
            "success"
        )

    except Exception as exc:

        conn.rollback()

        app.logger.exception(
            "Failed to clean unwanted students"
        )

        flash(
            f"Cleanup failed: {exc}",
            "error"
        )

    finally:
        conn.close()

    return redirect(
        url_for("admin_attendance_history")
    )
@app.route("/admin/faculty")
@role_required("admin")
def admin_faculty():

    conn = get_db_connection()

    try:
        faculty_members = conn.execute(
            """
            SELECT *
            FROM faculty
            ORDER BY name
            """
        ).fetchall()

    finally:
        conn.close()

    # This template matches the Faculty Management HTML
    # you shared in the previous message.
    return render_template(
        "faculty_management.html",
        faculty_members=faculty_members,
        username=session.get("username", "Admin"),
        role=session.get("role", "admin")
    )


# ============================================================
# FACULTY MANAGEMENT ACTIONS
# ============================================================

@app.route("/admin/faculty/add", methods=["POST"])
@role_required("admin")
def add_faculty():
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    department = request.form.get("department", "ECE").strip() or "ECE"
    password = request.form.get("password", "")

    if not name or not username or not password:
        flash("Name, username, and initial password are required.", "error")
        return redirect(url_for("admin_faculty"))

    if len(password) < 8:
        flash("Initial password must be at least 8 characters.", "error")
        return redirect(url_for("admin_faculty"))

    conn = get_db_connection()

    try:
        existing_user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        existing_faculty = conn.execute(
            "SELECT id FROM faculty WHERE username = ?",
            (username,)
        ).fetchone()

        if existing_user or existing_faculty:
            flash("That username is already in use.", "error")
            return redirect(url_for("admin_faculty"))

        conn.execute("BEGIN")

        conn.execute(
            """
            INSERT INTO faculty (name, username, password_hash, department, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (name, username, generate_password_hash(password), department)
        )

        conn.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, 'faculty')
            """,
            (username, generate_password_hash(password))
        )

        conn.commit()
        flash("Faculty member and login account created successfully.", "success")

    except sqlite3.Error:
        conn.rollback()
        app.logger.exception("Failed to add faculty")
        flash("Could not add faculty. Check the application log.", "error")

    finally:
        conn.close()

    return redirect(url_for("admin_faculty"))


# ============================================================
# EDIT FACULTY
# ============================================================

@app.route("/admin/faculty/edit/<int:faculty_id>", methods=["POST"])
@role_required("admin")
def edit_faculty(faculty_id):

    name = request.form.get("name", "").strip()
    department = request.form.get("department", "ECE").strip() or "ECE"

    if not name:
        flash("Faculty name is required.", "error")
        return redirect(url_for("admin_faculty"))

    conn = get_db_connection()

    try:

        result = conn.execute(
            """
            UPDATE faculty
            SET name = ?, department = ?
            WHERE id = ?
            """,
            (name, department, faculty_id)
        )

        if result.rowcount == 0:

            flash(
                "Faculty member not found.",
                "error"
            )

        else:

            conn.commit()

            flash(
                "Faculty details updated successfully.",
                "success"
            )

    except sqlite3.Error:

        conn.rollback()

        app.logger.exception(
            "Failed to edit faculty"
        )

        flash(
            "Could not update faculty details.",
            "error"
        )

    finally:

        conn.close()

    return redirect(url_for("admin_faculty"))


# ============================================================
# ACTIVATE / DEACTIVATE FACULTY
# ============================================================

@app.route(
    "/admin/faculty/status/<int:faculty_id>",
    methods=["POST"]
)
@role_required("admin")
def set_faculty_status(faculty_id):

    status = request.form.get("active", "")

    if status not in ("0", "1"):

        flash(
            "Invalid faculty status.",
            "error"
        )

        return redirect(
            url_for("admin_faculty")
        )

    conn = get_db_connection()

    try:

        faculty = conn.execute(
            """
            SELECT id, username, name, active
            FROM faculty
            WHERE id = ?
            """,
            (faculty_id,)
        ).fetchone()

        if not faculty:

            flash(
                "Faculty member not found.",
                "error"
            )

            return redirect(
                url_for("admin_faculty")
            )

        # ----------------------------------------------------
        # UPDATE STATUS
        # ----------------------------------------------------

        conn.execute(
            """
            UPDATE faculty
            SET active = ?
            WHERE id = ?
            """,
            (int(status), faculty_id)
        )

        conn.commit()

        if status == "0":

            flash(
                "Faculty deactivated. Existing login credentials "
                "were preserved.",
                "success"
            )

        else:

            flash(
                "Faculty reactivated successfully.",
                "success"
            )

    except sqlite3.Error:

        conn.rollback()

        app.logger.exception(
            "Failed to change faculty status"
        )

        flash(
            "Could not change faculty status.",
            "error"
        )

    finally:

        conn.close()

    return redirect(
        url_for("admin_faculty")
    )


# ============================================================
# PERMANENTLY DELETE INACTIVE FACULTY
# ============================================================

@app.route(
    "/admin/faculty/<int:faculty_id>/delete",
    methods=["POST"]
)
@role_required("admin")
def delete_faculty(faculty_id):

    conn = get_db_connection()

    try:

        # ----------------------------------------------------
        # GET FACULTY
        # ----------------------------------------------------

        faculty = conn.execute(
            """
            SELECT id, name, active
            FROM faculty
            WHERE id = ?
            """,
            (faculty_id,)
        ).fetchone()

        # ----------------------------------------------------
        # FACULTY NOT FOUND
        # ----------------------------------------------------

        if not faculty:

            flash(
                "Faculty member not found.",
                "error"
            )

            return redirect(
                url_for("admin_faculty")
            )

        # ----------------------------------------------------
        # ONLY INACTIVE FACULTY CAN BE DELETED
        # ----------------------------------------------------

        if faculty["active"]:

            flash(
                "Active faculty cannot be permanently deleted. "
                "Deactivate the faculty first.",
                "error"
            )

            return redirect(
                url_for("admin_faculty")
            )

        # ----------------------------------------------------
        # PERMANENT DATABASE DELETE
        # ----------------------------------------------------

        conn.execute(
            """
            DELETE FROM faculty
            WHERE id = ?
            """,
            (faculty_id,)
        )

        conn.commit()

        # ----------------------------------------------------
        # SUCCESS MESSAGE
        # ----------------------------------------------------

        flash(
            f"Faculty member '{faculty['name']}' "
            "removed permanently.",
            "success"
        )

    except sqlite3.Error as e:

        conn.rollback()

        app.logger.exception(
            "Failed to delete faculty"
        )

        flash(
            f"Unable to remove faculty member: {e}",
            "error"
        )

    finally:

        conn.close()

    # --------------------------------------------------------
    # RETURN TO FACULTY MANAGEMENT
    # --------------------------------------------------------

    return redirect(
        url_for("admin_faculty")
    )
# ============================================================
# ADMIN TIMETABLE
# ============================================================

from datetime import datetime


class TimetableConflictError(ValueError):
    """Raised when an active class overlaps another class."""


def normalize_day(value):
    value = (value or "").strip().lower()

    aliases = {
        "mon": "monday",
        "tue": "tuesday",
        "tues": "tuesday",
        "wed": "wednesday",
        "thu": "thursday",
        "thur": "thursday",
        "thurs": "thursday",
        "fri": "friday",
        "sat": "saturday",
        "sun": "sunday",
    }

    return aliases.get(value, value)


def get_timetable_conflicts(
    conn,
    day,
    start_time,
    end_time,
    class_name,
    exclude_id=None,
):
    """
    Return active classes that overlap on the same day
    and for the same class/section.

    Intervals that touch at the boundary are allowed:
    09:30-10:30 and 10:30-11:30 do not overlap.
    """

    query = """
        SELECT *
        FROM timetable
        WHERE lower(trim(day)) = ?
          AND lower(trim(COALESCE(class_name, ''))) = ?
          AND (active = 1 OR active IS NULL)
          AND start_time < ?
          AND end_time > ?
    """

    params = [
        normalize_day(day),
        (class_name or "").strip().lower(),
        end_time,
        start_time,
    ]

    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)

    query += " ORDER BY start_time, id"

    return conn.execute(query, params).fetchall()


def save_timetable_entry(conn, data, entry_id=None):
    """
    Validate and save a timetable entry.

    Raises TimetableConflictError if another active class
    overlaps for the same day and class/section.
    """

    day = (data.get("day") or "").strip().title()
    subject = (data.get("subject_name") or data.get("subject") or "").strip()
    course_code = (data.get("course_code") or "").strip()
    faculty_name = (data.get("faculty_name") or data.get("faculty") or "").strip()
    room_no = (data.get("room_no") or data.get("room") or "").strip()
    class_name = (data.get("class_name") or "").strip()
    start_time = (data.get("start_time") or "").strip()
    end_time = (data.get("end_time") or "").strip()

    allowed_days = {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }

    if day not in allowed_days:
        raise ValueError("Select a valid day.")

    if not subject:
        raise ValueError("Subject is required.")

    if not class_name:
        raise ValueError("Class/section is required.")

    if not start_time or not end_time:
        raise ValueError("Start time and end time are required.")

    try:
        start = datetime.strptime(start_time, "%H:%M")
        end = datetime.strptime(end_time, "%H:%M")
    except ValueError:
        raise ValueError("Enter times in HH:MM format.")

    if end <= start:
        raise ValueError("End time must be after start time.")

    # Prevent overlapping active classes for the same section.
    conflicts = get_timetable_conflicts(
        conn=conn,
        day=day,
        start_time=start_time,
        end_time=end_time,
        class_name=class_name,
        exclude_id=entry_id,
    )

    if conflicts:
        conflict = conflicts[0]

        raise TimetableConflictError(
            "This class overlaps an existing active class "
            f"(ID {conflict['id']}, {conflict['day']} "
            f"{conflict['start_time']}-{conflict['end_time']}, "
            f"{conflict['class_name']}). "
            "No changes were saved. Review the conflict before replacing it."
        )

    values = (
        subject,
        faculty_name or None,
        day,
        start_time,
        end_time,
        course_code or None,
        subject,
        faculty_name or None,
        room_no or None,
        class_name,
    )

    if entry_id is None:
        conn.execute(
            """
            INSERT INTO timetable (
                subject,
                faculty,
                day,
                start_time,
                end_time,
                course_code,
                subject_name,
                faculty_name,
                room_no,
                class_name,
                active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            values,
        )
    else:
        result = conn.execute(
            """
            UPDATE timetable
            SET subject = ?,
                faculty = ?,
                day = ?,
                start_time = ?,
                end_time = ?,
                course_code = ?,
                subject_name = ?,
                faculty_name = ?,
                room_no = ?,
                class_name = ?,
                active = 1
            WHERE id = ?
            """,
            values + (entry_id,),
        )

        if result.rowcount == 0:
            raise ValueError("Timetable entry not found.")


@app.route("/admin/timetable")
@role_required("admin")
def admin_timetable():
    conn = get_db_connection()

    try:
        timetable = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE active = 1 OR active IS NULL
            ORDER BY
                CASE lower(trim(day))
                    WHEN 'mon' THEN 1
                    WHEN 'monday' THEN 1
                    WHEN 'tue' THEN 2
                    WHEN 'tuesday' THEN 2
                    WHEN 'wed' THEN 3
                    WHEN 'wednesday' THEN 3
                    WHEN 'thu' THEN 4
                    WHEN 'thursday' THEN 4
                    WHEN 'fri' THEN 5
                    WHEN 'friday' THEN 5
                    WHEN 'sat' THEN 6
                    WHEN 'saturday' THEN 6
                    WHEN 'sun' THEN 7
                    WHEN 'sunday' THEN 7
                    ELSE 8
                END,
                start_time,
                id
            """
        ).fetchall()

    finally:
        conn.close()

    return render_template(
        "timetable.html",
        timetable=timetable,
    )



@app.route("/admin/timetable/add", methods=["POST"])
@role_required("admin")
def add_timetable_entry():
    conn = get_db_connection()

    try:
        # Validate and check for overlapping active classes.
        save_timetable_entry(conn, request.form)
        conn.commit()
        flash("Timetable class added successfully.", "success")

    except TimetableConflictError as exc:
        conn.rollback()

        # Find the conflicting active class for the confirmation prompt.
        day = (request.form.get("day") or "").strip()
        start_time = (request.form.get("start_time") or "").strip()
        end_time = (request.form.get("end_time") or "").strip()
        class_name = (request.form.get("class_name") or "").strip()

        conflicts = get_timetable_conflicts(
            conn,
            day,
            start_time,
            end_time,
            class_name,
        )

        timetable = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE active = 1 OR active IS NULL
            ORDER BY
                CASE lower(trim(day))
                    WHEN 'mon' THEN 1 WHEN 'monday' THEN 1
                    WHEN 'tue' THEN 2 WHEN 'tuesday' THEN 2
                    WHEN 'wed' THEN 3 WHEN 'wednesday' THEN 3
                    WHEN 'thu' THEN 4 WHEN 'thursday' THEN 4
                    WHEN 'fri' THEN 5 WHEN 'friday' THEN 5
                    WHEN 'sat' THEN 6 WHEN 'saturday' THEN 6
                    WHEN 'sun' THEN 7 WHEN 'sunday' THEN 7
                    ELSE 8
                END,
                start_time, id
            """
        ).fetchall()

        return render_template(
            "timetable.html",
            timetable=timetable,
            timetable_conflict=str(exc),
            conflict_entry=conflicts[0] if conflicts else None,
            pending_form=request.form,
        )

    except (ValueError, sqlite3.Error) as exc:
        conn.rollback()
        flash(str(exc), "error")

    finally:
        conn.close()

    return redirect(url_for("admin_timetable"))


@app.route("/admin/timetable/edit/<int:entry_id>", methods=["POST"])
@role_required("admin")
def edit_timetable_entry(entry_id):
    conn = get_db_connection()

    try:
        save_timetable_entry(
            conn,
            request.form,
            entry_id=entry_id,
        )
        conn.commit()
        flash("Timetable class updated successfully.", "success")

    except (ValueError, sqlite3.Error) as exc:
        conn.rollback()
        flash(str(exc), "error")

    finally:
        conn.close()

    return redirect(url_for("admin_timetable"))


@app.route("/admin/timetable/remove/<int:entry_id>", methods=["POST"])
@role_required("admin")
def remove_timetable_entry(entry_id):
    conn = get_db_connection()

    try:
        # Confirm that the timetable entry exists.
        entry = conn.execute(
            "SELECT id FROM timetable WHERE id = ?",
            (entry_id,),
        ).fetchone()

        if entry is None:
            flash("Timetable entry not found.", "error")
            return redirect(url_for("admin_timetable"))

        # Permanently delete this specific timetable entry.
        conn.execute(
            "DELETE FROM timetable WHERE id = ?",
            (entry_id,),
        )

        conn.commit()
        flash(
            f"Timetable entry {entry_id} was permanently removed.",
            "success",
        )

    except sqlite3.Error as exc:
        conn.rollback()
        flash(
            "Could not remove this entry. Related attendance records "
            "or database constraints may prevent deletion. "
            f"Database message: {exc}",
            "error",
        )

    finally:
        conn.close()

    return redirect(url_for("admin_timetable"))

@app.route(
    "/admin/timetable/replace/<int:entry_id>",
    methods=["POST"],
)
@role_required("admin")
def replace_timetable_entry(entry_id):
    """
    Explicitly replace one selected active timetable entry.

    The submitted replacement must not overlap any OTHER
    active entry for the same day and class/section.
    """

    conn = get_db_connection()

    try:
        conn.execute("BEGIN")

        existing = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE id = ?
              AND (active = 1 OR active IS NULL)
            """,
            (entry_id,),
        ).fetchone()

        if existing is None:
            raise ValueError(
                "The selected active timetable entry was not found."
            )

        # Check the submitted schedule against all active entries
        # except the specific entry the administrator chose to replace.
        conflicts = get_timetable_conflicts(
            conn=conn,
            day=request.form.get("day", ""),
            start_time=request.form.get("start_time", ""),
            end_time=request.form.get("end_time", ""),
            class_name=request.form.get("class_name", ""),
            exclude_id=entry_id,
        )

        if conflicts:
            conflict = conflicts[0]

            raise TimetableConflictError(
                "Replacement cancelled: the new schedule also overlaps "
                f"active timetable entry ID {conflict['id']}. "
                "No records were changed."
            )

        # Validate the submitted fields and insert the replacement.
        save_timetable_entry(conn, request.form)

        # Preserve the old row rather than deleting it.
        conn.execute(
            """
            UPDATE timetable
            SET active = 0
            WHERE id = ?
            """,
            (entry_id,),
        )

        conn.commit()

        flash(
            "Class replaced successfully. The previous record was preserved.",
            "success",
        )

    except (ValueError, sqlite3.Error) as exc:
        conn.rollback()
        flash(str(exc), "error")

    finally:
        conn.close()

    return redirect(url_for("admin_timetable"))


# ============================================================
# STUDENT DASHBOARD
# ============================================================

@app.route("/student")
@role_required("student")
def student_dashboard():

    from datetime import date, datetime, timedelta

    student = get_logged_in_student()

    if student is None:
        session.clear()
        return redirect(url_for("login"))

    # ========================================================
    # DATE
    # ========================================================

    today = date.today()
    now_time = datetime.now().time()

    selected_date = request.args.get(
        "date",
        today.isoformat()
    ).strip()

    try:
        selected_date_obj = date.fromisoformat(
            selected_date
        )
    except (ValueError, TypeError):

        selected_date = today.isoformat()
        selected_date_obj = today

    # IMPORTANT:
    # Always display selected date, not today's date.
    # Example:
    # 2026-10-21 -> 21/10/2026
    display_date = selected_date_obj.strftime(
        "%d/%m/%Y"
    )

    # ========================================================
    # ATTENDANCE PERIOD
    # ========================================================

    overall_start = date(2026, 7, 6)
    overall_end = date(2026, 11, 2)

    # Never count future classes in statistics.
    calculation_end = min(
        overall_end,
        today
    )

    # ========================================================
    # MONTHLY PERIOD
    # ========================================================

    month_start = selected_date_obj.replace(
        day=1
    )

    monthly_start = max(
        month_start,
        overall_start
    )

    monthly_end = min(
        selected_date_obj,
        overall_end,
        today
    )

    # ========================================================
    # OPEN DATABASE
    # ========================================================

    conn = get_db_connection()

    try:

        # ====================================================
        # LOAD TIMETABLE FOR REQUIRED DATE RANGE
        # ====================================================

        timetable_by_day = {}

        data_start = min(
            overall_start,
            monthly_start,
            selected_date_obj
        )

        data_end = max(
            calculation_end,
            monthly_end,
            selected_date_obj
        )

        current_day = data_start

        while current_day <= data_end:

            day_key = current_day.isoformat()

            aliases = {
                str(value).strip().lower()
                for value in get_day_aliases(day_key)
                if str(value).strip()
            }

            if aliases:

                placeholders = ",".join(
                    "?"
                    for _ in aliases
                )

                timetable_query = f"""
                    SELECT *
                    FROM timetable
                    WHERE lower(trim(day))
                        IN ({placeholders})
                    AND (
                        active = 1
                        OR active IS NULL
                    )
                    ORDER BY start_time
                """

                timetable_rows = conn.execute(
                    timetable_query,
                    tuple(sorted(aliases))
                ).fetchall()

                timetable_by_day[day_key] = [
                    dict(row)
                    for row in timetable_rows
                ]

            else:

                timetable_by_day[day_key] = []

            current_day += timedelta(days=1)

        # ====================================================
        # LOAD STUDENT ATTENDANCE
        # ====================================================

        attendance_rows = conn.execute(
            """
            SELECT
                rowid AS attendance_rowid,
                date,
                timetable_id,
                status,
                time
            FROM attendance
            WHERE student_id = ?
              AND date >= ?
              AND date <= ?
            ORDER BY
                date,
                timetable_id,
                rowid
            """,
            (
                student["id"],
                overall_start.isoformat(),
                overall_end.isoformat()
            )
        ).fetchall()

        attendance_by_key = {}

        # If duplicate attendance rows exist,
        # last row wins.
        for record in attendance_rows:

            key = (
                str(record["date"]),
                record["timetable_id"]
            )

            attendance_by_key[key] = dict(
                record
            )

        # ====================================================
        # HELPERS
        # ====================================================

        def is_present(status):

            return str(
                status or ""
            ).strip().lower() in (
                "present",
                "late",
                "p",
                "l"
            )

        # ----------------------------------------------------
        # PARSE TIME
        # ----------------------------------------------------

        def parse_time_value(value):

            if not value:
                return None

            value = str(
                value
            ).strip()

            formats = (
                "%H:%M:%S",
                "%H:%M",
                "%I:%M %p",
                "%I:%M:%S %p",
                "%I.%M %p",
                "%I.%M:%S %p"
            )

            for time_format in formats:

                try:

                    return datetime.strptime(
                        value,
                        time_format
                    ).time()

                except ValueError:

                    continue

            return None

        # ----------------------------------------------------
        # CHECK WHETHER CLASS HAS FINISHED
        # ----------------------------------------------------

        def class_has_finished(
            class_date,
            timetable_row
        ):

            # Previous dates are completed.
            if class_date < today:
                return True

            # Future dates are not completed.
            if class_date > today:
                return False

            # Today.
            end_value = str(
                timetable_row.get(
                    "end_time"
                )
                or ""
            ).strip()

            if not end_value:
                return False

            parsed_end = parse_time_value(
                end_value
            )

            if parsed_end is None:
                return False

            return parsed_end <= now_time

        # ====================================================
        # PREPARE DAILY CLASS
        # ====================================================

        def prepare_class(
            timetable_row,
            class_date
        ):

            item = dict(
                timetable_row
            )

            timetable_id = item.get(
                "id"
            )

            key = (
                class_date.isoformat(),
                timetable_id
            )

            record = attendance_by_key.get(
                key
            )

            # ------------------------------------------------
            # STATUS
            # ------------------------------------------------

            if record is not None:

                raw_status = str(
                    record.get("status")
                    or ""
                ).strip().lower()

                if raw_status in (
                    "present",
                    "p"
                ):

                    item["status"] = "Present"

                elif raw_status in (
                    "late",
                    "l"
                ):

                    item["status"] = "Late"

                elif raw_status in (
                    "absent",
                    "a"
                ):

                    item["status"] = "Absent"

                else:

                    item["status"] = (
                        record.get("status")
                        or "Not marked"
                    )

                item["time"] = (
                    record.get("time")
                    or ""
                )

            else:

                # ------------------------------------------------
                # VERY IMPORTANT:
                #
                # Today + ongoing/not started = Not marked
                # Today + completed = Absent
                # Past = Absent
                # Future = Not marked
                # ------------------------------------------------

                if class_has_finished(
                    class_date,
                    item
                ):

                    item["status"] = "Absent"

                else:

                    item["status"] = "Not marked"

                item["time"] = ""

            # ------------------------------------------------
            # SUBJECT
            # ------------------------------------------------

            item["subject"] = (
                item.get("subject_name")
                or item.get("subject")
                or item.get("course_name")
                or item.get("course_code")
                or item.get("class_name")
                or "Class"
            )

            # ------------------------------------------------
            # CLASS NAME
            # ------------------------------------------------

            item["class_name"] = (
                item.get("class_name")
                or item.get("subject_name")
                or item.get("subject")
                or item.get("course_code")
                or "Class"
            )

            # ------------------------------------------------
            # FACULTY
            # ------------------------------------------------

            item["faculty_name"] = (
                item.get("faculty_name")
                or item.get("faculty")
                or "-"
            )

            # ------------------------------------------------
            # ROOM
            # ------------------------------------------------

            item["room"] = (
                item.get("room")
                or item.get("room_no")
                or item.get("classroom")
                or "-"
            )

            # ------------------------------------------------
            # DISPLAY DATE
            # ------------------------------------------------

            item["attendance_date"] = (
                class_date.isoformat()
            )

            item["display_date"] = (
                class_date.strftime(
                    "%d/%m/%Y"
                )
            )

            return item

        # ====================================================
        # CALCULATE ATTENDANCE FOR PERIOD
        # ====================================================

        def calculate_period(
            period_start,
            period_end
        ):

            attended = 0
            absent = 0
            eligible_total = 0

            if (
                period_start is None
                or period_end is None
                or period_end < period_start
            ):

                return {
                    "present": 0,
                    "absent": 0,
                    "total": 0,
                    "percentage": 0.0
                }

            current = period_start

            while current <= period_end:

                day_key = current.isoformat()

                scheduled_classes = (
                    timetable_by_day.get(
                        day_key,
                        []
                    )
                )

                for timetable_row in scheduled_classes:

                    timetable_id = (
                        timetable_row.get("id")
                    )

                    record = attendance_by_key.get(
                        (
                            day_key,
                            timetable_id
                        )
                    )

                    # ----------------------------------------
                    # ATTENDANCE EXISTS
                    # ----------------------------------------

                    if record is not None:

                        eligible_total += 1

                        if is_present(
                            record.get("status")
                        ):

                            attended += 1

                        else:

                            absent += 1

                    # ----------------------------------------
                    # NO ATTENDANCE RECORD
                    # ----------------------------------------

                    elif class_has_finished(
                        current,
                        timetable_row
                    ):

                        eligible_total += 1

                        absent += 1

                current += timedelta(
                    days=1
                )

            percentage = (
                round(
                    attended * 100.0
                    / eligible_total,
                    1
                )
                if eligible_total
                else 0.0
            )

            return {
                "present": attended,
                "absent": absent,
                "total": eligible_total,
                "percentage": percentage
            }

        # ====================================================
        # DAILY CLASSES FOR SELECTED DATE
        # ====================================================

        classes = [

            prepare_class(
                row,
                selected_date_obj
            )

            for row in timetable_by_day.get(
                selected_date,
                []
            )

        ]

        # ====================================================
        # DAILY STATISTICS
        # ====================================================

        daily_stats = calculate_period(
            selected_date_obj,
            selected_date_obj
        )

        total_classes = len(
            classes
        )

        present_count = daily_stats[
            "present"
        ]

        absent_count = daily_stats[
            "absent"
        ]

        day_eligible_total = daily_stats[
            "total"
        ]

        day_percentage = daily_stats[
            "percentage"
        ]

        # ====================================================
        # OVERALL ATTENDANCE
        # ====================================================

        overall_stats = calculate_period(
            overall_start,
            calculation_end
        )

        overall_present = overall_stats[
            "present"
        ]

        overall_absent = overall_stats[
            "absent"
        ]

        overall_total = overall_stats[
            "total"
        ]

        overall_percentage = overall_stats[
            "percentage"
        ]

        overall_warning = (
            overall_total == 0
            or overall_percentage < 75
        )

        # ====================================================
        # MONTHLY ATTENDANCE
        # ====================================================

        monthly_stats = calculate_period(
            monthly_start,
            monthly_end
        )

        monthly_present = monthly_stats[
            "present"
        ]

        monthly_absent = monthly_stats[
            "absent"
        ]

        monthly_total = monthly_stats[
            "total"
        ]

        monthly_percentage = monthly_stats[
            "percentage"
        ]

        monthly_warning = (
            monthly_total == 0
            or monthly_percentage < 75
        )

        # ====================================================
        # DEBUG
        # ====================================================

        print(
            "\n===== STUDENT DASHBOARD ====="
        )

        print(
            "Student ID:",
            student["id"]
        )

        print(
            "Selected date:",
            selected_date
        )

        print(
            "Display date:",
            display_date
        )

        print(
            "Classes:",
            len(classes)
        )

        print(
            "Present:",
            present_count
        )

        print(
            "Absent:",
            absent_count
        )

        print(
            "Not marked:",
            sum(
                1
                for item in classes
                if str(
                    item.get("status")
                    or ""
                ).lower()
                == "not marked"
            )
        )

        print(
            "============================\n"
        )

        # ====================================================
        # RENDER
        # ====================================================

        return render_template(

            "student_dashboard.html",

            student=student,

            # ------------------------------------------------
            # SELECTED DATE
            # ------------------------------------------------

            selected_date=selected_date,

            selected_date_obj=selected_date_obj,

            display_date=display_date,

            # ------------------------------------------------
            # DAILY CLASSES
            # ------------------------------------------------

            classes=classes,

            total_classes=total_classes,

            present_count=present_count,

            absent_count=absent_count,

            day_eligible_total=day_eligible_total,

            day_percentage=day_percentage,

            # ------------------------------------------------
            # OVERALL
            # ------------------------------------------------

            overall_start=(
                overall_start.isoformat()
            ),

            overall_end=(
                overall_end.isoformat()
            ),

            overall_start_date=(
                overall_start.isoformat()
            ),

            overall_end_date=(
                overall_end.isoformat()
            ),

            overall_present=overall_present,

            overall_absent=overall_absent,

            overall_total=overall_total,

            overall_percentage=overall_percentage,

            overall_warning=overall_warning,

            # ------------------------------------------------
            # MONTHLY
            # ------------------------------------------------

            monthly_present=monthly_present,

            monthly_absent=monthly_absent,

            monthly_total=monthly_total,

            monthly_percentage=monthly_percentage,

            monthly_warning=monthly_warning,

            active_page="dashboard"
        )

    finally:

        conn.close()


# ============================================================
# FACULTY HELPERS
# ============================================================

def faculty_identity():
    faculty = get_logged_in_faculty()

    if faculty is None:
        return None, "", session.get("username", "")

    return (
        faculty,
        str(faculty["name"] or "").strip(),
        str(faculty["username"] or "").strip()
    )


def faculty_matches_timetable(timetable_row, faculty_name, username):
    keys = timetable_row.keys()
    assigned_values = []

    for field in ("faculty_name", "faculty"):
        if field in keys:
            assigned_values.append(
                str(timetable_row[field] or "").strip().casefold()
            )

    accepted = {
        str(faculty_name or "").strip().casefold(),
        str(username or "").strip().casefold()
    }
    accepted.discard("")

    return any(
        assigned and assigned in accepted
        for assigned in assigned_values
    )


def timetable_subject(row):
    keys = row.keys()

    for field in (
        "subject_name",
        "subject",
        "course_code",
        "class_name"
    ):
        if field in keys and row[field]:
            return row[field]

    return "Class"


def timetable_room(row):
    keys = row.keys()

    for field in ("room_no", "room", "classroom"):
        if field in keys and row[field]:
            return row[field]

    return "-"


def all_timetable_rows(conn):
    """Read timetable rows without assuming every DB uses identical columns."""
    try:
        return conn.execute(
            """
            SELECT *
            FROM timetable
            ORDER BY
                CASE lower(trim(day))
                    WHEN 'mon' THEN 1 WHEN 'monday' THEN 1
                    WHEN 'tue' THEN 2 WHEN 'tues' THEN 2 WHEN 'tuesday' THEN 2
                    WHEN 'wed' THEN 3 WHEN 'wednesday' THEN 3
                    WHEN 'thu' THEN 4 WHEN 'thur' THEN 4 WHEN 'thurs' THEN 4 WHEN 'thursday' THEN 4
                    WHEN 'fri' THEN 5 WHEN 'friday' THEN 5
                    WHEN 'sat' THEN 6 WHEN 'saturday' THEN 6
                    WHEN 'sun' THEN 7 WHEN 'sunday' THEN 7
                    ELSE 8
                END,
                start_time
            """
        ).fetchall()
    except sqlite3.OperationalError:
        # Fallback for schemas using weekday/from_time or another alias.
        return conn.execute("SELECT * FROM timetable").fetchall()


def scheduled_classes_for_date(conn, selected_date):
    try:
        selected_day = (
            date.fromisoformat(selected_date)
            .strftime("%A")
            .casefold()
        )
    except (ValueError, TypeError):
        return []

    day_aliases = {
        "monday": ["monday", "mon"],
        "tuesday": ["tuesday", "tue", "tues"],
        "wednesday": ["wednesday", "wed"],
        "thursday": ["thursday", "thu", "thur", "thurs"],
        "friday": ["friday", "fri"],
        "saturday": ["saturday", "sat"],
        "sunday": ["sunday", "sun"],
    }

    aliases = day_aliases.get(selected_day, [])

    if not aliases:
        return []

    placeholders = ",".join("?" for _ in aliases)

    return conn.execute(
        f"""
        SELECT *
        FROM timetable
        WHERE lower(trim(day)) IN ({placeholders})
          AND (active = 1 OR active IS NULL)
        ORDER BY start_time
        """,
        tuple(aliases)
    ).fetchall()





# ============================================================
# STUDENT TIMETABLE
# ============================================================

@app.route("/student/timetable")
@role_required("student")
def student_timetable():
    student = get_logged_in_student()

    if student is None:
        session.clear()
        return redirect(url_for("login"))

    # Monday to Friday only
    day_names = [
        ("Monday", ["mon", "monday"]),
        ("Tuesday", ["tue", "tuesday"]),
        ("Wednesday", ["wed", "wednesday"]),
        ("Thursday", ["thu", "thursday"]),
        ("Friday", ["fri", "friday"]),
    ]

    # Internal slot times stay in 24-hour format for matching.
    slots = [
        ("09:30", "10:30"),
        ("10:30", "11:30"),
        ("11:30", "12:30"),
        ("13:30", "14:30"),
        ("14:30", "15:30"),
        ("15:30", "16:30"),
    ]

    def to_minutes(value):
        """Convert a database time to minutes after midnight."""
        if not value:
            return None

        value = str(value).strip()

        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p"):
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.hour * 60 + parsed.minute
            except ValueError:
                continue

        return None

    def format_time_12h(value):
        """Display a database time in 12-hour format."""
        if not value:
            return "-"

        value = str(value).strip()

        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p"):
            try:
                return datetime.strptime(value, fmt).strftime(
                    "%I:%M %p"
                ).lstrip("0")
            except ValueError:
                continue

        return value

    today_key = date.today().strftime("%A").lower()
    conn = get_db_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE (active = 1 OR active IS NULL)
            ORDER BY start_time
            """
        ).fetchall()

        timetable = []

        for row in rows:
            item = dict(row)

            # Keep the original values for correct grid placement.
            item["start_time_raw"] = item.get("start_time")
            item["end_time_raw"] = item.get("end_time")

            item["start_minutes"] = to_minutes(
                item["start_time_raw"]
            )
            item["end_minutes"] = to_minutes(
                item["end_time_raw"]
            )

            item["display_start_time"] = format_time_12h(
                item["start_time_raw"]
            )
            item["display_end_time"] = format_time_12h(
                item["end_time_raw"]
            )

            item["display_subject"] = (
                item.get("subject_name")
                or item.get("subject")
                or item.get("class_name")
                or item.get("course_code")
                or "Class"
            )

            item["display_faculty"] = (
                item.get("faculty_name")
                or item.get("faculty")
                or "-"
            )

            item["display_room"] = (
                item.get("room")
                or item.get("room_no")
                or item.get("classroom")
                or "-"
            )

            timetable.append(item)

        weekly_rows = []

        for day_name, aliases in day_names:
            day_classes = [
                item for item in timetable
                if str(item.get("day") or "").strip().lower()
                in aliases
            ]

            # Build one grid cell per hour, except lunch.
            cells = []
            occupied = set()

            for slot_index, (slot_start, slot_end) in enumerate(slots):
                slot_start_min = to_minutes(slot_start)
                slot_end_min = to_minutes(slot_end)

                # Insert lunch after the third morning slot.
                if slot_index == 3:
                    cells.append({
                        "is_lunch": True,
                        "skip": False,
                        "item": None,
                        "colspan": 1,
                    })

                if slot_index in occupied:
                    cells.append({
                        "skip": True,
                        "is_lunch": False,
                        "item": None,
                        "colspan": 1,
                    })
                    continue

                # Find a class that starts in this slot.
                matching = None

                for item in day_classes:
                    if (
                        item["start_minutes"] is not None
                        and item["end_minutes"] is not None
                        and item["start_minutes"] == slot_start_min
                        and item["end_minutes"] > slot_start_min
                    ):
                        matching = item
                        break

                if matching is None:
                    # Avoid creating an empty cell for a class
                    # that continues from the previous slot.
                    continuing = any(
                        item["start_minutes"] is not None
                        and item["end_minutes"] is not None
                        and item["start_minutes"] < slot_start_min
                        and item["end_minutes"] > slot_start_min
                        for item in day_classes
                    )

                    cells.append({
                        "skip": continuing,
                        "is_lunch": False,
                        "item": None,
                        "colspan": 1,
                    })
                    continue

                class_end = matching["end_minutes"]

                # Find the number of hourly slots covered by
                # the class. Do not merge across the lunch break.
                span = 1
                current_index = slot_index

                while current_index + 1 < len(slots):
                    next_index = current_index + 1

                    # The transition from 12:30 to 13:30 is lunch.
                    if next_index == 3:
                        break

                    next_start, next_end = slots[next_index]
                    next_start_min = to_minutes(next_start)
                    next_end_min = to_minutes(next_end)

                    if (
                        next_start_min is None
                        or next_end_min is None
                        or class_end <= next_start_min
                    ):
                        break

                    span += 1
                    current_index = next_index

                    if class_end <= next_end_min:
                        break

                # Don't let a class extend beyond the displayed grid.
                if slot_index < 3:
                    span = min(span, 3 - slot_index)
                else:
                    span = min(span, 6 - slot_index)

                for covered_index in range(
                    slot_index + 1,
                    slot_index + span
                ):
                    occupied.add(covered_index)

                cells.append({
                    "skip": False,
                    "is_lunch": False,
                    "item": matching,
                    "colspan": span,
                })

            weekly_rows.append({
                "name": day_name,
                "is_today": day_name.lower() == today_key,
                "cells": cells,
            })

        return render_template(
            "student_timetable.html",
            student=student,
            timetable=timetable,
            weekly_rows=weekly_rows,
        )

    finally:
        conn.close()

# ============================================================
# FACULTY DASHBOARD
# ============================================================

@app.route("/faculty")
@app.route("/faculty/dashboard")
@role_required("faculty")
def faculty_dashboard():

    faculty, faculty_name, username = faculty_identity()

    if faculty is None:
        flash("Faculty account not found.", "error")
        return redirect(url_for("logout"))

    today = date.today()
    today_iso = today.isoformat()
    now = datetime.now()

    conn = get_db_connection()

    try:

        # ========================================================
        # GET ALL TIMETABLE ROWS
        # ========================================================

        all_rows = all_timetable_rows(conn)

        # ========================================================
        # ONLY LOGGED-IN FACULTY CLASSES
        # ========================================================

        my_classes = [
            dict(row)
            for row in all_rows
            if faculty_matches_timetable(
                row,
                faculty_name,
                username
            )
        ]

        # ========================================================
        # NORMALIZE CLASS DATA
        # ========================================================

        def prepare_class(item):

            item["subject_name"] = (
                item.get("subject_name")
                or item.get("subject")
                or item.get("course_code")
                or item.get("class_name")
                or "Class"
            )

            item["room_no"] = (
                item.get("room_no")
                or item.get("room")
                or item.get("classroom")
                or "-"
            )

            item["course_code"] = (
                item.get("course_code")
                or "-"
            )

            item["faculty_name"] = (
                item.get("faculty_name")
                or item.get("faculty")
                or faculty_name
                or username
                or "-"
            )

            item["class_section"] = (
                item.get("class_section")
                or item.get("section")
                or item.get("class_name")
                or item.get("branch")
                or "-"
            )

            return item

        for item in my_classes:
            prepare_class(item)

        # ========================================================
        # TODAY'S CLASSES
        # ========================================================

        today_aliases = {
            str(value).strip().lower()
            for value in get_day_aliases(today_iso)
        }

        today_classes = [
            item.copy()
            for item in my_classes
            if str(item.get("active",1)).strip() == "1"
            and str(item.get("day") or "").strip().lower() in today_aliases
        ]

        today_classes.sort(
            key=lambda item: (
                _time_value(
                    item.get("start_time")
                )
                or datetime.strptime(
                    "23:59",
                    "%H:%M"
                ).time()
            )
        )

        # ========================================================
        # NEXT CLASS
        # ========================================================

        next_class = None

        for day_offset in range(0, 15):

            candidate_date = (
                today + timedelta(days=day_offset)
            )

            candidate_iso = candidate_date.isoformat()

            day_aliases = {
                str(value).strip().lower()
                for value in get_day_aliases(
                    candidate_iso
                )
            }

            day_classes = [
                item.copy()
                for item in my_classes
                if str(
                    item.get("day") or ""
                ).strip().lower()
                in day_aliases
            ]

            day_classes.sort(
                key=lambda item: (
                    _time_value(
                        item.get("start_time")
                    )
                    or datetime.strptime(
                        "23:59",
                        "%H:%M"
                    ).time()
                )
            )

            for item in day_classes:

                start_time = _time_value(
                    item.get("start_time")
                )

                if start_time is None:
                    continue

                class_datetime = datetime.combine(
                    candidate_date,
                    start_time
                )

                if class_datetime > now:

                    next_class = prepare_class(
                        item.copy()
                    )

                    # Only:
                    # Friday, 23 Oct 2026
                    #
                    # NOT:
                    # Friday, 23 Oct 2026 — Friday

                    next_class["display_date"] = (
                        "Today"
                        if day_offset == 0
                        else candidate_date.strftime(
                            "%A, %d %b %Y"
                        )
                    )

                    break

            if next_class:
                break

        # ========================================================
        # FACULTY TIMETABLE IDS
        # ========================================================

        my_timetable_ids = [
            item["id"]
            for item in my_classes
            if item.get("id") is not None
        ]

        timetable_count = len(
            my_classes
        )

        # ========================================================
        # TODAY'S PRESENT + LATE COUNT
        # ========================================================

        today_present = 0

        if my_timetable_ids:

            placeholders = ",".join(
                "?"
                for _ in my_timetable_ids
            )

            today_present = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM attendance AS a

                WHERE a.date = ?

                  AND lower(
                        trim(
                            coalesce(
                                a.status,
                                ''
                            )
                        )
                      ) IN (
                          'present',
                          'late'
                      )

                  AND a.timetable_id IN (
                      {placeholders}
                  )
                """,
                (
                    today_iso,
                    *my_timetable_ids
                )
            ).fetchone()[0]

        # ========================================================
        # DASHBOARD
        #
        # DO NOT LOAD ATTENDANCE TABLE HERE.
        #
        # "View Today's Attendance" opens:
        #
        # /faculty/today-attendance
        # ========================================================

        return render_template(
            "faculty_dashboard.html",

            faculty=faculty,
            faculty_name=faculty_name,
            username=username,

            today_date=today_iso,

            today_classes=today_classes,

            next_class=next_class,

            timetable_count=timetable_count,

            today_present=today_present
        )

    finally:
        conn.close()


# ============================================================
# FACULTY TIMETABLE
# ============================================================

@app.route("/faculty/timetable")
@role_required("faculty")
def faculty_timetable():

    faculty, faculty_name, username = faculty_identity()

    if faculty is None:
        flash(
            "Faculty account not found.",
            "error"
        )
        return redirect(
            url_for("logout")
        )

    conn = get_db_connection()

    try:

        rows = all_timetable_rows(conn)

        timetable_entries = [
            dict(row)
            for row in rows
            if faculty_matches_timetable(
                row,
                faculty_name,
                username
            )
        ]

        for item in timetable_entries:

            item["subject_name"] = (
                item.get("subject_name")
                or item.get("subject")
                or item.get("course_code")
                or "Class"
            )

            item["room_no"] = (
                item.get("room_no")
                or item.get("room")
                or "-"
            )

        return render_template(
            "faculty_timetable.html",

            faculty=faculty,

            timetable_entries=timetable_entries,

            timetable=timetable_entries
        )

    finally:
        conn.close()


# ============================================================
# FACULTY TODAY'S ATTENDANCE
# ============================================================

@app.route("/faculty/today-attendance")
@role_required("faculty")
def faculty_today_attendance_page():

    faculty, faculty_name, username = faculty_identity()

    if faculty is None:
        flash("Faculty account not found.", "error")
        return redirect(url_for("logout"))

    today = date.today()
    today_iso = today.isoformat()

    selected_timetable_id = request.args.get(
        "timetable_id",
        ""
    ).strip()

    conn = get_db_connection()

    try:

        # ====================================================
        # GET THIS FACULTY'S TIMETABLE
        # ====================================================

        all_rows = all_timetable_rows(conn)

        my_classes = [
            dict(row)
            for row in all_rows
            if faculty_matches_timetable(
                row,
                faculty_name,
                username
            )
        ]

        # ====================================================
        # GET TODAY'S CLASSES ONLY
        # ====================================================

        today_aliases = {
            str(value).strip().lower()
            for value in get_day_aliases(today_iso)
        }

        today_classes = [
            item.copy()
            for item in my_classes
            if str(item.get("active", 1)).strip() == "1"
            and str(item.get("day") or "").strip().lower()
            in today_aliases
        ]

        # ====================================================
        # NORMALIZE CLASS INFORMATION
        # ====================================================

        for item in today_classes:

            item["subject_name"] = (
                item.get("subject_name")
                or item.get("subject")
                or item.get("course_code")
                or item.get("class_name")
                or "Class"
            )

            item["course_code"] = (
                item.get("course_code")
                or "-"
            )

            item["room_no"] = (
                item.get("room_no")
                or item.get("room")
                or item.get("classroom")
                or "-"
            )

            item["faculty_display"] = (
                item.get("faculty_name")
                or item.get("faculty")
                or faculty_name
                or username
                or "Faculty"
            )

            item["class_section"] = (
                item.get("class_section")
                or item.get("section")
                or item.get("class_name")
                or "-"
            )

        # ====================================================
        # SORT TODAY'S CLASSES BY START TIME
        # ====================================================

        today_classes.sort(
            key=lambda item: (
                _time_value(
                    item.get("start_time")
                )
                or datetime.strptime(
                    "23:59",
                    "%H:%M"
                ).time()
            )
        )

        # ====================================================
        # NO CLASSES TODAY
        # ====================================================

        if not today_classes:

            return render_template(
                "faculty_today_attendance.html",

                faculty=faculty,
                faculty_name=faculty_name,
                username=username,

                today_date=today_iso,

                today_classes=[],

                selected_timetable_id="",

                selected_class=None,

                attendance_records=[],

                subject="",
                course_code="",
                faculty_display=(
                    faculty_name
                    or username
                    or "Faculty"
                ),
                class_section="",
                start_time="",
                end_time="",
                room="-",

                total_students=0,
                present_count=0,
                late_count=0,
                absent_count=0,
                unmarked_count=0,
                marked_count=0,

                finalized=False
            )

        # ====================================================
        # SELECTED CLASS
        # ====================================================

        selected_class = None

        if selected_timetable_id:

            try:
                selected_id = int(
                    selected_timetable_id
                )
            except (
                ValueError,
                TypeError
            ):
                selected_id = None

            if selected_id is not None:

                selected_class = next(
                    (
                        item
                        for item in today_classes
                        if str(
                            item.get("id")
                        ) == str(selected_id)
                    ),
                    None
                )

        # ====================================================
        # IF ONLY ONE CLASS EXISTS,
        # AUTOMATICALLY SELECT IT
        # ====================================================

        if (
            selected_class is None
            and len(today_classes) == 1
        ):

            selected_class = today_classes[0]

            selected_timetable_id = str(
                selected_class["id"]
            )

        # ====================================================
        # ATTENDANCE DATA
        # ====================================================

        attendance_records = []

        if selected_class:

            attendance_records = _class_attendance_rows(
                conn,
                selected_class,
                today_iso
            )

        # ====================================================
        # NORMALIZE ATTENDANCE RECORDS
        # ====================================================

        for index, record in enumerate(
            attendance_records,
            start=1
        ):

            if not record.get("no"):
                record["no"] = index

            record["status"] = (
                record.get("status")
                or "Unmarked"
            )

        # ====================================================
        # ATTENDANCE COUNTS
        # ====================================================

        present_count = sum(
            1
            for row in attendance_records
            if str(
                row.get("status") or ""
            ).strip().lower()
            in ("present", "late")
        )

        late_count = sum(
            1
            for row in attendance_records
            if str(
                row.get("status") or ""
            ).strip().lower()
            == "late"
        )

        absent_count = sum(
            1
            for row in attendance_records
            if str(
                row.get("status") or ""
            ).strip().lower()
            == "absent"
        )

        total_students = len(
            attendance_records
        )

        # ====================================================
        # IMPORTANT
        #
        # Do NOT calculate unmarked as:
        #
        # total_students - marked_count
        #
        # if marked_count is coming from a different
        # attendance query.
        #
        # Instead calculate directly from the rows.
        # ====================================================

        marked_count = sum(
            1
            for row in attendance_records
            if str(
                row.get("status") or ""
            ).strip().lower()
            in (
                "present",
                "late",
                "absent"
            )
        )

        unmarked_count = max(
            0,
            total_students - marked_count
        )

        # A class is not finalized merely because every student has been
        # recognized. It can only be considered finalized after scheduled end.
        class_end_passed = False
        if selected_class is not None:
            scheduled_end = _time_value(
                selected_class.get("end_time")
            )
            class_end_passed = bool(
                scheduled_end is not None
                and datetime.now().time() >= scheduled_end
            )

        finalized = (
            class_end_passed
            and total_students > 0
            and unmarked_count == 0
        )

        # ====================================================
        # CLASS DISPLAY INFORMATION
        # ====================================================

        subject = ""
        course_code = ""
        faculty_display = (
            faculty_name
            or username
            or "Faculty"
        )
        class_section = ""
        start_time = ""
        end_time = ""
        room = "-"

        if selected_class:

            subject = (
                selected_class.get(
                    "subject_name"
                )
                or "Class"
            )

            course_code = (
                selected_class.get(
                    "course_code"
                )
                or "-"
            )

            faculty_display = (
                selected_class.get(
                    "faculty_display"
                )
                or faculty_display
            )

            class_section = (
                selected_class.get(
                    "class_section"
                )
                or "-"
            )

            start_time = (
                selected_class.get(
                    "start_time"
                )
                or ""
            )

            end_time = (
                selected_class.get(
                    "end_time"
                )
                or ""
            )

            room = (
                selected_class.get(
                    "room_no"
                )
                or "-"
            )

        # ====================================================
        # RENDER
        # ====================================================

        return render_template(
            "faculty_today_attendance.html",

            faculty=faculty,
            faculty_name=faculty_name,
            username=username,

            today_date=today_iso,

            today_classes=today_classes,

            selected_timetable_id=(
                selected_timetable_id
            ),

            selected_class=selected_class,

            attendance_records=(
                attendance_records
            ),

            subject=subject,

            course_code=course_code,

            faculty_display=faculty_display,

            class_section=class_section,

            start_time=start_time,

            end_time=end_time,

            room=room,

            total_students=total_students,

            present_count=present_count,

            late_count=late_count,

            absent_count=absent_count,

            unmarked_count=unmarked_count,

            marked_count=marked_count,

            finalized=finalized
        )

    finally:
        conn.close()
# ============================================================
# FACULTY DATE-WISE ATTENDANCE
# ============================================================

@app.route("/faculty/attendance")
@role_required("faculty")
def faculty_attendance():

    faculty, faculty_name, username = faculty_identity()

    if faculty is None:
        flash(
            "Faculty account not found.",
            "error"
        )
        return redirect(url_for("logout"))

    # ============================================================
    # SELECTED DATE
    # Internal/database format MUST remain YYYY-MM-DD
    # ============================================================

    selected_date = request.args.get(
        "date",
        date.today().isoformat()
    ).strip()

    try:
        date.fromisoformat(selected_date)
    except (ValueError, TypeError):
        selected_date = date.today().isoformat()

    # ============================================================
    # DISPLAY DATE
    # DD/MM/YYYY
    # ============================================================

    try:
        display_date = datetime.strptime(
            selected_date,
            "%Y-%m-%d"
        ).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        display_date = selected_date

    # ============================================================
    # SELECTED TIMETABLE
    # ============================================================

    selected_timetable_id = request.args.get(
        "timetable_id",
        ""
    ).strip()

    conn = get_db_connection()

    try:

        # ========================================================
        # GET CLASSES FOR SELECTED DATE
        # ========================================================

        scheduled = scheduled_classes_for_date(
            conn,
            selected_date
        )

        classes = [
            dict(row)
            for row in scheduled
        ]

        # ========================================================
        # NORMALIZE CLASS DATA
        # ========================================================

        for item in classes:

            item["subject_name"] = (
                item.get("subject_name")
                or item.get("subject")
                or item.get("course_code")
                or item.get("class_name")
                or "Class"
            )

            item["room_no"] = (
                item.get("room_no")
                or item.get("room")
                or item.get("classroom")
                or "-"
            )

            item["faculty_name"] = (
                item.get("faculty_name")
                or item.get("faculty")
                or faculty_name
                or "-"
            )

            item["class_name"] = (
                item.get("class_name")
                or item.get("class_section")
                or item.get("section")
                or "-"
            )

        # ========================================================
        # FIND SELECTED CLASS
        # ========================================================

        selected_class = None

        if selected_timetable_id:

            try:
                class_id = int(selected_timetable_id)
            except (ValueError, TypeError):
                class_id = None

            if class_id is not None:

                selected_class = next(
                    (
                        item
                        for item in classes
                        if str(item.get("id")) == str(class_id)
                    ),
                    None
                )

        # ========================================================
        # ATTENDANCE RECORDS
        # ========================================================

        attendance_records = []

        if selected_class is not None:

            attendance_records = _class_attendance_rows(
                conn,
                selected_class,
                selected_date
            )

        # ========================================================
        # DETERMINE CLASS STATE
        #
        # PAST:
        #     Only Present / Absent
        #
        # TODAY + ONGOING:
        #     Present / Absent / Unmarked
        #
        # FUTURE:
        #     Only Unmarked
        # ========================================================

        today = date.today()

        class_state = "future"

        if selected_class is not None:

            if selected_date < today.isoformat():

                # ------------------------------------------------
                # PAST CLASS
                # ------------------------------------------------

                class_state = "past"

            elif selected_date > today.isoformat():

                # ------------------------------------------------
                # FUTURE CLASS
                # ------------------------------------------------

                class_state = "future"

            else:

                # ------------------------------------------------
                # TODAY
                # ------------------------------------------------

                current_time = datetime.now().time()

                start_time_value = (
                    selected_class.get("start_time")
                )

                end_time_value = (
                    selected_class.get("end_time")
                )

                def parse_time_value(value):

                    if value is None:
                        return None

                    value = str(value).strip()

                    if not value:
                        return None

                    formats = (
                        "%H:%M:%S",
                        "%H:%M",
                        "%I:%M %p",
                        "%I:%M:%S %p"
                    )

                    for fmt in formats:

                        try:
                            return datetime.strptime(
                                value,
                                fmt
                            ).time()
                        except ValueError:
                            continue

                    return None

                start_time = parse_time_value(
                    start_time_value
                )

                end_time = parse_time_value(
                    end_time_value
                )

                if start_time is None:

                    # If start time cannot be determined,
                    # treat today's class as ongoing so that
                    # Unmarked is available.

                    class_state = "ongoing"

                elif current_time < start_time:

                    # ------------------------------------------------
                    # TODAY BUT NOT STARTED YET
                    # ------------------------------------------------

                    class_state = "future"

                elif end_time is not None and current_time > end_time:

                    # ------------------------------------------------
                    # TODAY BUT CLASS IS FINISHED
                    # ------------------------------------------------

                    class_state = "past"

                else:

                    # ------------------------------------------------
                    # TODAY AND CLASS IS CURRENTLY RUNNING
                    # ------------------------------------------------

                    class_state = "ongoing"

        # ========================================================
        # NORMALIZE ATTENDANCE STATUS
        # ========================================================

        normalized_records = []

        for row in attendance_records:

            record = dict(row)

            raw_status = str(
                record.get("status")
                or ""
            ).strip().lower()

            # ----------------------------------------------------
            # PAST CLASS
            #
            # If attendance exists:
            #     present -> Present
            #     late    -> Present
            #     absent  -> Absent
            #
            # Missing status is also treated as Absent because
            # the class is already completed.
            # ----------------------------------------------------

            if class_state == "past":

                if raw_status in (
                    "present",
                    "p",
                    "late",
                    "l"
                ):

                    display_status = "Present"

                else:

                    display_status = "Absent"

            # ----------------------------------------------------
            # ONGOING CLASS
            #
            # Attendance can be:
            #     Present
            #     Absent
            #     Unmarked
            # ----------------------------------------------------

            elif class_state == "ongoing":

                if raw_status in (
                    "present",
                    "p"
                ):

                    display_status = "Present"

                elif raw_status in (
                    "late",
                    "l"
                ):

                    display_status = "Late"

                elif raw_status in (
                    "absent",
                    "a"
                ):

                    display_status = "Absent"

                else:

                    display_status = "Unmarked"

            # ----------------------------------------------------
            # FUTURE CLASS
            #
            # Regardless of database state, do not show
            # Present/Absent for a class that has not started.
            # ----------------------------------------------------

            else:

                display_status = "Unmarked"

            record["status"] = display_status

            normalized_records.append(record)

        attendance_records = normalized_records

        # ========================================================
        # SORT
        #
        # Past / ongoing:
        #     Absent first
        #     Present / Late second
        #     Unmarked last
        #
        # Future:
        #     Everything is Unmarked
        # ========================================================

        status_order = {
            "absent": 0,
            "present": 1,
            "late": 1,
            "unmarked": 2
        }

        attendance_records.sort(
            key=lambda record: (
                status_order.get(
                    str(
                        record.get("status")
                        or "Unmarked"
                    ).strip().lower(),
                    2
                ),
                str(
                    record.get("roll_number")
                    or record.get("student_id")
                    or ""
                ).strip()
            )
        )

        # ========================================================
        # COUNTS
        # ========================================================

        total_students = len(
            attendance_records
        )

        present_count = sum(
            1
            for row in attendance_records
            if str(
                row.get("status") or ""
            ).strip().lower()
            in ("present", "late")
        )

        late_count = sum(
            1
            for row in attendance_records
            if str(
                row.get("status") or ""
            ).strip().lower()
            == "late"
        )

        absent_count = sum(
            1
            for row in attendance_records
            if str(
                row.get("status") or ""
            ).strip().lower()
            == "absent"
        )

        unmarked_count = sum(
            1
            for row in attendance_records
            if str(
                row.get("status") or ""
            ).strip().lower()
            == "unmarked"
        )

        # ========================================================
        # MARKED COUNT
        # ========================================================

        marked_count = 0

        if selected_class is not None:

            marked_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM attendance
                WHERE timetable_id = ?
                  AND date = ?
                  AND LOWER(TRIM(COALESCE(status, ''))) IN (
                      'present',
                      'p',
                      'absent',
                      'a',
                      'late',
                      'l'
                  )
                """,
                (
                    selected_class["id"],
                    selected_date
                )
            ).fetchone()[0]

        # ========================================================
        # FINALIZED
        # ========================================================

        finalized = (
            bool(total_students)
            and class_state == "past"
            and marked_count >= total_students
        )

        # ========================================================
        # RENDER
        # ========================================================

        return render_template(
            "faculty_attendance.html",

            faculty=faculty,

            faculty_name=faculty_name,

            username=username,

            # Database/input value
            # Keep this YYYY-MM-DD because <input type="date">
            # requires this format.
            selected_date=selected_date,

            # Display-only value
            # DD/MM/YYYY
            display_date=display_date,

            classes=classes,

            selected_timetable_id=selected_timetable_id,

            selected_class=selected_class,

            attendance_records=attendance_records,

            present_count=present_count,

            late_count=late_count,

            absent_count=absent_count,

            unmarked_count=unmarked_count,

            total_students=total_students,

            marked_count=marked_count,

            finalized=finalized,

            # Useful if you want the template to know whether
            # the class is past, ongoing, or future.
            class_state=class_state
        )

    finally:

        conn.close()

# ============================================================
# FINALIZE FACULTY ATTENDANCE
# ============================================================

@app.route(
    "/faculty/attendance/finalize",
    methods=["POST"]
)
@role_required("faculty")
def finalize_faculty_attendance():

    faculty, faculty_name, username = faculty_identity()

    if faculty is None:
        flash(
            "Faculty account not found.",
            "error"
        )
        return redirect(
            url_for("logout")
        )

    selected_date = request.form.get(
        "date",
        date.today().isoformat()
    ).strip()

    timetable_id = request.form.get(
        "timetable_id",
        ""
    ).strip()

    try:

        date.fromisoformat(
            selected_date
        )

        timetable_id = int(
            timetable_id
        )

        if timetable_id <= 0:
            raise ValueError(
                "Invalid timetable ID"
            )

    except (
        ValueError,
        TypeError
    ):

        flash(
            "Please select a valid date and class.",
            "error"
        )

        return redirect(
            url_for(
                "faculty_attendance"
            )
        )

    conn = get_db_connection()

    try:

        timetable = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE id = ?
              AND (
                    active = 1
                    OR active IS NULL
              )
            """,
            (timetable_id,)
        ).fetchone()

        if timetable is None:

            flash(
                "Selected class was not found.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=selected_date
                )
            )

        # --------------------------------------------------------
        # Verify class day
        # --------------------------------------------------------

        aliases = {
            item.lower()
            for item in get_day_aliases(
                selected_date
            )
        }

        class_day = str(
            timetable["day"] or ""
        ).strip().lower()

        if class_day not in aliases:

            flash(
                "That class is not scheduled on the selected date.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=selected_date
                )
            )

        # --------------------------------------------------------
        # Verify faculty ownership
        # --------------------------------------------------------

        if not faculty_matches_timetable(
            timetable,
            faculty_name,
            username
        ):

            flash(
                "You can finalize attendance only for your own class.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=display_date,
                    timetable_id=timetable_id
                )
            )

        # --------------------------------------------------------
        # Only today's attendance
        # --------------------------------------------------------

        if selected_date != date.today().isoformat():

            flash(
                "You can finalize attendance only for today's session.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=display_date,
                    timetable_id=timetable_id
                )
            )

        # --------------------------------------------------------
        # Attendance window
        # --------------------------------------------------------

        window = get_camera_window_for_class(
            timetable,
            selected_date
        )

        if window is None:

            flash(
                "Unable to determine this class's attendance window.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=display_date,
                    timetable_id=timetable_id
                )
            )

        if datetime.now() < window["end"]:

            flash(
                f"Attendance can be finalized after "
                f"{window['end_text']}.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=display_date,
                    timetable_id=timetable_id
                )
            )

        # --------------------------------------------------------
        # Add absent records
        # --------------------------------------------------------

        absent_added = 0

        finalized_time = datetime.now().strftime(
            "%H:%M:%S"
        )

        try:

            conn.execute("BEGIN")

            students = get_class_students(
                conn,
                timetable
            )

            for student in students:

                exists = conn.execute(
                    """
                    SELECT id
                    FROM attendance
                    WHERE student_id = ?
                      AND timetable_id = ?
                      AND date = ?
                    LIMIT 1
                    """,
                    (
                        student["id"],
                        timetable_id,
                        selected_date
                    )
                ).fetchone()

                if exists:
                    continue

                conn.execute(
                    """
                    INSERT INTO attendance
                    (
                        student_id,
                        timetable_id,
                        date,
                        time,
                        status,
                        confidence
                    )
                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        'Absent',
                        NULL
                    )
                    """,
                    (
                        student["id"],
                        timetable_id,
                        display_date,
                        finalized_time
                    )
                )

                absent_added += 1

            conn.commit()

        except Exception:

            conn.rollback()

            app.logger.exception(
                "Failed to finalize faculty attendance "
                "for timetable ID %s on %s",
                timetable_id,
                selected_date
            )

            flash(
                "Attendance could not be finalized. "
                "No partial changes were saved.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=display_date,
                    timetable_id=timetable_id
                )
            )

        flash(
            f"Attendance finalized successfully. "
            f"{absent_added} absent record(s) added.",
            "success"
        )

        return redirect(
            url_for(
                "faculty_attendance",
                date=display_date,
                timetable_id=timetable_id,
                finalized="1"
            )
        )

    finally:
        conn.close()

# ============================================================
# PDF GENERATION
# ============================================================

def build_attendance_pdf(
    rows,
    title,
    filename,
    class_info=None
):
    """
    Build a compact attendance PDF.

    Keeps all existing attendance data.
    Layout is compressed so more rows fit on each page.
    """

    buffer = BytesIO()

    # --------------------------------------------------------
    # COMPACT LANDSCAPE A4
    # --------------------------------------------------------

    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),

        # Smaller margins = more usable page height
        rightMargin=20,
        leftMargin=20,
        topMargin=18,
        bottomMargin=18
    )

    styles = getSampleStyleSheet()

    # --------------------------------------------------------
    # COMPACT TITLE STYLE
    # --------------------------------------------------------

    title_style = ParagraphStyle(
        "CompactPDFTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=17,
        spaceAfter=4
    )

    normal_style = ParagraphStyle(
        "CompactPDFNormal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10
    )

    story = []

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    story.append(
        Paragraph(
            str(title or "Attendance Report"),
            title_style
        )
    )

    story.append(
        Spacer(1, 5)
    )

    # ========================================================
    # CLASS INFORMATION
    # ========================================================

    if class_info:

        subject = str(
            class_info.get("subject")
            or "-"
        ).strip()

        faculty = str(
            class_info.get("faculty")
            or "-"
        ).strip()

        class_name = str(
            class_info.get("class_name")
            or "IV ECE A"
        ).strip()

        selected_date = str(
            class_info.get("date")
            or "-"
        ).strip()

        day = str(
            class_info.get("day")
            or "-"
        ).strip()

        start_time = str(
            class_info.get("start_time")
            or "-"
        ).strip()

        end_time = str(
            class_info.get("end_time")
            or "-"
        ).strip()

        room = str(
            class_info.get("room_no")
            or "-"
        ).strip()

        # ----------------------------------------------------
        # Convert YYYY-MM-DD -> DD/MM/YYYY
        # ----------------------------------------------------

        display_date = selected_date

        try:
            display_date = datetime.strptime(
                selected_date,
                "%Y-%m-%d"
            ).strftime("%d/%m/%Y")

        except (
            TypeError,
            ValueError
        ):
            pass

        # ----------------------------------------------------
        # Normalize class name
        # ----------------------------------------------------

        if class_name.upper() in (
            "IV B.TECH ECE AI",
            "IV B.TECH ECE A.I",
            "IV ECE AI",
            "IV ECE A.I"
        ):
            class_name = "IV ECE A"

        elif class_name.upper() in (
            "IV B.TECH ECE A",
            "IV ECE A"
        ):
            class_name = "IV ECE A"

        # ----------------------------------------------------
        # Compact header
        # ----------------------------------------------------

        details = (
            f"<b>Subject:</b> {subject}"
            f"&nbsp;&nbsp;&nbsp;&nbsp;"
            f"<b>Faculty:</b> {faculty}<br/>"

            f"<b>Class:</b> {class_name}"
            f"&nbsp;&nbsp;&nbsp;&nbsp;"
            f"<b>Date:</b> {display_date}"
            f"&nbsp;&nbsp;&nbsp;&nbsp;"
            f"<b>Day:</b> {day}<br/>"

            f"<b>Time:</b> {start_time} - {end_time}"
            f"&nbsp;&nbsp;&nbsp;&nbsp;"
            f"<b>Room:</b> {room}"
        )

        story.append(
            Paragraph(
                details,
                normal_style
            )
        )

        # Very small gap before table
        story.append(
            Spacer(1, 5)
        )

    # ========================================================
    # ATTENDANCE TABLE
    #
    # ONLY:
    #   No.
    #   Roll Number
    #   Student Name
    #   Status
    # ========================================================

    table_data = [[
        "No.",
        "Roll Number",
        "Student Name",
        "Status"
    ]]

    for index, row in enumerate(
        rows or [],
        start=1
    ):

        roll_number = (
            row.get("roll_number")
            or row.get("student_code")
            or row.get("student_id")
            or "-"
        )

        student_name = (
            row.get("student_name")
            or row.get("name")
            or "-"
        )

        status = (
            row.get("status")
            or "Not marked"
        )

        status = str(status).strip()

        if not status:
            status = "Not marked"

        table_data.append([
            str(index),
            str(roll_number),
            str(student_name),
            status
        ])

    # ========================================================
    # NO RECORDS
    # ========================================================

    if len(table_data) == 1:

        table_data.append([
            "-",
            "-",
            "No attendance records",
            "-"
        ])

    # ========================================================
    # COMPACT TABLE
    # ========================================================

    table = Table(
        table_data,
        repeatRows=1,

        # Total = 580 points
        # Fits comfortably inside landscape A4
        colWidths=[
            38,     # No.
            115,    # Roll Number
            350,    # Student Name
            90      # Status
        ],

        # Allow table to split naturally across pages
        splitByRow=1
    )

    table.setStyle(
        TableStyle([

            # ------------------------------------------------
            # HEADER
            # ------------------------------------------------

            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#222222")
            ),

            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white
            ),

            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),

            # ------------------------------------------------
            # BODY
            # ------------------------------------------------

            (
                "FONTNAME",
                (0, 1),
                (-1, -1),
                "Helvetica"
            ),

            # Smaller font
            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),

            # Tighter line spacing
            (
                "LEADING",
                (0, 0),
                (-1, -1),
                9
            ),

            # ------------------------------------------------
            # GRID
            # ------------------------------------------------

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.35,
                colors.HexColor("#cccccc")
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "MIDDLE"
            ),

            # ------------------------------------------------
            # ALIGNMENT
            # ------------------------------------------------

            (
                "ALIGN",
                (0, 0),
                (0, -1),
                "CENTER"
            ),

            (
                "ALIGN",
                (-1, 0),
                (-1, -1),
                "CENTER"
            ),

            # ------------------------------------------------
            # ALTERNATING ROWS
            # ------------------------------------------------

            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [
                    colors.white,
                    colors.HexColor("#f4f4f4")
                ]
            ),

            # ------------------------------------------------
            # VERY SMALL CELL PADDING
            # ------------------------------------------------

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                4
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                4
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                2.5
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                2.5
            )
        ])
    )

    # --------------------------------------------------------
    # ADD TABLE
    # --------------------------------------------------------

    story.append(table)

    # --------------------------------------------------------
    # BUILD PDF
    # --------------------------------------------------------

    document.build(story)

    buffer.seek(0)

    return buffer

# ============================================================
# BUILD PDF ROWS FROM DATABASE DATA
# ============================================================

def attendance_pdf_rows(
    conn,
    timetable_row,
    selected_date
):

    records = _class_attendance_rows(
        conn,
        timetable_row,
        selected_date
    )

    rows = []

    for record in records:

        rows.append({
            "roll_number": (
                record.get("student_code")
                or record.get("roll_number")
                or record.get("student_id")
                or "-"
            ),

            "student_name": (
                record.get("student_name")
                or record.get("name")
                or "-"
            ),

            "subject_name": (
                record.get("subject_name")
                or record.get("subject")
                or timetable_subject(timetable_row)
                or "-"
            ),

            "faculty_name": (
                record.get("faculty_name")
                or record.get("faculty")
                or timetable_row.get("faculty_name")
                if hasattr(timetable_row, "get")
                else "-"
            ),

            "date": (
                record.get("date")
                or selected_date
            ),

            "time": (
                record.get("time")
                or "-"
            ),

            "start_time": (
                record.get("start_time")
                or timetable_row["start_time"]
                if "start_time" in timetable_row.keys()
                else "-"
            ),

            "end_time": (
                record.get("end_time")
                or timetable_row["end_time"]
                if "end_time" in timetable_row.keys()
                else "-"
            ),

            "status": (
                record.get("status")
                or "Not marked"
            )
        })

    return rows


# ============================================================
# PDF FILENAME HELPER
# ============================================================

def make_attendance_pdf_filename(
    subject,
    selected_date,
    start_time,
    end_time
):
    """
    Creates filename like:

    Scripting_languages_23-10-2026_10-30-11-30.pdf

    NOTE:
    Windows does NOT allow "/" inside filenames.
    Therefore DD-MM-YYYY is used instead of DD/MM/YYYY.
    """

    subject = str(
        subject or "Attendance"
    ).strip()

    # Replace spaces with underscores
    safe_subject = re.sub(
        r"\s+",
        "_",
        subject
    )

    # Remove Windows-invalid filename characters
    safe_subject = re.sub(
        r'[<>:"/\\|?*]+',
        "",
        safe_subject
    )

    # Date
    try:

        filename_date = datetime.strptime(
            str(selected_date),
            "%Y-%m-%d"
        ).strftime("%d-%m-%Y")

    except (
        TypeError,
        ValueError
    ):

        filename_date = str(
            selected_date or ""
        ).replace("/", "-")

    # Times
    safe_start_time = re.sub(
        r'[<>:"/\\|?*]+',
        "-",
        str(start_time or "").strip()
    )

    safe_end_time = re.sub(
        r'[<>:"/\\|?*]+',
        "-",
        str(end_time or "").strip()
    )

    safe_start_time = safe_start_time.replace(
        " ",
        ""
    )

    safe_end_time = safe_end_time.replace(
        " ",
        ""
    )

    return (
        f"{safe_subject}_"
        f"{filename_date}_"
        f"{safe_start_time}-"
        f"{safe_end_time}.pdf"
    )


# ============================================================
# FACULTY DOWNLOAD — SELECTED CLASS AND DATE
# ============================================================

@app.route("/faculty/attendance/pdf")
@role_required("faculty")
def faculty_attendance_pdf():

    faculty, faculty_name, username = faculty_identity()

    if faculty is None:

        flash(
            "Faculty account not found.",
            "error"
        )

        return redirect(
            url_for("logout")
        )

    # --------------------------------------------------------
    # Selected date
    # --------------------------------------------------------

    selected_date = request.args.get(
        "date",
        date.today().isoformat()
    ).strip()

    # --------------------------------------------------------
    # Selected timetable
    # --------------------------------------------------------

    timetable_id = request.args.get(
        "timetable_id",
        ""
    ).strip()

    try:

        date.fromisoformat(
            selected_date
        )

        timetable_id = int(
            timetable_id
        )

    except (
        TypeError,
        ValueError
    ):

        flash(
            "Select a valid date and class first.",
            "error"
        )

        return redirect(
            url_for(
                "faculty_attendance",
                date=selected_date
            )
        )

    conn = get_db_connection()

    try:

        # ====================================================
        # GET SELECTED CLASS
        #
        # IMPORTANT:
        # Do NOT filter by logged-in faculty.
        #
        # This allows:
        #
        # Ms Jyothsna -> download Kazi class
        # Ms Kazi     -> download Jyothsna class
        # ====================================================

        timetable = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE id = ?
            """,
            (timetable_id,)
        ).fetchone()

        if timetable is None:

            flash(
                "Selected class was not found.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=selected_date
                )
            )

        # ====================================================
        # CHECK CLASS IS SCHEDULED ON SELECTED DATE
        # ====================================================

        valid_days = {
            str(item).strip().lower()
            for item in get_day_aliases(
                selected_date
            )
        }

        timetable_day = str(
            timetable["day"] or ""
        ).strip().lower()

        if timetable_day not in valid_days:

            flash(
                "This class is not scheduled on that date.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_attendance",
                    date=selected_date
                )
            )

        # ====================================================
        # GET ATTENDANCE
        # ====================================================

        rows = attendance_pdf_rows(
            conn,
            timetable,
            selected_date
        )

        # ====================================================
        # GET SUBJECT
        # ====================================================

        subject = timetable_subject(
            timetable
        )

        if not subject:

            subject = (
                timetable["subject"]
                if "subject" in timetable.keys()
                else "Attendance"
            )

        # ====================================================
        # GET FACULTY NAME
        # ====================================================

        if (
            "faculty_name" in timetable.keys()
            and timetable["faculty_name"]
        ):

            pdf_faculty = str(
                timetable["faculty_name"]
            ).strip()

        elif (
            "faculty" in timetable.keys()
            and timetable["faculty"]
        ):

            pdf_faculty = str(
                timetable["faculty"]
            ).strip()

        else:

            pdf_faculty = (
                faculty_name
                or username
                or "-"
            )

        # ====================================================
        # CLASS NAME
        # ====================================================

        if (
            "class_name" in timetable.keys()
            and timetable["class_name"]
        ):

            pdf_class_name = str(
                timetable["class_name"]
            ).strip()

        elif (
            "class_section" in timetable.keys()
            and timetable["class_section"]
        ):

            pdf_class_name = str(
                timetable["class_section"]
            ).strip()

        else:

            pdf_class_name = "IV ECE A"

        # Normalize ECE AI -> ECE A as requested
        if pdf_class_name.upper() in (
            "IV B.TECH ECE AI",
            "IV B.TECH ECE A.I",
            "IV ECE AI",
            "IV ECE A.I"
        ):

            pdf_class_name = "IV ECE A"

        elif pdf_class_name.upper() == "IV B.TECH ECE A":

            pdf_class_name = "IV ECE A"

        # ====================================================
        # DAY
        # ====================================================

        pdf_day = str(
            timetable["day"]
            if "day" in timetable.keys()
            else date.fromisoformat(
                selected_date
            ).strftime("%A")
        ).strip()

        # ====================================================
        # TIME
        # ====================================================

        pdf_start_time = str(
            timetable["start_time"]
            if "start_time" in timetable.keys()
            else "-"
        ).strip()

        pdf_end_time = str(
            timetable["end_time"]
            if "end_time" in timetable.keys()
            else "-"
        ).strip()

        # ====================================================
        # ROOM
        # ====================================================

        pdf_room = timetable_room(
            timetable
        )

        # ====================================================
        # PDF CLASS INFORMATION
        # ====================================================

        class_info = {

            "subject": subject,

            "faculty": pdf_faculty,

            "class_name": pdf_class_name,

            "date": selected_date,

            "day": pdf_day,

            "start_time": pdf_start_time,

            "end_time": pdf_end_time,

            "room_no": pdf_room
        }

        # ====================================================
        # BUILD PDF
        # ====================================================

        pdf = build_attendance_pdf(
            rows,

            "Class Attendance Report",

            "attendance.pdf",

            class_info
        )

        # ====================================================
        # DOWNLOAD FILENAME
        # ====================================================

        filename = make_attendance_pdf_filename(
            subject,
            selected_date,
            pdf_start_time,
            pdf_end_time
        )

        # ====================================================
        # SEND PDF
        # ====================================================

        return send_file(
            pdf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    finally:

        conn.close()


# ============================================================
# FACULTY DOWNLOAD — TODAY'S CLASSES
# ============================================================

@app.route("/faculty/attendance/today/pdf")
@role_required("faculty")
def faculty_today_attendance_pdf():

    faculty, faculty_name, username = faculty_identity()

    if faculty is None:

        flash(
            "Faculty account not found.",
            "error"
        )

        return redirect(
            url_for("logout")
        )

    today = date.today().isoformat()

    # IMPORTANT:
    # If a date/timetable_id was supplied in the URL,
    # use that selected class instead of blindly downloading
    # today's logged-in faculty classes.

    requested_date = request.args.get(
        "date",
        ""
    ).strip()

    requested_timetable_id = request.args.get(
        "timetable_id",
        ""
    ).strip()

    # --------------------------------------------------------
    # If timetable_id is supplied, redirect to the main
    # selected-class PDF endpoint.
    # --------------------------------------------------------

    if requested_timetable_id:

        selected_date = (
            requested_date
            or today
        )

        return redirect(
            url_for(
                "faculty_attendance_pdf",
                date=selected_date,
                timetable_id=requested_timetable_id
            )
        )

    conn = get_db_connection()

    try:

        # ----------------------------------------------------
        # Today's classes for this faculty
        # ----------------------------------------------------

        today_classes = [
            row
            for row in scheduled_classes_for_date(
                conn,
                today
            )
            if faculty_matches_timetable(
                row,
                faculty_name,
                username
            )
        ]

        # ----------------------------------------------------
        # No classes
        # ----------------------------------------------------

        if not today_classes:

            flash(
                "No classes scheduled for today.",
                "error"
            )

            return redirect(
                url_for(
                    "faculty_today_attendance_page"
                )
            )

        # ----------------------------------------------------
        # If there is exactly one class,
        # download that class.
        # ----------------------------------------------------

        if len(today_classes) == 1:

            timetable = today_classes[0]

            return redirect(
                url_for(
                    "faculty_attendance_pdf",
                    date=today,
                    timetable_id=timetable["id"]
                )
            )

        # ----------------------------------------------------
        # Multiple classes:
        # keep old combined download behavior.
        # ----------------------------------------------------

        combined_rows = []

        for timetable in today_classes:

            combined_rows.extend(
                attendance_pdf_rows(
                    conn,
                    timetable,
                    today
                )
            )

        class_info = {

            "subject": "All assigned classes",

            "faculty": (
                faculty_name
                or username
                or "-"
            ),

            "class_name": "IV ECE A",

            "date": today,

            "day": date.today().strftime("%A"),

            "start_time": "-",

            "end_time": "-",

            "room_no": "-"
        }

        pdf = build_attendance_pdf(
            combined_rows,
            "Today's Attendance Report",
            "today_attendance.pdf",
            class_info
        )

        filename = (
            f"faculty_attendance_"
            f"{datetime.strptime(today, '%Y-%m-%d').strftime('%d-%m-%Y')}"
            f".pdf"
        )

        return send_file(
            pdf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    finally:

        conn.close()


# ============================================================
# COMPATIBILITY ALIAS
#
# Your existing HTML can continue using:
#
# /faculty/attendance/today/download
# ============================================================

app.add_url_rule(
    "/faculty/attendance/today/download",
    endpoint="faculty_today_attendance_download",
    view_func=faculty_today_attendance_pdf,
    methods=["GET"]
)


# ============================================================
# ADMIN DOWNLOAD — CURRENT CAMERA CLASS
# ============================================================

@app.route("/admin/attendance/current/pdf")
@role_required("admin")
def admin_current_attendance_pdf():

    current_class = get_current_timetable_class()

    if current_class is None:

        flash(
            "There is no active camera attendance class.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    selected_date = date.today().isoformat()

    conn = get_db_connection()

    try:

        timetable = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE id = ?
            """,
            (current_class["id"],)
        ).fetchone()

        if timetable is None:

            flash(
                "Class not found.",
                "error"
            )

            return redirect(
                url_for("dashboard")
            )

        rows = attendance_pdf_rows(
            conn,
            timetable,
            selected_date
        )

        subject = timetable_subject(
            timetable
        )

        if not subject:

            subject = (
                timetable["subject"]
                if "subject" in timetable.keys()
                else "Attendance"
            )

        if (
            "faculty_name" in timetable.keys()
            and timetable["faculty_name"]
        ):

            pdf_faculty = timetable["faculty_name"]

        elif (
            "faculty" in timetable.keys()
            and timetable["faculty"]
        ):

            pdf_faculty = timetable["faculty"]

        else:

            pdf_faculty = "-"

        class_name = (
            timetable["class_name"]
            if "class_name" in timetable.keys()
            and timetable["class_name"]
            else "IV ECE A"
        )

        class_name = str(
            class_name
        ).strip()

        if class_name.upper() in (
            "IV B.TECH ECE AI",
            "IV B.TECH ECE A.I",
            "IV ECE AI",
            "IV ECE A.I",
            "IV B.TECH ECE A"
        ):

            class_name = "IV ECE A"

        start_time = str(
            timetable["start_time"]
            if "start_time" in timetable.keys()
            else "-"
        ).strip()

        end_time = str(
            timetable["end_time"]
            if "end_time" in timetable.keys()
            else "-"
        ).strip()

        class_info = {

            "subject": subject,

            "faculty": pdf_faculty,

            "class_name": class_name,

            "date": selected_date,

            "day": timetable["day"],

            "start_time": start_time,

            "end_time": end_time,

            "room_no": timetable_room(timetable)
        }

        pdf = build_attendance_pdf(
            rows,
            "Current Class Attendance",
            "current_attendance.pdf",
            class_info
        )

        filename = make_attendance_pdf_filename(
            subject,
            selected_date,
            start_time,
            end_time
        )

        return send_file(
            pdf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    finally:

        conn.close()


# ============================================================
# ADMIN DOWNLOAD — SELECTED DATE AND CLASS
# ============================================================

@app.route("/admin/attendance/pdf")
@role_required("admin")
def admin_attendance_pdf():

    selected_date = request.args.get(
        "date",
        date.today().isoformat()
    ).strip()

    timetable_id = request.args.get(
        "timetable_id",
        ""
    ).strip()

    try:

        date.fromisoformat(
            selected_date
        )

        timetable_id = int(
            timetable_id
        )

    except (
        TypeError,
        ValueError
    ):

        flash(
            "Select a valid date and class.",
            "error"
        )

        return redirect(
            url_for(
                "admin_attendance_history"
            )
        )

    conn = get_db_connection()

    try:

        # IMPORTANT:
        # Do not require active=1 here.
        # Historical/inactive timetable entries can still
        # have attendance records that need to be downloaded.

        timetable = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE id = ?
            """,
            (timetable_id,)
        ).fetchone()

        if timetable is None:

            flash(
                "Class not found.",
                "error"
            )

            return redirect(
                url_for(
                    "admin_attendance_history",
                    date=selected_date
                )
            )

        # ====================================================
        # VERIFY DATE
        # ====================================================

        valid_days = {
            str(item).strip().lower()
            for item in get_day_aliases(
                selected_date
            )
        }

        timetable_day = str(
            timetable["day"] or ""
        ).strip().lower()

        if timetable_day not in valid_days:

            flash(
                "This class is not scheduled on that date.",
                "error"
            )

            return redirect(
                url_for(
                    "admin_attendance_history",
                    date=selected_date
                )
            )

        # ====================================================
        # ATTENDANCE
        # ====================================================

        rows = attendance_pdf_rows(
            conn,
            timetable,
            selected_date
        )

        # ====================================================
        # SUBJECT
        # ====================================================

        subject = timetable_subject(
            timetable
        )

        if not subject:

            subject = (
                timetable["subject"]
                if "subject" in timetable.keys()
                else "Attendance"
            )

        # ====================================================
        # FACULTY
        # ====================================================

        if (
            "faculty_name" in timetable.keys()
            and timetable["faculty_name"]
        ):

            pdf_faculty = str(
                timetable["faculty_name"]
            ).strip()

        elif (
            "faculty" in timetable.keys()
            and timetable["faculty"]
        ):

            pdf_faculty = str(
                timetable["faculty"]
            ).strip()

        else:

            pdf_faculty = "-"

        # ====================================================
        # CLASS
        # ====================================================

        if (
            "class_name" in timetable.keys()
            and timetable["class_name"]
        ):

            pdf_class_name = str(
                timetable["class_name"]
            ).strip()

        else:

            pdf_class_name = "IV ECE A"

        if pdf_class_name.upper() in (
            "IV B.TECH ECE AI",
            "IV B.TECH ECE A.I",
            "IV ECE AI",
            "IV ECE A.I",
            "IV B.TECH ECE A"
        ):

            pdf_class_name = "IV ECE A"

        # ====================================================
        # TIME
        # ====================================================

        start_time = str(
            timetable["start_time"]
            if "start_time" in timetable.keys()
            else "-"
        ).strip()

        end_time = str(
            timetable["end_time"]
            if "end_time" in timetable.keys()
            else "-"
        ).strip()

        # ====================================================
        # CLASS INFO
        # ====================================================

        class_info = {

            "subject": subject,

            "faculty": pdf_faculty,

            "class_name": pdf_class_name,

            "date": selected_date,

            "day": timetable["day"],

            "start_time": start_time,

            "end_time": end_time,

            "room_no": timetable_room(timetable)
        }

        # ====================================================
        # BUILD PDF
        # ====================================================

        pdf = build_attendance_pdf(
            rows,
            "Attendance Report",
            "attendance.pdf",
            class_info
        )

        # ====================================================
        # FILENAME
        # ====================================================

        filename = make_attendance_pdf_filename(
            subject,
            selected_date,
            start_time,
            end_time
        )

        # ====================================================
        # SEND
        # ====================================================

        return send_file(
            pdf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    finally:

        conn.close()


# ============================================================
# CURRENT USER API
# ============================================================

@app.route("/api/me")
@login_required
def current_user():

    return jsonify({
        "id": session.get("user_id"),
        "username": session.get("username"),
        "role": session.get("role")
    })


# ============================================================
# STUDENTS API
# ============================================================

@app.route("/api/students")
@login_required
def api_students():

    conn = get_db_connection()

    try:
        students = conn.execute(
            """
            SELECT *
            FROM students
            ORDER BY student_id
            """
        ).fetchall()

        return jsonify([
            dict(student)
            for student in students
        ])

    finally:
        conn.close()


# ============================================================
# FACULTY API
# ============================================================

@app.route("/api/faculty")
@role_required("admin")
def api_faculty():

    conn = get_db_connection()

    try:
        faculty_members = conn.execute(
            """
            SELECT *
            FROM faculty
            ORDER BY name
            """
        ).fetchall()

        return jsonify([
            dict(member)
            for member in faculty_members
        ])

    finally:
        conn.close()


# ============================================================
# TIMETABLE API
# ============================================================

@app.route("/api/timetable")
@login_required
def api_timetable():

    conn = get_db_connection()

    try:
        rows = all_timetable_rows(conn)

        return jsonify([
            dict(row)
            for row in rows
        ])

    finally:
        conn.close()


@app.route("/api/timetable/day/<day_name>")
@login_required
def api_timetable_by_day(day_name):

    normalized = day_name.strip().lower()

    aliases = None

    for short_day, day_aliases in DAY_ALIASES.items():
        if normalized in [
            value.lower()
            for value in day_aliases
        ]:
            aliases = [
                value.lower()
                for value in day_aliases
            ]
            break

    if aliases is None:
        return jsonify({
            "success": False,
            "message": "Invalid day name."
        }), 400

    placeholders = ",".join("?" for _ in aliases)

    conn = get_db_connection()

    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM timetable
            WHERE lower(trim(day)) IN ({placeholders})
            ORDER BY start_time
            """,
            aliases
        ).fetchall()

        return jsonify({
            "success": True,
            "day": day_name,
            "classes": [
                dict(row)
                for row in rows
            ]
        })

    finally:
        conn.close()


# ============================================================
# CURRENT CLASS ATTENDANCE API
# ============================================================

@app.route("/api/attendance")
@login_required
def api_attendance():

    current_class = get_current_timetable_class()

    if current_class is None:
        return jsonify([])

    conn = get_db_connection()

    try:
        return jsonify(
            _class_attendance_rows(
                conn,
                current_class,
                date.today().isoformat()
            )
        )

    finally:
        conn.close()


# ============================================================
# AUTOMATIC ATTENDANCE EMAIL CHECK
# ============================================================

def run_attendance_email_notifications():
    print()
    print("=" * 70)
    print(
        "ATTENDANCE NOTIFICATION JOB STARTED:",
        datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    )
    print("=" * 70)

    try:
        result = notify_today_absentees(
            get_db_connection_function=get_db_connection,
            get_day_aliases_function=get_day_aliases,
            send_email=True,
            send_whatsapp=False
        )

        print("ABSENTEES:", result.get("total_absentees", 0))
        print("EMAILS SENT:", result.get("emails_sent", 0))
        print("EMAILS FAILED:", result.get("emails_failed", 0))
        print("SKIPPED:", result.get("skipped", 0))

        for detail in result.get("details", []):
            print(detail)

    except Exception as exc:
        print(
            "ATTENDANCE NOTIFICATION JOB ERROR:",
            repr(exc)
        )

    finally:
        print("=" * 70)
        print(
            "ATTENDANCE NOTIFICATION JOB FINISHED:",
            datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        )
        print("=" * 70)


# ============================================================
# ADMIN ATTENDANCE HISTORY HELPERS
# ============================================================

def get_admin_attendance_classes(conn, selected_date):
    all_rows = [dict(row) for row in all_timetable_rows(conn)]

    day_aliases = {
        str(value).strip().lower()
        for value in get_day_aliases(selected_date)
    }

    classes = []

    for item in all_rows:
        item_day = str(item.get("day") or "").strip().lower()
        active_value = str(item.get("active", 1)).strip().lower()

        if item_day not in day_aliases:
            continue

        if active_value in ("0", "false", "no", "inactive"):
            continue

        item["subject_name"] = (
            item.get("subject_name")
            or item.get("subject")
            or item.get("course_code")
            or item.get("class_name")
            or "Class"
        )

        item["course_code"] = item.get("course_code") or "-"

        item["faculty_name"] = (
            item.get("faculty_name")
            or item.get("faculty")
            or "-"
        )

        item["class_section"] = (
            item.get("class_section")
            or item.get("section")
            or item.get("class_name")
            or item.get("class")
            or "-"
        )

        section = str(item["class_section"]).strip()
        item["class_section"] = section.replace(
            "IV B.Tech ECE AI",
            "IV B.Tech ECE A"
        )

        item["room_no"] = (
            item.get("room_no")
            or item.get("room")
            or item.get("classroom")
            or "-"
        )

        classes.append(item)

    classes.sort(
        key=lambda item: (
            _time_value(item.get("start_time"))
            or datetime.strptime("23:59", "%H:%M").time()
        )
    )

    return classes


# ============================================================
# AJAX ENDPOINT: RETURN CLASSES SCHEDULED FOR A DATE
# ============================================================

@app.route("/admin/attendance/classes")
@role_required("admin")
def admin_attendance_classes():
    from datetime import date
    from flask import jsonify

    selected_date = request.args.get(
        "date",
        date.today().isoformat()
    )

    conn = get_db_connection()

    try:
        classes = get_admin_attendance_classes(conn, selected_date)

        result = []

        for item in classes:
            result.append({
                "id": item.get("id"),
                "start_time": item.get("start_time") or "--",
                "end_time": item.get("end_time") or "",
                "subject_name": item.get("subject_name") or "Class",
                "course_code": item.get("course_code") or "-",
                "faculty_name": item.get("faculty_name") or "-",
                "class_section": item.get("class_section") or "-",
                "room_no": item.get("room_no") or "-"
            })

        return jsonify({
            "date": selected_date,
            "classes": result
        })

    finally:
        conn.close()



# ============================================================
# ADMIN ATTENDANCE HISTORY
# ============================================================
@app.route("/admin/attendance")
@role_required("admin")
def admin_attendance_history():

    from datetime import date, datetime

    conn = get_db_connection()

    try:

        # ========================================================
        # SELECTED DATE
        # ========================================================

        selected_date = request.args.get(
            "date",
            date.today().isoformat()
        ).strip()

        try:
            selected_date_obj = date.fromisoformat(
                selected_date
            )
        except (ValueError, TypeError):

            selected_date = date.today().isoformat()
            selected_date_obj = date.today()


        # ========================================================
        # SELECTED TIMETABLE
        # ========================================================

        timetable_id_raw = request.args.get(
            "timetable_id",
            ""
        ).strip()

        try:
            selected_timetable_id = int(
                timetable_id_raw
            )
        except (ValueError, TypeError):

            selected_timetable_id = None


        # ========================================================
        # LOAD CLASSES FOR SELECTED DATE
        # ========================================================

        classes = []

        try:

            classes = get_admin_attendance_classes(
                conn,
                selected_date
            ) or []

        except Exception as class_error:

            print(
                "ADMIN ATTENDANCE CLASS LOAD ERROR:",
                class_error
            )

            # ----------------------------------------------------
            # FALLBACK: DIRECT TIMETABLE QUERY
            # ----------------------------------------------------

            try:

                timetable_columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(timetable)"
                    ).fetchall()
                }

                if "day" in timetable_columns:

                    valid_days = {
                        str(day_value)
                        .strip()
                        .lower()
                        for day_value
                        in get_day_aliases(
                            selected_date
                        )
                    }

                    timetable_sql = """
                        SELECT *
                        FROM timetable
                    """

                    timetable_parameters = []

                    if "active" in timetable_columns:

                        timetable_sql += """
                            WHERE (
                                active = 1
                                OR active IS NULL
                            )
                        """

                    order_parts = []

                    if "start_time" in timetable_columns:
                        order_parts.append(
                            "start_time"
                        )

                    if "id" in timetable_columns:
                        order_parts.append(
                            "id"
                        )

                    if order_parts:

                        timetable_sql += (
                            " ORDER BY "
                            + ", ".join(order_parts)
                        )

                    timetable_rows = conn.execute(
                        timetable_sql,
                        timetable_parameters
                    ).fetchall()

                    for row in timetable_rows:

                        row_dict = dict(row)

                        row_day = str(
                            row_dict.get("day")
                            or ""
                        ).strip().lower()

                        if row_day in valid_days:

                            classes.append(row)

            except Exception as fallback_error:

                print(
                    "ADMIN ATTENDANCE TIMETABLE "
                    "FALLBACK ERROR:",
                    fallback_error
                )

                classes = []


        # ========================================================
        # NORMALIZE CLASSES
        # ========================================================

        normalized_classes = []

        for item in classes:

            item = dict(item)


            # ----------------------------------------------------
            # TIMETABLE ID
            # ----------------------------------------------------

            if item.get("id") is None:

                item["id"] = item.get(
                    "timetable_id"
                )


            # ----------------------------------------------------
            # SUBJECT
            # ----------------------------------------------------

            item["subject_name"] = (
                item.get("subject_name")
                or item.get("subject")
                or item.get("course_name")
                or item.get("course_code")
                or item.get("class_name")
                or "Class"
            )


            # ----------------------------------------------------
            # COURSE CODE
            # ----------------------------------------------------

            item["course_code"] = (
                item.get("course_code")
                or item.get("course")
                or ""
            )


            # ----------------------------------------------------
            # FACULTY
            # ----------------------------------------------------

            item["faculty_name"] = (
                item.get("faculty_name")
                or item.get("faculty")
                or "-"
            )


            # ----------------------------------------------------
            # CLASS / SECTION
            # ----------------------------------------------------

            raw_class_name = str(
                item.get("class_section")
                or item.get("class_name")
                or item.get("section")
                or ""
            ).strip()


            # DATABASE:
            # IV B.Tech ECE AI
            #
            # DISPLAY:
            # IV B.Tech ECE A

            if raw_class_name == (
                "IV B.Tech ECE AI"
            ):

                item["class_section"] = (
                    "IV B.Tech ECE A"
                )

            else:

                item["class_section"] = (
                    raw_class_name
                    or "-"
                )


            # ----------------------------------------------------
            # ROOM
            # ----------------------------------------------------

            item["room_no"] = (
                item.get("room_no")
                or item.get("room")
                or item.get("classroom")
                or "-"
            )


            # ----------------------------------------------------
            # START TIME
            # ----------------------------------------------------

            item["start_time"] = (
                item.get("start_time")
                or item.get("from_time")
                or item.get("start")
                or ""
            )


            # ----------------------------------------------------
            # END TIME
            # ----------------------------------------------------

            item["end_time"] = (
                item.get("end_time")
                or item.get("to_time")
                or item.get("end")
                or ""
            )


            normalized_classes.append(item)


        classes = normalized_classes


        # ========================================================
        # FIND SELECTED CLASS
        # ========================================================

        selected_class = None

        if selected_timetable_id is not None:

            for item in classes:

                try:

                    item_id = int(
                        item.get("id")
                    )

                except (
                    ValueError,
                    TypeError
                ):

                    continue


                if item_id == selected_timetable_id:

                    selected_class = item

                    break


        # ========================================================
        # INITIAL COUNTS
        # ========================================================

        attendance_records = []

        total_students = 0

        present_count = 0

        absent_count = 0

        unmarked_count = 0


        # ========================================================
        # LOAD SELECTED CLASS ATTENDANCE
        # ========================================================

        if selected_class is not None:

            timetable_id = selected_class.get(
                "id"
            )


            # ====================================================
            # DATABASE COLUMNS
            # ====================================================

            student_columns = {

                row["name"]

                for row in conn.execute(
                    "PRAGMA table_info(students)"
                ).fetchall()

            }


            attendance_columns = {

                row["name"]

                for row in conn.execute(
                    "PRAGMA table_info(attendance)"
                ).fetchall()

            }


            # ====================================================
            # DEBUG
            # ====================================================

            print()
            print(
                "========== ADMIN ATTENDANCE =========="
            )

            print(
                "Selected date:",
                selected_date
            )

            print(
                "Selected timetable:",
                timetable_id
            )

            print(
                "Selected class:",
                selected_class.get(
                    "class_section"
                )
            )

            print(
                "Student columns:",
                student_columns
            )

            print(
                "Attendance columns:",
                attendance_columns
            )


            # ====================================================
            # STUDENT PRIMARY KEY
            # ====================================================

            student_pk_column = None

            for candidate in (
                "id",
                "student_id"
            ):

                if candidate in student_columns:

                    student_pk_column = candidate

                    break


            if student_pk_column is None:

                raise RuntimeError(
                    "Students table must contain "
                    "'id' or 'student_id'."
                )


            student_pk_sql = (
                f's."{student_pk_column}"'
            )


            # ====================================================
            # ROLL NUMBER
            # ====================================================

            roll_number_column = None

            for candidate in (
                "roll_number",
                "roll_no",
                "registration_number",
                "reg_no",
                "hall_ticket_no",
                "roll",
                "student_id"
            ):

                if candidate in student_columns:

                    roll_number_column = candidate

                    break


            if roll_number_column:

                roll_number_sql = (
                    f's."{roll_number_column}"'
                )

            else:

                roll_number_sql = "NULL"


            # ====================================================
            # STUDENT NAME
            # ====================================================

            student_name_column = None

            for candidate in (
                "name",
                "student_name",
                "full_name"
            ):

                if candidate in student_columns:

                    student_name_column = candidate

                    break


            if student_name_column:

                student_name_sql = (
                    f's."{student_name_column}"'
                )

            else:

                student_name_sql = "''"


            # ====================================================
            # STUDENT SECTION
            # ====================================================

            student_class_column = None

            for candidate in (
                "class_name",
                "class_section",
                "section",
                "class"
            ):

                if candidate in student_columns:

                    student_class_column = candidate

                    break


            # ====================================================
            # DISPLAY CLASS NAME
            # ====================================================

            display_class_name = str(

                selected_class.get(
                    "class_section"
                )
                or selected_class.get(
                    "class_name"
                )
                or selected_class.get(
                    "section"
                )
                or ""
            ).strip()


            # ====================================================
            # CLASS ALIASES
            # ====================================================

            class_aliases = []

            if display_class_name == (
                "IV B.Tech ECE A"
            ):

                class_aliases = [

                    "IV B.Tech ECE A",

                    "IV B.Tech ECE AI"

                ]

            elif display_class_name:

                class_aliases = [

                    display_class_name

                ]


            # ====================================================
            # BUILD CLASS FILTER
            # ====================================================

            class_sql = ""

            class_parameters = []


            if (
                student_class_column
                and class_aliases
            ):

                placeholders = ",".join(
                    "?"
                    for _ in class_aliases
                )


                class_sql = f"""
                    AND LOWER(
                        TRIM(
                            COALESCE(
                                s."{student_class_column}",
                                ''
                            )
                        )
                    ) IN (
                        {placeholders}
                    )
                """


                class_parameters = [

                    value.lower().strip()

                    for value
                    in class_aliases

                ]


            # ====================================================
            # EXCLUDED STUDENTS
            # ====================================================

            exclude_sql = ""

            exclude_parameters = []


            if roll_number_column:

                exclude_sql = f"""
                    AND TRIM(
                        CAST(
                            {roll_number_sql}
                            AS TEXT
                        )
                    ) NOT IN (?, ?)
                """


                exclude_parameters = [

                    "23321A0465",

                    "23321A0466"

                ]


            # ====================================================
            # ATTENDANCE STUDENT COLUMN
            # ====================================================

            attendance_student_column = None

            for candidate in (
                "student_id",
                "student_db_id",
                "student",
                "studentid"
            ):

                if candidate in attendance_columns:

                    attendance_student_column = candidate

                    break


            # ====================================================
            # ATTENDANCE TIMETABLE COLUMN
            # ====================================================

            attendance_timetable_column = None

            for candidate in (
                "timetable_id",
                "class_id",
                "schedule_id"
            ):

                if candidate in attendance_columns:

                    attendance_timetable_column = candidate

                    break


            # ====================================================
            # ATTENDANCE DATE COLUMN
            # ====================================================

            attendance_date_column = None

            for candidate in (
                "date",
                "attendance_date"
            ):

                if candidate in attendance_columns:

                    attendance_date_column = candidate

                    break


            # ====================================================
            # ATTENDANCE TIME COLUMN
            # ====================================================

            attendance_time_column = None

            for candidate in (
                "time",
                "attendance_time",
                "marked_time",
                "check_in_time"
            ):

                if candidate in attendance_columns:

                    attendance_time_column = candidate

                    break


            # ====================================================
            # BUILD ATTENDANCE JOIN
            # ====================================================

            attendance_join = ""

            attendance_parameters = []


            if (
                attendance_student_column
                and attendance_timetable_column
                and attendance_date_column
            ):

                # ------------------------------------------------
                # IMPORTANT:
                #
                # Some systems store attendance.student_id as
                # students.id.
                #
                # Other systems store attendance.student_id as
                # roll number.
                #
                # Therefore we check BOTH.
                # ------------------------------------------------

                db_id_match = f"""
                    CAST(
                        a."{attendance_student_column}"
                        AS TEXT
                    )
                    =
                    CAST(
                        {student_pk_sql}
                        AS TEXT
                    )
                """


                roll_match = "0 = 1"


                if roll_number_column:

                    roll_match = f"""
                        CAST(
                            a."{attendance_student_column}"
                            AS TEXT
                        )
                        =
                        CAST(
                            {roll_number_sql}
                            AS TEXT
                        )
                    """


                attendance_join = f"""

                    LEFT JOIN attendance AS a

                        ON (
                            {db_id_match}
                            OR
                            {roll_match}
                        )

                        AND CAST(
                            a."{attendance_timetable_column}"
                            AS TEXT
                        )
                        =
                        CAST(? AS TEXT)

                        AND DATE(
                            a."{attendance_date_column}"
                        )
                        =
                        DATE(?)

                """


                attendance_parameters = [

                    timetable_id,

                    selected_date

                ]


            else:

                attendance_join = """

                    LEFT JOIN attendance AS a

                        ON 1 = 0

                """


            # ====================================================
            # ATTENDANCE SELECT COLUMNS
            # ====================================================

            if "id" in attendance_columns:

                attendance_id_sql = (
                    'a."id" AS attendance_id'
                )

            else:

                attendance_id_sql = (
                    "NULL AS attendance_id"
                )


            if "status" in attendance_columns:

                attendance_status_sql = (
                    'a."status" AS attendance_status'
                )

            else:

                attendance_status_sql = (
                    "NULL AS attendance_status"
                )


            if attendance_date_column:

                attendance_date_sql = (
                    f'a."{attendance_date_column}" '
                    "AS attendance_date"
                )

            else:

                attendance_date_sql = (
                    "NULL AS attendance_date"
                )


            if attendance_time_column:

                attendance_time_sql = (
                    f'a."{attendance_time_column}" '
                    "AS attendance_time"
                )

            else:

                attendance_time_sql = (
                    "NULL AS attendance_time"
                )


            # ====================================================
            # MAIN STUDENT QUERY
            # ====================================================

            query = f"""

                SELECT

                    {student_pk_sql}
                        AS student_db_id,

                    {roll_number_sql}
                        AS roll_number,

                    {student_name_sql}
                        AS student_name,

                    {attendance_id_sql},

                    {attendance_status_sql},

                    {attendance_date_sql},

                    {attendance_time_sql}

                FROM students AS s

                {attendance_join}

                WHERE 1 = 1

                {class_sql}

                {exclude_sql}

                ORDER BY

                    {roll_number_sql}
                    COLLATE NOCASE,

                    {student_name_sql}
                    COLLATE NOCASE

            """


            query_parameters = (

                attendance_parameters

                + class_parameters

                + exclude_parameters

            )


            # ====================================================
            # FIRST QUERY
            # ====================================================

            print(
                "SQL PARAMETERS:",
                query_parameters
            )


            rows = conn.execute(
                query,
                query_parameters
            ).fetchall()


            print(
                "FIRST QUERY ROW COUNT:",
                len(rows)
            )


            # ====================================================
            # CRITICAL FALLBACK
            #
            # If section/class filtering produced ZERO students,
            # retry WITHOUT section filtering.
            #
            # This prevents:
            #
            # "No attendance records found"
            #
            # when timetable class name and student section
            # names don't exactly match.
            # ====================================================

            if len(rows) == 0:

                print(
                    "CLASS FILTER RETURNED 0 STUDENTS."
                )

                print(
                    "RETRYING WITHOUT STUDENT CLASS FILTER..."
                )


                query_without_class = f"""

                    SELECT

                        {student_pk_sql}
                            AS student_db_id,

                        {roll_number_sql}
                            AS roll_number,

                        {student_name_sql}
                            AS student_name,

                        {attendance_id_sql},

                        {attendance_status_sql},

                        {attendance_date_sql},

                        {attendance_time_sql}

                    FROM students AS s

                    {attendance_join}

                    WHERE 1 = 1

                    {exclude_sql}

                    ORDER BY

                        {roll_number_sql}
                        COLLATE NOCASE,

                        {student_name_sql}
                        COLLATE NOCASE

                """


                fallback_parameters = (

                    attendance_parameters

                    + exclude_parameters

                )


                rows = conn.execute(
                    query_without_class,
                    fallback_parameters
                ).fetchall()


                print(
                    "FALLBACK ROW COUNT:",
                    len(rows)
                )


            print(
                "FINAL ROW COUNT:",
                len(rows)
            )


            print(
                "FIRST ROWS:",
                [
                    dict(row)
                    for row in rows[:5]
                ]
            )


            # ====================================================
            # PARSE CLASS TIME
            # ====================================================

            def parse_time_value(value):

                if not value:

                    return None


                value = str(
                    value
                ).strip()


                formats = (

                    "%H:%M:%S",

                    "%H:%M",

                    "%I:%M %p",

                    "%I:%M:%S %p",

                    "%I.%M %p",

                    "%I.%M:%S %p"

                )


                for fmt in formats:

                    try:

                        return datetime.strptime(
                            value,
                            fmt
                        ).time()

                    except ValueError:

                        continue


                return None


            start_time = parse_time_value(

                selected_class.get(
                    "start_time"
                )

            )


            end_time = parse_time_value(

                selected_class.get(
                    "end_time"
                )

            )


            # ====================================================
            # DATE / CLASS STATE
            # ====================================================

            today = date.today()

            now = datetime.now()


            is_past_date = (
                selected_date_obj < today
            )


            is_today = (
                selected_date_obj == today
            )


            is_future_date = (
                selected_date_obj > today
            )


            class_ongoing = False

            class_completed = False


            if is_today:

                current_time = now.time()


                if (
                    start_time is not None
                    and
                    end_time is not None
                ):

                    class_ongoing = (

                        start_time
                        <= current_time
                        < end_time

                    )


                    class_completed = (

                        current_time
                        >= end_time

                    )


                elif start_time is not None:

                    # If no end time exists,
                    # don't mark missing attendance absent.

                    class_ongoing = (

                        current_time
                        >= start_time

                    )


                    class_completed = False


            # ====================================================
            # BUILD RECORDS
            # ====================================================

            for row in rows:

                record = dict(row)


                raw_status = str(

                    record.get(
                        "attendance_status"
                    )
                    or ""

                ).strip().lower()


                # =================================================
                # STATUS
                # =================================================

                if raw_status in (
                    "present",
                    "p"
                ):

                    display_status = "Present"


                elif raw_status in (
                    "late",
                    "l"
                ):

                    display_status = "Late"


                elif raw_status in (
                    "absent",
                    "a"
                ):

                    display_status = "Absent"


                elif is_future_date:

                    display_status = "Unmarked"


                elif is_today:

                    if class_completed:

                        display_status = "Absent"

                    else:

                        # TODAY BEFORE / DURING CLASS
                        #
                        # Missing attendance must NOT
                        # become absent.

                        display_status = "Unmarked"


                elif is_past_date:

                    # Past class:
                    # no attendance row = absent.

                    display_status = "Absent"


                else:

                    display_status = "Unmarked"


                # =================================================
                # COUNTS
                # =================================================

                if display_status in (
                    "Present",
                    "Late"
                ):

                    present_count += 1


                elif display_status == "Absent":

                    absent_count += 1


                else:

                    unmarked_count += 1


                # =================================================
                # ROLL NUMBER
                # =================================================

                roll_number = str(

                    record.get(
                        "roll_number"
                    )
                    or ""

                ).strip()


                # =================================================
                # NAME
                # =================================================

                student_name = str(

                    record.get(
                        "student_name"
                    )
                    or "Student"

                ).strip()


                # =================================================
                # CLASS DISPLAY
                # =================================================

                class_section = str(

                    selected_class.get(
                        "class_section"
                    )
                    or selected_class.get(
                        "class_name"
                    )
                    or selected_class.get(
                        "section"
                    )
                    or "-"

                ).strip()


                if class_section == (
                    "IV B.Tech ECE AI"
                ):

                    class_section = (
                        "IV B.Tech ECE A"
                    )


                # =================================================
                # SUBJECT
                # =================================================

                subject = (

                    selected_class.get(
                        "subject_name"
                    )

                    or selected_class.get(
                        "subject"
                    )

                    or selected_class.get(
                        "course_code"
                    )

                    or "Class"

                )


                # =================================================
                # FACULTY
                # =================================================

                faculty_name = (

                    selected_class.get(
                        "faculty_name"
                    )

                    or selected_class.get(
                        "faculty"
                    )

                    or "-"

                )


                # =================================================
                # ATTENDANCE TIME
                # =================================================

                attendance_time = (

                    record.get(
                        "attendance_time"
                    )

                    or selected_class.get(
                        "start_time"
                    )

                    or "--"

                )


                # =================================================
                # APPEND RECORD
                # =================================================

                attendance_records.append({

                    "student_id":
                        record.get(
                            "student_db_id"
                        ),

                    "roll_number":
                        roll_number or "-",

                    "student_name":
                        student_name,

                    "subject":
                        subject,

                    "course_code":
                        (
                            selected_class.get(
                                "course_code"
                            )
                            or "-"
                        ),

                    "faculty":
                        faculty_name,

                    "class_section":
                        class_section,

                    "date":
                        selected_date,

                    "time":
                        attendance_time,

                    "status":
                        display_status

                })


            # ====================================================
            # SORT
            # ====================================================

            status_order = {

                "absent": 0,

                "present": 1,

                "late": 1,

                "unmarked": 2

            }


            attendance_records.sort(

                key=lambda record: (

                    status_order.get(

                        str(

                            record.get(
                                "status"
                            )

                            or "Unmarked"

                        ).strip().lower(),

                        2

                    ),

                    str(

                        record.get(
                            "roll_number"
                        )

                        or ""

                    ).strip()

                )

            )


            # ====================================================
            # TOTAL STUDENTS
            # ====================================================

            total_students = len(
                attendance_records
            )


            print(
                "TOTAL STUDENTS:",
                total_students
            )

            print(
                "PRESENT:",
                present_count
            )

            print(
                "ABSENT:",
                absent_count
            )

            print(
                "UNMARKED:",
                unmarked_count
            )

            print(
                "======================================"
            )


        # ========================================================
        # NO CLASS SELECTED
        # ========================================================

        else:

            print(
                "ADMIN ATTENDANCE: "
                "NO SELECTED CLASS"
            )


        # ========================================================
        # DISPLAY DATE
        # ========================================================

        try:

            display_date = datetime.strptime(
                selected_date,
                "%Y-%m-%d"
            ).strftime(
                "%d/%m/%Y"
            )

        except (
            ValueError,
            TypeError
        ):

            display_date = selected_date


        # ========================================================
        # RENDER TEMPLATE
        # ========================================================

        return render_template(

            "admin_attendance.html",

            selected_date=
                selected_date,

            display_date=
                display_date,

            classes=
                classes,

            selected_timetable_id=
                selected_timetable_id,

            selected_class=
                selected_class,

            attendance_records=
                attendance_records,

            total_students=
                total_students,

            present_count=
                present_count,

            absent_count=
                absent_count,

            unmarked_count=
                unmarked_count

        )


    finally:

        conn.close()
# ============================================================
# ADMIN - NOTIFY TODAY'S ABSENTEES
# ============================================================

@app.route(
    "/admin/attendance/notify-absentees",
    methods=["POST"]
)
@role_required("admin")
def admin_notify_today_absentees():

    try:

        result = notify_today_absentees(
            get_db_connection_function=get_db_connection,
            get_day_aliases_function=get_day_aliases,
            send_email=True,
            send_whatsapp=True
        )

        total = result.get(
            "total_absentees",
            0
        )

        emails_sent = result.get(
            "emails_sent",
            0
        )

        whatsapp_sent = result.get(
            "whatsapp_sent",
            0
        )

        skipped = result.get(
            "skipped",
            0
        )

        emails_failed = result.get(
            "emails_failed",
            0
        )

        whatsapp_failed = result.get(
            "whatsapp_failed",
            0
        )

        flash(
            (
                f"Today's absentee notifications processed. "
                f"Absentees: {total}, "
                f"Emails sent: {emails_sent}, "
                f"WhatsApp sent: {whatsapp_sent}, "
                f"Skipped: {skipped}, "
                f"Email failures: {emails_failed}, "
                f"WhatsApp failures: {whatsapp_failed}."
            ),
            "success"
        )

    except Exception as exc:

        app.logger.exception(
            "Failed to send absentee notifications"
        )

        flash(
            f"Unable to send absentee notifications: {exc}",
            "danger"
        )

    return redirect(
        url_for(
            "admin_attendance_history"
        )
    )
# ============================================================
# ADMIN ATTENDANCE HISTORY API
# ============================================================

@app.route("/api/admin/attendance")
@role_required("admin")
def api_admin_attendance_history():

    selected_date = request.args.get(
        "date",
        date.today().isoformat()
    ).strip()

    timetable_id = request.args.get(
        "timetable_id",
        ""
    ).strip()

    try:
        date.fromisoformat(selected_date)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Invalid date."
        }), 400

    conn = get_db_connection()

    try:
        classes = scheduled_classes_for_date(
            conn,
            selected_date
        )

        if not timetable_id:
            return jsonify({
                "success": True,
                "classes": [
                    dict(row)
                    for row in classes
                ],
                "records": []
            })

        try:
            selected_id = int(timetable_id)
        except ValueError:
            return jsonify({
                "success": False,
                "message": "Invalid class selection."
            }), 400

        timetable = conn.execute(
            """
            SELECT *
            FROM timetable
            WHERE id = ?
              AND (active = 1 OR active IS NULL)
            """,
            (selected_id,)
        ).fetchone()

        if timetable is None:
            return jsonify({
                "success": False,
                "message": "Class not found."
            }), 404

        valid_days = {
            item.lower()
            for item in get_day_aliases(selected_date)
        }

        if str(timetable["day"] or "").strip().lower() not in valid_days:
            return jsonify({
                "success": False,
                "message": "Class is not scheduled on that date."
            }), 400

        records = _class_attendance_rows(
            conn,
            timetable,
            selected_date
        )

        return jsonify({
            "success": True,
            "classes": [],
            "records": records,
            "class_info": {
                "subject": timetable_subject(timetable),
                "faculty": (
                    timetable["faculty_name"]
                    if "faculty_name" in timetable.keys()
                    and timetable["faculty_name"]
                    else (
                        timetable["faculty"]
                        if "faculty" in timetable.keys()
                        else "-"
                    )
                ),
                "start_time": timetable["start_time"],
                "end_time": timetable["end_time"],
                "room_no": timetable_room(timetable),
                "date": selected_date
            }
        })

    finally:
        conn.close()


# ============================================================
# TEST ROUTE
# ============================================================

@app.route("/test")
def test():

    return """
    <h1>Intelligent Student Attendance System</h1>
    <p>Flask server is running successfully.</p>
    """


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    return """
    <h1>404 - Page Not Found</h1>
    <p>The requested page does not exist.</p>
    """, 404


@app.errorhandler(500)
def internal_server_error(error):

    app.logger.exception(
        "Internal server error: %s",
        error
    )

    return """
    <h1>500 - Internal Server Error</h1>
    <p>Something went wrong on the server. Check the Flask terminal for details.</p>
    """, 500


# ============================================================
# STUDENT TIMETABLE
# ============================================================

def get_student_or_redirect():
    student = get_logged_in_student()
    if student is None:
        session.clear()
        return None
    return student


def normalize_weekday(value):
    value = str(value or "").strip().lower()
    aliases = {
        "mon": "monday",
        "tue": "tuesday", "tues": "tuesday",
        "wed": "wednesday",
        "thu": "thursday", "thur": "thursday", "thurs": "thursday",
        "fri": "friday",
        "sat": "saturday",
        "sun": "sunday",
    }
    return aliases.get(value, value)


# ============================================================
# STUDENT ATTENDANCE HISTORY
# ============================================================

@app.route("/student/history")
@role_required("student")
def student_attendance_history():
    student = get_student_or_redirect()
    if student is None:
        return redirect(url_for("login"))

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    try:
        if start_date:
            date.fromisoformat(start_date)

        if end_date:
            date.fromisoformat(end_date)

        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date

    except ValueError:
        flash("Please select valid dates.", "error")
        start_date, end_date = "", ""

    sql = """
        SELECT
            a.date,
            a.time,
            a.status,
            t.subject,
            t.class_name,
            t.start_time,
            t.end_time,
            t.room,
            t.room_no
        FROM attendance AS a
        LEFT JOIN timetable AS t
            ON t.id = a.timetable_id
        WHERE a.student_id = ?
    """

    params = [student["id"]]

    if start_date:
        sql += " AND a.date >= ?"
        params.append(start_date)

    if end_date:
        sql += " AND a.date <= ?"
        params.append(end_date)

    sql += " ORDER BY a.date DESC, t.start_time ASC"

    conn = get_db_connection()

    try:
        records = [
            dict(row)
            for row in conn.execute(sql, params).fetchall()
        ]

        present_count = sum(
            1 for row in records
            if str(row.get("status") or "").lower()
            in ("present", "late")
        )

        total_count = len(records)

        percentage = (
            round(present_count * 100 / total_count, 1)
            if total_count else 0
        )

        return render_template(
            "student_history.html",
            student=student,
            records=records,
            start_date=start_date,
            end_date=end_date,
            present_count=present_count,
            total_count=total_count,
            percentage=percentage,
            active_page="history"
        )

    finally:
        conn.close()


# ============================================================
# STUDENT PROFILE AND PASSWORD CHANGE
# ============================================================

@app.route("/student/profile", methods=["GET", "POST"])
@role_required("student")
def student_profile():
    student = get_student_or_redirect()
    if student is None:
        return redirect(url_for("login"))

    conn = get_db_connection()

    try:
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(students)"
            ).fetchall()
        }

        editable_fields = [
            field for field in (
                "name", "department", "year", "section", "email"
            )
            if field in columns
        ]

        password_column = next(
            (
                field for field in (
                    "password_hash", "password", "password_digest"
                )
                if field in columns
            ),
            None
        )

        if request.method == "POST":
            action = request.form.get("action", "profile")

            if action == "profile":
                values = {
                    field: request.form.get(field, "").strip() or None
                    for field in editable_fields
                }

                if "name" in values and not values["name"]:
                    flash("Name cannot be empty.", "error")
                    return redirect(url_for("student_profile"))

                if values:
                    assignments = ", ".join(
                        f'"{field}" = ?' for field in values
                    )

                    conn.execute(
                        f"UPDATE students SET {assignments} WHERE id = ?",
                        [*values.values(), student["id"]]
                    )
                    conn.commit()
                    flash("Profile updated successfully.", "success")

                return redirect(url_for("student_profile"))

            if action == "password":
                current_password = request.form.get(
                    "current_password", ""
                )
                new_password = request.form.get("new_password", "")
                confirm_password = request.form.get(
                    "confirm_password", ""
                )

                if not password_column:
                    flash(
                        "Password changes are not configured for your "
                        "students table.",
                        "error"
                    )

                elif len(new_password) < 8:
                    flash(
                        "Your new password must contain at least "
                        "8 characters.",
                        "error"
                    )

                elif new_password != confirm_password:
                    flash("The new passwords do not match.", "error")

                else:
                    row = conn.execute(
                        f'SELECT "{password_column}" FROM students WHERE id = ?',
                        (student["id"],)
                    ).fetchone()

                    try:
                        valid_password = bool(
                            row
                            and row[0]
                            and check_password_hash(
                                row[0], current_password
                            )
                        )
                    except (ValueError, TypeError):
                        valid_password = False

                    if not valid_password:
                        flash(
                            "Current password is incorrect, or the "
                            "existing login does not use Werkzeug hashes.",
                            "error"
                        )
                    else:
                        conn.execute(
                            f'UPDATE students SET "{password_column}" = ? '
                            "WHERE id = ?",
                            (
                                generate_password_hash(new_password),
                                student["id"]
                            )
                        )
                        conn.commit()
                        flash("Password changed successfully.", "success")

                return redirect(url_for("student_profile"))

        row = conn.execute(
            "SELECT * FROM students WHERE id = ?",
            (student["id"],)
        ).fetchone()

        profile = dict(row) if row else dict(student)

        return render_template(
            "student_profile.html",
            student=profile,
            editable_fields=editable_fields,
            password_enabled=bool(password_column),
            active_page="profile"
        )

    finally:
        conn.close()
@app.route("/admin/test-attendance-email")
@role_required("admin")
def test_attendance_email():

    result = notify_completed_timetable_absentees(
        get_db_connection_function=get_db_connection,
        timetable_id=28,
        attendance_date="2026-10-26"
    )

    return jsonify(result)


# ============================================================
# START FLASK
# ============================================================

if __name__ == "__main__":

    import os

    # Local development
    if os.environ.get("RENDER") != "true":

        url = "http://127.0.0.1:5001"

        threading.Timer(
            1.0,
            lambda: webbrowser.open(url)
        ).start()

        app.run(
            host="127.0.0.1",
            port=5001,
            debug=False
        )

    # Cloud / Render
    else:

        app.run(
            host="0.0.0.0",
            port=int(
                os.environ.get(
                    "PORT",
                    5000
                )
            ),
            debug=False
        )
