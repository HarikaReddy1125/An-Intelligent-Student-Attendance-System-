
import sqlite3

conn = sqlite3.connect(r"D:\student_attendance\attendance.db")

print("=== DATABASE TABLES ===")
for row in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
):
    print(row[0])

for table in ["students", "attendance", "timetable"]:
    print(f"\n=== {table.upper()} COLUMNS ===")
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for col in columns:
        print(col[1], "-", col[2])

conn.close()
