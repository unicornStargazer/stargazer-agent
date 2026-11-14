"""Python HTTP 全链路兼容测试：临时配置/SQLite，HTTPX 模拟上游，不接真实服务。"""
import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.types import Message

from dokkan_agent.bootstrap.application import create_app


def frame(payload: object) -> bytes:
    matches_type = isinstance(payload, str)
    if matches_type:
        selected_value = payload
    else:
        selected_value = json.dumps(payload, ensure_ascii=False)
    text = selected_value
    value = f'data: {text}\n\n'
    encode = value.encode()
    return encode


def completion(content: str='回答', finish: str='stop') -> bytes:
    value = b''
    frame_2 = frame({'choices': [{'index': 0, 'delta': {'reasoning_content': '公开摘要'}, 'finish_reason': None}]})
    frame_3 = frame({'choices': [{'index': 0, 'delta': {'content': content}, 'finish_reason': finish}]})
    frame_4 = frame({'choices': [], 'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}})
    frame_5 = frame('[DONE]')
    join = value.join([frame_2, frame_3, frame_4, frame_5])
    return join


def make_app(tmp_path: Path, configuration: dict[str, Any], handler: Callable[[httpx.Request], httpx.Response]) -> FastAPI:
    configuration.pop('skillsDirectory', None)
    configuration['storage']['databasePath'] = 'test.sqlite'
    configuration['agents']['profiles'] = [
        {'id': 'a', 'name': '模型 A', 'model': 'model-a', 'historyLimit': 12},
        {'id': 'b', 'name': '模型 B', 'model': 'model-b', 'historyLimit': 12},
    ]
    configuration['agents']['defaultProfileId'] = 'a'
    path = tmp_path / 'config.json'
    serialized_payload = json.dumps(configuration)
    path.write_text(serialized_payload, encoding='utf-8')
    mock_transport = httpx.MockTransport(handler)
    create_app_2 = create_app(path, tmp_path, model_transport=mock_transport)
    return create_app_2


async def test_stream_persists_metadata_replays_after_restart_and_switches_model(tmp_path: Path, configuration: dict[str, Any]) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        parsed_payload = json.loads(request.content)
        requests.append(parsed_payload)
        completion_2 = completion()
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=completion_2)
        return response
    body = {'sessionId': 'same', 'requestId': 'r1', 'message': '你好', 'profileId': 'a'}
    for restart in (False, True):
        app = make_app(tmp_path, configuration, handler)
        router = app.router
        lifespan_context = router.lifespan_context(app)
        async with lifespan_context:
            transport = httpx.ASGITransport(app=app)
            http_client = httpx.AsyncClient(transport=transport, base_url='http://test')
            async with http_client as client:
                response = await client.post('/api/chat/stream', json=body)
                assert response.status_code == 200
                assert response.headers['cache-control'] == 'no-store'
                assert response.headers['x-content-type-options'] == 'nosniff'
                text = response.text
                count = text.count('event: done')
                assert count == 1
                assert 'event: error' not in response.text
                assert '"totalTokens":5' in response.text
                assert '公开摘要' in response.text
                item_count = len(requests)
                assert item_count == 1
                http_response = await client.get('/api/history?sessionId=same')
                payload = http_response.json()
                history = payload['messages']
                assert history == [{'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '回答', 'reasoning': '公开摘要', 'usage': {'inputTokens': 2, 'outputTokens': 3, 'totalTokens': 5}}]
                if restart:
                    switched = await client.post('/api/chat', json={**body, 'requestId': 'r2', 'profileId': 'b'})
                    assert switched.status_code == 200
                    continued = await client.post('/api/chat', json={'sessionId': 'same', 'requestId': 'r3', 'message': '继续'})
                    assert continued.status_code == 200
                    assert [request['model'] for request in requests] == ['model-a', 'model-b', 'model-b']
                    http_response_2 = await client.get('/api/history?sessionId=same')
                    payload_2 = http_response_2.json()
                    item_count_2 = len(payload_2['messages'])
                    assert item_count_2 == 6
                    assert [message['role'] for message in requests[1]['messages']][-3:] == ['user', 'assistant', 'user']
                    delete = await client.delete('/api/history?sessionId=same')
                    payload_3 = delete.json()
                    assert payload_3 == {'deleted': True}


@pytest.mark.parametrize('case', [(b'{}', {'content-type': 'text/plain'}, 415, 'UNSUPPORTED_MEDIA_TYPE'), (b'{', {'content-type': 'application/json'}, 400, 'INVALID_REQUEST'), (b'[]', {'content-type': 'application/json'}, 400, 'INVALID_REQUEST'), (b'x' * 32769, {'content-type': 'application/json'}, 413, 'REQUEST_TOO_LARGE'), (b'{"sessionId":"s","requestId":"r","message":"hello","profileId":null}', {'content-type': 'application/json'}, 400, 'INVALID_REQUEST'), (b'{"sessionId":"s","requestId":"r","message":"hello","profileId":"unknown"}', {'content-type': 'application/json'}, 400, 'UNKNOWN_PROFILE')])
async def test_preflight_errors_are_http_and_sanitized(tmp_path: Path, configuration: dict[str, Any], case: tuple[bytes, dict[str, str], int, str]) -> None:
    payload, headers, status, code = case

    def forbidden(request: httpx.Request) -> httpx.Response:
        assertion_error = AssertionError('参数失败不能连接模型')
        raise assertion_error
    app = make_app(tmp_path, configuration, forbidden)
    router = app.router
    lifespan_context = router.lifespan_context(app)
    async with lifespan_context:
        transport = httpx.ASGITransport(app=app)
        http_client = httpx.AsyncClient(transport=transport, base_url='http://test')
        async with http_client as client:
            response = await client.post('/api/chat/stream', content=payload, headers=headers)
            assert response.status_code == status
            payload_2 = response.json()
            assert payload_2['error']['code'] == code
            assert 'apiKey' not in response.text
            assert 'event:' not in response.text


async def test_commit_failure_after_content_emits_error_without_done_or_history(tmp_path: Path, configuration: dict[str, Any]) -> None:

    def handler_2(request: httpx.Request) -> httpx.Response:
        completion_2 = completion()
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=completion_2)
        return response
    app = make_app(tmp_path, configuration, handler_2)
    router = app.router
    lifespan_context = router.lifespan_context(app)
    async with lifespan_context:
        database_connection = sqlite3.connect(tmp_path / 'test.sqlite')
        with database_connection as connection:
            connection.execute("CREATE TRIGGER fail_commit BEFORE INSERT ON conversation_messages WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'test'); END")
        transport = httpx.ASGITransport(app=app)
        http_client = httpx.AsyncClient(transport=transport, base_url='http://test')
        async with http_client as client:
            response = await client.post('/api/chat/stream', json={'sessionId': 's', 'requestId': 'r', 'message': '你好'})
            assert 'event: chunk' in response.text
            assert 'CONVERSATION_STORAGE_UNAVAILABLE' in response.text
            assert 'event: done' not in response.text
            text = response.text
            count = text.count('event: error')
            assert count == 1
            http_response = await client.get('/api/history?sessionId=s')
            payload = http_response.json()
            assert payload == {'messages': []}


async def test_tool_loop_keeps_reasoning_usage_and_all_visible_content(tmp_path: Path, configuration: dict[str, Any], skill_directory: Path) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        item_count = len(requests)
        if item_count == 1:
            result = completion('先分析', 'tool_calls')
            data = {
                'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'id': 'call-a', 'type': 'function', 'function': {'name': 'activate_skill', 'arguments': '{"name":"analysis-test"}'}}]}, 'finish_reason': None}],
            }
            tool = frame(data)
            result = tool + result
        else:
            assert payload['messages'][-1]['role'] == 'tool'
            assert payload['messages'][-1]['tool_call_id'] == 'call-a'
            assert 'ANALYSIS_BODY' in payload['messages'][-1]['content']
            result = completion('最终回答')
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=result)
        return response
    app = make_app(tmp_path, configuration, handler)
    # make_app 默认不加载 Skill；本用例显式指定测试目录后重建组合根。
    path = tmp_path / 'config.json'
    document_text = path.read_text(encoding='utf-8')
    settings = json.loads(document_text)
    settings['skillsDirectory'] = str(skill_directory)
    serialized_payload = json.dumps(settings)
    path.write_text(serialized_payload, encoding='utf-8')
    mock_transport = httpx.MockTransport(handler)
    app = create_app(path, tmp_path, model_transport=mock_transport)
    router = app.router
    lifespan_context = router.lifespan_context(app)
    async with lifespan_context:
        transport = httpx.ASGITransport(app=app)
        http_client = httpx.AsyncClient(transport=transport, base_url='http://test')
        async with http_client as client:
            response = await client.post('/api/chat/stream', json={'sessionId': 's', 'requestId': 'r', 'message': '分析'})
            assert 'event: done' in response.text, response.text
            item_count = len(requests)
            assert item_count == 2
            http_response = await client.get('/api/history?sessionId=s')
            payload = http_response.json()
            saved = payload['messages'][-1]
            assert saved['content'] == '先分析最终回答'
            assert saved['reasoning'] == '公开摘要公开摘要'
            assert saved['usage'] == {'inputTokens': 4, 'outputTokens': 6, 'totalTokens': 10}
            serialized_payload_2 = json.dumps(requests[0], ensure_ascii=False)
            assert 'ANALYSIS_BODY' not in serialized_payload_2


async def test_static_files_cannot_escape_and_api_never_returns_html(tmp_path: Path, configuration: dict[str, Any]) -> None:
    public = tmp_path / 'web/dist'
    assets_directory = public / 'assets'
    assets_directory.mkdir(parents=True)
    index_path = public / 'index.html'
    index_path.write_text('<html>test</html>', encoding='utf-8')
    script_path = public / 'assets/app.js'
    script_path.write_text('export {};', encoding='utf-8')

    def handler_3(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(500)
        return response
    backend_root = tmp_path / 'backend'
    backend_root.mkdir()
    app = make_app(backend_root, configuration, handler_3)
    router = app.router
    lifespan_context = router.lifespan_context(app)
    async with lifespan_context:
        transport = httpx.ASGITransport(app=app)
        http_client = httpx.AsyncClient(transport=transport, base_url='http://test')
        async with http_client as client:
            http_response = await client.get('/')
            assert http_response.status_code == 200
            http_response_2 = await client.get('/assets/app.js')
            assert 'immutable' in http_response_2.headers['cache-control']
            for path in ('/api/missing', '/%2e%2e/config.json', '/C:/Windows/win.ini', '/..%5cconfig.json'):
                http_response_3 = await client.get(path)
                assert http_response_3.status_code == 404
            http_response_4 = await client.get('/api/profiles')
            payload = http_response_4.json()
            assert payload == {'profiles': [{'id': 'a', 'name': '模型 A', 'model': 'model-a'}, {'id': 'b', 'name': '模型 B', 'model': 'model-b'}]}


@pytest.mark.parametrize('route', ['/api/chat/stream', '/api/chat'])
async def test_asgi_disconnect_cancels_upstream_and_releases_session(tmp_path: Path, configuration: dict[str, Any], route: str) -> None:
    entered = asyncio.Event()
    closed = asyncio.Event()

    class BlockingStream(httpx.AsyncByteStream):

        async def __aiter__(self) -> AsyncIterator[bytes]:
            frame_2 = frame({'choices': [{'delta': {'content': 'partial'}, 'finish_reason': None}]})
            yield frame_2
            entered.set()
            event = asyncio.Event()
            await event.wait()

        async def aclose(self) -> None:
            closed.set()

    def handler_4(request: httpx.Request) -> httpx.Response:
        blocking_stream = BlockingStream()
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=blocking_stream)
        return response
    app = make_app(tmp_path, configuration, handler_4)
    serialized_payload = json.dumps({'sessionId': 's', 'requestId': 'r', 'message': '你好'})
    body = serialized_payload.encode()
    sent_body = False
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        await entered.wait()
        return {'type': 'http.disconnect'}

    async def send(message: Message) -> None:
        sent.append(message)
    encode = route.encode()
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'http',
        'path': route,
        'raw_path': encode,
        'query_string': b'',
        'headers': [(b'content-type', b'application/json')],
        'client': ('127.0.0.1', 1234),
        'server': ('127.0.0.1', 3001),
    }
    router = app.router
    lifespan_context = router.lifespan_context(app)
    async with lifespan_context:
        timeout = asyncio.timeout(5)
        async with timeout:
            if route == '/api/chat':
                expected_error = pytest.raises(asyncio.CancelledError)
                with expected_error:
                    await app(scope, receive, send)
            else:
                await app(scope, receive, send)
        is_set = closed.is_set()
        assert is_set
        service = app.state.services.conversations
        assert service.locks._entries == {}
        history = await service.history('s')
        assert history == ()
        database_connection = sqlite3.connect(tmp_path / 'test.sqlite')
        with database_connection as connection:
            cursor = connection.execute('SELECT status FROM agent_requests')
            fetchone = cursor.fetchone()
            assert fetchone == ('interrupted',)
