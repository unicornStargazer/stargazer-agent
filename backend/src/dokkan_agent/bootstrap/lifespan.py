"""资源装配与关闭：显式配置的存储、Skill 快照和 HTTP 连接池只在启动时建立。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.types import Lifespan

from dokkan_agent.bootstrap.runtime import create_agent_runner
from dokkan_agent.bootstrap.services import create_http_services
from dokkan_agent.bootstrap.settings import LoadedSettings
from dokkan_agent.infrastructure.memory.migration import migrate_database
from dokkan_agent.infrastructure.memory.sqlite_repository import SqliteConversationRepository
from dokkan_agent.infrastructure.provider.openai_compatible import (
    OpenAICompatibleGateway,
    ProviderOptions,
)
from dokkan_agent.infrastructure.skill.filesystem_catalog import FilesystemSkillCatalog

LOGGER = logging.getLogger(__name__)


def create_lifespan(loaded: LoadedSettings, transport: httpx.AsyncBaseTransport | None) -> Lifespan[FastAPI]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = loaded.settings
        # 先校验 Skill 再打开库，错误部署不应留下数据库迁移副作用。
        if loaded.skills_directory:
            catalog = await asyncio.to_thread(FilesystemSkillCatalog.discover, loaded.skills_directory)
        else:
            catalog = FilesystemSkillCatalog(())
        database_directory = loaded.database_path.parent
        await asyncio.to_thread(database_directory.mkdir, parents=True, exist_ok=True)
        await migrate_database(loaded.database_path)
        repository = SqliteConversationRepository(loaded.database_path)
        recovered = await repository.recover_interrupted()
        LOGGER.info("会话存储就绪 interrupted_requests=%d", recovered)
        provider = settings.provider
        timeout = httpx.Timeout(provider.read_timeout_seconds, connect=provider.connect_timeout_seconds)
        limits = httpx.Limits(max_connections=32, max_keepalive_connections=16)
        http_client = httpx.AsyncClient(timeout=timeout, limits=limits, transport=transport, trust_env=False, follow_redirects=False)
        async with http_client as client:
            secret = provider.api_key
            api_key = secret.get_secret_value()
            options = ProviderOptions(provider.base_url, api_key, provider.include_stream_usage, provider.max_attempts)
            gateway = OpenAICompatibleGateway(client, options)
            runner = create_agent_runner(gateway, catalog)
            app.state.services = create_http_services(settings, repository, runner)
            app.state.started = True
            try:
                yield
            finally:
                app.state.started = False
                del app.state.services

    return lifespan
