import os
import sqlite3
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

# Секретный код для регистрации админов (можно менять через env)
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "SuperAdmin2026!")

DATABASE = "booking.db"

# База данных

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
    """)
    conn.commit()
    conn.close()


def check_time_conflict(room_id, booking_date, start_time, end_time, exclude_booking_id=None):
    """
    Проверить, пересекается ли новое бронирование с существующими.
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


# Auth: регистрация / вход / выход

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
            errors.append("Имя пользователя должно быть не менее 3 символов.")
        if not email or "@" not in email:
            errors.append("Введите корректный email.")
        if len(password) < 6:
            errors.append("Пароль должен быть не менее 6 символов.")
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
            flash(f"Добро пожаловать, {username}!", "success")
            return redirect(url_for("rooms"))
        else:
            flash("Неверное имя пользователя или пароль.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("login"))


# Комнаты

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


# Бронирование

@app.route("/book/<int:room_id>", methods=["GET", "POST"])
@login_required
def book_room(room_id):
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if not room:
        flash("Комната не найдена.", "danger")
        return redirect(url_for("rooms"))

    if request.method == "POST":
        booking_date = request.form.get("booking_date")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        purpose = request.form.get("purpose", "").strip()

        errors = []
        if not booking_date:
            errors.append("Выберите дату.")
        if not start_time or not end_time:
            errors.append("Укажите время начала и окончания.")
        if start_time and end_time and start_time >= end_time:
            errors.append("Время окончания должно быть позже времени начала.")

        # Проверка на прошедшую дату
        if booking_date:
            try:
                bd = datetime.strptime(booking_date, "%Y-%m-%d").date()
                if bd < date.today():
                    errors.append("Нельзя бронировать на прошедшую дату.")
            except ValueError:
                errors.append("Некорректная дата.")

        if not errors and check_time_conflict(room_id, booking_date, start_time, end_time):
            errors.append("На выбранное время уже есть бронирование.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("book.html", room=room)

        db.execute(
            """INSERT INTO bookings (room_id, user_id, booking_date, start_time, end_time, purpose)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (room_id, session["user_id"], booking_date, start_time, end_time, purpose)
        )
        db.commit()
        flash("Бронирование создано!", "success")
        return redirect(url_for("dashboard"))

    return render_template("book.html", room=room)


# Календарь занятости

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

    # Нельзя отменить прошедшее бронирование
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

    return render_template("admin.html", rooms=rooms_from_db, users=users, bookings=all_bookings)


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
        flash("Название комнаты обязательно.", "danger")
        return redirect(url_for("admin_panel"))

    db = get_db()
    db.execute(
        """INSERT INTO rooms (name, description, capacity, floor, equipment, image_url)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, description, capacity, floor, equipment, image_url)
    )
    db.commit()
    flash(f"Комната «{name}» добавлена.", "success")
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
        flash(f"Комната теперь {status}.", "info")
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
        role = "администратором" if new_val else "пользователем"
        flash(f"Пользователь теперь {role}.", "info")
    return redirect(url_for("admin_panel"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
