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

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get user statistics
    cur.execute("SELECT COUNT(*) as count FROM users WHERE role='teacher'")
    teacher_count = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) as count FROM users WHERE role='student'")
    student_count = cur.fetchone()['count']

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
    print("deleteUser called")
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized access'}), 403

    cur = mysql.connection.cursor()

    try:
        # Get user info before deletion for notification
        cur.execute("SELECT username, first_name, last_name, role FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        username, first_name, last_name, role = user
        print(f"Deleting user: {username}, role: {role}")

        # Manually delete related records in the correct order to avoid CASCADE issues
        if role == 'student':
            # Delete submissions and enrollments for student
            cur.execute("DELETE FROM submissions WHERE student_id=%s", (user_id,))
            cur.execute("DELETE FROM enrollments WHERE student_id=%s", (user_id,))
        elif role == 'teacher':
            # Delete classes for teacher (this will cascade to enrollments, activities, submissions)
            cur.execute("DELETE FROM classes WHERE teacher_id=%s", (user_id,))

        # Delete notifications for the user
        cur.execute("DELETE FROM notifications WHERE user_id=%s", (user_id,))

        # Delete the user
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        mysql.connection.commit()
        print("User deleted and committed")

        # Notify admins about user deletion
        message = f"User deleted: {first_name} {last_name} ({username}), Role: {role}."
        print(f"About to add notification: {message}")
        add_admin_notification(message, notif_type='user_deleted')
        print("Notification added successfully.")

        return jsonify({'success': True})
    except Exception as e:
        print(f"Error in deleteUser: {str(e)}")
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
    cur.execute("SELECT COUNT(*) as count FROM users WHERE role='teacher'")
    teacher_count = cur.fetchone()['count']
    cur.execute("SELECT COUNT(*) as count FROM users WHERE role='student'")
    student_count = cur.fetchone()['count']
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
    print(f"add_admin_notification called: {message}")
    cur = None
    try:
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Get all admin users
        cur.execute("SELECT id FROM users WHERE role='admin'")
        admins = cur.fetchall()
        print(f"Found {len(admins)} admin users")

        if not admins:
            print("No admin users found!")
            return False

        # Insert notification for each admin
        for admin in admins:
            admin_id = admin['id']
            print(f"Inserting notification for admin_id: {admin_id}")
            cur.execute("""
                INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
                VALUES (%s, 'admin', %s, %s, %s, FALSE, NOW())
            """, (admin_id, notif_type, message, link))

        mysql.connection.commit()
        print("Notifications successfully saved to database")
        return True

    except Exception as e:
        print(f"Error in add_admin_notification: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        if mysql.connection:
            mysql.connection.rollback()
        return False
    finally:
        if cur:
            cur.close()

def get_admin_unread_notifications_count(admin_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("""
        SELECT COUNT(*) as count FROM notifications
        WHERE user_id = %s AND role = 'admin' AND is_read = FALSE
    """, (admin_id,))
    count = cur.fetchone()['count']
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

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
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
    result = [{'month': row['month'], 'count': row['count']} for row in data]
    return jsonify(result)

@admin_bp.route('/notifications/count')
def notificationsCount():
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    # Get admin id
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    user = cur.fetchone()
    admin_id = user['id']
    cur.close()

    count = get_admin_unread_notifications_count(admin_id)
    return jsonify({'count': count})


@admin_bp.route('/test-notification', methods=['POST'])
def test_notification():
    """Test route to verify notifications work"""
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        message = "Test notification from admin panel"
        success = add_admin_notification(message, 'test')
        
        if success:
            return jsonify({'success': True, 'message': 'Test notification created'})
        else:
            return jsonify({'success': False, 'message': 'Failed to create notification'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@admin_bp.route('/check-notifications-table')
def check_notifications_table():
    """Check if notifications table exists and has data"""
    if 'username' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        # Check table structure
        cur.execute("DESCRIBE notifications")
        table_structure = cur.fetchall()
        
        # Count notifications
        cur.execute("SELECT COUNT(*) as count FROM notifications")
        count_result = cur.fetchone()
        
        # Get recent notifications
        cur.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 5")
        recent_notifications = cur.fetchall()
        
        return jsonify({
            'table_structure': table_structure,
            'total_count': count_result['count'],
            'recent_notifications': recent_notifications
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()