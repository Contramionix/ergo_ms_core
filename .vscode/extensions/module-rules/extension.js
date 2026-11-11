const vscode = require('vscode');
const fsp = require('fs/promises');
const path = require('path');

const OUTPUT_CHANNEL_NAME = 'ERGO MS Module Rules';
const STAGING_REL = path.join('virtual_env', 'cache', 'cursor-module-plugins');

/** @type {vscode.OutputChannel | undefined} */
let output;

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
 * @param {string} dir
 * @returns {Promise<boolean>}
 */
async function isDir(dir) {
  try {
    const st = await fsp.stat(dir);
    return st.isDirectory();
  } catch {
    return false;
  }
}

/**
 * @param {unknown} value
 * @returns {Promise<void>}
 */
async function awaitMaybe(value) {
  if (value != null && typeof /** @type {any} */ (value).then === 'function') {
    await value;
  }
}

/**
 * @returns {{
 *   removePlugin?: (config: { path: string }) => void | Thenable<void>,
 *   unregisterPath?: (p: string) => void,
 * } | undefined}
 */
function getRemoveApi() {
  const cursor = /** @type {any} */ (vscode).cursor;
  const plugins = cursor && cursor.plugins;
  if (!plugins) {
    return undefined;
  }
  if (typeof plugins.removePlugin === 'function') {
    return { removePlugin: plugins.removePlugin.bind(plugins) };
  }
  if (typeof plugins.unregisterPath === 'function') {
    return { unregisterPath: plugins.unregisterPath.bind(plugins) };
  }
  return undefined;
}

/**
 * @param {string} stagingRoot
 * @returns {Promise<string[]>}
 */
async function listPluginRoots(stagingRoot) {
  if (!(await isDir(stagingRoot))) {
    return [];
  }
  const entries = await fsp.readdir(stagingRoot, { withFileTypes: true });
  /** @type {string[]} */
  const roots = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) {
      continue;
    }
    const pluginRoot = path.join(stagingRoot, entry.name);
    const marker = path.join(pluginRoot, '.cursor-plugin', 'plugin.json');
    try {
      await fsp.stat(marker);
      roots.push(pluginRoot);
    } catch {
      // не плагин
    }
  }
  return roots;
}

/**
 * Cursor сам читает modules/<имя>/.cursor/rules. Копия через addPlugin
 * грузила те же .mdc второй раз. Команда снимает уже зарегистрированные копии
 * и удаляет staging.
 *
 * @param {boolean} [showInfo]
 * @returns {Promise<void>}
 */
async function dropDuplicatePlugins(showInfo = false) {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    log('[WARNING] Корень workspace не найден');
    return;
  }

  const api = getRemoveApi();
  let removed = 0;

  for (const folder of folders) {
    const stagingRoot = path.join(folder.uri.fsPath, STAGING_REL);
    const pluginRoots = await listPluginRoots(stagingRoot);

    if (api && api.removePlugin) {
      for (const pluginPath of pluginRoots) {
        try {
          await awaitMaybe(api.removePlugin({ path: pluginPath }));
          removed += 1;
          log(`[INFO] removePlugin: ${pluginPath}`);
        } catch (err) {
          log(`[WARNING] removePlugin: ${err instanceof Error ? err.message : String(err)}`);
        }
      }
    } else if (api && api.unregisterPath && pluginRoots.length > 0) {
      try {
        api.unregisterPath(stagingRoot);
        removed += 1;
        log(`[INFO] unregisterPath: ${stagingRoot}`);
      } catch (err) {
        log(`[WARNING] unregisterPath: ${err instanceof Error ? err.message : String(err)}`);
      }
    }

    if (await isDir(stagingRoot)) {
      await fsp.rm(stagingRoot, { recursive: true, force: true });
      log(`[OK] staging удалён: ${stagingRoot}`);
    }
  }

  log('[INFO] Правила модулей читаются из modules/<имя>/.cursor/rules, без копии плагина.');
  if (showInfo) {
    vscode.window.showInformationMessage(
      `ERGO MS Module Rules: копии плагинов сняты (${removed}). Источник — вложенные .cursor/rules.`,
    );
  }
}

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
  output = vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME);
  log('[INFO] ERGO MS Module Rules: регистрация копий отключена');

  context.subscriptions.push(
    vscode.commands.registerCommand('ergo-ms-module-rules.sync', () =>
      dropDuplicatePlugins(true),
    ),
  );

  dropDuplicatePlugins(false).catch((err) => {
    log(`[ERROR] drop duplicates: ${err instanceof Error ? err.message : String(err)}`);
  });
}

function deactivate() {}

module.exports = {
  activate,
  deactivate,
};
