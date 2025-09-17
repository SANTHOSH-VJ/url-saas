URL Shortener SaaS
A simple Flask-based URL shortening web application with MySQL database integration. Users can input long URLs to generate shortened links, track click counts, and manage URL mappings.

Features:
Shorten long URLs using SHA-256 & Base64 encoding
Store and manage URLs in a MySQL database
Redirect users to the original URL when the short link is visited
Click tracking for each shortened URL
Responsive HTML frontend with Flask render_template

Tech Stack:
Backend: Python (Flask)
Database: MySQL
Frontend: HTML (Jinja2 templates)
Libraries: mysql-connector-python, hashlib, base64
