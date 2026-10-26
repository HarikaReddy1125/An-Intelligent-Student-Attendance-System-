
import sqlite3

DATABASE_PATH = r"D:\student_attendance\attendance.db"

conn = sqlite3.connect(DATABASE_PATH)

try:
    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(students)"
        ).fetchall()
    }

    if "mobile" not in columns:
        conn.execute(
            "ALTER TABLE students ADD COLUMN mobile TEXT"
        )
        conn.commit()
        print("Added the mobile column successfully.")
    else:
        print("The mobile column already exists. No changes needed.")

finally:
    conn.close()

input("Press Enter to close...")
