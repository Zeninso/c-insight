from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app import mysql

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
    return render_template('teacher_Dashboard.html', username=session['username'])


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
        