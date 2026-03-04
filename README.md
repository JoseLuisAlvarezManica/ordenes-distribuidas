# Distributed Orders

Sistema distribuido de ingesta de órdenes con **FastAPI**, **Postgres**, y **Redis**.

## Arquitectura

### Diagrama de componentes

```mermaid
flowchart TB
    Client["🖥️ Cliente<br/>(curl / Postman / Front)"]

    subgraph docker["Docker Network (docker-compose)"]

        subgraph gw["api-gateway · FastAPI · :8000"]
            POST_orders["POST /orders<br/>→ 202 Accepted"]
            GET_orders["GET /orders/{id}<br/>→ 200 OK"]
        end

        subgraph ws["writer-service · FastAPI · :8001"]
            POST_internal["POST /internal/orders<br/>→ 201 Created"]
            upsert["upsert_order()<br/>idempotente: sólo inserta<br/>si order_id no existe"]
        end

        Redis[("Redis :6379<br/><br/>Hash  order:{id}<br/>• status<br/>• last_update")]

        Postgres[("Postgres :5432<br/><br/>Tabla orders<br/>• order_id — PK varchar(36)<br/>• customer — varchar(255)<br/>• items — JSON<br/>• created_at — timestamp")]
    end

    Client -->|"POST /orders<br/>{customer, items:[{sku,qty}]}"| POST_orders
    Client -->|"GET /orders/{id}"| GET_orders

    POST_orders -->|"① HSET order:{id}<br/>status = RECEIVED"| Redis
    POST_orders -->|"② HTTP POST /internal/orders<br/>+ X-Request-Id<br/>timeout 1 s · 1 retry"| POST_internal
    POST_orders -.->|"Si writer falla:<br/>HSET status = FAILED"| Redis

    POST_internal --> upsert
    upsert -->|"③ INSERT INTO orders<br/>(si no existe)"| Postgres
    POST_internal -->|"④ HSET order:{id}<br/>status = PERSISTED"| Redis
    POST_internal -.->|"Si INSERT falla:<br/>HSET status = FAILED"| Redis

    GET_orders -->|"⑤ HGETALL order:{id}"| Redis
```

### Diagrama de secuencia

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente
    participant GW as api-gateway :8000
    participant R as Redis :6379
    participant WS as writer-service :8001
    participant PG as Postgres :5432

    C->>GW: POST /orders {customer, items}
    GW->>GW: genera order_id (UUID) + X-Request-Id
    GW->>R: HSET order:{id} status=RECEIVED
    GW->>WS: POST /internal/orders + X-Request-Id<br/>(timeout 1 s, max 1 retry)
    WS->>PG: SELECT … WHERE order_id = ? (idempotencia)
    alt orden no existe
        WS->>PG: INSERT INTO orders(…)
        WS->>R: HSET order:{id} status=PERSISTED
        WS-->>GW: 201 Created
    else ya existe
        WS-->>GW: 201 Created (sin duplicar)
    end
    GW-->>C: 202 Accepted {order_id, status=RECEIVED}

    Note over C,PG: Consulta posterior

    C->>GW: GET /orders/{order_id}
    GW->>R: HGETALL order:{order_id}
    GW-->>C: 200 {order_id, status, last_update}
```

### Resumen de la arquitectura

| Aspecto           | Detalle                                                                                         |
| ----------------- | ----------------------------------------------------------------------------------------------- |
| **Comunicación**  | HTTP síncrona (API Gateway → Writer) con timeout 1 s + 1 retry                                  |
| **Estado rápido** | Redis almacena hash `order:{id}` con `status` y `last_update`                                   |
| **Persistencia**  | Postgres vía SQLAlchemy async (asyncpg)                                                         |
| **Idempotencia**  | Writer verifica existencia de `order_id` antes de insertar                                      |
| **Trazabilidad**  | `X-Request-Id` propagado y logueado en ambos servicios                                          |
| **Health checks** | `pg_isready` (Postgres) · `redis-cli ping` (Redis)                                              |
| **Dependencias**  | api-gateway espera redis (healthy) + writer (started); writer espera postgres + redis (healthy) |
| **Estados**       | `RECEIVED` → `PERSISTED` · `RECEIVED` → `FAILED`                                                |

### Flujo

1. **POST /orders** → API Gateway genera `order_id`, guarda `status=RECEIVED` en Redis y envía el payload al Writer Service por HTTP.
2. **Writer Service** escribe en Postgres → actualiza `status=PERSISTED` (o `FAILED`) en Redis.
3. **GET /orders/{order_id}** → API Gateway lee el estado desde Redis (respuesta rápida).

## Estructura del proyecto

```
distributed-orders/
├── docker-compose.yml
├── .env
├── README.md
│
├── api-gateway/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # POST /orders, GET /orders/{id}
│       ├── config.py            # variables de entorno
│       ├── redis_client.py      # conexión a Redis
│       ├── schemas.py           # modelos Pydantic
│       └── services/
│           └── writer_client.py # llamada HTTP al writer (timeout + retry)
│
└── writer-service/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── main.py              # POST /internal/orders
        ├── config.py            # variables de entorno
        ├── redis_client.py      # conexión a Redis
        ├── db.py                # engine/session SQLAlchemy async
        ├── models.py            # modelo ORM (Order)
        ├── schemas.py           # modelo Pydantic (InternalOrder)
        └── repositories/
            └── orders_repo.py   # insert idempotente
```

## Servicios

| Servicio           | Puerto | Descripción                             |
| ------------------ | ------ | --------------------------------------- |
| **api-gateway**    | 8000   | API pública – recibe y consulta órdenes |
| **writer-service** | 8001   | Servicio interno – persiste en Postgres |
| **postgres**       | 5432   | Base de datos relacional                |
| **redis**          | 6379   | Caché de estado de órdenes              |

## Endpoints

### API Gateway

| Método | Ruta                 | Descripción                                                                    |
| ------ | -------------------- | ------------------------------------------------------------------------------ |
| `POST` | `/orders`            | Crea una orden. Body: `{ "customer": "...", "items": [{"sku":"A1","qty":2}] }` |
| `GET`  | `/orders/{order_id}` | Consulta el estado de una orden                                                |

### Writer Service (interno)

| Método | Ruta               | Descripción                                     |
| ------ | ------------------ | ----------------------------------------------- |
| `POST` | `/internal/orders` | Persiste la orden en Postgres y actualiza Redis |

## Características distribuidas

- **Correlación**: header `X-Request-Id` propagado y logueado en ambos servicios.
- **Timeout + retry**: API Gateway usa timeout de 1 s y 1 reintento al llamar al Writer.
- **Idempotencia**: el Writer verifica si el `order_id` ya existe antes de insertar (no duplica).
- **Estados en Redis**: `RECEIVED` → `PERSISTED` | `FAILED`.

## Cómo ejecutar

```bash
# Levantar todos los servicios
docker compose up --build

# Crear una orden
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"customer": "Berny", "items": [{"sku": "A1", "qty": 2}]}'

# Consultar estado (usar el order_id devuelto)
curl http://localhost:8000/orders/<order_id>
```

## Variables de entorno

Definidas en `.env` y compartidas vía `docker-compose.yml`:

| Variable                 | Valor por defecto                                                      |
| ------------------------ | ---------------------------------------------------------------------- |
| `POSTGRES_USER`          | `orders_user`                                                          |
| `POSTGRES_PASSWORD`      | `orders_pass`                                                          |
| `POSTGRES_DB`            | `orders_db`                                                            |
| `DATABASE_URL`           | `postgresql+asyncpg://orders_user:orders_pass@postgres:5432/orders_db` |
| `REDIS_URL`              | `redis://redis:6379/0`                                                 |
| `WRITER_SERVICE_URL`     | `http://writer-service:8001`                                           |
| `WRITER_TIMEOUT_SECONDS` | `1.0`                                                                  |
| `WRITER_MAX_RETRIES`     | `1`                                                                    |
