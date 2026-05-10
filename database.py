import psycopg2

conn = psycopg2.connect(
    host="localhost",
    database="padeco_inventory",
    user="postgres",
    password="admin123"
)

cur = conn.cursor()