from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import conn, cur
from datetime import datetime
import requests
from forecasting import moving_average, detect_trend, predict_days_left
from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash
import os

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
    cur.execute("""
CREATE TABLE IF NOT EXISTS request_comments (
    id SERIAL PRIMARY KEY,
    request_id INTEGER REFERENCES purchase_requests(id) ON DELETE CASCADE,
    sender_name VARCHAR(100),
    message TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
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

init_db()

# =========================
# AUTHENTICATION HELPERS
# =========================
def redirect_by_role(role):
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
    
    # Kunin ang inventory data kasama ang unit_price
    cur.execute("SELECT id, product_name, quantity, barcode_id, unit_price FROM inventory ORDER BY product_name ASC")
    inventory_items = cur.fetchall()
    
    analyzed_inventory = []
    for item in inventory_items:
        p_id, p_name, p_qty, p_barcode, p_price = item
        
        # Kunin ang huling 30 days na usage para sa mas akmang daily average
        cur.execute("""
            SELECT quantity_used FROM production_logs 
            WHERE product_name = %s 
            ORDER BY log_date DESC LIMIT 30
        """, (p_name,))
        usage_history = [row[0] for row in cur.fetchall() if row[0] is not None]
        
        # Gamitin ang moving_average function para makuha ang daily burn rate
        avg_daily_usage = moving_average(usage_history)
        
        # Kalkulahin ang Days Left base sa kasalukuyang stock
        if avg_daily_usage > 0:
            p_days_left = p_qty / avg_daily_usage
        else:
            p_days_left = float('inf') # Walang nagamit na stock o sadyang marami ang supply
            
        # UNIFIED LOGIC: Pareho na ito sa Dashboard para hindi nakakalito
        # Priority Restock kung mauubos na sa loob ng 3 araw
        if p_days_left <= 3:
            p_status, p_color = "PRIORITY RESTOCK", "bg-danger"
        # Low Stock kung mauubos na sa loob ng isang linggo (7 araw)
        elif p_days_left <= 7:
            p_status, p_color = "LOW STOCK", "bg-warning"
        else:
            p_status, p_color = "HEALTHY", "bg-success"
            
        analyzed_inventory.append({
            'id': p_id, 
            'name': p_name, 
            'qty': p_qty, 
            'barcode': p_barcode, 
            'price': float(p_price) if p_price else 0.0,
            'status': p_status, 
            'color': p_color,
            'days_left': round(p_days_left, 1) if p_days_left != float('inf') else "N/A"
        })
    
    return render_template('inventory.html', items=analyzed_inventory, username=session['user'], role=session['role'])

@app.route('/add_inventory', methods=['POST'])
def add_inventory():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    name = request.form.get('product_name')
    qty = request.form.get('quantity')
    barcode = request.form.get('barcode_id')
    price = request.form.get('unit_price') # KUNIN ANG PRICE MULA SA FORM

    try:
        cur.execute("""
            INSERT INTO inventory (product_name, quantity, barcode_id, unit_price) 
            VALUES (%s, %s, %s, %s)
        """, (name, qty, barcode, price))
        conn.commit()
        flash("Product registered successfully!")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {str(e)}")
        
    return redirect(url_for('inventory'))

@app.route('/update_inventory', methods=['POST'])
def update_inventory():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    p_id = request.form.get('id')
    name = request.form.get('product_name')
    qty = request.form.get('quantity')
    barcode = request.form.get('barcode_id')
    price = request.form.get('unit_price') # KUNIN ANG BAGONG PRICE

    try:
        cur.execute("""
            UPDATE inventory 
            SET product_name=%s, quantity=%s, barcode_id=%s, unit_price=%s 
            WHERE id=%s
        """, (name, qty, barcode, price, p_id))
        conn.commit()
        flash("Inventory updated!")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {str(e)}")
        
    return redirect(url_for('inventory'))

@app.route('/delete_inventory/<int:id>')
def delete_inventory(id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    try:
        cur.execute("DELETE FROM inventory WHERE id = %s", (id,))
        conn.commit()
    except: conn.rollback()
    return redirect(url_for('inventory'))

# =========================
# PRODUCTION & PURCHASING
# =========================
@app.route('/add_log', methods=['POST'])
def add_log():
    p_name, qty_used = request.form.get('product_name'), request.form.get('quantity_used')
    try:
        cur.execute("INSERT INTO production_logs (product_name, quantity_used) VALUES (%s, %s)", (p_name, qty_used))
        cur.execute("UPDATE inventory SET quantity = quantity - %s WHERE product_name = %s", (qty_used, p_name))
        conn.commit()
    except: conn.rollback()
    return redirect(url_for('production'))

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
        cur.execute("UPDATE inventory SET quantity = quantity + %s WHERE product_name = %s", (qty, p_name))
        conn.commit()
        flash(f"Successfully added {qty} bags to {p_name}")
    except:
        conn.rollback()
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
    if 'user' not in session: return redirect(url_for('login'))
    
    request_id = request.form.get('request_id')
    message = request.form.get('message')
    sender = session['user']

    if message:
        cur.execute("INSERT INTO request_comments (request_id, sender_name, message) VALUES (%s, %s, %s)", 
                    (request_id, sender, message))
        conn.commit()
    
    return redirect(url_for('purchasing'))

@app.route('/production_dashboard')
def production_dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    username = session.get('user')
    role = session.get('role')
    
    # 1. Kunin ang Inventory Items
    cur.execute("SELECT id, product_name, quantity FROM inventory ORDER BY product_name ASC")
    items_raw = cur.fetchall()
    
    # Logic para sa analyzed_items (AI Forecast simulation)
    analyzed_items = []
    low_stock_count = 0
    for row in items_raw:
        # Gamitin ang forecasting function mo
        forecast_val = predict_days_left(row[1]) 
        status = "CRITICAL" if row[2] < 20 else "HEALTHY"
        
        if status == "CRITICAL":
            low_stock_count += 1
            
        analyzed_items.append({
            'name': row[1],
            'qty': row[2],
            'forecast': forecast_val,
            'status': status
        })
    
    # 2. Kunin ang total usage ngayong araw
    today = datetime.now().strftime('%Y-%m-%d')
    cur.execute("SELECT SUM(quantity_used) FROM production_logs WHERE log_date = %s", (today,))
    total_today = cur.fetchone()[0] or 0
    
    # 3. Kunin ang Pending Requests para sa Chat
    cur.execute("SELECT id, product_name, quantity_requested FROM purchase_requests WHERE status = 'Pending'")
    pending_requests = cur.fetchall()
    
    # 4. Kunin ang Comments (with formatted time)
    cur.execute("""
        SELECT request_id, sender_name, message, 
        TO_CHAR(created_at, 'HH:MI AM') as time 
        FROM request_comments 
        ORDER BY created_at ASC
    """)
    all_comments = cur.fetchall()

    return render_template('production_dashboard.html', 
                           username=username, 
                           role=role,
                           items=items_raw,
                           total_today=total_today,
                           low_stock_count=low_stock_count,
                           analyzed_items=analyzed_items,
                           pending_requests=pending_requests,
                           all_comments=all_comments,
                           current_date=datetime.now().strftime('%B %d, %Y'))

if __name__ == '__main__':
    app.run(debug=True)