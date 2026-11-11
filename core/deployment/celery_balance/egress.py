"""Проба выхода в сеть с узла. Пустой адрес проверку не включает."""

from __future__ import annotations

import urllib.error
import urllib.request


def probe_egress(url: str, timeout: float = 5.0) -> bool:
    """True, если адрес открылся или проверка выключена. Ошибка пробы не пробрасывается."""
    text = (url or '').strip()
    if not text:
        return True
    request = urllib.request.Request(text, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = int(getattr(response, 'status', 0) or 0)
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False
    return 200 <= code < 400
