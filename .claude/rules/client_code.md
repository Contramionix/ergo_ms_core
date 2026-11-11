---
paths:
  - "core/client/**/*.vue"
  - "core/client/**/*.js"
  - "modules/*/client/**/*.vue"
  - "modules/*/client/**/*.js"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Клиент (Vue)

- Тексты UI — через **i18n** (`ru` / `en`), без лишних англицизмов в формулировках каталогов
- Адаптивная вёрстка (мобильные тоже) — `useBreakpoint` / Bootstrap; см. [`client-a11y.mdc`](../../.cursor/rules/client-a11y.mdc)
- Режимы анимаций / картинок / помощи диктору — только через `data-ergo-*` и `useUiModes` ([`client-a11y.mdc`](../../.cursor/rules/client-a11y.mdc))
- Иконки — **Lucide**, выравнивай по центру с текстом; icon-only — `aria-label`
- Темы и цвета — через CSS-переменные ядра (`themes.mdc`), не хардкод hex
- Шрифты — только `var(--font-family-base)` / `var(--font-family-mono)`; **без** Google Fonts и других CDN (`themes.mdc`)

## Язык интерфейса

Подписи, подсказки, toast, confirm, пустые состояния, ошибки — **ключи i18n** (`t` / `tGlobal`), каталоги [`core/client/src/i18n/locales/`](../../core/client/src/i18n/locales/). Механизм и hook модулей — [`i18n.mdc`](../../.cursor/rules/i18n.mdc).

В текстах каталогов (особенно `ru`) — понятный язык **без** копирования имён из кода (`toast`, `SelectBox`) в UI.

| Не пиши в каталоге UI | Пиши |
|---|---|
| toast | всплывающее уведомление |
| баннер ОС / OS notification | системное уведомление |
| dropdown | выпадающий список |
| fallback | значение по умолчанию, запасной вариант |
| offline / online (как статус) | не в сети / в сети |
| loading | загрузка… / идёт загрузка |
| client / frontend (о приложении) | приложение |
| settings (как подпись) | настройки |
| CMS | ядро, приложение, каталог страниц (по смыслу) |

**Допустимо** в UI: устоявшиеся имена продуктов и модулей (CRM, API при необходимости), единицы (MB), общепринятые аббревиатуры без замены смысла. Стиль для документации и правил — [`writing-docs-and-rules.mdc`](../../.cursor/rules/writing-docs-and-rules.mdc).

```vue
<!-- BAD — литерал без i18n -->
<span>Включает toast и баннер ОС</span>

<!-- GOOD -->
<span>{{ t('settings.notifications.title') }}</span>
```

```javascript
import { useAppI18n } from '@/i18n/useAppI18n.js'
import { tGlobal } from '@/i18n/index.js'

const { t } = useAppI18n()
toast.success(t('common.saved'))
showSuccess(tGlobal('common.saved'))
```

## Toast-уведомления

Единый слой — `@/js/utils/toast.js`. **Не** импортируй `vue-sonner` напрямую (кроме ядра: `toast.js`, `ErgoToaster.vue`).

```javascript
import { useToast, showSuccess, showError, handleApiError } from '@/js/utils/toast.js'
import { tGlobal } from '@/i18n/index.js'

// в setup / composable
const toast = useToast()
toast.success(tGlobal('common.saved'))
toast.error(tGlobal('common.somethingWentWrong'))

// вне setup (handlers, utils)
showSuccess(tGlobal('common.success'))
showError(tGlobal('errors.api.generic'))

// ошибки API
try { ... } catch (e) { await handleApiError(e, tGlobal('errors.api.generic')) }
```

Полезные функции: `showWarning`, `showInfo`, `showToast`, `showCustomToast`, `normalizeToastMessage`, `getToast`, `showValidationError`, `showSaveSuccess`, `showDeleteSuccess`.

Кастомное тело — любой Vue-компонент через `showCustomToast(component, props, options)` из того же `toast.js`. Модуль не импортирует `vue-sonner`.

Мягкая отмена через кнопку в success-toast — `showUndoableSuccess` (флаг `CLIENT_TOAST_UNDO_ENABLED`, по умолчанию выкл.): [`toast-undo.mdc`](../../.cursor/rules/toast-undo.mdc). Выполненная отмена пишется как `undo.performed` и попадает на вкладку «Отмененные действия», не в общий список журнала ([`audit.mdc`](../../.cursor/rules/audit.mdc)).

Разбор ошибок API: `@/js/utils/apiErrorMessage.js` (`extractApiError`, `parseApiErrorData`); toast — `handleApiError`.

## Подтверждения действий

Единый слой — `@/js/utils/confirm.js`. **Не** локальный `<ConfirmDialog>`, **не** `window.confirm()` / `alert()`.

```javascript
import { confirmAction, confirmDelete, runWithConfirm } from '@/js/utils/confirm.js'
import { tGlobal } from '@/i18n/index.js'

const ok = await confirmDelete(
  tGlobal('components.confirm.deleteTitle'),
  tGlobal('components.confirm.deleteMessage'),
)
if (!ok) return

await runWithConfirm(
  {
    title: tGlobal('components.confirm.deleteTitle'),
    message: tGlobal('components.confirm.deleteMessage'),
    variant: 'danger',
    confirmText: tGlobal('components.confirm.deleteConfirm'),
  },
  () => apiClient.delete(url),
)
```

Подробности, `confirmChoice`, countdown — в `modal-center.mdc`.

- Даты — `@/js/utils/timeUtils.js` (`time-utils.mdc`)

## CSP и динамические стили

При `API_CSP_MODE=no_unsafe*` браузер режет атрибут `style="..."` и Vue `:style`. Не добавляй `'unsafe-inline'` в заголовок.

| Нужно | Как |
|----|-----|
| Дискретные значения (размер 20px, `grid-column: span 6`) | класс или `data-*` + правило в SCSS |
| Непрерывные (координаты меню, `width: 37%`) | `v-csp-style="obj"` — пишет в adopted stylesheet (`cspInlineStyle.js`) |
| Цвет SVG | атрибуты `stroke` / `fill`, не `:style` |

```vue
<!-- BAD — под style-src 'self' правило не применится -->
<div :style="{ top: `${y}px`, left: `${x}px` }" />

<!-- GOOD -->
<div v-csp-style="{ top: `${y}px`, left: `${x}px` }" />
```

## Импорты

Из ядра — с `@/`:

```javascript
import { apiClient } from '@/js/api/manager'
import { endpoints } from '@/js/api/endpoints'
```

Внутри модуля — относительные пути.

Между модулями — только мост (`ModuleBridge`), не прямой import.

## Настройки из `.env`

- В корневом `.env` — **`CLIENT_*`**, общие **`API_*`**, **`DISABLED_MODULES`**. **`REALTIME_*`** — [`env/realtime.env.example`](../../env/realtime.env.example); фрагменты — [`env-examples.mdc`](../../.cursor/rules/env-examples.mdc)
- В коде ядра — **`import { clientEnv } from '@/js/clientEnv.js'`**, не `import.meta.env` и не префикс `VITE_`
- Новая настройка модуля: `CLIENT_<МОДУЛЬ>_*` в корневом `.env` **или** `modules/<имя>/.env`; в модуле читай через **локальный** `client/js/clientEnv.js`, не через ядровой `clientEnv.js`. Общие ключи ядра — поле в `clientEnv.js` + `buildClientEnvDefines()` в `core/client/vite.config.js`

```javascript
import { clientEnv } from '@/js/clientEnv.js'

const pageSize = clientEnv.biPreviewItemsPerPage
```

## Компоненты

Разбивай крупные страницы на части. Стили — Bootstrap + SCSS модуля. Вынос в отдельные `.scss`/`.js` — когда компонент больше 1000 строк.

Общие компоненты ядра — [`components.mdc`](../../.cursor/rules/components.mdc) (SelectBox, SearchInput, UserAvatar и др.).

Производительность прогрузки (lazy-модалки, параллельные API, prefetch меню) — [`client-perf.mdc`](../../.cursor/rules/client-perf.mdc).

`defineProps` / `defineEmits` не импортируй — это макросы компилятора.

## Фильтры list-страниц

Состояние поиска, фильтров и пагинации на list-страницах ядра и модулей храни в **URL query** через `@/composables/useRouteQueryState.js`, не в голых `ref()`.

```javascript
import { computed } from 'vue'
import { useRouteQueryState } from '@/composables/useRouteQueryState.js'

const { state: listState, patchState, watchState } = useRouteQueryState({
  q: { default: '' },
  page: { default: 1, type: 'number' },
  status: { default: 'all', enum: ['all', 'pending'] },
}, { debounceKeys: ['q'], preserveKeys: ['tab'] })

const searchQuery = computed(() => listState.value.q)

watchState(() => {
  loadItems()
})
```

Соглашения по ключам: `q` — поиск, `page` — страница, enum-фильтры — короткие имена (`status`, `presence`), даты — `date_from` / `date_to`. Пустые и дефолтные значения из URL убираются. При смене фильтра (кроме `page`) composable сбрасывает страницу в `1`.

Для `FilterMenu` — `filtersObjectFromState` / `filtersObjectToPatch`.

**Исключения:** модалки, inline-picker, одноразовые deep-link params (`?open=`).

## Связанные правила

| Тема | Файл |
|------|------|
| Доступность, режимы UI, адаптив | [`client-a11y.mdc`](../../.cursor/rules/client-a11y.mdc) |
| Производительность прогрузки | [`client-perf.mdc`](../../.cursor/rules/client-perf.mdc) |
| Компоненты UI | [`components.mdc`](../../.cursor/rules/components.mdc) |
| Темы, шрифты | [`themes.mdc`](../../.cursor/rules/themes.mdc) |
| Модалки, confirm | [`modal-center.mdc`](../../.cursor/rules/modal-center.mdc) |
| Undo в toast | [`toast-undo.mdc`](../../.cursor/rules/toast-undo.mdc) |
| Журнал отмен (`undo.performed`) | [`audit.mdc`](../../.cursor/rules/audit.mdc) |
| Ошибки API | [`log-error.mdc`](../../.cursor/rules/log-error.mdc) |
| Права маршрутов (UX) | [`permission_rules.mdc`](../../.cursor/rules/permission_rules.mdc) |
| Модули, мост | [`modules.mdc`](../../.cursor/rules/modules.mdc) |
| Шаблоны `.env` и `env/` | [`env-examples.mdc`](../../.cursor/rules/env-examples.mdc) |
