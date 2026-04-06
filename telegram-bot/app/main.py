import asyncio
import logging
import re
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select

from .config import settings
from .db import AsyncSessionLocal, engine
from .models import Base, TelegramSubscription
from .services.register_user import normalize_phone_number, register_user

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

START_PATTERN = re.compile(r"^/start(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$")
REGISTER_PATTERN = re.compile(r"^/register(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$")

class SendMessageRequest(BaseModel):
	phone_number: str
	text: str

async def _telegram_api_call(method: str, payload: dict) -> dict | list:
	if not settings.telegram_bot_token:
		raise RuntimeError("TELEGRAM_BOT_TOKEN no está configurado")

	url = (
		f"{settings.telegram_api_base_url.rstrip('/')}/"
		f"bot{settings.telegram_bot_token}/{method}"
	)
	timeout = httpx.Timeout(
		settings.telegram_read_timeout + 5,
		connect=settings.telegram_connect_timeout,
	)

	async with httpx.AsyncClient(timeout=timeout) as client:
		response = await client.post(url, json=payload)

	response.raise_for_status()
	data = response.json()
	if not data.get("ok"):
		description = data.get("description", "Error desconocido de Telegram")
		raise RuntimeError(description)
	return data.get("result", {})


async def _send_message(chat_id: str, text: str) -> None:
	await _telegram_api_call("sendMessage", {"chat_id": chat_id, "text": text})


async def _register_subscription(phone_number: str, chat_id: str) -> tuple[bool, str]:
	async with AsyncSessionLocal() as session:
		return await register_user(session, phone_number=phone_number, chat_id=chat_id)


async def _get_chat_id_by_phone_number(phone_number: str) -> str | None:
	normalized_phone = normalize_phone_number(phone_number)
	async with AsyncSessionLocal() as session:
		result = await session.execute(
			select(TelegramSubscription.chat_id).where(
				or_(
					TelegramSubscription.phone_number == normalized_phone,
					TelegramSubscription.phone_number.like(f"%{normalized_phone}"),
				)
			).order_by(TelegramSubscription.updated_at.desc())
		)
		return result.scalars().first()


async def _proccess_command(message: dict) -> None:
	text = (message.get("text") or "").strip()
	_is_start = START_PATTERN.match(text)
	_register_match = REGISTER_PATTERN.match(text)

	chat_id = str(((message.get("chat") or {}).get("id") or "")).strip()
	if not chat_id:
		return

	if not (_is_start or _register_match):
		await _send_message(
			chat_id=chat_id,
			text="Comando no reconocido. Usa /register para asociar tu número de teléfono.",
		)
		return

	if _is_start:
		await _send_message(
			chat_id=chat_id,
			text="¡Hola! Para recibir notificaciones de tus órdenes, por favor asocia tu número de teléfono usando el comando:\n/register 3001112233",
		)
		return

	phone_number = ""
	if _register_match and _register_match.group(1):
		phone_number = _register_match.group(1).strip()

	if not phone_number:
		await _send_message(
			chat_id=chat_id,
			text="Por favor proporciona un número de teléfono. Ejemplo: /register 3001112233",
		)
		return

	result = await _register_subscription(phone_number=phone_number, chat_id=chat_id)
	await _send_message(
		chat_id=chat_id,
		text=result[1],
	)
	if result[0]:
		logger.info("Suscripción registrada phone_number=%s chat_id=%s", phone_number, chat_id)


async def _init_db() -> None:
	if not settings.postgres_notifications_url:
		raise RuntimeError("POSTGRES_NOTIFICATIONS_URL no está configurado")
	async with engine.begin() as conn:
		await conn.run_sync(Base.metadata.create_all)


async def _get_updates(offset: int | None) -> list[dict]:
	payload: dict[str, int] = {"timeout": settings.telegram_poll_timeout}
	if offset is not None:
		payload["offset"] = offset

	result = await _telegram_api_call("getUpdates", payload)
	if isinstance(result, list):
		return result
	return []


async def _poll_telegram_updates(stop_event: asyncio.Event) -> None:
	offset: int | None = None
	retry_delay = settings.telegram_poll_seconds
	logger.info("Telegram polling iniciado")

	while not stop_event.is_set():
		try:
			updates = await _get_updates(offset)
			retry_delay = settings.telegram_poll_seconds

			for update in updates:
				update_id = update.get("update_id")
				if isinstance(update_id, int):
					offset = update_id + 1

				message = update.get("message") or update.get("edited_message")
				if message is None:
					continue
				await _proccess_command(message)
		except Exception as exc:
			if stop_event.is_set():
				break
			logger.warning(
				"Error en polling de Telegram: %s. Reintentando en %.1fs",
				exc,
				retry_delay,
			)
			await asyncio.sleep(retry_delay)
			retry_delay = min(retry_delay * 2, settings.telegram_retry_backoff_max)


@asynccontextmanager
async def lifespan(app: FastAPI):
	await _init_db()
	stop_event = asyncio.Event()
	polling_task = asyncio.create_task(_poll_telegram_updates(stop_event))
	app.state.stop_event = stop_event
	app.state.polling_task = polling_task
	try:
		yield
	finally:
		stop_event.set()
		polling_task.cancel()
		with suppress(asyncio.CancelledError):
			await polling_task
		await engine.dispose()


app = FastAPI(title="telegram-bot", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
	return {"status": "ok"}


@app.post("/internal/messages")
async def send_internal_message(payload: SendMessageRequest) -> dict[str, str]:
	try:
		chat_id = await _get_chat_id_by_phone_number(payload.phone_number)
		if not chat_id:
			raise HTTPException(
				status_code=404,
				detail="No existe suscripción para ese número de teléfono",
			)
		await _send_message(chat_id, payload.text)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	except HTTPException:
		raise
	except Exception as exc:
		raise HTTPException(status_code=502, detail=str(exc)) from exc
	return {"status": "sent"}


if __name__ == "__main__":
	import uvicorn

	uvicorn.run(
		"app.main:app",
		host=settings.telegram_bot_host,
		port=settings.telegram_bot_port,
		reload=False,
	)
