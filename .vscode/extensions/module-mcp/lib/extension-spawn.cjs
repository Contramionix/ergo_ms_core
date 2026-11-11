/**
 * Команда для vscode.cursor.mcp.registerServer.
 * API не принимает cwd и стартует процесс из домашнего каталога.
 * Относительный launcher тогда ищется не в репозитории, а npx.cmd
 * CreateProcess на Windows не запускает.
 */

const fs = require('fs');
const path = require('path');

const SPAWN_ENV_KEYS = [
  'PATH',
  'PATHEXT',
  'SYSTEMROOT',
  'WINDIR',
  'COMSPEC',
  'SYSTEMDRIVE',
  'USERPROFILE',
  'HOMEDRIVE',
  'HOMEPATH',
  'HOME',
  'APPDATA',
  'LOCALAPPDATA',
  'TEMP',
  'TMP',
  'PROGRAMFILES',
  'PROGRAMFILES(X86)',
  'PROGRAMW6432',
  'LANG',
  'LC_ALL',
  'USER',
  'LOGNAME',
  'SHELL',
  'TMPDIR',
];

/**
 * Пустой env в registerServer затирает PATH. Каталог portable Node
 * добавляется в начало, иначе npx.cmd вызывает голый `node` и не находит его.
 * @param {string} workspaceRoot
 * @returns {Record<string, string>}
 */
function extensionMcpEnv(workspaceRoot) {
  /** @type {Record<string, string>} */
  const env = {};
  for (const key of SPAWN_ENV_KEYS) {
    const value = process.env[key];
    if (typeof value === 'string' && value) {
      env[key] = value;
    }
  }
  const nodeDir = path.join(workspaceRoot, 'virtual_env', 'packages', 'nodejs');
  const nodeBinary = process.platform === 'win32'
    ? path.join(nodeDir, 'node.exe')
    : path.join(nodeDir, 'bin', 'node');
  if (fs.existsSync(nodeBinary)) {
    const bin = process.platform === 'win32' ? nodeDir : path.join(nodeDir, 'bin');
    env.PATH = env.PATH ? `${bin}${path.delimiter}${env.PATH}` : bin;
  }
  env.PYTHONIOENCODING = 'utf-8';
  env.PYTHONUTF8 = '1';
  return env;
}

/**
 * @param {string} workspaceRoot
 * @param {string} value
 * @returns {string}
 */
function resolveAgainstWorkspace(workspaceRoot, value) {
  if (value === '.') {
    return workspaceRoot;
  }
  if (path.isAbsolute(value)) {
    return value;
  }
  const abs = path.resolve(workspaceRoot, value);
  if (fs.existsSync(abs)) {
    return abs;
  }
  return value;
}

/**
 * @param {string} workspaceRoot
 * @param {{ command?: string, args?: string[] }} cfg
 * @returns {{ command: string, args: string[], env: Record<string, string> }}
 */
function toExtensionSpawn(workspaceRoot, cfg) {
  let command = resolveAgainstWorkspace(workspaceRoot, cfg.command || '');
  let args = (Array.isArray(cfg.args) ? cfg.args : []).map((arg) =>
    resolveAgainstWorkspace(workspaceRoot, String(arg)),
  );

  const nodeDir = path.join(workspaceRoot, 'virtual_env', 'packages', 'nodejs');
  const portableNode = process.platform === 'win32'
    ? path.join(nodeDir, 'node.exe')
    : path.join(nodeDir, 'bin', 'node');
  const portableNpxCli = path.join(nodeDir, 'node_modules', 'npm', 'bin', 'npx-cli.js');

  if (process.platform === 'win32' && /\.(cmd|bat)$/i.test(command)) {
    const dir = path.dirname(command);
    const nodeExe = fs.existsSync(portableNode) ? portableNode : path.join(dir, 'node.exe');
    const besideCli = path.join(dir, 'node_modules', 'npm', 'bin', 'npx-cli.js');
    const npxCli = fs.existsSync(besideCli) ? besideCli : portableNpxCli;
    if (fs.existsSync(nodeExe) && fs.existsSync(npxCli)) {
      command = nodeExe;
      args = [npxCli, ...args];
    }
  } else if ((command === 'node' || command === 'node.exe') && fs.existsSync(portableNode)) {
    command = portableNode;
  }

  return { command, args, env: extensionMcpEnv(workspaceRoot) };
}

module.exports = {
  toExtensionSpawn,
};
