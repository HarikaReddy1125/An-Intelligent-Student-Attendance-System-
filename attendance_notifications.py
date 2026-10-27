# ============================================================
# attendance_notifications.py
# One BCC email per completed timetable class
# ============================================================

import logging
import os
import re
import smtplib
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("ATTENDANCE_SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("ATTENDANCE_SMTP_PORT", "587"))
SMTP_USERNAME = (os.getenv("ATTENDANCE_SMTP_USERNAME") or
                 os.getenv("MAIL_USERNAME") or
                 "brecwecea2023@gmail.com").strip()
SMTP_PASSWORD = (os.getenv("ATTENDANCE_SMTP_PASSWORD") or
                 os.getenv("MAIL_PASSWORD") or "").strip()
EMAIL_FROM = (os.getenv("ATTENDANCE_EMAIL_FROM") or SMTP_USERNAME).strip()
SMTP_TIMEOUT = 30


def get_db_connection_for_notifications(get_db_connection_function):
    conn = get_db_connection_function()
    if conn.row_factory is None:
        conn.row_factory = sqlite3.Row
    return conn


def get_table_columns(conn, table_name):
    rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    result = set()
    for row in rows:
        try:
            result.add(row["name"])
        except (TypeError, IndexError):
            result.add(row[1])
    return result


def find_first_column(columns, candidates):
    return next((name for name in candidates if name in columns), None)


def ensure_notification_log_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance_notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_key TEXT NOT NULL UNIQUE,
            student_id TEXT NOT NULL,
            timetable_id TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT,
            status TEXT NOT NULL,
            message TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def notification_already_sent(conn, notification_key):
    row = conn.execute("""
        SELECT 1 FROM attendance_notification_log
        WHERE notification_key = ? AND status = 'sent' LIMIT 1
    """, (str(notification_key),)).fetchone()
    return row is not None


def save_notification_result(conn, notification_key, student_id,
                             timetable_id, attendance_date, recipient,
                             status, message):
    conn.execute("""
        INSERT INTO attendance_notification_log
        (notification_key, student_id, timetable_id, attendance_date,
         channel, recipient, status, message, created_at)
        VALUES (?, ?, ?, ?, 'email', ?, ?, ?, ?)
        ON CONFLICT(notification_key) DO UPDATE SET
            recipient = excluded.recipient,
            status = excluded.status,
            message = excluded.message,
            created_at = excluded.created_at
    """, (str(notification_key), str(student_id), str(timetable_id),
          str(attendance_date), recipient or "", status, message or "",
          datetime.now().isoformat(timespec="seconds")))
    conn.commit()


def parse_time_value(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p",
                "%I:%M:%S %p", "%I.%M %p", "%I.%M:%S %p"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def get_class_end_time(timetable):
    return parse_time_value(timetable.get("end_time") or
                             timetable.get("to_time") or
                             timetable.get("end") or "")


def class_has_finished(class_date, timetable_row):
    if class_date < date.today():
        return True
    if class_date > date.today():
        return False
    end_time = get_class_end_time(timetable_row)
    return bool(end_time and datetime.now().time() >= end_time)


def normalize_class_name(value):
    value = re.sub(r"\s+", " ", str(value or "").strip().upper())
    if value in ("IV B.TECH ECE AI", "IV BTECH ECE AI"):
        return value.replace(" AI", " A")
    return value


def class_names_match(timetable_class, student_class):
    timetable_class = normalize_class_name(timetable_class)
    student_class = normalize_class_name(student_class)
    if not timetable_class:
        return True
    if not student_class:
        return False
    if timetable_class == student_class:
        return True
    if re.fullmatch(r"[A-Z]", student_class):
        return timetable_class.split()[-1] == student_class
    return False


def get_timetable_class(timetable):
    return (timetable.get("class_section") or timetable.get("class_name") or
            timetable.get("section") or timetable.get("class") or "")


def get_timetable_subject(timetable):
    return (timetable.get("subject_name") or timetable.get("subject") or
            timetable.get("course_name") or timetable.get("course_code") or
            "Scheduled class")


def get_timetable_faculty(timetable):
    return timetable.get("faculty_name") or timetable.get("faculty") or "-"


def get_timetable_start_time(timetable):
    return (timetable.get("start_time") or timetable.get("from_time") or
            timetable.get("start") or "")


def get_timetable_end_time(timetable):
    return (timetable.get("end_time") or timetable.get("to_time") or
            timetable.get("end") or "")


def get_notification_schema(conn):
    students = get_table_columns(conn, "students")
    attendance = get_table_columns(conn, "attendance")
    timetable = get_table_columns(conn, "timetable")
    schema = {
        "student_pk": find_first_column(students, ("id", "student_db_id")),
        "student_name": find_first_column(students, ("name", "student_name", "full_name")),
        "student_email": find_first_column(students, ("email", "student_email",
                                                       "email_address", "mail",
                                                       "official_email")),
        "student_section": find_first_column(students, ("section", "class_section",
                                                         "class_name", "class")),
        "student_active": find_first_column(students, ("active", "is_active")),
        "attendance_student": find_first_column(attendance, ("student_id",
            "student_db_id", "student", "studentid")),
        "attendance_timetable": find_first_column(attendance, ("timetable_id",
            "class_id", "schedule_id")),
        "attendance_date": find_first_column(attendance, ("date", "attendance_date")),
        "attendance_status": find_first_column(attendance, ("status",)),
        "timetable_pk": find_first_column(timetable, ("id", "timetable_id")),
    }
    required = ("student_pk", "student_name", "student_email",
                "attendance_student", "attendance_timetable",
                "attendance_date", "attendance_status", "timetable_pk")
    missing = [key for key in required if not schema[key]]
    if missing:
        raise RuntimeError("Required database columns could not be identified: " +
                           ", ".join(missing))
    return schema


def get_timetable_by_id(conn, timetable_id):
    columns = get_table_columns(conn, "timetable")
    id_column = find_first_column(columns, ("id", "timetable_id"))
    if not id_column:
        raise RuntimeError("Timetable ID column was not found.")
    row = conn.execute(
        f'SELECT * FROM timetable WHERE "{id_column}" = ? LIMIT 1',
        (timetable_id,)).fetchone()
    return dict(row) if row else None


def get_absentees_for_timetable(conn, timetable_id, attendance_date):
    schema = get_notification_schema(conn)
    timetable = get_timetable_by_id(conn, timetable_id)
    if not timetable:
        raise RuntimeError(f"Timetable {timetable_id} was not found.")
    if isinstance(attendance_date, str):
        attendance_date = date.fromisoformat(attendance_date[:10])

    fields = [
        f's."{schema["student_pk"]}" AS student_db_id',
        f's."{schema["student_name"]}" AS student_name',
        f's."{schema["student_email"]}" AS email',
    ]
    if schema["student_section"]:
        fields.append(f's."{schema["student_section"]}" AS student_class')
    else:
        fields.append("'' AS student_class")
    query = f'SELECT {", ".join(fields)} FROM students s'
    if schema["student_active"]:
        query += (f' WHERE (s."{schema["student_active"]}" = 1'
                  f' OR s."{schema["student_active"]}" IS NULL)')
    students = conn.execute(query).fetchall()
    absentees = []
    for row in students:
        student = dict(row)
        if get_timetable_class(timetable) and not class_names_match(
                get_timetable_class(timetable), student.get("student_class")):
            continue
        attendance_row = conn.execute(f"""
            SELECT "{schema['attendance_status']}" AS status
            FROM attendance
            WHERE CAST("{schema['attendance_student']}" AS TEXT) = CAST(? AS TEXT)
              AND CAST("{schema['attendance_timetable']}" AS TEXT) = CAST(? AS TEXT)
              AND DATE("{schema['attendance_date']}") = DATE(?)
            ORDER BY rowid DESC LIMIT 1
        """, (student["student_db_id"], timetable_id,
              attendance_date.isoformat())).fetchone()
        status = str(attendance_row["status"] or "").strip().lower() if attendance_row else ""
        is_absent = attendance_row is None or status in ("absent", "a")
        if is_absent and student.get("email") and str(student["email"]).strip():
            student.update({
                "timetable_id": timetable_id,
                "date": attendance_date.isoformat(),
                "subject": get_timetable_subject(timetable),
                "faculty": get_timetable_faculty(timetable),
                "start_time": get_timetable_start_time(timetable),
                "end_time": get_timetable_end_time(timetable),
                "class_section": get_timetable_class(timetable),
            })
            absentees.append(student)
    return timetable, absentees


def send_bcc_absentee_email(recipients, subject, body):
    """Send exactly one SMTP message with all student addresses hidden in BCC."""
    recipients = sorted({str(address).strip() for address in recipients
                         if address and str(address).strip()})
    if not recipients:
        return False, "No valid recipient email addresses."
    if not SMTP_USERNAME:
        return False, "SMTP username is not configured."
    if not SMTP_PASSWORD:
        return False, "SMTP password is not configured. Set ATTENDANCE_SMTP_PASSWORD or MAIL_PASSWORD."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = "Undisclosed recipients"
    message["Bcc"] = ", ".join(recipients)
    message.set_content(body)
    try:
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message, to_addrs=recipients)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message, to_addrs=recipients)
        return True, f"SMTP accepted one BCC email for {len(recipients)} recipients."
    except Exception as exc:
        logger.error("BCC absentee email failed: %s", exc)
        return False, str(exc)


def notify_completed_timetable_absentees(
        get_db_connection_function, timetable_id, attendance_date,
        send_email=True, send_whatsapp=False):
    """Send one identical BCC email for absentees of one completed class."""
    result = {"status": "success", "total_absentees": 0,
              "emails_sent": 0, "emails_failed": 0, "skipped": 0}
    conn = get_db_connection_for_notifications(get_db_connection_function)
    try:
        ensure_notification_log_table(conn)
        if isinstance(attendance_date, datetime):
            attendance_date = attendance_date.date()
        elif isinstance(attendance_date, str):
            attendance_date = date.fromisoformat(attendance_date[:10])
        if not isinstance(attendance_date, date):
            result.update(status="failed", reason="Invalid attendance date.")
            return result

        timetable, absentees = get_absentees_for_timetable(
            conn, timetable_id, attendance_date)
        result["total_absentees"] = len(absentees)
        if not absentees:
            result["message"] = "No absent students found."
            return result
        if not send_email:
            result.update(status="disabled", skipped=len(absentees))
            return result

        pending = []
        for student in absentees:
            key = f"{timetable_id}:{attendance_date.isoformat()}:{student['student_db_id']}:email"
            if notification_already_sent(conn, key):
                result["skipped"] += 1
            else:
                pending.append((student, key))

        if not pending:
            result["message"] = "Notifications were already sent."
            return result

        recipients = [student["email"] for student, _ in pending]
        subject = f"Attendance Notification - {get_timetable_subject(timetable)}"
        class_name = get_timetable_class(timetable)
        start_time = get_timetable_start_time(timetable)
        end_time = get_timetable_end_time(timetable)
        time_text = f"{start_time} - {end_time}".strip(" -") or "Scheduled class"
        body_lines = [
            "Dear Student,",
            "",
            "You were marked absent for the scheduled class.",
            "",
            f"Subject: {get_timetable_subject(timetable)}",
        ]
        if class_name:
            body_lines.append(f"Class: {class_name}")
        body_lines.extend([
            f"Faculty: {get_timetable_faculty(timetable)}",
            f"Date: {attendance_date.strftime('%d/%m/%Y')}",
            f"Time: {time_text}",
            "",
            "If you believe this attendance record is incorrect, please contact the concerned faculty.",
            "",
            "Regards,",
            "Student Attendance System",
        ])
        ok, message = send_bcc_absentee_email(recipients, subject, "\n".join(body_lines))
        if ok:
            result["emails_sent"] = 1  # one SMTP email, delivered to BCC recipients
            for student, key in pending:
                save_notification_result(conn, key, student["student_db_id"],
                    timetable_id, attendance_date.isoformat(), student["email"],
                    "sent", "Included in one BCC email.")
            result["message"] = message
        else:
            result["emails_failed"] = 1
            result["status"] = "failed"
            result["reason"] = message
            for student, key in pending:
                save_notification_result(conn, key, student["student_db_id"],
                    timetable_id, attendance_date.isoformat(), student["email"],
                    "failed", message)
        return result
    except Exception as exc:
        logger.exception("Completed-class absentee notification failed.")
        result.update(status="failed", reason=str(exc))
        return result
    finally:
        conn.close()


def get_today_completed_timetables(conn, get_day_aliases_function):
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    columns = get_table_columns(conn, "timetable")
    id_column = find_first_column(columns, ("id", "timetable_id"))
    day_column = find_first_column(columns, ("day", "weekday", "day_of_week"))
    if not id_column or not day_column:
        return []
    aliases = {str(v).strip().lower()
               for v in get_day_aliases_function(today.isoformat()) if str(v).strip()}
    if not aliases:
        return []
    placeholders = ",".join("?" for _ in aliases)
    query = f'SELECT * FROM timetable WHERE LOWER(TRIM("{day_column}")) IN ({placeholders})'
    if "active" in columns:
        query += " AND (active = 1 OR active IS NULL)"
    if "start_time" in columns:
        query += " ORDER BY start_time"
    rows = conn.execute(query, tuple(sorted(aliases))).fetchall()
    completed = []
    for row in rows:
        timetable = dict(row)
        if class_has_finished(today, timetable):
            timetable["_timetable_id"] = timetable.get(id_column)
            completed.append(timetable)
    return completed


def get_today_absentees(conn, get_day_aliases_function):
    results = []
    for timetable in get_today_completed_timetables(conn, get_day_aliases_function):
        timetable_id = timetable.get("_timetable_id")
        if timetable_id is not None:
            _, absentees = get_absentees_for_timetable(conn, timetable_id, date.today())
            results.extend(absentees)
    return results


def notify_today_absentees(get_db_connection_function, get_day_aliases_function,
                           send_email=True, send_whatsapp=False):
    result = {"status": "completed", "total_absentees": 0, "emails_sent": 0,
              "emails_failed": 0, "skipped": 0}
    if not send_email:
        result["status"] = "disabled"
        return result
    conn = get_db_connection_for_notifications(get_db_connection_function)
    try:
        ensure_notification_log_table(conn)
        completed = get_today_completed_timetables(conn, get_day_aliases_function)
        # Keep terminal output to a short summary. Each completed class gets one BCC email.
        for timetable in completed:
            timetable_id = timetable.get("_timetable_id")
            if timetable_id is None:
                continue
            class_result = notify_completed_timetable_absentees(
                get_db_connection_function, timetable_id, date.today(),
                send_email=True, send_whatsapp=send_whatsapp)
            for key in ("total_absentees", "emails_sent", "emails_failed", "skipped"):
                result[key] += class_result.get(key, 0)
        if result["emails_failed"]:
            result["status"] = "partial_failure"
        return result
    except Exception as exc:
        logger.exception("Today's absentee email job failed.")
        result.update(status="failed", error=str(exc))
        return result
    finally:
        conn.close()


def process_attendance_email_notifications(get_db_connection_function,
                                           get_day_aliases_function):
    logger.info("ATTENDANCE NOTIFICATION JOB STARTED: %s",
                datetime.now().isoformat(timespec="seconds"))
    result = notify_today_absentees(
        get_db_connection_function=get_db_connection_function,
        get_day_aliases_function=get_day_aliases_function,
        send_email=True, send_whatsapp=False)
    logger.info(
        "ATTENDANCE NOTIFICATION JOB FINISHED: status=%s absentees=%s "
        "bcc_emails_sent=%s failed=%s skipped=%s",
        result.get("status"), result.get("total_absentees"),
        result.get("emails_sent"), result.get("emails_failed"),
        result.get("skipped"))
    return result
