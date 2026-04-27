import asyncio
import os
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg
import redis
import requests
from passlib.context import CryptContext

PWD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")


def load_env_files() -> None:
    root_dir = Path(__file__).resolve().parents[3]
    for file_name in (".env", ".env.dev"):
        env_path = root_dir / file_name
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


class TestOrders(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_env_files()

        cls.base_url = os.getenv("AUTH_TEST_BASE_URL", "http://localhost:8000").rstrip(
            "/"
        )
        cls.db_host = os.getenv("AUTH_TEST_DB_HOST", "localhost")
        cls.db_port = env_int("AUTH_TEST_DB_PORT", 5435)
        cls.redis_host = os.getenv("AUTH_TEST_REDIS_HOST", "localhost")
        cls.redis_port = env_int("AUTH_TEST_REDIS_PORT", 6379)
        cls.redis_db = env_int("AUTH_TEST_REDIS_DB", 0)

        db_user, db_password, db_name = cls.resolve_db_credentials()
        cls.db_user = db_user
        cls.db_password = db_password
        cls.db_name = db_name

        suffix = uuid4().hex[:10]
        cls.admin_email = f"qa-admin-{suffix}@example.com"
        cls.user_email = f"qa-user-{suffix}@example.com"
        cls.admin_password = "AdminTest#2026"
        cls.user_password = "UserTest#2026"
        cls.admin_username = f"qa_admin_{suffix}"
        cls.user_username = f"qa_user_{suffix}"
        cls.admin_phone_number = "+573001112233"
        cls.user_phone_number = os.getenv("PHONE", "2222222222")
        cls.notification_phone_number = os.getenv("PHONE")
        cls.notification_chat_id = f"777000001-{suffix}"
        cls.revoked_tokens: list[str] = []

        orders_db_user, orders_db_password, orders_db_name = (
            cls.resolve_orders_db_credentials()
        )
        cls.orders_db_user = orders_db_user
        cls.orders_db_password = orders_db_password
        cls.orders_db_name = orders_db_name
        cls.orders_db_host = os.getenv("ORDERS_TEST_DB_HOST", "localhost")
        cls.orders_db_port = env_int("ORDERS_TEST_DB_PORT", 5432)

        notifications_db_user, notifications_db_password, notifications_db_name = (
            cls.resolve_notifications_db_credentials()
        )
        cls.notifications_db_user = notifications_db_user
        cls.notifications_db_password = notifications_db_password
        cls.notifications_db_name = notifications_db_name
        cls.notifications_db_host = os.getenv("NOTIFICATIONS_TEST_DB_HOST", "localhost")
        cls.notifications_db_port = env_int("NOTIFICATIONS_TEST_DB_PORT", 5434)

        cls.wait_for_gateway_service()
        cls.create_admin_user_via_api()
        asyncio.run(cls.promote_admin_user_in_db())
        cls.user_token = cls.login_user()
        cls.admin_token = cls.login_admin()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            asyncio.run(cls.cleanup_users_in_db())
        finally:
            cls.cleanup_blacklist_tokens()

    @classmethod
    def resolve_db_credentials(cls) -> tuple[str, str, str]:
        user = os.getenv("POSTGRES_AUTH_USER", "")
        password = os.getenv("POSTGRES_AUTH_PASSWORD", "")
        database = os.getenv("POSTGRES_AUTH_DB", "")
        if user and password and database:
            return user, password, database

        auth_url = os.getenv("POSTGRES_AUTH_URL", "")
        if not auth_url:
            raise RuntimeError(
                "POSTGRES_AUTH_USER/POSTGRES_AUTH_PASSWORD/POSTGRES_AUTH_DB or POSTGRES_AUTH_URL is required"
            )

        normalized = auth_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        parsed = urlparse(normalized)
        if not (parsed.username and parsed.password and parsed.path):
            raise RuntimeError("POSTGRES_AUTH_URL is invalid")
        return parsed.username, parsed.password, parsed.path.lstrip("/")

    @classmethod
    def resolve_orders_db_credentials(cls) -> tuple[str, str, str]:
        user = os.getenv("POSTGRES_USER", "")
        password = os.getenv("POSTGRES_PASSWORD", "")
        database = os.getenv("POSTGRES_DB", "")
        if user and password and database:
            return user, password, database

        orders_url = os.getenv("DATABASE_URL", "")
        if not orders_url:
            raise RuntimeError(
                "POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB or DATABASE_URL is required"
            )

        normalized = orders_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        parsed = urlparse(normalized)
        if not (parsed.username and parsed.password and parsed.path):
            raise RuntimeError("DATABASE_URL is invalid")
        return parsed.username, parsed.password, parsed.path.lstrip("/")

    @classmethod
    def resolve_notifications_db_credentials(cls) -> tuple[str, str, str]:
        user = os.getenv("POSTGRES_NOTIFICATIONS_USER", "")
        password = os.getenv("POSTGRES_NOTIFICATIONS_PASSWORD", "")
        database = os.getenv("POSTGRES_NOTIFICATIONS_DB", "")
        if user and password and database:
            return user, password, database

        notifications_url = os.getenv("POSTGRES_NOTIFICATIONS_URL", "")
        if not notifications_url:
            raise RuntimeError(
                "POSTGRES_NOTIFICATIONS_USER/POSTGRES_NOTIFICATIONS_PASSWORD/POSTGRES_NOTIFICATIONS_DB or POSTGRES_NOTIFICATIONS_URL is required"
            )

        normalized = notifications_url.replace(
            "postgresql+asyncpg://", "postgresql://", 1
        )
        parsed = urlparse(normalized)
        if not (parsed.username and parsed.password and parsed.path):
            raise RuntimeError("POSTGRES_NOTIFICATIONS_URL is invalid")
        return parsed.username, parsed.password, parsed.path.lstrip("/")

    @classmethod
    async def get_db_conn(cls) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=cls.db_host,
            port=cls.db_port,
            user=cls.db_user,
            password=cls.db_password,
            database=cls.db_name,
        )

    @classmethod
    async def get_orders_db_conn(cls) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=cls.orders_db_host,
            port=cls.orders_db_port,
            user=cls.orders_db_user,
            password=cls.orders_db_password,
            database=cls.orders_db_name,
        )

    @classmethod
    async def get_notifications_db_conn(cls) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=cls.notifications_db_host,
            port=cls.notifications_db_port,
            user=cls.notifications_db_user,
            password=cls.notifications_db_password,
            database=cls.notifications_db_name,
        )

    @classmethod
    async def fetch_product_stock(cls, sku: str) -> int:
        conn = await cls.get_orders_db_conn()
        try:
            row = await conn.fetchrow("SELECT stock FROM products WHERE sku = $1", sku)
            if row is None:
                raise RuntimeError(f"SKU {sku} not found in products table")
            return int(row["stock"])
        finally:
            await conn.close()

    @classmethod
    async def ensure_telegram_subscription(cls, phone_number: str) -> None:
        conn = await cls.get_notifications_db_conn()
        try:
            await conn.execute(
                """
				INSERT INTO telegram_subscriptions (phone_number, chat_id, created_at, updated_at)
				VALUES ($1, $2, NOW(), NOW())
				ON CONFLICT (phone_number)
				DO UPDATE SET
					chat_id = EXCLUDED.chat_id,
					updated_at = NOW()
				""",
                phone_number,
                cls.notification_chat_id,
            )
        finally:
            await conn.close()

    @classmethod
    async def fetch_notifications_for_order(cls, order_id: str) -> list[asyncpg.Record]:
        conn = await cls.get_notifications_db_conn()
        try:
            rows = await conn.fetch(
                """
				SELECT order_id, customer, event_type, message, reason
				FROM notifications
				WHERE order_id = $1
				ORDER BY created_at DESC
				""",
                order_id,
            )
            return list(rows)
        finally:
            await conn.close()

    @classmethod
    async def promote_admin_user_in_db(cls) -> None:
        conn = await cls.get_db_conn()
        try:
            await conn.execute(
                """
				UPDATE users
				SET role = 'admin',
					username = $2,
					phone_number = $3
				WHERE email = $1
				""",
                cls.admin_email,
                cls.admin_username,
                cls.admin_phone_number,
            )
        finally:
            await conn.close()

    @classmethod
    def create_admin_user_via_api(cls) -> None:
        signup = requests.post(
            f"{cls.base_url}/auth/signup",
            json={
                "name": cls.admin_username,
                "email": cls.admin_email,
                "phone_number": cls.admin_phone_number,
                "password": cls.admin_password,
            },
            timeout=10,
        )
        if signup.status_code != 201:
            raise RuntimeError(
                f"Error creating admin seed user: {signup.status_code} - {signup.text}"
            )

    @classmethod
    async def cleanup_users_in_db(cls) -> None:
        conn = await cls.get_db_conn()
        try:
            await conn.execute(
                "DELETE FROM users WHERE email = ANY($1::text[])",
                [cls.admin_email, cls.user_email],
            )
        finally:
            await conn.close()

    @classmethod
    def cleanup_blacklist_tokens(cls) -> None:
        if not cls.revoked_tokens:
            return

        client = redis.Redis(
            host=cls.redis_host,
            port=cls.redis_port,
            db=cls.redis_db,
            decode_responses=True,
            socket_timeout=5,
        )
        try:
            keys = [f"blacklist:{token}" for token in set(cls.revoked_tokens)]
            if keys:
                client.delete(*keys)
        finally:
            client.close()

    @classmethod
    def wait_for_gateway_service(cls) -> None:
        deadline = time.time() + 120
        health_url = f"{cls.base_url}/health"
        while time.time() < deadline:
            try:
                response = requests.get(health_url, timeout=5)
                if response.status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(2)
        raise RuntimeError(f"api-gateway is not ready: {health_url}")

    @classmethod
    def login_user(cls) -> str:
        signup = requests.post(
            f"{cls.base_url}/auth/signup",
            json={
                "name": cls.user_username,
                "email": cls.user_email,
                "phone_number": cls.user_phone_number,
                "password": cls.user_password,
            },
            timeout=10,
        )
        if signup.status_code != 201:
            raise RuntimeError(
                f"Error creating user: {signup.status_code} - {signup.text}"
            )

        login = requests.post(
            f"{cls.base_url}/auth/login",
            json={"email": cls.user_email, "password": cls.user_password},
            timeout=10,
        )
        if login.status_code != 200:
            raise RuntimeError(
                f"Error logging user: {login.status_code} - {login.text}"
            )
        return login.json()["access_token"]

    @classmethod
    def login_admin(cls) -> str:
        login = requests.post(
            f"{cls.base_url}/auth/login",
            json={"email": cls.admin_email, "password": cls.admin_password},
            timeout=10,
        )
        if login.status_code != 200:
            raise RuntimeError(
                f"Error logging admin: {login.status_code} - {login.text}"
            )
        return login.json()["access_token"]

    def request_json(
        self,
        method: str,
        path: str,
        expected_status: int,
        token: str | None = None,
        payload: dict | None = None,
    ) -> dict | list:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.request(
            method=method,
            url=f"{self.base_url}{path}",
            json=payload,
            headers=headers,
            timeout=10,
        )

        self.assertEqual(
            response.status_code,
            expected_status,
            msg=f"Unexpected status for {method} {path}: {response.status_code} - {response.text}",
        )

        if not response.content:
            return {}
        return response.json()

    def test_01_user_gets_its_orders(self):
        response = self.request_json(
            method="GET",
            path="/orders/my_orders",
            expected_status=200,
            token=self.user_token,
        )
        self.assertIsInstance(response, list)

    def test_02_get_all_orders_as_admin(self):
        response = self.request_json(
            method="GET",
            path="/orders",
            expected_status=200,
            token=self.admin_token,
        )
        self.assertIsInstance(response, list)

    def test_03_user_cannot_get_others_orders(self):
        self.request_json(
            method="GET",
            path="/orders",
            expected_status=403,
            token=self.user_token,
        )

    def test_04_unauthenticated_user_cannot_create_orders(self):
        order_data = {
            "items": [{"sku": "12345", "qty": 2}],
        }
        self.request_json(
            method="POST",
            path="/orders",
            expected_status=401,
            payload=order_data,
        )

    def test_05_create_order_is_accepted_with_valid_schema(self):
        sku = "001-E"
        qty = 1
        stock_before = asyncio.run(self.fetch_product_stock(sku))

        order_data = {
            "items": [{"sku": sku, "qty": qty}],
        }
        create_response = self.request_json(
            method="POST",
            path="/orders",
            expected_status=202,
            token=self.user_token,
            payload=order_data,
        )
        order_id = create_response.get("order_id")
        self.assertIsNotNone(order_id)
        self.assertEqual(create_response.get("status"), "RECEIVED")

        expected_stock = stock_before - qty
        stock_after: int | None = None
        deadline = time.time() + 30
        while time.time() < deadline:
            stock_after = asyncio.run(self.fetch_product_stock(sku))
            if stock_after == expected_stock:
                break
            time.sleep(1)

        self.assertEqual(
            stock_after,
            expected_stock,
            msg=f"Inventory stock for {sku} did not decrease by {qty}. before={stock_before}, after={stock_after}",
        )

    def test_06_notification_is_persisted_for_created_order(self):
        if not self.notification_phone_number:
            self.skipTest("Skipping notification assertion because PHONE is not set")

        asyncio.run(self.ensure_telegram_subscription(self.notification_phone_number))

        order_data = {
            "items": [{"sku": "005-T", "qty": 1}],
        }
        create_response = self.request_json(
            method="POST",
            path="/orders",
            expected_status=202,
            token=self.user_token,
            payload=order_data,
        )

        order_id = create_response.get("order_id")
        self.assertIsNotNone(order_id)

        notifications: list[asyncpg.Record] = []
        deadline = time.time() + 30
        while time.time() < deadline:
            notifications = asyncio.run(self.fetch_notifications_for_order(order_id))
            if notifications:
                break
            time.sleep(1)

        self.assertTrue(
            notifications,
            msg=f"No notifications found for order_id={order_id}",
        )
        latest = notifications[0]
        self.assertEqual(latest["customer"], self.user_username)
        self.assertIn(latest["event_type"], ["order.created", "notification.error"])
        self.assertTrue(latest["message"])
        if latest["event_type"] == "order.created":
            self.assertIn("fue realizada con exito", latest["message"])
        if latest["event_type"] == "notification.error":
            self.assertTrue(latest["reason"])

        event_types = {row["event_type"] for row in notifications}
        self.assertTrue(
            event_types.intersection({"order.created", "notification.error"}),
            msg=(
                f"Expected notification event for order_id={order_id}; "
                f"got event types: {sorted(event_types)}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
