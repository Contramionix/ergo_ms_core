const vscode = require('vscode');
const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');
const { spawn } = require('child_process');
const { toExtensionSpawn } = require('./lib/extension-spawn.cjs');

const OUTPUT_CHANNEL_NAME = 'ERGO MS Module MCP';
const SYNC_DEBOUNCE_MS = 400;
const ENABLED_STATE_KEY = 'ergoMs.mcp.enabledServers';
const FINGERPRINT_STATE_KEY = 'ergoMs.mcp.lastFingerprint';
const API_OWNS_JSON_KEY = 'ergoMs.mcp.apiOwnsRegistration';

/** @type {vscode.OutputChannel | undefined} */
let output;
/** @type {string[]} */
let registeredMcpNames = [];
/** @type {boolean} */
let mcpApiWarningShown = false;
/** @type {NodeJS.Timeout | undefined} */
let debounceTimer;
/** @type {vscode.FileSystemWatcher[]} */
let watchers = [];
/** @type {vscode.ExtensionContext | undefined} */
let extensionContext;

/**
 * @param {string} message
 */
function log(message) {
  if (!output) {
    output = vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME);
  }
  output.appendLine(message);
}

/**
 * @returns {string | undefined}
 */
function findWorkspaceRoot() {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    return undefined;
  }
  for (const folder of folders) {
    const root = folder.uri.fsPath;
    if (
      fs.existsSync(path.join(root, '.cursor', 'mcp.registry.yaml')) ||
      (fs.existsSync(path.join(root, 'modules')) && fs.existsSync(path.join(root, '.cursor')))
    ) {
      return root;
    }
  }
  return folders[0].uri.fsPath;
}

/**
 * @param {string} workspaceRoot
 * @returns {string | undefined}
 */
function resolveProjectPython(workspaceRoot) {
  const winPy = path.join(workspaceRoot, 'virtual_env', 'python', 'Scripts', 'python.exe');
  const unixPy = path.join(workspaceRoot, 'virtual_env', 'python', 'bin', 'python');
  if (fs.existsSync(winPy)) {
    return winPy;
  }
  if (fs.existsSync(unixPy)) {
    return unixPy;
  }
  return undefined;
}

/**
 * @param {string} command
 * @param {string[]} args
 * @param {string} cwd
 * @returns {Promise<{ code: number, stdout: string, stderr: string }>}
 */
function runProcess(command, args, cwd) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd,
      shell: process.platform === 'win32',
      env: {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
      },
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on('data', (chunk) => {
      stderr += String(chunk);
    });
    child.on('error', (err) => {
      resolve({ code: 1, stdout, stderr: `${stderr}${err.message}` });
    });
    child.on('close', (code) => {
      resolve({ code: code == null ? 1 : code, stdout, stderr });
    });
  });
}

/**
 * @returns {{ registerServer?: (c: any) => void, unregisterServer?: (n: string) => void } | undefined}
 */
function getCursorMcpApi() {
  const cursor = /** @type {any} */ (vscode).cursor;
  if (!cursor || !cursor.mcp) {
    return undefined;
  }
  const { registerServer, unregisterServer } = cursor.mcp;
  if (typeof registerServer !== 'function' || typeof unregisterServer !== 'function') {
    return undefined;
  }
  return { registerServer, unregisterServer };
}

function unregisterMcpServers() {
  const api = getCursorMcpApi();
  if (!api) {
    registeredMcpNames = [];
    return;
  }
  for (const name of registeredMcpNames) {
    try {
      api.unregisterServer(name);
      log(`[INFO] unregisterServer: ${name}`);
    } catch (err) {
      log(`[WARNING] unregisterServer ${name}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  registeredMcpNames = [];
}

/**
 * @param {string} workspaceRoot
 * @returns {Promise<{ name: string, description: string, source: string, script: string, config: { command: string, args: string[] } }[]>}
 */
async function loadMcpEntries(workspaceRoot) {
  const python = resolveProjectPython(workspaceRoot);
  const script = path.join(workspaceRoot, '.cursor', 'mcp_sync.py');
  if (!python || !fs.existsSync(script)) {
    log('[WARNING] Python проекта или mcp_sync.py не найдены — MCP discovery пропущен');
    return [];
  }

  const result = await runProcess(python, [script, 'list', '--json'], workspaceRoot);
  if (result.code !== 0) {
    log(`[ERROR] mcp_sync list --json: ${result.stderr || result.stdout}`);
    return [];
  }
  const text = result.stdout.trim();
  if (!text) {
    return [];
  }
  try {
    const data = JSON.parse(text);
    if (!Array.isArray(data)) {
      log('[ERROR] mcp_sync list --json: ожидался массив');
      return [];
    }
    return data;
  } catch (err) {
    log(`[ERROR] Разбор JSON MCP: ${err instanceof Error ? err.message : String(err)}`);
    return [];
  }
}

/**
 * @param {string} workspaceRoot
 * @returns {Promise<Record<string, any>>}
 */
async function readExistingMcpServers(workspaceRoot) {
  const mcpPath = path.join(workspaceRoot, '.cursor', 'mcp.json');
  try {
    const raw = await fsp.readFile(mcpPath, 'utf8');
    const data = JSON.parse(raw);
    if (data && typeof data === 'object' && data.mcpServers && typeof data.mcpServers === 'object') {
      return data.mcpServers;
    }
  } catch {
    // нет файла или битый JSON
  }
  return {};
}

/**
 * @param {Record<string, any>} servers
 * @returns {string}
 */
function serializeMcpJson(servers) {
  return `${JSON.stringify({ mcpServers: servers }, null, 4)}\n`;
}

/**
 * Пишет mcp.json только если содержимое реально изменилось.
 * @param {string} workspaceRoot
 * @param {Record<string, any>} servers
 * @returns {Promise<boolean>} true если файл записан
 */
async function writeMcpJsonIfChanged(workspaceRoot, servers) {
  const mcpPath = path.join(workspaceRoot, '.cursor', 'mcp.json');
  const next = serializeMcpJson(servers);
  try {
    const prev = await fsp.readFile(mcpPath, 'utf8');
    if (prev === next) {
      log(`[SKIP] .cursor/mcp.json без изменений (${Object.keys(servers).length} серверов)`);
      return false;
    }
  } catch {
    // файла нет — пишем
  }
  await fsp.writeFile(mcpPath, next, 'utf8');
  const enabledCount = Object.values(servers).filter((s) => s && s.disabled === false).length;
  const disabledCount = Object.keys(servers).length - enabledCount;
  log(
    `[OK] .cursor/mcp.json: записано ${Object.keys(servers).length} ` +
      `(включено ${enabledCount}, выключено ${disabledCount})`,
  );
  return true;
}

/**
 * @param {{ name: string, config: { command: string, args: string[] } }[]} entries
 * @param {Set<string>} enabledSet
 * @returns {Record<string, any>}
 */
function buildServersFromEntries(entries, enabledSet) {
  /** @type {Record<string, any>} */
  const servers = {};
  for (const entry of entries) {
    const cfg = entry.config || {};
    if (!entry.name || !cfg.command) {
      continue;
    }
    servers[entry.name] = {
      command: cfg.command,
      args: Array.isArray(cfg.args) ? cfg.args : [],
      disabled: !enabledSet.has(entry.name),
    };
  }
  return servers;
}

/**
 * @param {{ name: string, config: { command: string, args: string[] } }[]} entries
 * @param {string[]} enabledNames
 * @returns {string}
 */
function buildFingerprint(entries, enabledNames) {
  const catalog = entries
    .map((e) => ({
      name: e.name,
      command: e.config && e.config.command,
      args: e.config && Array.isArray(e.config.args) ? e.config.args : [],
    }))
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  return JSON.stringify({
    catalog,
    enabled: [...enabledNames].sort(),
  });
}

/**
 * Включённые серверы: workspaceState; при первом запуске — миграция из mcp.json.
 * @param {vscode.ExtensionContext} context
 * @param {string} workspaceRoot
 * @param {string[]} allNames
 * @returns {Promise<string[]>}
 */
async function resolveEnabledNames(context, workspaceRoot, allNames) {
  const nameSet = new Set(allNames);
  const stored = context.workspaceState.get(ENABLED_STATE_KEY);
  if (Array.isArray(stored)) {
    return stored.filter((n) => typeof n === 'string' && nameSet.has(n));
  }

  const existing = await readExistingMcpServers(workspaceRoot);
  const fromFile = Object.entries(existing)
    .filter(([name, cfg]) => nameSet.has(name) && cfg && cfg.disabled === false)
    .map(([name]) => name)
    .sort();
  await context.workspaceState.update(ENABLED_STATE_KEY, fromFile);
  if (fromFile.length > 0) {
    log(`[INFO] Включённые MCP перенесены из mcp.json → workspaceState (${fromFile.length})`);
  }
  return fromFile;
}

/**
 * @param {vscode.ExtensionContext} context
 * @param {string[]} names
 */
async function saveEnabledNames(context, names) {
  await context.workspaceState.update(ENABLED_STATE_KEY, [...names].sort());
}

/**
 * Один раз убрать серверы ERGO из mcp.json, чтобы не дублировать с registerServer.
 * @param {vscode.ExtensionContext} context
 * @param {string} workspaceRoot
 * @param {string[]} ourNames
 */
async function neutralizeMcpJsonForApiOnce(context, workspaceRoot, ourNames) {
  if (context.workspaceState.get(API_OWNS_JSON_KEY) === true) {
    return;
  }
  const existing = await readExistingMcpServers(workspaceRoot);
  const ourSet = new Set(ourNames);
  /** @type {Record<string, any>} */
  const remaining = {};
  let removed = 0;
  for (const [name, cfg] of Object.entries(existing)) {
    if (ourSet.has(name)) {
      removed += 1;
      continue;
    }
    remaining[name] = cfg;
  }
  if (removed > 0) {
    await writeMcpJsonIfChanged(workspaceRoot, remaining);
    log(
      `[INFO] mcp.json: убрано ${removed} серверов ERGO (дальше только Cursor registerServer)`,
    );
  } else if (Object.keys(existing).length === 0) {
    log('[INFO] mcp.json пуст или отсутствует — регистрация только через Cursor API');
  }
  await context.workspaceState.update(API_OWNS_JSON_KEY, true);
}

/**
 * @param {string} workspaceRoot
 * @param {{ name: string, config: { command: string, args: string[] } }[]} entries
 * @param {string[]} enabledNames
 * @param {{ registerServer: (c: any) => void }} api
 * @returns {string[]}
 */
function registerEnabledServers(workspaceRoot, entries, enabledNames, api) {
  unregisterMcpServers();
  const enabledSet = new Set(enabledNames);
  /** @type {string[]} */
  const okNames = [];
  for (const entry of entries) {
    if (!enabledSet.has(entry.name)) {
      continue;
    }
    const cfg = entry.config || {};
    if (!entry.name || !cfg.command) {
      continue;
    }
    const spawnCfg = toExtensionSpawn(workspaceRoot, cfg);
    try {
      api.registerServer({
        name: entry.name,
        server: spawnCfg,
      });
      okNames.push(entry.name);
      log(
        `[OK] registerServer: ${entry.name} (${entry.source}) ${spawnCfg.command} ${spawnCfg.args.join(' ')}`,
      );
    } catch (err) {
      log(
        `[ERROR] registerServer ${entry.name}: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }
  registeredMcpNames = okNames;
  return okNames;
}

/**
 * @param {boolean} [showInfo]
 * @param {{ force?: boolean, allowSkipRegister?: boolean }} [options]
 */
async function syncMcpServers(showInfo = false, options = {}) {
  const force = Boolean(options.force);
  const allowSkipRegister = Boolean(options.allowSkipRegister);
  const context = extensionContext;
  if (!context) {
    log('[ERROR] extensionContext не инициализирован');
    return;
  }

  const workspaceRoot = findWorkspaceRoot();
  if (!workspaceRoot) {
    log('[WARNING] Корень workspace не найден');
    if (showInfo) {
      vscode.window.showWarningMessage('ERGO MS Module MCP: корень workspace не найден');
    }
    return;
  }

  log(`[INFO] Workspace: ${workspaceRoot}`);
  const entries = await loadMcpEntries(workspaceRoot);
  log(`[INFO] MCP: в каталоге ${entries.length}`);

  const allNames = entries.map((e) => e.name).filter(Boolean);
  const enabledNames = await resolveEnabledNames(context, workspaceRoot, allNames);
  const fingerprint = buildFingerprint(entries, enabledNames);
  const lastFingerprint = context.workspaceState.get(FINGERPRINT_STATE_KEY);
  const api = getCursorMcpApi();

  if (api) {
    await neutralizeMcpJsonForApiOnce(context, workspaceRoot, allNames);

    const canSkip =
      allowSkipRegister &&
      !force &&
      fingerprint === lastFingerprint &&
      registeredMcpNames.length === enabledNames.length &&
      enabledNames.every((n) => registeredMcpNames.includes(n));

    if (canSkip) {
      log(`[SKIP] Каталог и включённые MCP без изменений (${enabledNames.length} включено)`);
      if (showInfo) {
        vscode.window.showInformationMessage(
          `ERGO MS Module MCP: без изменений (${entries.length} в каталоге, ${enabledNames.length} включено)`,
        );
      }
      return;
    }

    const okNames = registerEnabledServers(workspaceRoot, entries, enabledNames, api);
    await context.workspaceState.update(FINGERPRINT_STATE_KEY, fingerprint);
    log(
      `[OK] Sync через Cursor API: каталог ${entries.length}, registerServer: ${okNames.length}`,
    );

    if (showInfo) {
      vscode.window.showInformationMessage(
        `ERGO MS Module MCP: ${entries.length} в каталоге, ${okNames.length} включено (API)`,
      );
    }
    return;
  }

  await context.workspaceState.update(API_OWNS_JSON_KEY, false);

  if (!mcpApiWarningShown) {
    mcpApiWarningShown = true;
    log(
      '[WARNING] vscode.cursor.mcp.registerServer недоступен. ' +
        'Fallback: .cursor/mcp.json (запись только при изменении).',
    );
  }

  const servers = buildServersFromEntries(entries, new Set(enabledNames));
  const wrote = await writeMcpJsonIfChanged(workspaceRoot, servers);
  await context.workspaceState.update(FINGERPRINT_STATE_KEY, fingerprint);

  if (!wrote && !force) {
    log(`[SKIP] Fallback sync: mcp.json актуален, каталог ${entries.length}`);
  } else {
    log(
      `[OK] Fallback sync: каталог ${entries.length}, включено ${enabledNames.length}`,
    );
  }

  if (showInfo) {
    vscode.window.showInformationMessage(
      `ERGO MS Module MCP: ${entries.length} в каталоге, ${enabledNames.length} включено (mcp.json)`,
    );
  }
}

/**
 * @returns {Promise<void>}
 */
async function enableMcpServers() {
  const context = extensionContext;
  if (!context) {
    return;
  }
  const workspaceRoot = findWorkspaceRoot();
  if (!workspaceRoot) {
    vscode.window.showWarningMessage('ERGO MS Module MCP: корень workspace не найден');
    return;
  }

  let entries = await loadMcpEntries(workspaceRoot);
  if (entries.length === 0) {
    await syncMcpServers(false, { force: true });
    entries = await loadMcpEntries(workspaceRoot);
    if (entries.length === 0) {
      vscode.window.showInformationMessage('ERGO MS Module MCP: серверы не найдены');
      return;
    }
  }

  const allNames = entries.map((e) => e.name).filter(Boolean);
  const enabledNames = await resolveEnabledNames(context, workspaceRoot, allNames);
  const enabledSet = new Set(enabledNames);
  const items = allNames.sort().map((name) => ({
    label: name,
    description: enabledSet.has(name) ? 'включён' : 'выключен',
    picked: enabledSet.has(name),
  }));
  const picked = await vscode.window.showQuickPick(items, {
    canPickMany: true,
    placeHolder: 'Отметьте серверы для включения (остальные останутся выключенными)',
    title: 'ERGO MS: Enable MCP Servers',
  });
  if (!picked) {
    return;
  }
  await saveEnabledNames(
    context,
    picked.map((p) => p.label),
  );
  await syncMcpServers(true, { force: true });
}

/**
 * @returns {Promise<void>}
 */
async function disableMcpServers() {
  const context = extensionContext;
  if (!context) {
    return;
  }
  const workspaceRoot = findWorkspaceRoot();
  if (!workspaceRoot) {
    vscode.window.showWarningMessage('ERGO MS Module MCP: корень workspace не найден');
    return;
  }

  const entries = await loadMcpEntries(workspaceRoot);
  const allNames = entries.map((e) => e.name).filter(Boolean);
  const enabledNames = await resolveEnabledNames(context, workspaceRoot, allNames);
  if (enabledNames.length === 0) {
    vscode.window.showInformationMessage('ERGO MS Module MCP: нет включённых серверов');
    return;
  }

  const items = enabledNames.map((name) => ({
    label: name,
    picked: false,
  }));
  const picked = await vscode.window.showQuickPick(items, {
    canPickMany: true,
    placeHolder: 'Отметьте серверы, которые нужно выключить',
    title: 'ERGO MS: Disable MCP Servers',
  });
  if (!picked || picked.length === 0) {
    return;
  }
  const disableSet = new Set(picked.map((p) => p.label));
  await saveEnabledNames(
    context,
    enabledNames.filter((n) => !disableSet.has(n)),
  );
  await syncMcpServers(true, { force: true });
}

function scheduleSync() {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
  }
  debounceTimer = setTimeout(() => {
    debounceTimer = undefined;
    syncMcpServers(false, { allowSkipRegister: true }).catch((err) => {
      log(`[ERROR] sync: ${err instanceof Error ? err.message : String(err)}`);
    });
  }, SYNC_DEBOUNCE_MS);
}

/**
 * @param {vscode.ExtensionContext} context
 * @param {string} workspaceRoot
 * @param {string} glob
 */
function addWatcher(context, workspaceRoot, glob) {
  const pattern = new vscode.RelativePattern(workspaceRoot, glob);
  const watcher = vscode.workspace.createFileSystemWatcher(pattern);
  watcher.onDidCreate(() => scheduleSync());
  watcher.onDidChange(() => scheduleSync());
  watcher.onDidDelete(() => scheduleSync());
  context.subscriptions.push(watcher);
  watchers.push(watcher);
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  extensionContext = context;
  output = vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME);
  log(
    '[INFO] ERGO MS Module MCP активировано ' +
      '(при Cursor API — registerServer без записи mcp.json; fallback — запись только при diff)',
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('ergo-ms-module-mcp.sync', () =>
      syncMcpServers(true, { force: true }),
    ),
    vscode.commands.registerCommand('ergo-ms-module-mcp.enable', () => enableMcpServers()),
    vscode.commands.registerCommand('ergo-ms-module-mcp.disable', () => disableMcpServers()),
  );

  const workspaceRoot = findWorkspaceRoot();
  if (workspaceRoot) {
    addWatcher(context, workspaceRoot, 'modules/*/mcp/**');
    addWatcher(context, workspaceRoot, '.cursor/mcp.registry.yaml');
    addWatcher(context, workspaceRoot, 'databases.yaml');
  }

  // Activate: зарегистрировать через API при необходимости; mcp.json не трогаем если API есть.
  syncMcpServers(false, { force: false, allowSkipRegister: false }).catch((err) => {
    log(`[ERROR] initial sync: ${err instanceof Error ? err.message : String(err)}`);
  });
}

function deactivate() {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = undefined;
  }
  unregisterMcpServers();
  watchers = [];
  extensionContext = undefined;
}

module.exports = {
  activate,
  deactivate,
};
