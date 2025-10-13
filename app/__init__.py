from flask import Flask
from flask_mysqldb import MySQL
from flask_dance.contrib.google import make_google_blueprint
import os
from dotenv import load_dotenv

load_dotenv()
mysql = MySQL()

def create_app():
    app = Flask(__name__, static_folder='static')
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = os.environ.get('OAUTHLIB_INSECURE_TRANSPORT', '0')

    # --- Google OAuth setup ---
    google_bp = make_google_blueprint(
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        scope=[
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid"
        ]
    )
    app.register_blueprint(google_bp, url_prefix="/login")

    from routes.auth import google_logged_in
    from flask_dance.consumer import oauth_authorized
    oauth_authorized.connect_via(google_bp)(google_logged_in)

    # --- MySQL (Private Railway Connection) ---
    app.config['MYSQL_HOST'] = os.environ.get('MYSQLHOST', 'mysql.railway.internal')
    app.config['MYSQL_USER'] = os.environ.get('MYSQLUSER')
    app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQLPASSWORD')
    app.config['MYSQL_DB'] = os.environ.get('MYSQLDATABASE')
    app.config['MYSQL_PORT'] = int(os.environ.get('MYSQLPORT', 3306))

    print("Using private Railway MySQL network:")
    print(f"Host: {app.config['MYSQL_HOST']}")
    print(f"Port: {app.config['MYSQL_PORT']}")
    print(f"User: {app.config['MYSQL_USER']}")
    print(f"DB: {app.config['MYSQL_DB']}")
    print("Attempting DB connection...")

    try:
        mysql.init_app(app)
        with app.app_context():
            cur = mysql.connection.cursor()
            cur.execute("SELECT 1;")
            print("Private MySQL connection successful!")
            cur.close()
    except Exception as e:
        print(" MySQL connection failed:", e)

    # --- Register blueprints ---
    from routes.home import home_bp
    from routes.auth import auth_bp
    from routes.teacher import teacher_bp
    from routes.student import student_bp
    from routes.admin import admin_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(teacher_bp, url_prefix="/teacher")
    app.register_blueprint(student_bp, url_prefix="/student")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    return app
