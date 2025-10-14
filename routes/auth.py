from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app import mysql
from flask_dance.contrib.google import google
import MySQLdb
from .admin import add_admin_notification


auth_bp = Blueprint('auth', __name__)
teacher_bp = Blueprint('teacher', __name__)
student_bp = Blueprint('student', __name__)



@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()

        # Check for case-insensitive username match
        cur.execute("SELECT username FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
        user_case_insensitive = cur.fetchone()

        if not user_case_insensitive:
            cur.close()
            flash('Invalid Username or Password', 'error')
            user = {
                'theme': session.get('theme', 'light')
            }
            return render_template('login.html', user=user)

        # Check if exact case matches
        if user_case_insensitive['username'] != username:
            cur.close()
            flash('Unauthorized access: Username Mismatch', 'error')
            user = {
                'theme': session.get('theme', 'light')
            }
            return render_template('login.html', user=user)

        # Fetch full user record with exact username
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user['password'], password):
            session['username'] = username
            session['first_name'] = user['first_name']
            session['last_name'] = user['last_name']
            session['role'] = user['role']

            if user['role'] == 'teacher':
                return redirect(url_for('teacher.teacherDashboard'))
            elif user['role'] == 'student':
                return redirect(url_for('student.studentDashboard'))
            elif user['role'] == 'admin':
                return redirect(url_for('admin.adminDashboard'))
            else:
                return redirect(url_for('home.home'))
        else:
            flash('Invalid Username or Password', 'error')
    user = {
        'theme': session.get('theme', 'light')  # or just 'light' if you don't store theme in session yet
    }
    return render_template('login.html', user=user)

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
        first_name = request.form['first_name']  
        last_name = request.form['last_name']    
        role = request.form['role']
        
        hashed_password = generate_password_hash(password)
        
        cur = mysql.connection.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password, first_name, last_name, role) VALUES (%s, %s, %s, %s, %s)",
                (username, hashed_password, first_name, last_name, role)
            )

            # Notify admins about new user registration
            message = f"New user registered: {first_name} {last_name} ({username}), Role: {role}."
            cur.execute("SELECT id FROM users WHERE role='admin'")
            admins = cur.fetchall()
            for (admin_id,) in admins:
                cur.execute("""
                    INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
                    VALUES (%s, 'admin', %s, %s, %s, FALSE, NOW())
                """, (admin_id, 'user_created', message, None))

            mysql.connection.commit()

            flash('Registration successful. Please login.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Registration failed. Error: {str(e)}', 'error')
        finally:
            cur.close()
    user = {
        'theme': session.get('theme', 'light')
    }
    return render_template('register.html', user=user)



@auth_bp.route('/profile')
def user_profile():
    if 'username' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute(
        "SELECT username, first_name, last_name, role, email FROM users WHERE username = %s",
        (session['username'],)
    )
    user = cur.fetchone()
    cur.close()

    if not user:
        flash('User  not found', 'error')
        return redirect(url_for('auth.login'))

    full_name = f"{user['first_name']} {user['last_name']}"

    # Render different templates or pass role to template
    if user['role'] == 'teacher':
        template = 'teacher_profile.html'
    elif user['role'] == 'student':
        template = 'student_profile.html'
    elif user['role'] == 'admin':
        template = 'admin_profile.html'
    else:
        # fallback or error
        flash('Invalid user role', 'error')
        return redirect(url_for('auth.login'))

    return render_template(template, user=user, full_name=full_name)


# Handle Google OAuth authorization
def google_logged_in(blueprint, token):
    from flask import current_app
    if not token:
        flash("Failed to log in with Google.", "error")
        return False

    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Failed to fetch user info from Google", "danger")
        return False

    user_info = resp.json()
    email = user_info["email"]
    first_name = user_info.get("given_name", "")
    last_name = user_info.get("family_name", "")
    google_id = user_info.get("id")
    username = user_info.get("name", email.split("@")[0]).replace(" ", "").lower()

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()

    if user:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["first_name"] = user.get("first_name", "")
        session["last_name"] = user.get("last_name", "")
        flash(f"Welcome back, {user['first_name']}!", "success")
        cursor.close()

        if user["role"] == "teacher":
            return redirect(url_for("teacher.teacherDashboard"))
        else:
            return redirect(url_for("student.studentDashboard"))

    else:
        session["google_temp"] = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "google_id": google_id,
            "username": username
        }
        flash("Please complete registration to continue.", "info")
        cursor.close()
        return redirect(url_for("auth.google_register"))

# --- Registration for Google  ---
@auth_bp.route("/google/register", methods=["GET", "POST"])
def google_register():
    if "google_temp" not in session:
        flash("Google session expired. Please login again.", "warning")
        return redirect(url_for("auth.login"))

    data = session["google_temp"]

    if request.method == "POST":
        role = request.form["role"]
        password = request.form.get("password")

        if not password or len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("google_register.html", data=data)
        
        hashed_password = generate_password_hash(password)

        cursor = None
        user = None
        try:
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
            cursor.execute("""
                INSERT INTO users (username, email, password, first_name, last_name, role, provider, provider_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (data["email"], data["email"], hashed_password, data["first_name"], data["last_name"],
                role, "google", data["google_id"]))
            mysql.connection.commit()
        
            cursor.execute("SELECT * FROM users WHERE email=%s", (data["email"],))
            user = cursor.fetchone()

            
        except Exception as e:
            mysql.connection.rollback()
            flash(f"Registration failed: {str(e)}", "error")
            return render_template("google_register.html", data=data)
        finally:
            if cursor is not None:
                cursor.close()
        
        if user is None:
            flash("User  registration failed, please try again.", "error")
            return render_template("google_register.html", data=data)


        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["first_name"] = user.get("first_name", "")
        session["last_name"] = user.get("last_name", "")

        # Notify admins about new user registration
        message = f"New user registered: {data['first_name']} {data['last_name']} ({data['username']}), Role: {role}."
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT id FROM users WHERE role='admin'")
        admins = cursor.fetchall()
        for (admin_id,) in admins:
            cursor.execute("""
                INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
                VALUES (%s, 'admin', %s, %s, %s, FALSE, NOW())
            """, (admin_id, 'user_created', message, None))
        mysql.connection.commit()
        cursor.close()

        print("Registration successful, redirecting now...")
        flash("Registration complete. Logged in successfully!", "success")
        session.pop("google_temp")

        if role == "teacher":
            return redirect(url_for("teacher.teacherDashboard"))
        else:
            return redirect(url_for("student.studentDashboard"))

    # GET request → show form
    user = {
        'theme': session.get('theme', 'light')
    }
    return render_template('google_register.html', data=data, user=user)

