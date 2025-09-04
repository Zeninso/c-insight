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
    teacher_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE role='student'")
    student_count = cur.fetchone()[0]


    cur.close()

    stats = {
        'teachers': teacher_count,
        'students': student_count

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
