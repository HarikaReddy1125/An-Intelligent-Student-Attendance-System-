
import sqlite3

DATABASE_PATH = r"D:\student_attendance\attendance.db"

conn = sqlite3.connect(DATABASE_PATH)
conn.row_factory = sqlite3.Row

try:
    tables = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
    """).fetchall()

    print("DATABASE TABLES")

    for item in tables:
        table = item["name"]
        print(f"\n--- {table} ---")

        # Table names come from this database's own table list.
        columns = conn.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()

        print("Columns:", [column["name"] for column in columns])

        foreign_keys = conn.execute(
            f'PRAGMA foreign_key_list("{table}")'
        ).fetchall()

        if foreign_keys:
            print("Foreign keys:")
            for fk in foreign_keys:
                print(dict(fk))

    print("\nCheck complete. No records were changed.")

finally:
    conn.close()

input("\nPress Enter to close...")
