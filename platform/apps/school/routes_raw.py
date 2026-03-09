import os
import sqlite3
import zipfile
import tempfile
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, send_file, g
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import flask
print("Flask version:", flask.__version__)
print("Flask module path:", flask.__file__)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from routes_super_badges import super_badges_bp
from flask import request, jsonify
from homework_utils import save_homework_files
from flask import send_from_directory



app = Flask(__name__)
# Load configuration from app/config.py Config class
app.config.from_object('app.config.Config')
app.secret_key = os.environ.get('SECRET_KEY', 'default-secret-key')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB file upload limit

# Fix Railway PostgreSQL URL (postgres:// -> postgresql://)
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url

# WhiteNoise for serving static files in production
if not app.debug:
    from whitenoise import WhiteNoise
    app.wsgi_app = WhiteNoise(app.wsgi_app, root=os.path.join(os.path.dirname(__file__), 'static'), prefix='static/')

# --- Password Reset Token Serializer ---
serializer = URLSafeTimedSerializer(app.secret_key)

# --- Helper: Get user by email or username ---
def get_user_by_username(identifier):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, username FROM users WHERE username=%s', (identifier,))
    user = c.fetchone()
    conn.close()
    return user  # (id, username) or None

# --- Helper: Update password hash ---
def update_user_password(user_id, new_password):
    password_hash = generate_password_hash(new_password)
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE users SET password_hash=%s WHERE id=%s', (password_hash, user_id))
    conn.commit()
    conn.close()

# --- Helper: Send reset link via email ---
from flask_mail import Mail, Message

# Initialize Flask-Mail

mail = Mail(app)

def send_reset_email(username, token):
    reset_url = url_for('reset_password', token=token, _external=True)
    msg = Message(
        subject="Password Reset Request",
        recipients=[username],  # username is the user's email address
        body=f"Hello,\n\nTo reset your password, click the following link:\n{reset_url}\n\nIf you did not request a password reset, please ignore this email."
    )
    try:
        mail.send(msg)
        print(f"[EMAIL SENT] Password reset link sent to {username}")
    except Exception as e:
        print(f"[EMAIL ERROR] Could not send password reset email to {username}: {e}")
    print(f"[RESET LINK] For {username}: {reset_url}")

# --- Forgot Password Route ---
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    message = None
    if request.method == 'POST':
        identifier = request.form['email'].strip()
        user = get_user_by_username(identifier)
        if user:
            user_id, username = user
            token = serializer.dumps({'user_id': user_id}, salt='reset-password')
            send_reset_email(username, token)
            message = 'A reset link has been sent (check console in local dev).'
        else:
            message = 'No user found with that username.'
    return render_template('forgot_password.html', message=message)

# --- Reset Password Route ---
@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    message = None
    try:
        data = serializer.loads(token, salt='reset-password', max_age=3600)  # 1 hour expiry
        user_id = data['user_id']
    except SignatureExpired:
        return render_template('reset_password.html', message='This reset link has expired.')
    except BadSignature:
        return render_template('reset_password.html', message='Invalid or tampered reset link.')

    if request.method == 'POST':
        new_password = request.form['password']
        if len(new_password) < 6:
            message = 'Password must be at least 6 characters.'
        else:
            update_user_password(user_id, new_password)
            message = 'Your password has been reset. You can now log in.'
            return render_template('reset_password.html', message=message)
    return render_template('reset_password.html', message=message)


from config import UPLOAD_FOLDER
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SUPPORT_MATERIAL_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'support_material')
os.makedirs(SUPPORT_MATERIAL_FOLDER, exist_ok=True)

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Enable WAL mode for better concurrent access
    conn.execute("PRAGMA journal_mode=WAL;")
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('super_admin', 'local_admin', 'teacher', 'student')),
        created_by INTEGER,
        FOREIGN KEY(created_by) REFERENCES users(id)
    )''')
    # Teachers table (linked to local admin)
    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        local_admin_id INTEGER NOT NULL,
        email TEXT,
        phone TEXT,
        notes TEXT,
        alerts TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(local_admin_id) REFERENCES users(id)
    )''')
    # Curriculum groups
    c.execute("""
        CREATE TABLE IF NOT EXISTS curriculum_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            local_admin_id INTEGER NOT NULL,
            level_id INTEGER NOT NULL,
            FOREIGN KEY(local_admin_id) REFERENCES users(id),
            FOREIGN KEY(level_id) REFERENCES levels(id)
        )
    """)
    # Curriculum items
    c.execute('''CREATE TABLE IF NOT EXISTS curriculum_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY(group_id) REFERENCES curriculum_groups(id)
    )''')
    # Levels table
    c.execute('''CREATE TABLE IF NOT EXISTS levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        local_admin_id INTEGER NOT NULL,
        FOREIGN KEY(local_admin_id) REFERENCES users(id)
    )''')
    # Classes
    c.execute('''CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        teacher_id INTEGER,
        local_admin_id INTEGER NOT NULL,
        level_id INTEGER,
        backup_teacher_id INTEGER,
        FOREIGN KEY(teacher_id) REFERENCES teachers(id),
        FOREIGN KEY(local_admin_id) REFERENCES users(id),
        FOREIGN KEY(level_id) REFERENCES levels(id),
        FOREIGN KEY(backup_teacher_id) REFERENCES teachers(id)
    )''')
    # Students
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        class_id INTEGER NOT NULL,
        email TEXT,
        phone TEXT,
        notes TEXT,
        alerts TEXT,
        FOREIGN KEY(class_id) REFERENCES classes(id)
    )''')
    # Student grades (badges)
    c.execute('''CREATE TABLE IF NOT EXISTS student_grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        curriculum_item_id INTEGER NOT NULL,
        level INTEGER,
        comment TEXT,
        comment_updated_at TEXT,
        comment_user TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(curriculum_item_id) REFERENCES curriculum_items(id)
    )''')
    # Class courses
    c.execute('''CREATE TABLE IF NOT EXISTS class_courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        curriculum_item_id INTEGER NOT NULL,
        FOREIGN KEY(class_id) REFERENCES classes(id),
        FOREIGN KEY(curriculum_item_id) REFERENCES curriculum_items(id)
    )''')
    # Events table
    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        start DATETIME NOT NULL,
        end DATETIME,
        color TEXT,
        recurrence TEXT,
        recurrence_group_id TEXT,
        recurrence_end DATE,
        FOREIGN KEY(class_id) REFERENCES classes(id)
    )''')
    # Ensure recurrence_group_id and recurrence_end columns exist (for migrations)
    c.execute("PRAGMA table_info(events)")
    columns = [row[1] for row in c.fetchall()]
    if 'recurrence_group_id' not in columns:
        c.execute("ALTER TABLE events ADD COLUMN recurrence_group_id TEXT")
    if 'recurrence_end' not in columns:
        c.execute("ALTER TABLE events ADD COLUMN recurrence_end DATE")
    # Backup log table
    c.execute('''CREATE TABLE IF NOT EXISTS backup_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backup_date TEXT NOT NULL,
        backup_by TEXT
    )''')
    conn.commit()
    conn.close()

# --- Ensure teachers table has extra columns ---
def ensure_teacher_columns():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    def has_column(col):
        c.execute("PRAGMA table_info(teachers)")
        return col in [row[1] for row in c.fetchall()]
    for col in ['email', 'phone', 'notes', 'alerts', 'name']:
        if not has_column(col):
            try:
                c.execute(f"ALTER TABLE teachers ADD COLUMN {col} TEXT")
                conn.commit()
            except sqlite3.OperationalError as e:
                # If column already exists, ignore
                if 'duplicate column name' in str(e):
                    pass
                else:
                    raise
    conn.close()

ensure_teacher_columns()

# --- Ensure students table has extra columns ---
def ensure_student_columns():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    def has_column(col):
        c.execute("PRAGMA table_info(students)")
        return col in [row[1] for row in c.fetchall()]
    for col in ['email', 'phone', 'notes', 'alerts']:
        if not has_column(col):
            try:
                c.execute(f"ALTER TABLE students ADD COLUMN {col} TEXT")
                conn.commit()
            except sqlite3.OperationalError as e:
                # If column already exists, ignore
                if 'duplicate column name' in str(e):
                    pass
                else:
                    raise
    conn.close()

ensure_student_columns()

# --- Ensure student_grades table has comment column ---
def ensure_student_grades_comment_column():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("PRAGMA table_info(student_grades)")
    columns = [row[1] for row in c.fetchall()]
    if 'comment' not in columns:
        c.execute("ALTER TABLE student_grades ADD COLUMN comment TEXT")
        conn.commit()
    conn.close()
ensure_student_grades_comment_column()

# --- Ensure student_grades table has comment columns for timestamp and user ---
def ensure_student_grades_comment_metadata_columns():
    with sqlite3.connect('ArabicSchool.db', timeout=2, check_same_thread=False) as conn:
        c = conn.cursor()
        c.execute('PRAGMA table_info(student_grades)')
        columns = [row[1] for row in c.fetchall()]
        if 'comment_updated_at' not in columns:
            c.execute("ALTER TABLE student_grades ADD COLUMN comment_updated_at TEXT")
        if 'comment_user' not in columns:
            c.execute("ALTER TABLE student_grades ADD COLUMN comment_user TEXT")
        conn.commit()
ensure_student_grades_comment_metadata_columns()

# --- Auth Decorators ---
from auth_utils import login_required

# --- User Registration/Login ---
@app.route('/register_super_admin', methods=['GET', 'POST'])
def register_super_admin():
    # Only allow if no super admin exists
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE role='super_admin'")
    if c.fetchone():
        conn.close()
        return 'Super admin already exists!', 403
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password_hash = generate_password_hash(password)
        c.execute('INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id',
                  (username, password_hash, 'super_admin'))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    conn.close()
    return render_template('register_super_admin.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT id, password_hash, role FROM users WHERE username=%s', (username,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['role'] = user[2]
            session['username'] = username
            # Store teacher_id in session if role is teacher
            if user[2] == 'teacher':
                conn2 = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
                c2 = conn2.cursor()
                c2.execute('SELECT id FROM teachers WHERE user_id=%s', (user[0],))
                teacher_row = c2.fetchone()
                if teacher_row:
                    session['teacher_id'] = teacher_row[0]
                conn2.close()
            if user[2] == 'student':
                # Look up all students for this parent/user by email
                conn2 = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
                c2 = conn2.cursor()
                c2.execute('''
                    SELECT s.id, s.class_id, s.name, c.name as class_name, l.name as level_name, s.email
                    FROM students s
                    LEFT JOIN classes c ON s.class_id = c.id
                    LEFT JOIN levels l ON c.level_id = l.id
                    WHERE s.email=%s
                ''', (username,))
                students = c2.fetchall()
                conn2.close()
                if not students:
                    error = 'Student record not found for this user.'
                    return render_template('login.html', error=error)
                # Filter out students with no class_id
                students_with_class = [s for s in students if s[1] is not None]
                if len(students_with_class) == 1:
                    student_id, class_id = students_with_class[0][:2]
                    return redirect(url_for('student_abilities', student_id=student_id, class_id=class_id))
                elif len(students_with_class) > 1:
                    # Render selection page with all students as cards
                    student_cards = [
                        {
                            'id': s[0],
                            'class_id': s[1],
                            'name': s[2],
                            'class_name': s[3] or 'بدون صف',
                            'level_name': s[4] or '',
                            'username': s[5]  # parent email
                        } for s in students_with_class
                    ]
                    return render_template('select_student.html', students=student_cards)
                else:
                    error = 'You are not assigned to a class yet. Please contact admin.'
                    return render_template('login.html', error=error)
            return redirect(url_for('dashboard'))
        error = 'Invalid credentials'
        return render_template('login.html', error=error)
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Dashboard (role-based) ---

#from werkzeug.security import generate_password_hash

@app.route('/manage_local_admins')
@login_required('local_admin')
def manage_local_admins():
    return render_template('manage_local_admins.html')

@app.route('/api/local_admins', methods=['GET'])
@login_required('local_admin')
@login_required()
def api_list_local_admins():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT id, username, name, is_director FROM users WHERE role='local_admin'")
    admins = [{'id': row[0], 'username': row[1], 'name': row[2], 'is_director': row[3]} for row in c.fetchall()]
    conn.close()
    from flask import jsonify
    return jsonify(list(admins))

@app.route('/api/local_admins/<int:admin_id>/set_director', methods=['POST'])
@login_required('local_admin')
def set_local_admin_director(admin_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Set all local_admins to is_director=0
    c.execute("UPDATE users SET is_director=0 WHERE role='local_admin'")
    # Set selected admin to is_director=1
    c.execute("UPDATE users SET is_director=1 WHERE id=%s AND role='local_admin'", (admin_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/local_admins', methods=['POST'])
@login_required('local_admin')
@login_required()
def api_add_local_admin():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    # Email validation
    from email_validator import validate_email, EmailNotValidError
    try:
        valid = validate_email(username)
        username = valid.email
    except EmailNotValidError:
        return jsonify({'success': False, 'error': 'يرجى إدخال بريد إلكتروني صحيح'}), 400
    if not name or not username or not password:
        return jsonify({'success': False, 'error': 'الرجاء تعبئة جميع الحقول'}), 400
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE username=%s', (username,))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'اسم المستخدم مستخدم بالفعل'}), 400
    password_hash = generate_password_hash(password)
    c.execute("INSERT INTO users (name, username, password_hash, role) VALUES (%s, %s, %s, 'local_admin')", (name, username, password_hash))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/local_admins/<int:admin_id>', methods=['PUT'])
@login_required('local_admin')
@login_required()
def api_edit_local_admin(admin_id):
    data = request.get_json()
    name = data.get('name')
    username = data.get('username')
    if not name or not username:
        return jsonify({'success': False, 'error': 'الرجاء تعبئة جميع الحقول'}), 400
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE id=%s AND role="local_admin"', (admin_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'المستخدم غير موجود'}), 404
    c.execute('SELECT id FROM users WHERE username=%s AND id!=%s', (username, admin_id))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'اسم المستخدم مستخدم بالفعل'}), 400
    c.execute('UPDATE users SET name=%s, username=%s WHERE id=%s', (name, username, admin_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/local_admins/<int:admin_id>', methods=['DELETE'])
@login_required('local_admin')
@login_required()
def api_delete_local_admin(admin_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE id=%s AND role="local_admin"', (admin_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': 'المستخدم غير موجود'}), 404
    c.execute('DELETE FROM users WHERE id=%s', (admin_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/dashboard')
@login_required('super_admin', 'local_admin', 'teacher')
def dashboard():
    # Load school info
    info_path = os.path.join(os.path.dirname(__file__), 'school_info.json')
    if os.path.exists(info_path):
        with open(info_path, encoding='utf-8') as f:
            school_info = json.load(f)
    else:
        school_info = {"name": "", "logo": "school_logo.png"}
    return render_template('dashboard.html', role=session.get('role'), username=session.get('username'), school_info=school_info)

# --- Events API ---
from flask import g

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

@app.route('/api/events/<int:class_id>', methods=['GET'])
def get_events(class_id):
    db = get_db()
    cur = db.execute('SELECT * FROM events WHERE class_id = %s', (class_id,))
    events = [dict(row) for row in cur.fetchall()]
    return jsonify(events)

@app.route('/api/events', methods=['POST'])
def create_event():
    from datetime import timedelta
    import time
    data = request.json
    print('[DEBUG] create_event data:', data)
    db = get_db()
    recurrence = data.get('recurrence', 'none')
    recurrence_end = data.get('recurrence_end')
    start = data['start']
    end = data.get('end')
    event_rows = []
    if recurrence in ['weekly', 'monthly'] and recurrence_end:
        # Generate recurrence group id
        recurrence_group_id = f"rec_{int(time.time()*1000)}"
        # Parse dates
        dt_start = datetime.fromisoformat(start)
        dt_end = datetime.fromisoformat(recurrence_end)
        delta = timedelta(weeks=1) if recurrence == 'weekly' else None
        if recurrence == 'monthly':
            def add_months(dt, n):
                # Simple month addition logic
                month = dt.month - 1 + n
                year = dt.year + month // 12
                month = month % 12 + 1
                day = min(dt.day, [31,29 if year%4==0 and (year%100!=0 or year%400==0) else 28,31,30,31,30,31,31,30,31,30,31][month-1])
                return dt.replace(year=year, month=month, day=day)
        events_to_create = []
        dt_current = dt_start
        while dt_current <= dt_end:
            events_to_create.append(dt_current)
            if recurrence == 'weekly':
                dt_current += delta
            else:
                dt_current = add_months(dt_current, 1)
        for dt in events_to_create:
            cursor = db.execute('INSERT INTO events (class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id RETURNING id',
                (data['class_id'], data['title'], data.get('description'), dt.isoformat(), end, data.get('color'), recurrence, recurrence_group_id, recurrence_end))
            event_id = cursor.fetchone()[0]
            event_rows.append(event_id)
        db.commit()
        # Return the first created event
        cur = db.execute('SELECT id, class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end FROM events WHERE id=%s', (event_rows[0],))
        row = cur.fetchone()
        if row:
            event = {
                'id': row[0],
                'class_id': row[1],
                'title': row[2],
                'description': row[3],
                'start': row[4],
                'end': row[5],
                'color': row[6],
                'recurrence': row[7],
                'recurrence_group_id': row[8],
                'recurrence_end': row[9]
            }
            return jsonify({'success': True, 'event': event}), 201
        else:
            return jsonify({'success': False, 'error': 'Event not found after creation'}), 500
    else:
        # Non-recurring event
        cursor = db.execute('INSERT INTO events (class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL)',
            (data['class_id'], data['title'], data.get('description'), start, end, data.get('color'), recurrence))
        db.commit()
        event_id = cursor.fetchone()[0]
        cur = db.execute('SELECT id, class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end FROM events WHERE id=%s', (event_id,))
        row = cur.fetchone()
        if row:
            event = {
                'id': row[0],
                'class_id': row[1],
                'title': row[2],
                'description': row[3],
                'start': row[4],
                'end': row[5],
                'color': row[6],
                'recurrence': row[7],
                'recurrence_group_id': row[8],
                'recurrence_end': row[9]
            }
            return jsonify({'success': True, 'event': event}), 201
        else:
            return jsonify({'success': False, 'error': 'Event not found after creation'}), 500



@app.route('/api/events/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    db = get_db()
    delete_all = request.args.get('all') == '1'
    if delete_all:
        # Find recurrence_group_id for this event
        cur = db.execute('SELECT recurrence_group_id FROM events WHERE id=%s', (event_id,))
        row = cur.fetchone()
        if row and row[0]:
            group_id = row[0]
            db.execute('DELETE FROM events WHERE recurrence_group_id=%s', (group_id,))
            db.commit()
            return jsonify({'success': True})
        else:
            # Fallback: just delete the single event if no group id found
            db.execute('DELETE FROM events WHERE id=%s', (event_id,))
            db.commit()
            return jsonify({'success': True})
    else:
        db.execute('DELETE FROM events WHERE id=%s', (event_id,))
        db.commit()
        return jsonify({'success': True})

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    else:
        return redirect(url_for('login'))

# --- User Management APIs ---

@app.route('/api/check_user_exists', methods=['GET', 'POST'])
@login_required()
def api_check_user_exists():
    import sqlite3
    if request.method == 'POST':
        data = request.get_json(force=True)
        username = data.get('username')
    else:
        username = request.args.get('username')
    exists = False
    if username:
        conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT 1 FROM users WHERE username=%s', (username,))
        exists = c.fetchone() is not None
        conn.close()
    return jsonify({'exists': exists})

@app.route('/create_user', methods=['POST'])
@login_required('super_admin')
def create_local_admin():
    data = request.json
    username = data['username']
    password = data['password']
    role = data['role']
    if role not in ['local_admin', 'teacher', 'student']:
        return jsonify({'error': 'Invalid role'}), 400
    password_hash = generate_password_hash(password)
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username, password_hash, role, created_by) VALUES (%s, %s, %s, %s) RETURNING id RETURNING id',
                  (username, password_hash, role, session['user_id']))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Username already exists'}), 400
    conn.close()
    return jsonify({'success': True})

@app.route('/list_users')
@login_required('super_admin')
def list_users():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, username, role FROM users')
    users = [{'id': row[0], 'username': row[1], 'role': row[2]} for row in c.fetchall()]
    conn.close()
    return jsonify(users)

@app.route('/update_user', methods=['POST'])
@login_required('super_admin')
def update_user():
    import sys
    data = request.json
    user_id = data.get('id')
    new_role = data.get('role')
    new_password = data.get('password')



    if not user_id:
        print("[DEBUG] Missing user id", file=sys.stderr)
        return jsonify({'error': 'Missing user id'}), 400
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    if new_role:
        c.execute('UPDATE users SET role=%s WHERE id=%s', (new_role, user_id))
    if new_password:
        password_hash = generate_password_hash(new_password)
        print(f"[DEBUG] Saving password_hash: {repr(password_hash)}", file=sys.stderr)
        c.execute('UPDATE users SET password_hash=%s WHERE id=%s', (password_hash, user_id))
    else:
        print("[DEBUG] No new password provided; password will not be changed.", file=sys.stderr)
    conn.commit()
    conn.close()
    print("[DEBUG] Update complete", file=sys.stderr)
    return jsonify({'success': True})

@app.route('/delete_user', methods=['POST'])
@login_required('super_admin')
def delete_user():
    data = request.json
    user_id = data.get('id')
    if not user_id:
        return jsonify({'error': 'Missing user id'}), 400
    # Prevent deleting self or last super admin
    if user_id == session['user_id']:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users WHERE role="super_admin"')
    if c.fetchone()[0] <= 1:
        c.execute('SELECT role FROM users WHERE id=%s', (user_id,))
        if c.fetchone() and c.fetchone()[0] == 'super_admin':
            conn.close()
            return jsonify({'error': 'Cannot delete the last super admin'}), 400
    c.execute('DELETE FROM users WHERE id=%s', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Events: Edit Event ---
@app.route('/api/events/<int:event_id>', methods=['PUT'])
def update_event(event_id):
    data = request.json
    print('[DEBUG] update_event data:', data)
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    update_all = request.args.get('all') == '1'
    if update_all:
        # Find recurrence_group_id for this event
        c.execute('SELECT recurrence_group_id FROM events WHERE id=%s', (event_id,))
        row = c.fetchone()
        if row and row[0]:
            group_id = row[0]
            # Update all events in the group
            c.execute('''UPDATE events SET title=%s, description=%s, color=%s, recurrence=%s, recurrence_end=%s WHERE recurrence_group_id=%s''',
                      (data['title'], data.get('description'), data.get('color'), data.get('recurrence'), data.get('recurrence_end'), group_id))
            conn.commit()
            # Fetch one updated event to return
            c.execute('SELECT id, class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end FROM events WHERE recurrence_group_id=%s LIMIT 1', (group_id,))
            row = c.fetchone()
            conn.close()
            if row:
                event = {
                    'id': row[0],
                    'class_id': row[1],
                    'title': row[2],
                    'description': row[3],
                    'start': row[4],
                    'end': row[5],
                    'color': row[6],
                    'recurrence': row[7],
                    'recurrence_group_id': row[8],
                    'recurrence_end': row[9]
                }
                return jsonify(event)
            else:
                return jsonify({'error': 'Event not found'}), 404
        else:
            return jsonify({'error': 'No recurrence group found'}), 404
    else:
        # Single event update
        c.execute('''UPDATE events SET title=%s, description=%s, start=%s, end=%s, color=%s, recurrence=%s, recurrence_end=%s WHERE id=%s''',
                  (data['title'], data.get('description'), data['start'], data.get('end'), data.get('color'), data.get('recurrence'), data.get('recurrence_end'), event_id))
        conn.commit()
        # Fetch updated event
        c.execute('SELECT id, class_id, title, description, start, end, color, recurrence, recurrence_group_id, recurrence_end FROM events WHERE id=%s', (event_id,))
        row = c.fetchone()
        conn.close()
        if row:
            event = {
                'id': row[0],
                'class_id': row[1],
                'title': row[2],
                'description': row[3],
                'start': row[4],
                'end': row[5],
                'color': row[6],
                'recurrence': row[7],
                'recurrence_group_id': row[8],
                'recurrence_end': row[9]
            }
            return jsonify(event)
        else:
            return jsonify({'error': 'Event not found'}), 404

# --- Local Admin: Teachers Management ---
@app.route('/teachers', methods=['GET'])
@login_required('local_admin')
def list_teachers():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('''SELECT t.id, u.username, t.email, t.phone, t.notes, t.alerts, t.name FROM teachers t JOIN users u ON t.user_id = u.id''')
    teachers = [{'id': row[0], 'username': row[1], 'email': row[2] or '', 'phone': row[3] or '', 'notes': row[4] or '', 'alerts': row[5] or '', 'name': row[6] or ''} for row in c.fetchall()]
    conn.close()
    return jsonify(teachers)

@app.route('/teachers', methods=['POST'])
@login_required('local_admin')
def add_teacher():
    ensure_teacher_columns()  # Ensure 'name' column exists
    data = request.json
    username = data['username']
    password = data['password']
    name = data.get('name', '')
    password_hash = generate_password_hash(password)
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Create user as teacher
    try:
        c.execute('INSERT INTO users (username, password_hash, role, created_by) VALUES (%s, %s, %s, %s) RETURNING id',
                  (username, password_hash, 'teacher', session['user_id']))
        user_id = c.fetchone()[0]
        # Link to teachers table, store name
        c.execute('INSERT INTO teachers (user_id, local_admin_id, name, email) VALUES (%s, %s, %s, %s)', (user_id, session['user_id'], name, username))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Username already exists'}), 400
    conn.close()
    return jsonify({'success': True})

@app.route('/teachers/<int:teacher_id>', methods=['DELETE'])
@login_required('local_admin')
def delete_teacher(teacher_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Remove from teachers table and users table
    c.execute('SELECT user_id FROM teachers WHERE id=%s AND local_admin_id=%s', (teacher_id, session['user_id']))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    user_id = row[0]
    c.execute('DELETE FROM teachers WHERE id=%s', (teacher_id,))
    c.execute('DELETE FROM users WHERE id=%s', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/teachers/<int:teacher_id>', methods=['PUT'])
@login_required('local_admin')
def update_teacher(teacher_id):
    data = request.json
    new_username = data.get('username')
    new_password = data.get('password')
    phone = data.get('phone')
    notes = data.get('notes')
    alerts = data.get('alerts')
    name = data.get('name')
    # For this system, email and username are unified, so use new_username for both
    email = new_username
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Get the user_id for this teacher and make sure it belongs to this local_admin
    c.execute('SELECT user_id FROM teachers WHERE id=%s AND local_admin_id=%s', (teacher_id, session['user_id']))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    user_id = row[0]
    # Check for username conflict if username is changing
    if new_username:
        c.execute('SELECT id FROM users WHERE username=%s AND id<>%s', (new_username, user_id))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'اسم المستخدم مستخدم بالفعل'}), 400
        c.execute('UPDATE users SET username=%s WHERE id=%s', (new_username, user_id))
        # Also update teachers.email to match username
        c.execute('UPDATE teachers SET email=%s WHERE id=%s', (new_username, teacher_id))
    if new_password:
        password_hash = generate_password_hash(new_password)
        c.execute('UPDATE users SET password_hash=%s WHERE id=%s', (password_hash, user_id))
    # Update teacher details
    updates = []
    params = []
    if phone is not None:
        updates.append('phone = %s')
        params.append(phone)
    if notes is not None:
        updates.append('notes = %s')
        params.append(notes)
    if alerts is not None:
        updates.append('alerts = %s')
        params.append(alerts)
    if name is not None:
        updates.append('name = %s')
        params.append(name)
    if updates:
        params.append(teacher_id)
        c.execute(f'UPDATE teachers SET {", ".join(updates)} WHERE id=%s', params)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Local Admin: Curriculum Groups/Items Management ---
@app.route('/curriculum_groups', methods=['GET'])
@login_required('local_admin', 'teacher')
def list_curriculum_groups():
    level_id = request.args.get('level_id')
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    if level_id:
        c.execute('SELECT id, name FROM curriculum_groups WHERE level_id=%s', (level_id,))
    else:
        c.execute('SELECT id, name FROM curriculum_groups')
    groups = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
    conn.close()
    return jsonify(groups)

@app.route('/curriculum_groups', methods=['POST'])
@login_required('local_admin')
def add_curriculum_group():
    data = request.json
    name = data['name']
    level_id = data['level_id']
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT INTO curriculum_groups (name, local_admin_id, level_id) VALUES (%s, %s, %s)', (name, session['user_id'], level_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/curriculum_groups/<int:group_id>', methods=['DELETE', 'PUT'])
@login_required('local_admin'  )
def delete_curriculum_group(group_id):
    level_id = request.args.get('level_id')
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    if request.method == 'DELETE':
        if level_id:
            c.execute('DELETE FROM curriculum_groups WHERE id=%s AND local_admin_id=%s AND level_id=%s', (group_id, session['user_id'], level_id))
        else:
            c.execute('DELETE FROM curriculum_groups WHERE id=%s AND local_admin_id=%s', (group_id, session['user_id']))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    elif request.method == 'PUT':
        data = request.json
        name = data.get('name')
        if name:
            c.execute('UPDATE curriculum_groups SET name=%s WHERE id=%s AND local_admin_id=%s', (name, group_id, session['user_id']))
            conn.commit()
        conn.close()
        return jsonify({'success': True})

@app.route('/curriculum_items/<int:group_id>', methods=['GET'])
@login_required('local_admin', 'teacher')
def list_curriculum_items(group_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, name FROM curriculum_items WHERE group_id=%s', (group_id,))
    items = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
    conn.close()
    return jsonify(items)

@app.route('/curriculum_items', methods=['POST'])
@login_required('local_admin')
def add_curriculum_item():
    data = request.json
    group_id = data['group_id']
    name = data['name']
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT INTO curriculum_items (group_id, name) VALUES (%s, %s)', (group_id, name))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/curriculum_items/<int:item_id>', methods=['PUT', 'DELETE'])
@login_required('local_admin')
def update_or_delete_curriculum_item(item_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    if request.method == 'PUT':
        data = request.json
        name = data.get('name')
        if name:
            c.execute('UPDATE curriculum_items SET name=%s WHERE id=%s', (name, item_id))
            conn.commit()
        conn.close()
        return jsonify({'success': True})
    elif request.method == 'DELETE':
        c.execute('DELETE FROM curriculum_items WHERE id=%s', (item_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})

@app.route('/update_group_name', methods=['POST'])
@login_required('local_admin')
def update_group_name():
    data = request.json
    group_id = data['group_id']
    new_name = data['new_name']
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE curriculum_groups SET name=%s WHERE id=%s AND local_admin_id=%s', (new_name, group_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/update_subject_name', methods=['POST'])
@login_required('local_admin')
def update_subject_name():
    data = request.json
    subject_id = data['subject_id']
    new_name = data['new_name']
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE curriculum_items SET name=%s WHERE id=%s', (new_name, subject_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Levels Management ---
@app.route('/levels', methods=['GET'])
@login_required('local_admin')
def list_levels():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, name FROM levels')
    levels = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
    conn.close()
    return jsonify(levels)

@app.route('/levels', methods=['POST'])
@login_required('local_admin')
def add_level():
    data = request.json
    name = data['name']
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT INTO levels (name, local_admin_id) VALUES (%s, %s)', (name, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/delete_level/<int:level_id>', methods=['DELETE'])
@login_required('local_admin')
def delete_level(level_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM levels WHERE id=%s AND local_admin_id=%s', (level_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/edit_level_name', methods=['POST'])
@login_required('local_admin')
def edit_level_name():
    data = request.get_json()
    level_id = data.get('level_id')
    new_name = data.get('new_name')
    if not (level_id and new_name):
        return jsonify(success=False, error="Missing data")
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('UPDATE levels SET name = %s WHERE id = %s AND local_admin_id = %s', (new_name, level_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify(success=True)

# --- Flask routes and logic below ---

from flask import session

# User-friendly handler for large file uploads
@app.errorhandler(413)
def file_too_large(e):
    if request.accept_mimetypes['application/json'] or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False, 'error': 'الملف أكبر من الحجم المسموح (20MB)'}), 413
    return '<h3 style="color:red">الملف أكبر من الحجم المسموح (20MB)</h3>', 413


def ensure_announcement_expiry_column():
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute("PRAGMA table_info(announcements)")
    columns = [row[1] for row in c.fetchall()]
    if 'expiry' not in columns:
        c.execute('ALTER TABLE announcements ADD COLUMN expiry TEXT')
        conn.commit()
    conn.close()

@app.route('/api/class/<int:class_id>/announcement', methods=['GET'])
def get_class_announcement(class_id):
    ensure_announcement_expiry_column()
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        expiry TEXT
    )''')
    c.execute('SELECT text, created_at, user_id, expiry FROM announcements WHERE class_id=%s ORDER BY id DESC LIMIT 1', (class_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'success': True, 'text': row[0], 'created_at': row[1], 'user_id': row[2], 'expiry': row[3]}
    else:
        return {'success': False, 'text': '', 'expiry': ''}

@app.route('/api/class/<int:class_id>/announcement', methods=['POST'])
def add_class_announcement(class_id):
    data = request.get_json()
    text = data.get('text', '').strip()
    user_id = session.get('user_id')
    if not text or not user_id:
        return {'success': False, 'error': 'Missing data'}, 400
    timestamp = datetime.now().isoformat(sep=' ', timespec='seconds')
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        expiry TEXT
    )''')
    c.execute('INSERT INTO announcements (class_id, text, created_at, user_id, expiry) VALUES (%s, %s, %s, %s, %s)',
              (class_id, text, timestamp, user_id, data.get('expiry')))
    conn.commit()
    conn.close()
    return {'success': True}

# --- Classes Management ---
@app.route('/classes', methods=['GET'])
@login_required('super_admin', 'local_admin', 'teacher')
def list_classes():
    import sqlite3
    from flask import session, request, jsonify
    print("[DEBUG] /classes endpoint called")
    print(f"[DEBUG] session: {dict(session)}")
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    role = session.get('role')
    user_id = session.get('user_id')
    print(f"[DEBUG] role={role}, user_id={user_id}")
    group_by = request.args.get('group_by', 'level')
    if role == 'teacher':
        teacher_id = session.get('teacher_id')
        print(f"[DEBUG] teacher_id from session: {teacher_id}")
        if teacher_id is None:
            conn.close()
            return jsonify([])
        c.execute('''
            SELECT classes.id, classes.name, classes.level_id, l.name as level_name,
                   classes.teacher_id, t.name as teacher_name,
                   classes.backup_teacher_id, tb.name as backup_teacher_name,
                   classes.dawra1_pub_start, classes.dawra1_pub_end,
                   classes.dawra2_pub_start, classes.dawra2_pub_end,
                   classes.dawra3_pub_start, classes.dawra3_pub_end,
                   classes.year_pub_start, classes.year_pub_end
            FROM classes
            LEFT JOIN levels l ON classes.level_id = l.id
            LEFT JOIN teachers t ON classes.teacher_id = t.id
            LEFT JOIN teachers tb ON classes.backup_teacher_id = tb.id
            WHERE classes.teacher_id = %s OR classes.backup_teacher_id = %s
        ''', (teacher_id, teacher_id))
        debug_rows = c.fetchall()
        print(f"[DEBUG] SQL rows for teacher: {debug_rows}")
        # Re-execute for actual fetch loop
        c.execute('''
            SELECT classes.id, classes.name, classes.level_id, l.name as level_name,
                   classes.teacher_id, t.name as teacher_name,
                   classes.backup_teacher_id, tb.name as backup_teacher_name,
                   classes.dawra1_pub_start, classes.dawra1_pub_end,
                   classes.dawra2_pub_start, classes.dawra2_pub_end,
                   classes.dawra3_pub_start, classes.dawra3_pub_end,
                   classes.year_pub_start, classes.year_pub_end
            FROM classes
            LEFT JOIN levels l ON classes.level_id = l.id
            LEFT JOIN teachers t ON classes.teacher_id = t.id
            LEFT JOIN teachers tb ON classes.backup_teacher_id = tb.id
            WHERE classes.teacher_id = %s OR classes.backup_teacher_id = %s
        ''', (teacher_id, teacher_id))
    else:
        c.execute('''
            SELECT classes.id, classes.name, classes.level_id, l.name as level_name,
                   classes.teacher_id, t.name as teacher_name,
                   classes.backup_teacher_id, tb.name as backup_teacher_name,
                   classes.dawra1_pub_start, classes.dawra1_pub_end,
                   classes.dawra2_pub_start, classes.dawra2_pub_end,
                   classes.dawra3_pub_start, classes.dawra3_pub_end,
                   classes.year_pub_start, classes.year_pub_end
            FROM classes
            LEFT JOIN levels l ON classes.level_id = l.id
            LEFT JOIN teachers t ON classes.teacher_id = t.id
            LEFT JOIN teachers tb ON classes.backup_teacher_id = tb.id
        ''')
    classes = []
    for row in c.fetchall():
        classes.append({
            'id': row[0],
            'name': row[1],
            'level_id': row[2],
            'level_name': row[3],
            'teacher_id': row[4],
            'teacher_name': row[5],
            'backup_teacher_id': row[6],
            'backup_teacher_name': row[7],
            'dawra1_pub_start': row[8],
            'dawra1_pub_end': row[9],
            'dawra2_pub_start': row[10],
            'dawra2_pub_end': row[11],
            'dawra3_pub_start': row[12],
            'dawra3_pub_end': row[13],
            'year_pub_start': row[14],
            'year_pub_end': row[15],
        })
    conn.close()
    # Grouping logic
    if group_by == 'none':
        return jsonify({'flat': classes, 'group_by': group_by})
    grouped = {}
    key_map = {
        'level': 'level_name',
        'teacher': 'teacher_name',
        'assistant': 'backup_teacher_name'
    }
    key = key_map.get(group_by, 'level_name')
    for cls in classes:
        group_val = cls.get(key) or '\u063a\u064a\u0631 \u0645\u062d\u062f\u062f'
        grouped.setdefault(group_val, []).append(cls)
    return jsonify({'grouped': grouped, 'group_by': group_by})


@app.route('/classes', methods=['POST'])
@login_required('local_admin')
def add_class():
    data = request.json
    name = data['name']
    level_id = data.get('level_id')
    teacher_id = data.get('teacher_id')
    backup_teacher_id = data.get('backup_teacher_id')
    print('[DEBUG] Received:', name, level_id, teacher_id, backup_teacher_id)
    # Apply edit logic: cast to int if not None/empty, else None
    level_id = int(level_id) if level_id not in (None, '', 'null', 'undefined') else None
    teacher_id = int(teacher_id) if teacher_id not in (None, '', 'null', 'undefined') else None
    backup_teacher_id = int(backup_teacher_id) if backup_teacher_id not in (None, '', 'null', 'undefined') else None
    print('[DEBUG] Processed:', name, level_id, teacher_id, backup_teacher_id)
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    sql = 'INSERT INTO classes (name, local_admin_id, level_id, teacher_id, backup_teacher_id) VALUES (%s, %s, %s, %s, %s)'
    values = (name, session['user_id'], level_id, teacher_id, backup_teacher_id)
    print('[DEBUG] SQL:', sql)
    print('[DEBUG] VALUES:', values)
    c.execute(sql, values)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/classes/<int:class_id>', methods=['DELETE'])
@login_required('local_admin')
def delete_class(class_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM classes WHERE id=%s AND local_admin_id=%s', (class_id, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/classes/<int:class_id>', methods=['GET', 'PUT'])
@login_required('local_admin', 'teacher')
def class_detail(class_id):
    if request.method == 'GET':
        conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
        c = conn.cursor()
        c.execute('''
            SELECT classes.id, classes.name, classes.level_id, l.name as level_name,
                   classes.teacher_id, ut.username as teacher_name,
                   classes.backup_teacher_id, ub.username as backup_teacher_name,
                   classes.dawra1_pub_start, classes.dawra1_pub_end,
                   classes.dawra2_pub_start, classes.dawra2_pub_end,
                   classes.dawra3_pub_start, classes.dawra3_pub_end,
                   classes.year_pub_start, classes.year_pub_end
            FROM classes
            LEFT JOIN levels l ON classes.level_id = l.id
            LEFT JOIN teachers t ON classes.teacher_id = t.id
            LEFT JOIN users ut ON t.user_id = ut.id
            LEFT JOIN teachers bt ON classes.backup_teacher_id = bt.id
            LEFT JOIN users ub ON bt.user_id = ub.id
            WHERE classes.id=%s AND classes.local_admin_id=%s
        ''', (class_id, session['user_id']))
        row = c.fetchone()
        conn.close()
        if not row:
            return jsonify({'error': 'Class not found'}), 404
        class_data = {
            'id': row[0],
            'name': row[1],
            'level_id': row[2],
            'level_name': row[3],
            'teacher_id': row[4],
            'teacher_name': row[5],
            'backup_teacher_id': row[6],
            'backup_teacher_name': row[7],
            'dawra1_pub_start': row[8],
            'dawra1_pub_end': row[9],
            'dawra2_pub_start': row[10],
            'dawra2_pub_end': row[11],
            'dawra3_pub_start': row[12],
            'dawra3_pub_end': row[13],
            'year_pub_start': row[14],
            'year_pub_end': row[15],
        }
        return jsonify(class_data)
    # PUT method (update_class) logic follows below
    data = request.json
    name = data.get('name')
    level_id = data.get('level_id')
    teacher_id = data.get('teacher_id')
    backup_teacher_id = data.get('backup_teacher_id')
    # Publication date fields
    dawra1_pub_start = data.get('dawra1_pub_start')
    dawra1_pub_end = data.get('dawra1_pub_end')
    dawra2_pub_start = data.get('dawra2_pub_start')
    dawra2_pub_end = data.get('dawra2_pub_end')
    dawra3_pub_start = data.get('dawra3_pub_start')
    dawra3_pub_end = data.get('dawra3_pub_end')
    year_pub_start = data.get('year_pub_start')
    year_pub_end = data.get('year_pub_end')
    # Convert empty strings to None
    def none_if_empty(val):
        return val if val not in ('', None) else None
    level_id = none_if_empty(level_id)
    teacher_id = none_if_empty(teacher_id)
    backup_teacher_id = none_if_empty(backup_teacher_id)
    dawra1_pub_start = none_if_empty(dawra1_pub_start)
    dawra1_pub_end = none_if_empty(dawra1_pub_end)
    dawra2_pub_start = none_if_empty(dawra2_pub_start)
    dawra2_pub_end = none_if_empty(dawra2_pub_end)
    dawra3_pub_start = none_if_empty(dawra3_pub_start)
    dawra3_pub_end = none_if_empty(dawra3_pub_end)
    year_pub_start = none_if_empty(year_pub_start)
    year_pub_end = none_if_empty(year_pub_end)
    updates = []
    params = []
    if name is not None:
        updates.append('name = %s')
        params.append(name)
    if level_id is not None:
        updates.append('level_id = %s')
        params.append(level_id)
    if teacher_id is not None:
        updates.append('teacher_id = %s')
        params.append(teacher_id)
    if backup_teacher_id is not None:
        updates.append('backup_teacher_id = %s')
        params.append(backup_teacher_id)
    updates.append('dawra1_pub_start = %s')
    params.append(dawra1_pub_start)
    updates.append('dawra1_pub_end = %s')
    params.append(dawra1_pub_end)
    updates.append('dawra2_pub_start = %s')
    params.append(dawra2_pub_start)
    updates.append('dawra2_pub_end = %s')
    params.append(dawra2_pub_end)
    updates.append('dawra3_pub_start = %s')
    params.append(dawra3_pub_start)
    updates.append('dawra3_pub_end = %s')
    params.append(dawra3_pub_end)
    updates.append('year_pub_start = %s')
    params.append(year_pub_start)
    updates.append('year_pub_end = %s')
    params.append(year_pub_end)
    params.append(class_id)
    sql = f'UPDATE classes SET {", ".join(updates)} WHERE id = %s'
    print('Updating class:', class_id)
    print('SQL:', sql)
    print('Params:', params)
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute(sql, params)
    print('Rows affected:', c.rowcount)
    conn.commit()
    conn.close()
    return jsonify({'success': True})
    data = request.json
    name = data.get('name')
    level_id = data.get('level_id')
    teacher_id = data.get('teacher_id')
    backup_teacher_id = data.get('backup_teacher_id')
    # Publication date fields
    dawra1_pub_start = data.get('dawra1_pub_start')
    dawra1_pub_end = data.get('dawra1_pub_end')
    dawra2_pub_start = data.get('dawra2_pub_start')
    dawra2_pub_end = data.get('dawra2_pub_end')
    dawra3_pub_start = data.get('dawra3_pub_start')
    dawra3_pub_end = data.get('dawra3_pub_end')
    year_pub_start = data.get('year_pub_start')
    year_pub_end = data.get('year_pub_end')
    # Convert empty strings to None
    def none_if_empty(val):
        return val if val not in ('', None) else None
    level_id = none_if_empty(level_id)
    teacher_id = none_if_empty(teacher_id)
    backup_teacher_id = none_if_empty(backup_teacher_id)
    dawra1_pub_start = none_if_empty(dawra1_pub_start)
    dawra1_pub_end = none_if_empty(dawra1_pub_end)
    dawra2_pub_start = none_if_empty(dawra2_pub_start)
    dawra2_pub_end = none_if_empty(dawra2_pub_end)
    dawra3_pub_start = none_if_empty(dawra3_pub_start)
    dawra3_pub_end = none_if_empty(dawra3_pub_end)
    year_pub_start = none_if_empty(year_pub_start)
    year_pub_end = none_if_empty(year_pub_end)
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    updates = []
    params = []
    if name is not None:
        updates.append('name = %s')
        params.append(name)
    updates.append('level_id = %s')
    params.append(level_id)
    updates.append('teacher_id = %s')
    params.append(teacher_id)
    updates.append('backup_teacher_id = %s')
    params.append(backup_teacher_id)
    updates.append('dawra1_pub_start = %s')
    params.append(dawra1_pub_start)
    updates.append('dawra1_pub_end = %s')
    params.append(dawra1_pub_end)
    updates.append('dawra2_pub_start = %s')
    params.append(dawra2_pub_start)
    updates.append('dawra2_pub_end = %s')
    params.append(dawra2_pub_end)
    updates.append('dawra3_pub_start = %s')
    params.append(dawra3_pub_start)
    updates.append('dawra3_pub_end = %s')
    params.append(dawra3_pub_end)
    updates.append('year_pub_start = %s')
    params.append(year_pub_start)
    updates.append('year_pub_end = %s')
    params.append(year_pub_end)
    params.append(class_id)
    sql = f'UPDATE classes SET {", ".join(updates)} WHERE id = %s'
    print('Updating class:', class_id)
    print('SQL:', sql)
    print('Params:', params)
    c.execute(sql, params)
    print('Rows affected:', c.rowcount)
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Attach/Detach Courses to Class ---
@app.route('/class_courses/<int:class_id>', methods=['GET'])
@login_required('local_admin')
def get_class_courses(class_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('''SELECT ci.id, ci.name FROM class_courses cc JOIN curriculum_items ci ON cc.curriculum_item_id=ci.id WHERE cc.class_id=%s''', (class_id,))
    courses = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
    conn.close()
    return jsonify(courses)

@app.route('/class_courses/<int:class_id>', methods=['POST'])
@login_required('local_admin')
def add_course_to_class(class_id):
    data = request.json
    curriculum_item_id = data['curriculum_item_id']
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT INTO class_courses (class_id, curriculum_item_id) VALUES (%s, %s)', (class_id, curriculum_item_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/class_courses/<int:class_id>/<int:curriculum_item_id>', methods=['DELETE'])
@login_required('local_admin')
def remove_course_from_class(class_id, curriculum_item_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM class_courses WHERE class_id=%s AND curriculum_item_id=%s', (class_id, curriculum_item_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Students Management ---
@app.route('/students', methods=['GET'])
@login_required('super_admin', 'local_admin', 'teacher')
def get_students():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    role = session.get('role')
    students = []
    if role == 'teacher':
        teacher_id = session.get('teacher_id')
        # Only show students in classes assigned to this teacher
        c.execute('''SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes, s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, c.id as class_id
                     FROM students s
                     LEFT JOIN users u ON s.email = u.username
                     LEFT JOIN classes c ON s.class_id = c.id
                     WHERE c.teacher_id = %s OR c.backup_teacher_id = %s
                     ORDER BY s.id DESC''', (teacher_id, teacher_id))
        rows = c.fetchall()
    else:
        c.execute('''SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes, s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, c.id as class_id, s.sex
                     FROM students s
                     LEFT JOIN users u ON s.email = u.username
                     LEFT JOIN classes c ON s.class_id = c.id
                     ORDER BY s.id DESC''')
        rows = c.fetchall()
    students = [
        {
            'id': row[0],
            'parent_username': row[1] or '',
            'name': row[2] or '',
            'email': row[3] or '',
            'phone': row[4] or '',
            'notes': row[5] or '',
            'alerts': row[6] or '',
            'date_of_birth': row[7] or '',
            'secondary_email': row[8] or '',
            'class_name': row[9] or 'بدون صف',
            'class_id': row[10],
            'sex': row[11] or ''
        } for row in rows
    ]
    conn.close()
    print(students)
    # Defensive: always return a list
    if not isinstance(students, list):
        students = [students]
    return jsonify(students)

# --- Backend-driven student search endpoint ---
@app.route('/students/search', methods=['GET'])
@login_required('super_admin', 'local_admin', 'teacher')
def search_students():
    query = request.args.get('query', '').strip()
    print(f"[DEBUG] /students/search called with query: '{query}'")
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    role = session.get('role')
    students = []
    if role == 'teacher':
        teacher_id = session.get('teacher_id')
        if not query:
            c.execute('''
                SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes, s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, s.class_id, s.sex
                FROM students s
                LEFT JOIN users u ON s.email = u.username
                LEFT JOIN classes c ON s.class_id = c.id
                WHERE (c.teacher_id = %s OR c.backup_teacher_id = %s)
                ORDER BY s.id DESC''', (teacher_id, teacher_id))
            rows = c.fetchall()
        else:
            like_query = f'%{query}%'
            c.execute('''
                SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes, s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, s.class_id, s.sex
                FROM students s
                LEFT JOIN users u ON s.email = u.username
                LEFT JOIN classes c ON s.class_id = c.id
                WHERE (c.teacher_id = %s OR c.backup_teacher_id = %s) AND (
                    s.name LIKE ? OR u.username LIKE ? OR s.email LIKE ? OR s.phone LIKE ?
                )
                ORDER BY s.id DESC''', (teacher_id, teacher_id, like_query, like_query, like_query, like_query))
            rows = c.fetchall()
    else:
        if not query:
            c.execute('''
                SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes, s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, s.class_id, s.sex
                FROM students s
                LEFT JOIN users u ON s.email = u.username
                LEFT JOIN classes c ON s.class_id = c.id
                ORDER BY s.id DESC''')
            rows = c.fetchall()
        else:
            like_query = f'%{query}%'
            c.execute('''
                SELECT s.id, u.username as parent_username, s.name, s.email, s.phone, s.notes, s.alerts, s.date_of_birth, s.secondary_email, c.name as class_name, s.class_id, s.sex
                FROM students s
                LEFT JOIN users u ON s.email = u.username
                LEFT JOIN classes c ON s.class_id = c.id
                WHERE s.name LIKE %s OR u.username LIKE %s OR s.email LIKE %s OR s.phone LIKE %s
                ORDER BY s.id DESC''', (like_query, like_query, like_query, like_query))
            rows = c.fetchall()
    students = [
        {
            'id': row[0],
            'parent_username': row[1] or '',
            'name': row[2] or '',
            'email': row[3] or '',
            'phone': row[4] or '',
            'notes': row[5] or '',
            'alerts': row[6] or '',
            'date_of_birth': row[7] or '',
            'secondary_email': row[8] or '',
            'class_name': row[9] or 'بدون صف',
            'class_id': row[10],
            'sex': row[11] or ''
        } for row in rows
    ]
    conn.close()
    return jsonify(students)

# ... rest of the code remains the same ...

@app.route('/create_student', methods=['POST'])
@login_required('super_admin', 'local_admin')
def create_student():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    name = data.get('name')
    email = data.get('email') or username
    phone = data.get('phone')
    notes = data.get('notes')
    alerts = data.get('alerts')
    class_id = data.get('class_id')
    date_of_birth = data.get('date_of_birth')
    secondary_email = data.get('secondary_email')
    if not username or not password or not name:
        return jsonify({'success': False, 'error': 'الرجاء تعبئة جميع الحقول'}), 400
    try:
        conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
        c = conn.cursor()
        # Check if user exists
        c.execute('SELECT id FROM users WHERE username=%s', (username,))
        user = c.fetchone()
        if user:
            user_id = user[0]
        else:
            password_hash = generate_password_hash(password)
            c.execute('INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id', (username, password_hash, 'student'))
            user_id = c.fetchone()[0]
        # Insert student with parent's email
        c.execute('INSERT INTO students (name, class_id, email, phone, notes, alerts, date_of_birth, secondary_email) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
                  (name, class_id, email or '', phone or '', notes or '', alerts or '', date_of_birth or '', secondary_email or ''))
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        return jsonify({'success': False, 'error': 'Database is busy, try again.'}), 500
    return jsonify({'success': True})

@app.route('/update_student/<int:student_id>', methods=['PUT'])
@login_required('super_admin', 'local_admin')
def update_student(student_id):
    import sys
    data = request.json
    print("[DEBUG] /update_student PUT called with data:", data, file=sys.stderr)
    new_username = data.get('username')
    new_password = data.get('password')
    email = data.get('email')
    phone = data.get('phone')
    notes = data.get('notes')
    alerts = data.get('alerts')
    name = data.get('name')
    date_of_birth = data.get('date_of_birth')
    secondary_email = data.get('secondary_email')
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Fetch old email for cleanup logic
    c.execute('SELECT email FROM students WHERE id=%s', (student_id,))
    row = c.fetchone()
    old_email = row[0] if row else None
    # If new_username is provided and different, check for conflicts and update
    if new_username and new_username != old_email:
        c.execute('SELECT id FROM users WHERE username=%s', (new_username,))
        user = c.fetchone()
        if not user:
            # Accept password from JSON or form, robustly handle both new_password and password fields
            debug_data = dict(data)
            new_password = data.get('new_password') or data.get('password')
            print("[DEBUG][early] incoming data:", debug_data, file=sys.stderr)
            print("[DEBUG][early] new_password (from JSON):", new_password, file=sys.stderr)
            if not new_password and hasattr(request, 'form'):
                new_password = request.form.get('new_password') or request.form.get('password')
                print("[DEBUG][early] new_password (from form):", new_password, file=sys.stderr)
            if not new_password:
                conn.close()
                print("[DEBUG][early] No password provided for new user, aborting.", file=sys.stderr)
                return jsonify({'success': False, 'error': 'يجب إدخال كلمة مرور للمستخدم الجديد', 'debug_data': str(debug_data), 'debug_new_password': str(new_password)}), 400
            password_hash = generate_password_hash(new_password)
            print(f"[DEBUG][early] Creating user {new_username} with password_hash: {repr(password_hash)}", file=sys.stderr)
            c.execute('INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id', (new_username, password_hash, 'student'))
        # Update student's email to new_username
        email = new_username
    # Update student fields
    updates = []
    params = []
    if email is not None:
        updates.append('email = %s')
        params.append(email)
    if phone is not None:
        updates.append('phone = %s')
        params.append(phone)
    if notes is not None:
        updates.append('notes = %s')
        params.append(notes)
    if alerts is not None:
        updates.append('alerts = %s')
        params.append(alerts)
    if name is not None:
        updates.append('name = %s')
        params.append(name)
    if date_of_birth is not None:
        updates.append('date_of_birth = %s')
        params.append(date_of_birth)
    if secondary_email is not None:
        updates.append('secondary_email = %s')
        params.append(secondary_email)
    if 'sex' in data:
        updates.append('sex = %s')
        params.append(data['sex'])
    if updates:
        params.append(student_id)
        c.execute(f'UPDATE students SET {", ".join(updates)} WHERE id=%s', params)
    # Clean up: if no students left with old_email, remove user
    if old_email and email and old_email != email:
        c.execute('SELECT COUNT(*) FROM students WHERE email=%s', (old_email,))
        count = c.fetchone()[0]
        if count == 0:
            c.execute('DELETE FROM users WHERE username=%s', (old_email,))
        # Now: check if new email exists in users, if not, prompt for password (frontend should handle prompt and send password)
        c.execute('SELECT id FROM users WHERE username=%s', (email,))
        user_exists = c.fetchone()
        if not user_exists:
            # Debug: log the full incoming data
            print("[DEBUG] incoming data:", data, file=sys.stderr)
            # Accept password from JSON or form, robustly handle both new_password and password fields
            new_password = data.get('new_password') or data.get('password')
            print("[DEBUG] new_password (from JSON):", new_password, file=sys.stderr)
            if not new_password and hasattr(request, 'form'):
                new_password = request.form.get('new_password') or request.form.get('password')
                print("[DEBUG] new_password (from form):", new_password, file=sys.stderr)
            if not new_password:
                conn.close()
                print("[DEBUG] No password provided for new user (cleanup), aborting.", file=sys.stderr)
                # Return debug info for troubleshooting
                return jsonify({'success': False, 'error': 'Password required for new user', 'debug_data': str(data), 'debug_new_password': str(new_password)}), 400
            password_hash = generate_password_hash(new_password)
            print(f"[DEBUG] Creating user {email} with password_hash: {repr(password_hash)}", file=sys.stderr)
            # You can choose a default role (e.g., 'student' or 'parent'), adjust as needed
            c.execute('INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id', (email, password_hash, 'student'))
    # If a new password is provided, update the user's password hash
    if data.get('new_password'):
        password_hash = generate_password_hash(data['new_password'])
        # Update the user with the current email/username
        c.execute('UPDATE users SET password_hash=%s WHERE username=%s', (password_hash, email))
        print(f"[DEBUG] Updated password for user {email}", file=sys.stderr)
    conn.commit()
    conn.close()
    print("[DEBUG] /update_student PUT finished", file=sys.stderr)
    return jsonify({'success': True})

@app.route('/update_student/<int:student_id>', methods=['POST'])
@login_required('local_admin')
def update_student_post(student_id):
    data = request.get_json()
    class_id = data.get('class_id')
    email = data.get('email')
    phone = data.get('phone')
    notes = data.get('notes')
    alerts = data.get('alerts')
    try:
        with sqlite3.connect('ArabicSchool.db', timeout=2, check_same_thread=False) as conn:
            c = conn.cursor()
            # Only update fields that are provided
            if class_id is not None:
                c.execute('UPDATE students SET class_id=%s WHERE id=%s', (class_id, student_id))
            if email is not None:
                c.execute('UPDATE students SET email=%s WHERE id=%s', (email, student_id))
            if phone is not None:
                c.execute('UPDATE students SET phone=%s WHERE id=%s', (phone, student_id))
            if notes is not None:
                c.execute('UPDATE students SET notes=%s WHERE id=%s', (notes, student_id))
            if alerts is not None:
                c.execute('UPDATE students SET alerts=%s WHERE id=%s', (alerts, student_id))
            conn.commit()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True})

@app.route('/students/<int:class_id>', methods=['GET'])
@login_required('super_admin', 'local_admin', 'teacher')
def list_students(class_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('''SELECT s.id, u.username, s.name, s.email, s.phone, s.notes, s.alerts
                 FROM students s LEFT JOIN users u ON s.id = u.id
                 WHERE s.class_id=%s''', (class_id,))
    students = [
        {
            'id': row[0],
            'username': row[1],
            'name': row[2] or '',
            'email': row[3] or '',
            'phone': row[4] or '',
            'notes': row[5] or '',
            'alerts': row[6] or ''
        } for row in c.fetchall()
    ]
    conn.close()
    return jsonify(students)


@app.route('/students/<int:class_id>', methods=['POST'])
@login_required('local_admin')
def add_student(class_id):
    data = request.json
    name = data['name']
    sex = data.get('sex')
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT INTO students (name, class_id, sex) VALUES (%s, %s, %s)', (name, class_id, sex))
    conn.commit()
    # Now fetch the updated list
    c.execute('''SELECT u.id, u.username, s.name, s.email, s.phone, s.notes, s.alerts, s.sex
                 FROM users u LEFT JOIN students s ON u.id = s.id
                 WHERE u.role="student" AND s.class_id=%s''', (class_id,))
    students = [
        {
            'id': row[0],
            'username': row[1],
            'name': row[2] or '',
            'email': row[3] or '',
            'phone': row[4] or '',
            'notes': row[5] or '',
            'alerts': row[6] or '',
            'sex': row[7] or ''
        } for row in c.fetchall()
    ]
    conn.close()
    return jsonify(students)


@app.route('/students/<int:class_id>/<int:student_id>', methods=['DELETE'])
@login_required('local_admin')
def delete_student(class_id, student_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('DELETE FROM students WHERE id=%s AND class_id=%s', (student_id, class_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- Get Courses for Student's Class & Grades ---
@app.route('/student_card/<int:student_id>', methods=['GET'])
@login_required()
def get_student_card(student_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Get student's class
    c.execute('SELECT class_id FROM students WHERE id=%s', (student_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Student not found'}), 404
    class_id = row[0]
    # Get courses attached to class
    c.execute('''SELECT ci.id, ci.name FROM class_courses cc JOIN curriculum_items ci ON cc.curriculum_item_id=ci.id WHERE cc.class_id=%s''', (class_id,))
    courses = [{'id': r[0], 'name': r[1]} for r in c.fetchall()]
    # Get grades for student
    c.execute('SELECT curriculum_item_id, level, comment FROM student_grades WHERE student_id=%s', (student_id,))
    rows = c.fetchall()
    scores = {row[0]: row[1] for row in rows}
    comments = {row[0]: row[2] or '' for row in rows}
    conn.close()
    return jsonify({'courses': courses, 'grades': scores, 'comments': comments})

@app.route('/delete_student', methods=['POST'])
@login_required('super_admin', 'local_admin')
def delete_student_api():
    data = request.get_json()
    student_id = data.get('id')
    try:
        with sqlite3.connect('ArabicSchool.db', timeout=2, check_same_thread=False) as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM users WHERE id=%s AND role="student"', (student_id,))
            student = c.fetchone()
            if not student:
                return jsonify({'success': False, 'error': 'الطالب غير موجود'}), 404
            c.execute('DELETE FROM users WHERE id=%s', (student_id,))
            conn.commit()
    except sqlite3.OperationalError as e:
        return jsonify({'success': False, 'error': 'Database is busy, try again.'}), 500
    return jsonify({'success': True})

@app.route('/student_abilities/<int:student_id>/<int:class_id>', methods=['GET', 'POST'])
def student_abilities(student_id, class_id):
    from flask import session, redirect, url_for
    if 'user_id' not in session:
        return redirect(url_for('login'))
    import sqlite3
    from flask import jsonify
    import os
    import json
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Load school info
    info_path = os.path.join(os.path.dirname(__file__), 'school_info.json')
    if os.path.exists(info_path):
        with open(info_path, encoding='utf-8') as f:
            school_info = json.load(f)
    else:
        school_info = {"name": "", "logo": "school_logo.png"}
    # Get class name and level
    c.execute('SELECT name, level_id FROM classes WHERE id=%s', (class_id,))
    row = c.fetchone()
    if not row or not row[0] or not row[1]:
        conn.close()
        error_message = 'لم يتم العثور على الصف أو المستوى المطلوب.'
        return render_template('student_abilities.html', school_info=school_info, error_message=error_message)
    class_name = row[0]
    level_id = row[1]
    # Fetch level name
    c.execute('SELECT name FROM levels WHERE id=%s', (level_id,))
    level_row = c.fetchone()
    class_level = level_row[0] if level_row else ''
    # Get all curriculum groups and items for this level
    c.execute('''SELECT cg.id, cg.name FROM curriculum_groups cg WHERE cg.level_id=%s''', (level_id,))
    groups = []
    for group_id, group_name in c.fetchall():
        c.execute('''SELECT ci.id, ci.name FROM curriculum_items ci WHERE ci.group_id=%s''', (group_id,))
        items = [{'id': cid, 'name': name} for cid, name in c.fetchall()]
        groups.append({'group_name': group_name, 'items': items})
    # Get scores for this student
    c.execute('SELECT curriculum_item_id, level, comment, comment_updated_at, comment_user FROM student_grades WHERE student_id=%s', (student_id,))
    rows = c.fetchall()
    scores = {row[0]: row[1] for row in rows}
    comments = {row[0]: row[2] or '' for row in rows}
    comment_meta = {row[0]: {'updated_at': row[3], 'user': row[4]} for row in rows}
    # POST: Save updates (teacher or local_admin only)
    if request.method == 'POST':
        if session.get('role') not in ('teacher', 'local_admin'):
            conn.close()
            return jsonify({'success': False, 'error': 'Not authorized'}), 403
        data = request.get_json()
        from datetime import datetime
        comment_user = session.get('username', 'unknown')
        comment_updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for group in groups:
            for item in group['items']:
                cid = item['id']
                val = data.get(str(cid))
                comment_in_request = f'comment_{cid}' in data
                comment = data.get(f'comment_{cid}', None)
                c.execute('SELECT id, comment FROM student_grades WHERE student_id=%s AND curriculum_item_id=%s', (student_id, cid))
                row = c.fetchone()
                if (val is None or val == '') and (not comment_in_request or not comment):
                    # Only delete if both score and comment are empty
                    c.execute('DELETE FROM student_grades WHERE student_id=%s AND curriculum_item_id=%s', (student_id, cid))
                else:
                    try:
                        val_int = int(val) if val not in (None, '') else None
                    except:
                        val_int = None
                    if row:
                        if comment_in_request:
                            # Update both level and comment
                            c.execute('UPDATE student_grades SET level=%s, comment=%s, comment_updated_at=%s, comment_user=%s WHERE student_id=%s AND curriculum_item_id=%s', (val_int, comment, comment_updated_at, comment_user, student_id, cid))
                        else:
                            # Only update level, leave comment untouched
                            c.execute('UPDATE student_grades SET level=%s WHERE student_id=%s AND curriculum_item_id=%s', (val_int, student_id, cid))
                    else:
                        # Insert new row. If no comment in request, use empty string
                        c.execute('INSERT INTO student_grades (student_id, curriculum_item_id, level, comment, comment_updated_at, comment_user) VALUES (%s, %s, %s, %s, %s, %s)', (student_id, cid, val_int, comment if comment is not None else '', comment_updated_at, comment_user))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    # GET: Render page
    editable = session.get('role') in ('teacher', 'local_admin')
    # Level badge info (reduced to 3: first, third, fifth)
    level_badges = [
        { 'label': 'بحاجة لمتابعة', 'class': 'level-none', 'icon': '💡' },
        { 'label': 'متوسط', 'class': 'level-intermediate', 'icon': '👍' },
        { 'label': 'متميز', 'class': 'level-master', 'icon': '🏆' },
    ]
    # Fetch student name
    c.execute('SELECT name FROM students WHERE id=%s', (student_id,))
    row = c.fetchone()
    student_name = row[0] if row else ''
    # Fetch all active homeworks for this class (due_date >= today)
    from datetime import datetime
    today_str = datetime.now().strftime('%Y-%m-%d')
    conn2 = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c2 = conn2.cursor()
    c2.execute('SELECT id, due_date, description, files FROM homework WHERE class_id=%s AND due_date >= %s ORDER BY due_date ASC', (class_id, today_str))
    homework_rows = c2.fetchall()
    conn2.close()
    homeworks = []
    for row in homework_rows:
        files = []
        if row[3]:
            try:
                files = row[3].split(';')
            except Exception:
                files = []
        homeworks.append({
            'id': row[0],
            'due_date': row[1],
            'description': row[2],
            'files': files
        })
    return render_template('student_abilities.html', school_info=school_info, groups=groups, scores=scores, comments=comments, comment_meta=comment_meta, editable=editable, level_badges=level_badges, student_name=student_name, student_id=student_id, class_id=class_id, class_name=class_name, class_level=class_level, homeworks=homeworks)

# --- Save single comment endpoint ---
@app.route('/save_comment', methods=['POST'])
def save_comment():
    import sqlite3
    from flask import request, session, jsonify
    if session.get('role') not in ('teacher', 'local_admin'):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    data = request.get_json()
    student_id = data.get('student_id')
    course_id = data.get('course_id')
    comment = data.get('comment', '')
    if not student_id or not course_id:
        return jsonify({'success': False, 'error': 'Missing data'}), 400
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    comment_user = session.get('username', 'unknown')
    comment_updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('SELECT id FROM student_grades WHERE student_id=%s AND curriculum_item_id=%s', (student_id, course_id))
    if c.fetchone():
        c.execute('UPDATE student_grades SET comment=%s, comment_updated_at=%s, comment_user=%s WHERE student_id=%s AND curriculum_item_id=%s', (comment, comment_updated_at, comment_user, student_id, course_id))
    else:
        # Insert with level=NULL
        c.execute('INSERT INTO student_grades (student_id, curriculum_item_id, level, comment, comment_updated_at, comment_user) VALUES (%s, %s, %s, %s, %s, %s)', (student_id, course_id, 0, comment, comment_updated_at, comment_user))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'comment': comment, 'comment_updated_at': comment_updated_at, 'comment_user': comment_user})

app.register_blueprint(super_badges_bp)

# --- HOMEWORK ENDPOINTS ---

@app.route('/api/homework/list/<int:class_id>', methods=['GET'])
def list_homework(class_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT id, due_date, description, files FROM homework WHERE class_id=%s ORDER BY due_date DESC', (class_id,))
    rows = c.fetchall()
    conn.close()
    result = []
    for row in rows:
        files = []
        if row[3]:
            try:
                files = row[3].split(';')
            except Exception:
                files = []
        result.append({
            'id': row[0],
            'due_date': row[1],
            'description': row[2],
            'files': files
        })
    return jsonify({'success': True, 'homeworks': result})

@app.route('/api/homework/edit/<int:homework_id>', methods=['POST'])
def edit_homework(homework_id):
    import os
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT class_id, files FROM homework WHERE id=%s', (homework_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Homework not found'}), 404
    class_id, old_files = row
    due_date = request.form.get('due_date')
    description = request.form.get('description')
    files = request.files.getlist('documents')
    from app.homework_utils import save_homework_files
    new_files = save_homework_files(files, class_id) if files else []
    # Append new files to old files
    all_files = old_files.split(';') if old_files else []
    all_files.extend(new_files)
    all_files_str = ';'.join([f for f in all_files if f])
    c.execute('UPDATE homework SET due_date=%s, description=%s, files=%s WHERE id=%s', (due_date, description, all_files_str, homework_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/homework/delete/<int:homework_id>', methods=['POST'])
def delete_homework(homework_id):
    import os
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT class_id, files FROM homework WHERE id=%s', (homework_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Homework not found'}), 404
    class_id, files = row
    # Delete files from filesystem
    if files:
        upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'class_{class_id}')
        for fname in files.split(';'):
            fpath = os.path.join(upload_folder, fname)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    c.execute('DELETE FROM homework WHERE id=%s', (homework_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/uploads/class_<int:class_id>/<filename>')
@login_required()
def uploaded_file(class_id, filename):
    import os
    upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], f'class_{class_id}')
    return send_from_directory(upload_folder, filename)

@app.route('/api/homework', methods=['POST'])
@login_required()
def upload_homework():
    due_date = request.form.get('due_date')
    description = request.form.get('description')
    class_id = request.form.get('class_id')
    files = request.files.getlist('documents')
    if not (due_date and description and class_id):
        return jsonify({'success': False, 'error': 'جميع الحقول مطلوبة'}), 400
    saved_files = save_homework_files(files, class_id)
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS homework (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER,
        due_date TEXT,
        description TEXT,
        files TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('INSERT INTO homework (class_id, due_date, description, files) VALUES (%s, %s, %s, %s)',
              (class_id, due_date, description, ','.join(saved_files)))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/super_badges', methods=['GET'])
def get_super_badges():
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    # Ensure 'active' column exists
    c.execute('''CREATE TABLE IF NOT EXISTS super_badges (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        icon_type TEXT,
        icon_value TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Try to add column if missing (safe to ignore if exists)
    try:
        c.execute('ALTER TABLE super_badges ADD COLUMN active INTEGER DEFAULT 1')
    except sqlite3.OperationalError:
        pass
    c.execute('SELECT id, name, icon_type, icon_value, active FROM super_badges')
    rows = c.fetchall()
    conn.close()
    badges = [
        {"id": row[0], "name": row[1], "icon_type": row[2], "icon_value": row[3], "active": row[4]} for row in rows
    ]
    return jsonify(badges)

@app.route('/api/super_badges', methods=['POST'])
def add_super_badge():
    import uuid
    data = request.get_json()
    name = data.get('name')
    icon_type = data.get('icon_type')
    icon_value = data.get('icon_value')
    if not name or not icon_type or not icon_value:
        return jsonify({'error': 'Missing required fields'}), 400
    badge_id = str(uuid.uuid4())
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS super_badges (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        icon_type TEXT,
        icon_value TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    try:
        c.execute('ALTER TABLE super_badges ADD COLUMN active INTEGER DEFAULT 1')
    except sqlite3.OperationalError:
        pass
    c.execute('INSERT INTO super_badges (id, name, icon_type, icon_value, active) VALUES (%s, %s, %s, %s, %s)',
              (badge_id, name, icon_type, icon_value, 1))
    conn.commit()
    conn.close()
    return jsonify({'id': badge_id, 'name': name, 'icon_type': icon_type, 'icon_value': icon_value, 'active': 1})

@app.route('/api/super_badges/<badge_id>', methods=['GET'])
def get_super_badge(badge_id):
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('SELECT id, name, icon_type, icon_value, active FROM super_badges WHERE id = %s', (badge_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({'id': row[0], 'name': row[1], 'icon_type': row[2], 'icon_value': row[3], 'active': row[4]})
    else:
        return jsonify({'error': 'Not found'}), 404

@app.route('/api/super_badges/<badge_id>', methods=['PUT'])
def update_super_badge(badge_id):
    data = request.get_json()
    name = data.get('name')
    icon_type = data.get('icon_type')
    icon_value = data.get('icon_value')
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('SELECT id FROM super_badges WHERE id = %s', (badge_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    c.execute('UPDATE super_badges SET name = %s, icon_type = %s, icon_value = %s WHERE id = %s',
              (name, icon_type, icon_value, badge_id))
    conn.commit()
    conn.close()
    return jsonify({'id': badge_id, 'name': name, 'icon_type': icon_type, 'icon_value': icon_value})

@app.route('/api/super_badges/<badge_id>/active', methods=['PATCH'])
def toggle_super_badge_active(badge_id):
    data = request.get_json(force=True, silent=True) or {}
    set_active = data.get('active')
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('SELECT active FROM super_badges WHERE id = %s', (badge_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    current_active = row[0]
    if set_active is None:
        new_active = 0 if current_active else 1
    else:
        new_active = 1 if set_active else 0
    c.execute('UPDATE super_badges SET active = %s WHERE id = %s', (new_active, badge_id))
    conn.commit()
    conn.close()
    return jsonify({'id': badge_id, 'active': new_active})

@app.route('/api/super_badges/<badge_id>', methods=['DELETE'])
def delete_super_badge(badge_id):
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('SELECT id FROM super_badges WHERE id = %s', (badge_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    c.execute('DELETE FROM super_badges WHERE id = %s', (badge_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/exams/<int:class_id>', methods=['GET'])
@login_required('local_admin')
def list_exams(class_id):
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('''SELECT exams.id, exams.name, exams.status, exams.curriculum_group_id, cg.name as subject_name, exams.is_final, exams.weight, exams.dawra, exams.is_year_final
                 FROM exams LEFT JOIN curriculum_groups cg ON exams.curriculum_group_id = cg.id
                 WHERE exams.class_id = %s ORDER BY exams.id''', (class_id,))
    exams = []
    for row in c.fetchall():
        exams.append({
            'id': row[0],
            'name': row[1],
            'status': row[2],
            'curriculum_group_id': row[3],
            'subject_name': row[4] or '',
            'is_final': row[5] if row[5] is not None else 0,
            'weight': row[6] if row[6] is not None else 1.0,
            'dawra': row[7] if len(row) > 7 and row[7] is not None else 1,
            'is_year_final': row[8] if len(row) > 8 and row[8] is not None else 0
        })
    conn.close()
    return jsonify({'exams': exams})

@app.route('/api/exams/<int:class_id>', methods=['POST'])
@login_required('local_admin', 'teacher')
def add_exam(class_id):
    data = request.get_json()
    name = data.get('name')
    curriculum_group_id = data.get('curriculum_group_id')
    status = data.get('status', 'active')
    is_final = data.get('is_final', 0)
    weight = data.get('weight', 1.0)
    dawra = data.get('dawra', 1)
    is_year_final = int(data.get('is_year_final', 0))
    # If year final, dawra is always NULL
    dawra_to_save = None if is_year_final else dawra
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not curriculum_group_id:
        return jsonify({'error': 'Subject is required'}), 400
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('INSERT INTO exams (class_id, name, status, curriculum_group_id, is_final, weight, dawra, is_year_final) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
              (class_id, name, status, curriculum_group_id, is_final, weight, dawra_to_save, is_year_final))
    conn.commit()
    exam_id = c.fetchone()[0]
    conn.close()
    return jsonify({'id': exam_id, 'name': name, 'status': status, 'curriculum_group_id': curriculum_group_id, 'is_final': is_final, 'weight': weight, 'dawra': dawra_to_save, 'is_year_final': is_year_final})

@app.route('/api/exams/<int:exam_id>', methods=['PUT'])
@login_required('local_admin', 'teacher')
def edit_exam(exam_id):
    data = request.get_json()
    name = data.get('name')
    curriculum_group_id = data.get('curriculum_group_id')
    status = data.get('status')
    is_final = data.get('is_final')
    weight = data.get('weight')
    dawra = data.get('dawra')
    is_year_final = data.get('is_year_final')
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    if name is not None:
        c.execute('UPDATE exams SET name = %s WHERE id = %s', (name, exam_id))
    if curriculum_group_id is not None:
        c.execute('UPDATE exams SET curriculum_group_id = %s WHERE id = %s', (curriculum_group_id, exam_id))
    if status is not None:
        c.execute('UPDATE exams SET status = %s WHERE id = %s', (status, exam_id))
    if is_final is not None:
        c.execute('UPDATE exams SET is_final = %s WHERE id = %s', (is_final, exam_id))
    if weight is not None:
        c.execute('UPDATE exams SET weight = %s WHERE id = %s', (weight, exam_id))
    if is_year_final is not None:
        # If year final, dawra must be NULL
        c.execute('UPDATE exams SET is_year_final = %s WHERE id = %s', (int(is_year_final), exam_id))
        if int(is_year_final):
            c.execute('UPDATE exams SET dawra = NULL WHERE id = %s', (exam_id,))
        elif dawra is not None:
            c.execute('UPDATE exams SET dawra = %s WHERE id = %s', (dawra, exam_id))
    elif dawra is not None:
        c.execute('UPDATE exams SET dawra = %s WHERE id = %s', (dawra, exam_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/exams/<int:exam_id>', methods=['DELETE'])
@login_required('local_admin','teacher')
def delete_exam(exam_id):
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('DELETE FROM exams WHERE id = %s', (exam_id,))
    c.execute('DELETE FROM grades WHERE exam_id = %s', (exam_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/grades/<int:class_id>', methods=['GET'])
@login_required('local_admin', 'teacher')
def list_grades(class_id):
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    # Get students
    c.execute('SELECT id, name FROM students WHERE class_id = %s ORDER BY id', (class_id,))
    students = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
    # Get exams (with subject)
    c.execute('''SELECT exams.id, exams.name, exams.curriculum_group_id, cg.name as subject_name, exams.is_final, exams.weight, exams.dawra, exams.is_year_final
                 FROM exams LEFT JOIN curriculum_groups cg ON exams.curriculum_group_id = cg.id
                 WHERE exams.class_id = %s ORDER BY exams.id''', (class_id,))
    exams = [
        {
            'id': row[0],
            'name': row[1],
            'curriculum_group_id': row[2],
            'subject_name': row[3] or '',
            'is_final': row[4] if row[4] is not None else 0,
            'weight': row[5] if row[5] is not None else 1.0,
            'dawra': row[6] if len(row) > 6 and row[6] is not None else 1,
            'is_year_final': row[7] if len(row) > 7 and row[7] is not None else 0
        }
        for row in c.fetchall()
    ]
    # Get grades
    c.execute('SELECT student_id, exam_id, grade FROM grades WHERE exam_id IN (SELECT id FROM exams WHERE class_id = %s)', (class_id,))
    grade_map = {}
    for student_id, exam_id, grade in c.fetchall():
        grade_map[(student_id, exam_id)] = grade
    # Build response
    for student in students:
        student['grades'] = {}
        for exam in exams:
            student['grades'][str(exam['id'])] = grade_map.get((student['id'], exam['id']), '')
    conn.close()
    return jsonify({'students': students, 'exams': exams})

@app.route('/api/grades/<int:class_id>', methods=['POST'])
@login_required('local_admin', 'teacher')
def update_grades(class_id):
    data = request.get_json()
    grades = data.get('grades', [])  # List of dicts: {student_id, exam_id, grade}
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    for entry in grades:
        student_id = entry.get('student_id')
        exam_id = entry.get('exam_id')
        grade = entry.get('grade')
        if not (student_id and exam_id):
            continue
        # Upsert using SQLite ON CONFLICT
        c.execute('''
            INSERT INTO grades (student_id, exam_id, grade)
            VALUES (%s, %s, %s)
            ON CONFLICT(student_id, exam_id) DO UPDATE SET grade=excluded.grade, updated_at=CURRENT_TIMESTAMP
        ''', (student_id, exam_id, grade))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/continuous_monitoring/<int:class_id>')
@login_required('local_admin', 'teacher')
def continuous_monitoring(class_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT name FROM classes WHERE id=%s', (class_id,))
    row = c.fetchone()
    conn.close()
    class_name = row[0] if row else ''
    return render_template('continuous_monitoring.html', class_id=class_id, class_name=class_name)

@app.route('/attendance/<int:class_id>')
@login_required('local_admin', 'teacher')
def attendance(class_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT name FROM classes WHERE id=%s', (class_id,))
    row = c.fetchone()
    class_name = row[0] if row else ''
    conn.close()
    return render_template('attendance.html', class_id=class_id, class_name=class_name)

@app.route('/api/attendance/<int:class_id>', methods=['GET'])
@login_required('local_admin', 'teacher')
def get_attendance(class_id):
    import datetime
    week_start_str = request.args.get('week_start')
    if week_start_str:
        week_start = datetime.datetime.strptime(week_start_str, '%Y-%m-%d').date()
    else:
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday() + 1 if today.weekday() < 6 else 0)
    week_dates = [(week_start + datetime.timedelta(days=i)).isoformat() for i in range(7)]
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Ensure attendance table exists
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        present INTEGER NOT NULL,
        UNIQUE(student_id, class_id, day)
    )''')
    # Get students
    c.execute('SELECT id, name FROM students WHERE class_id=%s ORDER BY id', (class_id,))
    students = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
    # Attendance records for this week
    q_marks = ','.join(['?']*len(week_dates))
    c.execute(f'SELECT student_id, day, present FROM attendance WHERE class_id=%s AND day IN ({q_marks})', (class_id, *week_dates))
    attendance = {(str(row[0]) + '_' + row[1]): row[2] for row in c.fetchall()}
    conn.close()
    return jsonify({'students': students, 'attendance': attendance})

@app.route('/api/attendance/<int:class_id>', methods=['POST'])
@login_required('local_admin', 'teacher')
def update_attendance(class_id):
    data = request.get_json()
    student_id = data.get('student_id')
    day = data.get('day')
    present = 1 if data.get('present') else 0
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        present INTEGER NOT NULL,
        UNIQUE(student_id, class_id, day)
    )''')
    c.execute('''INSERT INTO attendance (student_id, class_id, day, present)
                 VALUES (%s, %s, %s, %s)
                 ON CONFLICT(student_id, class_id, day) DO UPDATE SET present=excluded.present''',
              (student_id, class_id, day, present))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# Ensure support_material table exists
def ensure_support_material_table():
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS support_material (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level_id INTEGER,
        filename TEXT,
        original_filename TEXT,
        description TEXT,
        uploader TEXT,
        date TEXT
    )''')
    conn.commit()
    conn.close()

ensure_support_material_table()

@app.route('/levels/<int:level_id>/support_material', methods=['POST'])
def upload_support_material(level_id):
    print(f"[DEBUG] Upload called for level_id={level_id}")
    if 'file' not in request.files:
        print("[ERROR] No file part in request.files")
        return jsonify({'success': False, 'error': 'لم يتم اختيار ملف (file missing in request)'}), 400
    file = request.files['file']
    description = request.form.get('description', '').strip()
    if not file:
        print("[ERROR] file object is None")
        return jsonify({'success': False, 'error': 'file object is None'}), 400
    if file.filename == '':
        print("[ERROR] filename is empty")
        return jsonify({'success': False, 'error': 'اسم الملف فارغ'}), 400
    if not description:
        print("[ERROR] description is empty")
        return jsonify({'success': False, 'error': 'الوصف مطلوب'}), 400
    # Save file
    original_filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"level{level_id}_{timestamp}_{original_filename}"
    file_path = os.path.join(SUPPORT_MATERIAL_FOLDER, filename)
    try:
        file.save(file_path)
        print(f"[DEBUG] File saved to {file_path}")
    except Exception as e:
        print(f"[ERROR] Exception saving file: {e}")
        return jsonify({'success': False, 'error': f'خطأ في حفظ الملف: {str(e)}'}), 500
    uploader = session.get('username', 'Admin')
    date = datetime.now().strftime('%Y-%m-%d %H:%M')
    # Save metadata
    try:
        conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
        c = conn.cursor()
        c.execute('''INSERT INTO support_material (level_id, filename, original_filename, description, uploader, date) VALUES (%s, %s, %s, %s, %s, %s)''',
                  (level_id, filename, original_filename, description, uploader, date))
        conn.commit()
        conn.close()
        print(f"[DEBUG] Metadata inserted for {filename}")
    except Exception as e:
        print(f"[ERROR] Exception inserting metadata: {e}")
        return jsonify({'success': False, 'error': f'خطأ في حفظ بيانات الملف: {str(e)}'}), 500
    return jsonify({'success': True})

@app.route('/levels/<int:level_id>/support_material', methods=['GET'])
def list_support_material(level_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('''SELECT id, filename, original_filename, description, uploader, date FROM support_material WHERE level_id=%s ORDER BY id DESC''', (level_id,))
    files = [
        {
            'id': row[0],
            'filename': row[2],
            'url': url_for('serve_support_material', filename=row[1]),
            'description': row[3],
            'uploader': row[4],
            'date': row[5]
        } for row in c.fetchall()
    ]
    conn.close()
    return jsonify(files)

@app.route('/support_material/<filename>')
@login_required()
def serve_support_material(filename):
    return send_from_directory(SUPPORT_MATERIAL_FOLDER, filename, as_attachment=False)

@app.route('/support_material/<int:support_id>', methods=['DELETE'])
def delete_support_material(support_id):
    try:
        conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT filename FROM support_material WHERE id=%s', (support_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'success': False, 'error': 'لم يتم العثور على الملف'}), 404
        filename = row[0]
        file_path = os.path.join(SUPPORT_MATERIAL_FOLDER, filename)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"[ERROR] Failed to delete file: {e}")
        c.execute('DELETE FROM support_material WHERE id=%s', (support_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        print(f"[ERROR] Exception in delete_support_material: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/support_material/<int:support_id>', methods=['PUT'])
def edit_support_material(support_id):
    try:
        conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
        c = conn.cursor()
        # Accept both JSON and multipart/form-data
        if request.content_type and request.content_type.startswith('multipart/form-data'):
            new_desc = request.form.get('description', '').strip()
            file = request.files.get('file')
        else:
            data = request.get_json()
            new_desc = data.get('description', '').strip() if data else ''
            file = None
        if not new_desc:
            conn.close()
            return jsonify({'success': False, 'error': 'الوصف مطلوب'}), 400
        # Get current file info
        c.execute('SELECT filename, level_id FROM support_material WHERE id=%s', (support_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'success': False, 'error': 'لم يتم العثور على الملف'}), 404
        old_filename, level_id = row
        update_file = False
        if file and file.filename:
            # Remove old file
            old_path = os.path.join(SUPPORT_MATERIAL_FOLDER, old_filename)
            try:
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception as e:
                print(f"[ERROR] Failed to remove old file: {e}")
            # Save new file
            original_filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            new_filename = f"level{level_id}_{timestamp}_{original_filename}"
            file_path = os.path.join(SUPPORT_MATERIAL_FOLDER, new_filename)
            try:
                file.save(file_path)
            except Exception as e:
                print(f"[ERROR] Exception saving new file: {e}")
                conn.close()
                return jsonify({'success': False, 'error': f'خطأ في حفظ الملف الجديد: {str(e)}'}), 500
            update_file = True
        # Update DB
        if update_file:
            c.execute('UPDATE support_material SET description=%s, filename=%s, original_filename=%s WHERE id=%s', (new_desc, new_filename, original_filename, support_id))
        else:
            c.execute('UPDATE support_material SET description=%s WHERE id=%s', (new_desc, support_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        print(f"[ERROR] Exception in edit_support_material: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    print("[GLOBAL ERROR]", e)
    traceback.print_exc()
    return jsonify({'success': False, 'error': str(e)}), 500

import json
import os
from flask import request, redirect, url_for, flash

# --- General Announcements API ---
from flask import abort
ANNOUNCEMENTS_FILE = os.path.join(os.path.dirname(__file__), 'announcements.json')

def load_announcement():
    if not os.path.exists(ANNOUNCEMENTS_FILE):
        return None
    with open(ANNOUNCEMENTS_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            if isinstance(data, list):
                return data[-1] if data else None
            return data if data else None
        except Exception:
            return None

def save_announcement(announcement):
    with open(ANNOUNCEMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(announcement if announcement else {}, f, ensure_ascii=False, indent=2)

@app.route('/api/announcements', methods=['GET'])
def api_get_announcement():
    ann = load_announcement()
    return jsonify({'announcement': ann} if ann else {'announcement': None})

@app.route('/api/announcements', methods=['POST'])
def api_post_announcement():
    if 'role' not in session or session['role'] not in ['super_admin', 'local_admin']:
        abort(403)
    data = request.get_json(force=True)
    text = data.get('text', '').strip()
    expiry = data.get('expiry')
    if not text or not expiry:
        return jsonify({'success': False, 'error': 'Missing text or expiry'}), 400
    announcement = {
        'text': text,
        'expiry': expiry,
        'created_at': datetime.now().isoformat(),
        'author': session.get('username', 'unknown')
    }
    save_announcement(announcement)
    return jsonify({'success': True})

@app.route('/school_info', methods=['GET', 'POST'])
def school_info():
    info_path = os.path.join(os.path.dirname(__file__), 'school_info.json')
    static_path = os.path.join(os.path.dirname(__file__), 'static')
    # Load current info
    if os.path.exists(info_path):
        with open(info_path, encoding='utf-8') as f:
            school_info = json.load(f)
    else:
        school_info = {"name": "", "address": "", "contact": "", "email": "", "logo": "school_logo.png"}

    if request.method == 'POST':
        school_info['name'] = request.form.get('name', '')
        school_info['address'] = request.form.get('address', '')
        school_info['contact'] = request.form.get('contact', '')
        school_info['email'] = request.form.get('email', '')

        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            logo_filename = 'school_logo' + os.path.splitext(logo_file.filename)[-1]
            logo_path = os.path.join(static_path, logo_filename)
            os.makedirs(static_path, exist_ok=True)
            logo_file.save(logo_path)
            school_info['logo'] = logo_filename
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(school_info, f, ensure_ascii=False, indent=2)
        flash('تم تحديث معلومات المدرسة بنجاح', 'success')
        return redirect(url_for('school_info'))

    return render_template('school_info.html', school_info=school_info)

import json

@app.route('/score_card/<int:student_id>')
def score_card(student_id):
    from flask import session, redirect, url_for
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # Load school info
    info_path = os.path.join(os.path.dirname(__file__), 'school_info.json')
    if os.path.exists(info_path):
        with open(info_path, encoding='utf-8') as f:
            school_info = json.load(f)
    else:
        school_info = {"name": "", "logo": "school_logo.png"}

    # Fetch student info and scores
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Get student basic info
    c.execute('SELECT name, class_id FROM students WHERE id=%s', (student_id,))
    stu_row = c.fetchone()
    if not stu_row:
        conn.close()
        return render_template('score_card.html', error_message='لم يتم العثور على الطالب.', school_info=school_info)
    student_name, class_id = stu_row
    # Get class name and level
    c.execute('SELECT name, level_id FROM classes WHERE id=%s', (class_id,))
    class_row = c.fetchone()
    class_name, level_id = class_row if class_row else (None, None)
    class_level = None
    if level_id:
        c.execute('SELECT name FROM levels WHERE id=%s', (level_id,))
        lvl_row = c.fetchone()
        class_level = lvl_row[0] if lvl_row else None
    # Build score summary using 'grades' table
    query = '''
        SELECT s.name as student_name, ci.name as subject,
            MAX(CASE WHEN e.dawra=1 THEN g.grade END) as term1,
            MAX(CASE WHEN e.dawra=2 THEN g.grade END) as term2,
            MAX(CASE WHEN e.dawra=3 THEN g.grade END) as term3,
            MAX(CASE WHEN e.is_year_final=1 THEN g.grade END) as year_final,
            MAX(CASE WHEN e.is_final=1 THEN g.grade END) as year_avg
        FROM grades g
        JOIN students s ON g.student_id = s.id
        JOIN exams e ON g.exam_id = e.id
        JOIN curriculum_items ci ON e.curriculum_group_id = ci.id
        WHERE g.student_id=%s
        GROUP BY s.name, ci.name
        ORDER BY ci.name
    '''
    c.execute(query, (student_id,))
    score_summary = []
    for row in c.fetchall():
        score_summary.append({
            'student_name': row[0],
            'subject': row[1],
            'term1': row[2],
            'term2': row[3],
            'term3': row[4],
            'year_final': row[5],
            'year_avg': row[6],
        })
    # --- Absenteeism Info ---
    c = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False).cursor()
    c.execute('''SELECT day FROM attendance WHERE student_id=%s AND class_id=%s AND present=0 ORDER BY day''', (student_id, class_id))
    absent_days = [row[0] for row in c.fetchall()]
    total_absences = len(absent_days)
    c.connection.close()
    return render_template('score_card.html',
        school_info=school_info,
        student_name=student_name,
        class_name=class_name,
        class_level=class_level,
        score_summary=score_summary,
        total_absences=total_absences,
        absent_days=absent_days
    )

def calculate_student_subject_summary(student, exams, grades):
    """
    Returns a list of dicts, each with:
        'student_name', 'subject', 'term1', 'term2', 'term3', 'year_final', 'year_avg'
    using the same weighted average logic as continuous monitoring.
    """
    import json
    print(f"[DEBUG][summary] Called with student: {json.dumps(student, ensure_ascii=False)}")
    print(f"[DEBUG][summary] Exams: {json.dumps(exams, ensure_ascii=False)}")
    print(f"[DEBUG][summary] Grades: {json.dumps(grades, ensure_ascii=False)}")
    # Group exams by subject
    from collections import defaultdict
    subject_exams = defaultdict(list)
    for exam in exams:
        subject_exams[exam['subject_name']].append(exam)
    summary = []
    for subject, subject_exs in subject_exams.items():
        print(f"[DEBUG][summary] Subject: {subject}, Exams: {json.dumps(subject_exs, ensure_ascii=False)}")
        # Dawra averages (1,2,3)
        dawra_avgs = []
        for dawra in [1,2,3]:
            items = []
            for exam in subject_exs:
                if (exam.get('dawra', 1) == dawra and not exam.get('is_year_final', 0)):
                    val = grades.get(str(exam['id']))
                    weight = float(exam.get('weight', 1.0) or 1.0)
                    if val is not None and val != '' and str(val).replace('.','',1).isdigit():
                        items.append({'grade': float(val), 'weight': weight})
            weighted_sum = sum(item['grade'] * item['weight'] for item in items)
            total_weight = sum(item['weight'] for item in items)
            avg = round(weighted_sum / total_weight, 2) if total_weight > 0 else None
            dawra_avgs.append(avg)
        # Year final average (if multiple year finals for subject, average them)
        year_final_vals = [
            float(grades.get(str(exam['id'])))
            for exam in subject_exs
            if exam.get('is_year_final', 0) and grades.get(str(exam['id'])) not in (None, '', '-') and str(grades.get(str(exam['id']))).replace('.','',1).isdigit()
        ]
        year_final = round(sum(year_final_vals)/len(year_final_vals), 2) if year_final_vals else None
        # Year average: mean of all available dawra averages + year final
        all_for_year_avg = [v for v in dawra_avgs if v is not None]
        if year_final is not None:
            all_for_year_avg.append(year_final)
        year_avg = round(sum(all_for_year_avg)/len(all_for_year_avg), 2) if all_for_year_avg else None
        summary.append({
            'student_name': student['name'],
            'subject': subject,
            'term1': dawra_avgs[0],
            'term2': dawra_avgs[1],
            'term3': dawra_avgs[2],
            'year_final': year_final,
            'year_avg': year_avg
        })
    print(f"[DEBUG][summary] Output summary: {json.dumps(summary, ensure_ascii=False)}")
    return summary

@app.route('/api/score_card/<int:student_id>')
@login_required()
def api_score_card(student_id):
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    # Get student info
    c.execute('SELECT id, name, class_id FROM students WHERE id=%s', (student_id,))
    stu = c.fetchone()
    if not stu:
        conn.close()
        return jsonify({'error': 'Student not found'}), 404
    stu_id, stu_name, class_id = stu
    # Get class info (teachers, level)
    c.execute('''SELECT classes.name, l.name as level_name, t.name as teacher_name, tb.name as backup_teacher_name
                 FROM classes
                 LEFT JOIN levels l ON classes.level_id = l.id
                 LEFT JOIN teachers t ON classes.teacher_id = t.id
                 LEFT JOIN teachers tb ON classes.backup_teacher_id = tb.id
                 WHERE classes.id = %s''', (class_id,))
    class_row = c.fetchone()
    class_info = {
        'class_name': class_row[0] if class_row else '',
        'level_name': class_row[1] if class_row else '',
        'teacher_name': class_row[2] if class_row else '',
        'backup_teacher_name': class_row[3] if class_row else ''
    }
    # Get school principal (prefer is_director, fallback to any super_admin with name)
    c.execute("SELECT name, username FROM users WHERE role='local_admin' AND name IS NOT NULL ORDER BY (CASE WHEN is_director=1 OR is_director='1' THEN 0 ELSE 1 END), id ASC LIMIT 1")
    principal_row = c.fetchone()
    principal_name = ''
    if principal_row:
        principal_name = principal_row[0] if principal_row[0] else principal_row[1]
    # Calculate school year (e.g., 2024-2025)
    from datetime import datetime
    today = datetime.now().date()
    if today.month >= 9:
        school_year = f"{today.year}-{today.year+1}"
    else:
        school_year = f"{today.year-1}-{today.year}"
    # Get exams (with subject) for this class - same as /api/grades/<class_id>
    c.execute('''SELECT exams.id, exams.name, exams.curriculum_group_id, cg.name as subject_name, exams.is_final, exams.weight, exams.dawra, exams.is_year_final
                 FROM exams LEFT JOIN curriculum_groups cg ON exams.curriculum_group_id = cg.id
                 WHERE exams.class_id = %s ORDER BY exams.id''', (class_id,))
    exams = [
        {
            'id': row[0],
            'name': row[1],
            'curriculum_group_id': row[2],
            'subject_name': row[3] or '',
            'is_final': row[4] if row[4] is not None else 0,
            'weight': row[5] if row[5] is not None else 1.0,
            'dawra': row[6] if len(row) > 6 and row[6] is not None else 1,
            'is_year_final': row[7] if len(row) > 7 and row[7] is not None else 0
        }
        for row in c.fetchall()
    ]
    # Get grades for this student for these exams, using the same mapping as /api/grades/<class_id>
    c.execute('SELECT student_id, exam_id, grade FROM grades WHERE exam_id IN (SELECT id FROM exams WHERE class_id = %s)', (class_id,))
    grade_map = {}
    for student_id_row, exam_id_row, grade in c.fetchall():
        grade_map[(student_id_row, exam_id_row)] = grade
    grades = {}
    for exam in exams:
        grades[str(exam['id'])] = grade_map.get((stu_id, exam['id']), '')
    # Now grades is a dict of {str(exam_id): grade} as expected by the summary function

    # Fetch publication dates for this class
    c = sqlite3.connect('ArabicSchool.db').cursor()
    c.execute('''SELECT dawra1_pub_start, dawra2_pub_start, dawra3_pub_start, year_pub_start FROM classes WHERE id=%s''', (class_id,))
    pub_row = c.fetchone()
    pub_dates = {
        'dawra1_pub_start': pub_row[0],
        'dawra2_pub_start': pub_row[1],
        'dawra3_pub_start': pub_row[2],
        'year_pub_start': pub_row[3]
    } if pub_row else {}
    # Current date (from user context)
    from datetime import datetime
    today = datetime.now().date()
    # Helper: check if pub date is set and <= today
    def is_published(pub_date):
        if not pub_date: return False
        try:
            return datetime.strptime(pub_date, '%Y-%m-%d').date() <= today
        except Exception:
            return False
    published = {
        1: is_published(pub_dates.get('dawra1_pub_start')),
        2: is_published(pub_dates.get('dawra2_pub_start')),
        3: is_published(pub_dates.get('dawra3_pub_start')),
        'year': is_published(pub_dates.get('year_pub_start'))
    }
    # Build summary using shared calculation logic
    student_obj = {'id': stu_id, 'name': stu_name, 'class_id': class_id}
    summary = calculate_student_subject_summary(student_obj, exams, grades)
    # Mask unpublished dawras/years
    for row in summary:
        for i, dawra in enumerate([1,2,3]):
            if not published[dawra]:
                row[f'term{dawra}'] = None
        if not published['year']:
            row['year_final'] = None
            row['year_avg'] = None
    conn.close()
    debug_data = {
        'student': student_obj,
        'exams': exams,
        'grades': grades,
        'summary': summary,
        'publication_dates': pub_dates,
        'class_info': class_info,
        'principal_name': principal_name,
        'school_year': school_year
    }
    print(f"[DEBUG][api_score_card] student_id={student_id} response: {json.dumps(debug_data, ensure_ascii=False)}")
    return jsonify(debug_data)

# --- Backup System ---
def _create_backup_zip():
    """Create a temporary ZIP file containing the DB and uploaded files."""
    db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'ArabicSchool.db')
    if not os.path.exists(db_path):
        db_path = 'ArabicSchool.db'

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    tmp.close()

    with zipfile.ZipFile(tmp.name, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add database file
        if os.path.exists(db_path):
            zf.write(db_path, 'ArabicSchool.db')
        # Add support_material folder
        if os.path.isdir(SUPPORT_MATERIAL_FOLDER):
            for root, dirs, files in os.walk(SUPPORT_MATERIAL_FOLDER):
                for f in files:
                    full = os.path.join(root, f)
                    arcname = os.path.join('support_material', os.path.relpath(full, SUPPORT_MATERIAL_FOLDER))
                    zf.write(full, arcname)
        # Add uploads folder
        upload_dir = app.config.get('UPLOAD_FOLDER', 'uploads')
        if os.path.isdir(upload_dir):
            for root, dirs, files in os.walk(upload_dir):
                for f in files:
                    full = os.path.join(root, f)
                    arcname = os.path.join('uploads', os.path.relpath(full, upload_dir))
                    zf.write(full, arcname)

    return tmp.name

def _log_backup(username):
    """Log a backup entry in backup_log table."""
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('INSERT INTO backup_log (backup_date, backup_by) VALUES (%s, %s)',
              (datetime.now().isoformat(), username))
    conn.commit()
    conn.close()

@app.route('/api/backup/download')
@login_required()
def backup_download():
    if session.get('role') not in ('super_admin', 'local_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    zip_path = _create_backup_zip()
    _log_backup(session.get('username', ''))
    filename = f"backup_{datetime.now().strftime('%Y-%m-%d')}.zip"
    return send_file(zip_path, as_attachment=True, download_name=filename, mimetype='application/zip')

@app.route('/api/backup/email', methods=['POST'])
@login_required()
def backup_email():
    if session.get('role') not in ('super_admin', 'local_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    zip_path = _create_backup_zip()
    filename = f"backup_{datetime.now().strftime('%Y-%m-%d')}.zip"
    recipient = session.get('username', '')
    try:
        msg = Message(
            subject="ArabicSchool Backup - " + datetime.now().strftime('%Y-%m-%d'),
            recipients=[recipient],
            body="مرفق نسخة احتياطية من قاعدة البيانات والملفات المرفوعة."
        )
        with open(zip_path, 'rb') as f:
            msg.attach(filename, 'application/zip', f.read())
        mail.send(msg)
        _log_backup(recipient)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if os.path.exists(zip_path):
            os.unlink(zip_path)

@app.route('/api/backup/last')
@login_required()
def backup_last():
    if session.get('role') not in ('super_admin', 'local_admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    conn = sqlite3.connect('ArabicSchool.db', timeout=10, check_same_thread=False)
    c = conn.cursor()
    c.execute('SELECT backup_date FROM backup_log ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    if row:
        last_dt = datetime.fromisoformat(row[0])
        days_ago = (datetime.now() - last_dt).days
        return jsonify({'last_backup': row[0], 'days_ago': days_ago})
    return jsonify({'last_backup': None, 'days_ago': 999})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
