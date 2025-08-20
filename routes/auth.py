from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app import mysql
from datetime import datetime



auth_bp = Blueprint('auth', __name__)
teacher_bp = Blueprint('teacher', __name__)
student_bp = Blueprint('student', __name__)



@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()
        
        if user and check_password_hash(user[2], password):
            session['username'] = username
            session['first_name'] = user[3]  
            session['last_name'] = user[4]  
            session['role'] = user[5] 
                                
            if user[5] == 'teacher':
                return redirect(url_for('teacher.teacherDashboard'))
            elif user[5] == 'student':
                return redirect(url_for('student.studentDashboard'))
            else:
                return redirect(url_for('home.home'))
        else:
            flash('Invalid Username or Password', 'error')
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logout successfully', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        first_name = request.form['first_name']  # New field
        last_name = request.form['last_name']    # New field
        role = request.form['role']
        
        hashed_password = generate_password_hash(password)
        
        cur = mysql.connection.cursor()
        try:
            # Updated INSERT query to include first_name & last_name
            cur.execute(
                "INSERT INTO users (username, password, first_name, last_name, role) VALUES (%s, %s, %s, %s, %s)",
                (username, hashed_password, first_name, last_name, role)
            )
            mysql.connection.commit()
            flash('Registration successful. Please login.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Registration failed. Error: {str(e)}', 'error')
        finally:
            cur.close()
    
    return render_template('register.html')


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

    # Explicitly select all required columns (not a.* to avoid confusion)
    cur.execute("""
        SELECT  a.id, a.teacher_id, a.title, a.description, a.instructions,
                a.starter_code, a.due_date, a.correctness_weight, a.syntax_weight,
                a.logic_weight, a.similarity_weight, a.created_at,
                COUNT(s.id) AS submission_count
        FROM activities a
        LEFT JOIN submissions s ON a.id = s.activity_id
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
            'submission_count': activity[12]
        })

    return render_template('teacher_activities.html', activities=activities_list)



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


@teacher_bp.route('/create_activity', methods=['POST'])
def create_activity():
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401

    try:
        #  Basic form fields
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

        # Convert to dict { "Correctness": 50, "Syntax": 20, ... }
        rubrics = {}
        for name, weight in zip(rubric_names, rubric_weights):
            rubrics[name.strip()] = int(weight)

        #  Ensure the 4 required rubrics exist
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
                teacher_id, title, description, instructions,
                starter_code, due_date, correctness_weight,
                syntax_weight, logic_weight, similarity_weight, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            teacher_id, title, description, instructions,
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
    
    # Get teacher ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_row = cur.fetchone()
    if not teacher_row:
        return jsonify({'error': 'Teacher not found'}), 404
    teacher_id = teacher_row[0]
    
    if request.method == 'GET':
        # Get activity details
        cur.execute("""
            SELECT a.*, COUNT(s.id) AS submission_count
            FROM activities a
            LEFT JOIN submissions s ON a.id = s.activity_id
            WHERE a.id = %s AND a.teacher_id = %s
            GROUP BY a.id
        """, (activity_id, teacher_id))
        
        activity = cur.fetchone()
        if not activity:
            return jsonify({'error': 'Activity not found'}), 404
        
        # Convert to dict
        activity_dict = {
            'id': activity[0],
            'teacher_id': activity[1],
            'title': activity[2],
            'description': activity[3],
            'instructions': activity[4],
            'starter_code': activity[5],
            'due_date': activity[6].strftime('%Y-%m-%d %H:%M:%S') if activity[6] else None,
            'correctness_weight': activity[7],
            'syntax_weight': activity[8],
            'logic_weight': activity[9],
            'similarity_weight': activity[10],
            'created_at': activity[11].strftime('%Y-%m-%d %H:%M:%S') if activity[11] else None,
            'submission_count': activity[12]
        }
        
        return jsonify(activity_dict)
    
    elif request.method == 'PUT':
        try:
            # Get form data
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
            
            # Convert to dict { "Correctness": 50, "Syntax": 20, ... }
            rubrics = {}
            for name, weight in zip(rubric_names, rubric_weights):
                rubrics[name.strip()] = int(weight)
            
            # Ensure the 4 required rubrics exist
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
                SET title=%s, description=%s, instructions=%s, starter_code=%s, 
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
            
        except Exception as e:
            mysql.connection.rollback()
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
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
    

        


