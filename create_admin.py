import sqlite3
import os

from werkzeug.security import generate_password_hash


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_PATH = os.path.join(
    BASE_DIR,
    "attendance.db"
)


username = "admin"
password = "admin123"
role = "admin"


connection = sqlite3.connect(DATABASE_PATH)

cursor = connection.cursor()


cursor.execute("""
    INSERT INTO users
    (
        username,
        password_hash,
        role
    )
    VALUES (?, ?, ?)
""", (
    username,
    generate_password_hash(password),
    role
))


connection.commit()

connection.close()


print("Admin account created successfully.")

print("Username:", username)
print("Password:", password)
print("Role:", role)