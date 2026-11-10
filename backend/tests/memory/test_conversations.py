"""临时真实 SQLite 与运行器集成：原子性、跨重启幂等、并发和中断恢复。"""

import asyncio
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from dokkan_agent.application.conversation.profiles import ProfileCatalog
from dokkan_agent.application.conversation.service import ConversationService
from dokkan_agent.application.conversation.session_locks import SessionLease, SessionLocks
from dokkan_agent.application.runtime.models import RunProfile
from dokkan_agent.bootstrap.runtime import create_agent_runner
from dokkan_agent.domain.agent.budget import RunLimits
from dokkan_agent.domain.agent.errors import ModelUnavailableError
from dokkan_agent.domain.agent.models import (
    ContentDelta,
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ReasoningDelta,
    TokenUsage,
    UsageReported,
)
from dokkan_agent.domain.conversation.errors import (
    ConversationStorageError,
    RequestAttemptsExceeded,
    RequestConflictError,
    SessionBusyError,
)
from dokkan_agent.domain.conversation.models import (
    AssistantReply,
    ConversationCommand,
    RequestStatus,
)
from dokkan_agent.infrastructure.memory.migration import migrate_database
from dokkan_agent.infrastructure.memory.sqlite_repository import SqliteConversationRepository
from dokkan_agent.infrastructure.skill.filesystem_catalog import FilesystemSkillCatalog


class ControlledModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.entered = asyncio.Event()
        self.second_entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.fail = False
        self.closed = 0

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
        self.requests.append(request)
        self.entered.set()
        if len(self.requests) >= 2:
            self.second_entered.set()
        try:
            await self.release.wait()
            yield ReasoningDelta("公开摘要")
            yield ContentDelta("回答")
            if self.fail:
                raise ModelUnavailableError("模拟网络失败")
            yield UsageReported(TokenUsage(2, 3, 1, 5))
            yield ModelCompleted("stop")
        finally:
            self.closed += 1


def build_service(
    repository: SqliteConversationRepository, model: ControlledModel
) -> ConversationService:
    profiles = ProfileCatalog((RunProfile("a", "model-a"), RunProfile("b", "model-b")), "a")
    return ConversationService(
        repository, create_agent_runner(model, FilesystemSkillCatalog(())), profiles, RunLimits()
    )


async def test_replay_survives_restart_switch_keeps_history_and_delete_cascades(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sessions.sqlite"
    await migrate_database(database)
    repository = SqliteConversationRepository(database)
    model = ControlledModel()
    service = build_service(repository, model)
    first = ConversationCommand("s", "r1", "问题", "a")
    reply = await service.chat(first)
    assert reply == AssistantReply("回答", "公开摘要", TokenUsage(2, 3, 1, 5))
    restarted = build_service(SqliteConversationRepository(database), model)
    assert await restarted.chat(first) == reply
    assert len(model.requests) == 1
    with pytest.raises(RequestConflictError):
        await restarted.chat(ConversationCommand("s", "r1", "不同问题", "a"))
    await restarted.chat(ConversationCommand("s", "r2", "继续", "b"))
    await restarted.chat(ConversationCommand("s", "r3", "继续"))
    assert [request.model for request in model.requests] == ["model-a", "model-b", "model-b"]
    assert any(message.content == "问题" for message in model.requests[1].messages)
    assert len(await service.history("s")) == 6
    await restarted.delete("s")
    assert await service.history("s") == ()
    assert await repository.get_request(first) is None


async def test_duplicate_waits_without_second_generation_and_other_session_runs(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sessions.sqlite"
    await migrate_database(database)
    model = ControlledModel()
    model.release.clear()
    service = build_service(SqliteConversationRepository(database), model)
    command = ConversationCommand("s", "r", "问题")
    first = asyncio.create_task(service.chat(command))
    await model.entered.wait()
    duplicate = asyncio.create_task(service.chat(command))
    other = asyncio.create_task(service.chat(ConversationCommand("other", "r", "问题")))
    with pytest.raises(SessionBusyError):
        await service.delete("s")
    async with asyncio.timeout(5):
        await model.second_entered.wait()
    model.release.set()
    results = await asyncio.gather(first, duplicate, other)
    assert results[0] == results[1]
    assert len(model.requests) == 2
    assert service.locks._entries == {}


async def test_failed_waiter_does_not_automatically_retry_and_later_attempts_are_bounded(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sessions.sqlite"
    await migrate_database(database)
    model = ControlledModel()
    model.fail = True
    model.release.clear()
    repository = SqliteConversationRepository(database)
    service = build_service(repository, model)

    class ObservedLocks(SessionLocks):
        def __init__(self) -> None:
            super().__init__()
            self.waiter_entered = asyncio.Event()

        async def acquire(self, session_id: str, *, reject_busy: bool = False) -> SessionLease:
            if session_id in self._entries:
                self.waiter_entered.set()
            return await super().acquire(session_id, reject_busy=reject_busy)

    observed = ObservedLocks()
    service.locks = observed
    command = ConversationCommand("s", "r", "问题")
    first = asyncio.create_task(service.chat(command))
    await model.entered.wait()
    duplicate = asyncio.create_task(service.chat(command))
    async with asyncio.timeout(5):
        await observed.waiter_entered.wait()
    model.release.set()
    results = await asyncio.gather(first, duplicate, return_exceptions=True)
    assert all(isinstance(result, ModelUnavailableError) for result in results)
    assert len(model.requests) == 1
    for _ in range(2):
        with pytest.raises(ModelUnavailableError):
            await service.chat(command)
    with pytest.raises(RequestAttemptsExceeded):
        await service.chat(command)
    assert await service.history("s") == ()
    record = await repository.get_request(command)
    assert record and record.attempt == 3 and record.status == RequestStatus.FAILED


async def test_cancel_closes_upstream_releases_lock_and_restart_recovers_running(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sessions.sqlite"
    await migrate_database(database)
    repository = SqliteConversationRepository(database)
    model = ControlledModel()
    model.release.clear()
    service = build_service(repository, model)
    command = ConversationCommand("s", "r", "问题")
    running = asyncio.create_task(service.chat(command))
    await model.entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert model.closed == 1
    assert service.locks._entries == {}
    record = await repository.get_request(command)
    assert record and record.status == RequestStatus.INTERRUPTED
    assert await repository.history("s") == ()
    await repository.begin_request(command, "a")
    assert await repository.recover_interrupted() == 1
    model.release.set()
    await service.chat(command)
    succeeded = await repository.get_request(command)
    assert succeeded and succeeded.status == RequestStatus.SUCCEEDED


async def test_second_message_failure_rolls_back_whole_turn(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    await migrate_database(database)
    repository = SqliteConversationRepository(database)
    command = ConversationCommand("s", "r", "问题")
    await repository.begin_request(command, "a")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER fail_assistant BEFORE INSERT ON conversation_messages "
            "WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    with pytest.raises(ConversationStorageError):
        await repository.commit_reply(command, AssistantReply("回答"))
    assert await repository.history("s") == ()
    assert await repository.get_profile("s") is None
    record = await repository.get_request(command)
    assert record and record.status == RequestStatus.RUNNING


async def test_cancel_after_running_commit_during_prepare_marks_interrupted(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite"
    await migrate_database(database)
    registered = asyncio.Event()

    class PausedRepository(SqliteConversationRepository):
        async def begin_request(self, command: ConversationCommand, profile_id: str) -> None:
            await super().begin_request(command, profile_id)
            registered.set()
            await asyncio.Event().wait()

    repository = PausedRepository(database)
    model = ControlledModel()
    service = build_service(repository, model)
    command = ConversationCommand("s", "r", "问题")
    task = asyncio.create_task(service.prepare(command))
    await registered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = await repository.get_request(command)
    assert record and record.status == RequestStatus.INTERRUPTED
    assert service.locks._entries == {}
    assert model.requests == []


async def test_abandoned_prepared_request_can_release_without_starting_generator(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sessions.sqlite"
    await migrate_database(database)
    repository = SqliteConversationRepository(database)
    model = ControlledModel()
    service = build_service(repository, model)
    command = ConversationCommand("s", "r", "问题")
    prepared = await service.prepare(command)
    await prepared.aclose()
    await prepared.aclose()
    record = await repository.get_request(command)
    assert record and record.status == RequestStatus.INTERRUPTED
    assert service.locks._entries == {}
    assert model.requests == []
