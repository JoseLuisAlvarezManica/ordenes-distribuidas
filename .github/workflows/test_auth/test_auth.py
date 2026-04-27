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


class AuthEndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_env_files()

        cls.base_url = os.getenv("AUTH_TEST_BASE_URL", "http://localhost:8004").rstrip(
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

        cls.revoked_tokens = []

        cls.wait_for_auth_service()
        asyncio.run(cls.seed_admin_directly_in_db())

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
    async def seed_admin_directly_in_db(cls) -> None:
        conn = await cls.get_db_conn()
        try:
            await conn.execute(
                """
				INSERT INTO users (username, email, phone_number, password, role)
				VALUES ($1, $2, $3, $4, $5)
				ON CONFLICT (email)
				DO UPDATE SET
					username = EXCLUDED.username,
					phone_number = EXCLUDED.phone_number,
					password = EXCLUDED.password,
					role = EXCLUDED.role
				""",
                cls.admin_username,
                cls.admin_email,
                cls.phone_number,
                PWD_CONTEXT.hash(cls.admin_password),
                "admin",
            )
        finally:
            await conn.close()

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
    def wait_for_auth_service(cls) -> None:
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

        raise RuntimeError(f"auth-service is not ready: {health_url}")

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

    def test_01_admin_login_from_direct_db_seed(self) -> None:
        login_data = self.request_json(
            "POST",
            "/auth/login",
            expected_status=200,
            payload={"email": self.admin_email, "password": self.admin_password},
        )

        admin_token = login_data.get("access_token")
        self.assertTrue(admin_token)
        self.assertEqual(login_data.get("token_type"), "bearer")

        me_data = self.request_json(
            "GET", "/auth/me", expected_status=200, token=admin_token
        )
        self.assertEqual(me_data.get("email"), self.admin_email)
        self.assertEqual(me_data.get("role"), "admin")

    def test_02_user_auth_endpoints_workflow(self) -> None:
        signup_data = self.request_json(
            "POST",
            "/auth/signup",
            expected_status=201,
            payload={
                "name": self.user_username,
                "email": self.user_email,
                "phone_number": self.phone_number,
                "password": self.user_password,
            },
        )
        self.assertIn("User created", signup_data.get("detail", ""))

        login_data = self.request_json(
            "POST",
            "/auth/login",
            expected_status=200,
            payload={"email": self.user_email, "password": self.user_password},
        )
        user_token = login_data.get("access_token")
        self.assertTrue(user_token)
        self.assertEqual(login_data.get("token_type"), "bearer")

        me_data = self.request_json(
            "GET", "/auth/me", expected_status=200, token=user_token
        )
        self.assertEqual(me_data.get("email"), self.user_email)
        self.assertEqual(me_data.get("role"), "user")

        refresh_data = self.request_json(
            "POST", "/auth/refresh", expected_status=200, token=user_token
        )
        refreshed_token = refresh_data.get("access_token")
        self.assertTrue(refreshed_token)
        self.assertNotEqual(user_token, refreshed_token)

        self.__class__.revoked_tokens.append(user_token)

        revoked_response = requests.get(
            f"{self.base_url}/auth/me",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=10,
        )
        self.assertEqual(revoked_response.status_code, 401)

        logout_data = self.request_json(
            "POST", "/auth/logout", expected_status=200, token=refreshed_token
        )
        self.assertIn("Logged out", logout_data.get("detail", ""))
        self.__class__.revoked_tokens.append(refreshed_token)

        after_logout_response = requests.get(
            f"{self.base_url}/auth/me",
            headers={"Authorization": f"Bearer {refreshed_token}"},
            timeout=10,
        )
        self.assertEqual(after_logout_response.status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
