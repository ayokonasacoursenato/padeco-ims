import psycopg2
import os

# TAMA: 'DATABASE_URL' lang ang ilalagay dito. 
# Kukunin nito ang value na nilagay mo sa Render Environment tab.
DATABASE_URL = os.environ.get('DATABASE_URL')

try:
    if DATABASE_URL:
        # Kapag nasa Render (Live)
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        # Kapag nasa Laptop mo (Local)
        conn = psycopg2.connect(
            host="localhost",
            database="padeco_inventory",
            user="postgres",
            password="admin123"
        )
    
    cur = conn.cursor()
    print("Database connection successful!")
except Exception as e:
    print(f"Error connecting to database: {e}")
