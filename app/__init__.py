from flask import Flask
from flask_mysqldb import MySQL
from flask_dance.contrib.google import make_google_blueprint, google
import os

mysql = MySQL()

def create_app():
    app = Flask(__name__, static_folder='static')
    app.secret_key = "490893083299-jh7uqq99e8a96lb8dihmjmgieb5que7e.apps.googleusercontent.com"

    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # only for development

    # ✅ Register Google OAuth blueprint
    google_bp = make_google_blueprint(
        client_id="490893083299-21dn9iqobkjgar8h482g5814qavogf78.apps.googleusercontent.com",
        client_secret="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",
        scope=[
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid"
        ],
        redirect_to="auth.google_callback"  # your route function name
    )
    app.register_blueprint(google_bp, url_prefix="/login")

    # MySQL configuration
    app.config['MYSQL_HOST'] = 'localhost'
    app.config['MYSQL_USER'] = 'root'
    app.config['MYSQL_PASSWORD'] = 'Letsfuckingcode'
    app.config['MYSQL_DB'] = 'c_insight_db'

    mysql.init_app(app)

    from routes.home import home_bp
    from routes.auth import auth_bp
    from routes.auth import teacher_bp
    from routes.auth import student_bp



    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(teacher_bp, url_prefix="/teacher")
    app.register_blueprint(student_bp)

    


    return app

