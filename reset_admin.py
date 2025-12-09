# reset_admin.py
# Save this file in your project folder and run with:
#    python .\reset_admin.py

import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

# Candidate DB locations (checks these, first that exists will be used)
candidates = [
    Path.home() / ".ayurprakriti_app" / "ayurprakriti.db",
    Path("ayurprakriti.db"),
    Path.cwd() / "ayurprakriti.db",
]

DB_PATH = None
for p in candidates:
    if p.exists():
        DB_PATH = p
        break

# If not found, default to first candidate (script will create DB path when inserting)
DB_PATH = DB_PATH or candidates[0]
print("Using DB:", DB_PATH)

# New admin password you want (change here if you want a different one)
password = "admin123"

# Create hash using passlib if available, else pbkdf2 fallback
try:
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    hashed = pwd_context.hash(password)
    used = "passlib (bcrypt)"
except Exception:
    # fallback - stable pbkdf2 hash
    salt = b"ayur_salt_v2"
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000)
    hashed = dk.hex()
    used = "pbkdf2_hmac(sha256) fallback"

print("Hash method:", used)

# ensure parent dir exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

# Ensure users table exists (create simple schema if missing)
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    display_name TEXT,
    password_hash TEXT,
    role TEXT,
    created_at TEXT
)
""")

# Update existing admin or insert
cur.execute("SELECT id FROM users WHERE username = ?", ("admin",))
row = cur.fetchone()
if row:
    cur.execute(
        "UPDATE users SET password_hash = ?, display_name = ?, role = ?, created_at = ? WHERE id = ?",
        (hashed, "Administrator", "admin", datetime.now().isoformat(), row[0]),
    )
    print("Updated existing admin password.")
else:
    cur.execute(
        "INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
        ("admin", "Administrator", hashed, "admin", datetime.now().isoformat()),
    )
    print("Created admin user with password.")

conn.commit()
conn.close()
print("Done. Login with username 'admin' and password:", password)
