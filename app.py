from flask import Flask, request, redirect, jsonify, render_template
import os
import mysql.connector
from mysql.connector import pooling, Error
from dotenv import load_dotenv
import hashlib
import base64

POOL = None  # define globally

load_dotenv()

app = Flask(__name__)

# DB config from environment
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "root"),
    "database": os.getenv("DB_NAME", "test")
}

# Development mode (in-memory fallback)
DEVELOPMENT_MODE = os.getenv("DEVELOPMENT_MODE", "false").lower() == "true"
DEV_STORAGE = {}


# Initialize database connection pool
def init_db_pool():
    global POOL

    if DEVELOPMENT_MODE:
        print("[MODE] Running in DEVELOPMENT_MODE (using in-memory storage only)")
        POOL = None
        return

    try:
        print(f"[DB INIT] Connecting with config: {DB_CONFIG}")
        POOL = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="mypool",
            pool_size=5,
            **DB_CONFIG
        )
        print("[DB INIT] Connection pool created")

        # Test connection
        test_conn = POOL.get_connection()
        test_cursor = test_conn.cursor()
        test_cursor.execute("SELECT DATABASE()")
        current_db = test_cursor.fetchone()[0]
        print(f"[DB TEST] Connected to database: {current_db}")
        test_cursor.close()
        test_conn.close()

        # Ensure table exists
        create_table_if_not_exists()

    except Error as e:
        print(f"[DB ERROR] Could not create pool: {e}")
        print("[DB FALLBACK] Using in-memory storage")
        POOL = None


# Create table if not exists
def create_table_if_not_exists():
    if POOL is None:
        print("[DB WARN] Cannot create table - no pool")
        return

    try:
        conn = POOL.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS url_mapping (
            id INT AUTO_INCREMENT PRIMARY KEY,
            long_url TEXT NOT NULL,
            short_url VARCHAR(10) NOT NULL UNIQUE,
            clicks INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("[DB INFO] Table 'url_mapping' is ready")
    except Error as e:
        print(f"[DB ERROR] Failed to create table: {e}")


# Get DB connection
def get_db_connection():
    if POOL is None:
        print("[DB WARN] Pool not initialized - trying direct connection")
        try:
            return mysql.connector.connect(**DB_CONFIG)
        except Error as e:
            print(f"[DB ERROR] Direct connection failed: {e}")
            return None
    try:
        return POOL.get_connection()
    except Error as e:
        print(f"[DB ERROR] Pool connection failed: {e}")
        return None


# Generate short URL
def generate_short_url(long_url):
    hash_object = hashlib.sha256(long_url.encode())
    short_hash = base64.urlsafe_b64encode(hash_object.digest())[:6].decode()
    return short_hash


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    return '', 204


# Shorten URL
@app.route('/shorten', methods=['POST'])
def shorten_url():
    long_url = request.form.get('long_url')
    if not long_url:
        return "Invalid URL", 400

    # In-memory mode
    if DEVELOPMENT_MODE or POOL is None:
        for short_url, stored_long_url in DEV_STORAGE.items():
            if stored_long_url == long_url:
                print(f"[MEMORY] URL already shortened: {short_url}")
                return jsonify({
                    'success': True,
                    'short_url': f"{request.host_url}{short_url}",
                    'original_url': long_url
                })

        short_url = generate_short_url(long_url)
        DEV_STORAGE[short_url] = long_url
        print(f"[MEMORY] New short URL created: {short_url} -> {long_url}")
        return jsonify({
            'success': True,
            'short_url': f"{request.host_url}{short_url}",
            'original_url': long_url
        })

    # Database mode
    conn = get_db_connection()
    if conn is None:
        return "Database connection error. Please try again later.", 500

    try:
        cursor = conn.cursor()

        # Check existing
        cursor.execute("SELECT short_url FROM url_mapping WHERE long_url = %s", (long_url,))
        existing_entry = cursor.fetchone()
        if existing_entry:
            print(f"[DB INFO] URL already exists: {existing_entry[0]} -> {long_url}")
            conn.close()
            return jsonify({
                'success': True,
                'short_url': f"{request.host_url}{existing_entry[0]}",
                'original_url': long_url
            })

        short_url = generate_short_url(long_url)
        cursor.execute(
            "INSERT INTO url_mapping (long_url, short_url) VALUES (%s, %s)",
            (long_url, short_url)
        )
        conn.commit()
        print(f"[DB INSERT] Added: {short_url} -> {long_url}")

        cursor.execute("SELECT * FROM url_mapping ORDER BY id DESC LIMIT 1")
        print("[DB DEBUG] Last row inserted:", cursor.fetchone())

        conn.close()

        return jsonify({
            'success': True,
            'short_url': f"{request.host_url}{short_url}",
            'original_url': long_url
        })

    except Error as e:
        if conn:
            conn.close()
        print(f"[DB ERROR] Insert failed: {e}")
        return "Database error occurred", 500


# Redirect short URL
@app.route('/<short_url>', methods=['GET'])
def redirect_url(short_url):
    if DEVELOPMENT_MODE or POOL is None:
        if short_url in DEV_STORAGE:
            print(f"[MEMORY] Redirecting {short_url} -> {DEV_STORAGE[short_url]}")
            return redirect(DEV_STORAGE[short_url])
        else:
            return "Error: URL not found", 404

    conn = get_db_connection()
    if conn is None:
        return "Database connection error. Please try again later.", 500

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT long_url FROM url_mapping WHERE short_url = %s", (short_url,))
        entry = cursor.fetchone()
        if entry:
            cursor.execute("UPDATE url_mapping SET clicks = clicks + 1 WHERE short_url = %s", (short_url,))
            conn.commit()
            print(f"[DB REDIRECT] {short_url} -> {entry[0]} (clicks incremented)")
            conn.close()
            return redirect(entry[0])

        conn.close()
        return "Error: URL not found", 404

    except Error as e:
        if conn:
            conn.close()
        print(f"[DB ERROR] Redirect failed: {e}")
        return "Database error occurred", 500


# Start DB pool at app startup
init_db_pool()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
