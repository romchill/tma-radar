"""Клиент VK API для сбора заказов из групп.

Зачем вообще ВК: в телеграме прямого контакта взять негде — каналы отдают
перепечатку бирж с контактом админа, а чаты без аккаунта не читаются. В ВК же
посты на стене группы пишут сами люди, у поста есть автор, и написать ему
можно бесплатно.

Нужен сервисный ключ: vk.com/apps?act=manage → создать Standalone-приложение →
«Ключи доступа» → сервисный ключ. Бесплатно, карта не нужна, к личному
аккаунту доступа не даёт — только чтение открытых данных.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

from app.config import settings

log = logging.getLogger(__name__)

API = "https://api.vk.com/method/"
VERSION = "5.199"
TIMEOUT = aiohttp.ClientTimeout(total=25)

# сервисный ключ держит около 3 запросов в секунду
RATE_DELAY_SEC = 0.4


class VkError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"VK {code}: {message}")
        self.code = code
        self.message = message


@dataclass
class VkPost:
    group: str
    post_id: int
    owner_id: int
    author_id: int
    text: str
    link: str
    posted_at: datetime | None
    # заполняются после резолва автора
    author_name: str | None = None
    author_screen: str | None = None

    @property
    def by_user(self) -> bool:
        """Пост написал человек, а не сама группа.

        Только такие лиды писабельные: у поста от имени группы автор — админ,
        это то же самое, что контакт админа канала в телеграме.
        """
        return self.author_id > 0

    @property
    def contact_url(self) -> str | None:
        if not self.by_user:
            return None
        return f"https://vk.com/{self.author_screen or f'id{self.author_id}'}"


def available() -> bool:
    return bool(settings.vk_service_token)


async def call(session: aiohttp.ClientSession, method: str, **params) -> dict:
    params.update(access_token=settings.vk_service_token, v=VERSION)
    async with session.get(API + method, params=params) as response:
        data = await response.json()

    if "error" in data:
        err = data["error"]
        raise VkError(err.get("error_code", 0), err.get("error_msg", "?"))

    await asyncio.sleep(RATE_DELAY_SEC)
    return data.get("response", {})


async def fetch_wall(session: aiohttp.ClientSession, group: str, count: int = 50) -> list[VkPost]:
    """Посты со стены открытой группы. Репосты пропускаем — это не заказы."""
    key = "owner_id" if group.lstrip("-").isdigit() else "domain"
    value = group if key == "domain" else group

    try:
        data = await call(session, "wall.get", **{key: value}, count=count, filter="all")
    except VkError as exc:
        log.warning("группа %s недоступна: %s", group, exc)
        return []

    posts: list[VkPost] = []
    for item in data.get("items", []):
        if item.get("copy_history"):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue

        owner_id = item.get("owner_id", 0)
        post_id = item.get("id", 0)
        stamp = item.get("date")

        posts.append(
            VkPost(
                group=group,
                post_id=post_id,
                owner_id=owner_id,
                author_id=item.get("from_id", owner_id),
                text=text,
                link=f"https://vk.com/wall{owner_id}_{post_id}",
                posted_at=(
                    datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp else None
                ),
            )
        )

    return posts


async def resolve_authors(session: aiohttp.ClientSession, posts: list[VkPost]) -> None:
    """Дописывает имя и короткий адрес авторам-людям, чтобы было кому писать."""
    ids = sorted({p.author_id for p in posts if p.by_user})
    if not ids:
        return

    try:
        users = await call(
            session, "users.get", user_ids=",".join(map(str, ids)), fields="screen_name"
        )
    except VkError as exc:
        log.warning("не разобрал авторов: %s", exc)
        return

    by_id = {u["id"]: u for u in users}
    for post in posts:
        user = by_id.get(post.author_id)
        if not user:
            continue
        post.author_screen = user.get("screen_name")
        post.author_name = " ".join(
            x for x in (user.get("first_name"), user.get("last_name")) if x
        ) or None


async def group_title(session: aiohttp.ClientSession, group: str) -> str | None:
    try:
        data = await call(session, "groups.getById", group_id=group.lstrip("-"))
    except VkError:
        return None
    items = data.get("groups") or (data if isinstance(data, list) else [])
    return items[0].get("name") if items else None
