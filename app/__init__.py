from flask import Flask
from flask_mysqldb import MySQL
import os

mysql = MySQL()

def create_app():
    app = Flask(__name__, static_folder='static')
    app.secret_key = os.urandom(24)

    # MySQL configuration
    app.config['MYSQL_HOST'] = 'localhost'
    app.config['MYSQL_USER'] = 'root'
    app.config['MYSQL_PASSWORD'] = '_Zac@110502'
    app.config['MYSQL_DB'] = 'c_insight_db'

    mysql.init_app(app)

    # Import and register Blueprints
    from routes.home import home_bp
    from routes.auth import auth_bp
    from routes.auth import teacher_bp
    from routes.auth import student_bp



    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(teacher_bp, url_prefix="/teacher")
    app.register_blueprint(student_bp)
    


    return app

