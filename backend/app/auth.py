"""Аутентификация мини-аппа.

Telegram при открытии WebApp кладёт в `window.Telegram.WebApp.initData`
подписанную строку. Фронт шлёт её в каждом запросе заголовком
`Authorization: tma <initData>`. Здесь мы проверяем подпись ключом,
производным от токена бота, — подделать её без токена нельзя.

Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status

from app.config import settings

log = logging.getLogger(__name__)

MAX_AUTH_AGE_SEC = 24 * 60 * 60

# какой вариант контрольной строки подошёл — чтобы не писать это в лог каждый раз
_logged_variant: str | None = None


@dataclass(frozen=True)
class TgUser:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None

    @property
    def title(self) -> str:
        name = " ".join(x for x in (self.first_name, self.last_name) if x)
        return name or (f"@{self.username}" if self.username else str(self.id))


class InitDataError(ValueError):
    pass


def parse_init_data(init_data: str, bot_token: str, max_age: int = MAX_AUTH_AGE_SEC) -> TgUser:
    """Проверяет подпись initData и возвращает пользователя."""
    if not bot_token:
        raise InitDataError("BOT_TOKEN не задан на сервере")
    if not init_data:
        raise InitDataError("пустой initData")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("в initData нет hash")

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

    # Поле `signature` клиенты добавили не сразу, и входит ли оно в контрольную
    # строку — зависит от версии. Проверяем оба варианта: ошибиться тут значит
    # не пустить настоящего владельца, а подделать подпись без токена всё равно
    # нельзя ни в одном из них.
    variants: list[tuple[str, dict[str, str]]] = [("с signature", pairs)]
    if "signature" in pairs:
        stripped = {k: v for k, v in pairs.items() if k != "signature"}
        variants.append(("без signature", stripped))

    matched: str | None = None
    for name, fields in variants:
        check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
        calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(calculated, received_hash):
            matched = name
            break

    if matched is None:
        log.warning(
            "подпись не сошлась ни в одном варианте; поля: %s",
            ", ".join(sorted(pairs)),
        )
        raise InitDataError("подпись не сходится")

    global _logged_variant
    if _logged_variant != matched:
        log.info("подпись initData проверена, вариант: %s", matched)
        _logged_variant = matched

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("некорректный auth_date") from exc

    if max_age and time.time() - auth_date > max_age:
        raise InitDataError("initData протух, переоткрой приложение")

    raw_user = pairs.get("user")
    if not raw_user:
        raise InitDataError("в initData нет user")

    try:
        data = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise InitDataError("не разобрать user") from exc

    return TgUser(
        id=int(data["id"]),
        username=data.get("username"),
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        language_code=data.get("language_code"),
    )


async def require_admin(authorization: str | None = Header(default=None)) -> TgUser:
    """FastAPI-зависимость: пускаем только whitelist из ADMIN_IDS."""
    if settings.dev_mode and authorization and authorization.startswith("dev "):
        return TgUser(id=int(authorization[4:].strip()), username="dev")

    if not authorization or not authorization.lower().startswith("tma "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="нужен заголовок Authorization: tma <initData>",
        )

    try:
        user = parse_init_data(authorization[4:].strip(), settings.bot_token)
    except InitDataError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if settings.admin_id_list and user.id not in settings.admin_id_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="доступ только для владельца",
        )

    return user
