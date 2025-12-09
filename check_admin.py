# check_admin.py
import sqlite3, pathlib, json, sys
from passlib.context import CryptContext

DB = pathlib.Path.home() / ".ayurprakriti_app" / "ayurprakriti.db"
print("DB path:", DB)

# show file exists and size
try:
    stat = DB.stat()
    print("DB exists, size (bytes):", stat.st_size)
except Exception as e:
    print("DB file not found or unreadable:", e)
    sys.exit(1)

conn = sqlite3.connect(str(DB))
cur = conn.cursor()
cur.execute("SELECT id, username, password_hash, role FROM users WHERE username='admin'")
row = cur.fetchone()
if not row:
    print("No admin user found (row is None).")
    conn.close()
    sys.exit(1)

print("admin row id,username,role:", row[0], row[1], row[3])
pw = row[2]
print("password_hash (prefix):", pw[:60], "...")
# detect scheme with passlib
ctx = CryptContext(schemes=["bcrypt","pbkdf2_sha256","argon2"], deprecated="auto")
scheme = ctx.identify(pw)
print("passlib identifies scheme:", scheme)
try:
    ok = ctx.verify("admin123", pw)
    print("verify('admin123') ->", ok)
except Exception as e:
    print("Error while verifying with passlib:", type(e).__name__, e)

conn.close()
