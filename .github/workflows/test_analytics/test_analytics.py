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


class AnalyticsEndpointsTest(unittest.TestCase):
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
        cls.phone_number = "+573001112233"
        cls.revoked_tokens: list[str] = []

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
    async def get_db_conn(cls) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=cls.db_host,
            port=cls.db_port,
            user=cls.db_user,
            password=cls.db_password,
            database=cls.db_name,
        )

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
                cls.phone_number,
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
                "phone_number": cls.phone_number,
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
                "phone_number": cls.phone_number,
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
    ) -> dict:
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

    def test_01_user_creates_orders(self) -> None:
        orders_payload = [
            {"items": [{"sku": "001-E", "qty": 2}, {"sku": "005-T", "qty": 1}]},
            {"items": [{"sku": "003-E", "qty": 3}]},
            {"items": [{"sku": "010-A", "qty": 1}, {"sku": "012-S", "qty": 2}]},
        ]

        for payload in orders_payload:
            response = self.request_json(
                "POST",
                "/orders/",
                expected_status=202,
                token=self.user_token,
                payload=payload,
            )
            self.assertTrue(response.get("order_id"))
            self.assertEqual(response.get("status"), "RECEIVED")

    def test_02_admin_creates_orders(self) -> None:
        orders_payload = [
            {"items": [{"sku": "008-P", "qty": 5}]},
            {"items": [{"sku": "004-P", "qty": 2}, {"sku": "020-P", "qty": 3}]},
        ]

        for payload in orders_payload:
            response = self.request_json(
                "POST",
                "/orders/",
                expected_status=202,
                token=self.admin_token,
                payload=payload,
            )
            self.assertTrue(response.get("order_id"))
            self.assertEqual(response.get("status"), "RECEIVED")

    def test_03_admin_gets_analytics(self) -> None:
        time.sleep(5)

        response = self.request_json(
            "GET",
            "/analytics/",
            expected_status=200,
            token=self.admin_token,
        )
        print(
            "\n--- Analytics endpoint response ---\n",
            response,
            "\n-------------------------------\n",
        )

        self.assertIsInstance(response, dict)
        self.assertIn("total_orders_seen", response)
        self.assertIn("top_products", response)
        self.assertIn("most_frequent_customer", response)
        self.assertIn("error_rates", response)
        self.assertIn("avg_times_ms", response)
        self.assertGreaterEqual(response["total_orders_seen"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
