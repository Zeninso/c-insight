from flask import Flask
from flask_mysqldb import MySQL
from flask_dance.contrib.google import make_google_blueprint
import os

mysql = MySQL()

def create_app():
    app = Flask(__name__, static_folder='static')
    app.secret_key = os.environ.get('FLASK_SECRET_KEY')  # Use a proper secret key

    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = os.environ.get('OAUTHLIB_INSECURE_TRANSPORT', '1')  # only for development

    # Register Google OAuth blueprint
    google_bp = make_google_blueprint(
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        scope=[
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid"
        ],
        redirect_to="auth.google_callback"
    )
    app.register_blueprint(google_bp, url_prefix="/login")

    # MySQL configuration
    app.config['MYSQL_HOST'] = os.environ.get('MYSQL_HOST')
    app.config['MYSQL_USER'] = os.environ.get('MYSQL_USER')
    app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQL_PASSWORD')
    app.config['MYSQL_DB'] = os.environ.get('MYSQL_DB')
    app.config['MYSQL_UNIX_SOCKET'] = None



    mysql.init_app(app)

    # Imported blueprints from routes
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