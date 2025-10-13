from flask import Blueprint, render_template, session, redirect, url_for


home_bp = Blueprint('home', __name__)


@home_bp.route('/')
@home_bp.route('/home')
def home():
    username = session.get('username')  # None if not logged in
    return render_template('home.html', username=username)


@home_bp.route('/health')
def health():
    """Health check endpoint for Railway"""
    return {'status': 'healthy'}, 200
