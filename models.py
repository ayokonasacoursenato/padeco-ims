from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# =====================
# PRODUCT / INVENTORY
# =====================
class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# =====================
# SALES (for forecasting)
# =====================
class Sales(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('inventory.id'))
    quantity_sold = db.Column(db.Integer)
    sale_date = db.Column(db.DateTime, server_default=db.func.now())


# =====================
# SUPPLIERS
# =====================
class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    contact = db.Column(db.String(100))
    address = db.Column(db.String(200))


# =====================
# USERS (LOGIN SYSTEM)
# =====================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20))  # admin / staff