import os
from app import create_app, mysql

app = create_app()
application = app

@app.route('/test-db')
def test_db():
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT 1")
        result = cur.fetchone()
        cur.close()
        return f"Database connection successful: {result}"
    except Exception as e:
        return f"Database connection failed: {str(e)}"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)