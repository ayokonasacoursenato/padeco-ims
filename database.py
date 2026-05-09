import psycopg2
import os

# Kukunin nito ang DATABASE_URL mula sa Environment Variables ng Render.
# Kung wala (ibig sabihin nasa laptop ka), gagamitin niya yung default na localhost setup mo.
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:admin123@localhost:5432/padeco_inventory')

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    print("Database connection successful!")
except Exception as e:
    print(f"Error connecting to database: {e}")
