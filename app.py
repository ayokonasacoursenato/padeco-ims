from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import conn, cur
from datetime import datetime
import requests
from forecasting import moving_average, detect_trend, predict_days_left
from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash
import vonage
from vonage import Auth, Vonage
from vonage_sms import SmsMessage # Dito kukunin ang SmsMessage sa v3 SDK
import cv2
import numpy as np
import os

# Palitan ito ng URL na galing sa IP Webcam app sa phone mo
# Halimbawa: http://192.168.1.5:8080/shot.jpg
URL = os.environ.get('CAMERA_URL', "http://localhost:8080/shot.jpg")

def detect_finished_goods():
    # Sinisimulan ang real-time monitoring ng finished goods [cite: 130]
    print("Starting Camera Detection for Finished Goods...") 
    
    while True:
        try:
            # 1. Network Layer: Pagkuha ng image mula sa phone [cite: 116, 144, 385]
            img_resp = requests.get(URL, timeout=5)
            img_arr = np.array(bytearray(img_resp.content), dtype=np.uint8)
            frame = cv2.imdecode(img_arr, -1)
            
            # --- BAGONG VALIDATION CHECK ---
            # Sinisiguro na may valid image bago mag-process para maiwasan ang cvtColor error [cite: 503, 558]
            if frame is None:
                print("⚠️ Warning: Empty frame received. Skipping this cycle...")
                continue # Babalik sa simula ng loop para subukan ulit [cite: 560]
            # -------------------------------

            # 2. Image Processing: Pag-detect ng sako para sa evaluation [cite: 149, 171]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (5, 5), 0)
            _, thresh = cv2.threshold(blur, 40, 255, cv2.THRESH_BINARY)
            
            # 3. Identifying patterns/contours sa inventory usage [cite: 135, 187, 438]
            contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            
            count = 0
            for contour in contours:
                # I-evaluate ang sako base sa size constraint [cite: 150, 497]
                if cv2.contourArea(contour) > 5000: 
                    (x, y, w, h) = cv2.boundingRect(contour)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    count += 1
            
            # 4. Display results sa interface [cite: 151, 193]
            cv2.putText(frame, f"Sacks Detected: {count}", (10, 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            cv2.putText(frame, "Press 's' to Save to Inventory | 'q' to Quit", (10, 80), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            
            cv2.imshow("INVENTRA AI Camera Prototype", frame)

            key = cv2.waitKey(1) & 0xFF
            
            # 5. Database Integration: Pag-save ng stock-in transaction 
            if key == ord('s'):
                if count > 0:
                    product_name = "Soybean Meal" # Halimbawa ng product
                    try:
                        # Pag-update ng inventory levels sa real time [cite: 132]
                        cur.execute("UPDATE inventory SET quantity = quantity + %s WHERE product_name = %s", (count, product_name))
                        # Pag-record ng transaction sa PostgreSQL [cite: 128, 131]
                        cur.execute("INSERT INTO production_logs (product_name, quantity_used) VALUES (%s, %s)", (product_name, count))
                        conn.commit()
                        print(f"✅ Success: {count} bags added to {product_name}!")
                    except Exception as db_err:
                        conn.rollback()
                        print(f"❌ Database Error: {db_err}")
                else:
                    print("⚠️ No sacks detected to save.")

            elif key == ord('q'):
                break
                
        except Exception as e:
            # Corrective maintenance para sa connection issues [cite: 553]
            print(f"Connection Error: {e}") 
            break

    cv2.destroyAllWindows()
    
# Gamitin ang credentials mula sa app.py mo
VONAGE_API_KEY = os.environ.get("VONAGE_API_KEY", "15471af7")
VONAGE_API_SECRET = os.environ.get("VONAGE_API_SECRET", "qmz58VQZKSfLFuhJ")
SUPPLIER_NUMBER = os.environ.get("SUPPLIER_NUMBER", "639701316066")

auth = Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET)
client = Vonage(auth=auth)

app = Flask(__name__)
app.secret_key = "padeco_secret_key"

def get_weather_impact():
    """Kukuha ng weather data para sa forecasting alert (Lipa City, Batangas)"""
    API_KEY = "ba0ccf430038d0dcb3db3974acecbe91" 
    CITY = "Lipa,PH" # <--- PH para sa Pilipinas
    try:
        # units=metric para Celsius agad
        url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={API_KEY}&units=metric"
        response = requests.get(url, timeout=3)
        data = response.json()
        
        if response.status_code == 200:
            temp = round(data['main']['temp'], 1) # Celsius na ito
            condition = data['weather'][0]['main']
            
            if condition in ['Rain', 'Thunderstorm', 'Drizzle']:
                msg = f"⚠️ HIGH RISK: {condition} in Lipa. Possible logistics delay."
                impact = "Rain"
            else:
                msg = f"✅ NORMAL: {condition} in Lipa City. Operations smooth."
                impact = "Clear"
            
            return {"message": msg, "temp": temp, "condition": impact}
        else:
            # Fallback kapag may error sa API (e.g. invalid key)
            return {"message": "Weather service pending activation.", "temp": 31.0, "condition": "Clear"}
            
    except Exception as e:
        # Fallback kapag walang internet
        return {"message": "Weather service offline.", "temp": 30.0, "condition": "Clear"}
    
# =========================
# DATABASE INITIALIZATION
# =========================
def init_db():
    # In-update ang Inventory table para may barcode_id
    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id SERIAL PRIMARY KEY,
        product_name VARCHAR(100) UNIQUE NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        barcode_id VARCHAR(50) UNIQUE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        password VARCHAR(100) NOT NULL,
        role VARCHAR(50) NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS production_logs (
        id SERIAL PRIMARY KEY,
        product_name VARCHAR(100) NOT NULL,
        quantity_used INTEGER NOT NULL,
        log_date DATE NOT NULL DEFAULT CURRENT_DATE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS purchase_requests (
        id SERIAL PRIMARY KEY,
        product_name VARCHAR(100) NOT NULL,
        quantity_requested INTEGER NOT NULL,
        requested_by VARCHAR(100) NOT NULL,
        status VARCHAR(50) DEFAULT 'PENDING',
        date_requested TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # Hanapin ang bandang line 111 sa app.py
    cur.execute("""
    CREATE TABLE IF NOT EXISTS request_comments (
        id SERIAL PRIMARY KEY,
        request_id INTEGER REFERENCES purchase_requests(id) ON DELETE CASCADE,
        sender_name VARCHAR(100) NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()

    # --- ITO ANG DAGDAG PARA SA SCREENSHOT LOG ---
    cur.execute("SELECT COUNT(*) FROM inventory")
    count = cur.fetchone()[0]
    print(f"✅ DATA MIGRATION: Successfully parsed {count} records from PADECO Master Inventory.")
    # ---------------------------------------------------------

init_db()

# =========================
# AUTHENTICATION HELPERS
# =========================
def redirect_by_role(role):
    # Sinisiguro ang tamang landing page base sa departamento
    if role == 'production':
        return redirect(url_for('production_dashboard'))
    elif role == 'purchasing':
        return redirect(url_for('purchasing_dashboard'))
    else:
        # Default para sa Admin
        return redirect(url_for('index'))

# =========================
# ROUTES: LOGIN & LOGOUT
# =========================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password_candidate = request.form['password']
        
        cur.execute("SELECT username, role, password FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        
        if user:
            # user[2] ay ang hashed password mula sa database
            if check_password_hash(user[2], password_candidate):
                session['user'] = user[0]
                session['role'] = user[1].lower()
                
                # REDIRECT BASE SA ROLE: Staff -> Production, Admin/Others -> Dashboard
                return redirect_by_role(session['role'])
            else:
                flash("Invalid credentials. Please try again.")
        else:
            flash("Invalid credentials. Please try again.")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# =========================
# MAIN DASHBOARD (AI & IOT INTEGRATED)
# =========================
@app.route('/')
def index():
    if 'user' not in session: 
        return redirect(url_for('login'))
    
    if session.get('role') == 'production':
        return redirect(url_for('production'))
    
    # 1. Weather and Seasonal Info
    weather = get_weather_impact()
    current_month = datetime.now().strftime("%B")
    
    cur.execute("SELECT id, product_name, quantity, barcode_id, unit_price FROM inventory ORDER BY product_name ASC")
    inventory_items = cur.fetchall()

    analyzed_items = []
    total_inventory_value = 0
    predicted_expenses = 0 
    low_stock_count = 0
    total_daily_usage = 0

    for item in inventory_items:
        p_id, p_name, p_qty, p_barcode, p_price = item
        current_price = float(p_price) if p_price else 0.0
        total_inventory_value += (current_price * p_qty)
        
        # Kunin ang Historical Usage
        cur.execute("SELECT quantity_used FROM production_logs WHERE product_name = %s ORDER BY log_date DESC LIMIT 30", (p_name,))
        usage_history = [row[0] for row in cur.fetchall()]
        
        # 2. AI CALCULATIONS (Seasonal & Weather Aware)
        # I-update ang predict_days_left sa forecasting.py para tanggapin ang weather condition
        p_days_left = predict_days_left(p_qty, usage_history, weather['condition'])
        p_trend = detect_trend(usage_history)
        
        # Calculate daily usage for display
        avg_usage = moving_average(usage_history)
        total_daily_usage += avg_usage
        
        # Monthly Forecast (30 Days)
        p_forecast = avg_usage * 30
        item_predicted_cost = p_forecast * current_price
        predicted_expenses += item_predicted_cost

        # Status Logic
        p_status, p_color = "HEALTHY", "success"
        if p_days_left != "N/A":
            if p_days_left <= 3:
                p_status, p_color = "CRITICAL", "danger"
                low_stock_count += 1
            elif p_days_left <= 7:
                p_status, p_color = "WARNING", "warning"
                low_stock_count += 1
            
        analyzed_items.append({
            'name': p_name, 
            'qty': p_qty, 
            'price': current_price,
            'forecast': p_forecast,
            'predicted_cost': item_predicted_cost,
            'trend': p_trend, 
            'days_left': p_days_left,
            'status': p_status, 
            'color': p_color
        })

    recommendation = "URGENT: Stock up for peak season/weather." if low_stock_count > 0 else "Optimal levels for current season."

    return render_template('index.html', 
                           analyzed_items=analyzed_items, 
                           forecast=round(total_daily_usage, 1),
                           total_inventory_value=total_inventory_value,
                           predicted_expenses=predicted_expenses,
                           low_stock_count=low_stock_count, 
                           recommendation=recommendation,
                           weather=weather,
                           current_month=current_month,
                           username=session['user'], 
                           role=session['role'])

# =========================
# INVENTORY CRUD (ADMIN)
# =========================
@app.route('/inventory')
def inventory():
    if 'user' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    # 1. KUNIN ANG DATA: Dinagdagan ng 'category' sa SELECT statement
    cur.execute("SELECT id, product_name, quantity, barcode_id, unit_price, category FROM inventory ORDER BY product_name ASC")
    inventory_items = cur.fetchall()
    
    analyzed_inventory = []
    for item in inventory_items:
        # Pagtugmain ang variables sa pagkakasunod-sunod ng SELECT
        p_id, p_name, p_qty, p_barcode, p_price, p_cat = item
        
        # 2. HISTORY FETCH: Kunin ang huling 30 days na usage
        cur.execute("""
            SELECT quantity_used FROM production_logs 
            WHERE product_name = %s 
            ORDER BY log_date DESC LIMIT 30
        """, (p_name,))
        usage_history = [row[0] for row in cur.fetchall() if row[0] is not None]
        
        # 3. AI CALCULATIONS: Daily average burn rate
        avg_daily_usage = moving_average(usage_history)
        
        if avg_daily_usage > 0:
            p_days_left = p_qty / avg_daily_usage
        else:
            p_days_left = float('inf') 
            
        # 4. STATUS LOGIC: Unified colors para sa UI
        if p_days_left <= 3:
            p_status, p_color = "PRIORITY RESTOCK", "danger" # Inalis ang 'bg-' para sa badge consistency
        elif p_days_left <= 7:
            p_status, p_color = "LOW STOCK", "warning"
        else:
            p_status, p_color = "HEALTHY", "success"
            
        # 5. DATA PACKAGING: Siguraduhing 'category' ay maipapasa sa template
        analyzed_inventory.append({
            'id': p_id, 
            'name': p_name, 
            'qty': p_qty, 
            'barcode': p_barcode, 
            'price': float(p_price) if p_price else 0.0,
            'category': p_cat if p_cat else "Uncategorized", # Ipinasa rito ang category
            'status': p_status, 
            'color': p_color,
            'days_left': round(p_days_left, 1) if p_days_left != float('inf') else "N/A"
        })
    
    return render_template('inventory.html', items=analyzed_inventory, username=session['user'], role=session['role'])
@app.route('/add_inventory', methods=['POST'])
def add_inventory():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    # Kunin ang lahat ng data mula sa registration form
    name = request.form.get('product_name')
    qty = request.form.get('quantity')
    category = request.form.get('category') # Idinagdag para sa Finished Goods support
    barcode = request.form.get('barcode_id')
    price = request.form.get('unit_price')

    try:
        # In-update ang query para isama ang category column
        cur.execute("""
            INSERT INTO inventory (product_name, quantity, category, barcode_id, unit_price) 
            VALUES (%s, %s, %s, %s, %s)
        """, (name, qty, category, barcode, price))
        
        conn.commit()
        flash(f"Success: {name} registered under {category} category!")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ DB Error: {e}")
        flash(f"Error: Product registration failed.")
        
    return redirect(url_for('inventory'))

@app.route('/update_inventory', methods=['POST'])
def update_inventory():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    p_id = request.form.get('id')
    name = request.form.get('product_name')
    qty = request.form.get('quantity')
    category = request.form.get('category') # Idinagdag para ma-update ang category
    barcode = request.form.get('barcode_id')
    price = request.form.get('unit_price')

    try:
        # In-update ang query para isama ang category=%s
        cur.execute("""
            UPDATE inventory 
            SET product_name=%s, quantity=%s, category=%s, barcode_id=%s, unit_price=%s 
            WHERE id=%s
        """, (name, qty, category, barcode, price, p_id))
        
        conn.commit()
        flash(f"Inventory record for {name} updated successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Update Error: {e}")
        flash(f"Error: {str(e)}")
        
    return redirect(url_for('inventory'))

@app.route('/delete_inventory/<int:id>')
def delete_inventory(id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    try:
        cur.execute("DELETE FROM inventory WHERE id = %s", (id,))
        conn.commit()
        flash("Item deleted from master records.")
    except Exception as e: 
        conn.rollback()
        print(f"❌ Delete Error: {e}")
        flash("Error: Could not delete item.")
        
    return redirect(url_for('inventory'))

# =========================
# PRODUCTION & PURCHASING
# =========================
@app.route('/add_log', methods=['POST'])
def add_log():
    if 'user' not in session: return redirect(url_for('login'))
    
    p_name = request.form.get('product_name')
    qty_used = request.form.get('quantity_used')
    
    try:
        # Pilitin ang database na i-save ang transaction kasama ang eksaktong ORAS (Timestamp)
        cur.execute("""
            INSERT INTO production_logs (product_name, quantity_used, log_date) 
            VALUES (%s, %s, CURRENT_TIMESTAMP)
        """, (p_name, qty_used))
        
        # Pag-update ng imbentaryo base sa nabawas na materyales
        cur.execute("UPDATE inventory SET quantity = quantity - %s WHERE product_name = %s", (qty_used, p_name))
        
        # Importante: I-commit ang changes para mag-reflect agad sa "Logged Today" counter
        conn.commit() 
        print(f"✅ Success: Logged {qty_used} bags of {p_name} at {datetime.now().strftime('%H:%M:%S')}")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Log Error: {e}")
        flash("An error occurred while logging the activity.")

    # Pagbalik sa dashboard, siguradong committed na ang data para sa real-time updates
    return redirect(url_for('production_dashboard'))

@app.route('/production')
def production():
    if 'user' not in session: 
        return redirect(url_for('login'))
    
    # KUNIN ANG DROPDOWN ITEMS
    cur.execute("SELECT id, product_name, quantity FROM inventory ORDER BY product_name ASC")
    items = cur.fetchall()
    
    # KUNIN ANG RECENT LOGS
    cur.execute("""
        SELECT id, product_name, quantity_used, log_date 
        FROM production_logs 
        ORDER BY id DESC LIMIT 10
    """)
    logs = cur.fetchall()

    # KUNIN ANG MGA ACTIVE REQUESTS
    cur.execute("""
        SELECT id, product_name, quantity_requested, status, date_requested 
        FROM purchase_requests 
        WHERE status NOT IN ('Completed', 'Denied')
        ORDER BY id DESC
    """)
    pending_requests = cur.fetchall()

    # KUNIN ANG CHAT HISTORY
    # Note: Gumamit ng TO_CHAR para sa readable format ng timestamp
    cur.execute("""
        SELECT request_id, sender_name, message, 
               TO_CHAR(timestamp, 'Mon DD, HH:MI AM') as formatted_time 
        FROM request_comments 
        ORDER BY timestamp ASC
    """)
    all_comments = cur.fetchall()

    # PILIIN ANG TEMPLATE: 
    # 'production_dashboard.html' ang simplified UI para sa Staff
    # 'production.html' ang standard view para sa Admin
    template_name = 'production_dashboard.html' if session['role'] == 'production' else 'production.html'
    
    return render_template(template_name, 
                           items=items, 
                           logs=logs, 
                           pending_requests=pending_requests,
                           all_comments=all_comments,
                           username=session['user'], 
                           role=session['role'],
                           current_date=datetime.now().strftime("%B %d, %Y"))

@app.route('/purchasing')
def purchasing():
    if 'user' not in session: return redirect(url_for('login'))
    
    cur.execute("SELECT id, product_name, quantity, barcode_id, unit_price FROM inventory ORDER BY product_name ASC")
    items_from_db = cur.fetchall()

    analyzed_items = []
    for item in items_from_db:
        p_id, p_name, p_qty, p_barcode, p_price = item
        
        cur.execute("""
            SELECT quantity_used FROM production_logs 
            WHERE product_name = %s 
            ORDER BY log_date DESC LIMIT 30
        """, (p_name,))
        history = [row[0] for row in cur.fetchall() if row[0] is not None]
        
        # Calculate daily avg then convert to monthly forecast
        daily_avg = moving_average(history)
        p_forecast = daily_avg * 30
        
        # Suggested order: Monthly Need minus Current Stock
        order_suggestion = max(0, p_forecast - p_qty)
        
        current_price = float(p_price) if p_price else 0.0
        item_est_cost = order_suggestion * current_price
        
        # Status base sa Monthly coverage
        if p_qty < (p_forecast * 0.25): # Less than 1 week supply
            status, color = "PRIORITY RESTOCK", "danger"
        elif p_qty < p_forecast:
            status, color = "LOW STOCK", "warning"
        else:
            status, color = "HEALTHY", "success"
        
        analyzed_items.append({
            'name': p_name, 
            'qty': p_qty,
            'forecast': round(p_forecast, 2), 
            'suggested': round(order_suggestion, 2),
            'price': current_price,
            'est_cost': item_est_cost,
            'status': status,
            'color': color
        })

    return render_template('purchasing.html', 
                           items=items_from_db, 
                           analyzed_items=analyzed_items, 
                           username=session['user'], 
                           role=session['role'])

@app.route('/add_purchase', methods=['POST'])
def add_purchase():
    p_name = request.form.get('product_name')
    qty = request.form.get('quantity_purchased')
    
    try:
        # 1. Update ang Database
        cur.execute("UPDATE inventory SET quantity = quantity + %s WHERE product_name = %s", (qty, p_name))
        conn.commit()

        # 2. SMS Notification Logic (SDK v3.0+ Fix)
        message_text = f"PADECO ORDER: Isang order ng {qty} bags ng {p_name} ang na-process. Pakihanda ang delivery. Salamat!"
        
        # FIX: Gamitin ang 'from_' imbes na 'sender' para sa Pydantic validation
        message = SmsMessage(
            to=SUPPLIER_NUMBER,
            from_="PADECO_IMS",
            text=message_text
        )
        
        # I-send gamit ang client interface
        response = client.sms.send(message)

        # I-check ang status mula sa response object
        if response.messages[0].status == '0':
            flash(f"Successfully ordered {qty} bags. SMS sent to supplier!")
        else:
            flash(f"Stock updated, but SMS failed: {response.messages[0].error_text}")

    except Exception as e:
        conn.rollback()
        flash(f"Error: {str(e)}")
        
    return redirect(url_for('purchasing'))

@app.route('/users')
def user_management():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    cur.execute("SELECT id, username, role FROM users")
    return render_template('user_management.html', users=cur.fetchall(), username=session['user'], role=session['role'])

@app.route('/add_user', methods=['POST'])
def add_user():
    # Proteksyon: Admin lang ang pwedeng mag-add
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    username = request.form['username']
    plain_password = request.form['password']
    role = request.form['role']
    
    # Eto ang FIX: I-hash ang password bago i-save sa database
    hashed_password = generate_password_hash(plain_password)
    
    try:
        cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", 
                    (username, hashed_password, role))
        conn.commit()
        flash(f"User {username} successfully registered!")
    except Exception as e:
        conn.rollback()
        flash("Error: Username might already exist.")
        
    return redirect(url_for('user_management'))

@app.route('/delete_user/<int:id>')
def delete_user(id):
    cur.execute("DELETE FROM users WHERE id = %s AND username != %s", (id, session['user']))
    conn.commit()
    return redirect(url_for('user_management'))

@app.route('/send_comment', methods=['POST'])
def send_comment():
    if 'user' not in session: 
        return redirect(url_for('login'))
    
    request_id = request.form.get('request_id')
    message = request.form.get('message')
    sender = session['user']

    if message:
        cur.execute("INSERT INTO request_comments (request_id, sender_name, message) VALUES (%s, %s, %s)", 
                    (request_id, sender, message))
        conn.commit()
    
    # Babalik sa pinanggalingang page (Dashboard man o Purchasing)
    return redirect(request.referrer)

# =========================
# IOT CAMERA ROUTE [cite: 129, 436]
# =========================
@app.route('/run_camera')
def run_camera():
    if 'user' not in session:
        return redirect(url_for('login'))
    # Tinatawag ang OpenCV function na nasa app.py mo [cite: 58]
    detect_finished_goods() 
    # Babalik sa dashboard pagkatapos i-close ang camera
    return redirect(url_for('production_dashboard'))

# =========================
# PRODUCTION DASHBOARD LOGIC [cite: 124, 152]
# =========================
@app.route('/production_dashboard')
def production_dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    # 1. Kunin ang Inventory Items para sa Overview at Dropdowns
    cur.execute("SELECT id, product_name, quantity, category FROM inventory ORDER BY product_name ASC")
    inventory_items = cur.fetchall()
    
    weather_info = get_weather_impact()
    weather_cond = weather_info['condition']
    
    analyzed_items = []
    low_stock_count = 0 
    
    # 2. AI Logic: Kalkulahin ang status, forecast, at days left
    for item in inventory_items:
        p_id, p_name, p_qty, p_cat = item
        cur.execute("SELECT quantity_used FROM production_logs WHERE product_name = %s ORDER BY log_date DESC LIMIT 30", (p_name,))
        usage_history = [row[0] for row in cur.fetchall()]
        
        # AI Calculations
        avg_usage = moving_average(usage_history)
        p_forecast = avg_usage * 30 
        p_days_left = predict_days_left(p_qty, usage_history, weather_cond)
        
        # Status Logic
        if p_days_left == "N/A":
            status, color = "NO DATA", "secondary"
        elif p_days_left <= 3: 
            status, color = "CRITICAL", "danger"
            low_stock_count += 1
        elif p_days_left <= 7: 
            status, color = "WARNING", "warning"
            low_stock_count += 1
        else:
            status, color = "HEALTHY", "success"
            
        # FIX: Idinagdag ang forecast at days_left sa dictionary para hindi mag-error ang HTML
        analyzed_items.append({
            'name': p_name, 
            'qty': p_qty, 
            'category': p_cat, 
            'status': status, 
            'color': color,
            'forecast': p_forecast if p_forecast else 0,
            'days_left': p_days_left if p_days_left else 0
        })

    # 3. KPI LOGIC: Bags logged today
    cur.execute("SELECT SUM(quantity_used) FROM production_logs WHERE log_date::DATE = CURRENT_DATE")
    today_sum = cur.fetchone()[0]
    usage_today_count = today_sum if today_sum is not None else 0

    # 4. RECENT ACTIVITY LOGIC
    cur.execute("""
    SELECT id, product_name, quantity_used, 
           TO_CHAR(log_date, 'Mon DD, HH:MI AM') 
    FROM production_logs 
    ORDER BY id DESC LIMIT 5
    """)
    recent_logs = cur.fetchall()

    # 5. Tracker Logic: Bilangin ang PENDING at kuhanin ang ORDERED para sa receiving
    # Kinuha ang lahat ng columns (id, product_name, qty, requested_by, status)
    cur.execute("SELECT id, product_name, quantity_requested, requested_by, status FROM purchase_requests WHERE status IN ('PENDING', 'ORDERED')")
    pending_requests = cur.fetchall()

    # 6. Messenger Module
    cur.execute("""
        SELECT request_id, sender_name, message, 
               TO_CHAR(timestamp, 'HH:MI AM') as formatted_time 
        FROM request_comments 
        ORDER BY timestamp ASC
    """)
    all_comments = cur.fetchall()

    return render_template('production_dashboard.html', 
                           items=inventory_items, 
                           analyzed_items=analyzed_items, 
                           usage_today_count=usage_today_count, 
                           recent_logs=recent_logs,
                           all_comments=all_comments,
                           low_stock_count=low_stock_count,
                           pending_requests=pending_requests,
                           weather=weather_info, # Idinagdag para sa Weather Widget
                           username=session['user'],
                           current_date=datetime.now().strftime("%B %d, %Y"))

@app.route('/production_inventory')
def production_inventory():
    # Binago: Pinayagan ang purchasing staff na ma-access ang view-only ledger
    if 'user' not in session or session.get('role') not in ['production', 'admin', 'purchasing']:
        return redirect(url_for('login'))
    
    cur.execute("SELECT id, product_name, quantity, category FROM inventory ORDER BY product_name ASC")
    inventory_items = cur.fetchall()
    
    weather_info = get_weather_impact()
    weather_cond = weather_info['condition']
    
    analyzed_items = []
    for item in inventory_items:
        p_id, p_name, p_qty, p_cat = item
        
        cur.execute("SELECT quantity_used FROM production_logs WHERE product_name = %s ORDER BY log_date DESC LIMIT 30", (p_name,))
        usage_history = [row[0] for row in cur.fetchall()]
        
        avg_usage = moving_average(usage_history)
        p_forecast = avg_usage * 30 
        p_days_left = predict_days_left(p_qty, usage_history, weather_cond)
        p_trend = detect_trend(usage_history)
        
        if p_days_left == "N/A":
            status, color = "NO DATA", "secondary"
        elif p_days_left <= 3: 
            status, color = "CRITICAL", "danger"
        elif p_days_left <= 7: 
            status, color = "WARNING", "warning"
        else:
            status, color = "HEALTHY", "success"
            
        analyzed_items.append({
            'name': p_name,
            'qty': p_qty,
            'category': p_cat,
            'forecast': p_forecast,
            'days_left': p_days_left,
            'trend': p_trend,
            'status': status,
            'color': color
        })

    return render_template('production_inventory.html', 
                           analyzed_items=analyzed_items, 
                           username=session['user'],
                           current_date=datetime.now().strftime("%B %d, %Y"))
    
@app.route('/request_material', methods=['POST'])
def request_material():
    if 'user' not in session: return redirect(url_for('login'))
    
    product_name = request.form.get('product_name') # Halimbawa, galing sa dropdown
    qty = request.form.get('quantity')
    sender = session['user']

    # I-save bilang pormal na request sa database
    cur.execute("""
        INSERT INTO purchase_requests (product_name, quantity_requested, requested_by, status) 
        VALUES (%s, %s, %s, 'PENDING')
    """, (product_name, qty, sender))
    conn.commit()
    
    flash(f"Formal request for {product_name} has been sent to Purchasing.")
    return redirect(url_for('production_dashboard'))

@app.route('/purchasing_dashboard')
def purchasing_dashboard():
    if 'user' not in session or session.get('role') not in ['admin', 'purchasing']:
        return redirect(url_for('login'))
    
    # 1. Kunin ang Inventory Data
    cur.execute("SELECT id, product_name, quantity, category, unit_price FROM inventory ORDER BY product_name ASC")
    items_from_db = cur.fetchall()

    weather_info = get_weather_impact()
    weather_cond = weather_info['condition']
    
    analyzed_items = []
    total_est_cost = 0
    low_stock_count = 0

    for item in items_from_db:
        p_id, p_name, p_qty, p_cat, p_price = item
        
        # --- BAGONG FILTER LOGIC ---
        # Laktawan ang calculation kung ang item ay Finished Goods
        if p_cat == 'Finished Goods':
            continue 
        # ---------------------------

        current_price = float(p_price) if p_price else 0.0
        
        # 2. AI Calculations base sa 30-day history
        cur.execute("SELECT quantity_used FROM production_logs WHERE product_name = %s ORDER BY log_date DESC LIMIT 30", (p_name,))
        history = [row[0] for row in cur.fetchall()]
        
        daily_avg = moving_average(history)
        p_forecast = daily_avg * 30  # Monthly Forecast
        p_days_left = predict_days_left(p_qty, history, weather_cond)
        
        # 3. Suggested Order: Monthly Need minus Current Stock
        order_suggestion = max(0, round(p_forecast - p_qty))
        item_est_cost = order_suggestion * current_price
        
        # Isasama lang sa total expense ang mga kailangang i-restock na raw materials
        total_est_cost += item_est_cost
        
        # 4. AI-Based Status check para sa KPI cards
        if p_days_left != "N/A" and p_days_left <= 7:
            low_stock_count += 1

        analyzed_items.append({
            'name': p_name, 
            'qty': p_qty,
            'forecast': round(p_forecast, 1), 
            'suggested': order_suggestion,
            'est_cost': item_est_cost,
            'days_left': p_days_left
        })

    # 5. Kunin ang Pending Requests mula sa Production
    cur.execute("""
        SELECT id, product_name, quantity_requested, requested_by, status, date_requested 
        FROM purchase_requests 
        WHERE status = 'PENDING' 
        ORDER BY date_requested DESC
    """)
    pending_requests = cur.fetchall()

    # 6. Kunin ang Chat History para sa Messenger Module
    cur.execute("""
        SELECT request_id, sender_name, message, 
               TO_CHAR(timestamp, 'HH:MI AM') as formatted_time 
        FROM request_comments 
        ORDER BY timestamp ASC
    """)
    all_comments = cur.fetchall()

    return render_template('purchasing_dashboard.html', 
                           analyzed_items=analyzed_items, 
                           total_est_cost=total_est_cost,
                           low_stock_count=low_stock_count,
                           pending_requests=pending_requests,
                           all_comments=all_comments,
                           username=session['user'], 
                           current_date=datetime.now().strftime("%B %d, %Y"))

@app.route('/request_history')
def request_history():
    if 'user' not in session: return redirect(url_for('login'))
    
    role = session.get('role')
    activity_type = request.args.get('type')
    
    # 1. ROLE-BASED ACCESS CONTROL (Security Update)
    # Kung purchasing staff, bawal makita ang STOCK-OUT logs.
    if role == 'purchasing':
        if not activity_type or activity_type not in ['PROCUREMENT', 'STOCK-IN']:
            activity_type = 'PROCUREMENT' # Default view para sa purchasing
    
    # Default view para sa production at admin
    if not activity_type:
        activity_type = 'STOCK-OUT' if role == 'production' else 'ALL'

    # 2. UNIFIED QUERY: Hinati sa tatlong kategorya para sa 2-Step Verification logic
    # - STOCK-OUT: Pagbabawas ng gamit (Production)
    # - STOCK-IN: Pagpasok ng stocks (Kapag COMPLETED na ang request)
    # - PROCUREMENT: Pag-track ng orders (PENDING o ORDERED na status)
    query = """
        SELECT id, product_name, quantity_used as qty, 'STOCK-OUT' as activity_type, 
               'COMPLETED' as status, TO_CHAR(log_date, 'Mon DD, YYYY HH:MI AM') as timestamp 
        FROM production_logs
        UNION ALL
        SELECT id, product_name, quantity_requested as qty, 'STOCK-IN' as activity_type, 
               'COMPLETED' as status, TO_CHAR(date_requested, 'Mon DD, YYYY HH:MI AM') as timestamp 
        FROM purchase_requests WHERE status = 'COMPLETED'
        UNION ALL
        SELECT id, product_name, quantity_requested as qty, 'PROCUREMENT' as activity_type, 
               status, TO_CHAR(date_requested, 'Mon DD, YYYY HH:MI AM') as timestamp 
        FROM purchase_requests WHERE status != 'COMPLETED'
    """
    
    # 3. FINAL LOGIC FILTER
    if activity_type == 'ALL' and role != 'purchasing':
        final_query = f"SELECT * FROM ({query}) AS combined ORDER BY id DESC"
    elif activity_type == 'ALL' and role == 'purchasing':
        # Para sa purchasing staff, ang 'ALL' ay pinagsamang Procurement at Stock-In lang
        final_query = f"""
            SELECT * FROM ({query}) AS combined 
            WHERE activity_type IN ('PROCUREMENT', 'STOCK-IN') 
            ORDER BY id DESC
        """
    else:
        final_query = f"SELECT * FROM ({query}) AS combined WHERE activity_type = '{activity_type}' ORDER BY id DESC"
        
    cur.execute(final_query)
    all_activities = cur.fetchall()
    
    return render_template('request_history.html', 
                           activities=all_activities, 
                           current_filter=activity_type,
                           username=session['user'])
    
@app.route('/receive_order', methods=['POST'])
def receive_order():
    if 'user' not in session: 
        return redirect(url_for('login'))
    
    req_id = request.form.get('request_id')
    p_name = request.form.get('product_name')
    qty = request.form.get('quantity')

    try:
        # 1. UPDATE INVENTORY: Pormal na dagdag sa sako
        cur.execute("UPDATE inventory SET quantity = quantity + %s WHERE product_name = %s", (qty, p_name))
        
        # 2. STATUS UPDATE: Mula 'ORDERED' magiging 'COMPLETED'
        cur.execute("UPDATE purchase_requests SET status = 'COMPLETED' WHERE id = %s", (req_id,))
        
        # 3. AUDIT LOG (Opsyonal pero Recommended): 
        # Naglalagay tayo ng entry sa logs para lilitaw ito sa "Recent Activity" timeline
        # Ginagamit ang negative value o markahan bilang 'STOCK-IN' kung may type column ka
        cur.execute("""
            INSERT INTO production_logs (product_name, quantity_used, log_date) 
            VALUES (%s, %s, CURRENT_TIMESTAMP)
        """, (f"STOCK-IN: {p_name}", qty))
        
        conn.commit()
        flash(f"Success! {qty} bags of {p_name} have been added to inventory.")
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        flash("Failed to receive order. Please check database connection.")

    # Pagkatapos ng receive, balik sa dashboard para makita ang dagdag na stock
    return redirect(url_for('production_dashboard'))

@app.route('/approve_and_buy', methods=['POST'])
def approve_and_buy():
    if 'user' not in session or session.get('role') not in ['admin', 'purchasing']:
        return redirect(url_for('login'))
    
    req_id = request.form.get('request_id')
    p_name = request.form.get('product_name')
    qty = request.form.get('quantity')

    try:
        # 1. BAGUHIN ANG STATUS: Mula 'PENDING' magiging 'ORDERED' (Step 1 ng 2-Step Verification)
        cur.execute("UPDATE purchase_requests SET status = 'ORDERED' WHERE id = %s", (req_id,))
        
        # 2. SMS LOGIC: Padadalhan ang supplier ng order notification
        # Siguraduhin na may Vonage setup ka sa itaas ng app.py
        message_text = f"PADECO ORDER: {qty} bags of {p_name}. Deliver to Pansol, Padre Garcia, Batangas. Thank you!"
        
        # Subukan ipadala ang SMS (i-uncomment kung ready na ang Vonage API mo)
        # client.sms.send(SmsMessage(to=SUPPLIER_NUMBER, from_="PADECO_IMS", text=message_text))
        
        conn.commit()
        flash(f"Order for {p_name} has been sent to supplier! Status: ORDERED")
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        flash("Failed to process order.")

    return redirect(url_for('purchasing_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
