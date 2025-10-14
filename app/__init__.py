from flask import Flask
from flask_mysqldb import MySQL
from flask_dance.contrib.google import make_google_blueprint
import os
from dotenv import load_dotenv
import time

# Load environment variables from .env
load_dotenv()

# Initialize MySQL (will be attached to app later)
mysql = MySQL()

def create_app():
    app = Flask(__name__, static_folder='app/static', template_folder='app/templates')

    # Secret key
    app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

    # --- MySQL Railway Config ---
    app.config['MYSQL_HOST'] = os.environ.get('MYSQLHOST')            # Railway host
    app.config['MYSQL_USER'] = os.environ.get('MYSQLUSER')            # Railway username
    app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQLPASSWORD')    # Railway password
    app.config['MYSQL_DB'] = os.environ.get('MYSQLDATABASE')          # Railway database
    app.config['MYSQL_PORT'] = int(os.environ.get('MYSQLPORT', 3306)) # Railway port
    app.config['MYSQL_CURSORCLASS'] = 'DictCursor'                    # return dict instead of tuple
    app.config['MYSQL_USE_UNICODE'] = True                             # REQUIRED for Flask-MySQLdb

    # Attach MySQL to app
    mysql.init_app(app)

    # --- Google OAuth setup ---
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = os.environ.get('OAUTHLIB_INSECURE_TRANSPORT', '0')
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

    # Connect Flask-Dance signal for Google login
    from routes.auth import google_logged_in
    from flask_dance.consumer import oauth_authorized
    oauth_authorized.connect_via(google_bp)(google_logged_in)

    # --- Register Blueprints ---
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
