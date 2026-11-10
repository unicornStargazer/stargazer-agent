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


def create_lifespan(
    loaded: LoadedSettings, transport: httpx.AsyncBaseTransport | None
) -> Lifespan[FastAPI]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = loaded.settings
        # 先校验 Skill 再打开库，错误部署不应留下数据库迁移副作用。
        catalog = (
            await asyncio.to_thread(FilesystemSkillCatalog.discover, loaded.skills_directory)
            if loaded.skills_directory
            else FilesystemSkillCatalog(())
        )
        await asyncio.to_thread(loaded.database_path.parent.mkdir, parents=True, exist_ok=True)
        await migrate_database(loaded.database_path)
        repository = SqliteConversationRepository(loaded.database_path)
        recovered = await repository.recover_interrupted()
        LOGGER.info("会话存储就绪 interrupted_requests=%d", recovered)
        provider = settings.provider
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                provider.read_timeout_seconds, connect=provider.connect_timeout_seconds
            ),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            gateway = OpenAICompatibleGateway(
                client,
                ProviderOptions(
                    provider.base_url,
                    provider.api_key.get_secret_value(),
                    provider.include_stream_usage,
                    provider.max_attempts,
                ),
            )
            app.state.services = create_http_services(
                settings, repository, create_agent_runner(gateway, catalog)
            )
            app.state.started = True
            try:
                yield
            finally:
                app.state.started = False
                del app.state.services

    return lifespan
