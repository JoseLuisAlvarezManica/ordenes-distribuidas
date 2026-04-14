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

    Client -->|"POST /orders<br/>{customer, phone_number, items:[{sku,qty}]}"| POST_orders
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

    C->>GW: POST /orders {customer, phone_number, items}
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
| **analytics-service** | 8002 | API de analítica en tiempo real de eventos de órdenes |
| **notification-service** | - | Worker de RabbitMQ para notificaciones de órdenes |
| **telegram-bot** | - | Bot de Telegram para registro de chats (`/start <telefono>`) |
| **postgres**       | 5432   | Base de datos relacional                |
| **redis**          | 6379   | Caché de estado de órdenes              |

## Endpoints

### API Gateway

| Método | Ruta                 | Descripción                                                                    |
| ------ | -------------------- | ------------------------------------------------------------------------------ |
| `POST` | `/orders`            | Crea una orden. Body: `{ "customer": "...", "phone_number": "+573001112233", "items": [{"sku":"A1","qty":2}] }` |
| `GET`  | `/orders/{order_id}` | Consulta el estado de una orden                                                |

### Writer Service (interno)

| Método | Ruta               | Descripción                                     |
| ------ | ------------------ | ----------------------------------------------- |
| `POST` | `/internal/orders` | Persiste la orden en Postgres y actualiza Redis |

### Analytics Service

| Método | Ruta         | Descripción |
| ------ | ------------ | ----------- |
| `GET`  | `/analytics` | Devuelve productos más pedidos, cliente más frecuente, porcentaje de errores y tiempos promedio de persistencia/publicación/notificación. Requiere `Authorization: Bearer <ANALYTICS_ADMIN_TOKEN>` |

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
    -d '{"customer": "Berny", "phone_number": "+573001112233", "items": [{"sku": "A1", "qty": 2}]}'

# Consultar estado (usar el order_id devuelto)
curl http://localhost:8000/orders/<order_id>

# Consultar analitica agregada
curl http://localhost:8002/analytics \
    -H "Authorization: Bearer <ANALYTICS_ADMIN_TOKEN>"

# En Telegram, registrar tu chat con tu teléfono
# /start +573001112233
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
| `RABBITMQ_URL`           | `amqp://superuser:superpassword@rabbitmq:5672/`                        |
| `ANALYTICS_ADMIN_TOKEN`  | Token requerido para acceder al endpoint privado `GET /analytics`      |
| `TELEGRAM_BOT_TOKEN`     | Token del bot de Telegram                                               |
| `TELEGRAM_BOT_SERVICE_URL` | URL interna del servicio telegram-bot (default: `http://telegram-bot:8003`) |
| `TELEGRAM_POLL_SECONDS`  | Intervalo de reintento del polling de Telegram (default: `2`)          |

---

# Parte 2 — Inventario y mensajería asíncrona

Se incorporó un tercer microservicio (`inventory-service`) y RabbitMQ como bus de eventos. El sistema ya no descuenta stock de forma síncrona: el writer persiste la orden y publica un evento; el inventory-service lo consume en segundo plano y ajusta el stock.

## Nueva arquitectura

### Diagrama de componentes

```mermaid
flowchart TB
    Client["🖥️ Cliente"]

    subgraph docker["Docker Network"]

        subgraph gw["api-gateway · :8000"]
            POST_orders["POST /orders"]
            GET_orders["GET /orders/{id}"]
        end

        subgraph ws["writer-service · :8001"]
            POST_internal["POST /internal/orders"]
            validate["validate_stock()"]
            upsert["upsert_order()"]
            publish["publish_order.created()"]
        end

        subgraph inv["inventory-service · worker"]
            subscriber["rabbit_subscriber<br/>(hilo daemon)"]
            handler["on_order_created()"]
            svc["discount_inventory()"]
        end

        Redis[("Redis :6379<br/>order:{id} status")]
        Postgres[("Postgres :5432<br/>tabla orders<br/>tabla products")]
        RabbitMQ["RabbitMQ :5672<br/>exchange: orders type topic<br/>routing key: order.created<br/>queue: inventory.order.created"]
    end

    Client --> POST_orders
    Client --> GET_orders

    POST_orders -->|"HSET status=RECEIVED"| Redis
    POST_orders -->|"HTTP POST /internal/orders"| POST_internal
    POST_internal --> validate
    validate -->|"SELECT stock FROM products"| Postgres
    validate -->|"stock insuficiente → HSET status=FAILED"| Redis
    POST_internal --> upsert
    upsert -->|"INSERT INTO orders"| Postgres
    upsert -->|"HSET status=PERSISTED"| Redis
    POST_internal --> publish
    publish -->|"order.created"| RabbitMQ

    RabbitMQ -->|"inventory.order.created"| subscriber
    subscriber --> handler
    handler --> svc
    svc -->|"UPDATE products SET stock = stock - qty"| Postgres

    GET_orders -->|"HGETALL order:{id}"| Redis
```

### Diagrama de secuencia

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente
    participant GW as api-gateway
    participant R as Redis
    participant WS as writer-service
    participant PG as Postgres
    participant MQ as RabbitMQ
    participant INV as inventory-service

    C->>GW: POST /orders {customer, phone_number, items}
    GW->>R: HSET order:{id} status=RECEIVED
    GW->>WS: POST /internal/orders

    WS->>PG: SELECT stock FROM products (por cada SKU)
    alt stock insuficiente
        WS->>R: HSET status=FAILED
        WS-->>GW: 422 Unprocessable Entity
        GW-->>C: 202 Accepted (status quedará FAILED)
    else stock ok
        WS->>PG: INSERT INTO orders
        WS->>R: HSET status=PERSISTED
        WS->>MQ: publish order.created
        WS-->>GW: 201 Created
        GW-->>C: 202 Accepted {order_id}
    end

    Note over MQ,INV: Procesamiento asíncrono

    MQ->>INV: order.created (queue: inventory.order.created)
    INV->>PG: SELECT … FOR UPDATE (por cada SKU)
    INV->>PG: UPDATE products SET stock = stock - qty
    INV->>MQ: basic_ack
```

### Resumen de la nueva arquitectura

| Aspecto              | Detalle                                                                              |
| -------------------- | ------------------------------------------------------------------------------------ |
| **Mensajería**       | RabbitMQ con exchange `orders` tipo `topic`, routing key `order.created`             |
| **Validación previa**| Writer valida stock disponible antes de persistir la orden                           |
| **Descuento**        | Asíncrono en inventory-service tras recibir el evento `order.created`                |
| **Consistencia**     | `SELECT … FOR UPDATE` evita race conditions al descontar stock                       |
| **Idempotencia**     | Writer sigue verificando `order_id` antes de insertar                                |
| **Fault tolerance**  | `basic_nack(requeue=False)` descarta mensajes malformados sin bucle infinito         |
| **Productos**        | 25 productos pre-cargados por el seeder al iniciar writer-service                    |

## Nuevo servicio: inventory-service

Worker puro (sin HTTP) que escucha eventos de RabbitMQ y descuenta stock en Postgres.

### Estructura

```
inventory-service/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py                        # arranque, handler on_order_created
    ├── config.py                      
    ├── db.py                          # engine/session SQLAlchemy async
    ├── models.py                    
    ├── schemas.py                     # Pydantic
    └── services/
        ├── rabbit_subscriber.py       # infraestructura RabbitMQ
        └── inventory_service.py       # lógica de descuento de stock
```

### Estados de una orden

```
RECEIVED → PERSISTED → (stock descontado async)
RECEIVED → FAILED    (stock insuficiente al momento de crear la orden)
```

## Cómo ejecutar

```bash
docker compose up --build
```

### Ejemplo de petición

```http
POST http://localhost:8000/orders/
Content-Type: application/json

{
  "customer": "Juan Pérez",
    "phone_number": "+573001112233",
  "items": [
    { "sku": "003-E", "qty": 2 },
    { "sku": "010-A", "qty": 1 },
    { "sku": "009-P", "qty": 5 }
  ]
}
```

### Consultar estado

```bash
curl http://localhost:8000/orders/<order_id>
```
