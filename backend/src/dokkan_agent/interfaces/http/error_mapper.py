"""应用异常到稳定 HTTP/SSE 错误的唯一映射；绝不回传异常原文。"""

import logging
from dataclasses import dataclass
from typing import cast

from fastapi import Request
from fastapi.responses import JSONResponse

from dokkan_agent.application.runtime.models import ExplicitSkillError, ModelProtocolError
from dokkan_agent.domain.agent.budget import BudgetExceeded
from dokkan_agent.domain.agent.errors import ModelCapabilityError, ModelUnavailableError
from dokkan_agent.domain.conversation.errors import (
    ConversationStorageError,
    InterruptedRequestError,
    RequestAttemptsExceeded,
    RequestConflictError,
    SessionBusyError,
    UnknownProfileError,
)
from dokkan_agent.domain.skill.errors import SkillAccessError
from dokkan_agent.interfaces.http.errors import ErrorCode, ErrorDetail, ErrorResponse

LOGGER = logging.getLogger(__name__)


@dataclass
class ApiError(Exception):
    status: int
    code: ErrorCode
    message: str


ERROR_MAPPINGS = (
    (RequestConflictError, 409, ErrorCode.REQUEST_CONFLICT, "请求 ID 已用于其他输入。"),
    (SessionBusyError, 409, ErrorCode.SESSION_BUSY, "会话正在生成回复，暂时无法删除。"),
    (UnknownProfileError, 400, ErrorCode.UNKNOWN_PROFILE, "模型配置不存在，请重新选择。"),
    (
        ConversationStorageError,
        503,
        ErrorCode.CONVERSATION_STORAGE_UNAVAILABLE,
        "会话存储暂时不可用。",
    ),
    (
        ModelCapabilityError,
        502,
        ErrorCode.MODEL_CAPABILITY_UNSUPPORTED,
        "所选模型不支持所需的工具能力。",
    ),
    (BudgetExceeded, 422, ErrorCode.AGENT_BUDGET_EXCEEDED, "本次运行已达到预算上限。"),
    (ExplicitSkillError, 503, ErrorCode.SKILL_UNAVAILABLE, "指定的 Skill 不存在或不可用。"),
    (SkillAccessError, 503, ErrorCode.SKILL_UNAVAILABLE, "Skill 暂时不可用，请检查部署文件。"),
    (
        RequestAttemptsExceeded,
        409,
        ErrorCode.REQUEST_CONFLICT,
        "该请求已达三次尝试上限，请重新发送。",
    ),
    (InterruptedRequestError, 502, ErrorCode.MODEL_UNAVAILABLE, "原请求已中断，请稍后重试。"),
    (ModelProtocolError, 502, ErrorCode.MODEL_UNAVAILABLE, "模型未返回完整结果，请稍后重试。"),
    (ModelUnavailableError, 502, ErrorCode.MODEL_UNAVAILABLE, "模型暂时不可用，请稍后重试。"),
)


def map_error(error: Exception) -> ApiError:
    is_api_error = isinstance(error, ApiError)
    if is_api_error:
        mapped_error = cast(ApiError, error)
        return mapped_error
    for error_type, status, code, message in ERROR_MAPPINGS:
        matches = isinstance(error, error_type)
        if matches:
            mapped = ApiError(status, code, message)
            return mapped
    unexpected_type = type(error)
    LOGGER.error("未预期的应用异常 type=%s", unexpected_type.__name__)
    mapped = ApiError(500, ErrorCode.INTERNAL_ERROR, "服务内部发生错误。")
    return mapped


async def handle_error(request: Request, error: Exception) -> JSONResponse:
    mapped = map_error(error)
    detail = ErrorDetail(code=mapped.code, message=mapped.message)
    payload = ErrorResponse(error=detail)
    content = payload.model_dump(by_alias=True)
    response = JSONResponse(status_code=mapped.status, content=content)
    return response
