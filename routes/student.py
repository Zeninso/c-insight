from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app import mysql
from datetime import datetime, timedelta
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
    
    # Notify students about upcoming or passed deadlines
    notify_students_activity_deadline()

    cur = mysql.connection.cursor()

    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]

    # Get enrolled classes count
    cur.execute("""
        SELECT COUNT(*) FROM enrollments WHERE student_id = %s
    """, (student_id,))
    enrolled_classes_count = cur.fetchone()[0]

    # Get upcoming activities (next 5 due in the future)
    cur.execute("""
        SELECT a.title, a.due_date, c.name as class_name
        FROM activities a
        JOIN classes c ON a.class_id = c.id
        JOIN enrollments e ON c.id = e.class_id
        WHERE e.student_id = %s AND a.due_date > NOW()
        ORDER BY a.due_date ASC
        LIMIT 5
    """, (student_id,))
    upcoming_activities = cur.fetchall()

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]
    unread_notifications_count = get_unread_notifications_count(student_id)

    # Get recent submissions (last 5)
    cur.execute("""
        SELECT a.title, s.submitted_at, c.name as class_name
        FROM submissions s
        JOIN activities a ON s.activity_id = a.id
        JOIN classes c ON a.class_id = c.id
        WHERE s.student_id = %s
        ORDER BY s.submitted_at DESC
        LIMIT 5
    """, (student_id,))
    recent_submissions = cur.fetchall()

    # Get total activities and submitted activities for progress
    cur.execute("""
        SELECT COUNT(*) FROM activities a
        JOIN classes c ON a.class_id = c.id
        JOIN enrollments e ON c.id = e.class_id
        WHERE e.student_id = %s
    """, (student_id,))
    total_activities = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM submissions s
        WHERE s.student_id = %s
    """, (student_id,))
    submitted_activities = cur.fetchone()[0]

    progress_percentage = (submitted_activities / total_activities * 100) if total_activities > 0 else 0

    cur.close()

    return render_template('student_Dashboard.html',
                          username=session['username'],
                          enrolled_classes_count=enrolled_classes_count,
                          upcoming_activities=upcoming_activities,
                          recent_submissions=recent_submissions,
                          total_activities=total_activities,
                          submitted_activities=submitted_activities,
                          progress_percentage=progress_percentage,
                          unread_notifications_count=unread_notifications_count)


@student_bp.route('/join_class', methods=['GET', 'POST'])
def join_class():

    cur = mysql.connection.cursor()

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]
    unread_notifications_count = get_unread_notifications_count(student_id)
    cur.close()

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

        # Insert notification for student
        message = f"You have been added to class '{class_name}' by your teacher."
        link = url_for('student.class_details', class_id=class_id)
        cur.execute("""
            INSERT INTO notifications (user_id, role, type, message, link)
            VALUES (%s, 'student', 'added_to_class', %s, %s)
        """, (student_id, message, link))

        # Insert notification for teacher
        cur.execute("SELECT teacher_id, name FROM classes WHERE id = %s", (class_id,))
        class_info = cur.fetchone()
        teacher_id = class_info[0]
        class_name = class_info[1]
        student_name = f"{session.get('first_name', '')} {session.get('last_name', '')}".strip()
        notify_teacher_student_join_leave(teacher_id, student_name, class_name, 'joined')
        
        mysql.connection.commit()
        cur.close()
        
        flash(f'Successfully joined {class_name}!', 'success')
        return redirect(url_for('student.studentDashboard'))
    
    return render_template('student_join_class.html', username=session['username'],
                            unread_notifications_count=unread_notifications_count)


@student_bp.route('/my_classes')
def studentClasses():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    cur = mysql.connection.cursor()
    
    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]
    unread_notifications_count = get_unread_notifications_count(student_id)
    
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
    
    # Get activities count and activities for each class
    classes_list = []
    for class_item in classes:
        cur.execute("""
            SELECT COUNT(*)
            FROM activities
            WHERE class_id = %s
        """, (class_item[0],))
        activity_count = cur.fetchone()[0]

        # Get activities for this class
        cur.execute("""
            SELECT id, title, due_date, created_at
            FROM activities
            WHERE class_id = %s
            ORDER BY due_date ASC
        """, (class_item[0],))
        activities = cur.fetchall()

        activities_list = []
        for activity in activities:
            activities_list.append({
                'id': activity[0],
                'title': activity[1],
                'due_date': activity[2],
                'created_at': activity[3]
            })

        classes_list.append({
            'id': class_item[0],
            'name': class_item[1],
            'description': class_item[2],
            'teacher_name': f"{class_item[3]} {class_item[4]}",
            'enrolled_at': class_item[5],
            'activity_count': activity_count,
            'activities': activities_list
        })
    
    cur.close()
    
    return render_template('student_classes.html', classes=classes_list, username=session['username'],
                            unread_notifications_count=unread_notifications_count)    


@student_bp.route('/activities')
def studentActivities():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    cur = mysql.connection.cursor()

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]
    unread_notifications_count = get_unread_notifications_count(student_id)
    
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
    
    return render_template('student_activities.html', activities=activities_list, username=session['username'],
                            unread_notifications_count=unread_notifications_count)


@student_bp.route('/settings', methods=['GET', 'POST'])
def studentSettings():
    
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    

    
    cur = mysql.connection.cursor()
    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]
    unread_notifications_count = get_unread_notifications_count(student_id)
    cur.close()

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

        # Check if any changes were made
        changed = (
            username != user['username'] or
            first_name != user['first_name'] or
            last_name != user['last_name'] or
            email != user['email'] or
            hashed_password != user['password']
        )

        if not changed:
            if request.headers.get('Accept') == 'application/json':
                return jsonify({'info': 'No changes detected'})
            else:
                flash('No changes detected.', 'info')
                return redirect(url_for('student.studentSettings'))

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

            if request.headers.get('Accept') == 'application/json':
                return jsonify({'success': True})
            else:
                flash('Settings updated successfully.', 'success')
                return redirect(url_for('student.studentSettings'))
        except Exception as e:
            mysql.connection.rollback()
            if request.headers.get('Accept') == 'application/json':
                return jsonify({'error': f'Failed to update settings: {str(e)}'})
            else:
                flash(f'Failed to update settings: {str(e)}', 'error')

    cur.close()
    return render_template('student_settings.html', user=user,
                            unread_notifications_count=unread_notifications_count)


@student_bp.route('/class_details/<int:class_id>')
def class_details(class_id):
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]

    # Check if student is enrolled in the class
    cur.execute("""
        SELECT e.id FROM enrollments e
        WHERE e.class_id = %s AND e.student_id = %s
    """, (class_id, student_id))

    if not cur.fetchone():
        flash('You are not enrolled in this class', 'error')
        return redirect(url_for('student.studentClasses'))

    # Get class details
    cur.execute("""
        SELECT c.id, c.name, c.description, c.class_code, c.code_expires, c.created_at,
                u.first_name, u.last_name
        FROM classes c
        JOIN users u ON c.teacher_id = u.id
        WHERE c.id = %s
    """, (class_id,))

    class_data = cur.fetchone()

    if not class_data:
        flash('Class not found', 'error')
        return redirect(url_for('student.studentClasses'))

    # Get activities for the class
    cur.execute("""
        SELECT id, title, due_date, created_at
        FROM activities
        WHERE class_id = %s
        ORDER BY due_date ASC
    """, (class_id,))

    activities = cur.fetchall()
    cur.close()

    # Convert to dict
    class_info = {
        'id': class_data[0],
        'name': class_data[1],
        'description': class_data[2],
        'class_code': class_data[3],
        'code_expires': class_data[4],
        'created_at': class_data[5],
        'teacher_name': f"{class_data[6]} {class_data[7]}"
    }

    activities_list = []
    for activity in activities:
        activities_list.append({
            'id': activity[0],
            'title': activity[1],
            'due_date': activity[2],
            'created_at': activity[3]
        })

    return render_template('student_class_details.html', class_data=class_info, activities=activities_list)


@student_bp.route('/activity/<int:activity_id>')
def viewActivity(activity_id):
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]
    unread_notifications_count = get_unread_notifications_count(student_id)

    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]

    # Get activity details and check if student is enrolled in the class
    cur.execute("""
        SELECT a.id, a.teacher_id, a.class_id, a.title, a.description,
                a.instructions, a.starter_code, a.due_date, a.created_at,
                u.first_name, u.last_name, c.name as class_name,
                CASE WHEN s.id IS NOT NULL THEN 1 ELSE 0 END as submitted,
                CASE WHEN a.due_date < NOW() THEN 1 ELSE 0 END as overdue,
                s.code, s.submitted_at, a.correctness_weight, a.syntax_weight,
                a.logic_weight, a.similarity_weight, s.correctness_score,
                s.syntax_score, s.logic_score, s.similarity_score, s.feedback
        FROM activities a
        JOIN users u ON a.teacher_id = u.id
        JOIN classes c ON a.class_id = c.id
        JOIN enrollments e ON c.id = e.class_id AND e.student_id = %s
        LEFT JOIN submissions s ON a.id = s.activity_id AND s.student_id = %s
        WHERE a.id = %s
    """, (student_id, student_id, activity_id))

    activity = cur.fetchone()
    cur.close()

    if not activity:
        flash('Activity not found or you are not enrolled in this class', 'error')
        return redirect(url_for('student.studentActivities'))

    # Convert to dict
    activity_dict = {
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
        'overdue': bool(activity[13]),
        'code': activity[14],
        'submitted_at': activity[15],
        'correctness_weight': activity[16],
        'syntax_weight': activity[17],
        'logic_weight': activity[18],
        'similarity_weight': activity[19],
        'correctness_score': activity[20],
        'syntax_score': activity[21],
        'logic_score': activity[22],
        'similarity_score': activity[23],
        'feedback': activity[24]
    }

    return render_template('student_activity_view.html', activity=activity_dict, first_name=session.get('first_name', ''), last_name=session.get('last_name', ''),
                            unread_notifications_count=unread_notifications_count)

@student_bp.route('/submit_activity/<int:activity_id>', methods=['POST'])
def submit_activity(activity_id):
    from app.grading import grade_submission

    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    code = request.form.get('code', '').strip()
    if not code:
        flash('Submission code cannot be empty.', 'error')
        return redirect(url_for('student.viewActivity', activity_id=activity_id))

    cur = mysql.connection.cursor()

    try:
        # Get student ID
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        student_id = cur.fetchone()[0]

        # Check if student is enrolled in the class for this activity
        cur.execute("""
            SELECT a.id FROM activities a
            JOIN classes c ON a.class_id = c.id
            JOIN enrollments e ON c.id = e.class_id AND e.student_id = %s
            WHERE a.id = %s
        """, (student_id, activity_id))

        if not cur.fetchone():
            flash('You are not enrolled in the class for this activity.', 'error')
            return redirect(url_for('student.studentActivities'))

        # Insert or update submission
        cur.execute("""
            SELECT id FROM submissions
            WHERE activity_id = %s AND student_id = %s
        """, (activity_id, student_id))

        submission = cur.fetchone()

        now = datetime.now()

        if submission:
            # Update existing submission
            cur.execute("""
                UPDATE submissions
                SET code=%s, submitted_at=%s
                WHERE id=%s
            """, (code, now, submission[0]))
            submission_id = submission[0]
        else:
            # Insert new submission
            cur.execute("""
                INSERT INTO submissions (activity_id, student_id, code, submitted_at)
                VALUES (%s, %s, %s, %s)
            """, (activity_id, student_id, code, now))
            submission_id = cur.lastrowid

        mysql.connection.commit()

        # Grade the submission
        grading_result = grade_submission(activity_id, student_id, code)

        if 'error' not in grading_result:
            # Update submission with scores and feedback
            cur.execute("""
                UPDATE submissions
                SET correctness_score=%s, syntax_score=%s, logic_score=%s, similarity_score=%s, feedback=%s
                WHERE id=%s
            """, (
                grading_result['correctness_score'],
                grading_result['syntax_score'],
                grading_result['logic_score'],
                grading_result['similarity_score'],
                grading_result['feedback'],
                submission_id
            ))
            mysql.connection.commit()
            flash('Activity submitted and graded successfully!', 'success')
        else:
            flash(f"Activity submitted but grading failed: {grading_result['error']}", 'warning')

    except Exception as e:
        mysql.connection.rollback()
        flash(f'Failed to submit activity: {str(e)}', 'error')
    finally:
        cur.close()

    return redirect(url_for('student.viewActivity', activity_id=activity_id))


@student_bp.route('/un_enroll/<int:class_id>', methods=['POST'])
def un_enroll(class_id):
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]

    # Check if student is enrolled in the class
    cur.execute("""
        SELECT e.id FROM enrollments e
        WHERE e.class_id = %s AND e.student_id = %s
    """, (class_id, student_id))

    enrollment = cur.fetchone()

    if not enrollment:
        flash('You are not enrolled in this class', 'error')
        return redirect(url_for('student.studentClasses'))

    # Delete the enrollment
    cur.execute("""
        DELETE FROM enrollments
        WHERE class_id = %s AND student_id = %s
    """, (class_id, student_id))

    # Insert notification for teacher
    cur.execute("SELECT teacher_id, name FROM classes WHERE id = %s", (class_id,))
    class_info = cur.fetchone()
    teacher_id = class_info[0]
    class_name = class_info[1]

    student_name = f"{session.get('first_name', '')} {session.get('last_name', '')}".strip()
    notify_teacher_student_join_leave(teacher_id, student_name, class_name, 'left')

    mysql.connection.commit()
    cur.close()

    flash('Successfully left the class', 'success')
    return redirect(url_for('student.studentClasses'))

def get_unread_notifications_count(user_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM notifications
        WHERE user_id = %s AND role = 'student' AND is_read = FALSE
    """, (user_id,))
    count = cur.fetchone()[0]
    cur.close()
    return count

def add_notification(user_id, role, notif_type, message, link=None):
    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO notifications (user_id, role, type, message, link)
        VALUES (%s, %s, %s, %s, %s)
    """, (user_id, role, notif_type, message, link))
    mysql.connection.commit()
    cur.close()

def notify_students_activity_assigned(class_id, activity_id, activity_title, due_date):
    cur = mysql.connection.cursor()
    # Get all students enrolled in the class
    cur.execute("SELECT student_id FROM enrollments WHERE class_id = %s", (class_id,))
    students = cur.fetchall()
    for (student_id,) in students:
        message = f"New activity assigned: '{activity_title}' in your class. Deadline: {due_date.strftime('%Y-%m-%d %H:%M')}."
        link = url_for('student.viewActivity', activity_id=activity_id)
        add_notification(student_id, 'student', 'new_activity', message, link)
    cur.close()

def notify_teacher_student_join_leave(teacher_id, student_name, class_name, action):
    # action: 'joined' or 'left'
    message = f"Student {student_name} has {action} your class '{class_name}'."
    add_notification(teacher_id, 'teacher', f'student_{action}', message)

def notify_teacher_activity_finished(teacher_id, activity_title, class_name, total_submissions, total_students):
    message = (f"Activity '{activity_title}' in class '{class_name}' is finished. "
               f"Submissions: {total_submissions}/{total_students}.")
    add_notification(teacher_id, 'teacher', 'activity_finished', message)


@student_bp.route('/progress')
def studentProgress():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]

    # Get unread notifications count
    unread_notifications_count = get_unread_notifications_count(student_id)

    # Get overall progress
    cur.execute("""
        SELECT COUNT(*) FROM activities a
        JOIN classes c ON a.class_id = c.id
        JOIN enrollments e ON c.id = e.class_id
        WHERE e.student_id = %s
    """, (student_id,))
    total_activities = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM submissions s
        WHERE s.student_id = %s
    """, (student_id,))
    submitted_activities = cur.fetchone()[0]

    progress_percentage = (submitted_activities / total_activities * 100) if total_activities > 0 else 0

    # Get progress per class
    cur.execute("""
        SELECT c.name, c.id,
               COUNT(a.id) as total_activities,
               COUNT(s.id) as submitted_activities
        FROM classes c
        JOIN enrollments e ON c.id = e.class_id
        LEFT JOIN activities a ON c.id = a.class_id
        LEFT JOIN submissions s ON a.id = s.activity_id AND s.student_id = %s
        WHERE e.student_id = %s
        GROUP BY c.id, c.name
        ORDER BY c.name
    """, (student_id, student_id))

    class_progress = cur.fetchall()

    # Get progress per activity with scores
    cur.execute("""
        SELECT a.id, a.title, c.name as class_name, a.due_date,
               CASE WHEN s.id IS NOT NULL THEN 1 ELSE 0 END as submitted,
               CASE WHEN a.due_date < NOW() THEN 1 ELSE 0 END as overdue,
               s.correctness_score, s.syntax_score, s.logic_score, s.similarity_score,
               a.correctness_weight, a.syntax_weight, a.logic_weight, a.similarity_weight
        FROM activities a
        JOIN classes c ON a.class_id = c.id
        JOIN enrollments e ON c.id = e.class_id
        LEFT JOIN submissions s ON a.id = s.activity_id AND s.student_id = %s
        WHERE e.student_id = %s
        ORDER BY a.due_date DESC
    """, (student_id, student_id))

    activity_progress = cur.fetchall()
    cur.close()

    # Process activity progress data
    activities_progress_list = []
    for activity in activity_progress:
        total_score = None
        if activity[5] and all(score is not None for score in activity[6:10]):  # submitted and has scores
            total_score = (
                (activity[6] * activity[10] / 100) +  # correctness
                (activity[7] * activity[11] / 100) +  # syntax
                (activity[8] * activity[12] / 100) +  # logic
                (activity[9] * activity[13] / 100)    # similarity
            )

        activities_progress_list.append({
            'id': activity[0],
            'title': activity[1],
            'class_name': activity[2],
            'due_date': activity[3],
            'submitted': bool(activity[4]),
            'overdue': bool(activity[5]),
            'correctness_score': activity[6],
            'syntax_score': activity[7],
            'logic_score': activity[8],
            'similarity_score': activity[9],
            'correctness_weight': activity[10],
            'syntax_weight': activity[11],
            'logic_weight': activity[12],
            'similarity_weight': activity[13],
            'total_score': total_score
        })

    # Process class progress data
    classes_progress_list = []
    for class_item in class_progress:
        class_progress_percentage = (class_item[3] / class_item[2] * 100) if class_item[2] > 0 else 0
        classes_progress_list.append({
            'name': class_item[0],
            'id': class_item[1],
            'total_activities': class_item[2],
            'submitted_activities': class_item[3],
            'progress_percentage': class_progress_percentage
        })

    return render_template('student_progress.html',
                          total_activities=total_activities,
                          submitted_activities=submitted_activities,
                          progress_percentage=progress_percentage,
                          classes_progress=classes_progress_list,
                          activities_progress=activities_progress_list,
                          unread_notifications_count=unread_notifications_count)


@student_bp.route('/grades')
def studentGrades():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    # Get student ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    student_id = cur.fetchone()[0]

    # Get unread notifications count
    unread_notifications_count = get_unread_notifications_count(student_id)

    # Get all submissions with grading results
    cur.execute("""
        SELECT s.id, a.title, c.name as class_name, s.submitted_at,
               s.correctness_score, s.syntax_score, s.logic_score, s.similarity_score,
               a.correctness_weight, a.syntax_weight, a.logic_weight, a.similarity_weight,
               s.feedback
        FROM submissions s
        JOIN activities a ON s.activity_id = a.id
        JOIN classes c ON a.class_id = c.id
        WHERE s.student_id = %s AND s.correctness_score IS NOT NULL
        ORDER BY s.submitted_at DESC
    """, (student_id,))

    submissions = cur.fetchall()
    cur.close()

    # Convert to list of dictionaries
    grades_list = []
    for submission in submissions:
        total_score = (
            (submission[4] * submission[8] / 100) +  # correctness
            (submission[5] * submission[9] / 100) +  # syntax
            (submission[6] * submission[10] / 100) + # logic
            (submission[7] * submission[11] / 100)   # similarity
        ) if submission[4] is not None else None

        grades_list.append({
            'id': submission[0],
            'activity_title': submission[1],
            'class_name': submission[2],
            'submitted_at': submission[3],
            'correctness_score': submission[4],
            'syntax_score': submission[5],
            'logic_score': submission[6],
            'similarity_score': submission[7],
            'correctness_weight': submission[8],
            'syntax_weight': submission[9],
            'logic_weight': submission[10],
            'similarity_weight': submission[11],
            'total_score': total_score,
            'feedback': submission[12]
        })

    return render_template('student_grades.html', grades=grades_list,
                          unread_notifications_count=unread_notifications_count)


@student_bp.route('/notifications')
def notifications():
    if 'username' not in session or session.get('role') != 'student':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    user = cur.fetchone()
    if not user:
        flash('User  not found', 'error')
        return redirect(url_for('auth.login'))
    student_id = user['id']

    cur.execute("""
        SELECT id, type, message, link, is_read, created_at
        FROM notifications
        WHERE user_id = %s AND role = 'student'
        ORDER BY created_at DESC
    """, (student_id,))
    notifications = cur.fetchall()

    cur.execute("""
        UPDATE notifications SET is_read = TRUE
        WHERE user_id = %s AND role = 'student' AND is_read = FALSE
    """, (student_id,))
    mysql.connection.commit()
    cur.close()

    return render_template('student_notifications.html', notifications=notifications, username=session['username'])


def notify_students_activity_deadline():
    cur = mysql.connection.cursor()

    # Define threshold for "near deadline" (e.g., 24 hours)
    now = datetime.now()
    near_deadline = now + timedelta(hours=24)

    # Find activities with due_date within next 24 hours or past due, and not notified yet
    cur.execute("""
        SELECT a.id, a.title, a.due_date, a.class_id
        FROM activities a
        WHERE a.notified_deadline = FALSE
        AND a.due_date <= %s
        AND a.due_date >= %s
    """, (near_deadline, now))

    activities = cur.fetchall()

    for activity_id, title, due_date, class_id in activities:
        # Get students enrolled in the class
        cur.execute("SELECT student_id FROM enrollments WHERE class_id = %s", (class_id,))
        students = cur.fetchall()

        for (student_id,) in students:
            # Compose notification message
            if due_date < now:
                message = f"Deadline passed for activity '{title}'. Please submit as soon as possible."
            else:
                message = f"Activity '{title}' is due soon on {due_date.strftime('%Y-%m-%d %H:%M')}."

            link = url_for('student.viewActivity', activity_id=activity_id)

            # Insert notification if not already exists (optional: avoid duplicates)
            cur.execute("""
                SELECT 1 FROM notifications
                WHERE user_id = %s AND role = 'student' AND type = 'deadline_reminder' AND link = %s
            """, (student_id, link))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
                    VALUES (%s, 'student', 'deadline_reminder', %s, %s, FALSE, NOW())
                """, (student_id, message, link))

        # Mark activity as notified for deadline
        cur.execute("UPDATE activities SET notified_deadline = TRUE WHERE id = %s", (activity_id,))

    mysql.connection.commit()
    cur.close()






