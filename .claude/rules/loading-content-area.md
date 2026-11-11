---
paths:
  - "core/client/**/*.vue"
  - "modules/**/client/**/*.vue"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# LoadingContentArea — плавная загрузка контента

Для **списков, таблиц, панелей и модалок**, которые перезагружаются при поиске, фильтрах или пагинации, используй **`LoadingContentArea`** из ядра.

Компонент: `@/components/LoadingContentArea.vue`

## Поведение

- **Первый запрос** — центрированный спиннер, пока данных ещё не было.
- **Повторные обновления** — контент остаётся на месте, поверх полупрозрачный оверлей (без «дёргания» layout).
- **`reset-key`** — сброс режима «первой загрузки» при смене контекста (другой пользователь в модалке, другая вкладка и т.п.).

## Обязательно

- Новые и правки экранов с `DataTable`, списками, фильтрами — оборачивай контент в `LoadingContentArea`
- Импорт: `import LoadingContentArea from '@/components/LoadingContentArea.vue'`
- Статистику, фильтры и тулбар **не** прячь через `v-if="!isLoading"` — они должны оставаться видимыми при обновлении
- В модалках при смене сущности передавай `:reset-key` (например `userId`, `` `${organizationId}-${activeTab}` ``)

## Запрещено

```vue
<!-- BAD — таблица/список исчезает при каждом запросе -->
<div v-if="isLoading" class="py-5"><SpinnerLoading /></div>
<DataTable v-else :items="rows" ... />

<!-- BAD — сводка/статистика пропадает при фильтрации -->
<p v-if="!isLoading">{{ listSummary }}</p>

<!-- BAD — дублировать overlay/opacity/pointer-events в каждом экране -->
<div class="my-table-wrap" :class="{ refreshing: isLoading }">...</div>
```

## Базовый пример

```vue
<script setup>
import LoadingContentArea from '@/components/LoadingContentArea.vue'

const isLoading = ref(false)
</script>

<template>
  <p class="list-summary">{{ listSummary }}</p>

  <LoadingContentArea :loading="isLoading">
    <DataTable :items="rows" ... />
  </LoadingContentArea>
</template>
```

## Модалка / смена контекста

```vue
<LoadingContentArea :loading="loading" :reset-key="userId" min-height="16rem">
  <template v-if="userId">...</template>
</LoadingContentArea>
```

## Частые props

| Prop | Когда |
|------|--------|
| `loading` | флаг загрузки с API |
| `reset-key` | смена пользователя, организации, вкладки — снова «первая загрузка» |
| `min-height` | минимальная высота зоны (по умолчанию `12rem`) |
| `loading-text` | подпись под спиннером |
| `dim-content` | `false` — без затемнения старых данных при refresh |

## Исключения

- **Спиннер на кнопке** (отправка формы, сохранение) — `spinner-border` / `SpinnerLoading variant="button"`, не `LoadingContentArea`
- **Полноэкранная проверка доступа** до первого рендера страницы (`isCheckingAccess`) — отдельный блок, не таблица
- **Клиентская фильтрация без перезапроса** — overlay не нужен, если данные не перезагружаются с API

## Связанные правила

| Тема | Файл |
|------|------|
| Другие компоненты ядра | [`components.mdc`](../../.cursor/rules/components.mdc) |
| Производительность прогрузки | [`client-perf.mdc`](../../.cursor/rules/client-perf.mdc) |
| SelectBox в фильтрах | [`select-box.mdc`](../../.cursor/rules/select-box.mdc) |
