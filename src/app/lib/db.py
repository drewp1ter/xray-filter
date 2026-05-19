import sqlite3
from .constants import DATABASE_FILE

def get_connection():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS seen_online (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stable_id TEXT,           
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP                                         
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sent_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL,
        message_text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMP
    )
    """)
    
    connection.commit()
    connection.close()