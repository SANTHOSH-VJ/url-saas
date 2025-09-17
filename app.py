
from flask import Flask, request, redirect, jsonify, render_template, send_from_directory
import os
import mysql.connector 
from mysql.connector import pooling, Error
from dotenv import load_dotenv
import hashlib 
import base64 

POOL = None  # define globally to avoid NameError

load_dotenv()
 
app = Flask(__name__) 

# DB config from environment
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "root"),
    "database": os.getenv("DB_NAME", "test"),
    "autocommit": True
}

# Check if we're in development mode (no database available)
DEVELOPMENT_MODE = os.getenv("DEVELOPMENT_MODE", "false").lower() == "true"

# In-memory storage for development mode
DEV_STORAGE = {}

# Initialize database connection pool
def init_db_pool():
    global POOL
    
    if DEVELOPMENT_MODE:
        print("Running in DEVELOPMENT_MODE - Database connection disabled")
        POOL = None
        return
        
    try:
        print(f"Attempting to connect to database with config: {DB_CONFIG}")
        POOL = pooling.MySQLConnectionPool(
            pool_name="url_shortener_pool",
            pool_size=5,
            pool_reset_session=True,
            **DB_CONFIG
        )
        print("Database connection pool initialized successfully")
        
        # Test the connection
        test_conn = POOL.get_connection()
        test_cursor = test_conn.cursor()
        test_cursor.execute("SELECT 1")
        test_cursor.close()
        test_conn.close()
        print("Database connection test successful")
        
        # Create table if it doesn't exist
        create_table_if_not_exists()
        
    except Error as e:
        print(f"Error creating connection pool: {e}")
        print(f"Database config being used: {DB_CONFIG}")
        print("Falling back to development mode...")
        POOL = None

# Create table if it doesn't exist
def create_table_if_not_exists():
    if POOL is None:
        print("Cannot create table - connection pool not initialized")
        return
        
    try:
        conn = POOL.get_connection()
        cursor = conn.cursor()
        
        # Create the url_mapping table
        create_table_query = """
        CREATE TABLE IF NOT EXISTS url_mapping (
            id INT AUTO_INCREMENT PRIMARY KEY,
            long_url TEXT NOT NULL,
            short_url VARCHAR(10) NOT NULL UNIQUE,
            clicks INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        
        cursor.execute(create_table_query)
        conn.commit()
        cursor.close()
        conn.close()
        print("Table 'url_mapping' created or verified successfully")
        
    except Error as e:
        print(f"Error creating table: {e}")

# Create a pool of connections
def get_db_connection():
    if POOL is None:
        print("Connection pool is not initialized")
        return None
    try:
        return POOL.get_connection()
    except Error as e:
        print("DB connection error:", e)
        return None

 
 
# Function to generate a short URL 
def generate_short_url(long_url): 
   hash_object = hashlib.sha256(long_url.encode()) 
   short_hash = base64.urlsafe_b64encode(hash_object.digest())[:6].decode() 
   return short_hash 

@app.route('/') 
def home(): 
   return render_template('index.html')

# Handle favicon requests
@app.route('/favicon.ico')
def favicon():
    return '', 204  # Return empty response with 204 status 
 
 
# Handle URL shortening 
@app.route('/shorten', methods=['POST']) 
def shorten_url(): 
   long_url = request.form.get('long_url') 
   if not long_url: 
       return "Invalid URL", 400 

   # Development mode - use in-memory storage
   if DEVELOPMENT_MODE or POOL is None:
       # Check if URL already exists in dev storage
       for short_url, stored_long_url in DEV_STORAGE.items():
           if stored_long_url == long_url:
               return jsonify({
                   'success': True,
                   'short_url': f"{request.host_url}{short_url}",
                   'original_url': long_url
               })
       
       # Generate new short URL
       short_url = generate_short_url(long_url)
       DEV_STORAGE[short_url] = long_url
       return jsonify({
           'success': True,
           'short_url': f"{request.host_url}{short_url}",
           'original_url': long_url
       })

   conn = get_db_connection() 
   if conn is None:
       return "Database connection error. Please try again later.", 500
       
   try:
       cursor = conn.cursor(dictionary=True) 

       # Check if URL exists 
       cursor.execute("SELECT short_url FROM url_mapping WHERE long_url = %s", (long_url,)) 
       existing_entry = cursor.fetchone() 
       if existing_entry: 
           conn.close() 
           return jsonify({
               'success': True,
               'short_url': f"{request.host_url}{existing_entry['short_url']}",
               'original_url': long_url
           })

       short_url = generate_short_url(long_url) 
       cursor.execute("INSERT INTO url_mapping (long_url, short_url) VALUES (%s, %s)", (long_url, short_url)) 
       conn.commit() 
       conn.close() 

       return jsonify({
           'success': True,
           'short_url': f"{request.host_url}{short_url}",
           'original_url': long_url
       })
   except Error as e:
       if conn:
           conn.close()
       print(f"Database error: {e}")
       return "Database error occurred", 500
 
 
# Redirect shortened URLs 
@app.route('/<short_url>', methods=['GET']) 
def redirect_url(short_url): 
   # Development mode - use in-memory storage
   if DEVELOPMENT_MODE or POOL is None:
       if short_url in DEV_STORAGE:
           return redirect(DEV_STORAGE[short_url])
       else:
           return "Error: URL not found", 404
       
   conn = get_db_connection() 
   if conn is None:
       return "Database connection error. Please try again later.", 500
       
   try:
       cursor = conn.cursor(dictionary=True) 

       cursor.execute("SELECT long_url FROM url_mapping WHERE short_url = %s", (short_url,)) 
       entry = cursor.fetchone() 
       if entry: 
           cursor.execute("UPDATE url_mapping SET clicks = clicks + 1 WHERE short_url = %s", (short_url,)) 
           conn.commit() 
           conn.close() 
           return redirect(entry['long_url']) 

       conn.close() 
       return "Error: URL not found", 404
   except Error as e:
       if conn:
           conn.close()
       print(f"Database error: {e}")
       return "Database error occurred", 500
 
 
# Initialize database pool when the app starts
init_db_pool()

# Run the Flask application 
if __name__ == '__main__': 
   app.run(host="0.0.0.0", port=5000, debug=True) 
