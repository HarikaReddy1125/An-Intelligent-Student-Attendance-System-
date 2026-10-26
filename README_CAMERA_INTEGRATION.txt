INTELLIGENT STUDENT ATTENDANCE SYSTEM - CAMERA INTEGRATION

Contents:
- app.py: complete Flask app with the existing routes plus browser-camera attendance endpoints.
- templates/home.html: public home page.
- templates/start_attendance.html: browser camera UI.

INSTALL / USE
1. Make a backup of your existing D:\student_attendance\app.py and templates folder.
2. Extract these files into D:\student_attendance, allowing app.py and the two template files to be replaced.
3. Keep your existing attendance.db and models folder. Do not replace or delete the database.
4. Ensure these model files exist:
   models\face_detection_yunet_2026may.onnx
   models\face_recognition_sface_2021dec.onnx
5. Install dependencies in your project venv if needed: pip install flask opencv-contrib-python numpy
6. Run from the project folder: python app.py
7. Open http://127.0.0.1:5001 and click Start Marking Attendance.

NOTES
- This build expects the database at D:\student_attendance\attendance.db, matching the supplied app.py.
- It reuses existing student face_encoding values and attendance tables; it does not reset the database.
- Camera access is requested by the browser.
- The movement check is basic liveness guidance, not a spoof-proof identity check. Supervise attendance and verify the database/schema in a backup copy before production use.
- Keep the camera endpoint on a trusted local network; do not expose it publicly without authentication, rate limiting and stronger liveness protections.
