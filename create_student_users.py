import sqlite3
from werkzeug.security import generate_password_hash


DATABASE_PATH = r"D:\student_attendance\attendance.db"

PASSWORD = "Student@123"


conn = sqlite3.connect(DATABASE_PATH)

cursor = conn.cursor()


students = cursor.execute(
    """
    SELECT student_id, name
    FROM students
    WHERE student_id IS NOT NULL
    """
).fetchall()


created = 0

existing = 0


for student_id, name in students:

    check = cursor.execute(
        """
        SELECT id
        FROM users
        WHERE username = ?
        """,
        (student_id,)
    ).fetchone()


    if check:

        print(
            f"Already exists: {student_id} - {name}"
        )

        existing += 1

    else:

        cursor.execute(
            """
            INSERT INTO users
            (
                username,
                password_hash,
                role
            )
            VALUES
            (
                ?,
                ?,
                ?
            )
            """,
            (
                student_id,
                generate_password_hash(PASSWORD),
                "student"
            )
        )

        print(
            f"Created: {student_id} - {name}"
        )

        created += 1


conn.commit()


print()
print("=" * 50)
print("STUDENT ACCOUNT CREATION COMPLETE")
print("=" * 50)

print(
    f"Created : {created}"
)

print(
    f"Existing: {existing}"
)

print(
    f"Password for new accounts: {PASSWORD}"
)


conn.close()