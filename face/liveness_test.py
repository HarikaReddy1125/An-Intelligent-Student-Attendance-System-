import cv2
import time


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_PATH = "models/face_detection_yunet_2026may.onnx"

CAMERA_INDEX = 0

# Face position thresholds
LEFT_THRESHOLD = 0.35
RIGHT_THRESHOLD = 0.65

# Number of consecutive frames required
# before accepting a movement.
REQUIRED_FRAMES = 5


# ============================================================
# LOAD YUNET
# ============================================================

print("===================================")
print("       LIVENESS DETECTION TEST")
print("===================================")
print()

print("Loading YuNet...")

detector = cv2.FaceDetectorYN.create(
    MODEL_PATH,
    "",
    (320, 320),
    0.8,
    0.3,
    5000
)

print("YuNet loaded successfully.")
print()


# ============================================================
# OPEN CAMERA
# ============================================================

print("Opening camera...")

camera = cv2.VideoCapture(CAMERA_INDEX)

if not camera.isOpened():
    print("ERROR: Could not open camera.")
    exit()

print("Camera opened successfully.")
print()


# ============================================================
# LIVENESS STATE
# ============================================================

# Required sequence:
#
# CENTER -> LEFT -> CENTER -> RIGHT -> LIVE
#

state = "CENTER"

left_frames = 0
right_frames = 0
center_frames = 0

liveness_verified = False

verification_time = None


# ============================================================
# INSTRUCTIONS
# ============================================================

print("===================================")
print("           INSTRUCTIONS")
print("===================================")
print()
print("1. Keep your face in the CENTER.")
print("2. Look slowly to the LEFT.")
print("3. Return to CENTER.")
print("4. Look slowly to the RIGHT.")
print()
print("The system will verify that movement.")
print()
print("Press Q to quit.")
print()


# ============================================================
# MAIN LOOP
# ============================================================

while True:

    success, frame = camera.read()

    if not success:
        print("ERROR: Could not read camera frame.")
        break


    height, width = frame.shape[:2]

    detector.setInputSize(
        (width, height)
    )


    # --------------------------------------------------------
    # FACE DETECTION
    # --------------------------------------------------------

    _, faces = detector.detect(frame)


    position = "NO FACE"


    if faces is not None and len(faces) > 0:

        # ----------------------------------------------------
        # SELECT LARGEST FACE
        # ----------------------------------------------------

        faces = sorted(
            faces,
            key=lambda f: f[2] * f[3],
            reverse=True
        )

        face = faces[0]


        # ----------------------------------------------------
        # FACE BOX
        # ----------------------------------------------------

        x, y, w, h = face[:4].astype(int)


        center_x = x + w // 2
        center_y = y + h // 2


        # ----------------------------------------------------
        # RELATIVE HORIZONTAL POSITION
        # ----------------------------------------------------

        relative_x = center_x / width


        if relative_x < LEFT_THRESHOLD:

            position = "LEFT"

        elif relative_x > RIGHT_THRESHOLD:

            position = "RIGHT"

        else:

            position = "CENTER"


        # ----------------------------------------------------
        # DRAW FACE
        # ----------------------------------------------------

        cv2.rectangle(
            frame,
            (x, y),
            (x + w, y + h),
            (0, 255, 0),
            2
        )


        # ----------------------------------------------------
        # DRAW FACE CENTER
        # ----------------------------------------------------

        cv2.circle(
            frame,
            (center_x, center_y),
            5,
            (0, 255, 255),
            -1
        )


        # ----------------------------------------------------
        # LIVENESS STATE MACHINE
        # ----------------------------------------------------

        if not liveness_verified:

            # ================================================
            # STEP 1: CENTER
            # ================================================

            if state == "CENTER":

                if position == "CENTER":

                    center_frames += 1

                else:

                    center_frames = 0


                if center_frames >= REQUIRED_FRAMES:

                    state = "LEFT"

                    center_frames = 0


            # ================================================
            # STEP 2: LEFT
            # ================================================

            elif state == "LEFT":

                if position == "LEFT":

                    left_frames += 1

                else:

                    left_frames = 0


                if left_frames >= REQUIRED_FRAMES:

                    state = "RETURN_CENTER"

                    left_frames = 0


            # ================================================
            # STEP 3: RETURN TO CENTER
            # ================================================

            elif state == "RETURN_CENTER":

                if position == "CENTER":

                    center_frames += 1

                else:

                    center_frames = 0


                if center_frames >= REQUIRED_FRAMES:

                    state = "RIGHT"

                    center_frames = 0


            # ================================================
            # STEP 4: RIGHT
            # ================================================

            elif state == "RIGHT":

                if position == "RIGHT":

                    right_frames += 1

                else:

                    right_frames = 0


                if right_frames >= REQUIRED_FRAMES:

                    liveness_verified = True

                    verification_time = time.time()

                    state = "VERIFIED"

                    right_frames = 0


    # ========================================================
    # DISPLAY STATUS
    # ========================================================

    if liveness_verified:

        status_text = "LIVE PERSON VERIFIED"

        status_color = (0, 255, 0)

        instruction_text = "LIVENESS CHECK PASSED"

    else:

        status_color = (0, 255, 255)

        if state == "CENTER":

            instruction_text = "Keep face CENTER"

        elif state == "LEFT":

            instruction_text = "Look LEFT"

        elif state == "RETURN_CENTER":

            instruction_text = "Return to CENTER"

        elif state == "RIGHT":

            instruction_text = "Look RIGHT"

        else:

            instruction_text = "Processing..."

        status_text = "Liveness: " + state


    # ========================================================
    # DRAW TEXT
    # ========================================================

    cv2.putText(
        frame,
        "Position: " + position,
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2
    )


    cv2.putText(
        frame,
        instruction_text,
        (20, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        status_color,
        2
    )


    cv2.putText(
        frame,
        status_text,
        (20, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        status_color,
        2
    )


    # --------------------------------------------------------
    # SHOW VERIFICATION MESSAGE
    # --------------------------------------------------------

    if liveness_verified:

        cv2.putText(
            frame,
            "✓ LIVE PERSON VERIFIED",
            (20, 170),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            3
        )


    # ========================================================
    # DISPLAY CAMERA
    # ========================================================

    cv2.imshow(
        "Liveness Detection Test",
        frame
    )


    # ========================================================
    # QUIT
    # ========================================================

    if cv2.waitKey(1) & 0xFF == ord("q"):

        break


# ============================================================
# CLEANUP
# ============================================================

camera.release()

cv2.destroyAllWindows()


print()
print("===================================")

if liveness_verified:

    print("      LIVENESS TEST PASSED")

else:

    print("      LIVENESS TEST NOT COMPLETED")

print("===================================")