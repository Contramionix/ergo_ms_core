import { spawnSync } from 'child_process';
import { readdir, mkdir, rm, readFile, copyFile } from 'fs/promises';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import os from 'os';
import { existsSync } from 'fs';
import {
  copyDirectory,
  installExtensionFromVsix,
  removeLegacyExtensionDirs,
  resolveProjectPython,
  runCodeCli,
  vsixDriftFromSource,
} from '../lib/extension-cli.js';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const osAbstraction = require('../lib/os-abstraction.cjs');

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const projectRoot = join(__dirname, '..');
const repoRoot = join(projectRoot, '..');
const extensionsDir = join(projectRoot, 'local-extensions');
const sourceExtensionsDir = join(projectRoot, 'extensions');
const tempRoot = join(projectRoot, '.temp-extract');

function applyCursorBrowserPolicy(root) {
  const pythonExe = resolveProjectPython(root);
  const scriptPath = join(root, 'core', 'deployment', 'scripts', 'cursor_ide_browser_policy.py');
  if (!pythonExe || !existsSync(scriptPath)) {
    return;
  }
  const result = spawnSync(pythonExe, [scriptPath], {
    cwd: root,
    encoding: 'utf8',
    windowsHide: true,
  });
  const out = `${result.stdout || ''}${result.stderr || ''}`.trim();
  if (out) {
    console.log(out);
  }
}

/** @returns {number} negative if a<b, 0 if equal, positive if a>b */
function compareSemver(a, b) {
  const pa = String(a).split('.').map((x) => Number.parseInt(x, 10) || 0);
  const pb = String(b).split('.').map((x) => Number.parseInt(x, 10) || 0);
  for (let i = 0; i < 3; i += 1) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) {
      return d;
    }
  }
  return 0;
}

async function syncSharedLib(sourceExtensionDir) {
  const osAbstractionPath = join(projectRoot, 'lib', 'os-abstraction.cjs');
  if (!existsSync(osAbstractionPath)) {
    return;
  }
  const extLibDir = join(sourceExtensionDir, 'lib');
  await mkdir(extLibDir, { recursive: true });
  await copyFile(osAbstractionPath, join(extLibDir, 'os-abstraction.cjs'));
}

/** name из package.json → каталог исходника и версия. */
async function readSourceExtensions() {
  const sources = new Map();
  if (!existsSync(sourceExtensionsDir)) {
    return sources;
  }
  for (const entry of await readdir(sourceExtensionsDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) {
      continue;
    }
    const dir = join(sourceExtensionsDir, entry.name);
    const packageJsonPath = join(dir, 'package.json');
    if (!existsSync(packageJsonPath)) {
      continue;
    }
    try {
      const pkg = JSON.parse(await readFile(packageJsonPath, 'utf-8'));
      if (pkg.name && pkg.version) {
        sources.set(String(pkg.name), { dir, version: String(pkg.version), entry: entry.name });
      }
    } catch {
      // битый package.json — пропускаем, как и раньше
    }
  }
  return sources;
}

/**
 * Почему VSIX ставить нельзя, или пустая строка.
 * Источник правды — .vscode/extensions/. Код расширения правят там, а VSIX
 * пересобирают вручную: забытая пересборка при той же версии ставила старый код.
 */
async function vsixStaleReason(vsixPath, vsixVersion, source) {
  const order = compareSemver(source.version, vsixVersion);
  if (order > 0) {
    return `исходники ${source.version} новее VSIX ${vsixVersion}`;
  }
  if (order < 0) {
    return '';
  }
  await syncSharedLib(source.dir);
  const drift = await vsixDriftFromSource(vsixPath, source.dir, tempRoot);
  if (drift.length === 0) {
    return '';
  }
  return `VSIX ${vsixVersion} собран не из текущих исходников той же версии (${drift.join(', ')})`;
}

async function installFromSourceDir(sourceExtensionDir, homeDir) {
  const packageJsonPath = join(sourceExtensionDir, 'package.json');
  if (!existsSync(packageJsonPath)) {
    return false;
  }

  const packageJson = JSON.parse(await readFile(packageJsonPath, 'utf-8'));
  const { publisher, name, version } = packageJson;
  if (!publisher || !name || !version) {
    return false;
  }

  await syncSharedLib(sourceExtensionDir);

  const extensionDirName = `${publisher}.${name}-${version}`;
  const extensionIdPrefix = `${publisher}.${name}-`;
  let installed = false;

  for (const installDir of [
    ...[
      osAbstraction.getLocalExtensionsDir(homeDir, false),
      osAbstraction.getLocalExtensionsDir(homeDir, true),
    ],
    ...osAbstraction.getRemoteExtensionsDirs(homeDir),
  ]) {
    try {
      await mkdir(installDir, { recursive: true });

      if (existsSync(installDir)) {
        for (const entry of await readdir(installDir, { withFileTypes: true })) {
          if (!entry.isDirectory() || !entry.name.startsWith(extensionIdPrefix)) {
            continue;
          }
          if (entry.name === extensionDirName) {
            continue;
          }
          await rm(join(installDir, entry.name), { recursive: true, force: true }).catch(() => {});
        }
      }

      await removeLegacyExtensionDirs(installDir, name);

      const targetDir = join(installDir, extensionDirName);
      if (existsSync(targetDir)) {
        await rm(targetDir, { recursive: true, force: true });
      }
      await copyDirectory(sourceExtensionDir, targetDir);
      installed = true;
      console.log(`  [OK] Установлено из исходников: ${extensionDirName} -> ${installDir}`);
    } catch (error) {
      console.log(`  [WARNING] Не удалось установить в ${installDir}: ${error.message}`);
    }
  }

  return installed;
}

async function installUserConfigToRemote() {
  if (!osAbstraction.supportsRemoteInstall()) {
    return false;
  }

  try {
    const sourceExtensionDir = join(projectRoot, 'extensions', 'user-config');
    if (!existsSync(sourceExtensionDir)) {
      console.log('  [INFO] Исходная директория расширения не найдена, пропускаем установку на удаленный сервер');
      return false;
    }

    const remoteDirs = osAbstraction.getRemoteExtensionsDirs(os.homedir());
    if (remoteDirs.length === 0) {
      return false;
    }

    const packageJson = JSON.parse(
      await readFile(join(sourceExtensionDir, 'package.json'), 'utf-8'),
    );
    const publisher = String(packageJson.publisher || '');
    const name = String(packageJson.name || '');
    const version = String(packageJson.version || '');
    if (!publisher || !name || !version) {
      return false;
    }
    const extensionDirName = `${publisher}.${name}-${version}`;

    let installed = false;

    for (const remoteDir of remoteDirs) {
      try {
        await mkdir(remoteDir, { recursive: true });
        const targetDir = join(remoteDir, extensionDirName);

        if (existsSync(targetDir)) {
          await rm(targetDir, { recursive: true, force: true });
        }

        await copyDirectory(sourceExtensionDir, targetDir);
        console.log(`  [OK] Установлено на удаленный сервер: ${remoteDir}`);
        installed = true;
      } catch {
        console.log(`  [INFO] Директория недоступна: ${remoteDir}`);
      }
    }

    return installed;
  } catch (error) {
    console.error(`  [WARNING] Ошибка при установке на удаленный сервер: ${error.message}`);
    return false;
  }
}

async function installExtensions() {
  try {
    const homeDir = os.homedir();
    let vsixFiles = [];

    if (existsSync(extensionsDir)) {
      const files = await readdir(extensionsDir);
      // При нескольких версиях одного расширения — только максимальная semver.
      const byName = new Map();
      for (const file of files.filter((f) => f.endsWith('.vsix'))) {
        const m = file.match(/^(.*)-(\d+\.\d+\.\d+)\.vsix$/i);
        if (!m) {
          continue;
        }
        const [, base, ver] = m;
        const prev = byName.get(base);
        if (!prev || compareSemver(ver, prev.ver) > 0) {
          byName.set(base, { file, ver });
        }
      }
      vsixFiles = [...byName.values()].map((x) => x.file).sort();
    }

    if (vsixFiles.length === 0) {
      console.log('[INFO] VSIX в local-extensions нет — устанавливаем из .vscode/extensions/');
      if (!existsSync(sourceExtensionsDir)) {
        console.error('[ERROR] Нет ни VSIX, ни исходников расширений');
        process.exit(1);
      }

      const entries = await readdir(sourceExtensionsDir, { withFileTypes: true });
      const dirs = entries.filter((e) => e.isDirectory()).map((e) => e.name);
      let any = false;
      for (const dirName of dirs) {
        console.log(`\n-> Установка из исходников: ${dirName}`);
        const ok = await installFromSourceDir(join(sourceExtensionsDir, dirName), homeDir);
        if (ok) {
          any = true;
        }
      }
      if (!any) {
        console.error('[ERROR] Не удалось установить ни одного расширения из исходников');
        process.exit(1);
      }
      console.log('\n[OK] Установка расширений завершена.');
      applyCursorBrowserPolicy(repoRoot);
      console.log('Перезапустите IDE (Developer: Reload Window) для применения изменений.\n');
      return;
    }

    const isRemote = process.env.SSH_CONNECTION || process.env.SSH_CLIENT ||
      existsSync(join(os.homedir(), '.vscode-server')) ||
      existsSync(join(os.homedir(), '.cursor-server'));

    if (isRemote) {
      console.log('\n[WARNING] Скрипт запущен на удаленном сервере или VS Code подключен к Remote.');
      console.log('   Расширения будут установлены на удаленный сервер.');
      console.log('   Для локальной установки запустите эту команду на локальной машине.\n');
    }

    console.log(`[INFO] Найдено ${vsixFiles.length} расширений для установки:`);

    const sources = await readSourceExtensions();
    const vsixNames = new Set();
    let staleVsix = 0;

    for (const file of vsixFiles) {
      const filePath = join(extensionsDir, file);
      const isUserConfig = file.includes('user-config');
      const [, vsixName = '', vsixVersion = ''] = file.match(/^(.*)-(\d+\.\d+\.\d+)\.vsix$/i) || [];
      vsixNames.add(vsixName);

      const source = sources.get(vsixName);
      const stale = source ? await vsixStaleReason(filePath, vsixVersion, source) : '';
      if (stale) {
        staleVsix += 1;
        console.log(`\n-> [WARNING] ${file}: ${stale}. Ставлю из исходников: ${source.entry}`);
        await installFromSourceDir(source.dir, homeDir);
        continue;
      }

      console.log(`\n-> Установка: ${file}`);

      let installed = false;
      try {
        installed = await installExtensionFromVsix(filePath, homeDir, tempRoot);
      } catch (error) {
        console.log(`  [WARNING] Не удалось установить через распаковку: ${error.message}`);
      }

      if (installed) {
        console.log(`  [OK] Успешно установлено: ${file}`);
      } else {
        console.log('  [WARNING] Прямая установка не удалась, пробуем code CLI...');
        try {
          runCodeCli(`code --install-extension "${filePath}" --force`, { cwd: projectRoot });
          console.log(`  [OK] Успешно установлено через code CLI: ${file}`);
          installed = true;
        } catch (error) {
          console.log(`  [WARNING] Не удалось установить через code: ${error.message}`);
        }
      }

      if (!installed) {
        console.log(`\n  [INFO] Для ручной установки: code --install-extension "${filePath}" --force`);
      }

      if (isUserConfig) {
        console.log(`\n-> Установка на удаленный сервер: ${file}`);
        const remoteInstalled = await installUserConfigToRemote();
        if (remoteInstalled) {
          console.log(`[OK] Успешно установлено на удаленный сервер: ${file}`);
        } else {
          console.log(`[INFO] Удаленный сервер не найден или недоступен: ${file}`);
        }
      }
    }

    // Расширения без VSIX ставим из .vscode/extensions/.
    for (const [name, source] of sources) {
      if (vsixNames.has(name)) {
        continue;
      }
      console.log(`\n-> VSIX для ${name} нет — установка из исходников: ${source.entry}`);
      await installFromSourceDir(source.dir, homeDir);
    }

    if (staleVsix > 0) {
      console.log(`\n[WARNING] Устаревших VSIX: ${staleVsix}. Пересоберите пакеты: ergoms update-vsix`);
    }

    console.log('\n[OK] Установка расширений завершена.');
    applyCursorBrowserPolicy(repoRoot);
    console.log('Перезапустите IDE (Developer: Reload Window) для применения изменений.\n');
  } catch (error) {
    if (error.code === 'ENOENT') {
      console.error('[ERROR] Папка local-extensions не найдена');
    } else {
      console.error('[ERROR]', error.message);
    }
    process.exit(1);
  }
}

installExtensions();
