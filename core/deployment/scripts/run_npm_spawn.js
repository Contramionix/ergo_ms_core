/**
 * Запуск npm без DEP0190 (shell:true + массив args).
 * На Windows — через cmd.exe /d /s /c одной строкой; иначе spawn без shell.
 */

import { spawnSync } from 'node:child_process'

function quoteCmdArg(arg) {
  const s = String(arg)
  // В кавычках cmd.exe сохраняет ^; без них npm.cmd теряет диапазон semver.
  if (!/[ \t"&<>|()^]/.test(s)) {
    return s
  }
  return `"${s.replace(/"/g, '""')}"`
}

export function runNpm(args, options = {}) {
  const base = {
    stdio: 'inherit',
    env: process.env,
    ...options,
    shell: false,
  }

  if (process.platform === 'win32') {
    const line = ['npm', ...args].map(quoteCmdArg).join(' ')
    return spawnSync('cmd.exe', ['/d', '/s', '/c', line], {
      ...base,
      windowsHide: true,
      windowsVerbatimArguments: true,
    })
  }

  return spawnSync('npm', args, base)
}
