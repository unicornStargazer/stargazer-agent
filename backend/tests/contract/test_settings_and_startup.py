"""配置文件和启动契约，重点验证路径、敏感信息及未就绪状态。"""
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from dokkan_agent.bootstrap.application import create_app
from dokkan_agent.bootstrap.settings import ConfigurationError, load_settings
from dokkan_agent.main import main


def write_configuration(root: Path, configuration: dict[str, Any]) -> Path:
    path = root / 'settings.json'
    serialized_payload = json.dumps(configuration)
    path.write_text(serialized_payload, encoding='utf-8')
    return path


def test_paths_are_rooted_at_project_not_cwd(tmp_path: Path, configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    configuration.pop('runtime')
    path = write_configuration(tmp_path, configuration)
    child = tmp_path / 'unrelated'
    child.mkdir()
    monkeypatch.chdir(child)
    loaded = load_settings(tmp_path, path)
    assert loaded.database_path == tmp_path / 'backend/data/development.sqlite'
    assert loaded.skills_directory == tmp_path / 'backend/examples/skills'
    assert loaded.settings.runtime.max_model_calls == 12
    assert loaded.settings.agents.profiles[0].history_limit == 12
    database_path = loaded.database_path
    path_exists = database_path.exists()
    assert not path_exists


@pytest.mark.parametrize('invalid_value', [0, True, '3001', 65536])
def test_invalid_port_is_rejected_without_leaking_key(tmp_path: Path, configuration: dict[str, Any], invalid_value: object) -> None:
    configuration['provider']['apiKey'] = 'test-secret-not-for-output'
    configuration['server']['port'] = invalid_value
    path = write_configuration(tmp_path, configuration)
    expected_error = pytest.raises(ConfigurationError)
    with expected_error as captured:
        load_settings(tmp_path, path)
    error_text = str(captured.value)
    assert 'server.port' in error_text
    error_text_2 = str(captured.value)
    assert 'test-secret-not-for-output' not in error_text_2


@pytest.mark.parametrize('problem', ['duplicate', 'unknown_default', 'skill_binding', 'budget'])
def test_cross_field_and_runtime_rules(tmp_path: Path, configuration: dict[str, Any], problem: str) -> None:
    if problem == 'duplicate':
        configuration['agents']['profiles'] *= 2
    elif problem == 'unknown_default':
        configuration['agents']['defaultProfileId'] = 'missing'
    elif problem == 'skill_binding':
        configuration['agents']['profiles'][0]['skillIds'] = ['business']
    else:
        configuration['runtime']['maxToolExecutions'] = 0
    path = write_configuration(tmp_path, configuration)
    expected_error = pytest.raises(ConfigurationError)
    with expected_error:
        load_settings(tmp_path, path)


async def test_startup_migrates_only_explicit_temp_database_without_model_request(tmp_path: Path, configuration: dict[str, Any]) -> None:
    configuration.pop('skillsDirectory')
    path = write_configuration(tmp_path, configuration)
    app = create_app(path, tmp_path)
    data_directory = tmp_path / 'backend/data'
    path_exists = data_directory.exists()
    assert not path_exists
    router = app.router
    lifespan_context = router.lifespan_context(app)
    async with lifespan_context:
        transport = ASGITransport(app=app)
        http_client = AsyncClient(transport=transport, base_url='http://test')
        async with http_client as client:
            response = await client.get('/health/live')
            payload = response.json()
            assert payload == {'alive': True}
            response = await client.get('/health/ready')
            assert response.status_code == 200
            payload_2 = response.json()
            assert payload_2['ready'] is True
            http_response = await client.get('/api/status')
            payload_3 = http_response.json()
            assert payload_3['conversationStorage'] == 'sqlite'
            http_response_2 = await client.get('/openapi.json')
            assert 'apiKey' not in http_response_2.text
    assert app.state.started is False
    database_path = tmp_path / 'backend/data/development.sqlite'
    database_exists = database_path.is_file()
    assert database_exists


def test_malformed_or_missing_configuration_is_sanitized(tmp_path: Path) -> None:
    path = tmp_path / 'settings.json'
    path.write_text('{"apiKey":"secret-value", broken}', encoding='utf-8')
    expected_error = pytest.raises(ConfigurationError, match='有效 JSON')
    with expected_error as captured:
        load_settings(tmp_path, path)
    error_text = str(captured.value)
    assert 'secret-value' not in error_text
    path.unlink()
    expected_error_2 = pytest.raises(ConfigurationError, match='无法读取')
    with expected_error_2:
        load_settings(tmp_path, path)


def test_omitted_history_limit_preserves_legacy_unlimited_semantics(tmp_path: Path, configuration: dict[str, Any]) -> None:
    profile = configuration['agents']['profiles'][0]
    profile.pop('historyLimit')
    path = write_configuration(tmp_path, configuration)
    loaded = load_settings(tmp_path, path)
    assert loaded.settings.agents.profiles[0].history_limit is None
    snapshot = repr(loaded)
    assert 'replace-with-local-key' not in snapshot
    configuration['agents']['profiles'][0]['historyLimit'] = None
    path = write_configuration(tmp_path, configuration)
    expected_error = pytest.raises(ConfigurationError)
    with expected_error:
        load_settings(tmp_path, path)


def test_cli_explicit_project_root_uses_file_host_and_port(tmp_path: Path, configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    write_configuration(tmp_path, configuration)
    error_text = str(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['dokkan-agent', '--project-root', error_text, '--config', 'settings.json'])
    server_patch = patch('dokkan_agent.main.uvicorn.run', autospec=True)
    with server_patch as server:
        main()
    server.assert_called_once()
    assert server.call_args.kwargs == {'host': '127.0.0.1', 'port': 3001, 'workers': 1}
    assert server.call_args.args[0].state.configuration.project_root == tmp_path
