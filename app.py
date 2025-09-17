
from flask import Flask, request, redirect, jsonify, render_template 
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
 
 
# Handle URL shortening 
@app.route('/shorten', methods=['POST']) 
def shorten_url(): 
   long_url = request.form.get('long_url') 
   if not long_url: 
       return "Invalid URL", 400 
 
   conn = get_db_connection() 
   cursor = conn.cursor(dictionary=True) 
 
   # Check if URL exists 
   cursor.execute("SELECT short_url FROM url_mapping WHERE long_url = %s", (long_url,)) 
   existing_entry = cursor.fetchone() 
   if existing_entry: 
       conn.close() 
       #return f"Shortened URL: <a href='{request.host_url}{existing_entry['short_url']}'>{request.host_url}{existing_entry['short_url']}</a>" 
       return f"Shortened URL: <a href='{request.host_url}{existing_entry['short_url']}'>https://us/{existing_entry['short_url']}</a>" 
 
   short_url = generate_short_url(long_url) 
   cursor.execute("INSERT INTO url_mapping (long_url, short_url) VALUES (%s, %s)", (long_url, short_url)) 
   conn.commit() 
   conn.close() 

   return f"Shortened URL: <a href='{request.host_url}{short_url}'>{request.host_url}{short_url}</a>" 
 
 
# Redirect shortened URLs 
@app.route('/<short_url>', methods=['GET']) 
def redirect_url(short_url): 
   conn = get_db_connection() 
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
 
 
# Run the Flask application 
if __name__ == '__main__': 
   app.run(host="0.0.0.0", port=5000, debug=True) 
