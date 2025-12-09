# force_admin_bcrypt.py
import sqlite3, pathlib, sys
from passlib.context import CryptContext

DB = pathlib.Path.home() / ".ayurprakriti_app" / "ayurprakriti.db"
print("Using DB:", DB)
if not DB.exists():
    print("DB not found:", DB)
    sys.exit(1)

# prefer bcrypt if available
ctx = CryptContext(schemes=["bcrypt","pbkdf2_sha256","argon2"], deprecated="auto")
new_pw = "admin123"
hashval = ctx.hash(new_pw)
print("New hash scheme:", ctx.identify(hashval))

conn = sqlite3.connect(str(DB))
cur = conn.cursor()

cur.execute("SELECT id FROM users WHERE username='admin'")
if cur.fetchone():
    cur.execute("UPDATE users SET password_hash=? WHERE username='admin'", (hashval,))
    print("Updated admin hash.")
else:
    cur.execute(
        "INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?,?,?,?,datetime('now'))",
        ("admin","Administrator", hashval, "admin"),
    )
    print("Inserted admin user.")

conn.commit()
conn.close()
print("Done. Try login with admin/admin123")
