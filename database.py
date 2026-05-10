import psycopg2
import os

# Kukunin nito ang URL mula sa Environment Variable ng Render
DATABASE_URL = os.environ.get('postgresql://admin:TM7pO7B18TsBoy0AJvtYTC0yqxXdkksj@dpg-d7vk6k77f7vs73btqpn0-a/padeco_inventory)

try:
    # Kung nahanap ang DATABASE_URL (nasa Render tayo)
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        # Fallback sa local database mo kung wala sa Render
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
