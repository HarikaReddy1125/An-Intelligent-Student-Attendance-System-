import os
import sqlite3
import base64

import cv2
import numpy as np

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    current_app
)
from functools import wraps


# ============================================================
# BLUEPRINT
# ============================================================

enroll_bp = Blueprint(
    "enroll",
    __name__,
    url_prefix="/admin"
)


# ============================================================
# DATABASE
# ============================================================

def get_connection():

    database_path = os.path.join(
        current_app.root_path,
        "attendance.db"
    )

    conn = sqlite3.connect(
        database_path
    )

    conn.row_factory = sqlite3.Row

    return conn


# ============================================================
# ADMIN CHECK
# ============================================================

def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        from flask import session, redirect, url_for

        if session.get("user_id") is None:
            return redirect(
                url_for("login")
            )

        if session.get("role") != "admin":
            return redirect(
                url_for("home")
            )

        return function(
            *args,
            **kwargs
        )

    return wrapper


# ============================================================
# MODEL PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

MODEL_DIR = os.path.join(
    BASE_DIR,
    "models"
)

YUNET_MODEL_PATH = os.path.join(
    MODEL_DIR,
    "face_detection_yunet_2026may.onnx"
)

SFACE_MODEL_PATH = os.path.join(
    MODEL_DIR,
    "face_recognition_sface_2021dec.onnx"
)


# ============================================================
# SETTINGS
# ============================================================

NUM_SAMPLES = 5

DETECTION_SCORE = 0.90

NMS_THRESHOLD = 0.30

TOP_K = 5000


# ============================================================
# LOAD FACE MODELS
# ============================================================

_detector = None
_recognizer = None


def get_face_models():

    global _detector
    global _recognizer

    if (
        _detector is not None
        and _recognizer is not None
    ):
        return (
            _detector,
            _recognizer
        )

    if not os.path.isfile(
        YUNET_MODEL_PATH
    ):
        raise FileNotFoundError(
            "YuNet model not found: "
            + YUNET_MODEL_PATH
        )

    if not os.path.isfile(
        SFACE_MODEL_PATH
    ):
        raise FileNotFoundError(
            "SFace model not found: "
            + SFACE_MODEL_PATH
        )

    _detector = cv2.FaceDetectorYN.create(
        YUNET_MODEL_PATH,
        "",
        (640, 480),
        DETECTION_SCORE,
        NMS_THRESHOLD,
        TOP_K
    )

    _recognizer = cv2.FaceRecognizerSF.create(
        SFACE_MODEL_PATH,
        ""
    )

    return (
        _detector,
        _recognizer
    )


# ============================================================
# FACE EMBEDDING
# ============================================================

def generate_embedding(frame):

    detector, recognizer = (
        get_face_models()
    )

    height, width = frame.shape[:2]

    detector.setInputSize(
        (width, height)
    )

    _, faces = detector.detect(
        frame
    )

    if faces is None:

        return None, (
            "No face detected. "
            "Please position your face clearly."
        )

    if len(faces) > 1:

        return None, (
            "Multiple faces detected. "
            "Only one person is allowed."
        )

    if len(faces) == 0:

        return None, (
            "No face detected."
        )

    face = faces[0]

    try:

        aligned_face = (
            recognizer.alignCrop(
                frame,
                face
            )
        )

        feature = recognizer.feature(
            aligned_face
        )

        feature = feature.flatten()

        norm = np.linalg.norm(
            feature
        )

        if norm <= 0:

            return None, (
                "Invalid face encoding."
            )

        feature = (
            feature / norm
        )

        return feature, None

    except Exception as error:

        current_app.logger.exception(
            "Face embedding generation failed"
        )

        return None, (
            "Could not generate face encoding."
        )


# ============================================================
# PAGE
# ============================================================

@enroll_bp.route(
    "/enroll-students",
    methods=["GET"]
)
@admin_required
def enroll_students_page():

    return render_template(
        "enroll_students.html"
    )


# ============================================================
# FIND STUDENT
# ============================================================

@enroll_bp.route(
    "/enroll-students/find",
    methods=["POST"]
)
@admin_required
def find_student():

    data = request.get_json(
        silent=True
    ) or {}

    roll_number = str(
        data.get("roll_number")
        or ""
    ).strip()

    if not roll_number:

        return jsonify({
            "success": False,
            "message": (
                "Please enter a roll number."
            )
        }), 400

    conn = get_connection()

    try:

        student = conn.execute(
            """
            SELECT
                id,
                student_id,
                name,
                email,
                mobile,
                parent_mobile,
                department,
                year,
                section,
                face_encoding
            FROM students
            WHERE student_id = ?
            """,
            (roll_number,)
        ).fetchone()

        if student is None:

            return jsonify({
                "success": False,
                "message": (
                    "No student found with "
                    f"roll number {roll_number}."
                )
            }), 404

        return jsonify({
            "success": True,
            "student": {
                "id": student["id"],
                "student_id": student["student_id"],
                "name": student["name"],
                "email": student["email"] or "",
                "mobile": student["mobile"] or "",
                "parent_mobile": (
                    student["parent_mobile"]
                    or ""
                ),
                "department": (
                    student["department"]
                    or ""
                ),
                "year": (
                    student["year"]
                    or ""
                ),
                "section": (
                    student["section"]
                    or ""
                ),
                "already_enrolled": (
                    student["face_encoding"]
                    is not None
                )
            }
        })

    finally:

        conn.close()


# ============================================================
# CAPTURE ONE FACE SAMPLE
# ============================================================

@enroll_bp.route(
    "/enroll-students/capture",
    methods=["POST"]
)
@admin_required
def capture_sample():

    data = request.get_json(
        silent=True
    ) or {}

    image_data = str(
        data.get("image")
        or ""
    )

    if not image_data:

        return jsonify({
            "success": False,
            "message": "No camera image received."
        }), 400

    try:

        if "," in image_data:

            image_data = (
                image_data.split(",", 1)[1]
            )

        image_bytes = base64.b64decode(
            image_data
        )

        image_array = np.frombuffer(
            image_bytes,
            dtype=np.uint8
        )

        frame = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR
        )

        if frame is None:

            return jsonify({
                "success": False,
                "message": (
                    "Could not read camera image."
                )
            }), 400

    except Exception:

        return jsonify({
            "success": False,
            "message": (
                "Invalid camera image."
            )
        }), 400

    embedding, error = (
        generate_embedding(frame)
    )

    if embedding is None:

        return jsonify({
            "success": False,
            "message": error
        })

    return jsonify({
        "success": True,
        "message": "Face sample captured.",
        "embedding": base64.b64encode(
            embedding.astype(
                np.float32
            ).tobytes()
        ).decode("utf-8")
    })


# ============================================================
# SAVE FINAL FACE
# ============================================================

@enroll_bp.route(
    "/enroll-students/save",
    methods=["POST"]
)
@admin_required
def save_enrollment():

    data = request.get_json(
        silent=True
    ) or {}

    student_id = str(
        data.get("student_id")
        or ""
    ).strip()

    embeddings = data.get(
        "embeddings"
    )

    if not student_id:

        return jsonify({
            "success": False,
            "message": (
                "Student roll number is required."
            )
        }), 400

    if not isinstance(
        embeddings,
        list
    ):

        return jsonify({
            "success": False,
            "message": (
                "Face samples are missing."
            )
        }), 400

    if len(embeddings) != NUM_SAMPLES:

        return jsonify({
            "success": False,
            "message": (
                f"Exactly {NUM_SAMPLES} "
                "samples are required."
            )
        }), 400

    try:

        decoded_embeddings = []

        for encoded in embeddings:

            raw = base64.b64decode(
                encoded
            )

            embedding = np.frombuffer(
                raw,
                dtype=np.float32
            ).copy()

            if embedding.size == 0:

                raise ValueError(
                    "Empty embedding."
                )

            norm = np.linalg.norm(
                embedding
            )

            if norm <= 0:

                raise ValueError(
                    "Invalid embedding."
                )

            embedding /= norm

            decoded_embeddings.append(
                embedding
            )

        # ----------------------------------------------------
        # Average all samples
        # ----------------------------------------------------

        final_embedding = np.mean(
            np.array(
                decoded_embeddings,
                dtype=np.float32
            ),
            axis=0
        )

        # ----------------------------------------------------
        # Normalize final embedding
        # ----------------------------------------------------

        norm = np.linalg.norm(
            final_embedding
        )

        if norm <= 0:

            raise ValueError(
                "Invalid final embedding."
            )

        final_embedding /= norm

        # ----------------------------------------------------
        # Convert to SQLite BLOB
        # ----------------------------------------------------

        embedding_blob = (
            sqlite3.Binary(
                final_embedding.astype(
                    np.float32
                ).tobytes()
            )
        )

    except Exception:

        current_app.logger.exception(
            "Could not prepare face encoding"
        )

        return jsonify({
            "success": False,
            "message": (
                "Could not process face samples."
            )
        }), 400

    conn = get_connection()

    try:

        student = conn.execute(
            """
            SELECT
                id,
                student_id,
                name
            FROM students
            WHERE student_id = ?
            """,
            (student_id,)
        ).fetchone()

        if student is None:

            return jsonify({
                "success": False,
                "message": (
                    "Student no longer exists."
                )
            }), 404

        conn.execute(
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

        conn.commit()

        return jsonify({
            "success": True,
            "message": (
                "Face enrollment completed "
                "successfully."
            ),
            "student": {
                "student_id":
                    student["student_id"],
                "name":
                    student["name"]
            }
        })

    except Exception:

        conn.rollback()

        current_app.logger.exception(
            "Failed to save face enrollment"
        )

        return jsonify({
            "success": False,
            "message": (
                "Database error while saving "
                "face enrollment."
            )
        }), 500

    finally:

        conn.close()


# ============================================================
# REMOVE EXISTING FACE
# ============================================================

@enroll_bp.route(
    "/enroll-students/remove",
    methods=["POST"]
)
@admin_required
def remove_enrollment():

    data = request.get_json(
        silent=True
    ) or {}

    student_id = str(
        data.get("student_id")
        or ""
    ).strip()

    if not student_id:

        return jsonify({
            "success": False,
            "message": (
                "Student roll number is required."
            )
        }), 400

    conn = get_connection()

    try:

        result = conn.execute(
            """
            UPDATE students
            SET face_encoding = NULL
            WHERE student_id = ?
            """,
            (student_id,)
        )

        if result.rowcount == 0:

            return jsonify({
                "success": False,
                "message": (
                    "Student not found."
                )
            }), 404

        conn.commit()

        return jsonify({
            "success": True,
            "message": (
                "Existing face enrollment removed."
            )
        })

    except Exception:

        conn.rollback()

        current_app.logger.exception(
            "Failed to remove face enrollment"
        )

        return jsonify({
            "success": False,
            "message": (
                "Could not remove enrollment."
            )
        }), 500

    finally:

        conn.close()