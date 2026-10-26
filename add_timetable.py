import sqlite3
from pathlib import Path


# ============================================================
# DATABASE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"


# ============================================================
# TIMETABLE
# ============================================================

TIMETABLE = [

    # MONDAY
    ("Monday", "09:30", "10:30",
     "TT720", "Scripting Languages",
     "Ms Tasneem Rahath", "NB 108"),

    ("Monday", "10:30", "11:30",
     "EC701PC", "Microwave and Optical Communications",
     "Ms B Jyothsna", "NB 108"),

    ("Monday", "11:30", "12:30",
     "EC742PE", "Satellite Communications",
     "Ms Kazi Nikhat Parvin", "NB 500"),

    ("Monday", "13:30", "14:30",
     "EC731PE", "Radar Systems",
     "Ms A Jyothirmai", "NB 108"),

    ("Monday", "14:30", "15:30",
     "SPORTS", "Sports",
     "Ms Shafa Tasneem", "NA"),

    ("Monday", "15:30", "16:30",
     "EC702PC", "Professional Practice, Law & Ethics",
     "Ms Y Sagarika", "NB 108"),


    # TUESDAY
    ("Tuesday", "09:30", "12:30",
     "EC700PC", "Microwave and Optical Communications Lab",
     "Lab Faculty", "NB 113"),

    ("Tuesday", "13:30", "14:30",
     "TT720", "Scripting Languages",
     "Ms Tasneem Rahath", "NB 108"),

    ("Tuesday", "14:30", "15:30",
     "EC701PC", "Microwave and Optical Communications",
     "Ms B Jyothsna", "NB 108"),

    ("Tuesday", "15:30", "16:30",
     "EC731PE", "Radar Systems",
     "Ms A Jyothirmai", "NB 108"),


    # WEDNESDAY
    ("Wednesday", "09:30", "10:30",
     "EC701PC", "Microwave and Optical Communications",
     "Ms B Jyothsna", "NB 108"),

    ("Wednesday", "10:30", "11:30",
     "LIBRARY", "Library",
     "Ms S Manjula", "WB 102"),

    ("Wednesday", "11:30", "12:30",
     "EC702PC", "Professional Practice, Law & Ethics",
     "Ms Y Sagarika", "NB 108"),

    ("Wednesday", "13:30", "14:30",
     "EC742PE", "Satellite Communications",
     "Ms Kazi Nikhat Parvin", "NB 500"),

    ("Wednesday", "14:30", "15:30",
     "EC701PC", "Microwave and Optical Communications",
     "Ms B Jyothsna", "NB 108"),

    ("Wednesday", "15:30", "16:30",
     "TT720", "Scripting Languages",
     "Ms Tasneem Rahath", "NB 108"),


    # THURSDAY
    ("Thursday", "09:30", "10:30",
     "EC702PC", "Professional Practice, Law & Ethics",
     "Ms Y Sagarika", "NB 108"),

    ("Thursday", "10:30", "11:30",
     "EC742PE", "Satellite Communications",
     "Ms Kazi Nikhat Parvin", "NB 500"),

    ("Thursday", "11:30", "12:30",
     "EC731PE", "Radar Systems",
     "Ms A Jyothirmai", "NB 108"),

    ("Thursday", "13:30", "16:30",
     "EC700PC", "Microwave and Optical Communications Lab",
     "Lab Faculty", "NB 113"),


    # FRIDAY
    ("Friday", "09:30", "12:30",
     "EC704PC", "Project Stage-I",
     "Ms J Stella Mary", "NB 108 / NB 216"),

    ("Friday", "13:30", "16:30",
     "EC704PC", "Project Stage-I",
     "Ms J Stella Mary", "NB 108 / NB 216"),
]


# ============================================================
# CREATE / UPGRADE TABLES
# ============================================================

def create_tables(connection):

    cursor = connection.cursor()

    # --------------------------------------------------------
    # FACULTY TABLE
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faculty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE,
            password_hash TEXT,
            department TEXT DEFAULT 'ECE',
            active INTEGER DEFAULT 1
        )
    """)

    # --------------------------------------------------------
    # TIMETABLE TABLE
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
            active INTEGER DEFAULT 1
        )
    """)

    # --------------------------------------------------------
    # IMPORTANT:
    # If timetable already existed, add missing columns.
    # --------------------------------------------------------

    cursor.execute("PRAGMA table_info(timetable)")
    existing_columns = {
        column[1] for column in cursor.fetchall()
    }

    required_columns = {
        "day": "TEXT",
        "start_time": "TEXT",
        "end_time": "TEXT",
        "course_code": "TEXT",
        "subject_name": "TEXT",
        "faculty_name": "TEXT",
        "room_no": "TEXT",
        "class_name": "TEXT",
        "academic_year": "TEXT",
        "semester": "TEXT",
        "active": "INTEGER"
    }

    for column, data_type in required_columns.items():

        if column not in existing_columns:

            print(f"Adding missing column: {column}")

            cursor.execute(
                f"ALTER TABLE timetable ADD COLUMN {column} {data_type}"
            )

    # --------------------------------------------------------
    # INDEX
    # --------------------------------------------------------

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_timetable_day_time
        ON timetable(day, start_time, end_time)
    """)

    connection.commit()


# ============================================================
# ADD FACULTY
# ============================================================

def add_faculty(connection):

    faculty_list = [
        ("Ms B Jyothsna", "b_jyothsna"),
        ("Ms A Jyothirmai", "a_jyothirmai"),
        ("Ms Kazi Nikhat Parvin", "kazi_nikhat"),
        ("Ms Tasneem Rahath", "tasneem_rahath"),
        ("Ms Y Sagarika", "y_sagarika"),
        ("Ms Shafa Tasneem", "shafa_tasneem"),
        ("Ms S Manjula", "s_manjula"),
        ("Ms J Stella Mary", "j_stella_mary"),
        ("Lab Faculty", "lab_faculty")
    ]

    cursor = connection.cursor()

    for name, username in faculty_list:

        cursor.execute("""
            INSERT OR IGNORE INTO faculty
            (name, username)
            VALUES (?, ?)
        """, (name, username))

    connection.commit()


# ============================================================
# ADD TIMETABLE
# ============================================================

def add_timetable(connection):

    cursor = connection.cursor()

    # --------------------------------------------------------
    # Check existing columns
    # --------------------------------------------------------

    cursor.execute("PRAGMA table_info(timetable)")

    columns = {
        column[1]
        for column in cursor.fetchall()
    }

    print("\nExisting timetable columns:")
    print(columns)

    # --------------------------------------------------------
    # Clear old timetable records only
    # --------------------------------------------------------

    cursor.execute("DELETE FROM timetable")

    # --------------------------------------------------------
    # Insert timetable
    # --------------------------------------------------------

    for row in TIMETABLE:

        day = row[0]
        start_time = row[1]
        end_time = row[2]
        course_code = row[3]
        subject_name = row[4]
        faculty_name = row[5]
        room_no = row[6]

        # ----------------------------------------------------
        # Your OLD database has a required "subject" column.
        # We therefore fill BOTH subject and subject_name.
        # ----------------------------------------------------

        if "subject" in columns:

            cursor.execute("""
                INSERT INTO timetable (
                    day,
                    start_time,
                    end_time,
                    subject,
                    course_code,
                    subject_name,
                    faculty_name,
                    room_no,
                    class_name,
                    academic_year,
                    semester,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                day,
                start_time,
                end_time,

                # OLD column
                subject_name,

                # NEW columns
                course_code,
                subject_name,
                faculty_name,
                room_no,
                "IV B.Tech ECE A",
                "2026-27",
                "IV B.Tech ECE A",
                1
            ))

        else:

            cursor.execute("""
                INSERT INTO timetable (
                    day,
                    start_time,
                    end_time,
                    course_code,
                    subject_name,
                    faculty_name,
                    room_no,
                    class_name,
                    academic_year,
                    semester,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                day,
                start_time,
                end_time,
                course_code,
                subject_name,
                faculty_name,
                room_no,
                "IV B.Tech ECE A",
                "2026-27",
                "IV B.Tech ECE A",
                1
            ))

    connection.commit()

    print(f"\nInserted {len(TIMETABLE)} timetable entries.")


# ============================================================
# SHOW TIMETABLE
# ============================================================

def show_timetable(connection):

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            day,
            start_time,
            end_time,
            course_code,
            subject_name,
            faculty_name,
            room_no
        FROM timetable
        ORDER BY
            CASE day
                WHEN 'Monday' THEN 1
                WHEN 'Tuesday' THEN 2
                WHEN 'Wednesday' THEN 3
                WHEN 'Thursday' THEN 4
                WHEN 'Friday' THEN 5
                WHEN 'Saturday' THEN 6
                WHEN 'Sunday' THEN 7
            END,
            start_time
    """)

    rows = cursor.fetchall()

    print("\n")
    print("=" * 120)
    print("IV B.TECH ECE A - CLASS TIMETABLE")
    print("=" * 120)

    for row in rows:

        day, start, end, code, subject, faculty, room = row

        print(
            f"{day:<10} "
            f"{start}-{end:<12} "
            f"{code:<10} "
            f"{subject[:35]:<37} "
            f"{faculty[:25]:<27} "
            f"{room}"
        )

    print("=" * 120)


# ============================================================
# MAIN
# ============================================================

def main():

    print("\nConnecting to database...")
    print(DB_PATH)

    connection = sqlite3.connect(DB_PATH)

    try:

        print("\nChecking database tables...")
        create_tables(connection)

        print("\nAdding faculty...")
        add_faculty(connection)

        print("\nAdding timetable...")
        add_timetable(connection)

        print("\nDisplaying timetable...")
        show_timetable(connection)

        print("\n")
        print("=" * 60)
        print("SUCCESS")
        print("=" * 60)
        print("Timetable successfully added to attendance.db")
        print("Existing student/attendance data was NOT deleted.")

    except Exception as error:

        print("\nERROR:")
        print(error)

    finally:

        connection.close()


if __name__ == "__main__":
    main()
