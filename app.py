import os
from flask import Flask

app = Flask(__name__)
application = app  # This line is crucial!


@app.route('/')
def home():
    return 'C-Insight is working!'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)