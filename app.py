import os
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeSerializer

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

mail = Mail(app)

# SMTP-пресеты провайдеров
MAIL_PROVIDERS = {
    "gmail":  {"label": "Gmail",   "server": "smtp.gmail.com",    "port": 587, "tls": 1, "ssl": 0},
    "yandex": {"label": "Yandex",  "server": "smtp.yandex.ru",    "port": 465, "tls": 0, "ssl": 1},
    "mailru": {"label": "Mail.ru", "server": "smtp.mail.ru",      "port": 465, "tls": 0, "ssl": 1},
    "mipt":   {"label": "Физтех",  "server": "smtp.yandex.ru",    "port": 465, "tls": 0, "ssl": 1},
    "custom": {"label": "Другой",  "server": "",                  "port": 587, "tls": 1, "ssl": 0},
}

# Шифрование пароля почты
from cryptography.fernet import Fernet, InvalidToken

_enc_key = os.environ.get("MAIL_ENC_KEY")
if not _enc_key:
    _enc_key = Fernet.generate_key().decode()
    app.logger.warning("MAIL_ENC_KEY not set, using a temporary key")
_fernet = Fernet(_enc_key.encode() if isinstance(_enc_key, str) else _enc_key)

def encrypt_password(plain):
    return _fernet.encrypt(plain.encode()).decode()

def decrypt_password(token):
    try:
        return _fernet.decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        return ""


def apply_mail_settings(row=None):
    """Применить SMTP-настройки к app.config. row — строка из БД или None."""
    if row:
        app.config["MAIL_SERVER"] = row["mail_server"]
        app.config["MAIL_PORT"] = int(row["mail_port"])
        app.config["MAIL_USE_TLS"] = bool(row["use_tls"])
        app.config["MAIL_USE_SSL"] = bool(row["use_ssl"])
        app.config["MAIL_USERNAME"] = row["username"]
        app.config["MAIL_PASSWORD"] = decrypt_password(row["password"])
        app.config["MAIL_DEFAULT_SENDER"] = row["mail_from"] or row["username"]
    else:
        # дефолт из окружения
        app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
        app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
        app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "1") == "1"
        app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "0") == "1"
        app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
        app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
        app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_FROM", os.environ.get("MAIL_USERNAME"))
    mail.init_app(app)


def load_mail_settings_at_startup():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM mail_settings WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()
    apply_mail_settings(row)
serializer = URLSafeSerializer(app.secret_key, salt="release-booking-salt")
# Секретный код для создания администратора (лучше задавать через env)
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "SuperAdmin2026!")

DATABASE = "booking.db"

# Функции работы с БД

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            capacity INTEGER NOT NULL DEFAULT 1,
            floor INTEGER NOT NULL DEFAULT 1,
            equipment TEXT,
            image_url TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            booking_date DATE NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            purpose TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS mail_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            provider TEXT NOT NULL DEFAULT 'gmail',
            mail_server TEXT NOT NULL,
            mail_port INTEGER NOT NULL,
            use_tls INTEGER NOT NULL DEFAULT 1,
            use_ssl INTEGER NOT NULL DEFAULT 0,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            mail_from TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS release_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            requester_user_id INTEGER NOT NULL,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
            FOREIGN KEY (requester_user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


def send_booking_email(to_email, username, room_name, booking_date, start_time, end_time, purpose):
    if not to_email:
        return

    subject = f"Подтверждение бронирования аудитории: {room_name}"

    body = f"""Здравствуйте, {username}!

Ваше бронирование успешно создано.

Аудитория: {room_name}
Дата: {booking_date}
Время: {start_time} - {end_time}
Цель: {purpose if purpose else "Не указана"}

Спасибо, что пользуетесь BookRoom!
"""

    html = f"""
    <h2>Бронирование подтверждено</h2>
    <p>Здравствуйте, <b>{username}</b>!</p>
    <p>Ваше бронирование успешно создано.</p>

    <ul>
        <li><b>Аудитория:</b> {room_name}</li>
        <li><b>Дата:</b> {booking_date}</li>
        <li><b>Время:</b> {start_time} - {end_time}</li>
        <li><b>Цель:</b> {purpose if purpose else "Не указана"}</li>
    </ul>

    <p>Спасибо, что пользуетесь <b>BookRoom</b>!</p>
    """

    msg = Message(
        subject=subject,
        recipients=[to_email],
        body=body,
        html=html
    )
    mail.send(msg)


def check_time_conflict(room_id, booking_date, start_time, end_time, exclude_booking_id=None):
    """
    Проверяет, существует ли пересечение по времени с другими бронированиями.
    Возвращает True, если конфликт есть.
    """
    db = get_db()
    query = """
        SELECT COUNT(*) as cnt FROM bookings
        WHERE room_id = ? AND booking_date = ?
          AND start_time < ? AND end_time > ?
          AND (? IS NULL OR id != ?)
    """
    row = db.execute(query, (
        room_id, booking_date, end_time, start_time,
        exclude_booking_id, exclude_booking_id
    )).fetchone()
    return row["cnt"] > 0


# Декораторы

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Пожалуйста, войдите в систему.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Пожалуйста, войдите в систему.", "warning")
            return redirect(url_for("login"))
        db = get_db()
        user = db.execute("SELECT is_admin FROM users WHERE id = ?",
                          (session["user_id"],)).fetchone()
        if not user or not user["is_admin"]:
            flash("Доступ запрещён.", "danger")
            return redirect(url_for("rooms"))
        return f(*args, **kwargs)

    return decorated

def can_send_release_request(booking_id, requester_user_id):
    db = get_db()
    row = db.execute(
        """
        SELECT requested_at
        FROM release_requests
        WHERE booking_id = ? AND requester_user_id = ?
        ORDER BY requested_at DESC
        LIMIT 1
        """,
        (booking_id, requester_user_id)
    ).fetchone()

    if not row:
        return True

    last_request_time = datetime.strptime(row["requested_at"], "%Y-%m-%d %H:%M:%S")
    return datetime.utcnow() - last_request_time >= timedelta(hours=1)

def send_release_request_email(owner_email, owner_username, requester_username, room_name,
                               booking_date, start_time, end_time, release_link):
    if not owner_email:
        return

    subject = f"Запрос на освобождение аудитории: {room_name}"

    body = f"""Здравствуйте, {owner_username}!

Пользователь {requester_username} хочет забронировать аудиторию "{room_name}".

Ваше бронирование:
Дата: {booking_date}
Время: {start_time} - {end_time}

Если аудитория вам уже не нужна, перейдите по ссылке:
{release_link}

Если аудитория вам все еще нужна, просто проигнорируйте это письмо.
"""

    html = f"""
    <h2>Запрос на освобождение аудитории</h2>
    <p>Здравствуйте, <b>{owner_username}</b>!</p>
    <p>Пользователь <b>{requester_username}</b> хочет забронировать аудиторию <b>{room_name}</b>.</p>

    <ul>
        <li><b>Дата:</b> {booking_date}</li>
        <li><b>Время:</b> {start_time} - {end_time}</li>
    </ul>

    <p>Если аудитория вам уже не нужна, нажмите на ссылку ниже:</p>
    <p><a href="{release_link}">Освободить аудиторию</a></p>

    <p>Если аудитория вам все еще нужна, просто проигнорируйте это письмо.</p>
    """

    msg = Message(
        subject=subject,
        recipients=[owner_email],
        body=body,
        html=html
    )
    mail.send(msg)


def send_release_success_email(to_email, requester_username, owner_username, room_name,
                               booking_date, start_time, end_time):
    if not to_email:
        return

    subject = f"Аудитория освободилась: {room_name}"

    body = f"""Здравствуйте, {requester_username}!

Пользователь {owner_username} освободил желаемую аудиторию "{room_name}".

Освободившееся время:
Дата: {booking_date}
Время: {start_time} - {end_time}

Теперь вы можете попробовать забронировать эту аудиторию.
"""

    html = f"""
    <h2>Аудитория освободилась</h2>
    <p>Здравствуйте, <b>{requester_username}</b>!</p>
    <p>Пользователь <b>{owner_username}</b> освободил желаемую аудиторию <b>{room_name}</b>.</p>

    <ul>
        <li><b>Дата:</b> {booking_date}</li>
        <li><b>Время:</b> {start_time} - {end_time}</li>
    </ul>

    <p>Теперь вы можете попробовать забронировать эту аудиторию.</p>
    """

    msg = Message(
        subject=subject,
        recipients=[to_email],
        body=body,
        html=html
    )
    mail.send(msg)


def get_conflicting_booking(room_id, booking_date, start_time, end_time):
    db = get_db()
    query = """
        SELECT * FROM bookings
        WHERE room_id = ? AND booking_date = ?
          AND start_time < ? AND end_time > ?
        ORDER BY created_at ASC
        LIMIT 1
    """
    return db.execute(query, (room_id, booking_date, end_time, start_time)).fetchone()

# Auth: Регистрация / Вход / Выход

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("rooms"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        admin_code = request.form.get("admin_code", "").strip()

        # Валидация
        errors = []
        if not username or len(username) < 3:
            errors.append("Для регистрации имя должно быть не менее 3 символов.")
        if not email or "@" not in email:
            errors.append("Укажите корректный email.")
        if len(password) < 6:
            errors.append("Длина пароля должна быть не менее 6 символов.")
        if password != confirm_password:
            errors.append("Пароли не совпадают.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("register.html")

        db = get_db()
        try:
            is_admin = 1 if admin_code == ADMIN_SECRET else 0
            pw_hash = generate_password_hash(password)
            db.execute(
                "INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                (username, email, pw_hash, is_admin)
            )
            db.commit()
            flash("Регистрация успешна! Теперь войдите.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Пользователь с таким именем или email уже существует.", "danger")
            return render_template("register.html")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("rooms"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = user["is_admin"]
            flash(f"Вход выполнен, {username}!", "success")
            return redirect(url_for("rooms"))
        else:
            flash("Неверное имя пользователя или пароль.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("login"))


# Страницы

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("rooms"))
    return redirect(url_for("login"))


@app.route("/rooms")
@login_required
def rooms():
    db = get_db()
    rooms_list = db.execute(
        "SELECT * FROM rooms WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    return render_template("rooms.html", rooms=rooms_list)



@app.route("/book/<int:room_id>", methods=["GET", "POST"])
@login_required
def book_room(room_id):
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        flash("Аудитория не найдена.", "danger")
        return redirect(url_for("rooms"))

    if request.method == "POST":
        booking_date = request.form.get("booking_date")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        purpose = request.form.get("purpose", "").strip()

        errors = []
        conflicting_booking = None

        if not booking_date:
            errors.append("Выберите дату.")
        if not start_time or not end_time:
            errors.append("Укажите время начала и окончания.")
        if start_time and end_time and start_time >= end_time:
            errors.append("Время окончания должно быть позже времени начала.")

        if booking_date:
            try:
                bd = datetime.strptime(booking_date, "%Y-%m-%d").date()
                if bd < date.today():
                    errors.append("Нельзя бронировать на прошедшую дату.")
            except ValueError:
                errors.append("Некорректная дата.")

        if not errors:
            conflicting_booking = get_conflicting_booking(room_id, booking_date, start_time, end_time)
            if conflicting_booking:
                errors.append("На это время аудитория уже забронирована.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "book.html",
                room=room,
                conflict_exists=bool(conflicting_booking),
                booking_date=booking_date,
                start_time=start_time,
                end_time=end_time
            )

        db.execute(
            """INSERT INTO bookings (room_id, user_id, booking_date, start_time, end_time, purpose)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (room_id, session["user_id"], booking_date, start_time, end_time, purpose)
        )
        db.commit()

        user = db.execute(
            "SELECT username, email FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()

        try:
            send_booking_email(
                to_email=user["email"],
                username=user["username"],
                room_name=room["name"],
                booking_date=booking_date,
                start_time=start_time,
                end_time=end_time,
                purpose=purpose
            )
        except Exception as e:
            app.logger.error(f"Email sending failed: {e}")
            flash("Бронирование создано, но письмо-подтверждение не удалось отправить.", "warning")
            return redirect(url_for("dashboard"))

        flash("Бронирование успешно создано! Письмо отправлено на вашу почту.", "success")
        return redirect(url_for("dashboard"))

    return render_template("book.html", room=room)

    
@app.route("/calendar")
@login_required
def calendar():
    db = get_db()
    rooms_list = db.execute("SELECT * FROM rooms WHERE is_active = 1 ORDER BY name").fetchall()
    selected_date = request.args.get("date", date.today().isoformat())
    selected_room = request.args.get("room_id", type=int)

    query = """
        SELECT b.*, r.name as room_name, u.username
        FROM bookings b
        JOIN rooms r ON b.room_id = r.id
        JOIN users u ON b.user_id = u.id
        WHERE b.booking_date = ?
    """
    params = [selected_date]

    if selected_room:
        query += " AND b.room_id = ?"
        params.append(selected_room)

    query += " ORDER BY b.start_time"
    bookings = db.execute(query, params).fetchall()

    return render_template(
        "calendar.html",
        rooms=rooms_list,
        bookings=bookings,
        selected_date=selected_date,
        selected_room=selected_room
    )


@app.route("/api/bookings/<int:room_id>")
@login_required
def api_room_bookings(room_id):
    db = get_db()
    bookings = db.execute(
        """SELECT b.*, u.username
           FROM bookings b
           JOIN users u ON b.user_id = u.id
           WHERE b.room_id = ?
           ORDER BY b.booking_date, b.start_time""",
        (room_id,)
    ).fetchall()

    return jsonify([{
        "id": b["id"],
        "booking_date": b["booking_date"],
        "start_time": b["start_time"],
        "end_time": b["end_time"],
        "purpose": b["purpose"],
        "username": b["username"],
        "user_id": b["user_id"],
        "is_owner": b["user_id"] == session["user_id"],
        "is_admin": session.get("is_admin", False)
    } for b in bookings])


# Личный кабинет

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    today = date.today().isoformat()

    upcoming = db.execute(
        """SELECT b.*, r.name as room_name
           FROM bookings b
           JOIN rooms r ON b.room_id = r.id
           WHERE b.user_id = ? AND b.booking_date >= ?
           ORDER BY b.booking_date, b.start_time""",
        (session["user_id"], today)
    ).fetchall()

    past = db.execute(
        """SELECT b.*, r.name as room_name
           FROM bookings b
           JOIN rooms r ON b.room_id = r.id
           WHERE b.user_id = ? AND b.booking_date < ?
           ORDER BY b.booking_date DESC, b.start_time DESC""",
        (session["user_id"], today)
    ).fetchall()

    return render_template("dashboard.html", upcoming=upcoming, past=past)


@app.route("/booking/cancel/<int:booking_id>", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    db = get_db()
    booking = db.execute(
        "SELECT * FROM bookings WHERE id = ? AND user_id = ?",
        (booking_id, session["user_id"])
    ).fetchone()

    if not booking:
        flash("Бронирование не найдено или у вас нет прав.", "danger")
        return redirect(url_for("dashboard"))

    # Нельзя отменить прошедшие бронирования
    if booking["booking_date"] < date.today().isoformat():
        flash("Нельзя отменить прошедшее бронирование.", "warning")
        return redirect(url_for("dashboard"))

    db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    db.commit()
    flash("Бронирование отменено.", "info")
    return redirect(url_for("dashboard"))


# Админ-панель

@app.route("/admin")
@admin_required
def admin_panel():
    db = get_db()
    rooms_from_db = db.execute("SELECT * FROM rooms ORDER BY name").fetchall()
    users = db.execute("SELECT id, username, email, is_admin, created_at FROM users ORDER BY username").fetchall()
    all_bookings = db.execute(
        """SELECT b.*, r.name as room_name, u.username
           FROM bookings b
           JOIN rooms r ON b.room_id = r.id
           JOIN users u ON b.user_id = u.id
           ORDER BY b.booking_date DESC, b.start_time DESC
           LIMIT 50"""
    ).fetchall()

    mail_cfg = db.execute("SELECT * FROM mail_settings WHERE id = 1").fetchone()

    return render_template(
        "admin.html",
        rooms=rooms_from_db,
        users=users,
        bookings=all_bookings,
        mail_cfg=mail_cfg,
        mail_providers=MAIL_PROVIDERS,
    )


@app.route("/admin/room/add", methods=["POST"])
@admin_required
def add_room():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    capacity = request.form.get("capacity", type=int, default=1)
    floor = request.form.get("floor", type=int, default=1)
    equipment = request.form.get("equipment", "").strip()
    image_url = request.form.get("image_url", "").strip()

    if not name:
        flash("Название аудитории обязательно.", "danger")
        return redirect(url_for("admin_panel"))

    db = get_db()
    db.execute(
        """INSERT INTO rooms (name, description, capacity, floor, equipment, image_url)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, description, capacity, floor, equipment, image_url)
    )
    db.commit()
    flash(f"Аудитория '{name}' добавлена.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/room/<int:room_id>/toggle", methods=["POST"])
@admin_required
def toggle_room(room_id):
    db = get_db()
    room = db.execute("SELECT is_active FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room:
        new_val = 0 if room["is_active"] else 1
        db.execute("UPDATE rooms SET is_active = ? WHERE id = ?", (new_val, room_id))
        db.commit()
        status = "активна" if new_val else "неактивна"
        flash(f"Статус аудитории изменён: {status}.", "info")
    return redirect(url_for("admin_panel"))


@app.route("/admin/booking/<int:booking_id>/delete", methods=["POST"])
@admin_required
def admin_delete_booking(booking_id):
    db = get_db()
    db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    db.commit()
    flash("Бронирование удалено.", "info")
    return redirect(url_for("admin_panel"))


@app.route("/admin/user/<int:user_id>/toggle-admin", methods=["POST"])
@admin_required
def toggle_admin(user_id):
    db = get_db()
    user = db.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if user:
        new_val = 0 if user["is_admin"] else 1
        db.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_val, user_id))
        db.commit()
        role = "администратором" if new_val else "обычным пользователем"
        flash(f"Пользователь теперь {role}.", "info")
    return redirect(url_for("admin_panel"))


@app.route("/admin/mail", methods=["POST"])
@admin_required
def update_mail_settings():
    provider = request.form.get("provider", "custom")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    mail_from = request.form.get("mail_from", "").strip() or username

    preset = MAIL_PROVIDERS.get(provider, MAIL_PROVIDERS["custom"])
    if provider == "custom":
        server = request.form.get("mail_server", "").strip()
        port = request.form.get("mail_port", type=int, default=587)
        use_tls = 1 if request.form.get("use_tls") else 0
        use_ssl = 1 if request.form.get("use_ssl") else 0
    else:
        server, port = preset["server"], preset["port"]
        use_tls, use_ssl = preset["tls"], preset["ssl"]

    if not username or not password or not server:
        flash("Заполните адрес, пароль и (для 'Другой') сервер.", "danger")
        return redirect(url_for("admin_panel"))

    enc = encrypt_password(password)

    db = get_db()
    db.execute(
        """
        INSERT INTO mail_settings
            (id, provider, mail_server, mail_port, use_tls, use_ssl, username, password, mail_from)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            provider=excluded.provider, mail_server=excluded.mail_server,
            mail_port=excluded.mail_port, use_tls=excluded.use_tls,
            use_ssl=excluded.use_ssl, username=excluded.username,
            password=excluded.password, mail_from=excluded.mail_from,
            updated_at=CURRENT_TIMESTAMP
        """,
        (provider, server, port, use_tls, use_ssl, username, enc, mail_from),
    )
    db.commit()

    row = db.execute("SELECT * FROM mail_settings WHERE id = 1").fetchone()
    apply_mail_settings(row)
    flash("Настройки почты сохранены.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/booking/request-release/<int:room_id>", methods=["POST"])
@login_required
def request_release(room_id):
    db = get_db()

    booking_date = request.form.get("booking_date")
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")

    room = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        flash("Аудитория не найдена.", "danger")
        return redirect(url_for("rooms"))

    conflict = get_conflicting_booking(room_id, booking_date, start_time, end_time)
    if not conflict:
        flash("Конфликтующее бронирование не найдено.", "warning")
        return redirect(url_for("book_room", room_id=room_id))

    if conflict["user_id"] == session["user_id"]:
        flash("Вы не можете отправить запрос самому себе.", "warning")
        return redirect(url_for("book_room", room_id=room_id))

    if not can_send_release_request(conflict["id"], session["user_id"]):
        flash("Такой запрос можно отправлять не чаще одного раза в час.", "warning")
        return redirect(url_for("book_room", room_id=room_id))

    owner = db.execute(
        "SELECT id, username, email FROM users WHERE id = ?",
        (conflict["user_id"],)
    ).fetchone()

    requester = db.execute(
        "SELECT id, username, email FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    token = serializer.dumps({
        "booking_id": conflict["id"],
        "requester_user_id": requester["id"]
    })

    db.execute(
        """
        INSERT INTO release_requests (booking_id, requester_user_id, token, status)
        VALUES (?, ?, ?, 'pending')
        """,
        (conflict["id"], requester["id"], token)
    )
    db.commit()

    release_link = url_for("release_booking_by_token", token=token, _external=True)

    try:
        send_release_request_email(
            owner_email=owner["email"],
            owner_username=owner["username"],
            requester_username=requester["username"],
            room_name=room["name"],
            booking_date=conflict["booking_date"],
            start_time=conflict["start_time"],
            end_time=conflict["end_time"],
            release_link=release_link
        )
        flash("Запрос на освобождение аудитории отправлен.", "success")
    except Exception as e:
        app.logger.error(f"Release request email failed: {e}")
        flash("Не удалось отправить письмо владельцу брони.", "danger")

    return redirect(url_for("book_room", room_id=room_id))

@app.route("/booking/release/<token>")
def release_booking_by_token(token):
    db = get_db()

    try:
        data = serializer.loads(token)
        booking_id = data["booking_id"]
        requester_user_id = data["requester_user_id"]
    except Exception:
        flash("Ссылка недействительна.", "danger")
        return redirect(url_for("login"))

    release_request = db.execute(
        "SELECT * FROM release_requests WHERE token = ? AND status = 'pending'",
        (token,)
    ).fetchone()

    if not release_request:
        flash("Эта ссылка уже была использована или недействительна.", "warning")
        return redirect(url_for("login"))

    booking = db.execute(
        "SELECT * FROM bookings WHERE id = ?",
        (booking_id,)
    ).fetchone()

    if not booking:
        db.execute(
            "UPDATE release_requests SET status = 'booking_missing' WHERE token = ?",
            (token,)
        )
        db.commit()
        flash("Бронь уже отсутствует.", "info")
        return redirect(url_for("login"))

    owner = db.execute(
        "SELECT id, username, email FROM users WHERE id = ?",
        (booking["user_id"],)
    ).fetchone()

    requester = db.execute(
        "SELECT id, username, email FROM users WHERE id = ?",
        (requester_user_id,)
    ).fetchone()

    room = db.execute(
        "SELECT * FROM rooms WHERE id = ?",
        (booking["room_id"],)
    ).fetchone()

    booking_date = booking["booking_date"]
    start_time = booking["start_time"]
    end_time = booking["end_time"]

    db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    db.execute(
        "UPDATE release_requests SET status = 'approved' WHERE token = ?",
        (token,)
    )
    db.commit()

    try:
        send_release_success_email(
            to_email=requester["email"],
            requester_username=requester["username"],
            owner_username=owner["username"],
            room_name=room["name"],
            booking_date=booking_date,
            start_time=start_time,
            end_time=end_time
        )
    except Exception as e:
        app.logger.error(f"Release success email failed: {e}")

    return """
    <h2>Бронирование отменено</h2>
    <p>Вы успешно освободили аудиторию. Запрашивающий пользователь уже уведомлен.</p>
    """

with app.app_context():
    init_db()
    load_mail_settings_at_startup()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
    