from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "zaj_bank.sqlite3"
SESSION_COOKIE = "zaj_session"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 210_000
SMS_CODE_MINUTES = 5
SMS_TIMEOUT_SECONDS = 12
MARKET_PRODUCTS = {
    "ZAJ Phone X": {"category": "Смартфоны", "price": 389_990},
    "Ноутбук Atlas 14": {"category": "Техника", "price": 549_000},
    "Наушники Pulse Air": {"category": "Аудио", "price": 49_900},
    "Умные часы Nomad": {"category": "Гаджеты", "price": 119_000},
    "Электросамокат City": {"category": "Транспорт", "price": 219_500},
    "Пылесос Home Pro": {"category": "Дом", "price": 87_400},
}


class SmsDeliveryError(RuntimeError):
    pass


def load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    _, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, digest_hex)


def normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return f"+{digits}" if digits else ""


def normalize_iin(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def phone_email(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return f"{digits}@phone.zaj.local"


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    # External USB volumes can reject SQLite rollback-journal writes. This keeps
    # the prototype database local and writable on the shared workspace drive.
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE COLLATE NOCASE,
              phone TEXT,
              iin TEXT,
              sms_verified INTEGER NOT NULL DEFAULT 0,
              password_salt TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              token_hash TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              slug TEXT NOT NULL,
              name TEXT NOT NULL,
              balance INTEGER NOT NULL,
              income INTEGER NOT NULL DEFAULT 0,
              spending INTEGER NOT NULL DEFAULT 0,
              cashback INTEGER NOT NULL DEFAULT 0,
              UNIQUE(user_id, slug)
            );

            CREATE TABLE IF NOT EXISTS programs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              amount INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              account_slug TEXT NOT NULL,
              title TEXT NOT NULL,
              subtitle TEXT NOT NULL,
              amount INTEGER NOT NULL,
              direction TEXT NOT NULL CHECK(direction IN ('in', 'out', 'hold')),
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS market_orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              account_slug TEXT NOT NULL,
              product_title TEXT NOT NULL,
              category TEXT NOT NULL,
              amount INTEGER NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_registrations (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              phone TEXT NOT NULL,
              iin TEXT NOT NULL,
              email TEXT NOT NULL,
              password_salt TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              code_hash TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_logins (
              id TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              phone TEXT NOT NULL,
              code_hash TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );
            """
        )
        ensure_column(connection, "users", "phone", "TEXT")
        ensure_column(connection, "users", "iin", "TEXT")
        ensure_column(connection, "users", "sms_verified", "INTEGER NOT NULL DEFAULT 0")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_phone_unique ON users(phone) WHERE phone IS NOT NULL")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_iin_unique ON users(iin) WHERE iin IS NOT NULL")


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in connection.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_default_private_data(connection: sqlite3.Connection, user_id: int) -> None:
    accounts = [
        ("personal", "Личный счет", 1_842_500, 384_000, 142_300, 12_840),
        ("salary", "Доходный счет", 2_430_000, 920_000, 284_100, 18_330),
        ("social", "Социальные выплаты", 238_700, 82_200, 36_400, 3_210),
    ]
    programs = [
        ("Адресная помощь", "Зачисление ожидается 25 мая", 64_000),
        ("Субсидия ЖКХ", "Документы приняты", 18_200),
        ("Налоговый вычет", "Проверка 2 из 3", 92_500),
    ]
    transactions = [
        ("personal", "Зачисление зарплаты", "09:18 · Работодатель", 384_000, "in"),
        ("personal", "Оплата ЖКХ", "08:42 · Коммунальные услуги", -21_600, "out"),
        ("social", "Адресная помощь", "В обработке · Минтруд", 64_000, "hold"),
    ]
    connection.executemany(
        """
        INSERT INTO accounts (user_id, slug, name, balance, income, spending, cashback)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(user_id, *account) for account in accounts],
    )
    connection.executemany(
        "INSERT INTO programs (user_id, title, status, amount) VALUES (?, ?, ?, ?)",
        [(user_id, *program) for program in programs],
    )
    connection.executemany(
        """
        INSERT INTO transactions (user_id, account_slug, title, subtitle, amount, direction, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(user_id, *transaction, iso_now()) for transaction in transactions],
    )


def serialize_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "iin": row["iin"],
    }


def dashboard(connection: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    accounts = [
        dict(row)
        for row in connection.execute(
            """
            SELECT slug, name, balance, income, spending, cashback
            FROM accounts
            WHERE user_id = ?
            ORDER BY id
            """,
            (user_id,),
        )
    ]
    programs = [
        dict(row)
        for row in connection.execute(
            "SELECT title, status, amount FROM programs WHERE user_id = ? ORDER BY id",
            (user_id,),
        )
    ]
    transactions = [
        dict(row)
        for row in connection.execute(
            """
            SELECT title, subtitle, amount, direction, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 8
            """,
            (user_id,),
        )
    ]
    orders = [
        dict(row)
        for row in connection.execute(
            """
            SELECT product_title, category, amount, status, created_at
            FROM market_orders
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 6
            """,
            (user_id,),
        )
    ]
    return {"accounts": accounts, "programs": programs, "transactions": transactions, "orders": orders}


class ZajBankHandler(BaseHTTPRequestHandler):
    server_version = "ZAJBank/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/me":
            self.handle_me()
            return
        if parsed.path == "/api/dashboard":
            self.handle_dashboard()
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        routes = {
            "/api/register/start": self.handle_register_start,
            "/api/register/verify": self.handle_register_verify,
            "/api/login/start": self.handle_login_start,
            "/api/login/verify": self.handle_login_verify,
            "/api/login": self.handle_login,
            "/api/logout": self.handle_logout,
            "/api/transfer": self.handle_transfer,
            "/api/service/pay": self.handle_service_pay,
            "/api/market/buy": self.handle_market_buy,
        }
        handler = routes.get(parsed.path)
        if handler:
            handler()
            return
        self.send_json({"error": "Маршрут не найден"}, HTTPStatus.NOT_FOUND)

    def serve_static(self, path: str) -> None:
        clean_path = path.lstrip("/") or "index.html"
        target = (ROOT / clean_path).resolve()
        if not str(target).startswith(str(ROOT)) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if target.name.endswith((".html", ".js", ".css")) else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def handle_me(self) -> None:
        user = self.current_user()
        if not user:
            self.send_json({"error": "Нужен вход"}, HTTPStatus.UNAUTHORIZED)
            return
        with db() as connection:
            self.send_json({"user": serialize_user(user), "dashboard": dashboard(connection, user["id"])})

    def handle_dashboard(self) -> None:
        user = self.current_user()
        if not user:
            self.send_json({"error": "Нужен вход"}, HTTPStatus.UNAUTHORIZED)
            return
        with db() as connection:
            self.send_json({"dashboard": dashboard(connection, user["id"])})

    def handle_register_start(self) -> None:
        payload = self.read_json()
        name = str(payload.get("name", "")).strip()
        phone = normalize_phone(str(payload.get("phone", "")).strip())
        iin = normalize_iin(str(payload.get("iin", "")).strip())
        password = str(payload.get("password", "")) or secrets.token_urlsafe(18)

        if len(name) < 2:
            self.send_json({"error": "Введите имя"}, HTTPStatus.BAD_REQUEST)
            return
        if len(phone) < 11 or len(phone) > 16:
            self.send_json({"error": "Введите корректный номер телефона"}, HTTPStatus.BAD_REQUEST)
            return
        if iin and len(iin) != 12:
            self.send_json({"error": "ИИН должен состоять из 12 цифр"}, HTTPStatus.BAD_REQUEST)
            return

        email = phone_email(phone)
        salt, password_hash = hash_password(password)
        code = f"{secrets.randbelow(900000) + 100000}"
        challenge_id = secrets.token_urlsafe(18)
        expires_at = utcnow() + timedelta(minutes=SMS_CODE_MINUTES)

        with db() as connection:
            existing = connection.execute("SELECT id FROM users WHERE phone = ? OR email = ?", (phone, email)).fetchone()
            if not existing and iin:
                existing = connection.execute("SELECT id FROM users WHERE iin = ?", (iin,)).fetchone()
            if existing:
                self.send_json({"error": "Пользователь с таким телефоном уже есть"}, HTTPStatus.CONFLICT)
                return

            if iin:
                connection.execute("DELETE FROM pending_registrations WHERE phone = ? OR iin = ?", (phone, iin))
            else:
                connection.execute("DELETE FROM pending_registrations WHERE phone = ?", (phone,))
            connection.execute(
                """
                INSERT INTO pending_registrations
                (id, name, phone, iin, email, password_salt, password_hash, code_hash, attempts, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    challenge_id,
                    name,
                    phone,
                    iin,
                    email,
                    salt,
                    password_hash,
                    hash_token(code),
                    iso_now(),
                    expires_at.isoformat(),
                ),
            )

        try:
            sms_delivery = self.send_sms(phone, code)
        except SmsDeliveryError as error:
            with db() as connection:
                connection.execute("DELETE FROM pending_registrations WHERE id = ?", (challenge_id,))
            self.send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return

        self.send_json(
            {
                "challengeId": challenge_id,
                "expiresIn": SMS_CODE_MINUTES * 60,
                "smsMode": sms_delivery["mode"],
                "demoCode": code if sms_delivery["mode"] == "demo" else None,
            }
        )

    def handle_register_verify(self) -> None:
        payload = self.read_json()
        challenge_id = str(payload.get("challengeId", "")).strip()
        code = "".join(ch for ch in str(payload.get("code", "")) if ch.isdigit())

        if not challenge_id or len(code) != 6:
            self.send_json({"error": "Введите 6-значный SMS-код"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            with db() as connection:
                pending = connection.execute(
                    "SELECT * FROM pending_registrations WHERE id = ?",
                    (challenge_id,),
                ).fetchone()
                if not pending:
                    self.send_json({"error": "SMS-код не найден. Запросите новый код."}, HTTPStatus.BAD_REQUEST)
                    return
                if pending["expires_at"] <= iso_now():
                    connection.execute("DELETE FROM pending_registrations WHERE id = ?", (challenge_id,))
                    self.send_json({"error": "SMS-код истек. Запросите новый код."}, HTTPStatus.BAD_REQUEST)
                    return
                if pending["attempts"] >= 5:
                    self.send_json({"error": "Слишком много попыток. Запросите новый код."}, HTTPStatus.TOO_MANY_REQUESTS)
                    return
                if not hmac.compare_digest(pending["code_hash"], hash_token(code)):
                    connection.execute(
                        "UPDATE pending_registrations SET attempts = attempts + 1 WHERE id = ?",
                        (challenge_id,),
                    )
                    self.send_json({"error": "Неверный SMS-код"}, HTTPStatus.BAD_REQUEST)
                    return

                cursor = connection.execute(
                    """
                    INSERT INTO users
                    (name, email, phone, iin, sms_verified, password_salt, password_hash, created_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        pending["name"],
                        pending["email"],
                        pending["phone"],
                        pending["iin"] or None,
                        pending["password_salt"],
                        pending["password_hash"],
                        iso_now(),
                    ),
                )
                user_id = int(cursor.lastrowid)
                create_default_private_data(connection, user_id)
                connection.execute("DELETE FROM pending_registrations WHERE id = ?", (challenge_id,))
                token = self.create_session(connection, user_id)
                user = connection.execute(
                    "SELECT id, name, email, phone, iin FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
                self.send_json(
                    {"user": serialize_user(user), "dashboard": dashboard(connection, user_id)},
                    cookie=self.session_cookie(token),
                )
        except sqlite3.IntegrityError:
            self.send_json({"error": "Такой телефон уже зарегистрирован"}, HTTPStatus.CONFLICT)

    def handle_login_start(self) -> None:
        payload = self.read_json()
        phone = normalize_phone(str(payload.get("phone", "")).strip())

        if len(phone) < 11 or len(phone) > 16:
            self.send_json({"error": "Введите корректный номер телефона"}, HTTPStatus.BAD_REQUEST)
            return

        code = f"{secrets.randbelow(900000) + 100000}"
        challenge_id = secrets.token_urlsafe(18)
        expires_at = utcnow() + timedelta(minutes=SMS_CODE_MINUTES)

        with db() as connection:
            user = connection.execute(
                "SELECT id, phone FROM users WHERE phone = ?",
                (phone,),
            ).fetchone()
            if not user:
                self.send_json({"error": "Аккаунт с таким телефоном не найден"}, HTTPStatus.NOT_FOUND)
                return

            connection.execute("DELETE FROM pending_logins WHERE user_id = ?", (user["id"],))
            connection.execute(
                """
                INSERT INTO pending_logins
                (id, user_id, phone, code_hash, attempts, created_at, expires_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    challenge_id,
                    user["id"],
                    phone,
                    hash_token(code),
                    iso_now(),
                    expires_at.isoformat(),
                ),
            )

        try:
            sms_delivery = self.send_sms(phone, code)
        except SmsDeliveryError as error:
            with db() as connection:
                connection.execute("DELETE FROM pending_logins WHERE id = ?", (challenge_id,))
            self.send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
            return

        self.send_json(
            {
                "challengeId": challenge_id,
                "expiresIn": SMS_CODE_MINUTES * 60,
                "smsMode": sms_delivery["mode"],
                "demoCode": code if sms_delivery["mode"] == "demo" else None,
            }
        )

    def handle_login_verify(self) -> None:
        payload = self.read_json()
        challenge_id = str(payload.get("challengeId", "")).strip()
        code = "".join(ch for ch in str(payload.get("code", "")) if ch.isdigit())

        if not challenge_id or len(code) != 6:
            self.send_json({"error": "Введите 6-значный SMS-код"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as connection:
            pending = connection.execute(
                "SELECT * FROM pending_logins WHERE id = ?",
                (challenge_id,),
            ).fetchone()
            if not pending:
                self.send_json({"error": "SMS-код не найден. Запросите новый код."}, HTTPStatus.BAD_REQUEST)
                return
            if pending["expires_at"] <= iso_now():
                connection.execute("DELETE FROM pending_logins WHERE id = ?", (challenge_id,))
                self.send_json({"error": "SMS-код истек. Запросите новый код."}, HTTPStatus.BAD_REQUEST)
                return
            if pending["attempts"] >= 5:
                self.send_json({"error": "Слишком много попыток. Запросите новый код."}, HTTPStatus.TOO_MANY_REQUESTS)
                return
            if not hmac.compare_digest(pending["code_hash"], hash_token(code)):
                connection.execute(
                    "UPDATE pending_logins SET attempts = attempts + 1 WHERE id = ?",
                    (challenge_id,),
                )
                self.send_json({"error": "Неверный SMS-код"}, HTTPStatus.BAD_REQUEST)
                return

            user = connection.execute(
                "SELECT id, name, email, phone, iin FROM users WHERE id = ?",
                (pending["user_id"],),
            ).fetchone()
            if not user:
                connection.execute("DELETE FROM pending_logins WHERE id = ?", (challenge_id,))
                self.send_json({"error": "Аккаунт не найден"}, HTTPStatus.NOT_FOUND)
                return

            connection.execute("DELETE FROM pending_logins WHERE id = ?", (challenge_id,))
            token = self.create_session(connection, user["id"])
            self.send_json(
                {"user": serialize_user(user), "dashboard": dashboard(connection, user["id"])},
                cookie=self.session_cookie(token),
            )

    def handle_login(self) -> None:
        payload = self.read_json()
        phone = normalize_phone(str(payload.get("phone", "")).strip())
        login = str(payload.get("phone", "")).strip().lower()
        password = str(payload.get("password", ""))

        with db() as connection:
            user = connection.execute(
                """
                SELECT id, name, email, phone, iin, password_salt, password_hash
                FROM users
                WHERE phone = ? OR email = ?
                """,
                (phone, login),
            ).fetchone()
            if not user or not verify_password(password, user["password_salt"], user["password_hash"]):
                self.send_json({"error": "Неверный телефон или пароль"}, HTTPStatus.UNAUTHORIZED)
                return
            token = self.create_session(connection, user["id"])
            self.send_json(
                {"user": serialize_user(user), "dashboard": dashboard(connection, user["id"])},
                cookie=self.session_cookie(token),
            )

    def handle_logout(self) -> None:
        token = self.session_token()
        if token:
            with db() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
        expired = f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
        self.send_json({"ok": True}, cookie=expired)

    def handle_transfer(self) -> None:
        user = self.current_user()
        if not user:
            self.send_json({"error": "Нужен вход"}, HTTPStatus.UNAUTHORIZED)
            return

        payload = self.read_json()
        recipient = str(payload.get("recipient", "")).strip()
        source = str(payload.get("source", "")).strip()

        try:
            amount = int(payload.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0

        if len(recipient) < 2:
            self.send_json({"error": "Введите получателя"}, HTTPStatus.BAD_REQUEST)
            return
        if amount < 500:
            self.send_json({"error": "Минимальная сумма перевода ₸ 500"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as connection:
            account = connection.execute(
                "SELECT slug, name, balance, spending FROM accounts WHERE user_id = ? AND slug = ?",
                (user["id"], source),
            ).fetchone()
            if not account:
                self.send_json({"error": "Счет не найден"}, HTTPStatus.BAD_REQUEST)
                return
            if account["balance"] < amount:
                self.send_json({"error": "Недостаточно средств"}, HTTPStatus.BAD_REQUEST)
                return

            connection.execute(
                "UPDATE accounts SET balance = balance - ?, spending = spending + ? WHERE user_id = ? AND slug = ?",
                (amount, amount, user["id"], source),
            )
            connection.execute(
                """
                INSERT INTO transactions (user_id, account_slug, title, subtitle, amount, direction, created_at)
                VALUES (?, ?, ?, ?, ?, 'out', ?)
                """,
                (
                    user["id"],
                    source,
                    f"Перевод: {recipient}",
                    f"Только что · {account['name']}",
                    -amount,
                    iso_now(),
                ),
            )
            self.send_json({"dashboard": dashboard(connection, user["id"])})

    def handle_market_buy(self) -> None:
        user = self.current_user()
        if not user:
            self.send_json({"error": "Нужен вход"}, HTTPStatus.UNAUTHORIZED)
            return

        payload = self.read_json()
        product_title = str(payload.get("product", "")).strip()
        source = str(payload.get("source", "personal")).strip() or "personal"
        product = MARKET_PRODUCTS.get(product_title)
        if not product:
            self.send_json({"error": "Товар не найден"}, HTTPStatus.BAD_REQUEST)
            return

        amount = int(product["price"])
        cashback = max(100, int(amount * 0.02))
        with db() as connection:
            account = connection.execute(
                "SELECT slug, name, balance FROM accounts WHERE user_id = ? AND slug = ?",
                (user["id"], source),
            ).fetchone()
            if not account:
                self.send_json({"error": "Счет не найден"}, HTTPStatus.BAD_REQUEST)
                return
            if account["balance"] < amount:
                self.send_json({"error": "Недостаточно средств для покупки"}, HTTPStatus.BAD_REQUEST)
                return

            connection.execute(
                """
                UPDATE accounts
                SET balance = balance - ?, spending = spending + ?, cashback = cashback + ?
                WHERE user_id = ? AND slug = ?
                """,
                (amount, amount, cashback, user["id"], source),
            )
            connection.execute(
                """
                INSERT INTO market_orders
                (user_id, account_slug, product_title, category, amount, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    source,
                    product_title,
                    str(product["category"]),
                    amount,
                    "Оплачено · доставка формируется",
                    iso_now(),
                ),
            )
            connection.execute(
                """
                INSERT INTO transactions (user_id, account_slug, title, subtitle, amount, direction, created_at)
                VALUES (?, ?, ?, ?, ?, 'out', ?)
                """,
                (
                    user["id"],
                    source,
                    f"Маркет: {product_title}",
                    f"ZAJ Market · {account['name']}",
                    -amount,
                    iso_now(),
                ),
            )
            self.send_json({"dashboard": dashboard(connection, user["id"])})

    def handle_service_pay(self) -> None:
        user = self.current_user()
        if not user:
            self.send_json({"error": "Нужен вход"}, HTTPStatus.UNAUTHORIZED)
            return

        payload = self.read_json()
        service = str(payload.get("service", "")).strip()
        source = str(payload.get("source", "")).strip()
        try:
            amount = int(payload.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0

        if service not in {"Налоги", "ЖКХ", "Школа", "Транспорт"}:
            self.send_json({"error": "Услуга не найдена"}, HTTPStatus.BAD_REQUEST)
            return
        if amount < 300:
            self.send_json({"error": "Минимальная сумма платежа ₸ 300"}, HTTPStatus.BAD_REQUEST)
            return

        with db() as connection:
            account = connection.execute(
                "SELECT slug, name, balance FROM accounts WHERE user_id = ? AND slug = ?",
                (user["id"], source),
            ).fetchone()
            if not account:
                self.send_json({"error": "Счет не найден"}, HTTPStatus.BAD_REQUEST)
                return
            if account["balance"] < amount:
                self.send_json({"error": "Недостаточно средств"}, HTTPStatus.BAD_REQUEST)
                return

            connection.execute(
                "UPDATE accounts SET balance = balance - ?, spending = spending + ? WHERE user_id = ? AND slug = ?",
                (amount, amount, user["id"], source),
            )
            connection.execute(
                """
                INSERT INTO transactions (user_id, account_slug, title, subtitle, amount, direction, created_at)
                VALUES (?, ?, ?, ?, ?, 'out', ?)
                """,
                (
                    user["id"],
                    source,
                    f"Платеж: {service}",
                    f"Городские сервисы · {account['name']}",
                    -amount,
                    iso_now(),
                ),
            )
            self.send_json({"dashboard": dashboard(connection, user["id"])})

    def create_session(self, connection: sqlite3.Connection, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(days=SESSION_DAYS)
        connection.execute(
            """
            INSERT INTO sessions (user_id, token_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, hash_token(token), iso_now(), expires_at.isoformat()),
        )
        return token

    def current_user(self) -> sqlite3.Row | None:
        token = self.session_token()
        if not token:
            return None
        with db() as connection:
            return connection.execute(
                """
                SELECT users.id, users.name, users.email, users.phone, users.iin
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (hash_token(token), iso_now()),
            ).fetchone()

    def session_token(self) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        cookie = SimpleCookie(cookie_header)
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def session_cookie(self, token: str) -> str:
        max_age = SESSION_DAYS * 24 * 60 * 60
        return f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"

    def send_sms(self, phone: str, code: str) -> dict[str, str | None]:
        provider = os.environ.get("SMS_PROVIDER", "demo").strip().lower() or "demo"
        message = f"ZAJ BANK: {code} - kod podtverzhdeniya. Nikomu ne soobshchaite kod."
        if provider in {"demo", "local"}:
            print(f"[SMS demo] ZAJ BANK code for {phone}: {code}")
            return {"mode": "demo", "sid": None}
        if provider == "twilio":
            return self.send_sms_twilio(phone, message)
        raise SmsDeliveryError("Неизвестный SMS_PROVIDER. Используйте demo или twilio.")

    def send_sms_twilio(self, phone: str, message: str) -> dict[str, str | None]:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        from_number = os.environ.get("TWILIO_FROM", "").strip()
        messaging_service_sid = os.environ.get("TWILIO_MESSAGING_SERVICE_SID", "").strip()

        if not account_sid or not auth_token:
            raise SmsDeliveryError("Twilio не настроен: нужны TWILIO_ACCOUNT_SID и TWILIO_AUTH_TOKEN.")
        if not from_number and not messaging_service_sid:
            raise SmsDeliveryError("Twilio не настроен: укажите TWILIO_FROM или TWILIO_MESSAGING_SERVICE_SID.")

        payload = {
            "To": phone,
            "Body": message,
        }
        if messaging_service_sid:
            payload["MessagingServiceSid"] = messaging_service_sid
        else:
            payload["From"] = from_number

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        auth = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
        request = Request(
            url,
            data=urlencode(payload).encode("utf-8"),
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=SMS_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
                return {"mode": "twilio", "sid": str(data.get("sid", "")) or None}
        except HTTPError as error:
            detail = self.twilio_error_detail(error)
            raise SmsDeliveryError(f"Twilio не отправил SMS: {detail}") from error
        except (URLError, TimeoutError) as error:
            raise SmsDeliveryError("Twilio недоступен. Проверьте интернет и настройки провайдера.") from error
        except json.JSONDecodeError as error:
            raise SmsDeliveryError("Twilio вернул неожиданный ответ.") from error

    def twilio_error_detail(self, error: HTTPError) -> str:
        try:
            raw = error.read().decode("utf-8")
            data = json.loads(raw)
            return str(data.get("message") or data.get("error") or f"HTTP {error.code}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return f"HTTP {error.code}"

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        cookie: str | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {format % args}")


def main() -> None:
    load_env_file()
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 4173), ZajBankHandler)
    print("ZAJ BANK is running: http://127.0.0.1:4173")
    print(f"SQLite database: {DB_PATH}")
    print(f"SMS provider: {os.environ.get('SMS_PROVIDER', 'demo')}")
    server.serve_forever()


if __name__ == "__main__":
    main()
