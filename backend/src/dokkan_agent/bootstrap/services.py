"""把文件配置转成应用依赖；模型配置不向 Skill 目录或 HTTP 请求泄漏。"""

from dokkan_agent.application.conversation.profiles import ProfileCatalog
from dokkan_agent.application.conversation.service import ConversationService
from dokkan_agent.application.runtime.models import RunProfile
from dokkan_agent.application.runtime.runner import AgentRunner
from dokkan_agent.bootstrap.runtime import create_run_limits
from dokkan_agent.bootstrap.settings import ProfileSettings, Settings
from dokkan_agent.domain.conversation.ports import ConversationRepository
from dokkan_agent.interfaces.http.schemas import ProfileResponse
from dokkan_agent.interfaces.http.services import HttpServices


def create_http_services(settings: Settings, repository: ConversationRepository, runner: AgentRunner) -> HttpServices:
    run_profiles: list[RunProfile] = []
    public_profiles: list[ProfileResponse] = []
    for profile in settings.agents.profiles:
        run_profile = _run_profile(profile)
        run_profiles.append(run_profile)
        public_profile = ProfileResponse(id=profile.id, name=profile.name, model=profile.model)
        public_profiles.append(public_profile)
    configured_profiles = tuple(run_profiles)
    profiles = ProfileCatalog(configured_profiles, settings.agents.default_profile_id)
    public = tuple(public_profiles)
    limits = create_run_limits(settings.runtime)
    conversations = ConversationService(repository, runner, profiles, limits)
    default_candidates = (profile for profile in public if profile.id == profiles.default.id)
    default_profile = next(default_candidates)
    services = HttpServices(conversations, public, default_profile)
    return services


def _run_profile(profile: ProfileSettings) -> RunProfile:
    run_profile = RunProfile(profile.id, profile.model, profile.system_prompt, profile.history_limit, profile.supports_tools)
    return run_profile
