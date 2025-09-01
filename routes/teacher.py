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

teacher_bp = Blueprint('teacher', __name__)




###################TEACHER ROUTES##########################################

@teacher_bp.route('/teacherDashboard')
def teacherDashboard():
    if 'username' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('auth.login'))
    if session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('home.home'))
    return render_template('teacher_Dashboard.html', first_name=session['first_name'])
        

@teacher_bp.route('/activities', methods=['GET', 'POST'])
def teacherActivities():
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    #  Get teacher ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_row = cur.fetchone()
    if not teacher_row:
        flash("Teacher not found", "error")
        return redirect(url_for('auth.login'))
    teacher_id = teacher_row[0]

    # Get classes for the teacher
    cur.execute("""
        SELECT id, name, description
        FROM classes
        WHERE teacher_id = %s
        ORDER BY name
    """, (teacher_id,))
    classes = cur.fetchall()

    cur.execute("""
        SELECT  a.id, a.teacher_id, a.class_id, a.title, a.description, a.instructions,
                a.starter_code, a.due_date, a.correctness_weight, a.syntax_weight,
                a.logic_weight, a.similarity_weight, a.created_at,
                COUNT(s.id) AS submission_count, c.name AS class_name
        FROM activities a
        LEFT JOIN submissions s ON a.id = s.activity_id
        LEFT JOIN classes c ON a.class_id = c.id
        WHERE a.teacher_id = %s
        GROUP BY a.id
        ORDER BY a.created_at DESC
    """, (teacher_id,))
    activities = cur.fetchall()
    cur.close()

    #  Convert to dicts and format datetime fields
    activities_list = []
    for activity in activities:
        class_name = activity[14]
        if activity[2] is None:
            class_name = 'No Class'
        elif class_name is None:
            class_name = 'Class Deleted'
        elif class_name == '':
            class_name = 'Unnamed Class'
        # else keep class_name

        activities_list.append({
            'id': activity[0],
            'teacher_id': activity[1],
            'class_id': activity[2],
            'title': activity[3],
            'description': activity[4],
            'instructions': activity[5],
            'starter_code': activity[6],
            'due_date': activity[7],
            'correctness_weight': activity[8],
            'syntax_weight': activity[9],
            'logic_weight': activity[10],
            'similarity_weight': activity[11],
            'created_at': activity[12],
            'submission_count': activity[13],
            'class_name': class_name
        })

    # Convert classes to dicts
    classes_list = []
    for class_item in classes:
        classes_list.append({
            'id': class_item[0],
            'name': class_item[1],
            'description': class_item[2]
        })

    return render_template('teacher_activities.html', activities=activities_list, classes=classes_list)


@teacher_bp.route('/create_activity', methods=['POST'])
def create_activity():
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401

    try:
        #  Basic form fields
        class_id = request.form.get('class_id')
        if not class_id:
            return jsonify({'error': 'Class is required'}), 400

        title = request.form['title']
        description = request.form['description']
        instructions = request.form['instructions']
        starter_code = request.form.get('starter_code', '')
        due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%dT%H:%M')
        created_at = datetime.now()

        # Get rubrics arrays from form
        rubric_names = request.form.getlist('rubric_name[]')
        rubric_weights = request.form.getlist('rubric_weight[]')

        if not rubric_names or not rubric_weights:
            return jsonify({'error': 'Rubrics are required'}), 400

        rubrics = {}
        for name, weight in zip(rubric_names, rubric_weights):
            rubrics[name.strip()] = int(weight)

        required_rubrics = ["Correctness", "Syntax", "Logic", "Similarity"]
        for r in required_rubrics:
            if r not in rubrics:
                return jsonify({'error': f'Missing rubric: {r}'}), 400

        correctness_weight = rubrics.get("Correctness", 0)
        syntax_weight = rubrics.get("Syntax", 0)
        logic_weight = rubrics.get("Logic", 0)
        similarity_weight = rubrics.get("Similarity", 0)

        #  Validate weights sum = 100
        total_weight = correctness_weight + syntax_weight + logic_weight + similarity_weight
        if total_weight != 100:
            return jsonify({'error': 'Rubric weights must sum to 100%'}), 400

        #  Get teacher ID
        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_id = cur.fetchone()[0]

        # Verify teacher owns the class
        cur.execute("SELECT id FROM classes WHERE id=%s AND teacher_id=%s", (class_id, teacher_id))
        if not cur.fetchone():
            return jsonify({'error': 'Unauthorized access to class'}), 403

        # Insert into DB
        cur.execute("""
            INSERT INTO activities (
                teacher_id, class_id, title, description, instructions,
                starter_code, due_date, correctness_weight,
                syntax_weight, logic_weight, similarity_weight, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            teacher_id, class_id, title, description, instructions,
            starter_code, due_date, correctness_weight,
            syntax_weight, logic_weight, similarity_weight, created_at
        ))
        mysql.connection.commit()


    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cur' in locals():
            cur.close()


@teacher_bp.route('/activity/<int:activity_id>', methods=['GET', 'PUT', 'DELETE'])
def manage_activity(activity_id):
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401
    
    cur = mysql.connection.cursor()
    
    try:
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_row = cur.fetchone()
        if not teacher_row:
            return jsonify({'error': 'Teacher not found'}), 404
        teacher_id = teacher_row[0]
        
        if request.method == 'GET':
            # Get activity details
            cur.execute("""
                SELECT a.id, a.teacher_id, a.class_id, a.title, a.description, a.instructions,
                        a.starter_code, a.due_date, a.correctness_weight, a.syntax_weight,
                        a.logic_weight, a.similarity_weight, a.created_at,
                        COUNT(s.id) AS submission_count, c.name AS class_name
                FROM activities a
                LEFT JOIN submissions s ON a.id = s.activity_id
                LEFT JOIN classes c ON a.class_id = c.id
                WHERE a.id = %s AND a.teacher_id = %s
                GROUP BY a.id
            """, (activity_id, teacher_id))

            activity = cur.fetchone()
            if not activity:
                return jsonify({'error': 'Activity not found'}), 404


            class_name = activity[14]
            if activity[2] is None:
                class_name = 'No Class'
            elif class_name is None:
                class_name = 'Class Deleted'
            elif class_name == '':
                class_name = 'Unnamed Class'
            # else keep class_name

            activity_dict = {
                'id': activity[0],
                'teacher_id': activity[1],
                'class_id': activity[2],
                'title': activity[3],
                'description': activity[4],
                'instructions': activity[5],
                'starter_code': activity[6],
                'due_date': activity[7].strftime('%Y-%m-%d %H:%M:%S') if activity[7] else None,
                'correctness_weight': activity[8],
                'syntax_weight': activity[9],
                'logic_weight': activity[10],
                'similarity_weight': activity[11],
                'created_at': activity[12].strftime('%Y-%m-%d %H:%M:%S') if activity[12] else None,
                'submission_count': activity[13],
                'class_name': class_name
            }

            return jsonify(activity_dict)
        
        elif request.method == 'PUT':
            # Get form data
            class_id = request.form.get('class_id')
            title = request.form['title']
            description = request.form['description']
            instructions = request.form['instructions']
            starter_code = request.form.get('starter_code', '')
            due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%dT%H:%M')

            # Get rubrics arrays from form
            rubric_names = request.form.getlist('rubric_name[]')
            rubric_weights = request.form.getlist('rubric_weight[]')

            if not rubric_names or not rubric_weights:
                return jsonify({'error': 'Rubrics are required'}), 400


            rubrics = {}
            for name, weight in zip(rubric_names, rubric_weights):
                rubrics[name.strip()] = int(weight)

            required_rubrics = ["Correctness", "Syntax", "Logic", "Similarity"]
            for r in required_rubrics:
                if r not in rubrics:
                    return jsonify({'error': f'Missing rubric: {r}'}), 400

            correctness_weight = rubrics.get("Correctness", 0)
            syntax_weight = rubrics.get("Syntax", 0)
            logic_weight = rubrics.get("Logic", 0)
            similarity_weight = rubrics.get("Similarity", 0)

            # Validate weights sum = 100
            total_weight = correctness_weight + syntax_weight + logic_weight + similarity_weight
            if total_weight != 100:
                return jsonify({'error': 'Rubric weights must sum to 100%'}), 400

            # If class_id is provided and not empty, verify teacher owns the new class
            if class_id and class_id.strip():
                cur.execute("SELECT id FROM classes WHERE id=%s AND teacher_id=%s", (class_id, teacher_id))
                if not cur.fetchone():
                    return jsonify({'error': 'Unauthorized access to class'}), 403

            # Update activity in database
            if class_id and class_id.strip():
                cur.execute("""
                    UPDATE activities
                    SET class_id=%s, title=%s, description=%s, instructions=%s, starter_code=%s,
                        due_date=%s, correctness_weight=%s, syntax_weight=%s,
                        logic_weight=%s, similarity_weight=%s
                    WHERE id=%s AND teacher_id=%s
                """, (
                    class_id, title, description, instructions, starter_code, due_date,
                    correctness_weight, syntax_weight, logic_weight, similarity_weight,
                    activity_id, teacher_id
                ))
            else:
                cur.execute("""
                    UPDATE activities
                    SET class_id=NULL, title=%s, description=%s, instructions=%s, starter_code=%s,
                        due_date=%s, correctness_weight=%s, syntax_weight=%s,
                        logic_weight=%s, similarity_weight=%s
                    WHERE id=%s AND teacher_id=%s
                """, (
                    title, description, instructions, starter_code, due_date,
                    correctness_weight, syntax_weight, logic_weight, similarity_weight,
                    activity_id, teacher_id
                ))

            mysql.connection.commit()
            return jsonify({'success': 'Activity updated successfully'})
            
        elif request.method == 'DELETE':
            # Check if activity exists and belongs to teacher
            cur.execute("SELECT id FROM activities WHERE id=%s AND teacher_id=%s", (activity_id, teacher_id))
            activity = cur.fetchone()
            
            if not activity:
                return jsonify({'error': 'Activity not found'}), 404
            
            # Delete activity
            cur.execute("DELETE FROM activities WHERE id=%s", (activity_id,))
            mysql.connection.commit()
            
            return jsonify({'success': 'Activity deleted successfully'})
            
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500
        
    finally:
        if 'cur' in locals():
            cur.close()
    

    
@teacher_bp.route('/classes')
def teacherClasses():
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    cur = mysql.connection.cursor()
    
    # Get teacher ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()[0]
    
    # Get all classes created by this teacher
    cur.execute("""
        SELECT c.id, c.name, c.description, c.class_code, c.code_expires, 
                COUNT(e.student_id) as student_count
        FROM classes c
        LEFT JOIN enrollments e ON c.id = e.class_id
        WHERE c.teacher_id = %s
        GROUP BY c.id
        ORDER BY c.created_at DESC
    """, (teacher_id,))
    
    classes = cur.fetchall()
    
    # Get activities count for each class
    classes_list = []
    for class_item in classes:
        cur.execute("SELECT COUNT(*) FROM activities WHERE class_id=%s", (class_item[0],))
        activity_count = cur.fetchone()[0]
        
        classes_list.append({
            'id': class_item[0],
            'name': class_item[1],
            'description': class_item[2],
            'class_code': class_item[3],
            'code_expires': class_item[4],
            'student_count': class_item[5],
            'activity_count': activity_count
        })
    
    cur.close()
    
    return render_template('teacher_classes.html', classes=classes_list, first_name=session['first_name'])


@teacher_bp.route('/create_class', methods=['POST'])
def create_class():
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401
    
    try:
        name = request.form['name']
        description = request.form.get('description', '')
        
        # Generate a unique class code
        import random
        import string
        from datetime import datetime, timedelta
        
        # Generate a 6-character alphanumeric code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code_expires = datetime.now() + timedelta(days=7)  # Code expires in 7 days
        
        cur = mysql.connection.cursor()
        
        # Get teacher ID
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_id = cur.fetchone()[0]
        
        # Insert new class
        cur.execute("""
            INSERT INTO classes (teacher_id, name, description, class_code, code_expires)
            VALUES (%s, %s, %s, %s, %s)
        """, (teacher_id, name, description, code, code_expires))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({
            'success': 'Class created successfully!',
            'class_code': code,
            'expires': code_expires.strftime('%Y-%m-%d %H:%M:%S')
        }), 200
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500


@teacher_bp.route('/class/<int:class_id>/regenerate_code', methods=['POST'])
def regenerate_class_code(class_id):
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401
    
    try:

        import random
        import string
        from datetime import datetime, timedelta
        
        new_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        new_expires = datetime.now() + timedelta(days=7)
        
        cur = mysql.connection.cursor()
        
        # Verify the teacher owns this class
        cur.execute("SELECT teacher_id FROM classes WHERE id=%s", (class_id,))
        class_info = cur.fetchone()
        
        if not class_info:
            return jsonify({'error': 'Class not found'}), 404
        
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_id = cur.fetchone()[0]
        
        if class_info[0] != teacher_id:
            return jsonify({'error': 'Unauthorized access'}), 403
        
        # Update the class code
        cur.execute("""
            UPDATE classes 
            SET class_code=%s, code_expires=%s 
            WHERE id=%s
        """, (new_code, new_expires, class_id))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({
            'success': 'Class code regenerated!',
            'class_code': new_code,
            'expires': new_expires.strftime('%Y-%m-%d %H:%M:%S')
        }), 200
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500


@teacher_bp.route('/class/<int:class_id>')
def view_class(class_id):
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    cur = mysql.connection.cursor()
    
    # Verify the teacher owns this class
    cur.execute("SELECT teacher_id FROM classes WHERE id=%s", (class_id,))
    class_info = cur.fetchone()
    
    if not class_info:
        flash('Class not found', 'error')
        return redirect(url_for('teacher.teacherClasses'))
    
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()[0]
    
    if class_info[0] != teacher_id:
        flash('Unauthorized access', 'error')
        return redirect(url_for('teacher.teacherClasses'))
    
    # Get class details
    cur.execute("""
        SELECT c.id, c.name, c.description, c.class_code, c.code_expires, c.created_at
        FROM classes c
        WHERE c.id = %s
    """, (class_id,))
    
    class_data = cur.fetchone()
    
    # Get enrolled students
    cur.execute("""
        SELECT u.id, u.username, u.first_name, u.last_name, e.enrolled_at
        FROM enrollments e
        JOIN users u ON e.student_id = u.id
        WHERE e.class_id = %s
        ORDER BY u.first_name, u.last_name
    """, (class_id,))
    
    students = cur.fetchall()
    
    # Get class activities
    cur.execute("""
        SELECT id, title, due_date, created_at
        FROM activities
        WHERE class_id = %s
        ORDER BY due_date ASC
    """, (class_id,))
    
    activities = cur.fetchall()
    
    cur.close()
    
    class_dict = {
        'id': class_data[0],
        'name': class_data[1],
        'description': class_data[2],
        'class_code': class_data[3],
        'code_expires': class_data[4],
        'created_at': class_data[5]
    }
    
    students_list = []
    for student in students:
        students_list.append({
            'id': student[0],
            'username': student[1],
            'first_name': student[2],
            'last_name': student[3],
            'enrolled_at': student[4]
        })
    
    activities_list = []
    for activity in activities:
        activities_list.append({
            'id': activity[0],
            'title': activity[1],
            'due_date': activity[2],
            'created_at': activity[3]
        })
    
    return render_template('teacher_class_view.html',
                            class_data=class_dict,
                            students=students_list,
                            activities=activities_list,
                            first_name=session['first_name'])

# New route to delete enrolled students
@teacher_bp.route('/class/<int:class_id>/delete_students', methods=['POST'])
def delete_enrolled_students(class_id):
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    student_ids = request.form.getlist('student_ids')
    if not student_ids:
        flash('No students selected for deletion.', 'error')
        return redirect(url_for('teacher.view_class', class_id=class_id))

    cur = mysql.connection.cursor()

    # Verify the teacher owns this class
    cur.execute("SELECT teacher_id FROM classes WHERE id=%s", (class_id,))
    class_info = cur.fetchone()
    if not class_info:
        flash('Class not found', 'error')
        cur.close()
        return redirect(url_for('teacher.teacherClasses'))

    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()[0]

    if class_info[0] != teacher_id:
        flash('Unauthorized access', 'error')
        cur.close()
        return redirect(url_for('teacher.teacherClasses'))

    try:
        # Delete enrollments for selected students in this class
        format_strings = ','.join(['%s'] * len(student_ids))
        query = f"DELETE FROM enrollments WHERE class_id=%s AND student_id IN ({format_strings})"
        cur.execute(query, [class_id] + student_ids)
        mysql.connection.commit()
        flash(f'Successfully deleted {len(student_ids)} student(s) from the class.', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Failed to delete students: {str(e)}', 'error')
    finally:
        cur.close()

    return redirect(url_for('teacher.view_class', class_id=class_id))




@teacher_bp.route('/settings', methods=['GET', 'POST'])
def teacherSettings():
    if 'username' not in session or session.get('role') != 'teacher':
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
                return render_template('teacher_settings.html', user=user, errors=errors)


        # Password change validation
        if new_password or confirm_password:
            if not current_password:
                flash('Current password is required to change password.', 'error')
                return render_template('teacher_settings.html', user=user)
            if not check_password_hash(user['password'], current_password):
                flash('Current password is incorrect.', 'error')
                return render_template('teacher_settings.html', user=user)
            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'error')
                return render_template('teacher_settings.html', user=user)
            if len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'error')
                return render_template('teacher_settings.html', user=user)
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
            return redirect(url_for('teacher.teacherSettings'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Failed to update settings: {str(e)}', 'error')

    cur.close()
    return render_template('teacher_settings.html', user=user)

