from database import get_connection


def register_student():
    print("\n==============================")
    print("     STUDENT REGISTRATION")
    print("==============================\n")

    student_id = input("Student ID: ").strip()
    name = input("Student Name: ").strip()
    email = input("Student Email: ").strip()
    parent_mobile = input("Parent WhatsApp Number: ").strip()
    department = input("Department: ").strip()
    year = input("Year: ").strip()
    section = input("Section: ").strip()

    # Basic validation
    if not student_id or not name:
        print("\nStudent ID and Name are required.")
        return

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO students
            (
                student_id,
                name,
                email,
                parent_mobile,
                department,
                year,
                section
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            student_id,
            name,
            email,
            parent_mobile,
            department,
            year,
            section
        ))

        connection.commit()

        print("\n================================")
        print(" Student registered successfully!")
        print("================================")
        print(f"Student ID       : {student_id}")
        print(f"Name             : {name}")
        print(f"Student Email    : {email}")
        print(f"Parent WhatsApp  : {parent_mobile}")
        print(f"Department       : {department}")
        print(f"Year             : {year}")
        print(f"Section          : {section}")

    except Exception as error:
        print("\nError:", error)

    finally:
        connection.close()


if __name__ == "__main__":
    register_student()