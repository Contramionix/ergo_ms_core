<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Изоляция ядра от модулей

Ядро (`core/api`, `core/client`, `core/media_api`, `core/deployment`) не знает домен модулей. Связь — ModuleBridge и hook discovery. Проверка: `ergoms core-rules-check`. Каталог hook’ов — [`modules.mdc`](../../.cursor/rules/modules.mdc), контракты — [`module-contracts.mdc`](../../.cursor/rules/module-contracts.mdc).

- Нет `from modules.<имя>...` и static import из `modules/` в бизнес-коде ядра.
- Нет имён установленных модулей в runtime, комментариях и docstring ядра и `.cursor/rules/` — только `<name>`.
- Нет зашитых JWT claim, моделей и маршрутов модуля. Ядро кладёт произвольный dict claims.
- Данные модуля в сценарии ядра идут через platform-контракт и `bridge.call` или hook.
- Связь только модуль↔модуль не клади в каталог ядра. Имена контрактов ядра — `session.*`, `audit.*`, `core.*`.

```python
# GOOD
restore_claims = bridge.call(SESSION_RESTORE_CLAIMS, user=user) or {}
# BAD
from modules.<name>.api.models import SomeEntity
```

Новая связь ядро↔модуль начинается с константы в каталоге. Доменный loader модуля живёт в `modules/<name>/`.
