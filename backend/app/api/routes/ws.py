"""WebSocket endpoints for real-time telemetry & order updates (spec §5D).

Authenticated: the client passes its JWT as a `?token=` query parameter (the
browser WebSocket API cannot set Authorization headers). Telemetry is internal-
only; the orders stream is filtered per-customer so a customer never sees another
tenant's order events. Best-effort — the frontend falls back to polling.
"""

import asyncio
import contextlib
import json
from collections.abc import Callable

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from app.api.deps import INTERNAL_ROLES
from app.core import redis, security
from app.core.config import settings
from app.core.db import engine
from app.models import User

router = APIRouter(tags=["realtime"])


def _user_from_token(token: str | None) -> User | None:
    """Validate a JWT query token and return the active user, or None."""
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
    except Exception:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    with Session(engine) as session:
        user = session.get(User, sub)
        if user and user.is_active:
            session.expunge(user)
            return user
    return None


async def _pump(
    websocket: WebSocket,
    channel: str,
    *,
    allow: Callable[[dict], bool] | None = None,
) -> None:
    await websocket.accept()
    client = redis.get_redis()
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            if allow is not None:
                try:
                    if not allow(json.loads(data)):
                        continue
                except Exception:
                    continue
            await websocket.send_text(data)
    except WebSocketDisconnect:
        pass
    except Exception:
        # Redis unavailable — keep the socket open but idle; client will poll.
        with contextlib.suppress(Exception):
            while True:
                await asyncio.sleep(30)
                await websocket.send_text('{"keepalive":true}')
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()


@router.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket) -> None:
    user = _user_from_token(websocket.query_params.get("token"))
    if not user or user.role not in INTERNAL_ROLES:
        await websocket.close(code=1008)  # policy violation
        return
    await _pump(websocket, redis.TELEMETRY_CHANNEL)


@router.websocket("/ws/orders")
async def ws_orders(websocket: WebSocket) -> None:
    user = _user_from_token(websocket.query_params.get("token"))
    if not user:
        await websocket.close(code=1008)
        return
    allow: Callable[[dict], bool] | None = None
    if user.role not in INTERNAL_ROLES:
        # Customers only receive events for their OWN orders.
        cid = str(user.customer_id) if user.customer_id else "__none__"
        allow = lambda msg: msg.get("customer_id") == cid  # noqa: E731
    await _pump(websocket, redis.ORDERS_CHANNEL, allow=allow)
