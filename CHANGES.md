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
Permite crear una nueva instancia de cliente Redis utilizando una URL de conexión en lugar de pasar un objeto de configuración con host, puerto, contraseña

