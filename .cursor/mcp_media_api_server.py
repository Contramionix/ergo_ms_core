"""
MCP сервер для работы с media_api проекта ErgoMS.
Подписанные URL, upload-токены и internal API (meta/read/write/delete).
"""

import asyncio
import base64
import json
import mimetypes
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

_cursor_dir = Path(__file__).parent.resolve()
PROJECT_DIR = _cursor_dir.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from core.shared.media_hmac import create_upload_token, sign_url

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


_DEPLOYMENT_DIR = PROJECT_DIR / 'core' / 'deployment'
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from env_file_loader import load_project_env  # noqa: E402

SECRET_KEY: Optional[str] = None
PUBLIC_BASE_URL: Optional[str] = None
INTERNAL_BASE_URL: Optional[str] = None
INTERNAL_KEY: Optional[str] = None
AUTH_TOKEN: Optional[str] = None
API_BASE_URL: Optional[str] = None
DEFAULT_USER_ID: int = 1
MEDIA_URL_EXPIRATION = 3600
MEDIA_UPLOAD_MAX_SIZE = 104857600
MEDIA_UPLOAD_TOKEN_EXPIRATION = 300
MAX_READ_INLINE_BYTES = 1_048_576

server = Server('ergo-media-api-server')


def load_env() -> dict:
    """Загружает .env + env/*.env (в т.ч. env/mcp.env)."""
    env_vars = load_project_env(PROJECT_DIR)
    if not env_vars and not (PROJECT_DIR / '.env').is_file():
        raise FileNotFoundError(f'Файл .env не найден: {PROJECT_DIR / ".env"}')
    return env_vars


def _int_env(env_vars: dict, *keys: str, default: int) -> int:
    for key in keys:
        raw = env_vars.get(key)
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
    return default


def build_public_base_url(env_vars: dict) -> str:
    explicit = env_vars.get('MEDIA_API_URL', '').strip()
    if explicit:
        return explicit.rstrip('/')

    host = env_vars.get('MEDIA_API_HOST', 'localhost')
    port = env_vars.get('MEDIA_API_PORT') or env_vars.get('MEDIA_API_BIND_PORT', '8003')
    protocol = env_vars.get('MEDIA_API_PROTOCOL', 'http')
    port_int = int(port)
    if (protocol == 'http' and port_int == 80) or (protocol == 'https' and port_int == 443):
        return f'{protocol}://{host}'
    return f'{protocol}://{host}:{port}'


def build_internal_base_url(env_vars: dict) -> str:
    explicit = env_vars.get('MEDIA_API_INTERNAL_URL', '').strip()
    if explicit:
        return explicit.rstrip('/')

    bind_host = env_vars.get('MEDIA_API_BIND_HOST', '127.0.0.1').strip() or '127.0.0.1'
    bind_port = env_vars.get('MEDIA_API_BIND_PORT', '8003').strip() or '8003'
    return f'http://{bind_host}:{bind_port}'


def decode_user_id_from_jwt(bearer_token: str) -> Optional[int]:
    try:
        token = bearer_token.replace('Bearer ', '', 1).strip()
        payload_part = token.split('.')[1]
        padded = payload_part + '=' * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        user_id = payload.get('user_id')
        if user_id is not None:
            return int(user_id)
    except Exception:
        return None
    return None


async def authenticate_and_get_token(base_url: str, username: str, password: str) -> str:
    auth_url = f'{base_url}/api/cms/adp/authorization/'
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            auth_url,
            json={
                'username': username,
                'password': password,
                'password_confirm': password,
            },
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
        )
        if response.status_code != 200:
            raise ValueError(f'Ошибка авторизации: {response.status_code} - {response.text}')
        access_token = response.json().get('access')
        if not access_token:
            raise ValueError('Токен доступа не найден в ответе API')
        return f'Bearer {access_token}'


def internal_headers() -> dict:
    return {
        'X-Media-Internal-Key': INTERNAL_KEY or '',
        'Accept': 'application/json',
    }


def make_signed_url(file_path: str, expires_in: Optional[int] = None) -> str:
    ttl = expires_in if expires_in is not None else MEDIA_URL_EXPIRATION
    signature, expires = sign_url(file_path, SECRET_KEY, ttl)
    return f'{PUBLIC_BASE_URL}/serve/{file_path}?signature={signature}&expires={expires}'


def make_upload_token(
    user_id: int,
    target_dir: str = '',
    max_size: Optional[int] = None,
    allowed_types: Optional[list] = None,
    expires_in: Optional[int] = None,
) -> str:
    payload = {'user_id': user_id, 'target_dir': target_dir}
    if max_size:
        payload['max_size'] = max_size
    if allowed_types:
        payload['allowed_types'] = allowed_types
    ttl = expires_in if expires_in is not None else MEDIA_UPLOAD_TOKEN_EXPIRATION
    return create_upload_token(payload, SECRET_KEY, ttl)


async def initialize_config():
    global SECRET_KEY, PUBLIC_BASE_URL, INTERNAL_BASE_URL, INTERNAL_KEY
    global AUTH_TOKEN, API_BASE_URL, DEFAULT_USER_ID
    global MEDIA_URL_EXPIRATION, MEDIA_UPLOAD_MAX_SIZE, MEDIA_UPLOAD_TOKEN_EXPIRATION

    env_vars = load_env()

    SECRET_KEY = env_vars.get('API_SECRET_KEY', '').strip()
    if not SECRET_KEY:
        raise ValueError('API_SECRET_KEY должен быть указан в .env')

    PUBLIC_BASE_URL = build_public_base_url(env_vars)
    INTERNAL_BASE_URL = build_internal_base_url(env_vars)
    INTERNAL_KEY = env_vars.get('MEDIA_API_INTERNAL_KEY', '').strip()

    MEDIA_URL_EXPIRATION = _int_env(env_vars, 'MEDIA_URL_EXPIRATION', default=3600)
    MEDIA_UPLOAD_MAX_SIZE = _int_env(env_vars, 'MEDIA_UPLOAD_MAX_SIZE', default=104857600)
    MEDIA_UPLOAD_TOKEN_EXPIRATION = _int_env(
        env_vars, 'MEDIA_UPLOAD_TOKEN_EXPIRATION', default=300,
    )

    admin_login = env_vars.get('ADMIN_LOGIN')
    admin_password = env_vars.get('ADMIN_PASSWORD')
    api_host = env_vars.get('API_HOST', 'localhost')
    api_port = env_vars.get('API_PORT', '8000')
    API_BASE_URL = f'http://{api_host}:{api_port}'

    if admin_login and admin_password:
        try:
            AUTH_TOKEN = await authenticate_and_get_token(API_BASE_URL, admin_login, admin_password)
            DEFAULT_USER_ID = decode_user_id_from_jwt(AUTH_TOKEN) or 1
        except Exception as e:
            # Вход нужен только для user id в токене загрузки. Падение до stdio даёт в Cursor 0 tools.
            AUTH_TOKEN = None
            DEFAULT_USER_ID = 1
            print(f'[WARNING] Авторизация API недоступна, user id по умолчанию: {e}', file=sys.stderr)
    else:
        AUTH_TOKEN = None
        DEFAULT_USER_ID = 1

    print('[OK] MCP media_api сервер инициализирован', file=sys.stderr)
    print(f'  - Публичный URL: {PUBLIC_BASE_URL}', file=sys.stderr)
    print(f'  - Internal URL: {INTERNAL_BASE_URL}', file=sys.stderr)
    print(
        f'  - Internal API: {"включён" if INTERNAL_KEY else "отключён (нет MEDIA_API_INTERNAL_KEY)"}',
        file=sys.stderr,
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name='media_api_status',
            description='Проверить состояние media_api (health).',
            inputSchema={'type': 'object', 'properties': {}},
        ),
        Tool(
            name='media_api_signed_url',
            description='Сгенерировать подписанный URL для скачивания/просмотра файла в media_api.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'file_path': {
                        'type': 'string',
                        'description': 'Относительный путь к файлу (например: avatars/uuid.jpg)',
                    },
                    'expires_in': {
                        'type': 'integer',
                        'description': 'Время жизни URL в секундах (по умолчанию из MEDIA_URL_EXPIRATION)',
                    },
                },
                'required': ['file_path'],
            },
        ),
        Tool(
            name='media_api_upload',
            description='Загрузить локальный файл в media_api через upload-токен.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'local_file_path': {
                        'type': 'string',
                        'description': 'Абсолютный или относительный путь к локальному файлу',
                    },
                    'target_dir': {
                        'type': 'string',
                        'description': 'Целевая директория в хранилище (например: mcp/uploads)',
                        'default': 'mcp/uploads',
                    },
                    'user_id': {
                        'type': 'integer',
                        'description': 'ID пользователя для upload-токена (по умолчанию — из JWT админа)',
                    },
                    'allowed_types': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Разрешённые расширения без точки (pdf, png, …)',
                    },
                },
                'required': ['local_file_path'],
            },
        ),
        Tool(
            name='media_api_meta',
            description='Получить метаданные файла (exists, size) через internal API.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'file_path': {'type': 'string', 'description': 'Относительный путь к файлу'},
                },
                'required': ['file_path'],
            },
        ),
        Tool(
            name='media_api_read',
            description=(
                'Прочитать файл через internal API. '
                'Текстовые файлы возвращаются как текст, бинарные — base64 (до 1 МБ).'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'file_path': {'type': 'string', 'description': 'Относительный путь к файлу'},
                    'max_bytes': {
                        'type': 'integer',
                        'description': 'Максимальный размер ответа в байтах (по умолчанию 1048576)',
                    },
                },
                'required': ['file_path'],
            },
        ),
        Tool(
            name='media_api_write',
            description='Записать файл через internal API (текст или base64).',
            inputSchema={
                'type': 'object',
                'properties': {
                    'file_path': {'type': 'string', 'description': 'Относительный путь для сохранения'},
                    'content': {'type': 'string', 'description': 'Текстовое содержимое файла'},
                    'content_base64': {
                        'type': 'string',
                        'description': 'Содержимое в base64 (альтернатива content)',
                    },
                },
                'required': ['file_path'],
            },
        ),
        Tool(
            name='media_api_delete',
            description='Удалить файл через internal API.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'file_path': {'type': 'string', 'description': 'Относительный путь к файлу'},
                },
                'required': ['file_path'],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    handlers = {
        'media_api_status': handle_status,
        'media_api_signed_url': handle_signed_url,
        'media_api_upload': handle_upload,
        'media_api_meta': handle_meta,
        'media_api_read': handle_read,
        'media_api_write': handle_write,
        'media_api_delete': handle_delete,
    }
    handler = handlers.get(name)
    if not handler:
        raise ValueError(f'Неизвестный инструмент: {name}')
    return await handler(arguments or {})


def _json_result(payload: dict) -> list[TextContent]:
    return [TextContent(type='text', text=json.dumps(payload, ensure_ascii=False, indent=2))]


def _require_internal_key() -> Optional[list[TextContent]]:
    if not INTERNAL_KEY:
        return _json_result({
            'error': 'Internal API недоступен: не задан MEDIA_API_INTERNAL_KEY в .env',
        })
    return None


def _normalize_file_path(file_path: str) -> str:
    return file_path.replace('\\', '/').lstrip('/')


async def handle_status(_arguments: dict) -> list[TextContent]:
    url = f'{INTERNAL_BASE_URL}/health/'
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            try:
                data = response.json()
            except Exception:
                data = response.text
            return _json_result({
                'status_code': response.status_code,
                'url': url,
                'data': data,
            })
    except Exception as e:
        return _json_result({'error': 'Не удалось подключиться к media_api', 'details': str(e), 'url': url})


async def handle_signed_url(arguments: dict) -> list[TextContent]:
    file_path = _normalize_file_path(arguments.get('file_path', ''))
    if not file_path:
        return _json_result({'error': 'file_path обязателен'})

    expires_in = arguments.get('expires_in')
    signed_url = make_signed_url(file_path, expires_in)
    return _json_result({
        'file_path': file_path,
        'signed_url': signed_url,
        'expires_in': expires_in or MEDIA_URL_EXPIRATION,
    })


async def handle_upload(arguments: dict) -> list[TextContent]:
    local_path_raw = arguments.get('local_file_path', '')
    if not local_path_raw:
        return _json_result({'error': 'local_file_path обязателен'})

    local_path = Path(local_path_raw)
    if not local_path.is_absolute():
        local_path = (PROJECT_DIR / local_path).resolve()
    if not local_path.is_file():
        return _json_result({'error': 'Локальный файл не найден', 'path': str(local_path)})

    target_dir = _normalize_file_path(arguments.get('target_dir', 'mcp/uploads'))
    user_id = int(arguments.get('user_id', DEFAULT_USER_ID))
    allowed_types = arguments.get('allowed_types')

    file_size = local_path.stat().st_size
    if file_size > MEDIA_UPLOAD_MAX_SIZE:
        return _json_result({
            'error': f'Файл превышает MEDIA_UPLOAD_MAX_SIZE ({MEDIA_UPLOAD_MAX_SIZE} байт)',
            'size': file_size,
        })

    token = make_upload_token(
        user_id=user_id,
        target_dir=target_dir,
        max_size=MEDIA_UPLOAD_MAX_SIZE,
        allowed_types=allowed_types,
    )
    upload_url = f'{PUBLIC_BASE_URL}/upload/'

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(local_path, 'rb') as fh:
                response = await client.post(
                    upload_url,
                    data={'token': token},
                    files={'file': (local_path.name, fh, mimetypes.guess_type(local_path.name)[0] or 'application/octet-stream')},
                )
            try:
                data = response.json()
            except Exception:
                data = response.text
            return _json_result({
                'status_code': response.status_code,
                'upload_url': upload_url,
                'local_file_path': str(local_path),
                'data': data,
            })
    except Exception as e:
        return _json_result({'error': 'Ошибка загрузки', 'details': str(e), 'upload_url': upload_url})


async def handle_meta(arguments: dict) -> list[TextContent]:
    blocked = _require_internal_key()
    if blocked:
        return blocked

    file_path = _normalize_file_path(arguments.get('file_path', ''))
    if not file_path:
        return _json_result({'error': 'file_path обязателен'})

    url = f'{INTERNAL_BASE_URL}/internal/meta/{file_path}'
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=internal_headers())
            try:
                data = response.json()
            except Exception:
                data = response.text
            return _json_result({'status_code': response.status_code, 'url': url, 'data': data})
    except Exception as e:
        return _json_result({'error': 'Ошибка meta', 'details': str(e), 'url': url})


async def handle_read(arguments: dict) -> list[TextContent]:
    blocked = _require_internal_key()
    if blocked:
        return blocked

    file_path = _normalize_file_path(arguments.get('file_path', ''))
    if not file_path:
        return _json_result({'error': 'file_path обязателен'})

    max_bytes = int(arguments.get('max_bytes', MAX_READ_INLINE_BYTES))
    url = f'{INTERNAL_BASE_URL}/internal/read/{file_path}'

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, headers=internal_headers())
            if response.status_code != 200:
                try:
                    data = response.json()
                except Exception:
                    data = response.text
                return _json_result({'status_code': response.status_code, 'url': url, 'data': data})

            content = response.content
            content_type = response.headers.get('content-type', mimetypes.guess_type(file_path)[0] or 'application/octet-stream')
            size = len(content)

            if size > max_bytes:
                return _json_result({
                    'error': f'Файл слишком большой для inline-ответа ({size} > {max_bytes})',
                    'file_path': file_path,
                    'size': size,
                    'content_type': content_type,
                    'signed_url': make_signed_url(file_path),
                })

            is_text = content_type.startswith('text/') or content_type in (
                'application/json', 'application/xml', 'application/javascript',
            )
            if is_text:
                try:
                    text = content.decode('utf-8')
                    encoding = 'text'
                    payload_content: Any = text
                except UnicodeDecodeError:
                    encoding = 'base64'
                    payload_content = base64.b64encode(content).decode('ascii')
            else:
                encoding = 'base64'
                payload_content = base64.b64encode(content).decode('ascii')

            return _json_result({
                'file_path': file_path,
                'size': size,
                'content_type': content_type,
                'encoding': encoding,
                'content': payload_content,
            })
    except Exception as e:
        return _json_result({'error': 'Ошибка чтения', 'details': str(e), 'url': url})


async def handle_write(arguments: dict) -> list[TextContent]:
    blocked = _require_internal_key()
    if blocked:
        return blocked

    file_path = _normalize_file_path(arguments.get('file_path', ''))
    if not file_path:
        return _json_result({'error': 'file_path обязателен'})

    content = arguments.get('content')
    content_base64 = arguments.get('content_base64')
    if content_base64:
        body = base64.b64decode(content_base64)
    elif content is not None:
        body = content.encode('utf-8')
    else:
        return _json_result({'error': 'Укажите content или content_base64'})

    url = f'{INTERNAL_BASE_URL}/internal/write/{file_path}'
    headers = internal_headers()
    headers['Content-Type'] = 'application/octet-stream'

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.put(url, headers=headers, content=body)
            try:
                data = response.json()
            except Exception:
                data = response.text
            return _json_result({'status_code': response.status_code, 'url': url, 'data': data})
    except Exception as e:
        return _json_result({'error': 'Ошибка записи', 'details': str(e), 'url': url})


async def handle_delete(arguments: dict) -> list[TextContent]:
    blocked = _require_internal_key()
    if blocked:
        return blocked

    file_path = _normalize_file_path(arguments.get('file_path', ''))
    if not file_path:
        return _json_result({'error': 'file_path обязателен'})

    url = f'{INTERNAL_BASE_URL}/internal/delete/{file_path}'
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(url, headers=internal_headers())
            try:
                data = response.json()
            except Exception:
                data = response.text
            return _json_result({'status_code': response.status_code, 'url': url, 'data': data})
    except Exception as e:
        return _json_result({'error': 'Ошибка удаления', 'details': str(e), 'url': url})


async def main():
    await initialize_config()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == '__main__':
    asyncio.run(main())
