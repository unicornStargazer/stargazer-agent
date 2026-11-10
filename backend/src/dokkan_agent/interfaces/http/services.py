"""HTTP 所需应用依赖的显式快照；组合根注入，不在路由内创建存储或模型。"""

from dataclasses import dataclass

from fastapi import Request

from dokkan_agent.application.conversation.service import ConversationService
from dokkan_agent.interfaces.http.schemas import ProfileResponse


@dataclass(frozen=True, slots=True)
class HttpServices:
    conversations: ConversationService
    profiles: tuple[ProfileResponse, ...]
    default_profile: ProfileResponse


def get_services(request: Request) -> HttpServices:
    services: HttpServices = request.app.state.services
    return services
