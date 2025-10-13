from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import mysql
from werkzeug.security import generate_password_hash, check_password_hash
import MySQLdb

admin_bp = Blueprint('admin', __name__)



@admin_bp.route('/dashboard')
def adminDashboard():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    # Get user statistics
    cur.execute("SELECT COUNT(*) FROM users WHERE role='teacher'")
    teacher_count = cur.fetchone()['COUNT(*)']

    cur.execute("SELECT COUNT(*) FROM users WHERE role='student'")
    student_count = cur.fetchone()['COUNT(*)']

    # Get admin id
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    user = cur.fetchone()
    if user is None:
        flash('User not found', 'error')
        return redirect(url_for('auth.login'))
    admin_id = user['id']

    # Fetch recent activities from notifications for current admin (last 5)
    cur.execute("""
        SELECT type, message, created_at
        FROM notifications
        WHERE user_id = %s AND role = 'admin'
        ORDER BY created_at DESC
        LIMIT 5
    """, (admin_id,))
    recent_activities = cur.fetchall()
    cur.close()

    unread_notifications_count = get_admin_unread_notifications_count(admin_id)

    stats = {
        'teachers': teacher_count,
        'students': student_count
    }

    return render_template('admin_dashboard.html', stats=stats, first_name=session['first_name'],
                           unread_notifications_count=unread_notifications_count,
                           recent_activities=recent_activities)

@admin_bp.route('/users')
def adminUsers():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT id, username, first_name, last_name, email, role FROM users WHERE role != 'admin' ORDER BY role, first_name")
    users = cur.fetchall()

    cur.close()

    cur = mysql.connection.cursor()
    # Get admin id
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    user = cur.fetchone()
    admin_id = user['id']
    cur.close()

    unread_notifications_count = get_admin_unread_notifications_count(admin_id)

    return render_template('admin_users.html', users=users, first_name=session['first_name'],
                            unread_notifications_count=unread_notifications_count)





@admin_bp.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
def editUser(user_id):
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':
        update_fields = []
        params = []

        if 'username' in request.form:
            update_fields.append('username = %s')
            params.append(request.form['username'])

        if 'first_name' in request.form:
            update_fields.append('first_name = %s')
            params.append(request.form['first_name'])

        if 'last_name' in request.form:
            update_fields.append('last_name = %s')
            params.append(request.form['last_name'])

        if 'email' in request.form:
            email_val = request.form['email'] or None
            update_fields.append('email = %s')
            params.append(email_val)

        if 'role' in request.form:
            update_fields.append('role = %s')
            params.append(request.form['role'])

        if not update_fields:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        try:
            query = "UPDATE users SET " + ', '.join(update_fields) + " WHERE id = %s"
            params.append(user_id)
            cur.execute(query, params)
            mysql.connection.commit()
            return jsonify({'success': True})
        except Exception as e:
            mysql.connection.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
        finally:
            cur.close()

    cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone()
    cur.close()

    if not user:
        flash('User not found', 'error')
        return redirect(url_for('admin.adminUsers'))

    return render_template('admin_edit_user.html', user=user, first_name=session['first_name'])

@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
def deleteUser(user_id):
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized access'}), 403

    cur = mysql.connection.cursor()

    try:
        # Get user info before deletion for notification
        cur.execute("SELECT username, first_name, last_name, role FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'User  not found'}), 404
        
        cur.execute("DELETE FROM notifications WHERE user_id=%s", (user_id,))
        cur.execute("DELETE FROM submissions WHERE student_id=%s", (user_id,))
        cur.execute("DELETE FROM enrollments WHERE student_id=%s", (user_id,))
        cur.execute("DELETE FROM activities WHERE teacher_id=%s", (user_id,))
        cur.execute("DELETE FROM classes WHERE teacher_id=%s", (user_id,))
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        mysql.connection.commit()

        # Notify admins about user deletion
        message = f"User  deleted: {user[1]} {user[2]} ({user[0]}), Role: {user[3]}."
        add_admin_notification(message, notif_type='user_deleted')

        return jsonify({'success': True})
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cur.close()

@admin_bp.route('/settings')
def adminSettings():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM settings WHERE id=1")
    settings = cur.fetchone()
    cur.close()

    cur = mysql.connection.cursor()
    # Get admin id
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    user = cur.fetchone()
    admin_id = user['id']
    cur.close()

    unread_notifications_count = get_admin_unread_notifications_count(admin_id)

    if not settings:
        settings = {
            'site_name': 'C-Insight',
            'admin_email': 'admin@cinsight.com',
            'primary_color': '#6f42c1',
            'secondary_color': '#007bff',
            'font_family': 'Arial, sans-serif'
        }

    # Get user statistics for status display
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE role='teacher'")
    teacher_count = cur.fetchone()['COUNT(*)']
    cur.execute("SELECT COUNT(*) FROM users WHERE role='student'")
    student_count = cur.fetchone()['COUNT(*)']
    cur.close()

    stats = {
        'teachers': teacher_count,
        'students': student_count
    }

    return render_template('admin_settings.html', settings=settings, stats=stats, first_name=session['first_name'],
                           unread_notifications_count=unread_notifications_count)

@admin_bp.route('/update-settings', methods=['POST'])
def updateSettings():
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized access'}), 403

    site_name = request.form['site_name']
    admin_email = request.form['admin_email']

    cur = mysql.connection.cursor()

    try:
        cur.execute("UPDATE settings SET site_name=%s, admin_email=%s WHERE id=1", (site_name, admin_email))
        mysql.connection.commit()
        return jsonify({'success': True})
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cur.close()

def add_admin_notification(message, notif_type='info', link=None):
    cur = mysql.connection.cursor()
    # Assuming admin user(s) have role='admin', you can notify all admins or a specific admin
    # Here, notify all admins
    cur.execute("SELECT id FROM users WHERE role='admin'")
    admins = cur.fetchall()
    for (admin_id,) in admins:
        cur.execute("""
            INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
            VALUES (%s, 'admin', %s, %s, %s, FALSE, NOW())
        """, (admin_id, notif_type, message, link))
    mysql.connection.commit()
    cur.close()
def get_admin_unread_notifications_count(admin_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM notifications
        WHERE user_id = %s AND role = 'admin' AND is_read = FALSE
    """, (admin_id,))
    count = cur.fetchone()['COUNT(*)']
    cur.close()
    return count


@admin_bp.route('/notifications')
def admin_notifications():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get admin user id
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    user = cur.fetchone()
    if not user:
        flash('User  not found', 'error')
        return redirect(url_for('auth.login'))
    admin_id = user['id']

    # Fetch notifications for admin
    cur.execute("""
        SELECT id, type, message, link, is_read, created_at
        FROM notifications
        WHERE user_id = %s AND role = 'admin'
        ORDER BY created_at DESC
    """, (admin_id,))
    notifications = cur.fetchall()

    # Mark all unread notifications as read
    cur.execute("""
        UPDATE notifications SET is_read = TRUE
        WHERE user_id = %s AND role = 'admin' AND is_read = FALSE
    """, (admin_id,))
    mysql.connection.commit()
    cur.close()

    return render_template('admin_notifications.html', notifications=notifications, username=session['username'])

@admin_bp.route('/stats/monthly')
def monthlyStats():
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT DATE_FORMAT(created_at, '%Y-%m') as month, COUNT(*) as count
        FROM users
        WHERE role != 'admin'
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    """)
    data = cur.fetchall()
    cur.close()

    # Format as list of dicts
    result = [{'month': row[0], 'count': row[1]} for row in data]
    return jsonify(result)

@admin_bp.route('/notifications/count')
def notificationsCount():
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    cur = mysql.connection.cursor()
    # Get admin id
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    user = cur.fetchone()
    admin_id = user['id']
    cur.close()

    count = get_admin_unread_notifications_count(admin_id)
    return jsonify({'count': count})
