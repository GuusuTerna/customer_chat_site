from flask import session, Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO, join_room, emit
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'chat-site-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

DB_FILE = 'chat_v2.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS subscribers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT NOT NULL,
        receiver TEXT NOT NULL,
        text TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL)''')
    c.execute("SELECT * FROM admins WHERE username = ?", ('admin',))
    if not c.fetchone():
        c.execute("INSERT INTO admins (username, password) VALUES (?, ?)", ('admin', 'admin123'))
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
    elif wants_newsletter:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("INSERT INTO subscribers (email) VALUES (?)", (email,))
            conn.commit()
            flash('✅ Subscribed successfully!')
        except sqlite3.IntegrityError:
            flash('⚠️ You\'re already subscribed.')
        finally:
            conn.close()
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
        WHERE sender = ? AND receiver = 'admin'
        UNION
        SELECT sender, text, timestamp FROM messages
        WHERE sender = 'admin' AND receiver = ?
        ORDER BY timestamp ASC
    """, (username, username))
    messages = c.fetchall()
    conn.close()
    return render_template('admin_chat.html', messages=messages, target=username)

# === SOCKET EVENTS ===

@socketio.on('join')
def handle_join(data):
    room = data.get('room')
    if room:
        join_room(room)

@socketio.on('message')
def handle_message(data):
    sender = data.get('sender')
    receiver = data.get('receiver')
    text = data.get('text', '')
    timestamp = datetime.now().strftime('%H:%M')

    if not sender or not receiver or not text:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender, receiver, text, timestamp) VALUES (?, ?, ?, ?)",
              (sender, receiver, text, timestamp))
    conn.commit()
    conn.close()

    socketio.emit('message', {
        'user': sender,
        'to': receiver,
        'text': text,
        'timestamp': timestamp
    }, room=receiver if receiver != 'admin' else sender)

@socketio.on('admin_reply')
def handle_admin_reply(data):
    to_user = data.get('to')
    text = data.get('text')
    timestamp = datetime.now().strftime('%H:%M')

    if not to_user or not text:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender, receiver, text, timestamp) VALUES (?, ?, ?, ?)",
              ('admin', to_user, text, timestamp))
    conn.commit()
    conn.close()

    socketio.emit('message', {
        'user': 'Admin',
        'to': to_user,
        'text': text,
        'timestamp': timestamp
    }, room=to_user)

@socketio.on('load_history')
def handle_load_history(data):
    username = data.get('username')
    if not username:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT sender, text FROM messages
        WHERE (sender = ? AND receiver = 'admin') OR (sender = 'admin' AND receiver = ?)
        ORDER BY timestamp ASC
    """, (username, username))
    messages = [{'user': 'Admin' if row[0] == 'admin' else row[0], 'text': row[1]} for row in c.fetchall()]
    conn.close()
    emit('history', {'messages': messages})
    
if __name__ == '__main__':
    init_db()
    PORT = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=PORT, allow_unsafe_werkzeug=True)
