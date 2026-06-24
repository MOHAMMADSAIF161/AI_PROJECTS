from dotenv import load_dotenv
load_dotenv()
import requests
import subprocess
import tempfile
import os
import PyPDF2
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from config import Config
from models import db, Student
from flask_bcrypt import Bcrypt
from ai import converse as chat, client, MODEL_NAME
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
resume_store = {}

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.from_object(Config)
db.init_app(app)
bcrypt = Bcrypt(app)
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)


@app.route('/run-code', methods=['POST'])
def run_code():
    data = request.json
    language = data['language']
    code = data['files'][0]['content']

    if language == 'python':
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                fname = f.name
            result = subprocess.run(['python', fname], capture_output=True, text=True, timeout=10)
            os.unlink(fname)
            return jsonify({'run': {'output': result.stdout, 'stderr': result.stderr}})
        except subprocess.TimeoutExpired:
            return jsonify({'run': {'output': '', 'stderr': 'Timed out!'}})
        except Exception as e:
            return jsonify({'run': {'output': '', 'stderr': str(e)}})

    if language == 'java':
        try:
            res = requests.post(
                'https://api.jdoodle.com/v1/execute',
                json={
                    'clientId': os.getenv('JDOODLE_CLIENT_ID'),
                    'clientSecret': os.getenv('JDOODLE_CLIENT_SECRET'),
                    'script': code,
                    'language': 'java',
                    'versionIndex': '4'
                },
                timeout=15
            )
            result = res.json()
            return jsonify({'run': {'output': result.get('output', ''), 'stderr': ''}})
        except Exception as e:
            return jsonify({'run': {'output': '', 'stderr': str(e)}})

    lang_map = {
        'c': ('c', '5'),
        'c++': ('cpp17', '1'),
        'cpp': ('cpp17', '1'),
        'javascript': ('nodejs', '4'),
    }

    lang_info = lang_map.get(language)
    if not lang_info:
        return jsonify({'run': {'output': '', 'stderr': f'Language {language} not supported'}})

    jdoodle_lang, version_index = lang_info

    try:
        res = requests.post(
            'https://api.jdoodle.com/v1/execute',
            json={
                'clientId': os.getenv('JDOODLE_CLIENT_ID'),
                'clientSecret':  os.getenv('JDOODLE_CLIENT_SECRET'),
                'script': code,
                'language': jdoodle_lang,
                'versionIndex': version_index
            },
            timeout=15
        )
        result = res.json()
        return jsonify({'run': {'output': result.get('output', ''), 'stderr': ''}})
    except Exception as e:
        return jsonify({'run': {'output': '', 'stderr': str(e)}})

@app.route('/upload-resume', methods=['POST'])
def upload_resume():
    print("Upload resume called!")  # ADD THIS
    print("Files:", request.files) 
    if 'resume' not in request.files:
        return jsonify({'error': 'No file uploaded'})
    file = request.files['resume']
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ''
        for page in pdf_reader.pages:
            text += page.extract_text()
        
        # Store in global dict using student id
        student_id = session.get('student_id')
        resume_store[student_id] = text
        print("Resume stored, length:", len(text))
        
        from ai import chat_history
        chat_history.clear()

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a professional interviewer. Briefly summarize the candidate's profile in 2 sentences and say you will ask questions based on their resume. Keep it short for voice."},
                {"role": "user", "content": f"Resume: {text[:1000]}"}
            ],
            max_tokens=100
        )
        message = response.choices[0].message.content.strip()
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        return jsonify({'error': str(e)})
@app.route('/')
def home():
    return render_template('welcome.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        existing = Student.query.filter_by(email=email).first()
        if existing:
            return 'Email already registered! <a href="/register">Try again</a>'
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        student = Student(name=name, email=email, password=hashed)
        db.session.add(student)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')
@app.route('/login/google')
def google_login():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/login/google/callback')
def google_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    email = user_info['email']
    name = user_info['name']
    student = Student.query.filter_by(email=email).first()
    if not student:
        student = Student(name=name, email=email, password=None)
        db.session.add(student)
        db.session.commit()
    session['student_id'] = student.id
    session['student_name'] = student.name
    return redirect(url_for('dashboard'))
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        student = Student.query.filter_by(email=email).first()
        if student and bcrypt.check_password_hash(student.password, password):
            session['student_id'] = student.id
            session['student_name'] = student.name
            return redirect(url_for('dashboard'))
        return 'Invalid credentials! <a href="/login">Try again</a>'
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'student_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', student_name=session['student_name'])

@app.route('/start', methods=['POST'])
def start():
    if 'student_id' not in session:
        return redirect(url_for('login'))
    return render_template('chat.html', student_name=session['student_name'])

@app.route('/chat', methods=['POST'])
def chat_route():
    data = request.json
    message = data['message']
    student_id = session.get('student_id')
    resume_text = resume_store.get(student_id, '')
    reply = chat(message, resume_text)
    return jsonify({'reply': reply})

@app.route('/dashboard-chat', methods=['POST'])
def dashboard_chat():
    data = request.json
    message = data['message']
    history = data.get('history', [])
    student_name = session.get('student_name', 'Student')
    
    DASHBOARD_PROMPT = f"""You are a helpful AI assistant like ChatGPT talking to {student_name}.
You can help with anything — answering questions, explaining concepts, writing, coding, math, science, history, and more.
Address the student by their name {student_name} occasionally to make it personal.
Be helpful, clear and conversational.
Keep responses concise since this is a voice chat — 2-3 sentences max."""

    messages = [{"role": "system", "content": DASHBOARD_PROMPT}]
    messages += history
    messages.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        max_tokens=200
    )
    reply = response.choices[0].message.content.strip()
    return jsonify({'reply': reply})
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

with app.app_context():
        db.create_all()
        print("Ready!")
if __name__ == '__main__':
    app.run(debug=True)