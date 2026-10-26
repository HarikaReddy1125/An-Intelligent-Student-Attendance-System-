import cv2
import os
import sqlite3
import numpy as np


# ---------------------------------------
# Paths
# ---------------------------------------

YUNET_MODEL = "models/face_detection_yunet_2026may.onnx"
SFACE_MODEL = "models/face_recognition_sface_2021dec.onnx"

DATABASE = "attendance.db"


# ---------------------------------------
# Check model files
# ---------------------------------------

if not os.path.exists(YUNET_MODEL):
    print("ERROR: YuNet model not found:")
    print(YUNET_MODEL)
    exit()

if not os.path.exists(SFACE_MODEL):
    print("ERROR: SFace model not found:")
    print(SFACE_MODEL)
    exit()


# ---------------------------------------
# Get student ID
# ---------------------------------------

student_id = input("Enter Student ID to enroll: ").strip()

if not student_id:
    print("Student ID cannot be empty.")
    exit()


# ---------------------------------------
# Check student exists
# ---------------------------------------

connection = sqlite3.connect(DATABASE)
cursor = connection.cursor()

cursor.execute(
    """
    SELECT id, student_id, name
    FROM students
    WHERE student_id = ?
    """,
    (student_id,)
)

student = cursor.fetchone()

connection.close()


if student is None:
    print("Student not found in database.")
    print("Please register the student first.")
    exit()


database_id = student[0]
student_id = student[1]
student_name = student[2]

print()
print("Student found:")
print("ID   :", student_id)
print("Name :", student_name)
print()


# ---------------------------------------
# Create YuNet detector
# ---------------------------------------

detector = cv2.FaceDetectorYN.create(
    YUNET_MODEL,
    "",
    (320, 320),
    0.8,
    0.3,
    5000
)


# ---------------------------------------
# Create SFace recognizer
# ---------------------------------------

recognizer = cv2.FaceRecognizerSF.create(
    SFACE_MODEL,
    "",
    0,
    0
)


# ---------------------------------------
# Open camera
# ---------------------------------------

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("ERROR: Could not open laptop camera.")
    exit()


print("======================================")
print("        FACE ENROLLMENT")
print("======================================")
print()
print("Look at the camera.")
print("Keep your face inside the green box.")
print()
print("We will capture 5 face samples.")
print()
print("Press Q to cancel.")
print()


embeddings = []

sample_count = 5


# ---------------------------------------
# Capture face samples
# ---------------------------------------

while len(embeddings) < sample_count:

    success, frame = camera.read()

    if not success:
        print("ERROR: Could not read camera.")
        break

    height, width = frame.shape[:2]

    detector.setInputSize((width, height))

    _, faces = detector.detect(frame)

    face_found = False

    if faces is not None and len(faces) > 0:

        # Use the largest detected face
        faces = sorted(
            faces,
            key=lambda f: f[2] * f[3],
            reverse=True
        )

        face = faces[0]

        x, y, w, h = face[:4].astype(int)

        # Make sure coordinates are inside frame
        x = max(0, x)
        y = max(0, y)
        w = min(w, width - x)
        h = min(h, height - y)

        cv2.rectangle(
            frame,
            (x, y),
            (x + w, y + h),
            (0, 255, 0),
            2
        )

        # Face landmarks
        landmarks = face[4:14].reshape(5, 2).astype(int)

        for lx, ly in landmarks:
            cv2.circle(
                frame,
                (lx, ly),
                3,
                (0, 255, 255),
                -1
            )

        face_found = True

        cv2.putText(
            frame,
            "Face detected",
            (x, max(y - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2
        )

    cv2.putText(
        frame,
        f"Samples: {len(embeddings)}/{sample_count}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 255),
        2
    )

    cv2.imshow(
        "Student Face Enrollment",
        frame
    )

    # Capture a sample every time SPACE is pressed
    key = cv2.waitKey(1) & 0xFF

    if key == ord("q"):
        print("Enrollment cancelled.")
        camera.release()
        cv2.destroyAllWindows()
        exit()

    if key == 32 and face_found:

        # Align and crop face
        aligned_face = recognizer.alignCrop(
            frame,
            face
        )

        # Generate SFace feature embedding
        feature = recognizer.feature(
            aligned_face
        )

        embeddings.append(feature.copy())

        print(
            f"Captured sample "
            f"{len(embeddings)}/{sample_count}"
        )


camera.release()
cv2.destroyAllWindows()


# ---------------------------------------
# Make sure samples exist
# ---------------------------------------

if len(embeddings) == 0:

    print("No face samples captured.")
    exit()


# ---------------------------------------
# Average embeddings
# ---------------------------------------

average_embedding = np.mean(
    np.vstack(embeddings),
    axis=0,
    keepdims=True
)


# Normalize embedding
average_embedding = (
    average_embedding /
    np.linalg.norm(average_embedding)
)


# ---------------------------------------
# Convert embedding to binary
# ---------------------------------------

embedding_blob = average_embedding.astype(
    np.float32
).tobytes()


# ---------------------------------------
# Save embedding to database
# ---------------------------------------

connection = sqlite3.connect(DATABASE)
cursor = connection.cursor()

cursor.execute(
    """
    UPDATE students
    SET face_encoding = ?
    WHERE id = ?
    """,
    (
        embedding_blob,
        database_id
    )
)

connection.commit()
connection.close()


print()
print("======================================")
print("       ENROLLMENT COMPLETE")
print("======================================")
print()
print("Student ID :", student_id)
print("Name       :", student_name)
print("Samples    :", len(embeddings))
print()
print("Face embedding saved to database.")