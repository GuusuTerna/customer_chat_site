from flask import session
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO, send
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'chat-site-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


def init_db():
    conn = sqlite3.connect('chat.db')
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
            username TEXT NOT NULL,
            text TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

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
            conn = sqlite3.connect('chat.db')
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

# === SOCKET EVENTS ===
@socketio.on('message')
def handle_message(data):
    user = data.get('user', 'Anonymous')
    text = data.get('text', '').strip()
    timestamp = datetime.now().strftime('%H:%M')
    full_msg = f"[{user}] {text} <span class='timestamp'>{timestamp}</span>"
    print(full_msg)
    send(full_msg, broadcast=True)

    # Save to DB
    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("INSERT INTO messages (username, text) VALUES (?, ?)", (user, text))
    conn.commit()
    conn.close()

@app.route('/join')
def join():
    return render_template('join.html')


@app.route('/admin')
def admin():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('chat.db')
    c = conn.cursor()
    c.execute("SELECT username, text FROM messages ORDER BY id DESC LIMIT 100")
    messages = c.fetchall()
    conn.close()
    return render_template('admin.html', messages=messages)



@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'admin' and password == 'password123':  # Replace with real credentials later
            session['admin_logged_in'] = True
            return redirect(url_for('admin'))
        else:
            flash('Invalid credentials')
            return redirect(url_for('admin_login'))
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))


if __name__ == '__main__':
    init_db()
    print("Running app with SocketIO...")
    PORT = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=PORT, allow_unsafe_werkzeug=True)
