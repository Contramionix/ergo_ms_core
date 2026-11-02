"""Служебные вызовы media_api другой зоны. Ключ в журнал не пишется."""

from __future__ import annotations

from io import BytesIO
from typing import BinaryIO
from urllib.parse import quote

import requests

_TIMEOUT = (10, 120)
_WRITE_TIMEOUT = (10, 600)
_CHUNK = 1024 * 1024


class MediaZoneError(RuntimeError):
    """Удалённая зона не ответила так, как ждёт хранилище."""


class ZoneStream:
    """Тело ответа. seek только вперёд: Range отдачи пропускает уже прочитанное."""

    def __init__(self, response: requests.Response):
        self._response = response
        self._raw = response.raw
        self._raw.decode_content = True
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(None if size is None or size < 0 else size)
        if chunk:
            self._pos += len(chunk)
        return chunk or b''

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence != 0 or offset < self._pos:
            raise OSError('Поток удалённой зоны перематывается только вперёд')
        while self._pos < offset:
            skipped = self.read(min(_CHUNK, offset - self._pos))
            if not skipped:
                break
        return self._pos

    def close(self) -> None:
        self._response.close()

    def __enter__(self) -> 'ZoneStream':
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _url(base_url: str, suffix: str, path: str) -> str:
    encoded = quote(str(path).replace('\\', '/').strip('/'), safe='/')
    return f'{base_url.rstrip("/")}/internal/{suffix}/{encoded}'


def _headers(key: str) -> dict[str, str]:
    return {'X-Media-Internal-Key': key}


def zone_meta(base_url: str, key: str, path: str) -> tuple[bool, int]:
    """exists, size. 404 — файла нет. Сбой сети — ошибка, не «файла нет»."""
    try:
        response = requests.get(
            _url(base_url, 'meta', path),
            headers=_headers(key),
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MediaZoneError(f'Зона {base_url} не ответила на meta {path}') from exc
    if response.status_code == 404:
        return False, 0
    if response.status_code != 200:
        raise MediaZoneError(f'Зона {base_url} ответила {response.status_code} на meta {path}')
    payload = response.json()
    if not payload.get('exists'):
        return False, 0
    return True, int(payload.get('size') or 0)


def zone_open(base_url: str, key: str, path: str) -> ZoneStream:
    try:
        response = requests.get(
            _url(base_url, 'read', path),
            headers=_headers(key),
            timeout=_TIMEOUT,
            stream=True,
        )
    except requests.RequestException as exc:
        raise MediaZoneError(f'Зона {base_url} не ответила на read {path}') from exc
    if response.status_code == 404:
        response.close()
        raise FileNotFoundError(path)
    if response.status_code != 200:
        response.close()
        raise MediaZoneError(f'Зона {base_url} ответила {response.status_code} на read {path}')
    return ZoneStream(response)


def zone_save(base_url: str, key: str, path: str, content: BinaryIO | bytes) -> str:
    if isinstance(content, (bytes, bytearray)):
        body: BinaryIO = BytesIO(bytes(content))
    else:
        body = content
    try:
        response = requests.put(
            _url(base_url, 'write', path),
            headers={**_headers(key), 'Content-Type': 'application/octet-stream'},
            data=body,
            timeout=_WRITE_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MediaZoneError(f'Зона {base_url} не приняла запись {path}') from exc
    if response.status_code not in (200, 201):
        raise MediaZoneError(f'Зона {base_url} ответила {response.status_code} на запись {path}')
    payload = response.json()
    return str(payload.get('path') or path)


def zone_delete(base_url: str, key: str, path: str) -> bool:
    try:
        response = requests.delete(
            _url(base_url, 'delete', path),
            headers=_headers(key),
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MediaZoneError(f'Зона {base_url} не ответила на delete {path}') from exc
    if response.status_code == 404:
        return False
    if response.status_code != 200:
        raise MediaZoneError(f'Зона {base_url} ответила {response.status_code} на delete {path}')
    return bool(response.json().get('deleted'))


def zone_download(base_url: str, key: str, path: str, dest: str) -> None:
    stream = zone_open(base_url, key, path)
    try:
        with open(dest, 'wb') as handle:
            while True:
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
    finally:
        stream.close()
