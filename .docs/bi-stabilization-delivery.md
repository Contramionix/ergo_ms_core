# Стабилизация BI: локальная поставка 25.10.2026

Закрыт доступный контур стабилизации `0 + первая часть F`: PostgreSQL, Windows,
CPU, локальный media_client. Изменения ядра и gitlinks в эту серию не входят.
Работа выполнена локально, без SSH, production, push и перезапуска рабочих служб.
Исходный аудит остаётся историческим документом.

## Исправления и совместимость

- Новая либо изменённая связь проверяет доступ к источнику. Файловое разрешение
  `csv` не разрешает все CSV-файлы; `schema.table` сохраняется в ACL. Независимый
  шаринг графиков сохраняется. HTTP-проверки не заменяют bridge-контракты.
- Для private task до Celery сохраняются инициатор, источники и срок действия.
  Публикация выполняется после внешнего commit; rollback не оставляет задания.
  Повторные активные запросы сериализуются блокировкой. `PENDING` имеет допустимое
  время очереди, `STARTED/RETRY/PROGRESS` учитываются до предельного возраста.
  Непроверяемые, чужие, отозванные и сменившие источник задачи дают `404` до backend.
- Прежние EDA/modeling workers проверяют доступ перед чтением и публикацией
  результата, принимают только ожидаемый task_id и pending-отчёт. Повторная
  доставка завершённого отчёта не пересчитывает его. При отказе очереди нет
  тяжёлого HTTP fallback; клиент получает контролируемую ошибку.
- UUID отчётов/профилей/страниц/виджетов заполняются миграциями. Результаты,
  времена, владельцы, PK, конфигурации и ACL сохраняются. Числовые ключи остаются
  для совместимости; существующие UUID не меняются при повторном migrate.
- Дашборд обновляется одной транзакцией, по UUID внутри своего родителя.
  Скрытые страницы исключаются из чтения, пропущенные сохраняются. Удаления
  явные; UUID из другой страницы, конфликт либо ошибка откатывают весь запрос.
  Частичный patch виджета не сбрасывает его порядок. API и клиент поставляются
  вместе: schema_version=2, public_id, deleted_pages/deleted_items.
- CRUD использует классы и аудит ядра, сохраняя ACL. В журнал не включаются
  пароли, конфигурации источников и содержимое датасетов.
- Клиент сохраняет UUID после ответа сервера, не мутирует страницы при отмене,
  соблюдает права страниц и работает без Web Crypto на HTTP. Новых зависимостей
  и ослабления ESLint нет. Общие вычисления и выбранный источник сохраняют
  поведение поставок C/D.

## Фактические проверки

| Проверка | Результат |
|---|---|
| Исходная рабочая копия | 240 тестов BI OK, 5 ожидаемых пропусков |
| Диагностические регрессии до исправлений | task lifecycle: 11 тестов, 15 падений subtest; ACL: 3 теста, 2 падения + 1 ошибка; partial order: одно падение из 59 |
| Итоговая целевая группа | 62 теста OK |
| Чистая поставка, рабочая копия и отдельный экспорт HEAD | По 263 теста BI OK, 5 ожидаемых пропусков |
| Node | 41/41 OK |
| ESLint BI | 312 файлов, 0 ошибок, 436 прежних предупреждений |
| Production-сборка ядра клиента + BI | Успешна, остальные модули не входят в эту сборку |
| Chrome и настоящий API/PostgreSQL | 6 сценариев OK; отдельно повторены на экспорте HEAD |
| Новая PostgreSQL-БД: core + BI (18 приложений) | Вся цепочка миграций OK; повтор без операций; два dry-run без расхождений |
| Отдельный Celery solo-worker, JSON, собственные SQLite broker/backend | 5 descriptor-операций через HTTP bridge + 6 legacy workflows, eager=False |
| Legacy workflows | EDA, boxplot, сохранённый preview с offset, файловый preview, draft snapshot, sandbox с настоящей BGE на CPU |
| Источник и сохранность | Отдельные app/source БД, таблица-тёзка в app не использована; исторические отчёты неизменны; чужим задачам 404 |
| Архитектура | Экспорт HEAD проходит без диагностических ошибок; рабочая копия — те же 5 прежних нарушений документов CRM |
| Сохранность локальных изменений | Снимок и хэши 22 репозиториев, проверены HEAD/index и неизменные gitlinks |

Пять обычных пропусков: три opt-in проверки embedding-модели, одна opt-in
интеграция сходства с настоящей моделью и браузерная проверка. Браузер и BGE
проверены отдельно в этом прогоне. Первый Chrome-прогон завершился тайм-аутом
навигации до сценариев; runner теперь ждёт готовности приложения и сохраняет
список незавершённых запросов при отказе. Повторные прогоны проходят.

Два диагностических межпроцессных прогона подтвердили пять новых операций,
но остановились на ошибках QA-фикстуры: путь вне bi/uploads, затем отсутствие
обязательного mainTable.id. Фикстура приведена к настоящему контракту media и
клиента; QA-worker запущен с аргументом worker для штатной инициализации Celery.
Полный успешный повтор выполнен на новых UUID-БД; старые тестовые базы не
пересоздавались. Журналы отказов сохранены и не считаются успешными прогонами.

В успешных тестовых журналах есть ожидаемые ERROR/traceback из проверок отказа
брокера, смены источника и отзыва прав. Регрессии проверяют итоговые статусы,
HTTP-коды и отсутствие результата; эти записи не скрывались.

Предварительный архитектурный прогон завершился с кодом 0, но его startup-проверка
обращалась к ещё не созданной QA-БД. Этот журнал не используется для приёмки.
Окончательный core-rules-check повторён на экспорте HEAD с
DATABASE_TEST_CONNECTIONS=false: структурный анализ выполняется без проверки
доступности сервера, а работа с настоящей PostgreSQL подтверждена отдельно.

Команды выполнялись через ergoms в отдельных каталогах virtual_env/cache.
Точные логи, составы и хэши: virtual_env/cache/bi-stabilization-20261025/.
API-тесты используют отдельную БД/кэш и memory broker; межпроцессная проверка
использует собственные broker/backend и настоящий worker. Созданные ей БД удалены,
worker завершён, QA PostgreSQL остановлен. Установленные веса BGE только читались,
скачиваний, изменений Torch/CUDA и установки зависимостей не было.

## Границы приёмки и локальный остаток

Настоящие MSSQL/ClickHouse, remote media_api, Linux Celery, Redis/RabbitMQ,
GPU, нагрузка, все модули клиента и миграция копии рабочей установки остаются в H.
Отдельных серверов MSSQL/ClickHouse пользователь не предоставлял. Проверка storage
без `.path` — регрессионная заглушка, не реальный удалённый сервер.
Общий system-test/deployment в этой серии повторно не запускался: ядро и deployment
не менялись. Пять нарушений CRM не исправлялись.

Сохранены и не включены: переключение `_mssql_url` на pymssql в
api/bi_connections/table_preview.py и декларация необязательной BGE-модели в
runtime_requirements.yaml. Также не затронуты исходные изменения root, core/client
и остальных модулей. Никакие файлы не скрывались новым .gitignore.

Далее — оставшиеся F/G: типы виджетов, клонирование/шаблоны/версии/экспорт,
кэш с ACL до чтения, декомпозиция ECharts и серверные агрегации. Затем E и H.

## Локальные коммиты и состав

Серия применяется целиком, совместно с клиентом и миграциями. Коммиты разделяют
смысловые части, но не являются независимыми версиями API.

| Часть | SHA | Назначение |
|---|---|---|
| sources | `8f637b1daab4ade79d8512bfa61f89eb7ad9aae4` | Точные ACL файлов и схем таблиц, безопасное чтение метаданных и ошибки источника; логические имена полей. |
| tasks | `f2e337ed2f4154f0e83d5778368a6d0dd04c8e5a` | Привязка инициатора/источника до публикации, on_commit, защита worker и повторных запусков, CPU/GPU-маршруты. |
| dashboards | `bfa8fe15ce8ed1f74950976077b9bd9c222add0c` | UUID и атомарное сохранение вложенных объектов, явное удаление, ACL страниц, проверка миграции без пересчёта. |
| crud | `b1ce70b5cb675fc35a4f481429544682cbc335ee` | Действующие базовые классы и журнал ядра, проверка родителя/ACL, регрессионные проверки доступа и сохранения. |
| client | `8b14e5691f8b1b881f1cf45234628aa74e7ddaf3` | Стабильный протокол редактора, ссылки текущего развёртывания, отмена/права страниц и точечные исправления ESLint. |
| documentation | `6d8bd91c2a436ef03115a0828721c18fc525af59` | Настройки окружения, поведение, совместимость обновления и границы проверок. |

Все пути далее относятся к modules/bi_analysis.

| Файл | Назначение |
|---|---|
| [api/bi_connections/source_access.py](../modules/bi_analysis/api/bi_connections/source_access.py) | Точные имена файлов вместо расширений; общий ключ schema.table. |
| [api/operations/access.py](../modules/bi_analysis/api/operations/access.py) | Общие ACL источников и правильный файловый ключ при чтении артефакта. |
| [api/bi_connections/methods.py](../modules/bi_analysis/api/bi_connections/methods.py) | Проверка соединений оставляет подробности ошибки в журнале. |
| [api/bi_connections/table_preview.py](../modules/bi_analysis/api/bi_connections/table_preview.py) | Безопасные SQL-идентификаторы, освобождение engine, ACL схем и стабильные ошибки. |
| [api/sandbox/service.py](../modules/bi_analysis/api/sandbox/service.py) | Метаданные через существующий общий читатель после проверки ACL; убраны дубли URL/SQL. |
| [api/bi_connections/files/media_io.py](../modules/bi_analysis/api/bi_connections/files/media_io.py) | Раздельные нормализация storage-имени и проверка существования файла. |
| [api/bi_connections/files/serializers.py](../modules/bi_analysis/api/bi_connections/files/serializers.py) | Проверка прав при смене подключения файла. |
| [api/bi_datasets/services/column_renames.py](../modules/bi_analysis/api/bi_datasets/services/column_renames.py) | Логические имена и ссылки формул переименовываются без DDL источника. |
| [api/tests/test_saved_dataset_execution.py](../modules/bi_analysis/api/tests/test_saved_dataset_execution.py) | Сопоставление JOIN, формул, параметров, типов, NULL, профиля и переименований. |
| [api/tests/test_postgres_source.py](../modules/bi_analysis/api/tests/test_postgres_source.py) | Настоящее SQLAlchemy-подключение PostgreSQL без fallback к основной БД. |
| [api/models.py](../modules/bi_analysis/api/models.py) | UUID прежних отчётов/профилей; сохранённая привязка BiTaskRun. |
| [api/migrations/0008_public_ids_task_runs.py](../modules/bi_analysis/api/migrations/0008_public_ids_task_runs.py) | Заполнение UUID существующих отчётов/профилей и таблица привязок задач. |
| [api/task_access.py](../modules/bi_analysis/api/task_access.py) | on_commit, дедупликация, TTL/статусы и повторная проверка инициатора/источников. |
| [api/config.py](../modules/bi_analysis/api/config.py) | Порог асинхронного preview, время очереди и предельный возраст задачи. |
| [api/celery_config.py](../modules/bi_analysis/api/celery_config.py) | EDA/modeling возвращены в CPU-очередь; sandbox имеет отдельный маршрут. |
| [task_footprint.yaml](../modules/bi_analysis/task_footprint.yaml) | GPU-профиль выделен для sandbox с CPU fallback; остальные задачи объявлены CPU. |
| [api/tasks.py](../modules/bi_analysis/api/tasks.py) | Привязки private workers проверяются до чтения и выдачи результата; preview учитывает offset/search. |
| [api/bi_connections/files/preview_task.py](../modules/bi_analysis/api/bi_connections/files/preview_task.py) | Прежнее выполнение файлового preview вынесено без смены публичного имени задачи. |
| [api/bi_connections/files/upload_views.py](../modules/bi_analysis/api/bi_connections/files/upload_views.py) | Проверяемые storage-пути и owner/source binding файловых задач; безопасные ответы. |
| [api/eda/task.py](../modules/bi_analysis/api/eda/task.py) | Атомарный pending-claim, проверка прав до/после расчёта и запрет пересчёта при redelivery. |
| [api/eda/views.py](../modules/bi_analysis/api/eda/views.py) | Запуск через общий lifecycle, поиск task_id вместе с датасетом URL и стабильные ошибки. |
| [api/eda/serializers.py](../modules/bi_analysis/api/eda/serializers.py) | UUID отчёта и маскирование подробностей исключений. |
| [api/modeling/task.py](../modules/bi_analysis/api/modeling/task.py) | Та же защита прав и повторной доставки для моделирования. |
| [api/modeling/views.py](../modules/bi_analysis/api/modeling/views.py) | Общий lifecycle, привязка статуса к датасету URL и проверка формы параметров. |
| [api/modeling/serializers.py](../modules/bi_analysis/api/modeling/serializers.py) | UUID отчёта моделирования и безопасное поле ошибки. |
| [api/sandbox/views.py](../modules/bi_analysis/api/sandbox/views.py) | Owner/source binding до публикации; ACL с учётом схемы до статуса, кэша и экспорта. |
| [api/bi_datasets/services/draft_preview/snapshot.py](../modules/bi_analysis/api/bi_datasets/services/draft_preview/snapshot.py) | Блокировка пользователя сериализует конкурентное создание одинаковых снимков. |
| [api/bi_datasets/services/sync.py](../modules/bi_analysis/api/bi_datasets/services/sync.py) | Smoke-проверка пересинхронизации использует выбранное подключение датасета. |
| [api/bi_datasets/views/_sync_gate.py](../modules/bi_analysis/api/bi_datasets/views/_sync_gate.py) | Права проверяются до выдачи состояния синхронизации; исключения скрыты. |
| [api/bi_datasets/views/dataset_preview_views.py](../modules/bi_analysis/api/bi_datasets/views/dataset_preview_views.py) | Проверка параметров, обязательный Celery для больших запросов и приватный статус. |
| [api/bi_datasets/views/draft_preview_views.py](../modules/bi_analysis/api/bi_datasets/views/draft_preview_views.py) | Проверка источников и инициатора снимка до публикации/выдачи; чужой снимок даёт 404. |
| [api/bi_datasets/views/sync_status_views.py](../modules/bi_analysis/api/bi_datasets/views/sync_status_views.py) | Стабильное сообщение об ошибке синхронизации. |
| [api/tests/test_task_lifecycle.py](../modules/bi_analysis/api/tests/test_task_lifecycle.py) | Commit/rollback, смена и отзыв источника, redelivery, скрытие недействительных задач. |
| [api/tests/test_task_concurrency.py](../modules/bi_analysis/api/tests/test_task_concurrency.py) | Конкурентные одинаковые запуски не создают дубликаты. |
| [api/tests/test_draft_task_access.py](../modules/bi_analysis/api/tests/test_draft_task_access.py) | Права и сохранённая привязка черновика до публикации и после отзыва доступа. |
| [api/tests/test_preview_boundaries.py](../modules/bi_analysis/api/tests/test_preview_boundaries.py) | Границы файлового preview, отказ брокера и обход прав родительского источника. |
| [api/bi_dashboards/models.py](../modules/bi_analysis/api/bi_dashboards/models.py) | UUID страниц и виджетов. |
| [api/bi_dashboards/migrations/0007_page_item_public_ids.py](../modules/bi_analysis/api/bi_dashboards/migrations/0007_page_item_public_ids.py) | Заполнение UUID существующих страниц/виджетов без пересоздания. |
| [api/bi_dashboards/graph_write.py](../modules/bi_analysis/api/bi_dashboards/graph_write.py) | Атомарное обновление дерева в своём родителе, явные удаления и сохранение порядка. |
| [api/bi_dashboards/serializers.py](../modules/bi_analysis/api/bi_dashboards/serializers.py) | UUID в протоколе записи, явные удаления и фильтрация чтения по ACL страниц. |
| [api/sharing/services.py](../modules/bi_analysis/api/sharing/services.py) | Разрешение редактирования страниц с учётом индивидуальных overrides. |
| [api/tests/test_public_id_migration.py](../modules/bi_analysis/api/tests/test_public_id_migration.py) | Upgrade и повтор migrate сохраняют результаты, времена, конфигурации, UUID и ACL. |
| [api/crud_audit.py](../modules/bi_analysis/api/crud_audit.py) | Whitelist полей общего аудита, исключающий конфигурации и содержимое данных. |
| [api/bi_charts/serializers.py](../modules/bi_analysis/api/bi_charts/serializers.py) | Права при новой связи с датасетом; существующий независимый шаринг сохранён. |
| [api/bi_charts/views.py](../modules/bi_analysis/api/bi_charts/views.py) | Базовые классы/аудит CRUD и безопасные ошибки графиков. |
| [api/bi_connections/views.py](../modules/bi_analysis/api/bi_connections/views.py) | Базовые классы/аудит, общий URL PostgreSQL и стабильные ошибки подключения. |
| [api/bi_connections/files/views.py](../modules/bi_analysis/api/bi_connections/files/views.py) | Ошибка чтения файла не раскрывает исключение. |
| [api/bi_datasets/views/dataset_views.py](../modules/bi_analysis/api/bi_datasets/views/dataset_views.py) | Аудит создания/обновления датасетов внутри действующих ACL и транзакций. |
| [api/bi_datasets/views/table_field_param_views.py](../modules/bi_analysis/api/bi_datasets/views/table_field_param_views.py) | Базовые viewsets/аудит, права обоих родителей и логическое переименование. |
| [api/bi_dashboards/views.py](../modules/bi_analysis/api/bi_dashboards/views.py) | Права редактирования страниц, аудит CRUD и полный ответ после записи. |
| [api/tests/test_bi_crud_audit.py](../modules/bi_analysis/api/tests/test_bi_crud_audit.py) | Аудит create/update/delete с UUID без секретов и без расширения reader-прав. |
| [api/tests/test_stabilization.py](../modules/bi_analysis/api/tests/test_stabilization.py) | Реальные URL cold/warm, storage без path, ACL страниц, откат и сохранение идентичности. |
| [api/tests/test_source_acl_edges.py](../modules/bi_analysis/api/tests/test_source_acl_edges.py) | Файловые имена, schema.table, display labels и маскирование ошибок источника. |
| [client/Charts/components/BiChartEmbed.vue](../modules/bi_analysis/client/Charts/components/BiChartEmbed.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Charts/components/ChartSettingsFieldModal.vue](../modules/bi_analysis/client/Charts/components/ChartSettingsFieldModal.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Charts/components/InMemoryChartEmbed.vue](../modules/bi_analysis/client/Charts/components/InMemoryChartEmbed.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Charts/components/js/chartDataTransform.js](../modules/bi_analysis/client/Charts/components/js/chartDataTransform.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Charts/components/js/chartTheme.js](../modules/bi_analysis/client/Charts/components/js/chartTheme.js) | Удалены дубликаты ключей с сохранением итоговых цветов. |
| [client/Charts/components/js/echartsOptionBuilder.js](../modules/bi_analysis/client/Charts/components/js/echartsOptionBuilder.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Connections/Files/FilePreview/js/useCsvPreview.js](../modules/bi_analysis/client/Connections/Files/FilePreview/js/useCsvPreview.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Connections/Files/SheetEditor/SheetEditor.vue](../modules/bi_analysis/client/Connections/Files/SheetEditor/SheetEditor.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Connections/Files/SheetEditor/SpreadsheetGrid.vue](../modules/bi_analysis/client/Connections/Files/SheetEditor/SpreadsheetGrid.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Connections/Files/SheetEditor/composables/sheetTranspose.js](../modules/bi_analysis/client/Connections/Files/SheetEditor/composables/sheetTranspose.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Connections/Files/SheetEditor/composables/useFormulas.js](../modules/bi_analysis/client/Connections/Files/SheetEditor/composables/useFormulas.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Connections/Files/SheetEditor/composables/useMerge.js](../modules/bi_analysis/client/Connections/Files/SheetEditor/composables/useMerge.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Connections/Files/js/useFileList.js](../modules/bi_analysis/client/Connections/Files/js/useFileList.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Connections/components/db-settings/ConnectionDetail.vue](../modules/bi_analysis/client/Connections/components/db-settings/ConnectionDetail.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Dashboards/Chart/ChartWidget.vue](../modules/bi_analysis/client/Dashboards/Chart/ChartWidget.vue) | Чистый computed, синхронизация видимой вкладки и title iframe. |
| [client/Dashboards/Chart/chartUrlUtils.js](../modules/bi_analysis/client/Dashboards/Chart/chartUrlUtils.js) | Приём UUID-ссылок текущего origin без привязки к localhost. |
| [client/Dashboards/DashboardHeader.vue](../modules/bi_analysis/client/Dashboards/DashboardHeader.vue) | Действия по роли пользователя и правильная кнопка создания. |
| [client/Dashboards/DashboardPage.vue](../modules/bi_analysis/client/Dashboards/DashboardPage.vue) | UUID из ответа сервера, согласованная запись дерева и перенос виджетов со своей страницей. |
| [client/Dashboards/Selector/SelectorSettings.vue](../modules/bi_analysis/client/Dashboards/Selector/SelectorSettings.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Dashboards/Selector/SelectorWidget.vue](../modules/bi_analysis/client/Dashboards/Selector/SelectorWidget.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Dashboards/Selector/components/SelectorDataSection.vue](../modules/bi_analysis/client/Dashboards/Selector/components/SelectorDataSection.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Dashboards/Selector/components/SelectorListItem.vue](../modules/bi_analysis/client/Dashboards/Selector/components/SelectorListItem.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Dashboards/Selector/components/SelectorListPanel.vue](../modules/bi_analysis/client/Dashboards/Selector/components/SelectorListPanel.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Dashboards/components/DefaultValueSelector.vue](../modules/bi_analysis/client/Dashboards/components/DefaultValueSelector.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Dashboards/components/PageWindow.vue](../modules/bi_analysis/client/Dashboards/components/PageWindow.vue) | Отмена без мутации данных, права страницы и временные ключи без Web Crypto. |
| [client/Dashboards/components/connections/ConnectionsModal.vue](../modules/bi_analysis/client/Dashboards/components/connections/ConnectionsModal.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Dashboards/js/dashboardSerialization.js](../modules/bi_analysis/client/Dashboards/js/dashboardSerialization.js) | UUID, явные удаления, сохранение неизвестных настроек и пропуск read-only страниц. |
| [client/Dashboards/js/useDashboardDrag.js](../modules/bi_analysis/client/Dashboards/js/useDashboardDrag.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/Analysis/AnalysisPage.vue](../modules/bi_analysis/client/Datasets/Analysis/AnalysisPage.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/DatasetFooter.vue](../modules/bi_analysis/client/Datasets/DatasetFooter.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/DatasetListPage.vue](../modules/bi_analysis/client/Datasets/DatasetListPage.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/DatasetPage.vue](../modules/bi_analysis/client/Datasets/DatasetPage.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/Fields/Source/SourceSettings.vue](../modules/bi_analysis/client/Datasets/Fields/Source/SourceSettings.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/Fields/Source/js/formulaLanguage.js](../modules/bi_analysis/client/Datasets/Fields/Source/js/formulaLanguage.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/Fields/Source/js/formulaValidation.js](../modules/bi_analysis/client/Datasets/Fields/Source/js/formulaValidation.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/Sources/DatasetCreating.vue](../modules/bi_analysis/client/Datasets/Sources/DatasetCreating.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/Datasets/Sources/TableLinkModal.vue](../modules/bi_analysis/client/Datasets/Sources/TableLinkModal.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/MainPage/Sidebar/components/SimpleTableDataSet.vue](../modules/bi_analysis/client/MainPage/Sidebar/components/SimpleTableDataSet.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/MainPage/js/useMainSidebarStore.js](../modules/bi_analysis/client/MainPage/js/useMainSidebarStore.js) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/components/common/Placeholders.vue](../modules/bi_analysis/client/components/common/Placeholders.vue) | Использованы существующие вычисляемые подписи и действия заглушки. |
| [client/components/sharing/UserSearch.vue](../modules/bi_analysis/client/components/sharing/UserSearch.vue) | Точечное исправление ESLint без ослабления правил и массового форматирования. |
| [client/package.json](../modules/bi_analysis/client/package.json) | Добавлена команда постоянных Node-тестов без новых зависимостей. |
| [client/tests/browserHarness.js](../modules/bi_analysis/client/tests/browserHarness.js) | Реальные компоненты/API-клиент в локальной тестовой оболочке. |
| [client/tests/chartUrlUtils.test.mjs](../modules/bi_analysis/client/tests/chartUrlUtils.test.mjs) | Допустимые ссылки развёртывания и отклонение чужого origin. |
| [client/tests/dashboard.browser.mjs](../modules/bi_analysis/client/tests/dashboard.browser.mjs) | Шесть UI-сценариев, ожидание готовности, диагностика запросов и проверка без randomUUID. |
| [client/tests/dashboardSerialization.test.mjs](../modules/bi_analysis/client/tests/dashboardSerialization.test.mjs) | Стабильные IDs, явные удаления, read-only, настройки и уникальные временные ключи. |
| [api/tests/test_dashboard_browser.py](../modules/bi_analysis/api/tests/test_dashboard_browser.py) | Opt-in Chrome через настоящий LiveServer/PostgreSQL; контроль БД и ACL после UI. |
| [.env.example](../modules/bi_analysis/.env.example) | Документированы порог preview и времена ожидания/жизни задач. |
| [BEHAVIOR.md](../modules/bi_analysis/BEHAVIOR.md) | Зафиксировано ожидаемое поведение сохранения и прав страниц. |
| [README.md](../modules/bi_analysis/README.md) | Совместимость, обновление, канонические проверки и ссылка на актуальную приёмку. |
