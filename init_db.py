"""One-time DB init script — run schema.sql against DATABASE_URL."""
import os
import psycopg2

db_url = os.environ["DATABASE_URL"]
with open("schema.sql") as f:
    schema = f.read()

conn = psycopg2.connect(db_url)
conn.autocommit = True
cur = conn.cursor()
cur.execute(schema)
cur.close()
conn.close()
print("Schema executed successfully!")
