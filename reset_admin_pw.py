# reset_admin_pw.py
import sqlite3
from pathlib import Path
from datetime import datetime
from passlib.context import CryptContext

APP_DIR = Path.home() / ".ayurprakriti_app"
DB_PATH = APP_DIR / "ayurprakriti.db"

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

username = "admin"
new_plain = "admin123"
new_hash = pwd_context.hash(new_plain)

# Check if admin exists
cur.execute("SELECT id, username, display_name FROM users WHERE username=?", (username,))
r = cur.fetchone()
if r:
    cur.execute("UPDATE users SET password_hash=?, created_at=? WHERE username=?", (new_hash, datetime.now().isoformat(), username))
    conn.commit()
    print("Password reset for user 'admin' -> 'admin123' (hashed).")
else:
    # create admin if missing
    cur.execute("INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                (username, "Administrator", new_hash, "admin", datetime.now().isoformat()))
    conn.commit()
    print("Admin user created with password 'admin123'.")
conn.close()
