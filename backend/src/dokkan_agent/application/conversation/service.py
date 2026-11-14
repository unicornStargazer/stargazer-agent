"""对话应用入口；幂等和提交属于会话用例，模型/工具循环由 AgentRunner 承担。"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing

import anyio

from dokkan_agent.application.conversation.history import complete_turns
from dokkan_agent.application.conversation.profiles import ProfileCatalog
from dokkan_agent.application.conversation.session_locks import SessionLease, SessionLocks
from dokkan_agent.application.runtime.models import RunFinished, RunInput
from dokkan_agent.application.runtime.runner import AgentRunner
from dokkan_agent.domain.agent.budget import RunLimits
from dokkan_agent.domain.agent.models import ContentDelta, ReasoningDelta, UsageReported
from dokkan_agent.domain.conversation.errors import (
    ConversationStorageError,
    InterruptedRequestError,
    RequestConflictError,
)
from dokkan_agent.domain.conversation.models import (
    AssistantReply,
    ConversationCommand,
    ConversationTurn,
    RequestStatus,
)
from dokkan_agent.domain.conversation.ports import ConversationRepository, HistoryMessage

LOGGER = logging.getLogger(__name__)
type ConversationEvent = ContentDelta | ReasoningDelta | UsageReported | AssistantReply


class PreparedConversation:
    """持有一条会话租约；调用方必须消费 stream 或调用 aclose，HTTP 头前即可完成校验。"""

    def __init__(self, service: "ConversationService", lease: SessionLease, request: RunInput, replay: AssistantReply | None) -> None:
        self._service = service
        self._lease = lease
        self._request = request
        self._replay = replay
        self._settled = replay is not None
        self._closed = False
        self._started = False
        self._started_at = time.monotonic()

    async def stream(self) -> AsyncGenerator[ConversationEvent, None]:
        """仅提交后产生 AssistantReply 终止结果；它不等于模型的 finish_reason。"""
        if self._started or self._closed:
            raise RuntimeError("会话流只能消费一次")
        self._started = True
        request = self._request
        service = self._service
        repository = service.repository
        try:
            if self._replay is not None:
                if self._replay.reasoning:
                    reasoning = ReasoningDelta(self._replay.reasoning)
                    yield reasoning
                if self._replay.usage is not None:
                    usage = UsageReported(self._replay.usage)
                    yield usage
                content = ContentDelta(self._replay.content)
                yield content
                yield self._replay
                return
            runner = service.runner
            stream = runner.stream(request, service.limits)
            closing = aclosing(stream)
            async with closing as events:
                async for event in events:
                    match event:
                        case RunFinished():
                            await repository.commit_reply(request.command, event.result.reply)
                            self._settled = True
                            now = time.monotonic()
                            duration_ms = int((now - self._started_at) * 1000)
                            message = (
                                "会话提交成功 session=%s request=%s profile=%s model_calls=%d "
                                "tool_executions=%d duration_ms=%d"
                            )
                            LOGGER.info(message, request.command.session_id, request.command.request_id, request.profile.id, event.result.model_calls, event.result.tool_executions, duration_ms)
                            yield event.result.reply
                            return
                        case _:
                            yield event
            raise RuntimeError("Agent 未返回完整结果")
        except Exception as error:
            error_type = type(error)
            code = error_type.__name__
            LOGGER.warning("会话运行失败 session=%s request=%s error_type=%s", request.command.session_id, request.command.request_id, code)
            lease = self._lease
            entry = lease.entry
            command = request.command
            fingerprint = command.fingerprint()
            entry.failures[request.command.request_id] = (fingerprint, error)
            await self._mark_failure(RequestStatus.FAILED, code)
            raise
        finally:
            await self.aclose()

    async def _mark_failure(self, status: RequestStatus, code: str) -> None:
        if self._settled:
            return
        service = self._service
        repository = service.repository
        request = self._request
        try:
            await repository.fail_request(request.command, status, code)
        except ConversationStorageError:
            # 故障不覆盖原始异常；遗留 running 将在下次启动收敛。
            LOGGER.error("请求状态写回失败 session=%s request=%s", request.command.session_id, request.command.request_id)
        self._settled = True

    async def aclose(self) -> None:
        """放弃或取消运行时标记 interrupted；成功后的重复关闭无副作用。"""
        if self._closed:
            return
        self._closed = True
        try:
            if not self._settled:
                lease = self._lease
                entry = lease.entry
                request = self._request
                command = request.command
                fingerprint = command.fingerprint()
                error = InterruptedRequestError("原请求已中断。")
                entry.failures[command.request_id] = (fingerprint, error)
                # 独立任务防止 asyncio 取消打断状态清理；调用方仍负责关闭上游生成器。
                # ASGI 使用层级取消作用域；仅 asyncio.shield 不能保护其子任务。
                scope = anyio.CancelScope(shield=True)
                with scope:
                    failure = self._mark_failure(RequestStatus.INTERRUPTED, "INTERRUPTED")
                    cleanup = asyncio.create_task(failure)
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        await cleanup
                        raise
        finally:
            service = self._service
            locks = service.locks
            locks.release(self._lease)


class ConversationService:
    def __init__(self, repository: ConversationRepository, runner: AgentRunner, profiles: ProfileCatalog, limits: RunLimits) -> None:
        self.repository = repository
        self.runner = runner
        self.profiles = profiles
        self.limits = limits
        self.locks = SessionLocks()

    async def prepare(self, command: ConversationCommand) -> PreparedConversation:
        """先串行、去重、选择模型再登记 running；失败时释放租约，不执行网络请求。"""
        locks = self.locks
        lease = await locks.acquire(command.session_id)
        repository = self.repository
        profiles = self.profiles
        try:
            failure = None
            if lease.waited:
                entry = lease.entry
                failures = entry.failures
                failure = failures.get(command.request_id)
            if failure:
                fingerprint = command.fingerprint()
                if failure[0] != fingerprint:
                    raise RequestConflictError("请求 ID 已用于其他输入。")
                raise failure[1]
            existing = await repository.get_request(command)
            replay = (
                existing.response
                if existing and existing.status == RequestStatus.SUCCEEDED
                else None
            )
            if replay:
                # 重放不要求旧模型配置仍存在，更不应连接 Provider。
                profile = profiles.default
            else:
                profile_id = command.profile_id
                if not profile_id:
                    profile_id = await repository.get_profile(command.session_id)
                profile = profiles.select(profile_id)
            history: tuple[ConversationTurn, ...] = ()
            if not replay:
                messages = await repository.history(command.session_id)
                history = complete_turns(messages)
            request = RunInput(command, profile, history)
            if replay is None:
                await repository.begin_request(command, profile.id)
            prepared = PreparedConversation(self, lease, request, replay)
            return prepared
        except BaseException:
            try:
                # begin_request 可能已提交但返回前被取消；只收敛同指纹 running，
                # 不会修改已成功记录，也不把尚未创建的请求插入数据库。
                scope = anyio.CancelScope(shield=True)
                with scope:
                    await repository.fail_request(command, RequestStatus.INTERRUPTED, "INTERRUPTED")
            except ConversationStorageError:
                LOGGER.error("准备阶段状态清理失败 session=%s request=%s", command.session_id, command.request_id)
            finally:
                locks.release(lease)
            raise

    async def chat(self, command: ConversationCommand) -> AssistantReply:
        prepared = await self.prepare(command)
        stream = prepared.stream()
        closing = aclosing(stream)
        async with closing as events:
            async for event in events:
                match event:
                    case AssistantReply():
                        return event
        raise RuntimeError("会话未完成")

    async def history(self, session_id: str) -> tuple[HistoryMessage, ...]:
        repository = self.repository
        history = await repository.history(session_id)
        return history

    async def delete(self, session_id: str) -> None:
        locks = self.locks
        lease = await locks.acquire(session_id, reject_busy=True)
        repository = self.repository
        try:
            await repository.delete(session_id)
        finally:
            locks.release(lease)
