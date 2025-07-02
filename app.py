from flask import session, Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO, send, join_room
from datetime import datetime
import sqlite3
import os
from werkzeug.utils import secure_filename

# === Upload Config ===
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2MB

# === Flask App Setup ===
app = Flask(__name__)
app.secret_key = 'chat-site-secret-key'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

DB_FILE = 'chat_v2.db'


# === Helper Functions ===
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            text TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    c.execute("SELECT * FROM admins WHERE username = ?", ('admin',))
    if not c.fetchone():
        c.execute("INSERT INTO admins (username, password) VALUES (?, ?)", ('admin', 'admin123'))
    conn.commit()
    conn.close()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# === Routes ===
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form['email'].strip()
    wants_newsletter = request.form.get('newsletter') == 'on'

    if not email:
        flash('Please enter a valid email.')
        return redirect(url_for('index'))

    if wants_newsletter:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("INSERT INTO subscribers (email) VALUES (?)", (email,))
            conn.commit()
            conn.close()
            flash('✅ Subscribed successfully!')
        except sqlite3.IntegrityError:
            flash('⚠️ You\'re already subscribed.')
    else:
        flash('📬 Email saved, but newsletter not selected.')

    return redirect(url_for('index'))


@app.route('/join')
def join():
    return render_template('join.html')


@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if request.method == 'POST':
        username = request.form['username'].strip()
        if not username:
            flash("Please enter a valid name.")
            return redirect(url_for('join'))
        session['username'] = username
        return render_template('chat.html', username=username)
    else:
        if 'username' not in session:
            return redirect(url_for('join'))
        return render_template('chat.html', username=session['username'])


@app.route('/adminlogin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT * FROM admins WHERE username = ? AND password = ?", (username, password))
        admin = c.fetchone()
        conn.close()

        if admin:
            session['is_admin'] = True
            return redirect(url_for('admin'))
        else:
            flash('❌ Invalid credentials.')
            return redirect(url_for('admin_login'))

    return render_template('admin_login.html')


@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    session.pop('username', None)
    flash("You have been logged out.")
    return redirect(url_for('admin_login'))


@app.route('/admin')
def admin():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT DISTINCT sender FROM messages WHERE receiver = 'admin'")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return render_template('admin.html', users=users)


@app.route('/admin/chat/<username>')
def view_user_chat(username):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT sender, text, timestamp FROM messages
        WHERE (sender = ? AND receiver = 'admin') OR (sender = 'admin' AND receiver = ?)
        ORDER BY timestamp ASC
    """, (username, username))
    messages = c.fetchall()
    conn.close()
    return render_template('admin_chat.html', messages=messages, target=username)


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return {'success': False, 'error': 'No file part'}

    file = request.files['file']
    if file.filename == '':
        return {'success': False, 'error': 'No selected file'}

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file.save(filepath)

        file_url = url_for('static', filename='uploads/' + filename)
        return {'success': True, 'url': file_url}
    else:
        return {'success': False, 'error': 'Invalid file type or size too large'}


# === SOCKET.IO EVENTS ===
@socketio.on('join')
def handle_join(data):
    room = data.get('room')
    if room:
        join_room(room)
        print(f"{room} joined room")


@socketio.on('message')
def handle_message(data):
    sender = data.get('sender', 'Anonymous').strip()
    receiver = data.get('receiver', 'admin').strip()
    text = data.get('text', '').strip()
    timestamp = datetime.now().strftime('%H:%M')

    if not sender or not receiver or not text:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender, receiver, text) VALUES (?, ?, ?)",
              (sender, receiver, text))
    conn.commit()
    conn.close()

    socketio.emit('message', {
        'user': sender.capitalize() if sender.lower() == 'admin' else sender,
        'to': receiver,
        'text': text,
        'timestamp': timestamp
    }, room=receiver if receiver != 'admin' else sender)


@socketio.on('admin_reply')
def handle_admin_reply(data):
    to_user = data.get('to')
    text = data.get('text', '').strip()
    timestamp = datetime.now().strftime('%H:%M')

    if not to_user or not text:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender, receiver, text) VALUES (?, ?, ?)",
              ('admin', to_user, text))
    conn.commit()
    conn.close()

    socketio.emit('message', {
        'user': 'Admin',
        'to': to_user,
        'text': text,
        'timestamp': timestamp
    }, room=to_user)


@socketio.on('image')
def handle_image(data):
    sender = data.get('sender')
    receiver = data.get('receiver')
    image_url = data.get('url')
    timestamp = datetime.now().strftime('%H:%M')

    if not sender or not receiver or not image_url:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender, receiver, text) VALUES (?, ?, ?)",
              (sender, receiver, image_url))
    conn.commit()
    conn.close()

    socketio.emit('message', {
        'user': 'Admin' if sender.lower() == 'admin' else sender,
        'to': receiver,
        'text': image_url,
        'timestamp': timestamp,
        'is_image': True
    }, room=receiver if receiver != 'admin' else sender)


@socketio.on('load_history')
def handle_load_history(data):
    username = data.get('username')
    if not username:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT sender, text FROM messages
        WHERE (sender = ? AND receiver = 'admin')
           OR (sender = 'admin' AND receiver = ?)
        ORDER BY timestamp ASC
    """, (username, username))
    rows = c.fetchall()
    conn.close()

    messages = []
    for sender, text in rows:
        user = 'Admin' if sender.lower() == 'admin' else sender
        is_image = text.startswith('/static/uploads/')
        messages.append({'user': user, 'text': text, 'is_image': is_image})

    socketio.emit('history', {'messages': messages})


if __name__ == '__main__':
    init_db()
    print("Running app with SocketIO...")
    PORT = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=PORT, allow_unsafe_werkzeug=True)
