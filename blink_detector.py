"""Robust two-blink liveness detector for the Flask attendance app.

Requires MediaPipe Tasks and models/face_landmarker.task.
Public interface: TwoBlinkDetector.process(bgr_frame) -> (blink_count, completed, message)
"""
from pathlib import Path
import time
import cv2
import numpy as np
import mediapipe as mp


# MediaPipe Face Mesh landmark indices for eye aspect ratio (EAR).
_LEFT_EYE = (362, 385, 387, 263, 373, 380)
_RIGHT_EYE = (33, 160, 158, 133, 153, 144)


class TwoBlinkDetector:
    def __init__(self, model_path=None):
        root = Path(__file__).resolve().parent
        self.model_path = Path(model_path) if model_path else root / "models" / "face_landmarker.task"
        if not self.model_path.is_absolute():
            self.model_path = root / self.model_path
        if not self.model_path.exists():
            raise FileNotFoundError(f"Face landmark model not found: {self.model_path}")

        BaseOptions = mp.tasks.BaseOptions
        VisionRunningMode = mp.tasks.vision.RunningMode
        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=VisionRunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.45,
            min_face_presence_confidence=0.45,
            min_tracking_confidence=0.45,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self.landmarker = FaceLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1
        self._started_at = time.monotonic()
        self._baseline_samples = []
        self._open_ear = 0.26
        self._eye_closed = False
        self._closed_at = None
        self._last_blink_at = 0.0
        self.blink_count = 0
        self.completed = False

    @staticmethod
    def _ear(landmarks, indices):
        pts = np.array([[landmarks[i].x, landmarks[i].y] for i in indices], dtype=np.float32)
        # Indices order: outer corner, upper outer, upper inner, inner corner, lower inner, lower outer.
        vertical_1 = np.linalg.norm(pts[1] - pts[5])
        vertical_2 = np.linalg.norm(pts[2] - pts[4])
        horizontal = np.linalg.norm(pts[0] - pts[3])
        if horizontal < 1e-6:
            return 0.0
        return float((vertical_1 + vertical_2) / (2.0 * horizontal))

    def process(self, bgr_frame):
        if self.completed:
            return self.blink_count, True, "Two blinks detected. Matching your face..."
        if bgr_frame is None or getattr(bgr_frame, "size", 0) == 0:
            return self.blink_count, False, "Keep your face visible to the camera."

        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        now_ms = int((time.monotonic() - self._started_at) * 1000)
        self._last_timestamp_ms = max(now_ms, self._last_timestamp_ms + 1)
        result = self.landmarker.detect_for_video(mp_image, self._last_timestamp_ms)

        if not result.face_landmarks:
            self._eye_closed = False
            self._closed_at = None
            return self.blink_count, False, "Face not detected — look at the camera and improve lighting."

        landmarks = result.face_landmarks[0]
        ear_left = self._ear(landmarks, _LEFT_EYE)
        ear_right = self._ear(landmarks, _RIGHT_EYE)
        ear = (ear_left + ear_right) / 2.0
        now = time.monotonic()

        # Calibrate from open-eye frames, but do not let closed-eye frames lower the baseline.
        if not self._eye_closed and ear > 0.12:
            self._baseline_samples.append(ear)
            self._baseline_samples = self._baseline_samples[-25:]
            if self._baseline_samples:
                measured = float(np.median(self._baseline_samples))
                # Keep calibration within plausible values and adapt slowly to camera/face variation.
                measured = min(0.42, max(0.18, measured))
                self._open_ear = 0.75 * self._open_ear + 0.25 * measured

        close_threshold = max(0.115, self._open_ear * 0.70)
        reopen_threshold = max(close_threshold + 0.025, self._open_ear * 0.82)

        if not self._eye_closed:
            if ear < close_threshold:
                self._eye_closed = True
                self._closed_at = now
                return self.blink_count, False, f"Blink detected — open your eyes ({self.blink_count}/2)."
            elapsed = now - self._started_at
            if elapsed < 1.5:
                return self.blink_count, False, "Keep your eyes open briefly; then blink naturally twice."
            return self.blink_count, False, f"Blink naturally twice — progress {self.blink_count}/2."

        # Eye was closed; count it only when it opens again and it is not a duplicate.
        if ear > reopen_threshold:
            closed_duration = (now - self._closed_at) if self._closed_at is not None else 0.0
            self._eye_closed = False
            self._closed_at = None
            if 0.035 <= closed_duration <= 1.0 and (now - self._last_blink_at) >= 0.22:
                self.blink_count += 1
                self._last_blink_at = now
                if self.blink_count >= 2:
                    self.completed = True
                    return self.blink_count, True, "Two blinks detected. Matching your face..."
                return self.blink_count, False, "Blink 1/2 detected — blink once more."
            return self.blink_count, False, f"Eyes open. Blink naturally twice — progress {self.blink_count}/2."

        # Avoid a permanently latched closed-eye state if tracking glitches.
        if self._closed_at is not None and now - self._closed_at > 1.2:
            self._eye_closed = False
            self._closed_at = None
            return self.blink_count, False, "Blink was not clear. Keep your face steady and try again."
        return self.blink_count, False, f"Eyes closed — open them to register the blink ({self.blink_count}/2)."

    def close(self):
        if getattr(self, "landmarker", None) is not None:
            self.landmarker.close()
            self.landmarker = None
