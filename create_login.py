"""
create_login.py
----------------
The `users` table (username, password_hash, role) already exists in the
schema (see database.py) but nothing creates rows in it yet. Run this
once per student/faculty/admin to give them a website login.

For a student, use their student_id (roll number) as the username so it
matches the `students.student_id` column - app.py depends on that match.

Usage:
    python create_login.py
"""

from getpass import getpass
from werkzeug.security import generate_password_hash

from database import get_connection


def create_login():
    print("\n==============================")
    print("      CREATE WEBSITE LOGIN")
    print("==============================\n")

    username = input("Username (student: use exact Student ID / roll no): ").strip()
    role = input("Role (student / faculty / admin): ").strip().lower()

    if role not in ("student", "faculty", "admin"):
        print("Role must be student, faculty, or admin.")
        return

    password = getpass("Password: ").strip()
    if not password:
        print("Password cannot be empty.")
        return

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role)
        )
        connection.commit()
        print(f"\nLogin created for '{username}' with role '{role}'.")
    except Exception as error:
        print("\nError:", error)
    finally:
        connection.close()


if __name__ == "__main__":
    create_login()
