import cv2

MODEL_PATH = "models/face_detection_yunet_2026may.onnx"

# Create YuNet face detector
detector = cv2.FaceDetectorYN.create(
    MODEL_PATH,
    "",
    (320, 320),
    0.8,
    0.3,
    5000
)

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("ERROR: Could not open laptop camera.")
    exit()

print("YuNet face detection started.")
print("Press Q to quit.")

while True:

    success, frame = camera.read()

    if not success:
        print("ERROR: Could not read camera frame.")
        break

    # Set detector input size to actual camera frame
    height, width = frame.shape[:2]
    detector.setInputSize((width, height))

    # Detect faces
    _, faces = detector.detect(frame)

    face_count = 0

    if faces is not None:

        face_count = len(faces)

        for face in faces:

            x, y, w, h = face[:4].astype(int)

            # Draw face rectangle
            cv2.rectangle(
                frame,
                (x, y),
                (x + w, y + h),
                (0, 255, 0),
                2
            )

            # Detection confidence
            confidence = face[-1]

            cv2.putText(
                frame,
                f"Face {confidence:.2f}",
                (x, max(y - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

            # Draw 5 facial landmarks
            landmarks = face[4:14].reshape(5, 2).astype(int)

            for lx, ly in landmarks:

                cv2.circle(
                    frame,
                    (lx, ly),
                    3,
                    (0, 255, 255),
                    -1
                )

    cv2.putText(
        frame,
        f"Faces detected: {face_count}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 255),
        2
    )

    cv2.imshow(
        "Student Attendance - YuNet Face Detection",
        frame
    )

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()

print("Face detection stopped.")