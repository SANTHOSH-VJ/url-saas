from flask import Flask, request, redirect, jsonify, render_template
import os
import mysql.connector
from mysql.connector import pooling, Error
from dotenv import load_dotenv
import hashlib
import base64

POOL = None

load_dotenv()

app = Flask(__name__)

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "root"),
    "database": os.getenv("DB_NAME", "test")
}

DEVELOPMENT_MODE = os.getenv("DEVELOPMENT_MODE", "false").lower() == "true"
DEV_STORAGE = {}


# ---------------------------
#  DB INITIALIZATION
# ---------------------------

def init_db_pool():
    global POOL
    if DEVELOPMENT_MODE:
        print("[MODE] DEVELOPMENT_MODE enabled (in-memory only)")
        POOL = None
        return

    try:
        POOL = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="mypool",
            pool_size=5,
            **DB_CONFIG
        )

        conn = POOL.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS url_mapping (
            id INT AUTO_INCREMENT PRIMARY KEY,
            long_url TEXT NOT NULL,
            short_url VARCHAR(50) NOT NULL UNIQUE,
            clicks INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()
        cursor.close()
        conn.close()

        print("[DB] Table ready")

    except Error as e:
        print("[DB ERROR] Pool failed:", e)
        POOL = None


def get_db_connection():
    if POOL:
        try:
            return POOL.get_connection()
        except Error:
            return None
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except:
        return None


# ---------------------------
#  SHORT CODE GENERATION
# ---------------------------

def generate_short_url(long_url):
    hash_object = hashlib.sha256(long_url.encode())
    return base64.urlsafe_b64encode(hash_object.digest())[:6].decode()


# ---------------------------
#  ROUTES
# ---------------------------

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/shorten', methods=['POST'])
def shorten_url():
    long_url = request.form.get('long_url')
    custom_alias = request.form.get('alias')  # ⭐ ADDING CUSTOM ALIAS HERE

    if not long_url:
        return "Invalid URL", 400

    # -------------------------
    # DEVELOPMENT / IN-MEMORY MODE
    # -------------------------
    if DEVELOPMENT_MODE or POOL is None:

        # Check if custom alias is taken
        if custom_alias:
            if custom_alias in DEV_STORAGE:
                return jsonify({"error": "Alias already taken"}), 400
            
            DEV_STORAGE[custom_alias] = long_url

            return jsonify({
                'success': True,
                'short_url': f"{request.host_url}{custom_alias}",
                'original_url': long_url
            })

        # Auto generate random
        short_url = generate_short_url(long_url)
        DEV_STORAGE[short_url] = long_url

        return jsonify({
            'success': True,
            'short_url': f"{request.host_url}{short_url}",
            'original_url': long_url
        })

    # -------------------------
    # DATABASE MODE
    # -------------------------
    conn = get_db_connection()
    if conn is None:
        return "DB error", 500

    cursor = conn.cursor()

    # 1️⃣ If custom alias was given
    if custom_alias:
        cursor.execute("SELECT id FROM url_mapping WHERE short_url = %s", (custom_alias,))
        exists = cursor.fetchone()

        if exists:
            conn.close()
            return jsonify({"error": "Alias already taken"}), 400

        # Insert with alias
        cursor.execute(
            "INSERT INTO url_mapping (long_url, short_url) VALUES (%s, %s)",
            (long_url, custom_alias)
        )
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'short_url': f"{request.host_url}{custom_alias}",
            'original_url': long_url
        })

    # 2️⃣ Auto-generated
    short_url = generate_short_url(long_url)
    cursor.execute(
        "INSERT INTO url_mapping (long_url, short_url) VALUES (%s, %s)",
        (long_url, short_url)
    )
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'short_url': f"{request.host_url}{short_url}",
        'original_url': long_url
    })


# ---------------------------
# REDIRECT
# ---------------------------

@app.route('/<short_url>', methods=['GET'])
def redirect_url(short_url):

    if DEVELOPMENT_MODE or POOL is None:
        if short_url in DEV_STORAGE:
            return redirect(DEV_STORAGE[short_url])
        return "Not Found", 404

    conn = get_db_connection()
    if conn is None:
        return "DB Error", 500

    cursor = conn.cursor()
    cursor.execute("SELECT long_url FROM url_mapping WHERE short_url = %s", (short_url,))
    entry = cursor.fetchone()

    if entry:
        cursor.execute("UPDATE url_mapping SET clicks = clicks + 1 WHERE short_url = %s", (short_url,))
        conn.commit()
        conn.close()
        return redirect(entry[0])

    conn.close()
    return "Not Found", 404


init_db_pool()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
