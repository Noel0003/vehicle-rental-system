from flask import Flask, abort, render_template, request, redirect, url_for, session, flash, send_from_directory
import sqlite3, os
import shutil
from functools import wraps
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

ALLOWED_EXT = {'jpg','jpeg','png','pdf'}
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
LEGACY_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXT

app = Flask(__name__)
app.secret_key = 'change-this-secret-key-before-deployment'
DB = 'vehicle_rental.db'


def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def rental_conflict(con, rental):
    return con.execute('''
        SELECT 1 FROM rentals
        WHERE veh_id=? AND rental_id!=? AND status IN ('approved','active')
          AND NOT(end_date < ? OR start_date > ?)
    ''', (rental['veh_id'], rental['rental_id'], rental['start_date'], rental['end_date'])).fetchone()


def init_db():
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','customer')),
            phone TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS vehicles (
            veh_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reg_number TEXT UNIQUE NOT NULL,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            category TEXT NOT NULL,
            rental_price REAL NOT NULL CHECK(rental_price > 0),
            fuel_type TEXT DEFAULT 'Petrol',
            transmission TEXT NOT NULL DEFAULT 'Manual' CHECK(transmission IN ('Manual','Automatic')),
            seats INTEGER DEFAULT 5 CHECK(seats > 0),
            avail_status TEXT NOT NULL DEFAULT 'available' CHECK(avail_status IN ('available','rented','maintenance')),
            image_url TEXT DEFAULT '',
            description TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS rentals (
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
        CREATE TABLE IF NOT EXISTS maintenance (
            maintenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            veh_id INTEGER NOT NULL,
            service_date TEXT NOT NULL,
            description TEXT NOT NULL,
            cost REAL NOT NULL DEFAULT 0 CHECK(cost >= 0),
            status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','in progress','completed')),
            next_service_date TEXT DEFAULT '',
            FOREIGN KEY(veh_id) REFERENCES vehicles(veh_id)
        );
        CREATE TABLE IF NOT EXISTS documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            rental_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            doc_type TEXT NOT NULL,
            filename TEXT NOT NULL,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(rental_id) REFERENCES rentals(rental_id),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            veh_id INTEGER NOT NULL,
            rental_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(veh_id) REFERENCES vehicles(veh_id),
            FOREIGN KEY(rental_id) REFERENCES rentals(rental_id)
        );
        ''')
        rental_columns = {row['name'] for row in con.execute('PRAGMA table_info(rentals)')}
        if 'refund_status' not in rental_columns:
            con.execute("ALTER TABLE rentals ADD COLUMN refund_status TEXT NOT NULL DEFAULT 'none' CHECK(refund_status IN ('none','initiated'))")
            con.execute("UPDATE rentals SET refund_status='initiated' WHERE status='cancelled' AND payment_status='refunded'")
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        if os.path.isdir(LEGACY_UPLOAD_FOLDER):
            for doc in con.execute('SELECT filename FROM documents'):
                filename = os.path.basename(doc['filename'])
                if filename == doc['filename']:
                    old_path = os.path.join(LEGACY_UPLOAD_FOLDER, filename)
                    new_path = os.path.join(UPLOAD_FOLDER, filename)
                    if os.path.isfile(old_path) and not os.path.exists(new_path):
                        shutil.move(old_path, new_path)
        if not con.execute('SELECT 1 FROM users WHERE email=?', ('admin@rental.com',)).fetchone():
            con.execute('INSERT INTO users(full_name,email,password_hash,role,phone) VALUES(?,?,?,?,?)',
                        ('System Admin','admin@rental.com',generate_password_hash('Admin@123'),'admin',''))
        if con.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0] == 0:
            con.executemany('''INSERT INTO vehicles(reg_number,brand,model,category,rental_price,fuel_type,transmission,seats,avail_status,image_url,description)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''', [
                ('KL-13-AB-1001','Maruti Suzuki','Swift','Hatchback',1800,'Petrol','Manual',5,'available',
                 '/static/images/swift.jpg',
                 'Compact and economical city drive. Great fuel efficiency for daily commutes.'),
                ('KL-86-CD-2002','Hyundai','Creta','SUV',3200,'Diesel','Automatic',5,'available',
                 '/static/images/creta.jpg',
                 'Comfortable SUV for family trips. Spacious cabin with premium features.'),
                ('KL-07-EF-3003','Honda','City','Sedan',2700,'Petrol','Automatic',5,'available',
                 '/static/images/city.jpg',
                 'Premium sedan for smooth journeys. Refined ride quality and elegant styling.'),
                ('KL-13-GH-4004','Mahindra','Thar','Off-road',4500,'Diesel','Manual',4,'available',
                 '/static/images/thar.jpg',
                 'Adventure-ready 4x4 experience. Built for rough terrain and weekend escapes.'),
                ('KL-86-IJ-5005','Toyota','Innova Crysta','MPV',3800,'Diesel','Manual',7,'available',
                 '/static/images/innova.jpg',
                 'Spacious 7-seater MPV perfect for group travel and long highway drives.'),
                ('KL-07-KL-6006','BMW','3 Series','Luxury',8500,'Petrol','Automatic',5,'available',
                 '/static/images/bmw3.jpg',
                 'Luxury sports sedan with dynamic handling and a premium interior experience.'),
                ('KL-13-MN-7007','Tata','Nexon EV','Electric',2900,'Electric','Automatic',5,'available',
                 '/static/images/nexonev.jpg',
                 'Zero-emission electric SUV with a 300 km range. Smooth, silent, and smart.'),
                ('KL-86-OP-8008','Ford','Mustang','Sports',9500,'Petrol','Manual',4,'available',
                 '/static/images/mustang.jpg',
                 'Iconic American muscle car. Thrilling V8 performance for the open road.'),
                ('KL-07-QR-9009','Kia','Seltos','SUV',3100,'Petrol','Automatic',5,'available',
                 '/static/images/seltos.jpg',
                 'Feature-packed compact SUV with a panoramic sunroof and connected tech.'),
                ('KL-13-ST-1010','Mercedes-Benz','GLC','Luxury',11000,'Diesel','Automatic',5,'available',
                 '/static/images/glc.jpg',
                 'Premium luxury SUV combining elegance, comfort, and cutting-edge technology.'),
            ])
        additional_vehicles = [
            ('KL-86-TU-1111','Maruti Suzuki','Baleno','Hatchback',2000,'Petrol','Manual',5,'available','/static/images/baleno.jpg',
             'Fuel-efficient hatchback with a comfortable cabin, ideal for city trips.'),
            ('KL-07-UV-1212','Hyundai','Verna','Sedan',2800,'Petrol','Automatic',5,'available','/static/images/verna.jpg',
             'Refined sedan with a smooth automatic drive and generous passenger space.'),
            ('KL-13-VW-1313','Mahindra','XUV700','SUV',4200,'Diesel','Automatic',7,'available','/static/images/xuv700.webp',
             'Spacious seven-seat SUV suited to family journeys and long-distance travel.'),
            ('KL-86-WX-1414','Kia','Carens','MPV',3600,'Diesel','Automatic',7,'available','/static/images/carens.webp',
             'Comfortable seven-seat MPV with flexible space for passengers and luggage.'),
            ('KL-07-XY-1515','Tata','Punch','SUV',2200,'Petrol','Manual',5,'available','/static/images/punch.jpg',
             'Compact SUV with a raised driving position, perfect for everyday outings.'),
            ('KL-13-YZ-1616','Ford','Endeavour','SUV',5500,'Diesel','Automatic',7,'available','/static/images/endeavour.jpg',
             'Powerful seven-seat SUV with a spacious cabin, ideal for family road trips.'),
        ]
        for vehicle in additional_vehicles:
            if not con.execute('SELECT 1 FROM vehicles WHERE brand=? AND model=?', (vehicle[1], vehicle[2])).fetchone():
                con.execute('''INSERT INTO vehicles(reg_number,brand,model,category,rental_price,fuel_type,transmission,seats,avail_status,image_url,description)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''', vehicle)
            con.execute('UPDATE vehicles SET image_url=? WHERE brand=? AND model=?',
                        (vehicle[9], vehicle[1], vehicle[2]))
        if con.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0] == 0:
            customers = [
                ('Arjun Menon',   'arjun@example.com',   'Pass@1234', '9876543210'),
                ('Priya Nair',    'priya@example.com',   'Pass@1234', '9876543211'),
                ('Rahul Sharma',  'rahul@example.com',   'Pass@1234', '9876543212'),
                ('Sneha Pillai',  'sneha@example.com',   'Pass@1234', '9876543213'),
                ('Vikram Das',    'vikram@example.com',  'Pass@1234', '9876543214'),
            ]
            for name, email, pwd, phone in customers:
                con.execute('INSERT INTO users(full_name,email,password_hash,role,phone) VALUES(?,?,?,?,?)',
                            (name, email, generate_password_hash(pwd), 'customer', phone))
        if con.execute('SELECT COUNT(*) FROM rentals').fetchone()[0] == 0:
            con.executemany('INSERT INTO rentals(user_id,veh_id,start_date,end_date,total_amount,advance_paid,payment_method,payment_status,status) VALUES(?,?,?,?,?,?,?,?,?)', [
                (2,1,'2025-06-01','2025-06-03', 5400, 1620,'UPI','paid','completed'),
                (3,2,'2025-06-05','2025-06-08',12800, 3840,'Card','paid','completed'),
                (4,3,'2025-06-10','2025-06-12', 8100, 2430,'Wallet','paid','approved'),
                (5,4,'2025-06-15','2025-06-17',13500, 4050,'UPI','paid','active'),
                (6,5,'2025-06-20','2025-06-22',11400, 3420,'Card','paid','pending'),
                (2,6,'2025-07-01','2025-07-03',25500, 7650,'UPI','paid','pending'),
            ])
        if con.execute('SELECT COUNT(*) FROM maintenance').fetchone()[0] == 0:
            con.executemany('INSERT INTO maintenance(veh_id,service_date,description,cost,status,next_service_date) VALUES(?,?,?,?,?,?)', [
                (1,'2025-05-10','Oil change and tyre rotation',1800,'completed','2025-11-10'),
                (2,'2025-05-18','Brake pad replacement',3500,'completed','2025-11-18'),
                (4,'2025-06-01','Full 4x4 drivetrain service',6200,'in progress','2025-12-01'),
                (7,'2025-06-12','Battery health check and software update',2500,'scheduled','2025-12-12'),
            ])
        if con.execute('SELECT COUNT(*) FROM reviews').fetchone()[0] == 0:
            con.executemany('INSERT INTO reviews(user_id,veh_id,rental_id,rating,comment,created_at) VALUES(?,?,?,?,?,?)', [
                (2,1,1,5,'Fantastic experience! The Swift was clean, fuel-efficient and perfect for city driving. Highly recommend DriveEase!','2025-06-04 10:23:11'),
                (3,2,2,4,'Creta was very comfortable for our family trip. Smooth booking process. Will definitely rent again.','2025-06-09 14:47:32'),
                (4,3,3,5,'Honda City was in excellent condition. The staff was helpful and the whole process was seamless.','2025-06-13 09:15:05'),
                (5,4,4,4,'Thar was an absolute beast on the trails! Great adventure vehicle. Minor delay at pickup but overall great.','2025-06-18 18:02:44'),
                (6,5,5,5,'Innova was spacious and perfect for our group. Very clean and well maintained. 5 stars!','2025-06-23 11:38:57'),
            ])


def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get('user_id'):
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('You do not have permission to access that page.', 'error')
                return redirect(url_for('dashboard'))
            return fn(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def inject_globals():
    return {'current_year': date.today().year, 'theme': session.get('theme', 'light')}


app.jinja_env.filters['enumerate'] = enumerate


@app.route('/')
def home():
    with connect() as con:
        vehicles = con.execute("SELECT * FROM vehicles WHERE avail_status='available' ORDER BY veh_id DESC LIMIT 6").fetchall()
    return render_template('home.html', vehicles=vehicles)


@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name, email = request.form['full_name'].strip(), request.form['email'].strip().lower()
        password, phone = request.form['password'], request.form.get('phone','').strip()
        if len(password) < 8:
            flash('Password must contain at least 8 characters.', 'error')
        else:
            try:
                with connect() as con:
                    con.execute('INSERT INTO users(full_name,email,password_hash,role,phone) VALUES(?,?,?,?,?)',
                                (name,email,generate_password_hash(password),'customer',phone))
                flash('Account created. Please sign in.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('An account with that email already exists.', 'error')
    return render_template('register.html')


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email, password = request.form['email'].strip().lower(), request.form['password']
        with connect() as con:
            user = con.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session.update(user_id=user['user_id'], name=user['full_name'], role=user['role'], email=user['email'])
            flash('Welcome back, ' + user['full_name'] + '!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')


@app.route('/toggle-theme')
def toggle_theme():
    session['theme'] = 'light' if session.get('theme') == 'dark' else 'dark'
    return redirect(request.referrer or url_for('home'))


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been signed out.', 'success')
    return redirect(url_for('home'))


@app.route('/dashboard')
@login_required()
def dashboard():
    with connect() as con:
        if session['role'] == 'admin':
            stats = {
                'vehicles': con.execute('SELECT COUNT(*) FROM vehicles').fetchone()[0],
                'rentals': con.execute("SELECT COUNT(*) FROM rentals WHERE status NOT IN ('cancelled','completed')").fetchone()[0],
                'pending': con.execute("SELECT COUNT(*) FROM rentals WHERE status='pending'").fetchone()[0],
                'maintenance': con.execute("SELECT COUNT(*) FROM maintenance WHERE status != 'completed'").fetchone()[0],
                'customers': con.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0],
                'revenue': con.execute("SELECT COALESCE(SUM(advance_paid),0) FROM rentals WHERE payment_status='paid' AND refund_status!='initiated'").fetchone()[0],
            }
            recent = con.execute('''SELECT r.*,u.full_name,v.brand,v.model FROM rentals r JOIN users u ON r.user_id=u.user_id JOIN vehicles v ON r.veh_id=v.veh_id ORDER BY r.rental_id DESC LIMIT 6''').fetchall()
            top_vehicles = con.execute('''SELECT v.brand,v.model,v.category,COUNT(r.rental_id) as total_bookings,COALESCE(AVG(rv.rating),0) as avg_rating FROM vehicles v LEFT JOIN rentals r ON v.veh_id=r.veh_id AND r.status!='cancelled' LEFT JOIN reviews rv ON v.veh_id=rv.veh_id GROUP BY v.veh_id ORDER BY total_bookings DESC LIMIT 5''').fetchall()
            all_reviews = con.execute('''SELECT rv.*,u.full_name,v.brand,v.model FROM reviews rv JOIN users u ON rv.user_id=u.user_id JOIN vehicles v ON rv.veh_id=v.veh_id ORDER BY rv.created_at DESC LIMIT 10''').fetchall()
            return render_template('admin_dashboard.html', stats=stats, recent=recent, top_vehicles=top_vehicles, all_reviews=all_reviews)
        rentals = con.execute('''SELECT r.*,v.brand,v.model,v.reg_number FROM rentals r JOIN vehicles v ON r.veh_id=v.veh_id WHERE r.user_id=? ORDER BY r.rental_id DESC''', (session['user_id'],)).fetchall()
        reviews_given = con.execute('SELECT review_id, rental_id FROM reviews WHERE user_id=?', (session['user_id'],)).fetchall()
        reviewed_rental_ids = {rv['rental_id'] for rv in reviews_given}
        customer_reviews = con.execute('''
            SELECT rv.*,u.full_name,v.brand,v.model,ratings.avg_rating,ratings.review_count
            FROM reviews rv
            JOIN users u ON rv.user_id=u.user_id
            JOIN vehicles v ON rv.veh_id=v.veh_id
            JOIN (
                SELECT veh_id,AVG(rating) AS avg_rating,COUNT(*) AS review_count
                FROM reviews
                GROUP BY veh_id
            ) ratings ON ratings.veh_id=rv.veh_id
            ORDER BY rv.created_at DESC,rv.review_id DESC
            LIMIT 10
        ''').fetchall()
        total_paid = sum(r['advance_paid'] for r in rentals if r['payment_status'] == 'paid' and r['refund_status'] != 'initiated')
        return render_template('customer_dashboard.html', rentals=rentals, reviewed_rental_ids=reviewed_rental_ids, total_paid=total_paid, customer_reviews=customer_reviews)


@app.route('/vehicles')
def vehicles():
    search = request.args.get('q','').strip()
    with connect() as con:
        rows = con.execute('''SELECT * FROM vehicles WHERE (brand LIKE ? OR model LIKE ? OR category LIKE ? OR reg_number LIKE ?) ORDER BY veh_id DESC''',
                           tuple(['%'+search+'%']*4)).fetchall()
    return render_template('vehicles.html', vehicles=rows, search=search)


@app.route('/admin/vehicles/add', methods=['GET','POST'])
@login_required('admin')
def vehicle_add():
    if request.method == 'POST':
        fields = [request.form.get(k,'').strip() for k in ('reg_number','brand','model','category','rental_price','fuel_type','transmission','seats','avail_status','image_url','description')]
        try:
            with connect() as con:
                con.execute('''INSERT INTO vehicles(reg_number,brand,model,category,rental_price,fuel_type,transmission,seats,avail_status,image_url,description) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                            (fields[0].upper(),fields[1],fields[2],fields[3],float(fields[4]),fields[5] or 'Petrol',fields[6] or 'Manual',int(fields[7] or 5),fields[8] or 'available',fields[9],fields[10]))
            flash('Vehicle added successfully.', 'success'); return redirect(url_for('vehicles'))
        except (ValueError, sqlite3.IntegrityError):
            flash('Check the entered values. Registration number must be unique and price must be positive.', 'error')
    return render_template('vehicle_form.html', vehicle=None)


@app.route('/admin/vehicles/<int:veh_id>/edit', methods=['GET','POST'])
@login_required('admin')
def vehicle_edit(veh_id):
    with connect() as con: vehicle = con.execute('SELECT * FROM vehicles WHERE veh_id=?',(veh_id,)).fetchone()
    if not vehicle: flash('Vehicle not found.','error'); return redirect(url_for('vehicles'))
    if request.method == 'POST':
        try:
            with connect() as con:
                con.execute('''UPDATE vehicles SET reg_number=?,brand=?,model=?,category=?,rental_price=?,fuel_type=?,transmission=?,seats=?,avail_status=?,image_url=?,description=? WHERE veh_id=?''',
                    (request.form['reg_number'].strip().upper(),request.form['brand'].strip(),request.form['model'].strip(),request.form['category'],float(request.form['rental_price']),request.form['fuel_type'],request.form.get('transmission','Manual'),int(request.form['seats']),request.form['avail_status'],request.form.get('image_url','').strip(),request.form.get('description','').strip(),veh_id))
            flash('Vehicle updated.','success'); return redirect(url_for('vehicles'))
        except (ValueError, sqlite3.IntegrityError): flash('Could not update. Check the values and registration number.','error')
    return render_template('vehicle_form.html', vehicle=vehicle)


@app.route('/admin/vehicles/<int:veh_id>/delete', methods=['POST'])
@login_required('admin')
def vehicle_delete(veh_id):
    try:
        with connect() as con: con.execute('DELETE FROM vehicles WHERE veh_id=?',(veh_id,))
        flash('Vehicle deleted.','success')
    except sqlite3.IntegrityError: flash('Cannot delete a vehicle with rental or maintenance history. Keep the record for audit purposes.','error')
    return redirect(url_for('vehicles'))


@app.route('/rent/<int:veh_id>', methods=['GET','POST'])
@login_required('customer')
def rent_vehicle(veh_id):
    with connect() as con:
        vehicle = con.execute(
            "SELECT * FROM vehicles WHERE veh_id=? AND avail_status!='maintenance'",
            (veh_id,)
        ).fetchone()
        bookings = con.execute('''
            SELECT start_date,end_date,status FROM rentals
            WHERE veh_id=? AND (
                status='pending' OR
                (status IN ('approved','active') AND end_date>=?)
            )
            ORDER BY start_date
        ''', (veh_id, date.today().isoformat())).fetchall()
    if not vehicle: flash('This vehicle is currently unavailable.','error'); return redirect(url_for('vehicles'))
    is_available = vehicle['avail_status'] == 'available'
    advance_pct  = 0.60 if is_available else 0.30
    reserved_ranges = [
        {'start': booking['start_date'], 'end': booking['end_date'], 'status': booking['status']}
        for booking in bookings
    ]
    pending_hold = any(booking['status'] == 'pending' for booking in bookings)

    def render_booking_page():
        return render_template(
            'rent.html',
            vehicle=vehicle,
            today=date.today().isoformat(),
            advance_pct=advance_pct,
            reserved_ranges=reserved_ranges,
            pending_hold=pending_hold
        )

    if request.method == 'POST':
        start, end = request.form['start_date'], request.form['end_date']
        payment_method = request.form.get('payment_method','').strip()
        try:
            start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
            days = (end_d-start_d).days + 1
            if start_d < date.today() or days < 1: raise ValueError()
            if payment_method not in {'UPI','Credit Card','Debit Card','Net Banking','Wallet','Cash'}:
                flash('Please select a valid payment method.','error')
                raise ValueError()
            total   = days * vehicle['rental_price']
            advance = round(total * advance_pct, 2)
            with connect() as con:
                con.execute('BEGIN IMMEDIATE')
                pending = con.execute(
                    "SELECT 1 FROM rentals WHERE veh_id=? AND status='pending'",
                    (veh_id,)
                ).fetchone()
                overlap = con.execute('''
                    SELECT 1 FROM rentals
                    WHERE veh_id=? AND status IN ('approved','active')
                      AND NOT(end_date < ? OR start_date > ?)
                ''', (veh_id, start, end)).fetchone()
                if pending:
                    flash('A booking for this vehicle is already awaiting admin approval. Please wait for a decision before booking it.','error')
                elif overlap:
                    flash('This vehicle is already booked for some or all of those dates. Please choose different dates.','error')
                else:
                    con.execute('INSERT INTO rentals(user_id,veh_id,start_date,end_date,total_amount,advance_paid,payment_method,payment_status,status) VALUES(?,?,?,?,?,?,?,?,?)',
                                (session['user_id'],veh_id,start,end,total,advance,payment_method,'paid','pending'))
                    msg = f'Booking request submitted! ₹{advance:,.2f} advance recorded. Awaiting admin approval.'
                    rental_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
                    # Save uploaded documents
                    doc_types = ['driving_licence','aadhaar_passport']
                    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                    docs_uploaded = 0
                    for doc_type in doc_types:
                        f = request.files.get(doc_type)
                        if f and f.filename and allowed_file(f.filename):
                            ext = f.filename.rsplit('.',1)[1].lower()
                            fname = secure_filename(f'rental{rental_id}_{doc_type}.{ext}')
                            f.save(os.path.join(UPLOAD_FOLDER, fname))
                            con.execute('INSERT INTO documents(rental_id,user_id,doc_type,filename) VALUES(?,?,?,?)',
                                        (rental_id, session['user_id'], doc_type, fname))
                            docs_uploaded += 1
                    if docs_uploaded < 2:
                        # Roll back the rental if documents are missing
                        con.execute('DELETE FROM rentals WHERE rental_id=?',(rental_id,))
                        flash('Both documents are required to complete the booking. Please upload your Driving Licence and Aadhaar/Passport.','error')
                        return render_booking_page()
                    flash(msg, 'success')
                    return redirect(url_for('dashboard'))
        except ValueError: pass
    return render_booking_page()


@app.route('/admin/rentals/<int:rental_id>/documents')
@login_required('admin')
def rental_documents(rental_id):
    with connect() as con:
        rental = con.execute('SELECT r.*,u.full_name,v.brand,v.model FROM rentals r JOIN users u ON r.user_id=u.user_id JOIN vehicles v ON r.veh_id=v.veh_id WHERE r.rental_id=?',(rental_id,)).fetchone()
        docs = con.execute('SELECT * FROM documents WHERE rental_id=? ORDER BY doc_id',(rental_id,)).fetchall()
    if not rental: flash('Rental not found.','error'); return redirect(url_for('rentals_admin'))
    return render_template('rental_documents.html', rental=rental, docs=docs)


@app.route('/admin/rentals/<int:rental_id>/documents/<int:doc_id>')
@login_required('admin')
def rental_document_file(rental_id, doc_id):
    with connect() as con:
        doc = con.execute(
            'SELECT filename FROM documents WHERE doc_id=? AND rental_id=?',
            (doc_id, rental_id)
        ).fetchone()
    if not doc:
        abort(404)
    return send_from_directory(
        UPLOAD_FOLDER,
        doc['filename'],
        as_attachment=request.args.get('download') == '1',
        download_name=doc['filename']
    )


@app.route('/admin/rentals')
@login_required('admin')
def rentals_admin():
    with connect() as con:
        rows = con.execute('''SELECT r.*,u.full_name,u.email,v.brand,v.model,v.reg_number FROM rentals r JOIN users u ON r.user_id=u.user_id JOIN vehicles v ON r.veh_id=v.veh_id ORDER BY r.rental_id DESC''').fetchall()
    return render_template('rentals_admin.html', rentals=rows)


@app.route('/admin/rentals/<int:rental_id>/status', methods=['POST'])
@login_required('admin')
def rental_status(rental_id):
    status = request.form.get('status')
    allowed = {'pending','approved','active','completed','cancelled'}
    if status not in allowed: flash('Invalid rental status.','error'); return redirect(url_for('rentals_admin'))
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        rental = con.execute('SELECT * FROM rentals WHERE rental_id=?',(rental_id,)).fetchone()
        refund_initiated = False
        if rental:
            if status in ('approved','active') and rental_conflict(con, rental):
                flash('This booking overlaps another approved or active rental for the vehicle. Resolve the conflict before approving it.','error')
                return redirect(url_for('rentals_admin'))
            pay_status = rental['payment_status']
            if status == 'cancelled' and rental['payment_status'] == 'paid' and rental['advance_paid'] > 0:
                refund_initiated = rental['refund_status'] != 'initiated'
            refund_status = 'initiated' if refund_initiated else rental['refund_status']
            con.execute('UPDATE rentals SET status=?,payment_status=?,refund_status=? WHERE rental_id=?',
                        (status,pay_status,refund_status,rental_id))
            if status in ('approved','active'):
                con.execute("UPDATE vehicles SET avail_status='rented' WHERE veh_id=? AND avail_status!='maintenance'",(rental['veh_id'],))
            elif status in ('completed','cancelled'):
                other = con.execute("SELECT 1 FROM rentals WHERE veh_id=? AND rental_id!=? AND status IN ('approved','active')",(rental['veh_id'],rental_id)).fetchone()
                if not other: con.execute("UPDATE vehicles SET avail_status='available' WHERE veh_id=? AND avail_status='rented'",(rental['veh_id'],))
    if rental and status == 'cancelled' and rental['payment_status'] == 'paid' and rental['advance_paid'] > 0:
        flash(f"Rental cancelled. A refund of ₹{rental['advance_paid']:,.2f} has been recorded as initiated (demo only; no real payment was processed).",'success')
    else:
        flash('Rental status updated.','success')
    return redirect(url_for('rentals_admin'))


@app.route('/admin/rentals/<int:rental_id>/quick/<action>', methods=['POST'])
@login_required('admin')
def rental_quick(rental_id, action):
    mapping = {'approve':'approved','reject':'cancelled','complete':'completed','activate':'active'}
    if action not in mapping: flash('Invalid action.','error'); return redirect(url_for('rentals_admin'))
    status = mapping[action]
    refund_initiated = False
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        rental = con.execute('SELECT * FROM rentals WHERE rental_id=?',(rental_id,)).fetchone()
        if rental:
            if status in ('approved','active') and rental_conflict(con, rental):
                flash('This booking overlaps another approved or active rental for the vehicle. Resolve the conflict before approving it.','error')
                return redirect(url_for('rentals_admin'))
            pay_status = rental['payment_status']
            if status == 'cancelled' and rental['payment_status'] == 'paid' and rental['advance_paid'] > 0:
                refund_initiated = rental['refund_status'] != 'initiated'
            refund_status = 'initiated' if status == 'cancelled' and rental['payment_status'] == 'paid' and rental['advance_paid'] > 0 else rental['refund_status']
            con.execute('UPDATE rentals SET status=?,payment_status=?,refund_status=? WHERE rental_id=?',
                        (status,pay_status,refund_status,rental_id))
            if status in ('approved','active'):
                con.execute("UPDATE vehicles SET avail_status='rented' WHERE veh_id=? AND avail_status!='maintenance'",(rental['veh_id'],))
            elif status in ('completed','cancelled'):
                other = con.execute("SELECT 1 FROM rentals WHERE veh_id=? AND rental_id!=? AND status IN ('approved','active')",(rental['veh_id'],rental_id)).fetchone()
                if not other: con.execute("UPDATE vehicles SET avail_status='available' WHERE veh_id=? AND avail_status='rented'",(rental['veh_id'],))
    labels = {'approve':'approved','reject':'rejected','complete':'completed','activate':'activated'}
    if action == 'reject' and rental and rental['payment_status'] == 'paid' and rental['advance_paid'] > 0:
        if refund_initiated:
            flash(f"Rental rejected. A refund of ₹{rental['advance_paid']:,.2f} has been recorded as initiated (demo only; no real payment was processed).",'success')
        else:
            flash('Rental rejected. A refund was already recorded as initiated.','success')
    else:
        flash(f'Rental {labels[action]}.','success')
    return redirect(url_for('rentals_admin'))


@app.route('/customer/cancel/<int:rental_id>', methods=['POST'])
@login_required('customer')
def customer_cancel(rental_id):
    with connect() as con:
        rental = con.execute('SELECT * FROM rentals WHERE rental_id=? AND user_id=?',(rental_id,session['user_id'])).fetchone()
        if not rental:
            flash('Rental not found.','error')
        elif rental['status'] not in ('pending','approved','active'):
            flash('Only bookings that have not been completed can be cancelled.','error')
        else:
            refund_initiated = rental['payment_status'] == 'paid' and rental['advance_paid'] > 0
            refund_status = 'initiated' if refund_initiated else rental['refund_status']
            con.execute('UPDATE rentals SET status=?,refund_status=? WHERE rental_id=?',
                        ('cancelled',refund_status,rental_id))
            other = con.execute("SELECT 1 FROM rentals WHERE veh_id=? AND rental_id!=? AND status IN ('approved','active')",(rental['veh_id'],rental_id)).fetchone()
            if not other: con.execute("UPDATE vehicles SET avail_status='available' WHERE veh_id=? AND avail_status='rented'",(rental['veh_id'],))
            if refund_initiated:
                flash(f"Booking cancelled. A refund of ₹{rental['advance_paid']:,.2f} has been recorded as initiated (demo only; no real payment was processed).",'success')
            else:
                flash('Booking cancelled. No payment had been recorded.','success')
    return redirect(url_for('dashboard'))


@app.route('/admin/customers')
@login_required('admin')
def customers_list():
    with connect() as con:
        customers = con.execute('''
            SELECT u.*,
                COUNT(r.rental_id) as total_bookings,
                COALESCE(SUM(CASE WHEN r.status NOT IN ('cancelled') THEN r.total_amount ELSE 0 END),0) as total_spent
            FROM users u
            LEFT JOIN rentals r ON u.user_id = r.user_id
            WHERE u.role = 'customer'
            GROUP BY u.user_id
            ORDER BY u.created_at DESC
        ''').fetchall()
    return render_template('customers.html', customers=customers)


@app.route('/review/add', methods=['POST'])
@login_required('customer')
def review_add():
    rental_id = int(request.form.get('rental_id', 0))
    rating    = int(request.form.get('rating', 0))
    comment   = request.form.get('comment', '').strip()
    if not (1 <= rating <= 5):
        flash('Please select a rating between 1 and 5.', 'error')
        return redirect(url_for('dashboard'))
    with connect() as con:
        rental = con.execute('SELECT * FROM rentals WHERE rental_id=? AND user_id=? AND status=?', (rental_id, session['user_id'], 'completed')).fetchone()
        if not rental:
            flash('You can only review completed rentals.', 'error')
        elif con.execute('SELECT 1 FROM reviews WHERE rental_id=? AND user_id=?', (rental_id, session['user_id'])).fetchone():
            flash('You have already reviewed this rental.', 'error')
        else:
            con.execute('INSERT INTO reviews(user_id,veh_id,rental_id,rating,comment) VALUES(?,?,?,?,?)',
                        (session['user_id'], rental['veh_id'], rental_id, rating, comment))
            flash('Thank you for your review!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin/maintenance')
@login_required('admin')
def maintenance_list():
    with connect() as con:
        rows = con.execute('SELECT m.*,v.brand,v.model,v.reg_number FROM maintenance m JOIN vehicles v ON m.veh_id=v.veh_id ORDER BY m.service_date DESC').fetchall()
        cars = con.execute('SELECT veh_id,brand,model,reg_number FROM vehicles ORDER BY brand').fetchall()
    return render_template('maintenance.html', maintenance=rows, vehicles=cars)


@app.route('/admin/maintenance/add', methods=['POST'])
@login_required('admin')
def maintenance_add():
    try:
        with connect() as con:
            con.execute('INSERT INTO maintenance(veh_id,service_date,description,cost,status,next_service_date) VALUES(?,?,?,?,?,?)',
                (int(request.form['veh_id']),request.form['service_date'],request.form['description'].strip(),float(request.form.get('cost') or 0),request.form['status'],request.form.get('next_service_date','')))
            if request.form['status'] != 'completed': con.execute("UPDATE vehicles SET avail_status='maintenance' WHERE veh_id=?",(int(request.form['veh_id']),))
        flash('Maintenance record added.','success')
    except (ValueError, sqlite3.IntegrityError): flash('Could not add maintenance record. Check the values.','error')
    return redirect(url_for('maintenance_list'))


@app.route('/admin/maintenance/<int:mid>/edit', methods=['POST'])
@login_required('admin')
def maintenance_edit(mid):
    status = request.form.get('status')
    with connect() as con:
        item = con.execute('SELECT * FROM maintenance WHERE maintenance_id=?',(mid,)).fetchone()
        if item:
            con.execute('UPDATE maintenance SET status=?,cost=?,next_service_date=? WHERE maintenance_id=?',(status,float(request.form.get('cost') or 0),request.form.get('next_service_date',''),mid))
            if status == 'completed':
                other = con.execute("SELECT 1 FROM maintenance WHERE veh_id=? AND maintenance_id!=? AND status!='completed'",(item['veh_id'],mid)).fetchone()
                if not other: con.execute("UPDATE vehicles SET avail_status='available' WHERE veh_id=? AND avail_status='maintenance'",(item['veh_id'],))
            else: con.execute("UPDATE vehicles SET avail_status='maintenance' WHERE veh_id=?",(item['veh_id'],))
    flash('Maintenance record updated.','success'); return redirect(url_for('maintenance_list'))


@app.route('/admin/maintenance/<int:mid>/delete', methods=['POST'])
@login_required('admin')
def maintenance_delete(mid):
    with connect() as con:
        item = con.execute('SELECT * FROM maintenance WHERE maintenance_id=?',(mid,)).fetchone()
        if item:
            con.execute('DELETE FROM maintenance WHERE maintenance_id=?',(mid,))
            other = con.execute("SELECT 1 FROM maintenance WHERE veh_id=? AND status!='completed'",(item['veh_id'],)).fetchone()
            if not other: con.execute("UPDATE vehicles SET avail_status='available' WHERE veh_id=? AND avail_status='maintenance'",(item['veh_id'],))
    flash('Maintenance record deleted.','success'); return redirect(url_for('maintenance_list'))


@app.route('/invoice/<int:rental_id>')
@login_required('customer')
def invoice(rental_id):
    with connect() as con:
        rental = con.execute('''
            SELECT r.*,v.brand,v.model,v.reg_number,v.category,v.fuel_type,v.seats,
                   u.full_name,u.email,u.phone
            FROM rentals r
            JOIN vehicles v ON r.veh_id=v.veh_id
            JOIN users u ON r.user_id=u.user_id
            WHERE r.rental_id=? AND r.user_id=?
        ''', (rental_id, session['user_id'])).fetchone()
    if not rental:
        flash('Invoice not found.', 'error')
        return redirect(url_for('dashboard'))
    from datetime import date as _date
    start = _date.fromisoformat(rental['start_date'])
    end   = _date.fromisoformat(rental['end_date'])
    days    = (end - start).days + 1
    daily   = round(rental['total_amount'] / days, 2)
    advance = round(rental['advance_paid'], 2)
    balance = round(rental['total_amount'] - advance, 2)
    return render_template('invoice.html', r=rental, days=days, daily=daily, advance=advance, balance=balance)


@app.route('/profile', methods=['GET','POST'])
@login_required()
def profile():
    with connect() as con: user = con.execute('SELECT * FROM users WHERE user_id=?',(session['user_id'],)).fetchone()
    if request.method == 'POST':
        name, phone = request.form['full_name'].strip(), request.form.get('phone','').strip()
        with connect() as con: con.execute('UPDATE users SET full_name=?,phone=? WHERE user_id=?',(name,phone,session['user_id']))
        session['name'] = name; flash('Profile updated.','success'); return redirect(url_for('profile'))
    return render_template('profile.html', user=user)


@app.errorhandler(404)
def not_found(_): return render_template('error.html', code=404, message='The page you requested could not be found.'), 404


init_db()
if __name__ == '__main__':
    app.run(debug=True)
