# DriveEase — Vehicle Rental System

A professional Flask website for a DBMS mini-project with the required **Vehicles**, **Rentals**, and **Maintenance** modules. SQLite is used for a zero-configuration local database; the SQL schema is in `schema.sql` and can be adapted for MySQL/Oracle if your lab specifically requires one of those systems.

## Features
- Separate admin and customer login; customer registration.
- Vehicles: create, view, search, update, delete; registration numbers are unique; availability and pricing are validated.
- Rentals: all customer bookings await admin approval; only one request per vehicle can await review at a time; overlapping dates with approved or active rentals are rejected and shown as unavailable in the booking calendar. Cancelling a booking with an advance records a refund as initiated; this is a demo status only and does not issue real money.
- Maintenance: create, view, update status/cost/next service date, delete records; maintenance status affects vehicle availability.
- Customer dashboard, rental history, profile update, admin statistics, responsive professional UI.
- Password hashes (not plaintext), foreign keys, validation and demo seed data.

## Run locally (Windows)
1. Install Python 3.10+.
2. Extract this folder and open a terminal inside `vehicle_rental_system`.
3. Create a virtual environment (recommended):
   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   ```
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
5. Start the website:
   ```powershell
   python app.py
   ```
6. Open `http://127.0.0.1:5000` in your browser. The SQLite database `vehicle_rental.db` is created automatically.

## Demo admin login
- Email: `admin@rental.com`
- Password: `Admin@123`

Change the demo password and `app.secret_key` before any real deployment. The project is intended as a college demonstration, not a production booking/payment system.

## Database modules / relationships
- `users(user_id PK)` — admin and customer accounts.
- `vehicles(veh_id PK, reg_number UNIQUE)` — fleet inventory and current availability.
- `rentals(rental_id PK, user_id FK, veh_id FK)` — booking dates, amount and lifecycle status.
- `maintenance(maintenance_id PK, veh_id FK)` — vehicle service history and costs.

## Main pages
- `/` — home page
- `/vehicles` — vehicle listing/search; admin can add/edit/delete
- `/dashboard` — role-based dashboard
- `/admin/rentals` — admin rental workflow
- `/admin/maintenance` — maintenance management
- `/profile` — update profile

## Notes for DBMS viva/report
- CRUD means Create, Read, Update and Delete.
- Primary keys uniquely identify records; foreign keys connect rentals to users/vehicles and maintenance to vehicles.
- `CHECK` constraints restrict valid prices, seat counts, roles and statuses.
- Passwords are hashed using Werkzeug.
- The current system calculates rental price as daily price × number of calendar days, including both pickup and return dates.
- Payment methods are demo selections only: no money is charged or refunded until a real payment provider is integrated. Cancellation records a demo refund-initiated status. ID verification, email/SMS notifications and production-grade CSRF protection are also not implemented.
