import cv2
import sqlite3
import numpy as np
import os


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

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

# SFace cosine similarity threshold
# We will tune this later using real tests.
SIMILARITY_THRESHOLD = 0.40


# ============================================================
# CHECK FILES
# ============================================================

if not os.path.exists(YU_NET_MODEL):

    print("ERROR: YuNet model not found:")
    print(YU_NET_MODEL)
    exit()


if not os.path.exists(SFACE_MODEL):

    print("ERROR: SFace model not found:")
    print(SFACE_MODEL)
    exit()


if not os.path.exists(DATABASE_PATH):

    print("ERROR: Database not found:")
    print(DATABASE_PATH)
    exit()


# ============================================================
# DATABASE
# ============================================================

connection = sqlite3.connect(
    DATABASE_PATH
)

cursor = connection.cursor()


# ============================================================
# LOAD ENROLLED STUDENTS
# ============================================================

cursor.execute("""
    SELECT
        student_id,
        name,
        face_encoding
    FROM students
    WHERE face_encoding IS NOT NULL
""")


rows = cursor.fetchall()


if not rows:

    print()
    print("ERROR: No enrolled faces found.")
    print("Enroll at least one student first.")
    print()

    connection.close()
    exit()


students = []


for row in rows:

    student_id = row[0]
    name = row[1]
    blob = row[2]


    try:

        embedding = np.frombuffer(
            blob,
            dtype=np.float32
        )


        # Normalize

        norm = np.linalg.norm(
            embedding
        )

        if norm > 0:

            embedding = embedding / norm


        students.append(
            (
                student_id,
                name,
                embedding
            )
        )


    except Exception as error:

        print(
            f"Could not load encoding for "
            f"{student_id}: {error}"
        )


connection.close()


print()
print("==========================================")
print("       FACE RECOGNITION TEST")
print("==========================================")
print()

print(
    f"Enrolled faces loaded: {len(students)}"
)

print()

for student_id, name, _ in students:

    print(
        f"- {student_id} : {name}"
    )

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
print("Press Q to quit.")
print()


camera = cv2.VideoCapture(
    CAMERA_INDEX,
    cv2.CAP_DSHOW
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
    # Update detector input size
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
    # Process detected faces
    # --------------------------------------------------------

    if faces is not None:

        for face in faces:

            x = int(face[0])
            y = int(face[1])
            w = int(face[2])
            h = int(face[3])


            # ------------------------------------------------
            # Draw rectangle
            # ------------------------------------------------

            cv2.rectangle(
                frame,
                (x, y),
                (x + w, y + h),
                (0, 255, 0),
                2
            )


            # ------------------------------------------------
            # Generate SFace feature
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


                # Normalize feature

                norm = np.linalg.norm(
                    feature
                )

                if norm > 0:

                    feature = feature / norm


                # ------------------------------------------------
                # Compare against enrolled students
                # ------------------------------------------------

                best_student = None
                best_similarity = -1


                for (
                    student_id,
                    name,
                    stored_embedding
                ) in students:


                    similarity = float(
                        np.dot(
                            feature,
                            stored_embedding
                        )
                    )


                    if similarity > best_similarity:

                        best_similarity = similarity

                        best_student = (
                            student_id,
                            name
                        )


                # ------------------------------------------------
                # Determine identity
                # ------------------------------------------------

                if (
                    best_student is not None
                    and best_similarity >= SIMILARITY_THRESHOLD
                ):

                    student_id = best_student[0]
                    name = best_student[1]

                    label = (
                        f"{name}"
                    )

                    sub_label = (
                        f"{student_id} "
                        f"Similarity: "
                        f"{best_similarity:.2f}"
                    )

                    color = (
                        0,
                        255,
                        0
                    )


                else:

                    label = "UNKNOWN"

                    sub_label = (
                        f"Similarity: "
                        f"{best_similarity:.2f}"
                    )

                    color = (
                        0,
                        0,
                        255
                    )


                # ------------------------------------------------
                # Display result
                # ------------------------------------------------

                text_y = max(
                    y - 10,
                    30
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


                cv2.putText(
                    frame,
                    sub_label,
                    (
                        x,
                        text_y + 30
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2
                )


            except Exception as error:

                cv2.putText(
                    frame,
                    "Recognition Error",
                    (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2
                )

                print(
                    "Recognition error:",
                    error
                )


    # ========================================================
    # Display camera
    # ========================================================

    cv2.imshow(
        "Face Recognition Test",
        frame
    )


    # ========================================================
    # Quit
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
print("Recognition test closed.")