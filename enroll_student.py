import cv2
import sqlite3
import numpy as np
import os
import time


# ============================================================
# PATHS
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

NUM_SAMPLES = 5

SAMPLE_INTERVAL = 1.5


# ============================================================
# CHECK FILES
# ============================================================

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
# HEADER
# ============================================================

print()
print("==========================================")
print("          FACE ENROLLMENT")
print("==========================================")
print()


# ============================================================
# DATABASE CONNECTION
# ============================================================

connection = sqlite3.connect(
    DATABASE_PATH
)

cursor = connection.cursor()


# ============================================================
# GET HALL TICKET NUMBER
# ============================================================

roll_number = input(
    "Enter Hall Ticket Number: "
).strip()


if not roll_number:

    print()
    print("ERROR: Hall Ticket Number cannot be empty.")

    connection.close()
    exit()


# ============================================================
# FIND STUDENT
# ============================================================

cursor.execute(
    """
    SELECT
        student_id,
        name,
        email,
        parent_mobile,
        department,
        year,
        section,
        face_encoding
    FROM students
    WHERE student_id = ?
    """,
    (roll_number,)
)

student = cursor.fetchone()


if student is None:

    print()
    print("==========================================")
    print("          STUDENT NOT FOUND")
    print("==========================================")
    print()

    print(
        "No student exists with Hall Ticket Number:",
        roll_number
    )

    print()

    connection.close()
    exit()


# ============================================================
# STUDENT INFORMATION
# ============================================================

student_id = student[0]
name = student[1]
email = student[2]
parent_mobile = student[3]
department = student[4]
year = student[5]
section = student[6]
existing_encoding = student[7]


print()
print("------------------------------------------")
print("Student found!")
print("------------------------------------------")

print("Roll Number     :", student_id)
print("Name            :", name)
print("Email           :", email)
print("Parent WhatsApp :", parent_mobile)
print("Department      :", department)
print("Year            :", year)
print("Section         :", section)

print("------------------------------------------")
print()


# ============================================================
# CHECK EXISTING FACE ENROLLMENT
# ============================================================

if existing_encoding is not None:

    print("WARNING: This student already has")
    print("a face encoding stored in the database.")
    print()

    choice = input(
        "Do you want to RE-ENROLL this student? (y/n): "
    ).strip().lower()


    if choice != "y":

        print()
        print("Enrollment cancelled.")
        print("Existing face encoding was NOT changed.")
        print()

        connection.close()
        exit()


    print()
    print("Existing face encoding will be replaced.")
    print()


# ============================================================
# LOAD YUNET
# ============================================================

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

print("Instructions:")
print("1. Make sure only ONE person is visible.")
print("2. Look directly at the camera.")
print("3. Keep your face clearly visible.")
print("4. Slightly change your position between samples.")
print("5. Press Q to cancel.")
print()


camera = cv2.VideoCapture(
    CAMERA_INDEX,
    cv2.CAP_DSHOW
)


if not camera.isOpened():

    print("ERROR: Could not open camera.")

    connection.close()
    exit()


# ============================================================
# CAPTURE SAMPLES
# ============================================================

embeddings = []

sample_count = 0

last_capture_time = 0


while True:

    success, frame = camera.read()


    if not success:

        print("ERROR: Could not read camera frame.")
        break


    height, width = frame.shape[:2]


    # --------------------------------------------------------
    # Set detector input size
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


    face = None


    # --------------------------------------------------------
    # Require exactly ONE face
    # --------------------------------------------------------

    if faces is not None:

        number_of_faces = len(faces)


        if number_of_faces == 1:

            face = faces[0]


        elif number_of_faces > 1:

            cv2.putText(
                frame,
                "MULTIPLE FACES - ONLY ONE ALLOWED",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2
            )


    # --------------------------------------------------------
    # Process single face
    # --------------------------------------------------------

    if face is not None:

        x = int(face[0])
        y = int(face[1])
        w = int(face[2])
        h = int(face[3])


        # ----------------------------------------------------
        # Draw face rectangle
        # ----------------------------------------------------

        cv2.rectangle(
            frame,
            (x, y),
            (x + w, y + h),
            (0, 255, 0),
            2
        )


        # ----------------------------------------------------
        # Capture sample
        # ----------------------------------------------------

        current_time = time.time()


        if (
            current_time - last_capture_time
            >= SAMPLE_INTERVAL
            and sample_count < NUM_SAMPLES
        ):

            try:

                # --------------------------------------------
                # Align face
                # --------------------------------------------

                aligned_face = recognizer.alignCrop(
                    frame,
                    face
                )


                # --------------------------------------------
                # Generate SFace feature
                # --------------------------------------------

                feature = recognizer.feature(
                    aligned_face
                )


                feature = feature.flatten()


                # --------------------------------------------
                # Normalize
                # --------------------------------------------

                norm = np.linalg.norm(
                    feature
                )


                if norm > 0:

                    feature = feature / norm


                # --------------------------------------------
                # Store sample
                # --------------------------------------------

                embeddings.append(
                    feature
                )


                sample_count += 1

                last_capture_time = current_time


                print(
                    f"Sample {sample_count}/{NUM_SAMPLES} captured"
                )


            except Exception as error:

                print(
                    "Could not generate embedding:",
                    error
                )


    # ========================================================
    # CAMERA STATUS
    # ========================================================

    cv2.putText(
        frame,
        f"Samples: {sample_count}/{NUM_SAMPLES}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 255),
        2
    )


    cv2.putText(
        frame,
        "Press Q to cancel",
        (20, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2
    )


    # ========================================================
    # SHOW CAMERA
    # ========================================================

    cv2.imshow(
        "Face Enrollment",
        frame
    )


    # ========================================================
    # FINISH AFTER 5 SAMPLES
    # ========================================================

    if sample_count >= NUM_SAMPLES:

        break


    # ========================================================
    # QUIT
    # ========================================================

    key = cv2.waitKey(1) & 0xFF


    if key == ord("q"):

        print()
        print("Enrollment cancelled.")
        break


# ============================================================
# CLOSE CAMERA
# ============================================================

camera.release()

cv2.destroyAllWindows()


# ============================================================
# SAVE ONLY IF 5 SAMPLES WERE CAPTURED
# ============================================================

if len(embeddings) == NUM_SAMPLES:

    try:

        # ----------------------------------------------------
        # Average all five embeddings
        # ----------------------------------------------------

        final_embedding = np.mean(
            np.array(embeddings),
            axis=0
        )


        # ----------------------------------------------------
        # Normalize final embedding
        # ----------------------------------------------------

        norm = np.linalg.norm(
            final_embedding
        )


        if norm > 0:

            final_embedding = (
                final_embedding / norm
            )


        # ----------------------------------------------------
        # Convert to SQLite BLOB
        # ----------------------------------------------------

        embedding_blob = sqlite3.Binary(
            final_embedding.astype(
                np.float32
            ).tobytes()
        )


        # ----------------------------------------------------
        # Save embedding
        # ----------------------------------------------------

        cursor.execute(
            """
            UPDATE students
            SET face_encoding = ?
            WHERE student_id = ?
            """,
            (
                embedding_blob,
                student_id
            )
        )


        connection.commit()


        print()
        print("==========================================")
        print("       ENROLLMENT SUCCESSFUL")
        print("==========================================")
        print()

        print("Student       :", name)
        print("Roll Number   :", student_id)
        print("Samples       :", NUM_SAMPLES)
        print("Face Encoding : Saved")
        print()

    except Exception as error:

        connection.rollback()

        print()
        print("==========================================")
        print("       ENROLLMENT FAILED")
        print("==========================================")
        print()

        print("Error:", error)
        print("Database was NOT changed.")
        print()


else:

    print()
    print("==========================================")
    print("       ENROLLMENT CANCELLED")
    print("==========================================")
    print()

    print(
        f"Only {len(embeddings)} "
        f"of {NUM_SAMPLES} samples captured."
    )

    print()
    print("No face encoding was changed.")
    print()


# ============================================================
# CLOSE DATABASE
# ============================================================

connection.close()