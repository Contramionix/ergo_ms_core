"""
MCP сервер для работы с Django API проекта ErgoMS
Предоставляет инструменты для выполнения HTTP запросов к API с автоматической авторизацией
"""

import asyncio
import json
import sys
import os
from pathlib import Path
from typing import Any, Optional
import httpx
import yaml

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


# Определяем корневую директорию проекта
PROJECT_DIR = Path(__file__).parent.parent.absolute()
DATABASES_YAML = PROJECT_DIR / 'databases.yaml'
_DEPLOYMENT_DIR = PROJECT_DIR / 'core' / 'deployment'
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from env_file_loader import load_project_env  # noqa: E402

# Глобальные переменные для конфигурации
API_BASE_URL = None
AUTH_TOKEN = None
DB_CONFIG = None


# Создаем экземпляр сервера
server = Server("ergo-api-server")


def load_env() -> dict:
    """Загружает .env + env/*.env (в т.ч. env/mcp.env)."""
    env_vars = load_project_env(PROJECT_DIR)
    if not env_vars and not (PROJECT_DIR / '.env').is_file():
        raise FileNotFoundError(f'Файл .env не найден: {PROJECT_DIR / ".env"}')
    return env_vars


def load_databases_yaml() -> dict:
    """Загружает конфигурацию баз данных из databases.yaml"""
    if not DATABASES_YAML.exists():
        raise FileNotFoundError(f"Файл databases.yaml не найден: {DATABASES_YAML}")
    
    with open(DATABASES_YAML, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    if not config or 'databases' not in config:
        raise ValueError("Неверный формат файла databases.yaml")
    
    return config['databases']


async def authenticate_and_get_token(base_url: str, username: str, password: str) -> str:
    """
    Авторизуется в API и получает токен доступа
    
    Args:
        base_url: Базовый URL API
        username: Логин администратора
        password: Пароль администратора
    
    Returns:
        Токен доступа в формате "Bearer <token>"
    """
    auth_url = f"{base_url}/api/cms/adp/authorization/"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                auth_url,
                json={
                    "username": username,
                    "password": password,
                    "password_confirm": password
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                access_token = data.get('access')
                if not access_token:
                    raise ValueError("Токен доступа не найден в ответе API")
                return f"Bearer {access_token}"
            else:
                error_msg = f"Ошибка авторизации: {response.status_code} - {response.text}"
                raise ValueError(error_msg)
                
        except httpx.RequestError as e:
            raise ValueError(f"Ошибка при подключении к API: {str(e)}")


async def initialize_config():
    """Готовит URL и конфиг БД. Сбой входа в API не останавливает stdio: иначе Cursor видит 0 tools."""
    global API_BASE_URL, AUTH_TOKEN, DB_CONFIG

    env_vars = load_env()
    admin_login = env_vars.get('ADMIN_LOGIN')
    admin_password = env_vars.get('ADMIN_PASSWORD')
    api_host = env_vars.get('API_HOST', 'localhost')
    api_port = env_vars.get('API_PORT', '8000')
    API_BASE_URL = f"http://{api_host}:{api_port}"
    DB_CONFIG = load_databases_yaml()

    if not admin_login or not admin_password:
        AUTH_TOKEN = None
        print(
            'MCP api: нет ADMIN_LOGIN/ADMIN_PASSWORD в .env или env/mcp.env',
            file=sys.stderr,
        )
        return

    try:
        AUTH_TOKEN = await authenticate_and_get_token(API_BASE_URL, admin_login, admin_password)
        print(f"MCP api: авторизация успешна, API {API_BASE_URL}", file=sys.stderr)
    except Exception as e:
        AUTH_TOKEN = None
        print(f"MCP api: API недоступен, инструменты без токена: {e}", file=sys.stderr)


async def ensure_auth() -> Optional[list[TextContent]]:
    """Повторяет вход, если при старте API ещё не отвечал."""
    if AUTH_TOKEN:
        return None
    await initialize_config()
    if AUTH_TOKEN:
        return None
    return [TextContent(
        type="text",
        text=json.dumps({
            "error": "Нет токена API. Проверьте, что Django запущен, и ADMIN_LOGIN/ADMIN_PASSWORD в .env или env/mcp.env",
            "api": API_BASE_URL,
        }, ensure_ascii=False, indent=2),
    )]


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Список доступных инструментов для работы с API"""
    return [
        Tool(
            name="api_request",
            description="Выполнить HTTP запрос к Django API ErgoMS. Поддерживает все HTTP методы (GET, POST, PUT, PATCH, DELETE). Автоматически добавляет токен авторизации.",
            inputSchema={
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "HTTP метод",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    },
                    "endpoint": {
                        "type": "string",
                        "description": "API endpoint (например: /api/cms/get_groups/ или /api/bi_analysis/)",
                    },
                    "data": {
                        "type": "object",
                        "description": "JSON данные для отправки в теле запроса (для POST, PUT, PATCH)",
                    },
                    "params": {
                        "type": "object",
                        "description": "Query параметры URL (например: {\"page\": 1, \"limit\": 10})",
                    },
                },
                "required": ["method", "endpoint"],
            },
        ),
        Tool(
            name="api_get_endpoints",
            description="Получить список всех доступных API endpoints Django проекта через introspection",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="api_get_db_config",
            description="Получить конфигурацию баз данных из databases.yaml",
            inputSchema={
                "type": "object",
                "properties": {
                    "database_name": {
                        "type": "string",
                        "description": "Имя базы данных (например: default, celery, analytics). Если не указано, вернет все конфигурации.",
                    }
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Обработка вызовов инструментов"""
    
    if name == "api_request":
        auth_error = await ensure_auth()
        if auth_error:
            return auth_error
        return await handle_api_request(arguments)
    elif name == "api_get_endpoints":
        auth_error = await ensure_auth()
        if auth_error:
            return auth_error
        return await handle_get_endpoints()
    elif name == "api_get_db_config":
        return await handle_get_db_config(arguments)
    else:
        raise ValueError(f"Неизвестный инструмент: {name}")


async def handle_api_request(arguments: dict) -> list[TextContent]:
    """Выполнение HTTP запроса к API"""
    method = arguments.get("method", "GET").upper()
    endpoint = arguments.get("endpoint", "")
    data = arguments.get("data")
    params = arguments.get("params")
    
    # Формируем полный URL
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    url = f"{API_BASE_URL}{endpoint}"
    
    # Подготавливаем заголовки
    headers = {
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Выполняем запрос
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                response = await client.post(url, headers=headers, json=data, params=params)
            elif method == "PUT":
                response = await client.put(url, headers=headers, json=data, params=params)
            elif method == "PATCH":
                response = await client.patch(url, headers=headers, json=data, params=params)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers, params=params)
            else:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": f"Неподдерживаемый HTTP метод: {method}"}, ensure_ascii=False, indent=2)
                )]
            
            # Формируем ответ
            result = {
                "status_code": response.status_code,
                "status_text": response.reason_phrase,
                "url": str(response.url),
                "method": method,
            }
            
            # Пытаемся распарсить JSON ответ
            try:
                result["data"] = response.json()
            except Exception:
                result["data"] = response.text
            
            # Добавляем заголовки ответа (только важные)
            result["headers"] = {
                "content-type": response.headers.get("content-type"),
                "content-length": response.headers.get("content-length"),
            }
            
            return [TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2)
            )]
            
    except httpx.TimeoutException:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Таймаут запроса",
                "url": url,
                "method": method
            }, ensure_ascii=False, indent=2)
        )]
    except httpx.ConnectError as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Ошибка подключения к серверу",
                "details": str(e),
                "url": url,
                "method": method
            }, ensure_ascii=False, indent=2)
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Неожиданная ошибка",
                "details": str(e),
                "url": url,
                "method": method
            }, ensure_ascii=False, indent=2)
        )]


async def handle_get_endpoints() -> list[TextContent]:
    """Получение списка доступных endpoints через Django URL patterns"""
    url = f"{API_BASE_URL}/swagger.json"
    headers = {
        "Authorization": AUTH_TOKEN,
        "Accept": "application/json",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                swagger_data = response.json()
                endpoints = list(swagger_data.get("paths", {}).keys())
                
                result = {
                    "total_endpoints": len(endpoints),
                    "endpoints": sorted(endpoints),
                    "swagger_url": url
                }
                
                return [TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2)
                )]
            else:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "Не удалось получить список endpoints",
                        "status_code": response.status_code,
                        "details": "Попробуйте использовать api_request для доступа к конкретным endpoints"
                    }, ensure_ascii=False, indent=2)
                )]
                
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Ошибка при получении списка endpoints",
                "details": str(e)
            }, ensure_ascii=False, indent=2)
        )]


async def handle_get_db_config(arguments: dict) -> list[TextContent]:
    """Получение конфигурации баз данных"""
    database_name = arguments.get("database_name")
    
    try:
        if database_name:
            # Возвращаем конфигурацию конкретной БД
            if database_name in DB_CONFIG:
                result = {
                    "database": database_name,
                    "config": DB_CONFIG[database_name]
                }
            else:
                result = {
                    "error": f"База данных '{database_name}' не найдена в конфигурации",
                    "available_databases": list(DB_CONFIG.keys())
                }
        else:
            # Возвращаем все конфигурации
            result = {
                "databases": DB_CONFIG,
                "total_databases": len(DB_CONFIG)
            }
        
        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2)
        )]
        
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "Ошибка при получении конфигурации БД",
                "details": str(e)
            }, ensure_ascii=False, indent=2)
        )]


async def main():
    """Запуск MCP сервера через stdio"""
    # Инициализируем конфигурацию перед запуском
    await initialize_config()
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())

