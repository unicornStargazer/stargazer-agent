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
        release = self.release
        release.set()
        self.fail = False
        self.closed = 0

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
        requests = self.requests
        requests.append(request)
        entered = self.entered
        entered.set()
        item_count = len(self.requests)
        if item_count >= 2:
            second_entered = self.second_entered
            second_entered.set()
        try:
            release = self.release
            await release.wait()
            reasoning_delta = ReasoningDelta('公开摘要')
            yield reasoning_delta
            content_delta = ContentDelta('回答')
            yield content_delta
            if self.fail:
                model_unavailable_error = ModelUnavailableError('模拟网络失败')
                raise model_unavailable_error
            token_usage = TokenUsage(2, 3, 1, 5)
            usage_reported = UsageReported(token_usage)
            yield usage_reported
            model_completed = ModelCompleted('stop')
            yield model_completed
        finally:
            self.closed += 1


def build_service(repository: SqliteConversationRepository, model: ControlledModel) -> ConversationService:
    run_profile = RunProfile('a', 'model-a')
    run_profile_2 = RunProfile('b', 'model-b')
    profiles = ProfileCatalog((run_profile, run_profile_2), 'a')
    catalog = FilesystemSkillCatalog(())
    generated_runner = create_agent_runner(model, catalog)
    run_limits = RunLimits()
    service = ConversationService(repository, generated_runner, profiles, run_limits)
    return service


async def test_replay_survives_restart_switch_keeps_history_and_delete_cascades(tmp_path: Path) -> None:
    database = tmp_path / 'sessions.sqlite'
    await migrate_database(database)
    repository = SqliteConversationRepository(database)
    model = ControlledModel()
    service = build_service(repository, model)
    first = ConversationCommand('s', 'r1', '问题', 'a')
    reply = await service.chat(first)
    token_usage = TokenUsage(2, 3, 1, 5)
    assistant_reply = AssistantReply('回答', '公开摘要', token_usage)
    assert reply == assistant_reply
    restarted_repository = SqliteConversationRepository(database)
    restarted = build_service(restarted_repository, model)
    chat = await restarted.chat(first)
    assert chat == reply
    item_count = len(model.requests)
    assert item_count == 1
    expected_error = pytest.raises(RequestConflictError)
    with expected_error:
        conversation_command = ConversationCommand('s', 'r1', '不同问题', 'a')
        await restarted.chat(conversation_command)
    conversation_command_2 = ConversationCommand('s', 'r2', '继续', 'b')
    await restarted.chat(conversation_command_2)
    conversation_command_3 = ConversationCommand('s', 'r3', '继续')
    await restarted.chat(conversation_command_3)
    assert [request.model for request in model.requests] == ['model-a', 'model-b', 'model-b']
    any_result = any(message.content == '问题' for message in model.requests[1].messages)
    assert any_result
    history = await service.history('s')
    item_count_2 = len(history)
    assert item_count_2 == 6
    await restarted.delete('s')
    history_2 = await service.history('s')
    assert history_2 == ()
    stored_request = await repository.get_request(first)
    assert stored_request is None


async def test_duplicate_waits_without_second_generation_and_other_session_runs(tmp_path: Path) -> None:
    database = tmp_path / 'sessions.sqlite'
    await migrate_database(database)
    model = ControlledModel()
    release = model.release
    release.clear()
    restarted_repository = SqliteConversationRepository(database)
    service = build_service(restarted_repository, model)
    command = ConversationCommand('s', 'r', '问题')
    chat = service.chat(command)
    first = asyncio.create_task(chat)
    entered = model.entered
    await entered.wait()
    chat_2 = service.chat(command)
    duplicate = asyncio.create_task(chat_2)
    conversation_command = ConversationCommand('other', 'r', '问题')
    chat_3 = service.chat(conversation_command)
    other = asyncio.create_task(chat_3)
    expected_error = pytest.raises(SessionBusyError)
    with expected_error:
        await service.delete('s')
    timeout = asyncio.timeout(5)
    async with timeout:
        second_entered = model.second_entered
        await second_entered.wait()
    release_2 = model.release
    release_2.set()
    results = await asyncio.gather(first, duplicate, other)
    assert results[0] == results[1]
    item_count = len(model.requests)
    assert item_count == 2
    assert service.locks._entries == {}


async def test_failed_waiter_does_not_automatically_retry_and_later_attempts_are_bounded(tmp_path: Path) -> None:
    database = tmp_path / 'sessions.sqlite'
    await migrate_database(database)
    model = ControlledModel()
    model.fail = True
    release = model.release
    release.clear()
    repository = SqliteConversationRepository(database)
    service = build_service(repository, model)

    class ObservedLocks(SessionLocks):

        def __init__(self) -> None:
            SessionLocks.__init__(self)
            self.waiter_entered = asyncio.Event()

        async def acquire(self, session_id: str, *, reject_busy: bool=False) -> SessionLease:
            if session_id in self._entries:
                waiter_entered = self.waiter_entered
                waiter_entered.set()
            acquire = await SessionLocks.acquire(self, session_id, reject_busy=reject_busy)
            return acquire
    observed = ObservedLocks()
    service.locks = observed
    command = ConversationCommand('s', 'r', '问题')
    chat = service.chat(command)
    first = asyncio.create_task(chat)
    entered = model.entered
    await entered.wait()
    chat_2 = service.chat(command)
    duplicate = asyncio.create_task(chat_2)
    timeout = asyncio.timeout(5)
    async with timeout:
        waiter_entered = observed.waiter_entered
        await waiter_entered.wait()
    release_2 = model.release
    release_2.set()
    results = await asyncio.gather(first, duplicate, return_exceptions=True)
    unavailable_results = []
    for result in results:
        unavailable = isinstance(result, ModelUnavailableError)
        unavailable_results.append(unavailable)
    all_unavailable = all(unavailable_results)
    assert all_unavailable
    item_count = len(model.requests)
    assert item_count == 1
    range_result = range(2)
    for _ in range_result:
        expected_error = pytest.raises(ModelUnavailableError)
        with expected_error:
            await service.chat(command)
    expected_error_2 = pytest.raises(RequestAttemptsExceeded)
    with expected_error_2:
        await service.chat(command)
    history = await service.history('s')
    assert history == ()
    record = await repository.get_request(command)
    assert record and record.attempt == 3 and (record.status == RequestStatus.FAILED)


async def test_cancel_closes_upstream_releases_lock_and_restart_recovers_running(tmp_path: Path) -> None:
    database = tmp_path / 'sessions.sqlite'
    await migrate_database(database)
    repository = SqliteConversationRepository(database)
    model = ControlledModel()
    release = model.release
    release.clear()
    service = build_service(repository, model)
    command = ConversationCommand('s', 'r', '问题')
    chat = service.chat(command)
    running = asyncio.create_task(chat)
    entered = model.entered
    await entered.wait()
    running.cancel()
    expected_error = pytest.raises(asyncio.CancelledError)
    with expected_error:
        await running
    assert model.closed == 1
    assert service.locks._entries == {}
    record = await repository.get_request(command)
    assert record and record.status == RequestStatus.INTERRUPTED
    history = await repository.history('s')
    assert history == ()
    await repository.begin_request(command, 'a')
    recovered_count = await repository.recover_interrupted()
    assert recovered_count == 1
    release_2 = model.release
    release_2.set()
    await service.chat(command)
    succeeded = await repository.get_request(command)
    assert succeeded and succeeded.status == RequestStatus.SUCCEEDED


async def test_second_message_failure_rolls_back_whole_turn(tmp_path: Path) -> None:
    database = tmp_path / 'sessions.sqlite'
    await migrate_database(database)
    repository = SqliteConversationRepository(database)
    command = ConversationCommand('s', 'r', '问题')
    await repository.begin_request(command, 'a')
    database_connection = sqlite3.connect(database)
    with database_connection as connection:
        connection.execute("CREATE TRIGGER fail_assistant BEFORE INSERT ON conversation_messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    expected_error = pytest.raises(ConversationStorageError)
    with expected_error:
        assistant_reply = AssistantReply('回答')
        await repository.commit_reply(command, assistant_reply)
    history = await repository.history('s')
    assert history == ()
    stored_profile = await repository.get_profile('s')
    assert stored_profile is None
    record = await repository.get_request(command)
    assert record and record.status == RequestStatus.RUNNING


async def test_cancel_after_running_commit_during_prepare_marks_interrupted(tmp_path: Path) -> None:
    database = tmp_path / 'sessions.sqlite'
    await migrate_database(database)
    registered = asyncio.Event()

    class PausedRepository(SqliteConversationRepository):

        async def begin_request(self, command: ConversationCommand, profile_id: str) -> None:
            await SqliteConversationRepository.begin_request(self, command, profile_id)
            registered.set()
            event = asyncio.Event()
            await event.wait()
    repository = PausedRepository(database)
    model = ControlledModel()
    service = build_service(repository, model)
    command = ConversationCommand('s', 'r', '问题')
    prepare = service.prepare(command)
    task = asyncio.create_task(prepare)
    await registered.wait()
    task.cancel()
    expected_error = pytest.raises(asyncio.CancelledError)
    with expected_error:
        await task
    record = await repository.get_request(command)
    assert record and record.status == RequestStatus.INTERRUPTED
    assert service.locks._entries == {}
    assert model.requests == []


async def test_abandoned_prepared_request_can_release_without_starting_generator(tmp_path: Path) -> None:
    database = tmp_path / 'sessions.sqlite'
    await migrate_database(database)
    repository = SqliteConversationRepository(database)
    model = ControlledModel()
    service = build_service(repository, model)
    command = ConversationCommand('s', 'r', '问题')
    prepared = await service.prepare(command)
    await prepared.aclose()
    await prepared.aclose()
    record = await repository.get_request(command)
    assert record and record.status == RequestStatus.INTERRUPTED
    assert service.locks._entries == {}
    assert model.requests == []
