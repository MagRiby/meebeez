from flask import Blueprint, render_template, request, jsonify
from auth_utils import login_required
from models import db, SuperBadge
import uuid
import sqlite3
from flask import current_app
print(">>> routes_super_badges.py loaded")

super_badges_bp = Blueprint('super_badges', __name__)

@super_badges_bp.route('/super_badges', methods=['GET'])
def super_badges_page():
    return render_template('super_badges.html')

# @super_badges_bp.route('/api/super_badges', methods=['GET'])
# def get_super_badges():
#     import traceback
#     print(">>> /api/super_badges endpoint was hit")
#     try:
#         badges = SuperBadge.query.order_by(SuperBadge.created_at.desc()).all()
#         print(">>> Query succeeded, returning badges")
#         return jsonify([
#             {
#                 'id': b.id,
#                 'name': b.name,
#                 'icon_type': b.icon_type or 'key',
#                 'icon_value': b.icon_value or ''
#             } for b in badges
#         ])
#     except Exception as e:
#         print('[get_super_badges] Exception:', str(e))
#         print(traceback.format_exc())
#         return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


# --- NEW ENDPOINT: Get all super badges for a student, with active status ---
@super_badges_bp.route('/api/student/<int:student_id>/super_badges', methods=['GET'])
@login_required()
def get_student_super_badges(student_id):
    print(f"[DEBUG] /api/student/{student_id}/super_badges endpoint HIT for student_id={student_id}")
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    # Only get badges where active=1
    c.execute('SELECT id, name, icon_type, icon_value FROM super_badges WHERE  active=1 ORDER BY created_at DESC')
    all_badges = c.fetchall()
    # Get active badge info for this student (including created_at)
    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        super_badge_id TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at DATETIME,
        UNIQUE(student_id, super_badge_id)
    )''')
    c.execute('SELECT super_badge_id, created_at FROM student_super_badges WHERE student_id=? AND active=1', (student_id,))
    active_badge_info = {row[0]: row[1] for row in c.fetchall()}
    # Compose response
    badges = []
    for b in all_badges:
        badge_id = str(b[0])
        awarded_at = active_badge_info.get(badge_id)
        badges.append({
            'id': badge_id,
            'name': b[1],
            'icon_type': b[2],
            'icon_value': b[3],
            'active': badge_id in active_badge_info,
            'awarded_at': awarded_at if awarded_at else None
        })
    conn.close()
    return jsonify(badges)




# --- NEW ENDPOINT: Toggle a super badge for a student ---
@super_badges_bp.route('/api/student/<int:student_id>/super_badges/<badge_id>/toggle', methods=['POST'])
@login_required()
def toggle_student_super_badge(student_id, badge_id):
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    # Ensure table exists
    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        super_badge_id TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        UNIQUE(student_id, super_badge_id)
    )''')
    # Check current state
    c.execute('SELECT id, active FROM student_super_badges WHERE student_id=? AND super_badge_id=?', (student_id, badge_id))
    row = c.fetchone()
    if row:
        new_active = 0 if row[1] else 1
        c.execute('UPDATE student_super_badges SET active=? WHERE id=?', (new_active, row[0]))
    else:
        new_active = 1
        c.execute('INSERT INTO student_super_badges (student_id, super_badge_id, active) VALUES (?, ?, ?)', (student_id, badge_id, new_active))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'active': bool(new_active)})

# --- NEW ENDPOINT: Batch update super badges for a student ---
@super_badges_bp.route('/api/student/<int:student_id>/super_badges/batch_update', methods=['POST'])
def batch_update_student_super_badges(student_id):
    data = request.get_json()
    badge_states = data.get('badges', {})
    if not isinstance(badge_states, dict):
        return jsonify({'success': False, 'error': 'Invalid data'}), 400
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    # Ensure table exists
    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        super_badge_id TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        UNIQUE(student_id, super_badge_id)
    )''')
    import datetime
    for badge_id, is_active in badge_states.items():
        c.execute('SELECT id FROM student_super_badges WHERE student_id=? AND super_badge_id=?', (student_id, badge_id))
        row = c.fetchone()
        now_str = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        if row:
            if is_active:
                # Reactivating: set active=1 and update created_at
                c.execute('UPDATE student_super_badges SET active=?, created_at=? WHERE id=?', (1, now_str, row[0]))
            else:
                # Deactivating: set active=0 only
                c.execute('UPDATE student_super_badges SET active=? WHERE id=?', (0, row[0]))
        else:
            # Insert new record with created_at
            c.execute('INSERT INTO student_super_badges (student_id, super_badge_id, active, created_at) VALUES (?, ?, ?, ?)',
                      (student_id, badge_id, 1 if is_active else 0, now_str))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- NEW ENDPOINTS: Notes for all super badges for a student ---
from flask import session
from datetime import datetime

@super_badges_bp.route('/api/student/<int:student_id>/super_badges/notes', methods=['GET'])
@login_required()
def get_super_badges_notes(student_id):
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges_notes (
        student_id INTEGER PRIMARY KEY,
        note TEXT,
        updated_at TEXT,
        user TEXT
    )''')
    c.execute('SELECT note, updated_at, user FROM student_super_badges_notes WHERE student_id=?', (student_id,))
    row = c.fetchone()
    display_name = ''
    if row and row[2]:
        user_id = row[2]
        # Try users table first
        c.execute('SELECT name FROM users WHERE id=?', (user_id,))
        user_row = c.fetchone()
        if user_row and user_row[0]:
            display_name = user_row[0]
        else:
            # Try teachers table
            c.execute('SELECT name FROM teachers WHERE id=?', (user_id,))
            teacher_row = c.fetchone()
            if teacher_row and teacher_row[0]:
                display_name = teacher_row[0]
            else:
                display_name = user_id
    return jsonify({'note': row[0] if row else '', 'updated_at': row[1] if row else '', 'user': display_name})

@super_badges_bp.route('/api/student/<int:student_id>/super_badges/notes', methods=['POST'])
@login_required()
def save_super_badges_notes(student_id):
    from flask import session
    from datetime import datetime
    data = request.get_json()
    note = data.get('note', '').strip()
    # Always use the user ID from session for tracking
    user_id = session.get('user_id', None)
    updated_at = datetime.now().strftime('%Y-%m-%d %H:%M')
    conn = sqlite3.connect('ArabicSchool.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS student_super_badges_notes (
        student_id INTEGER PRIMARY KEY,
        note TEXT,
        updated_at TEXT,
        user TEXT
    )''')
    c.execute('SELECT student_id FROM student_super_badges_notes WHERE student_id=?', (student_id,))
    exists = c.fetchone()
    if exists:
        c.execute('UPDATE student_super_badges_notes SET note=?, updated_at=?, user=? WHERE student_id=?', (note, updated_at, str(user_id), student_id))
    else:
        c.execute('INSERT INTO student_super_badges_notes (student_id, note, updated_at, user) VALUES (?, ?, ?, ?)', (student_id, note, updated_at, str(user_id)))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'updated_at': updated_at, 'user': user_id})

# @super_badges_bp.route('/api/super_badges', methods=['POST'])
# def add_super_badge():
#     import traceback
#     try:
#         print("[add_super_badge] Called")
#         data = request.get_json(force=True, silent=True)
#         print("[add_super_badge] Received data:", data)
#         if not data:
#             return jsonify({'error': 'No JSON payload received'}), 400
#         name = data.get('name')
#         icon_type = data.get('icon_type')
#         icon_value = data.get('icon_value')
#
#         # --- ENFORCE: If icon_type is 'svg', icon_value must be SVG data, even for key icons ---
#         if icon_type == 'svg':
#             assert icon_value.strip().startswith('<svg'), (
#                 "icon_type is 'svg' but icon_value does not start with <svg. "
#                 "Frontend must send SVG data for all svg icons, including key icons!"
#             )
#         if not name or not icon_type or not icon_value:
#             print(f"[add_super_badge] Missing required fields: name={name}, icon_type={icon_type}, icon_value={icon_value}")
#             return jsonify({'error': 'Name, icon_type, and icon_value are required'}), 400
#         badge = SuperBadge(id=str(uuid.uuid4()), name=name, icon_type=icon_type, icon_value=icon_value)
#         db.session.add(badge)
#         db.session.commit()
#         print(f"[add_super_badge] Badge created: {badge.id}")
#         # NOTE: Do not override icon_type or icon_value here. If icon_type is 'svg', icon_value must be SVG data, never a key name.
#
#
#         # --- Assign this badge to all students as active ---
#         import sqlite3
#         from flask import current_app
#         db_path = current_app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
#         conn = sqlite3.connect(db_path)
#         c = conn.cursor()
#         c.execute('SELECT id FROM students')
#         student_ids = [row[0] for row in c.fetchall()]
#         conn.close()
#         print(f"[add_super_badge] Student IDs fetched: {student_ids}")
#         # (Assignment logic can be added here if needed)
#         db.session.commit()
#         return jsonify({'id': badge.id, 'name': badge.name, 'icon_type': badge.icon_type, 'icon_value': badge.icon_value})
#     except Exception as e:
#         print('[add_super_badge] Exception:', str(e))
#         print(traceback.format_exc())
#         return jsonify({'error': 'Internal server error', 'details': str(e)}), 500


# @super_badges_bp.route('/api/super_badges/<badge_id>', methods=['GET'])
# def get_super_badge(badge_id):
#     badge = SuperBadge.query.get(badge_id)
#     if not badge:
#         return jsonify({'error': 'Not found'}), 404
#     return jsonify({
#         'id': badge.id,
#         'name': badge.name,
#         'icon_type': getattr(badge, 'icon_type', None),
#         'icon_value': getattr(badge, 'icon_value', None)
#     })

# @super_badges_bp.route('/api/super_badges/<badge_id>', methods=['PUT'])
# def update_super_badge(badge_id):
#     badge = SuperBadge.query.get(badge_id)
#     if not badge:
#         return jsonify({'error': 'Not found'}), 404
#
#     data = request.get_json()
#     badge.name = data.get('name', badge.name)
#     icon_type = data.get('icon_type', badge.icon_type)
#     icon_value = data.get('icon_value', badge.icon_value)
#     # --- ENFORCE: If icon_type is 'svg', icon_value must be SVG data, even for key icons ---
#     if icon_type == 'svg':
#         assert icon_value.strip().startswith('<svg'), (
#             "icon_type is 'svg' but icon_value does not start with <svg. "
#             "Frontend must send SVG data for all svg icons, including key icons!"
#         )
#     badge.icon_type = icon_type
#     badge.icon_value = icon_value
#     db.session.commit()
#     return jsonify({'id': badge.id, 'name': badge.name, 'icon_type': badge.icon_type, 'icon_value': badge.icon_value})
#     # NOTE: Do not override icon_type or icon_value here. If icon_type is 'svg', icon_value must be SVG data, never a key name.

# @super_badges_bp.route('/api/super_badges/<id>', methods=['DELETE'])
# def delete_super_badge(id):
#     badge = SuperBadge.query.get(id)
#     if not badge:
#         return jsonify({'error': 'Badge not found'}), 404
#     db.session.delete(badge)
#     db.session.commit()
#     return jsonify({'success': True})
