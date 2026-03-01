import sqlite3
import uuid
import datetime
import json
import os

DB_NAME = "study_guide.db"

def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, 
                  password TEXT,
                  display_name TEXT,
                  about TEXT,
                  strengths TEXT,
                  weaknesses TEXT,
                  total_tokens INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_notes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  note_date TEXT,
                  note_text TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (username) REFERENCES users(username))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS threads 
                 (id TEXT PRIMARY KEY, 
                  username TEXT, 
                  title TEXT, 
                  chat_mode TEXT DEFAULT 'study',
                  created_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  thread_id TEXT,
                  role TEXT,
                  content TEXT,
                  message_type TEXT DEFAULT 'text',
                  flashcards TEXT,
                  audio_path TEXT,
                  tokens_used INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (thread_id) REFERENCES threads(id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS uploaded_files
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT,
                  thread_id TEXT,
                  filename TEXT,
                  filepath TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (username) REFERENCES users(username),
                  FOREIGN KEY (thread_id) REFERENCES threads(id))''')
    
    conn.commit()
    conn.close()

def register_user(username, password):
    try:
        conn = get_conn()
        conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def verify_user(username, password):
    conn = get_conn()
    res = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
    conn.close()
    return res is not None

def get_user_profile(username):
    conn = get_conn()
    res = conn.execute("""SELECT username, display_name, about, strengths, weaknesses, total_tokens 
                          FROM users WHERE username=?""", (username,)).fetchone()
    conn.close()
    if res:
        return {
            "username": res[0],
            "display_name": res[1] or res[0],
            "about": res[2] or "",
            "strengths": res[3] or "",
            "weaknesses": res[4] or "",
            "total_tokens": res[5] or 0
        }
    return None

def update_user_profile(username, display_name, about, strengths, weaknesses):
    conn = get_conn()
    conn.execute("""UPDATE users SET display_name=?, about=?, strengths=?, weaknesses=? 
                    WHERE username=?""", (display_name, about, strengths, weaknesses, username))
    conn.commit()
    conn.close()

def add_user_tokens(username, tokens):
    conn = get_conn()
    conn.execute("UPDATE users SET total_tokens = total_tokens + ? WHERE username=?", (tokens, username))
    conn.commit()
    conn.close()

def get_user_notes(username):
    conn = get_conn()
    rows = conn.execute("""SELECT id, note_date, note_text FROM user_notes 
                           WHERE username=? ORDER BY note_date ASC""", (username,)).fetchall()
    conn.close()
    return [{"id": r[0], "date": r[1], "text": r[2]} for r in rows]

def add_user_note(username, note_date, note_text):
    conn = get_conn()
    conn.execute("INSERT INTO user_notes (username, note_date, note_text) VALUES (?, ?, ?)",
                 (username, note_date, note_text))
    conn.commit()
    conn.close()

def delete_user_note(note_id):
    conn = get_conn()
    conn.execute("DELETE FROM user_notes WHERE id=?", (note_id,))
    conn.commit()
    conn.close()

def create_thread_entry(username, thread_id, first_message, chat_mode="study"):
    conn = get_conn()
    title = (first_message[:30] + '...') if len(first_message) > 30 else first_message
    conn.execute("INSERT OR IGNORE INTO threads VALUES (?, ?, ?, ?, ?)", 
                 (thread_id, username, title, chat_mode, datetime.datetime.now()))
    conn.commit()
    conn.close()

def get_user_threads(username):
    conn = get_conn()
    threads = conn.execute("""SELECT id, title, chat_mode FROM threads 
                              WHERE username=? ORDER BY created_at DESC""", (username,)).fetchall()
    conn.close()
    return [{"id": t[0], "title": t[1], "mode": t[2] or "study"} for t in threads]

def update_thread_title(thread_id, new_title):
    conn = get_conn()
    conn.execute("UPDATE threads SET title=? WHERE id=?", (new_title, thread_id))
    conn.commit()
    conn.close()

def delete_thread_entry(thread_id):
    conn = get_conn()
    # Delete associated voice files
    rows = conn.execute("SELECT audio_path FROM messages WHERE thread_id=?", (thread_id,)).fetchall()
    for row in rows:
        if row[0] and os.path.exists(row[0]):
            os.remove(row[0])
    
    # Delete associated PDF files
    rows = conn.execute("SELECT filepath FROM uploaded_files WHERE thread_id=?", (thread_id,)).fetchall()
    for row in rows:
        if row[0] and os.path.exists(row[0]):
            os.remove(row[0])
            
    conn.execute("DELETE FROM uploaded_files WHERE thread_id=?", (thread_id,))
    conn.execute("DELETE FROM messages WHERE thread_id=?", (thread_id,))
    conn.execute("DELETE FROM threads WHERE id=?", (thread_id,))
    conn.commit()
    conn.close()

def save_message(thread_id, role, content, message_type="text", flashcards=None, audio_path=None, tokens_used=0):
    conn = get_conn()
    flashcards_json = json.dumps(flashcards) if flashcards else None
    conn.execute("""INSERT INTO messages (thread_id, role, content, message_type, flashcards, audio_path, tokens_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                 (thread_id, role, content, message_type, flashcards_json, audio_path, tokens_used))
    conn.commit()
    conn.close()

def get_thread_messages(thread_id):
    conn = get_conn()
    rows = conn.execute("""SELECT role, content, message_type, flashcards, audio_path 
                           FROM messages WHERE thread_id=? ORDER BY created_at ASC""", (thread_id,)).fetchall()
    conn.close()
    messages = []
    for r in rows:
        msg = {"role": r[0], "content": r[1], "type": r[2]}
        if r[3]:
            msg["flashcards"] = json.loads(r[3])
        if r[4]:
            msg["audio_path"] = r[4]
        messages.append(msg)
    return messages

def save_uploaded_file(username, filename, filepath, thread_id=None):
    conn = get_conn()
    conn.execute("INSERT INTO uploaded_files (username, thread_id, filename, filepath) VALUES (?, ?, ?, ?)",
                 (username, thread_id, filename, filepath))
    conn.commit()
    conn.close()

def delete_uploaded_file_by_id(file_id):
    conn = get_conn()
    row = conn.execute("SELECT filepath FROM uploaded_files WHERE id=?", (file_id,)).fetchone()
    if row and row[0]:
        if os.path.exists(row[0]):
            os.remove(row[0])
    conn.execute("DELETE FROM uploaded_files WHERE id=?", (file_id,))
    conn.commit()
    conn.close()

def get_user_files(username, thread_id=None):
    conn = get_conn()
    if thread_id:
        rows = conn.execute("""SELECT id, filename, filepath FROM uploaded_files 
                               WHERE username=? AND thread_id=? ORDER BY created_at DESC""", (username, thread_id)).fetchall()
    else:
        # On new chat (thread_id=None), we only want files that aren't attached to any thread yet
        rows = conn.execute("""SELECT id, filename, filepath FROM uploaded_files 
                               WHERE username=? AND thread_id IS NULL ORDER BY created_at DESC""", (username,)).fetchall()
    conn.close()
    return [{"id": r[0], "filename": r[1], "filepath": r[2]} for r in rows]

def delete_uploaded_file(file_id):
    conn = get_conn()
    row = conn.execute("SELECT filepath FROM uploaded_files WHERE id=?", (file_id,)).fetchone()
    if row and row[0]:
        import os
        if os.path.exists(row[0]):
            os.remove(row[0])
    conn.execute("DELETE FROM uploaded_files WHERE id=?", (file_id,))
    conn.commit()
    conn.close()

def get_thread_files(thread_id):
    conn = get_conn()
    rows = conn.execute("""SELECT id, filename, filepath FROM uploaded_files 
                           WHERE thread_id=? ORDER BY created_at DESC""", (thread_id,)).fetchall()
    conn.close()
    return [{"id": r[0], "filename": r[1], "filepath": r[2]} for r in rows]

init_db()
