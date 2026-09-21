from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _blank_means_unset(cls, data):
        """Пустая строка в .env = значение не задано, берётся умолчание.

        Без этого `TG_API_ID=` (типичное состояние недозаполненного .env)
        роняет каждый контейнер на старте с невнятной ошибкой парсинга int.
        """
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data

    # infra
    database_url: str = "postgresql+asyncpg://radar:radar@db:5432/radar"
    domain: str = "localhost"
    log_level: str = "INFO"
    # собранный фронт; api раздаёт его сам, отдельный веб-сервер не нужен
    static_dir: str = "/app/static"
    # На бесплатном хостинге контейнер разрешён один: сбор, оценка и бот
    # поднимаются задачей внутри процесса api. На ноутбуке под docker compose
    # у них свой контейнер, и здесь остаётся false.
    run_workers_inline: bool = False
    # dev_mode=true разрешает заголовок `Authorization: dev <user_id>` вместо
    # подписанного initData. Никогда не включать на проде.
    dev_mode: bool = False

    # telegram bot
    bot_token: str = ""
    admin_ids: str = ""

    # telegram userbot
    tg_api_id: int = 0
    tg_api_hash: str = ""
    tg_phone: str = ""
    tg_session: str = "/app/sessions/collector"
    # новые найденные чаты сразу включать в сбор
    autoenable_new_sources: bool = True

    # Окно, в котором заказ ещё живой. Двенадцать часов — не перестраховка:
    # на биржах отклики разбирают за несколько часов, и вчерашний заказ почти
    # наверняка уже взят. Раньше стояло 14 дней, и лента наполнялась мёртвым.
    max_post_age_hours: int = 12
    # Источник, молчащий дольше этого, считается мёртвым и подсвечивается.
    dead_source_after_days: int = 30

    # ---- ВКонтакте: посты пишут сами люди, контакт прямой ----
    # сервисный ключ Standalone-приложения, vk.com/apps?act=manage
    vk_service_token: str = ""
    vk_poll_interval_sec: int = 180

    # ---- сбор из публичных каналов (без аккаунта, номера и api_id) ----
    # заказ живёт часы, поэтому обход чаще
    channel_poll_interval_sec: int = 180
    # пауза между каналами внутри обхода, чтобы не долбить t.me подряд
    channel_fetch_delay_sec: float = 3.0

    # anthropic
    anthropic_api_key: str = ""
    model_scorer: str = "claude-haiku-4-5"
    model_writer: str = "claude-sonnet-5"

    # логика
    score_threshold: int = 60
    score_hot: int = 75
    # не больше N уведомлений в телеграм за сутки (UTC). 0 = без лимита.
    # Сама лента не режется: всё, что прошло порог, остаётся в приложении.
    daily_lead_cap: int = 15
    contact_cooldown_days: int = 30
    scorer_batch: int = 20
    scorer_interval_sec: int = 5

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.replace(" ", "").split(",") if x]

    @property
    def sync_database_url(self) -> str:
        """Синхронный URL — нужен alembic'у."""
        from app.dburl import to_sync

        return to_sync(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
