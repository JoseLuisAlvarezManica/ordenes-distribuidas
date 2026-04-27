import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def _load_env_var(env_path: Path, variable_name: str) -> str | None:
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == variable_name and value:
            return value

    return None


def _load_env_support_number(env_path: Path) -> str | None:
    return _load_env_var(env_path, "SUPPORT_NUMBER")


def _post_json(url: str, payload: dict, timeout: float) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def _get_json(
    url: str,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def build_seed_orders(support_number: str | None) -> list[dict]:
    # Al menos dos ordenes usan SUPPORT_NUMBER desde .env.
    phone_a = support_number or "+522224148006"
    phone_b = support_number or "+522224148006"

    return [
        {
            "customer": "Carlos",
            "phone_number": phone_a,
            "items": [
                {"sku": "001-E", "qty": 1},
                {"sku": "005-T", "qty": 2},
            ],
        },
        {
            "customer": "Laura",
            "phone_number": "+573001112234",
            "items": [
                {"sku": "003-E", "qty": 1},
                {"sku": "010-A", "qty": 1},
            ],
        },
        {
            "customer": "Carlos",
            "phone_number": phone_b,
            "items": [
                {"sku": "008-P", "qty": 3},
                {"sku": "009-P", "qty": 2},
            ],
        },
        {
            "customer": "Andrea",
            "phone_number": "+573001112235",
            "items": [
                {"sku": "014-T", "qty": 1},
                {"sku": "015-T", "qty": 1},
            ],
        },
        {
            "customer": "Mateo",
            "phone_number": "+573001112236",
            "items": [
                {"sku": "025-A", "qty": 1},
                {"sku": "021-W", "qty": 2},
            ],
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed de 5 ordenes via API Gateway")
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="URL base de api-gateway"
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="Timeout HTTP por request"
    )
    parser.add_argument(
        "--status-wait-seconds",
        type=float,
        default=1.0,
        help="Espera antes de consultar estado de ordenes",
    )
    args = parser.parse_args()

    env_path = Path(".env")
    support_number = _load_env_support_number(env_path)
    analytics_admin_token = _load_env_var(env_path, "ANALYTICS_ADMIN_TOKEN")
    if support_number:
        print(f"SUPPORT_NUMBER detectado en .env: {support_number}")
    else:
        print("No se encontro SUPPORT_NUMBER en .env, se usara numero fallback.")

    if analytics_admin_token:
        print(
            "ANALYTICS_ADMIN_TOKEN detectado en .env: se enviara Authorization Bearer en /analytics"
        )
    else:
        print(
            "ANALYTICS_ADMIN_TOKEN no detectado: /analytics puede responder 401 o 503"
        )

    orders_url = f"{args.base_url.rstrip('/')}/orders/"
    created_order_ids: list[str] = []

    print("== Creando 5 ordenes ==")
    for index, order_payload in enumerate(build_seed_orders(support_number), start=1):
        status, response = _post_json(orders_url, order_payload, timeout=args.timeout)
        print(f"[{index}] POST /orders -> status {status} | response: {response}")
        if isinstance(response, dict) and response.get("order_id"):
            created_order_ids.append(str(response["order_id"]))

    if not created_order_ids:
        print("No se crearon ordenes. Revisa logs del api-gateway/writer-service.")
        return

    time.sleep(max(args.status_wait_seconds, 0.0))

    print("\n== Consultando estado de ordenes creadas ==")
    for order_id in created_order_ids:
        status_url = f"{args.base_url.rstrip('/')}/orders/{order_id}"
        status, response = _get_json(status_url, timeout=args.timeout)
        print(f"GET /orders/{order_id} -> status {status} | response: {response}")

    analytics_url = "http://localhost:8002/analytics"
    analytics_headers = (
        {"Authorization": f"Bearer {analytics_admin_token}"}
        if analytics_admin_token
        else None
    )
    analytics_status, analytics_response = _get_json(
        analytics_url,
        timeout=args.timeout,
        headers=analytics_headers,
    )
    print("\n== Snapshot de analitica ==")
    print(
        f"GET /analytics -> status {analytics_status} | response: {analytics_response}"
    )


if __name__ == "__main__":
    main()
