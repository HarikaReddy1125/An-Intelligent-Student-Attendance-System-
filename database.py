import sqlite3
from pathlib import Path


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE_NAME = BASE_DIR / "attendance.db"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    connection = sqlite3.connect(DATABASE_NAME)
    connection.row_factory = sqlite3.Row

    # Enable foreign-key support
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ============================================================
# CREATE TABLES
# ============================================================

def create_tables():

    connection = get_connection()
    cursor = connection.cursor()

    # --------------------------------------------------------
    # STUDENTS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            parent_mobile TEXT,
            department TEXT,
            year INTEGER,
            section TEXT,
            face_encoding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


    # --------------------------------------------------------
    # FACULTY
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faculty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE,
            password_hash TEXT,
            department TEXT DEFAULT 'ECE',
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


    # --------------------------------------------------------
    # TIMETABLE
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,

            course_code TEXT,
            subject_name TEXT NOT NULL,

            faculty_name TEXT,
            room_no TEXT,

            class_name TEXT DEFAULT 'IV B.Tech ECE A',
            academic_year TEXT DEFAULT '2026-27',
            semester TEXT DEFAULT 'IV B.Tech ECE A Semester',

            active INTEGER DEFAULT 1,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


    # --------------------------------------------------------
    # ATTENDANCE
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            student_id INTEGER NOT NULL,
            timetable_id INTEGER NOT NULL,

            date TEXT NOT NULL,
            time TEXT NOT NULL,

            status TEXT NOT NULL,

            confidence REAL,

            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE,

            FOREIGN KEY (timetable_id)
                REFERENCES timetable(id)
                ON DELETE CASCADE,

            UNIQUE(student_id, timetable_id, date)
        )
    """)


    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,

            role TEXT NOT NULL,

            student_id INTEGER,
            faculty_id INTEGER,

            active INTEGER DEFAULT 1,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (student_id)
                REFERENCES students(id)
                ON DELETE CASCADE,

            FOREIGN KEY (faculty_id)
                REFERENCES faculty(id)
                ON DELETE CASCADE
        )
    """)


    # ========================================================
    # INDEXES
    # ========================================================

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_timetable_day_time
        ON timetable(day, start_time, end_time)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_student
        ON attendance(student_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_date
        ON attendance(date)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_timetable
        ON attendance(timetable_id)
    """)


    connection.commit()
    connection.close()

    print("Database tables created successfully.")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    create_tables()