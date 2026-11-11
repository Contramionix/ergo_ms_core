import { register } from 'node:module'

// Голый импорт из modules/*/client Node ищет рядом с файлом и не видит
// пакеты, которые ergoms кладёт в virtual_env/npm/node_modules.
await register('./resolve_workspace_hook.mjs', import.meta.url)
