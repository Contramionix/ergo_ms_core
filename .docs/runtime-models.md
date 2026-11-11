# Общий индекс моделей

Этап B расширяет существующий lifecycle. Индекс объединяет Hugging Face и
подключаемые провайдеры; скачивание выполняют прежние установщики. Миграций БД,
изменения весов существующих отчётов и обновления Torch/CUDA в этом этапе нет.

Последняя [локальная приёмка A/B](runtime-acceptance-20261022.md) проверяет
обязательные модели с настоящими потребителями на Windows/Linux. HF-модель
дополнительно выполнила инференс на CPU. Выявленное удаление транзитивных extras
исправлено в существующем Python-установщике. Модульный загрузчик на Windows CPU
использует отдельную явную маску SDPA: вызов проверки CUDA-stream в установленном
стеке приводил к аварийному завершению процесса. Проверены пакетный и одиночный
расчёты для текстов разной длины, включая пустой; версии Torch/CUDA не менялись.
Инференс Ollama и GPU этим прогоном не подтверждены.

## Команды и политика установки

```text
ergoms runtime-models --json
ergoms runtime-model-check --json
ergoms runtime-model-install
ergoms runtime-model-install --include-optional
ergoms runtime-model-install --provider huggingface --model org/model
ergoms runtime-model-resolve --provider huggingface --model org/model --json
ergoms runtime-model-resolve --provider ollama --model embeddinggemma --json
```

Чтение и разрешение ссылки не запускают сервер и не скачивают файлы.
На Windows существующая обёртка ergoms печатает строки диспетчеризации перед
JSON. Для программного доступа следует использовать Python resolver либо
непосредственно JSON CLI; его stdout содержит один JSON, диагностика — в stderr.
Отсутствующая либо неполная модель даёт ненулевой код; идентификатор Hub
не возвращается вместо локального пути. `resolve --allow-download` разрешает
установку при первом использовании явно. Обычная установка выбирает только
`required: true`; необязательные модели устанавливаются явной командой или
с `--include-optional`. Прежние HF/Ollama CLI-алиасы сохраняются.

Host `setup-full` использует прежний HF-шаг и модульные setup-задачи;
после них, до миграций, проверяет обязательные модели. Docker init/bootstrap
устанавливают инструменты и обязательные модели через существующий API oneoff.
Ошибка останавливает pipeline. Отсутствие SDK/бинарника не считается успехом.

Обновление требует согласованных версий обёртки, `core/api` и адаптера Ollama:
прежний модуль ещё не регистрирует hook индекса и устанавливает другой состав
моделей. Не выполнять setup между частичными обновлениями этих репозиториев.
Gitlinks этим этапом не обновляются.

Индекс `virtual_env/cache/model_index.json` восстанавливается из деклараций
включённых модулей и локальных файлов. Он не служит доказательством готовности:
runtime повторно проверяет хранилище. Обязательность объединяется по OR.
Отключённый провайдер отмечается `provider_missing`; обязательная модель
препятствует успешной проверке, необязательная — нет.

## Каталоги и целостность

- Бинарники: `virtual_env/packages/`, существующий реестр инструментов A.
- HF-веса: `virtual_env/trained_models/huggingface/<org>/<name>/`.
- Ollama-веса: прежний `virtual_env/packages/ollama_models/` (отдельно от бинарника).
- Кэши и staging загрузки: `virtual_env/cache/`; временная публикация готового
  снимка — рядом с его каталогом весов на томе назначения, с автоматической очисткой.

HF требует читаемую `config.json` и настоящий файл весов либо все shard-файлы
из индекса. LFS-указатели, выход путей за каталог и неполный набор отклоняются.
Базовый каталог HF и пути снимков проверяются после раскрытия ссылок и junction:
они должны оставаться в `virtual_env` текущей установки. Это проверяется при
чтении, установке и переносе прежнего снимка, до обращения к загрузчику.
Скачивание проходит во временный каталог; публикация сохраняет прежние веса
при ошибке. Перенос прежнего `trained_models/<name>` сохраняет содержимое.
Если кэш и веса находятся на разных томах, снимок копируется на том назначения
до замены прежних весов. Ошибка копирования сохраняет предыдущий снимок;
ошибка финального переименования восстанавливает его из резервного каталога.
Уже готовый снимок повторно не очищается и не скачивается. Установки одной
модели сериализуются файловой блокировкой Windows/Linux; ошибка снимает блокировку.

Ollama проверяет локальный manifest, конфигурацию, наличие и размеры всех blobs;
точный tag обязателен. Поддерживаются обычные manifests и runner-specific manifest
lists для ggml/llamacpp. Формат следует [исходникам Ollama](https://github.com/ollama/ollama/blob/main/manifest/manifest.go).
Полное вычисление SHA256 доступно в `inspect_model(..., verify_hashes=True)`
для проверки установки; обычный runtime не перечитывает гигабайты на каждый запрос.
HF-проверка структурная и не заменяет загрузку модели соответствующей библиотекой;
revision/digest Hub не закрепляются этим изменением.

## Runtime Python

```python
from src.core.utils.model_index import resolve_model

reference = resolve_model('huggingface', 'org/model')
local_directory = reference['local_path']
```

Результат содержит `provider`, `name`, `runtime_name`, `local_path`, `ready`,
`required`, `reason`, `source_module`, `source_file`. Для HF путь указывает на
каталог снимка, для Ollama — локальный manifest; запрос серверу по-прежнему
использует `runtime_name` через модуль-провайдер и ModuleBridge. Новый resolver
не обходит права на данные и не создаёт HTTP endpoint.

Совместимый `ensure_local_source` использует общий resolver с явным разрешением
загрузки. Старый `resolve_huggingface_source` сохраняет прежний fallback для
потребителей, ещё не перешедших на строгий контракт.

## Hook провайдера

`modules/<name>/model_providers.yaml` читается через существующий ModuleCatalog:

```yaml
schema_version: 1
module: my_provider
providers:
  my_runtime:
    script: deployment/model_provider.py
    storage: virtual_env/trained_models/my_runtime
```

Скрипт находится внутри модуля, storage — внутри `virtual_env`. Дублирование
провайдера, подмена встроенного HF, повторные YAML-ключи и неизвестные поля — ошибки.
Ядро не импортирует модуль: вызывает его скрипт текущим Python с JSON по stdout;
диагностика идёт в stderr. Аргументы: `list|resolve|install --root PATH`,
для resolve/install ещё `--model NAME`, для install возможен `--force`.
List возвращает `{"models": [...]}`, resolve/install — одну запись описанного
выше формата. Код 0 установки проверяется повторным resolve; сам по себе он
не подтверждает готовность. Обнаружение провайдера не даёт сетевых прав
потребителю: операции инференса остаются за прежними bridge-контрактами.

Ollama регистрирует собственный адаптер и прежний загрузчик деклараций.
Потребитель по-прежнему объявляет `requires`/`extends` и модель в
`runtime_requirements.yaml` либо совместимом `ollama_models.yaml`.
Для дополнительного провайдера в этой версии нужен его собственный загрузчик
объявлений; схема потребительского манифеста версии 1 принимает HF и Ollama.

## Приёмка

Результаты установки и ограничения общей приёмки A/B фиксируются в
[runtime-requirements.md](runtime-requirements.md). Проверка индекса не является
проверкой качества инференса, GPU, лицензии либо доступности внешнего API.

## Состав изменений B

Пути ниже относятся к корню соответствующего репозитория; gitlinks не обновляются.

| Репозиторий / файлы | Назначение |
|---|---|
| ergo_ms: `core/deployment/model_index/__init__.py`, `registry.py`, `cli.py`, `locking.py` | Общий индекс, JSON-протокол провайдеров, строгий resolver, команды и блокировка установки |
| ergo_ms: `core/deployment/project_layout.py` | Проверка HF идентификатора, конфигурации и полного состава shard-файлов |
| ergo_ms: `core/deployment/huggingface/snapshot.py`, `cli.py` | Staging, безопасная публикация/перенос прежних весов, неизменность готовых снимков, контролируемые ошибки |
| ergo_ms: `core/deployment/lifecycle/recipes.py`, `steps/model_index_steps.py` | Обязательные модели в существующем host/Docker lifecycle |
| ergo_ms: `core/deployment/docker/Dockerfile.python` | zstd для существующего установщика архивов Ollama `.tar.zst` |
| ergo_ms: `core/deployment/commands.conf`, `help.manifest.yaml` | Четыре новые команды индекса с сохранением прежних алиасов |
| ergo_ms: `core/deployment/locales/{ru,en,fr}/cli_messages.yaml` | Диагностика нового CLI |
| ergo_ms: `core/deployment/tests/test_model_index.py`, `test_model_storage.py` | Регрессии индекса, провайдера, атомарности, блокировки, обязательности и повторов |
| ergo_ms: `core/deployment/tests/test_host_ops_paths.py` | Отклонение неверного HF ID вместо молчаливого исправления пути |
| ergo_ms: `.cursor/rules/modules.mdc`, `.docs/modules.md` | Новый нейтральный hook в каталоге расширений |
| ergo_ms: `.docs/runtime-models.md`, `runtime-requirements.md`, `local-residual-status.md` | Контракт B, результаты и ограничения A/B, сохранённый локальный остаток |
| core/api: `src/core/utils/model_index.py`, `huggingface_snapshot.py` | Runtime resolver и совместимый переход ensure_local_source на общий индекс |
| ollama_framework: `model_providers.yaml`, `deployment/model_provider.py`, `model_store.py` | Hook, JSON-адаптер существующих ops, проверка локальных manifests/blobs |
| ollama_framework: `deployment/pull_setup_models.py` | Только обязательные модели по умолчанию, проверка весов до/после pull, блокировка и безопасный повтор |
| ollama_framework: `deployment/model_names.py`, `ollama_ops.py` | Точный tag, настроенный адрес SDK и существующая политика прокси |
| ollama_framework: `tests/test_model_index.py` | Готовность, повреждения blobs, manifest lists, optional, SDK и ложный успех установки |
| ollama_framework: `README.md`, `AGENTS.md`, `.cursor/rules/ollama-framework.mdc`, `ergoms.help.yaml` | Документация провайдера и политики установки |
