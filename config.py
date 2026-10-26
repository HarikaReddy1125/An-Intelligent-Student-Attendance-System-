import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Point this to the SAME attendance.db used by main_attendance.py / database.py
DATABASE_PATH = os.path.join(BASE_DIR, "attendance.db")

SECRET_KEY = "change-this-secret-key-in-production"

# Attendance % below this shows a warning on the student dashboard
LOW_ATTENDANCE_THRESHOLD = 75