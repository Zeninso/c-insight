from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app import mysql
from datetime import datetime
from flask import Flask
from flask_mysqldb import MySQL
from flask_dance.contrib.google import make_google_blueprint
import os
from flask_dance.contrib.google import google
from flask import current_app as app
import MySQLdb
import random, string

app = Flask(__name__)
app.secret_key = os.environ.get("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", "dev")


student_bp = Blueprint('student', __name__)



#====================STUDENTS ROUTE=====================


@student_bp.route('/student_Dashboard')
def studentDashboard():
    # Check if user is logged in
    if 'username' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('auth.login'))
    if session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('home.home'))
    return render_template('student_Dashboard.html', username=session['username'])


@student_bp.route('/join_class', methods=['GET', 'POST'])
def join_class():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        class_code = request.form['class_code'].strip().upper()
        
        cur = mysql.connection.cursor()
        
        # Check if class code is valid and not expired
        cur.execute("""
            SELECT id, name, code_expires 
            FROM classes 
            WHERE class_code = %s
        """, (class_code,))
        
        class_info = cur.fetchone()
        
        if not class_info:
            flash('Invalid class code', 'error')
            return redirect(url_for('student.join_class'))
        
        class_id, class_name, code_expires = class_info
        
        from datetime import datetime
        if datetime.now() > code_expires:
            flash('This class code has expired', 'error')
            return redirect(url_for('student.join_class'))
        
        # Get student ID
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        student_id = cur.fetchone()[0]
        
        # Check if student is already enrolled
        cur.execute("""
            SELECT id FROM enrollments 
            WHERE class_id = %s AND student_id = %s
        """, (class_id, student_id))
        
        if cur.fetchone():
            flash(f'You are already enrolled in {class_name}', 'info')
            return redirect(url_for('student.studentDashboard'))
        
        # Enroll the student
        cur.execute("""
            INSERT INTO enrollments (class_id, student_id)
            VALUES (%s, %s)
        """, (class_id, student_id))
        
        mysql.connection.commit()
        cur.close()
        
        flash(f'Successfully joined {class_name}!', 'success')
        return redirect(url_for('student.studentDashboard'))
    
    return render_template('student_join_class.html', username=session['username'])


@student_bp.route('/my_classes')
def studentClasses():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    cur = mysql.connection.cursor()
    
    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]
    
    # Get all classes the student is enrolled in
    cur.execute("""
        SELECT c.id, c.name, c.description, u.first_name, u.last_name, e.enrolled_at
        FROM classes c
        JOIN enrollments e ON c.id = e.class_id
        JOIN users u ON c.teacher_id = u.id
        WHERE e.student_id = %s
        ORDER BY e.enrolled_at DESC
    """, (student_id,))
    
    classes = cur.fetchall()
    
    # Get activities count for each class
    classes_list = []
    for class_item in classes:
        cur.execute("""
            SELECT COUNT(*) 
            FROM activities 
            WHERE class_id = %s
        """, (class_item[0],))
        activity_count = cur.fetchone()[0]
        
        classes_list.append({
            'id': class_item[0],
            'name': class_item[1],
            'description': class_item[2],
            'teacher_name': f"{class_item[3]} {class_item[4]}",
            'enrolled_at': class_item[5],
            'activity_count': activity_count
        })
    
    cur.close()
    
    return render_template('student_classes.html', classes=classes_list, username=session['username'])    


@student_bp.route('/activities')
def studentActivities():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    cur = mysql.connection.cursor()
    
    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]
    
    # Get all activities from classes where the student is enrolled
    cur.execute("""
        SELECT a.id, a.teacher_id, a.class_id, a.title, a.description, 
                a.instructions, a.starter_code, a.due_date, a.created_at,
                u.first_name, u.last_name, c.name as class_name,
                CASE WHEN s.id IS NOT NULL THEN 1 ELSE 0 END as submitted,
                CASE WHEN a.due_date < NOW() THEN 1 ELSE 0 END as overdue
        FROM activities a
        JOIN users u ON a.teacher_id = u.id
        JOIN classes c ON a.class_id = c.id
        JOIN enrollments e ON c.id = e.class_id AND e.student_id = %s
        LEFT JOIN submissions s ON a.id = s.activity_id AND s.student_id = %s
        ORDER BY a.due_date ASC, a.created_at DESC
    """, (student_id, student_id))
    
    activities = cur.fetchall()
    cur.close()
    
    # Convert to list of dictionaries
    activities_list = []
    for activity in activities:
        activities_list.append({
            'id': activity[0],
            'teacher_id': activity[1],
            'class_id': activity[2],
            'title': activity[3],
            'description': activity[4],
            'instructions': activity[5],
            'starter_code': activity[6],
            'due_date': activity[7],
            'created_at': activity[8],
            'teacher_name': f"{activity[9]} {activity[10]}",
            'class_name': activity[11],
            'submitted': bool(activity[12]),
            'overdue': bool(activity[13])
        })
    
    return render_template('student_activities.html', activities=activities_list, username=session['username'])


@student_bp.route('/settings', methods=['GET', 'POST'])
def studentSettings():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT * FROM users WHERE username = %s", (session['username'],))
    user = cur.fetchone()

    if request.method == 'POST':
        # Profile info
        username = request.form.get('username', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        if email == '':
            email = None

        # Password change fields
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validate required profile fields
        if not username or not first_name or not last_name:
            flash('Username, First name, and Last name, are required.', 'error')
            return render_template('teacher_settings.html', user=user)
        
        # Check if the new username is already taken by another user
        cur.execute("SELECT username FROM users WHERE username = %s AND username != %s", (username, session['username']))
        existing_user = cur.fetchone()

        if existing_user:
            errors = {}
            # After checking if username exists
            if existing_user:
                errors['username'] = 'The username is already taken. Please choose a different one.'
            # Then, if errors exist, render template with errors and user data
            if errors:
                return render_template('student_settings.html', user=user, errors=errors)


        # Password change validation
        if new_password or confirm_password:
            if not current_password:
                flash('Current password is required to change password.', 'error')
                return render_template('student_settings.html', user=user)
            if not check_password_hash(user['password'], current_password):
                flash('Current password is incorrect.', 'error')
                return render_template('student_settings.html', user=user)
            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'error')
                return render_template('student_settings.html', user=user)
            if len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'error')
                return render_template('student_settings.html', user=user)
            hashed_password = generate_password_hash(new_password)
        else:
            hashed_password = user['password']

        try:
            cur.execute("""
                UPDATE users
                SET username=%s, first_name=%s, last_name=%s, email=%s, password=%s
                WHERE username=%s
            """, (
                username, first_name, last_name, email, hashed_password,
                session['username']
            ))
            mysql.connection.commit()

            # Update session info
            session['username'] = username
            session['first_name'] = first_name
            session['last_name'] = last_name

            flash('Settings updated successfully.', 'success')
            return redirect(url_for('student.studentSettings'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Failed to update settings: {str(e)}', 'error')

    cur.close()
    return render_template('student_settings.html', user=user)


