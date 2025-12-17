import sqlite3
import os

db_path = "./app.db"

if not os.path.exists(db_path):
    print("Database not found, models initialized via main app startup usually.")
    # If DB doesn't exist, main app startup will create tables with new schema.
    exit()

conn = sqlite3.connect(db_path)
c = conn.cursor()

print("Migrating Scenarios...")
try:
    c.execute("ALTER TABLE scenarios ADD COLUMN deleted_at TIMESTAMP")
    print("- Added deleted_at to scenarios")
except Exception as e:
    print(f"- Skipped scenarios: {e}")

print("Migrating Calls...")
try:
    c.execute("ALTER TABLE calls ADD COLUMN recording_sid VARCHAR")
    print("- Added recording_sid to calls")
except Exception as e:
    print(f"- Skipped calls: {e}")

print("Migrating Answers...")
try:
    c.execute("ALTER TABLE answers ADD COLUMN question_sort_at_call INTEGER DEFAULT 0")
    print("- Added question_sort_at_call to answers")
except Exception as e:
    print(f"- Skipped answers: {e}")

print("Creating EndingGuidance table...")
c.execute('''
    CREATE TABLE IF NOT EXISTS ending_guidances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scenario_id INTEGER,
        text VARCHAR,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP,
        FOREIGN KEY(scenario_id) REFERENCES scenarios(id)
    )
''')
try:
    c.execute("CREATE INDEX IF NOT EXISTS ix_ending_guidances_id ON ending_guidances (id)")
except Exception as e:
    print(f"Index creation error: {e}")

print("Migrating/Creating TranscriptionLog table...")
# Ensure base table exists
c.execute('''
    CREATE TABLE IF NOT EXISTS transcription_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        answer_id INTEGER,
        service VARCHAR,
        status VARCHAR,
        created_at TIMESTAMP
    )
''')

# Phase 2 columns - Add safely
cols = [
    ("audio_bytes", "INTEGER"),
    ("audio_duration", "INTEGER"),
    ("model_name", "VARCHAR"),
    ("language", "VARCHAR"),
    ("processing_time", "INTEGER"),
    ("request_payload", "TEXT"),
    ("response_payload", "TEXT")
]

for col, dtype in cols:
    try:
        c.execute(f"ALTER TABLE transcription_logs ADD COLUMN {col} {dtype}")
        print(f"- Added {col} to transcription_logs")
    except Exception as e:
        pass # Already exists

try:
    c.execute("CREATE INDEX IF NOT EXISTS ix_transcription_logs_id ON transcription_logs (id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_transcription_logs_answer_id ON transcription_logs (answer_id)")
except Exception as e:
    print(f"Index creation error: {e}")

print("Creating Message table...")
c.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        call_sid VARCHAR,
        recording_sid VARCHAR,
        recording_url VARCHAR,
        transcript_text TEXT,
        created_at TIMESTAMP,
        FOREIGN KEY(call_sid) REFERENCES calls(call_sid)
    )
''')
try:
    c.execute("CREATE INDEX IF NOT EXISTS ix_messages_call_sid ON messages (call_sid)")
except Exception as e:
    print(f"Index creation error: {e}")

conn.commit()
conn.close()
print("Migration completed")
