from flask import Flask, request, redirect, jsonify, render_template
import os
import psycopg
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv
import hashlib
import base64
import re
from urllib.parse import urlparse
from contextlib import contextmanager
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)

# --------------------------
# ENV VARIABLES
# --------------------------
DB_URL = os.getenv("DB_URL")   # Supabase Postgres Session Pooler URL
DEVELOPMENT_MODE = os.getenv("DEVELOPMENT_MODE", "false").lower() == "true"

DEV_STORAGE = {}  # Format: {short_url: {'long_url': url, 'expires_at': datetime or None}}
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

        POOL = ConnectionPool(
            conninfo=DB_URL,
            min_size=1,
            max_size=5
        )

        with POOL.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS url_mapping (
                    id SERIAL PRIMARY KEY,
                    long_url TEXT NOT NULL,
                    short_url VARCHAR(50) UNIQUE NOT NULL,
                    clicks INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP DEFAULT NULL
                );
                """)
                conn.commit()
                
                # Add expires_at column if it doesn't exist (for existing tables)
                cursor.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                                   WHERE table_name='url_mapping' AND column_name='expires_at') THEN
                        ALTER TABLE url_mapping ADD COLUMN expires_at TIMESTAMP DEFAULT NULL;
                    END IF;
                END $$;
                """)
                conn.commit()

        print("[DB] Supabase table ready")

    except Exception as e:
        print("[DB ERROR] Failed to connect:", e)
        POOL = None


# --------------------------
# GET A CONNECTION (Context Manager)
# --------------------------
@contextmanager
def get_db_connection():
    """Context manager for safe database connection handling."""
    if not POOL:
        yield None
        return
    
    try:
        with POOL.connection() as conn:
            yield conn
    except Exception as e:
        print(f"[DB ERROR] Connection error: {e}")
        yield None


# --------------------------
# URL VALIDATION
# --------------------------
def is_valid_url(url):
    """Validate URL format."""
    try:
        result = urlparse(url)
        return all([result.scheme in ('http', 'https'), result.netloc])
    except:
        return False


def is_valid_alias(alias):
    """Validate custom alias (alphanumeric, hyphens, underscores only)."""
    if not alias:
        return True
    return bool(re.match(r'^[a-zA-Z0-9_-]{1,50}$', alias))


# --------------------------
# SHORT URL GENERATION
# --------------------------
def generate_short_url(long_url, salt=""):
    """Generate a short URL hash with optional salt for collision handling."""
    hash_input = f"{long_url}{salt}".encode()
    hash_object = hashlib.sha256(hash_input)
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
def calculate_expiration(expiration_type):
    """Calculate expiration datetime based on type."""
    if not expiration_type or expiration_type == 'never':
        return None
    
    now = datetime.now()
    expiration_map = {
        '1h': timedelta(hours=1),
        '24h': timedelta(hours=24),
        '7d': timedelta(days=7),
        '30d': timedelta(days=30),
        '90d': timedelta(days=90),
        '1y': timedelta(days=365)
    }
    
    if expiration_type in expiration_map:
        return now + expiration_map[expiration_type]
    
    # Handle custom minutes
    if expiration_type.startswith('custom_'):
        try:
            minutes = int(expiration_type.replace('custom_', ''))
            if minutes > 0:
                return now + timedelta(minutes=minutes)
        except ValueError:
            pass
    
    return None


@app.route('/shorten', methods=['POST'])
def shorten_url():
    long_url = request.form.get('long_url', '').strip()
    custom_alias = request.form.get('alias', '').strip()
    expiration_type = request.form.get('expiration', 'never').strip()

    # Validate URL
    if not long_url or not is_valid_url(long_url):
        return jsonify({"error": "Please enter a valid URL (http/https)"}), 400

    # Validate custom alias
    if custom_alias and not is_valid_alias(custom_alias):
        return jsonify({"error": "Alias can only contain letters, numbers, hyphens, and underscores"}), 400

    # Calculate expiration
    expires_at = calculate_expiration(expiration_type)

    # --------------------------
    # DEVELOPMENT MODE
    # --------------------------
    if DEVELOPMENT_MODE or POOL is None:
        if custom_alias:
            if custom_alias in DEV_STORAGE:
                return jsonify({"error": "Alias already taken"}), 400
            DEV_STORAGE[custom_alias] = {'long_url': long_url, 'expires_at': expires_at}
            return jsonify({
                "success": True,
                "short_url": f"{request.host_url}{custom_alias}",
                "original_url": long_url,
                "expires_at": expires_at.isoformat() if expires_at else None
            })

        # Handle collisions in dev mode
        for attempt in range(5):
            salt = str(attempt) if attempt > 0 else ""
            short_url = generate_short_url(long_url, salt)
            if short_url not in DEV_STORAGE:
                DEV_STORAGE[short_url] = {'long_url': long_url, 'expires_at': expires_at}
                return jsonify({
                    "success": True,
                    "short_url": f"{request.host_url}{short_url}",
                    "original_url": long_url,
                    "expires_at": expires_at.isoformat() if expires_at else None
                })

        return jsonify({"error": "Failed to generate unique URL. Try again."}), 500

    # --------------------------
    # DATABASE MODE
    # --------------------------
    with get_db_connection() as conn:
        if conn is None:
            return jsonify({"error": "Database connection failed"}), 500

        try:
            cursor = conn.cursor()

            # Check custom alias
            if custom_alias:
                cursor.execute("SELECT id FROM url_mapping WHERE short_url = %s;", (custom_alias,))
                if cursor.fetchone():
                    cursor.close()
                    return jsonify({"error": "Alias already taken"}), 400

                cursor.execute(
                    "INSERT INTO url_mapping (long_url, short_url, expires_at) VALUES (%s, %s, %s);",
                    (long_url, custom_alias, expires_at)
                )
                conn.commit()
                cursor.close()
                return jsonify({
                    "success": True,
                    "short_url": f"{request.host_url}{custom_alias}",
                    "original_url": long_url,
                    "expires_at": expires_at.isoformat() if expires_at else None
                })

            # Auto-generate with collision handling
            for attempt in range(5):
                salt = str(attempt) if attempt > 0 else ""
                short_url = generate_short_url(long_url, salt)

                try:
                    cursor.execute(
                        "INSERT INTO url_mapping (long_url, short_url, expires_at) VALUES (%s, %s, %s) RETURNING id;",
                        (long_url, short_url, expires_at)
                    )
                    conn.commit()
                    cursor.close()
                    return jsonify({
                        "success": True,
                        "short_url": f"{request.host_url}{short_url}",
                        "original_url": long_url,
                        "expires_at": expires_at.isoformat() if expires_at else None
                    })
                except psycopg.errors.UniqueViolation:
                    conn.rollback()  # Collision, try with new salt
                    continue

            cursor.close()
            return jsonify({"error": "Failed to generate unique URL. Try again."}), 500

        except Exception as e:
            print(f"[DB ERROR] shorten_url: {e}")
            return jsonify({"error": "Database error occurred"}), 500


# --------------------------
# REDIRECT
# --------------------------
@app.route('/<short_url>')
def redirect_url(short_url):
    # Validate short_url format to prevent injection
    if not re.match(r'^[a-zA-Z0-9_-]{1,50}$', short_url):
        return "Invalid URL", 400

    # Development mode only
    if DEVELOPMENT_MODE or POOL is None:
        if short_url in DEV_STORAGE:
            entry = DEV_STORAGE[short_url]
            # Handle old format (string) vs new format (dict)
            if isinstance(entry, str):
                return redirect(entry)
            
            expires_at = entry.get('expires_at')
            if expires_at and datetime.now() > expires_at:
                return render_template('expired.html'), 410
            return redirect(entry['long_url'])
        return "Not Found", 404

    with get_db_connection() as conn:
        if conn is None:
            return "DB Error", 500

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT long_url, expires_at FROM url_mapping WHERE short_url = %s;", (short_url,))
            entry = cursor.fetchone()

            if entry:
                long_url, expires_at = entry
                
                # Check if link has expired
                if expires_at and datetime.now() > expires_at:
                    cursor.close()
                    return render_template('expired.html'), 410
                
                cursor.execute("UPDATE url_mapping SET clicks = clicks + 1 WHERE short_url = %s;", (short_url,))
                conn.commit()
                cursor.close()
                return redirect(long_url)

            cursor.close()
            return "Not Found", 404

        except Exception as e:
            print(f"[DB ERROR] redirect_url: {e}")
            return "Server Error", 500


# --------------------------
# INIT DATABASE
# --------------------------
init_db_pool()


# --------------------------
# RUN SERVER
# --------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
