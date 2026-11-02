<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Правила по запросу

Cursor подключает эти правила по описанию, Claude Code сам их не грузит. Если задача совпадает с описанием, открой файл через Read до первых действий.

- [`.cursor/rules/audit.mdc`](../../.cursor/rules/audit.mdc) — Аудит действий — запись через мост, автоаудит CRUD, каталог действий, журнал отмен (undo.performed)
- [`.cursor/rules/celery-balance.mdc`](../../.cursor/rules/celery-balance.mdc) — Балансировщик Celery — task_footprint.yaml, бюджет хоста, celery-balance, overlay
- [`.cursor/rules/celery.mdc`](../../.cursor/rules/celery.mdc) — Celery — ergoms start-worker/beat, задачи в modules/, celery_config, логи
- [`.cursor/rules/client-perf.mdc`](../../.cursor/rules/client-perf.mdc) — Производительность клиента Vue — lazy-чанки, async-модалки, параллельные API, prefetch меню
- [`.cursor/rules/components.mdc`](../../.cursor/rules/components.mdc) — Индекс UI-компонентов ядра — SelectBox, SearchInput, DecimalInput, DatePicker, TimePicker, ToggleSwitch, TriStateSwitch, DropZone, FileCard, FormCard, FormField, SettingsCard, SettingsCardRow, FilterMenu, DropDown, TextEditor, TabBar, StepRail, DataTable, UserAvatar, ImageHoverFrame, DocumentViewer, LinkBoard, GraphAtlas, LaneGraph
- [`.cursor/rules/cursor-browser.mdc`](../../.cursor/rules/cursor-browser.mdc) — Встроенный браузер Cursor, cursor-ide-browser, вход через #login из env/mcp.env, без пароля в чате
- [`.cursor/rules/data-table.mdc`](../../.cursor/rules/data-table.mdc) — UI ядра — DataTable, раскрывающаяся подстрока и пагинация через enable-pagination
- [`.cursor/rules/database.mdc`](../../.cursor/rules/database.mdc) — База данных — миграции Django, ORM, SqlAlchemyManager, DBConfig, ergoms
- [`.cursor/rules/dataset-search.mdc`](../../.cursor/rules/dataset-search.mdc) — Поиск чужих датасетов и дампов — площадки, веб-корпуса, диски, курсы, статьи, соревнования, запросы и индексы URL
- [`.cursor/rules/date-picker.mdc`](../../.cursor/rules/date-picker.mdc) — UI ядра — Дата — DatePicker
- [`.cursor/rules/decimal-input.mdc`](../../.cursor/rules/decimal-input.mdc) — UI ядра — Ввод числа — DecimalInput
- [`.cursor/rules/deployment-infra.mdc`](../../.cursor/rules/deployment-infra.mdc) — Redis, nginx, TLS, Docker — portable packages, ergoms install-*, redis_runtime, production за reverse proxy
- [`.cursor/rules/diagnose-before-code.mdc`](../../.cursor/rules/diagnose-before-code.mdc) — Пустой экран, старый dist, nginx и CSP — сначала ergoms client-build и .env, потом правка кода
- [`.cursor/rules/django.mdc`](../../.cursor/rules/django.mdc) — Django и DRF в ERGO MS — PyPI-пакеты, ErgoUser (AbstractUser), admin отключён
- [`.cursor/rules/docker.mdc`](../../.cursor/rules/docker.mdc) — Docker Compose ERGO MS — ergoms docker-*, DOCKER_*, compose profiles; при правках запуска/развёртывания учитывать Docker
- [`.cursor/rules/document-viewer.mdc`](../../.cursor/rules/document-viewer.mdc) — UI ядра — Просмотр PDF и DOCX — DocumentViewer
- [`.cursor/rules/drop-down.mdc`](../../.cursor/rules/drop-down.mdc) — UI ядра — Меню действий — DropDown
- [`.cursor/rules/drop-zone.mdc`](../../.cursor/rules/drop-zone.mdc) — UI ядра — Зона файлов — DropZone
- [`.cursor/rules/ergoms-commands.mdc`](../../.cursor/rules/ergoms-commands.mdc) — Техническая справка ergoms — commands.conf, help.manifest.yaml, help modules/module, префиксы api/npm
- [`.cursor/rules/file-card.mdc`](../../.cursor/rules/file-card.mdc) — UI ядра — Карточка файла — FileCard
- [`.cursor/rules/form-card.mdc`](../../.cursor/rules/form-card.mdc) — UI ядра — Формы — FormCard / FormField
- [`.cursor/rules/graph-atlas.mdc`](../../.cursor/rules/graph-atlas.mdc) — UI ядра — Атлас — GraphAtlas
- [`.cursor/rules/host-lifecycle.mdc`](../../.cursor/rules/host-lifecycle.mdc) — host_lifecycle.yaml — install/uninstall/stop модульных демонов в install-services и тестах без хардкода имён модулей
- [`.cursor/rules/image-hover-frame.mdc`](../../.cursor/rules/image-hover-frame.mdc) — UI ядра — поставить, заменить или удалить обложку, аватар и другую картинку — ImageHoverFrame
- [`.cursor/rules/image-lightbox.mdc`](../../.cursor/rules/image-lightbox.mdc) — UI ядра — ImageLightbox, предпросмотр фото, галерея и зум
- [`.cursor/rules/lane-graph.mdc`](../../.cursor/rules/lane-graph.mdc) — UI ядра — Схема по колонкам — LaneGraph
- [`.cursor/rules/link-board.mdc`](../../.cursor/rules/link-board.mdc) — UI ядра — Схема связей — LinkBoard
- [`.cursor/rules/logging.mdc`](../../.cursor/rules/logging.mdc) — Логирование ERGO MS — logs/, logging_config, logError, Celery, env ERGO_LOG_*, ergoms logs, без FileHandler в коде
- [`.cursor/rules/long-running-jobs.mdc`](../../.cursor/rules/long-running-jobs.mdc) — Долгий расчёт, обучение и обход каталога — Celery --async, чекпоинт и --resume, не shell Cursor
- [`.cursor/rules/member-picker.mdc`](../../.cursor/rules/member-picker.mdc) — UI ядра — Multi-select выбор пользователей — MemberPickerModal
- [`.cursor/rules/module-contracts-catalog.mdc`](../../.cursor/rules/module-contracts-catalog.mdc) — Каталог имён platform-контрактов ModuleBridge — сервер, клиент, hook-файлы, пример session-scope
- [`.cursor/rules/module-cursor-rules.mdc`](../../.cursor/rules/module-cursor-rules.mdc) — Правила Cursor в modules/ — вложенные .cursor/rules и короткий AGENTS.md, без копии плагина
- [`.cursor/rules/notifications.mdc`](../../.cursor/rules/notifications.mdc) — Уведомления — создание и отзыв через мост, каталог событий
- [`.cursor/rules/packages.mdc`](../../.cursor/rules/packages.mdc) — Portable-пакеты virtual_env/packages — реестр ядра, packages.yaml модулей, ergoms package-*
- [`.cursor/rules/parser-pages.mdc`](../../.cursor/rules/parser-pages.mdc) — Парсер хранит полный HTML страницы в media через store_parsed_page, каталог pages
- [`.cursor/rules/person.mdc`](../../.cursor/rules/person.mdc) — Карточка человека Person в ядре — личность без учётки, user_public_id, person_public_id, снимок ФИО, однофамильцы, слияние, CORE_PERSON_*
- [`.cursor/rules/process-roles.mdc`](../../.cursor/rules/process-roles.mdc) — process_roles.yaml — учёт модульных процессов в ergoms resource-usage через ModuleCatalog
- [`.cursor/rules/search.mdc`](../../.cursor/rules/search.mdc) — Централизованный поиск ERGO MS — Meilisearch BM25, core.search, useListSearch, search_indexes.py
- [`.cursor/rules/security-details.mdc`](../../.cursor/rules/security-details.mdc) — Безопасность ERGO MS подробно — .env, auth, public_id, localStorage, cookies, WebSocket, media_api, инъекции, логи; примеры BAD/GOOD
- [`.cursor/rules/settings-card.mdc`](../../.cursor/rules/settings-card.mdc) — UI ядра — Настройки — SettingsCard / SettingsCardRow
- [`.cursor/rules/status-reports.mdc`](../../.cursor/rules/status-reports.mdc) — Ответ «как процесс», «сколько осталось», «идёт», «есть капча» — только факты и числа
- [`.cursor/rules/step-rail.mdc`](../../.cursor/rules/step-rail.mdc) — UI ядра — Шкала шагов — StepRail
- [`.cursor/rules/tab-bar.mdc`](../../.cursor/rules/tab-bar.mdc) — UI ядра — Вкладки — TabBar
- [`.cursor/rules/testing.mdc`](../../.cursor/rules/testing.mdc) — Изолированные тесты модулей и системный контур — ergoms api test, ergoms system-test
- [`.cursor/rules/text-editor.mdc`](../../.cursor/rules/text-editor.mdc) — UI ядра — Текст — TextEditor
- [`.cursor/rules/time-picker.mdc`](../../.cursor/rules/time-picker.mdc) — UI ядра — Время — TimePicker
- [`.cursor/rules/time-utils.mdc`](../../.cursor/rules/time-utils.mdc) — Даты и время на клиенте — timeUtils.js, getRelativeTime, formatDateTime
- [`.cursor/rules/toast-undo.mdc`](../../.cursor/rules/toast-undo.mdc) — Отмена через success-toast — showUndoableSuccess, undoRegistry, CLIENT_TOAST_UNDO_ENABLED, undoAudit
- [`.cursor/rules/toggle-switch.mdc`](../../.cursor/rules/toggle-switch.mdc) — UI ядра — Тумблер — ToggleSwitch
- [`.cursor/rules/tri-state-switch.mdc`](../../.cursor/rules/tri-state-switch.mdc) — UI ядра — Трёхпозиционный тумблер — TriStateSwitch
- [`.cursor/rules/ui-screenshots.mdc`](../../.cursor/rules/ui-screenshots.mdc) — Снимки интерфейса — кадр 1920×1080, осмысленные части страницы, Roboto, заполненная разобранная карточка, архив в virtual_env/cache/ui-screenshots
- [`.cursor/rules/user-avatar.mdc`](../../.cursor/rules/user-avatar.mdc) — UI ядра — Аватар пользователя — UserAvatar
- [`.cursor/rules/user_search.mdc`](../../.cursor/rules/user_search.mdc) — Поиск пользователей в API — facade над core.search; см. search.mdc
- [`.cursor/rules/virtual-env.mdc`](../../.cursor/rules/virtual-env.mdc) — Виртуальное окружение Python — portable runtime, virtual_env/python, флаги PORTABLE_PYTHON_ENABLED
