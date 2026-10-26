# Web Dashboard (app.py) — drop-in for your existing project

## How to install
1. Copy these files into your **main project folder** (same folder as
   `database.py`, `main_attendance.py`, `attendance.db`, `models/`):
   - `app.py`
   - `config.py`
   - `create_login.py`
   - `templates/` (the whole folder)

2. Install Flask (if not already installed):
   ```
   pip install flask
   ```

3. Create logins for people who should be able to use the website
   (one time, per person):
   ```
   python create_login.py
   ```
   - For a **student**, the Username **must exactly match** their
     `student_id` (roll number) as stored in the `students` table —
     the dashboard looks up the student by matching `users.username`
     to `students.student_id`.
   - For **faculty**, the Username must exactly match the `faculty`
     text you used in `add_timetable.py` for their classes.
   - For **admin**, any username works.

4. Run the site:
   ```
   python app.py
   ```
   Open http://127.0.0.1:5000 and log in.

## What it does
- **Student dashboard** (`/student/dashboard`): overall attendance %,
  subject-wise %, and a day-by-day log of every class held this month
  with Present / Late / Absent, with month navigation (Prev/Next).
- **Class attendance sheet** (`/class/<timetable_id>/<date>`): opened
  from any row in the day-by-day log — shows subject, faculty, day,
  date, timing, and the full roll-number-wise list of who
  attended that specific period, with the logged-in student's row
  highlighted.
- **Faculty dashboard**: list of classes they teach with a shortcut to
  today's attendance sheet.
- **Admin dashboard**: basic counts (students / timetable slots /
  today's attendance) — a starting point to build a full admin UI on.

## Important note on "Absent"
`main_attendance.py` only ever **inserts a row** when a face is
recognised (Present/Late). It never writes an "Absent" row. So this
app **computes Absent itself**: for each student's section, it expands
the recurring weekly `timetable` into actual calendar dates for the
selected month (up to today), and any date with no matching row in
`attendance` is shown as Absent. This is why the tables line up
correctly even though the database never stores "Absent" directly.
