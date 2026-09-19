"""
Creates a sample e-commerce SQLite database with realistic data
so the text-to-SQL agent has something meaningful to query.

Run once: python setup_database.py
"""

import sqlite3
import random
from datetime import datetime, timedelta

DB_NAME = "ecommerce.db"

conn = sqlite3.connect(DB_NAME)
cur = conn.cursor()

# --- Schema ---
cur.executescript("""
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    signup_date DATE NOT NULL
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date DATE NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
""")

# --- Sample data ---
cities = ["Mumbai", "Delhi", "Bangalore", "Pune", "Hyderabad", "Chennai"]
names = ["Rohit", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Karan", "Neha", "Arjun", "Divya"]

for i in range(1, 31):
    cur.execute(
        "INSERT INTO customers (customer_id, name, city, signup_date) VALUES (?, ?, ?, ?)",
        (i, random.choice(names) + f"_{i}", random.choice(cities),
         (datetime(2024, 1, 1) + timedelta(days=random.randint(0, 600))).date().isoformat())
    )

products = [
    ("Wireless Mouse", "Electronics", 499),
    ("Mechanical Keyboard", "Electronics", 2999),
    ("Bluetooth Earbuds", "Electronics", 1999),
    ("Yoga Mat", "Fitness", 799),
    ("Dumbbell Set", "Fitness", 1499),
    ("Running Shoes", "Fitness", 3499),
    ("Coffee Mug", "Home", 299),
    ("Desk Lamp", "Home", 899),
    ("Notebook Pack", "Stationery", 199),
    ("Backpack", "Accessories", 1299),
]
for idx, (name, cat, price) in enumerate(products, start=1):
    cur.execute(
        "INSERT INTO products (product_id, name, category, price) VALUES (?, ?, ?, ?)",
        (idx, name, cat, price)
    )

statuses = ["completed", "pending", "cancelled"]
order_id = 1
item_id = 1
for _ in range(80):
    cust_id = random.randint(1, 30)
    order_date = (datetime(2024, 6, 1) + timedelta(days=random.randint(0, 450))).date().isoformat()
    status = random.choices(statuses, weights=[0.75, 0.15, 0.10])[0]
    cur.execute(
        "INSERT INTO orders (order_id, customer_id, order_date, status) VALUES (?, ?, ?, ?)",
        (order_id, cust_id, order_date, status)
    )
    # 1-4 items per order
    for _ in range(random.randint(1, 4)):
        prod_id = random.randint(1, len(products))
        qty = random.randint(1, 3)
        cur.execute(
            "INSERT INTO order_items (order_item_id, order_id, product_id, quantity) VALUES (?, ?, ?, ?)",
            (item_id, order_id, prod_id, qty)
        )
        item_id += 1
    order_id += 1

conn.commit()
conn.close()

print(f"Sample database created: {DB_NAME}")
print("Tables: customers, products, orders, order_items")
