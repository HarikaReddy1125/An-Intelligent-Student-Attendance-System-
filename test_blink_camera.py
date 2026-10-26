
import cv2
from blink_detector import TwoBlinkDetector

detector = TwoBlinkDetector()
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("Could not open camera.")
    detector.close()
    raise SystemExit(1)

try:
    while True:
        ok, frame = camera.read()

        if not ok:
            print("Could not read camera frame.")
            break

        count, completed, message = detector.process(frame)

        cv2.putText(
            frame,
            message,
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0) if completed else (0, 200, 255),
            2,
        )

        cv2.imshow("Two-Blink Test", frame)

        if completed:
            print("Two blinks detected successfully.")
            break

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    camera.release()
    cv2.destroyAllWindows()
    detector.close()
