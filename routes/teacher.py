from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app import mysql
from datetime import datetime
from flask import Flask
from flask_dance.contrib.google import make_google_blueprint
import os
from flask_dance.contrib.google import google
from flask import current_app as app
import MySQLdb
import random, string

teacher_bp = Blueprint('teacher', __name__)




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


    # Get teacher's classes
    cur.execute("SELECT id, name FROM classes WHERE teacher_id = %s ORDER BY name", (teacher_id,))
    classes = cur.fetchall()

    cur.execute("""
        SELECT  a.id, a.teacher_id, a.title, a.description, a.instructions,
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
        activities_list.append({
            'id': activity[0],
            'teacher_id': activity[1],
            'title': activity[2],
            'description': activity[3],
            'instructions': activity[4],
            'starter_code': activity[5],
            'due_date': activity[6],
            'correctness_weight': activity[7],
            'syntax_weight': activity[8],
            'logic_weight': activity[9],
            'similarity_weight': activity[10],
            'created_at': activity[11],
            'submission_count': activity[12],
            'class_name': activity[13] or 'N/A'
        })

    classes_list = [{'id': cls[0], 'name': cls[1]} for cls in classes]

    return render_template('teacher_activities.html', activities=activities_list, classes=classes_list)


@teacher_bp.route('/create_activity', methods=['POST'])
def create_activity():
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401

    try:
        #  Basic form fields
        class_id = request.form['class_id']
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

        return jsonify({
            'success': 'Activity created successfully!',
            'created_at': created_at.strftime("%Y-%m-%d %H:%M:%S")
        }), 200

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
                SELECT a.*, COUNT(s.id) AS submission_count, c.name AS class_name
                FROM activities a
                LEFT JOIN submissions s ON a.id = s.activity_id
                LEFT JOIN classes c ON a.class_id = c.id
                WHERE a.id = %s AND a.teacher_id = %s
                GROUP BY a.id
            """, (activity_id, teacher_id))

            activity = cur.fetchone()
            if not activity:
                return jsonify({'error': 'Activity not found'}), 404

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
                'class_name': activity[15] or 'N/A'
            }

            return jsonify(activity_dict)
        
        elif request.method == 'PUT':
            # Get form data
            class_id = request.form['class_id']
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

            # Update activity in database
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


@teacher_bp.route('/class/<int:class_id>/delete_student/<int:student_id>', methods=['POST'])
def delete_enrolled_student(class_id, student_id):
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor()

    try:
        # Verify the teacher owns this class
        cur.execute("SELECT teacher_id FROM classes WHERE id=%s", (class_id,))
        class_info = cur.fetchone()

        if not class_info:
            flash('Class not found', 'error')
            return redirect(url_for('teacher.view_class', class_id=class_id))

        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_id = cur.fetchone()[0]

        if class_info[0] != teacher_id:
            flash('Unauthorized access', 'error')
            return redirect(url_for('teacher.view_class', class_id=class_id))

        # Check if student is enrolled in this class
        cur.execute("""
            SELECT u.first_name, u.last_name FROM enrollments e
            JOIN users u ON e.student_id = u.id
            WHERE e.class_id = %s AND e.student_id = %s
        """, (class_id, student_id))

        student_info = cur.fetchone()

        if not student_info:
            flash('Student not enrolled in this class', 'error')
            return redirect(url_for('teacher.view_class', class_id=class_id))

        # Delete the enrollment
        cur.execute("DELETE FROM enrollments WHERE class_id = %s AND student_id = %s", (class_id, student_id))
        mysql.connection.commit()

        flash(f'Successfully removed {student_info[0]} {student_info[1]} from the class', 'success')

    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error removing student: {str(e)}', 'error')

    finally:
        cur.close()

    return redirect(url_for('teacher.view_class', class_id=class_id))