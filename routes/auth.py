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

app = Flask(__name__)
app.secret_key = os.environ.get("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", "dev")


auth_bp = Blueprint('auth', __name__)
teacher_bp = Blueprint('teacher', __name__)
student_bp = Blueprint('student', __name__)



@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        # Case-insensitive search for username
        cur.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(%s)", (username.lower(),))
        user = cur.fetchone()
        cur.close()

        if user:
            # Check if username case matches exactly
            if user[1] != username:
                flash('Unauthorized access: Username case mismatch', 'error')
                return render_template('login.html')
            # Check password
            if check_password_hash(user[2], password):
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
            mysql.connection.commit()
            flash('Registration successful. Please login.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Registration failed. Error: {str(e)}', 'error')
        finally:
            cur.close()
    
    return render_template('register.html')




# --- Google login start ---
@auth_bp.route("/google")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))  # this triggers Flask-Dance flow
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Failed to fetch user info from Google", "danger")
        return redirect(url_for("auth.login"))

    user_info = resp.json()
    email = user_info["email"]
    name = user_info.get("name", email.split("@")[0])

    # check if user already exists in DB
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()

    if not user:
        # if not found, create new user
        username = name.replace(" ", "").lower()
        # ensure uniqueness by adding random chars
        username += ''.join(random.choices(string.ascii_lowercase, k=3))

        cursor.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (username, email, None)   # password = None since Google login
        )
        app.mysql.connection.commit()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

    # log the user in
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    flash("Logged in with Google as {}".format(user["username"]), "success")
    return redirect(url_for("teacher.teacherDashboard"))


@auth_bp.route("/google/authorized")
def google_authorized():
    # Flask-Dance handles this internally, we just redirect
    return redirect(url_for("auth.google_login"))


# --- Google Login Flow ---
@auth_bp.route("/google/callback")
def google_callback():
    if not google.authorized:
        return redirect(url_for("google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Failed to fetch user info from Google", "danger")
        return redirect(url_for("auth.login"))

    user_info = resp.json()
    print("DEBUG: Google user info:", user_info)
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
        return redirect(url_for("auth.google_register"))

# --- Registration after Google Login ---
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

        print("Registration successful, redirecting now...")
        flash("Registration complete. Logged in successfully!", "success")
        session.pop("google_temp")

        if role == "teacher":
            return redirect(url_for("teacher.teacherDashboard"))
        else:
            return redirect(url_for("student.studentDashboard"))

    # GET request → show form
    return render_template("google_register.html", data=data)