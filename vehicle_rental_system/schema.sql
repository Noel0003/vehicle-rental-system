-- SQLite schema used by app.py (works with SQLite 3)
PRAGMA foreign_keys = ON;
CREATE TABLE users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','customer')),
  phone TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE vehicles (
  veh_id INTEGER PRIMARY KEY AUTOINCREMENT,
  reg_number TEXT UNIQUE NOT NULL,
  brand TEXT NOT NULL,
  model TEXT NOT NULL,
  category TEXT NOT NULL,
  rental_price REAL NOT NULL CHECK(rental_price > 0),
  fuel_type TEXT DEFAULT 'Petrol',
  seats INTEGER DEFAULT 5 CHECK(seats > 0),
  avail_status TEXT NOT NULL DEFAULT 'available' CHECK(avail_status IN ('available','rented','maintenance')),
  image_url TEXT DEFAULT '',
  description TEXT DEFAULT ''
);
CREATE TABLE rentals (
  rental_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  veh_id INTEGER NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  total_amount REAL NOT NULL CHECK(total_amount > 0),
  advance_paid REAL NOT NULL DEFAULT 0,
  payment_method TEXT DEFAULT '',
  payment_status TEXT NOT NULL DEFAULT 'pending' CHECK(payment_status IN ('pending','paid','refunded')),
  refund_status TEXT NOT NULL DEFAULT 'none' CHECK(refund_status IN ('none','initiated')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','active','completed','cancelled')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(user_id),
  FOREIGN KEY(veh_id) REFERENCES vehicles(veh_id)
);
CREATE TABLE maintenance (
  maintenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
  veh_id INTEGER NOT NULL,
  service_date TEXT NOT NULL,
  description TEXT NOT NULL,
  cost REAL NOT NULL DEFAULT 0 CHECK(cost >= 0),
  status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','in progress','completed')),
  next_service_date TEXT DEFAULT '',
  FOREIGN KEY(veh_id) REFERENCES vehicles(veh_id)
);
