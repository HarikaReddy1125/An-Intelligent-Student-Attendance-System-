
import sqlite3

DB_PATH = "attendance.db"

# Keep this True for a safe preview.
# Change to False only when ready to save the updates.
PREVIEW_ONLY = False

# Format: roll_number,mobile
# Leave mobile blank when no number was supplied.
ROSTER = """
23321A0401,9392938483
23321A0402,6303273535
23321A0403,8522840884
23321A0404,9989063685
23321A0406,9133964804
23321A0407,7816094846
23321A0408,9392783972
23321A0409,9515530884
23321A0410,9908790672
23321A0411,7732007020
23321A0412,8978912489
23321A0413,9392795615
23321A0414,8309670766
23321A0415,6302165396
23321A0416,9381712810
23321A0417,6301638114
23321A0418,7780320872
23321A0419,6281770618
23321A0420,9490927507
23321A0421,8919973354
23321A0422,9550632442
23321A0424,9849775242
23321A0425,8919665467
23321A0426,7416184070
23321A0427,7569139921
23321A0428,8688088955
23321A0429,9182544996
23321A0430,8309636246
23321A0431,9063925359
23321A0432,7702541947
23321A0433,9849736145
23321A0434,9121822922
23321A0435,9701134003
23321A0436,7396951729
23321A0437,
23321A0438,9381695937
23321A0439,
23321A0440,7815968399
23321A0441,9493832514
23321A0442,9346252939
23321A0443,9502375726
23321A0444,9398151175
23321A0445,7075007926
23321A0446,8074470269
23321A0447,8331091977
23321A0449,9381067325
23321A0450,8555842793
23321A0451,
23321A0452,6309341977
23321A0453,
23321A0454,8688600415
23321A0455,
23321A0456,9704039673
23321A0457,8125952494
23321A0458,7993354365
23321A0459,
23321A0460,9398209716
23321A0461,7780318727
23321A0462,7842697669
23321A0463,6304184858
23321A0464,
24325A0401,8074141719
24325A0402,9642829370
24325A0403,9550308253
24325A0404,9391386983
24325A0405,8688634209
24325A0406,9381485155
24325A0407,7396673652
"""


def main():
    roster = []

    for line in ROSTER.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]

        if len(parts) != 2:
            raise ValueError(f"Invalid roster line: {line!r}")

        roll, mobile = parts

        if not roll:
            raise ValueError("A roster entry has an empty roll number.")

        college_email = f"{roll.lower()}@brecw.ac.in"
        roster.append((roll, mobile, college_email))

    rolls = [row[0] for row in roster]

    if len(rolls) != len(set(rolls)):
        raise ValueError("Duplicate roll numbers found. Nothing was changed.")

    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute("BEGIN")

        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(students)"
            )
        }

        required = {"student_id", "mobile", "email", "active"}

        if not required.issubset(columns):
            raise RuntimeError(
                f"Missing required columns: {required - columns}"
            )

        updates = []
        missing = []
        inactive = []

        for roll, mobile, college_email in roster:
            matches = conn.execute(
                """
                SELECT id, active, mobile, email
                FROM students
                WHERE student_id = ?
                """,
                (roll,),
            ).fetchall()

            if not matches:
                missing.append(roll)
                continue

            if len(matches) > 1:
                raise RuntimeError(
                    f"Duplicate database records for roll number {roll}. "
                    "Nothing was saved."
                )

            student_id, active, old_mobile, old_email = matches[0]

            if active != 1:
                inactive.append(roll)
                continue

            # Blank roster mobile means preserve the current database value.
            new_mobile = mobile if mobile else old_mobile
            new_email = college_email

            if (
                new_mobile != old_mobile
                or new_email != old_email
            ):
                updates.append(
                    (student_id, roll, new_mobile, new_email)
                )

        print(f"Roster entries: {len(roster)}")
        print(f"Records to update: {len(updates)}")
        print(f"Missing roll numbers: {missing or 'None'}")
        print(f"Inactive records skipped: {inactive or 'None'}")
        print("\nPreview of planned changes:")

        for _, roll, mobile, email in updates:
            print(f"{roll}: mobile={mobile!r}, email={email!r}")

        if missing or inactive:
            print(
                "\nWARNING: Missing or inactive records were found. "
                "Review the list before applying changes."
            )

        if PREVIEW_ONLY:
            conn.rollback()
            print("\nPREVIEW ONLY: No changes were saved.")
            print("Set PREVIEW_ONLY = False after checking this preview.")
            return

        if missing or inactive:
            raise RuntimeError(
                "Import stopped because missing or inactive records "
                "were found. No changes were saved."
            )

        for student_db_id, roll, mobile, email in updates:
            conn.execute(
                """
                UPDATE students
                SET mobile = ?, email = ?
                WHERE id = ? AND student_id = ? AND active = 1
                """,
                (mobile, email, student_db_id, roll),
            )

        conn.commit()
        print(
            f"\nSUCCESS: Updated contact details for "
            f"{len(updates)} students."
        )
        print("Attendance and face data were not modified.")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
