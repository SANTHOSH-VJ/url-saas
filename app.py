from flask import Flask, request, redirect, jsonify, render_template
import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv
import hashlib
import base64

load_dotenv()

app = Flask(__name__)

# --------------------------
# ENV VARIABLES
# --------------------------
DB_URL = os.getenv("DB_URL")   # Supabase Postgres Session Pooler URL
DEVELOPMENT_MODE = os.getenv("DEVELOPMENT_MODE", "false").lower() == "true"

DEV_STORAGE = {}
POOL = None


# --------------------------
# INIT POSTGRES CONNECTION POOL
# --------------------------
def init_db_pool():
    global POOL

    if DEVELOPMENT_MODE:
        print("[MODE] DEVELOPMENT_MODE enabled (in-memory only)")
        POOL = None
        return

    try:
        print("[DB] Connecting to Supabase...")

        POOL = SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=DB_URL
        )

        conn = POOL.getconn()
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS url_mapping (
            id SERIAL PRIMARY KEY,
            long_url TEXT NOT NULL,
            short_url VARCHAR(50) UNIQUE NOT NULL,
            clicks INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        conn.commit()
        cursor.close()
        POOL.putconn(conn)

        print("[DB] Supabase table ready")

    except Exception as e:
        print("[DB ERROR] Failed to connect:", e)
        POOL = None


# --------------------------
# GET A CONNECTION
# --------------------------
def get_db_connection():
    if POOL:
        try:
            return POOL.getconn()
        except:
            return None
    return None


# --------------------------
# SHORT URL GENERATION
# --------------------------
def generate_short_url(long_url):
    hash_object = hashlib.sha256(long_url.encode())
    return base64.urlsafe_b64encode(hash_object.digest())[:6].decode()


# --------------------------
# HOME PAGE
# --------------------------
@app.route('/')
def home():
    return render_template('index.html')


# --------------------------
# SHORTEN URL
# --------------------------
@app.route('/shorten', methods=['POST'])
def shorten_url():
    long_url = request.form.get('long_url')
    custom_alias = request.form.get('alias')

    if not long_url:
        return jsonify({"error": "Invalid URL"}), 400

    # --------------------------
    # DEVELOPMENT MODE
    # --------------------------
    if DEVELOPMENT_MODE or POOL is None:

        if custom_alias:
            if custom_alias in DEV_STORAGE:
                return jsonify({"error": "Alias already taken"}), 400

            DEV_STORAGE[custom_alias] = long_url
            return jsonify({
                "success": True,
                "short_url": f"{request.host_url}{custom_alias}",
                "original_url": long_url
            })

        short_url = generate_short_url(long_url)
        DEV_STORAGE[short_url] = long_url

        return jsonify({
            "success": True,
            "short_url": f"{request.host_url}{short_url}",
            "original_url": long_url
        })

    # --------------------------
    # DATABASE MODE
    # --------------------------
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cursor = conn.cursor()

    # Check custom alias
    if custom_alias:
        cursor.execute("SELECT id FROM url_mapping WHERE short_url = %s;", (custom_alias,))
        exists = cursor.fetchone()

        if exists:
            POOL.putconn(conn)
            return jsonify({"error": "Alias already taken"}), 400

        cursor.execute(
            "INSERT INTO url_mapping (long_url, short_url) VALUES (%s, %s);",
            (long_url, custom_alias)
        )
        conn.commit()
        POOL.putconn(conn)

        return jsonify({
            "success": True,
            "short_url": f"{request.host_url}{custom_alias}",
            "original_url": long_url
        })

    # Auto-generate short code
    short_url = generate_short_url(long_url)

    cursor.execute(
        "INSERT INTO url_mapping (long_url, short_url) VALUES (%s, %s) RETURNING id;",
        (long_url, short_url)
    )
    conn.commit()

    POOL.putconn(conn)

    return jsonify({
        "success": True,
        "short_url": f"{request.host_url}{short_url}",
        "original_url": long_url
    })


# --------------------------
# REDIRECT
# --------------------------
@app.route('/<short_url>')
def redirect_url(short_url):

    # Development mode only
    if DEVELOPMENT_MODE or POOL is None:
        if short_url in DEV_STORAGE:
            return redirect(DEV_STORAGE[short_url])
        return "Not Found", 404

    conn = get_db_connection()
    if conn is None:
        return "DB Error", 500

    cursor = conn.cursor()
    cursor.execute("SELECT long_url FROM url_mapping WHERE short_url = %s;", (short_url,))
    entry = cursor.fetchone()

    if entry:
        cursor.execute("UPDATE url_mapping SET clicks = clicks + 1 WHERE short_url = %s;", (short_url,))
        conn.commit()
        long_url = entry[0]
        POOL.putconn(conn)
        return redirect(long_url)

    POOL.putconn(conn)
    return "Not Found", 404


# --------------------------
# INIT DATABASE
# --------------------------
init_db_pool()


# --------------------------
# RUN SERVER
# --------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
