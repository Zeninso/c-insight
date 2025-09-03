from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import mysql
from werkzeug.security import generate_password_hash, check_password_hash
import MySQLdb

admin_bp = Blueprint('admin', __name__)

#ADMIN PASS = '_adminPassword08'

@admin_bp.route('/dashboard')
def adminDashboard():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    # Get user statistics
    cur.execute("SELECT COUNT(*) FROM users WHERE role='teacher'")
    teacher_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE role='student'")
    student_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    admin_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM classes")
    class_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM activities")
    activity_count = cur.fetchone()[0]

    cur.close()

    stats = {
        'teachers': teacher_count,
        'students': student_count,
        'admins': admin_count,
        'classes': class_count,
        'activities': activity_count
    }

    return render_template('admin_dashboard.html', stats=stats, first_name=session['first_name'])

@admin_bp.route('/users')
def adminUsers():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT id, username, first_name, last_name, email, role FROM users ORDER BY role, first_name")
    users = cur.fetchall()
    cur.close()

    return render_template('admin_users.html', users=users, first_name=session['first_name'])

@admin_bp.route('/classes')
def adminClasses():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.id, c.name, c.description, c.class_code, c.code_expires, c.created_at,
                u.first_name, u.last_name, COUNT(e.student_id) as student_count
        FROM classes c
        JOIN users u ON c.teacher_id = u.id
        LEFT JOIN enrollments e ON c.id = e.class_id
        GROUP BY c.id
        ORDER BY c.created_at DESC
    """)
    classes = cur.fetchall()
    cur.close()

    classes_list = []
    for class_item in classes:
        classes_list.append({
            'id': class_item[0],
            'name': class_item[1],
            'description': class_item[2],
            'class_code': class_item[3],
            'code_expires': class_item[4],
            'created_at': class_item[5],
            'teacher_name': f"{class_item[6]} {class_item[7]}",
            'student_count': class_item[8]
        })

    return render_template('admin_classes.html', classes=classes_list, first_name=session['first_name'])

@admin_bp.route('/activities')
def adminActivities():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT a.id, a.title, a.description, a.due_date, a.created_at,
                u.first_name, u.last_name, c.name as class_name,
                COUNT(s.id) as submission_count
        FROM activities a
        JOIN users u ON a.teacher_id = u.id
        LEFT JOIN classes c ON a.class_id = c.id
        LEFT JOIN submissions s ON a.id = s.activity_id
        GROUP BY a.id
        ORDER BY a.created_at DESC
    """)
    activities = cur.fetchall()
    cur.close()

    activities_list = []
    for activity in activities:
        activities_list.append({
            'id': activity[0],
            'title': activity[1],
            'description': activity[2],
            'due_date': activity[3],
            'created_at': activity[4],
            'teacher_name': f"{activity[5]} {activity[6]}",
            'class_name': activity[7] if activity[7] else 'No Class',
            'submission_count': activity[8]
        })

    return render_template('admin_activities.html', activities=activities_list, first_name=session['first_name'])

@admin_bp.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
def editUser(user_id):
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':
        username = request.form['username']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form.get('email')
        role = request.form['role']

        try:
            cur.execute("""
                UPDATE users
                SET username=%s, first_name=%s, last_name=%s, email=%s, role=%s
                WHERE id=%s
            """, (username, first_name, last_name, email, role, user_id))
            mysql.connection.commit()
            flash('User updated successfully', 'success')
            return redirect(url_for('admin.adminUsers'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Failed to update user: {str(e)}', 'error')
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
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    try:
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        mysql.connection.commit()
        flash('User deleted successfully', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Failed to delete user: {str(e)}', 'error')
    finally:
        cur.close()

    return redirect(url_for('admin.adminUsers'))

@admin_bp.route('/create_admin', methods=['GET', 'POST'])
def createAdmin():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form.get('email')

        hashed_password = generate_password_hash(password)

        cur = mysql.connection.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password, first_name, last_name, email, role) VALUES (%s, %s, %s, %s, %s, %s)",
                (username, hashed_password, first_name, last_name, email, 'admin')
            )
            mysql.connection.commit()
            flash('Admin user created successfully', 'success')
            return redirect(url_for('admin.adminUsers'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Failed to create admin: {str(e)}', 'error')
        finally:
            cur.close()

    return render_template('admin_create_admin.html', first_name=session['first_name'])
