
import sqlite3

DATABASE_PATH = r"D:\student_attendance\attendance.db"

conn = sqlite3.connect(DATABASE_PATH)

try:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(students)").fetchall()
    }

    if "active" not in columns:
        conn.execute(
            "ALTER TABLE students ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
        )
        conn.commit()
        print("Added the active column. Existing students remain active.")
    else:
        print("The active column already exists. No changes needed.")

except sqlite3.Error as error:
    conn.rollback()
    print(f"Database update failed: {error}")

finally:
    conn.close()

input("Press Enter to close...")
