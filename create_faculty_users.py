import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect("attendance.db")
cursor = conn.cursor()

password = "Faculty@123"

faculty = cursor.execute("""
    SELECT username
    FROM faculty
    WHERE username IS NOT NULL AND active = 1
""").fetchall()

for (username,) in faculty:
    existing = cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,)
    ).fetchone()

    if existing:
        print(f"Already exists: {username}")
    else:
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, ?)
            """,
            (
                username,
                generate_password_hash(password),
                "faculty"
            )
        )
        print(f"Created: {username}")

conn.commit()

print("\nFaculty accounts:")
rows = cursor.execute("""
    SELECT username, role
    FROM users
    WHERE role = 'faculty'
""").fetchall()

for row in rows:
    print(row)

conn.close()