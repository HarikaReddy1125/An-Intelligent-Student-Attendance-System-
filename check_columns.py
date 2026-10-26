
import sqlite3

db_path = r"D:\student_attendance\attendance.db"
conn = sqlite3.connect(db_path)

for table in ("students", "users"):
    print(f"\n{table} table:")
    try:
        columns = conn.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()

        for column in columns:
            print(column[1])
    except sqlite3.Error as error:
        print(error)

conn.close()
input("\nPress Enter to close...")
