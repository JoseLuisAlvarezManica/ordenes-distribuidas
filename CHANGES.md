## ORM

El mapeo objeto-relacional (ORM) es el proceso de abstraer la conexión entre las entidades del lenguaje de programación y la base de datos.

Sirve para desacoplar la base de datos de la abstracción de los objetos: en lugar de escribir SQL a mano, se trabaja con clases y atributos normales de Python, y el ORM traduce esas operaciones a consultas SQL de forma automática.


## Asyncio

Python ejecuta el código en un solo hilo. Sin asyncio, cada vez que el programa espera algo el hilo queda bloqueado sin hacer nada hasta que llega la respuesta.

asyncio introduce el concepto de event loop: un ciclo que está corriendo permanentemente, cede el control a otra tarea que sí tiene trabajo que hacer. Cuando la respuesta llega, el event loop retoma la tarea original desde donde la dejó.


# @asynccontextmanager

Un context manager garantiza que siempre se ejecute un bloque de limpieza al salir, haya error o no.


FastAPI llama a esta función al iniciar y espera al yield; cuando el proceso recibe la señal de apagado, retoma la función desde el yield y ejecuta la limpieza. Esto garantiza que los recursos siempre se liberan correctamente.


## SQLAlchemy

Es un conjunto de herramientas ORM para Python. Contiene varios patrones comunes diseñados para la eficiencia y desempeño en el acceso a una base de datos.

`scalar_one_or_none()`: Devuelve 1 si el registro existe o none si no existe.

# Engine

El Engine es la pieza central de SQLAlchemy. Representa la conexión con la base de datos y gestiona internamente un pool de conexiones: en lugar de abrir y cerrar una conexión física a Postgres por cada consulta mantiene varias conexiones abiertas y las reutiliza cuando llegan nuevas peticiones.

`pool_pre_ping=True` es importante en entornos Docker: si Postgres se reinicia, las conexiones del pool quedan muertas. Con esta opción, SQLAlchemy hace un `SELECT 1` silencioso antes de usar cada conexión, y si falla, la descarta y abre una nueva.

El driver que hace el puente entre SQLAlchemy y Postgres en modo async es asyncpg, que es mucho más rápido que el driver síncrono psycopg2 porque fue diseñado desde cero para asyncio.

# Session 

 Es la unidad de trabajo: agrupa todas las operaciones (SELECT, INSERT, UPDATE, DELETE) de un mismo request en una sola transacción. Al hacer `commit`, todas las operaciones se aplican a la vez; si hay un error, se puede hacer `rollback` para deshacer todo sin dejar la base de datos en un estado inconsistente.


`expire_on_commit=False` es necesario en async: normalmente SQLAlchemy marca los objetos como expirados tras el commit para forzar una recarga desde la BD la próxima vez que se accede a un atributo. En async esa recarga implícita lanza una excepción porque ya no hay una sesión activa. Con esta opción los atributos conservan su valor en memoria.


# Base

`Base = DeclarativeBase` es la clase raíz de todos los modelos ORM del proyecto. Al heredar de ella, SQLAlchemy sabe que la clase representa una tabla.

# Mapped
Se utiliza para definir el mapeo de forma declarativa permitiendo definir los modelos

# Schemas Pydantic

 schemas Pydantic describen cómo viaja esa información entre servicios: qué campos se aceptan en un request, cuáles se devuelven en una respuesta, y qué tipos y restricciones tienen.

 ## Redis

# `ioredis.from_url` 
Permite crear una nueva instancia de cliente Redis utilizando una URL de conexión en lugar de pasar un objeto de configuración con host, puerto, contraseña.

## httpx
Biblioteca de python la cual permite realizar peticiones de HTTP de manera sencilla y permite conexiones asincronas, se ocupo junto a una clase para realizar las peticiones del gateway al writer.

## uuid4
Funcion de la libreria uuid, la cual permite generar identificadores unicos al azar. Con esta función se crearon los id de las peticiones, las cuales al llegar a la base de datos se convertiria en el id de una orden.
Annotated permite describir información extra (metadatos) sobre un tipo sin cambiar el tipo en sí. Frameworks como FastAPI pueden leer esos metadatos para aplicar comportamientos adicionales, como ejecutar dependencias definidas con `Depends`.

## RabbitMQ
un broker de mensajeria, este ayuda a desacoplar distintos servicios al poder repartir mensajes a traves de un sistema de publicaciones y subscripciones.

## Pika
Biblioteca de python la cual se ocupa para implementar el protocolo AMQP 0-9-1, el cual es uno de los posibles protocolos a ocupar para establecer comunicaciones con RabbitMQ.


## Analytics Service

Se agregó un servicio de analítica que escucha eventos del exchange `orders` en RabbitMQ y construye métricas agregadas  para exponerlas en `GET /analytics`.

La idea de este servicio es separar observabilidad del flujo de negocio principal: writer, inventory y notification siguen su camino normal, mientras analytics consume eventos y calcula indicadores.


# on_order_event (analytics-service/app/main.py)

Es el callback principal del consumer AMQP. Lee `routing_key` y decide qué tipo de evento procesar.

- Si llega `order.created`, valida el payload con `OrderCreatedEvent` y actualiza métricas de volumen/productos/clientes.
- Si llega `order.error`, valida con `OrderErrorEvent` y contabiliza error global y, si aplica, error de publicación.
- Si llega `order.processing`, valida con `OrderProcessingEvent` y actualiza latencias operativas y errores de procesamiento.

Después del procesamiento hace `ack` del mensaje. Si hay excepción hace `nack` con `requeue=False` para no ciclar mensajes inválidos.

# lifespan 

Maneja el ciclo de vida del servicio:

- En startup inicia el subscriber RabbitMQ.
- En shutdown cierra el subscriber.

Esto asegura alta automática al iniciar el contenedor y cierre limpio al apagar.

# run_consumer 

Configura y ejecuta la suscripción AMQP:

- Declara exchange `orders` tipo topic.
- Declara queue `analytics.order.events`.
- Hace bind de múltiples routing keys: `order.created`, `order.error`, `order.processing`.
- Define `prefetch_count=50` para throughput del consumidor.
- Inicia consumo continuo con `basic_consume` + `start_consuming`.

# start_subscriber 

Levanta un hilo daemon para correr `run_consumer` en segundo plano y no bloquear el hilo principal de FastAPI.

# stop_subscriber 

Cierra la conexión AMQP activa para detener el consumo cuando la app se apaga.

# AnalyticsAggregator.add_created

Actualiza indicadores de negocio por orden:

- incrementa total de órdenes vistas.
- incrementa frecuencia del cliente (`customer`).
- suma cantidades por SKU para ranking de productos.
- acumula `persist_ms` para promedio de persistencia en Postgres.

# AnalyticsAggregator.add_error

Registra errores globales y separa los errores de etapa `publish` para un porcentaje específico de publicación.

# AnalyticsAggregator.add_processing

Registra métricas operativas por servicio:

- incrementa total de eventos de procesamiento.
- si `status=error`, cuenta como error de sistema.
- si viene de writer con `metric=publish`, acumula tiempo de publicación RabbitMQ.
- si viene de notification, acumula tiempo de notificación.

# AnalyticsAggregator.snapshot

Construye el payload final de `GET /analytics` con:

- conteos agregados.
- top productos.
- cliente más frecuente.
- porcentajes de error.
- promedios de latencia.

## Endpoint /analytics: significado de cada campo

# total_orders_seen

Número de eventos `order.created` consumidos por analytics.

Se obtiene incrementando en cada llamada a `add_created`.

# top_products

Lista top 5 por cantidad total pedida (`qty`) acumulada por SKU.

No representa número de órdenes, sino suma de unidades.

# most_frequent_customer

Cliente con más órdenes observadas y su conteo (`orders`).

Se obtiene con `Counter.most_common(1)` sobre el contador de clientes.

# error_rates.publish_error_percentage

Porcentaje de errores de publicación sobre total de órdenes vistas.

Fórmula:

`(publish_error_events / total_orders_seen) * 100`

# error_rates.system_error_percentage

Porcentaje de errores globales sobre eventos rastreados.

Fórmula:

`(error_events_total / (total_orders_seen + processing_events_total)) * 100`

# error_rates.error_events

Conteo absoluto de errores detectados en analytics.

Incluye errores de `order.error` y `order.processing` con `status=error`.

# avg_times_ms.persist_order_postgres

Promedio de tiempo de persistencia en Postgres (ms).

Se alimenta con `persist_ms` del evento `order.created` emitido por writer.

# avg_times_ms.publish_event_rabbitmq

Promedio de tiempo de publicación a RabbitMQ (ms).

Se alimenta con `duration_ms` de `order.processing` cuando `service=writer` y `metric=publish`.

# avg_times_ms.notification

Promedio de tiempo de notificación (ms).

Se alimenta con `duration_ms` de `order.processing` cuando `service=notification`.


## Cómo se mide el tiempo

Analytics no cronometra localmente la ejecución interna de writer/notification. En su lugar, consume tiempos ya medidos por cada servicio productor en sus payloads de eventos (`persist_ms`, `duration_ms`) y calcula promedios acumulados.

Este enfoque evita acoplar analytics a la lógica interna de cada microservicio y mantiene la medición distribuida en origen.

La medición en cada servicio se hace con `time.perf_counter()` usando el patrón:

1. guardar tiempo de inicio.
2. ejecutar la operación.
3. calcular `duracion = (time.perf_counter() - inicio) * 1000` para expresarlo en ms.


Luego analytics solo agrega esos valores para calcular promedios, en lugar de volver a medir el tiempo remoto desde su propio proceso.

## ack / nack

Son la forma de confirmarle a RabbitMQ qué pasó con un mensaje:

- **ack** (acknowledge): "procesé el mensaje correctamente". RabbitMQ lo elimina de la queue.
- **nack** (negative acknowledge): "algo salió mal". Con `requeue=False` RabbitMQ lo descarta; con `requeue=True` lo devuelve a la queue para reintentarlo.

Si el consumer no hace ni ack ni nack y se desconecta, RabbitMQ reencola el mensaje automáticamente.

## Callable

`Callable` es un tipo de Python que representa cualquier objeto que se puede llamar como función: funciones normales, lambdas, métodos, o clases con `__call__`.

Se usa en `rabbit_subscriber.py` para declarar que `on_message` es un parámetro que acepta una función con una firma específica

## Python-JOSE

Biblioteca para crear y firmar JSON Web Tokens en Python. Se utilizó junto con un par de llaves RSA para firmar y verificar los JWT con el algoritmo RS256 (asimétrico): el auth-service firma con la clave privada y el api-gateway verifica con la clave pública sin necesidad de compartir el secreto.

Generación del par de llaves:

```bash
# Clave privada RSA de 2048 bits
openssl genrsa -out private.pem 2048

# Clave pública derivada
openssl rsa -in private.pem -pubout -out public.pem
```

Los valores de `private.pem` y `public.pem` se pasan a los servicios como variables de entorno `PRIVATE_KEY` y `PUBLIC_KEY`.

## Passlib

Biblioteca de hashing de contraseñas. Se utilizó el esquema `bcrypt`, que incorpora un salt aleatorio y un factor de costo que hace el hash computacionalmente costoso, dificultando ataques de fuerza bruta.

## Pruebas sign up, login y logout

**Registro de usuario:**

```bash
curl -s -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"name":"Juan Perez","email":"juan@mail.com","phone_number":"+521234567890","password":"supersecret123"}'
```

**Login y captura del token:**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"juan@mail.com","password":"supersecret123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo $TOKEN
```

**Logout (invalida el token en Redis):**

```bash
curl -s -X POST http://localhost:8000/auth/logout \
  -H "Authorization: Bearer $TOKEN"
```

**Registro duplicado (debe retornar 409):**

```bash
curl -s -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"name":"Juan Perez","email":"juan@mail.com","phone_number":"+521234567890","password":"supersecret123"}'
```

**Login con contraseña incorrecta (debe retornar 401):**

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"juan@mail.com","password":"wrongpassword"}'
```

## Auth: endpoint /refresh y /me

- renovar el token sin pedir credenciales otra vez (`/refresh`),
- obtener la informacion del usuario autenticado (`/me`).


### Solucion implementada

Se hicieron cambios en `auth-service` y en `api-gateway` para que funcionen de extremo a extremo.

1. `auth-service/app/routes/users.py`

- Se agrego una validacion centralizada de Bearer token:
  - decodifica JWT con llave publica,
  - revisa en Redis si el token esta en blacklist (`blacklist:<token>`),
  - rechaza token invalido o revocado con `401`.
- Se implemento `POST /auth/refresh`:
  - usa los claims del token actual (`sub`, `email`, `role`, `phone_number`),
  - genera un nuevo `access_token` con la expiracion configurada,
  - envia el token anterior a blacklist en Redis para invalidarlo inmediatamente,
  - devuelve `200` con `{ access_token, token_type }`.
- Se implemento `GET /auth/me`:
  - toma el email del token validado,
  - consulta el usuario en Postgres,
  - devuelve `200` con `username`, `email`, `phone_number`, `role`.
- `logout` ahora reutiliza la misma validacion de token y mantiene la revocacion en Redis con TTL hasta la expiracion del JWT.

2. `auth-service/app/schemas.py`

- Se agregaron modelos de respuesta:
  - `TokenResponse` para login/refresh,
  - `MeResponse` para `/me`.

3. `api-gateway/app/routes/auth.py`

- Se agrego `POST /auth/refresh` que reenvia el header `Authorization` al `auth-service`.
- Se agrego `GET /auth/me` que reenvia el header `Authorization` al `auth-service`.

4. `api-gateway/app/schemas.py`

- Se agrego `MeResponse` para tipar la respuesta del endpoint `/auth/me` en el gateway.

### Como probar

Prueba recomendada via API Gateway (`http://localhost:8000`):

1. Login y captura de token:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"juan@mail.com","password":"supersecret123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo $TOKEN
```

2. Consultar usuario autenticado:

```bash
curl -s -X GET http://localhost:8000/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

Resultado esperado: `200` con `username`, `email`, `phone_number`, `role`.

3. Renovar token:

```bash
NEW_TOKEN=$(curl -s -X POST http://localhost:8000/auth/refresh \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo $NEW_TOKEN
```

Resultado esperado: `200` con un nuevo `access_token`.

4. Verificar que el nuevo token funciona en `/me`:

```bash
curl -s -X GET http://localhost:8000/auth/me \
  -H "Authorization: Bearer $NEW_TOKEN"
```

Resultado esperado: `200` con la misma informacion del usuario.

5. Verificar que el token anterior ya no es valido despues de refresh:

```bash
curl -s -X GET http://localhost:8000/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

Resultado esperado: `401` con mensaje de token revocado.

6. Logout y validacion de revocacion:

```bash
curl -s -X POST http://localhost:8000/auth/logout \
  -H "Authorization: Bearer $NEW_TOKEN"

curl -s -X POST http://localhost:8000/auth/refresh \
  -H "Authorization: Bearer $NEW_TOKEN"
```
