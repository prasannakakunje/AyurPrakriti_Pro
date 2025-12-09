# force_admin_pbkdf2.py
import sqlite3, hashlib, os, shutil, datetime, binascii

DB_PATH = os.path.expanduser(r"~\.ayurprakriti_app\ayurprakriti.db")
if not os.path.exists(DB_PATH):
    raise SystemExit("DB not found: " + DB_PATH)

# backup already done, but double-check
bak = DB_PATH + ".forcedreset.bak_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
shutil.copy2(DB_PATH, bak)
print("Backup created:", bak)

# simple pbkdf2-hmac-sha256 (match fallback used in your code)
def pbkdf2_hash_password(pw, salt=b"ayur_salt_v2", iters=200000):
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters)
    return binascii.hexlify(dk).decode("ascii")

new_pw = "admin123"   # change if you want a different password
new_hash = pbkdf2_hash_password(new_pw)
print("New pbkdf2 hash:", new_hash[:30], "... (len {})".format(len(new_hash)))

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
# Try update first
cur.execute("SELECT id, username FROM users WHERE username = ?", ("admin",))
row = cur.fetchone()
if row:
    cur.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, "admin"))
    print("Updated admin hash for id", row[0])
else:
    # insert admin
    cur.execute("INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
                ("admin","Administrator", new_hash, "admin", datetime.datetime.now().isoformat()))
    print("Inserted admin user")
conn.commit()
conn.close()
print("Done. Login with admin /", new_pw)
