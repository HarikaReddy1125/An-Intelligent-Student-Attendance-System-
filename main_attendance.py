import cv2
import sqlite3
import numpy as np
import os
from datetime import datetime


# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_PATH = os.path.join(
    BASE_DIR,
    "attendance.db"
)

YU_NET_MODEL = os.path.join(
    BASE_DIR,
    "models",
    "face_detection_yunet_2026may.onnx"
)

SFACE_MODEL = os.path.join(
    BASE_DIR,
    "models",
    "face_recognition_sface_2021dec.onnx"
)


# ============================================================
# SETTINGS
# ============================================================

CAMERA_INDEX = 0

SIMILARITY_THRESHOLD = 0.40

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480


# ============================================================
# LIVENESS SETTINGS
# ============================================================

# Number of consecutive frames required for each movement.
LIVENESS_REQUIRED_FRAMES = 5

# Required sequence:
# CENTER -> LEFT -> CENTER -> RIGHT
LIVENESS_SEQUENCE = [
    "CENTER",
    "LEFT",
    "CENTER",
    "RIGHT"
]

# Number of frames without a face before liveness is reset.
LIVENESS_FACE_LOST_FRAMES = 20


# ============================================================
# CHECK REQUIRED FILES
# ============================================================

print()
print("==============================================")
print("   INTELLIGENT STUDENT ATTENDANCE SYSTEM")
print("==============================================")
print()


if not os.path.exists(DATABASE_PATH):

    print("ERROR: Database not found:")
    print(DATABASE_PATH)
    exit()


if not os.path.exists(YU_NET_MODEL):

    print("ERROR: YuNet model not found:")
    print(YU_NET_MODEL)
    exit()


if not os.path.exists(SFACE_MODEL):

    print("ERROR: SFace model not found:")
    print(SFACE_MODEL)
    exit()


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection


# ============================================================
# LOAD ENROLLED STUDENTS
# ============================================================

def load_students():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            student_id,
            name,
            face_encoding
        FROM students
        WHERE face_encoding IS NOT NULL
    """)

    rows = cursor.fetchall()

    connection.close()

    students = []

    for row in rows:

        try:

            embedding = np.frombuffer(
                row["face_encoding"],
                dtype=np.float32
            ).copy()

            norm = np.linalg.norm(
                embedding
            )

            if norm > 0:

                embedding = embedding / norm

            students.append({
                "database_id": row["id"],
                "student_id": row["student_id"],
                "name": row["name"],
                "embedding": embedding
            })

        except Exception as error:

            print(
                f"Could not load encoding for "
                f"{row['student_id']}: {error}"
            )

    return students


# ============================================================
# FIND CURRENT TIMETABLE
# ============================================================

def get_current_class():

    now = datetime.now()

    current_day = now.strftime("%A")

    current_time = now.strftime("%H:%M")

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            course_code,
            subject_name,
            faculty_name,
            room_no,
            class_name,
            academic_year,
            semester,
            day,
            start_time,
            end_time,
            active
        FROM timetable
        WHERE day = ?
          AND start_time <= ?
          AND end_time >= ?
          AND (active = 1 OR active IS NULL)
        ORDER BY start_time
        LIMIT 1
    """, (
        current_day,
        current_time,
        current_time
    ))

    row = cursor.fetchone()

    connection.close()

    return row


# ============================================================
# MARK ATTENDANCE
# ============================================================

def mark_attendance(
    database_student_id,
    timetable_id,
    confidence
):

    now = datetime.now()

    current_date = now.strftime(
        "%Y-%m-%d"
    )

    current_time = now.strftime(
        "%H:%M:%S"
    )

    connection = get_connection()

    cursor = connection.cursor()

    # --------------------------------------------------------
    # Check whether attendance already exists
    # --------------------------------------------------------

    cursor.execute("""
        SELECT id, status
        FROM attendance
        WHERE student_id = ?
          AND timetable_id = ?
          AND date = ?
    """, (
        database_student_id,
        timetable_id,
        current_date
    ))

    existing = cursor.fetchone()

    if existing:

        connection.close()

        return (
            False,
            "ALREADY MARKED",
            existing["status"]
        )


    # --------------------------------------------------------
    # Determine Present / Late
    # --------------------------------------------------------

    cursor.execute("""
        SELECT late_after
        FROM timetable
        WHERE id = ?
    """, (
        timetable_id,
    ))

    timetable_row = cursor.fetchone()

    status = "Present"

    if timetable_row:

        late_after = timetable_row["late_after"]

        if late_after:

            try:

                current_minutes = (
                    now.hour * 60
                    + now.minute
                )

                late_hour, late_minute = map(
                    int,
                    late_after.split(":")
                )

                late_minutes = (
                    late_hour * 60
                    + late_minute
                )

                if current_minutes > late_minutes:

                    status = "Late"

            except Exception:

                status = "Present"


    # --------------------------------------------------------
    # Insert attendance
    # --------------------------------------------------------

    cursor.execute("""
        INSERT INTO attendance (
            student_id,
            timetable_id,
            date,
            time,
            status,
            confidence
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        database_student_id,
        timetable_id,
        current_date,
        current_time,
        status,
        confidence
    ))

    connection.commit()

    connection.close()

    return (
        True,
        "MARKED",
        status
    )


# ============================================================
# LIVENESS HELPER
# ============================================================

def get_face_position(
    face,
    frame_width
):

    """
    Determine whether the detected face is
    LEFT, CENTER or RIGHT.

    This uses the same position logic as the
    standalone liveness test that already passed.
    """

    x = int(face[0])
    w = int(face[2])

    center_x = x + (w // 2)

    relative_x = center_x / frame_width

    if relative_x < 0.35:

        return "LEFT"

    elif relative_x > 0.65:

        return "RIGHT"

    else:

        return "CENTER"


# ============================================================
# LIVENESS STATE
# ============================================================

liveness_sequence_index = 0

liveness_frame_count = 0

liveness_verified = False

liveness_verified_student_id = None

liveness_face_lost_count = 0

liveness_status = "LIVENESS: CENTER"


# ============================================================
# LOAD STUDENTS
# ============================================================

students = load_students()


if not students:

    print()
    print("ERROR: No enrolled students found.")
    print()

    print("Please enroll students first.")
    print()

    exit()


print(
    f"Enrolled students loaded: "
    f"{len(students)}"
)

for student in students:

    print(
        f"- {student['student_id']} : "
        f"{student['name']}"
    )


# ============================================================
# LOAD YUNET
# ============================================================

print()
print("Loading YuNet...")

detector = cv2.FaceDetectorYN.create(
    YU_NET_MODEL,
    "",
    (320, 320),
    0.9,
    0.3,
    5000
)


# ============================================================
# LOAD SFACE
# ============================================================

print("Loading SFace...")

recognizer = cv2.FaceRecognizerSF.create(
    SFACE_MODEL,
    ""
)


# ============================================================
# OPEN CAMERA
# ============================================================

print()
print("Opening camera...")
print()
print("Press Q to quit.")
print()


camera = cv2.VideoCapture(
    CAMERA_INDEX
)

camera.set(
    cv2.CAP_PROP_FRAME_WIDTH,
    CAMERA_WIDTH
)

camera.set(
    cv2.CAP_PROP_FRAME_HEIGHT,
    CAMERA_HEIGHT
)


if not camera.isOpened():

    print("ERROR: Could not open camera.")

    exit()


# ============================================================
# RECOGNITION LOOP
# ============================================================

while True:

    success, frame = camera.read()

    if not success:

        print("Could not read camera frame.")

        break


    height, width = frame.shape[:2]


    # --------------------------------------------------------
    # Update detector size
    # --------------------------------------------------------

    detector.setInputSize(
        (width, height)
    )


    # --------------------------------------------------------
    # Detect faces
    # --------------------------------------------------------

    _, faces = detector.detect(
        frame
    )


    # --------------------------------------------------------
    # Current timetable
    # --------------------------------------------------------

    current_class = get_current_class()


    if current_class:

        course_code = (
            current_class["course_code"]
            or ""
        )

        subject_name = (
            current_class["subject_name"]
            or current_class["course_code"]
            or "Unknown Subject"
        )

        faculty_name = (
            current_class["faculty_name"]
            or "Faculty not assigned"
        )

        room_no = (
            current_class["room_no"]
            or "Room not assigned"
        )

        class_name = (
            current_class["class_name"]
            or ""
        )

        start_time = (
            current_class["start_time"]
            or ""
        )

        end_time = (
            current_class["end_time"]
            or ""
        )


        # ----------------------------------------------------
        # Main class information
        # ----------------------------------------------------

        if course_code:

            class_text = (
                f"{course_code} | "
                f"{subject_name}"
            )

        else:

            class_text = subject_name


        cv2.putText(
            frame,
            class_text,
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2
        )


        # ----------------------------------------------------
        # Faculty + room
        # ----------------------------------------------------

        faculty_text = (
            f"Faculty: {faculty_name}"
        )

        cv2.putText(
            frame,
            faculty_text,
            (20, 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (255, 255, 255),
            2
        )


        room_text = (
            f"Room: {room_no}"
        )

        cv2.putText(
            frame,
            room_text,
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (255, 255, 255),
            2
        )


        # ----------------------------------------------------
        # Class timing
        # ----------------------------------------------------

        time_text = (
            f"Time: {start_time} - {end_time}"
        )

        cv2.putText(
            frame,
            time_text,
            (20, 105),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (255, 255, 255),
            2
        )


        # ----------------------------------------------------
        # Class name
        # ----------------------------------------------------

        if class_name:

            cv2.putText(
                frame,
                class_name,
                (20, 130),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1
            )


    else:

        cv2.putText(
            frame,
            "NO CLASS SCHEDULED",
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 0, 255),
            2
        )


    # ========================================================
    # LIVENESS / FACE PROCESSING
    # ========================================================

    if faces is not None and len(faces) > 0:

        # ----------------------------------------------------
        # Select the largest face for liveness.
        # ----------------------------------------------------

        faces = sorted(
            faces,
            key=lambda f: f[2] * f[3],
            reverse=True
        )

        liveness_face = faces[0]

        liveness_face_lost_count = 0


        # ====================================================
        # LIVENESS NOT YET VERIFIED
        # ====================================================

        if not liveness_verified:

            position = get_face_position(
                liveness_face,
                width
            )

            expected_position = (
                LIVENESS_SEQUENCE[
                    liveness_sequence_index
                ]
            )


            # ------------------------------------------------
            # Correct movement
            # ------------------------------------------------

            if position == expected_position:

                liveness_frame_count += 1

            else:

                liveness_frame_count = 0


            liveness_status = (
                f"LIVENESS: {expected_position}"
            )


            # ------------------------------------------------
            # Required frames reached
            # ------------------------------------------------

            if (
                liveness_frame_count
                >= LIVENESS_REQUIRED_FRAMES
            ):

                liveness_sequence_index += 1

                liveness_frame_count = 0


                # ------------------------------------------------
                # Entire sequence completed
                # ------------------------------------------------

                if (
                    liveness_sequence_index
                    >= len(LIVENESS_SEQUENCE)
                ):

                    liveness_verified = True

                    liveness_status = (
                        "LIVENESS: VERIFIED"
                    )

                    print()
                    print(
                        "[LIVENESS] "
                        "Live person verified."
                    )


                else:

                    liveness_status = (
                        "LIVENESS: "
                        + LIVENESS_SEQUENCE[
                            liveness_sequence_index
                        ]
                    )


            # ------------------------------------------------
            # Display liveness instructions
            # ------------------------------------------------

            cv2.putText(
                frame,
                liveness_status,
                (20, 160),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (0, 255, 255),
                2
            )

            cv2.putText(
                frame,
                (
                    f"Progress: "
                    f"{liveness_sequence_index}/"
                    f"{len(LIVENESS_SEQUENCE)}"
                ),
                (20, 185),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 255, 255),
                2
            )


            cv2.putText(
                frame,
                "Move: "
                + LIVENESS_SEQUENCE[
                    min(
                        liveness_sequence_index,
                        len(LIVENESS_SEQUENCE) - 1
                    )
                ],
                (20, 210),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 255, 255),
                2
            )


            # ------------------------------------------------
            # Draw the face used for liveness
            # ------------------------------------------------

            x = int(liveness_face[0])
            y = int(liveness_face[1])
            w = int(liveness_face[2])
            h = int(liveness_face[3])

            cv2.rectangle(
                frame,
                (x, y),
                (x + w, y + h),
                (0, 255, 255),
                2
            )

            cv2.putText(
                frame,
                position,
                (x, max(y - 10, 25)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (0, 255, 255),
                2
            )


            # ------------------------------------------------
            # IMPORTANT:
            # Do not recognize or mark attendance until
            # liveness has been verified.
            # ------------------------------------------------

            if not liveness_verified:

                cv2.imshow(
                    "Student Attendance System",
                    frame
                )

                key = cv2.waitKey(1) & 0xFF

                if key == ord("q"):

                    break

                continue


        # ====================================================
        # LIVENESS VERIFIED
        # ====================================================

        cv2.putText(
            frame,
            "LIVENESS: VERIFIED",
            (20, 160),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (0, 255, 0),
            2
        )


        # ====================================================
        # PROCESS RECOGNITION
        # ====================================================

        for face in faces:

            x = int(face[0])
            y = int(face[1])
            w = int(face[2])
            h = int(face[3])


            # ------------------------------------------------
            # Generate face feature
            # ------------------------------------------------

            try:

                aligned_face = recognizer.alignCrop(
                    frame,
                    face
                )

                feature = recognizer.feature(
                    aligned_face
                )

                feature = feature.flatten()

                norm = np.linalg.norm(
                    feature
                )

                if norm > 0:

                    feature = feature / norm


                # ------------------------------------------------
                # Find best matching student
                # ------------------------------------------------

                best_student = None

                best_similarity = -1


                for student in students:

                    similarity = float(
                        np.dot(
                            feature,
                            student["embedding"]
                        )
                    )


                    if similarity > best_similarity:

                        best_similarity = similarity

                        best_student = student


                # ------------------------------------------------
                # Recognized student
                # ------------------------------------------------

                if (
                    best_student is not None
                    and best_similarity
                    >= SIMILARITY_THRESHOLD
                ):

                    student_name = (
                        best_student["name"]
                    )

                    student_id = (
                        best_student["student_id"]
                    )

                    database_student_id = (
                        best_student["database_id"]
                    )


                    # ------------------------------------------------
                    # Bind liveness verification to the first
                    # recognized student.
                    # ------------------------------------------------

                    if (
                        liveness_verified_student_id
                        is None
                    ):

                        liveness_verified_student_id = (
                            database_student_id
                        )

                        print(
                            "[LIVENESS] "
                            f"Verified for student "
                            f"{student_id}."
                        )


                    # ------------------------------------------------
                    # Only the student associated with the
                    # liveness verification can proceed.
                    # ------------------------------------------------

                    if (
                        database_student_id
                        != liveness_verified_student_id
                    ):

                        label = "NOT VERIFIED"

                        sub_label = (
                            f"{student_id} | "
                            f"{best_similarity:.2f}"
                        )

                        attendance_text = (
                            "LIVENESS NOT VERIFIED"
                        )

                        color = (
                            0,
                            0,
                            255
                        )


                    else:

                        label = student_name

                        sub_label = (
                            f"{student_id} | "
                            f"{best_similarity:.2f}"
                        )

                        color = (
                            0,
                            255,
                            0
                        )


                        # ====================================================
                        # ATTENDANCE
                        # ====================================================

                        if current_class:

                            marked, message, status = (
                                mark_attendance(
                                    database_student_id,
                                    current_class["id"],
                                    best_similarity
                                )
                            )


                            if marked:

                                attendance_text = (
                                    f"ATTENDANCE: "
                                    f"{status.upper()}"
                                )

                                print(
                                    f"[ATTENDANCE] "
                                    f"{student_id} - "
                                    f"{student_name} - "
                                    f"{status} - "
                                    f"Confidence: "
                                    f"{best_similarity:.2f}"
                                )

                            else:

                                attendance_text = (
                                    "ATTENDANCE ALREADY MARKED"
                                )


                        else:

                            attendance_text = (
                                "NO CLASS - NOT MARKED"
                            )


                # ------------------------------------------------
                # Unknown student
                # ------------------------------------------------

                else:

                    label = "UNKNOWN"

                    sub_label = (
                        f"Similarity: "
                        f"{best_similarity:.2f}"
                    )

                    attendance_text = (
                        "ATTENDANCE NOT MARKED"
                    )

                    color = (
                        0,
                        0,
                        255
                    )


                # ------------------------------------------------
                # Draw face rectangle
                # ------------------------------------------------

                cv2.rectangle(
                    frame,
                    (x, y),
                    (x + w, y + h),
                    color,
                    2
                )


                # ------------------------------------------------
                # Display name
                # ------------------------------------------------

                text_y = max(
                    y - 40,
                    60
                )


                cv2.putText(
                    frame,
                    label,
                    (x, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2
                )


                # ------------------------------------------------
                # Display student ID + similarity
                # ------------------------------------------------

                cv2.putText(
                    frame,
                    sub_label,
                    (x, text_y + 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    2
                )


                # ------------------------------------------------
                # Display attendance status
                # ------------------------------------------------

                cv2.putText(
                    frame,
                    attendance_text,
                    (x, text_y + 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    2
                )


            except Exception as error:

                print(
                    "Recognition error:",
                    error
                )


    # ========================================================
    # NO FACE DETECTED
    # ========================================================

    else:

        liveness_face_lost_count += 1


        # ----------------------------------------------------
        # Reset liveness after the person leaves the camera.
        # ----------------------------------------------------

        if (
            liveness_face_lost_count
            >= LIVENESS_FACE_LOST_FRAMES
        ):

            liveness_sequence_index = 0

            liveness_frame_count = 0

            liveness_verified = False

            liveness_verified_student_id = None

            liveness_face_lost_count = 0

            liveness_status = (
                "LIVENESS: CENTER"
            )

            print(
                "[LIVENESS] "
                "Reset - no face detected."
            )


        cv2.putText(
            frame,
            "LIVENESS: FACE REQUIRED",
            (20, 160),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (0, 255, 255),
            2
        )


    # ========================================================
    # DISPLAY CAMERA
    # ========================================================

    cv2.imshow(
        "Student Attendance System",
        frame
    )


    # ========================================================
    # QUIT
    # ========================================================

    key = cv2.waitKey(1) & 0xFF


    if key == ord("q"):

        break


# ============================================================
# CLEANUP
# ============================================================

camera.release()

cv2.destroyAllWindows()

print()
print("Attendance system closed.")
