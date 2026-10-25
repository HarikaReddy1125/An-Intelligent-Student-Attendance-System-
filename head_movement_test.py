import cv2
import numpy as np


MODEL_PATH = "models/face_detection_yunet_2026may.onnx"


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
    print("ERROR: Could not open camera.")
    exit()


print("===================================")
print("      HEAD MOVEMENT TEST")
print("===================================")
print()
print("Move your head slowly LEFT and RIGHT.")
print("Press Q to quit.")
print()


while True:

    success, frame = camera.read()

    if not success:
        break


    height, width = frame.shape[:2]

    detector.setInputSize(
        (width, height)
    )


    _, faces = detector.detect(frame)


    if faces is not None and len(faces) > 0:

        # Select largest face
        faces = sorted(
            faces,
            key=lambda f: f[2] * f[3],
            reverse=True
        )

        face = faces[0]


        x, y, w, h = face[:4].astype(int)


        # ---------------------------------
        # Face center
        # ---------------------------------

        center_x = x + w // 2
        center_y = y + h // 2


        # ---------------------------------
        # Face horizontal position
        # ---------------------------------

        relative_x = center_x / width


        if relative_x < 0.35:

            position = "LEFT"

        elif relative_x > 0.65:

            position = "RIGHT"

        else:

            position = "CENTER"


        # ---------------------------------
        # Draw face
        # ---------------------------------

        cv2.rectangle(
            frame,
            (x, y),
            (x + w, y + h),
            (0, 255, 0),
            2
        )


        # ---------------------------------
        # Draw center point
        # ---------------------------------

        cv2.circle(
            frame,
            (center_x, center_y),
            5,
            (0, 255, 255),
            -1
        )


        # ---------------------------------
        # Display position
        # ---------------------------------

        cv2.putText(
            frame,
            f"Position: {position}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 255),
            2
        )


        cv2.putText(
            frame,
            f"X: {relative_x:.2f}",
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2
        )


    cv2.imshow(
        "Head Movement Test",
        frame
    )


    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


camera.release()
cv2.destroyAllWindows()

print("Test completed.")