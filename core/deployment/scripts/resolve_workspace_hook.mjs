import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const npmPackage = pathToFileURL(
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../virtual_env/npm/package.json'),
).href

function isBare(specifier) {
  return !specifier.startsWith('.')
    && !specifier.startsWith('/')
    && !specifier.startsWith('node:')
    && !specifier.startsWith('file:')
    && !specifier.startsWith('data:')
}

export async function resolve(specifier, context, nextResolve) {
  if (!isBare(specifier)) {
    return nextResolve(specifier, context)
  }
  try {
    return await nextResolve(specifier, context)
  } catch (error) {
    if (error?.code !== 'ERR_MODULE_NOT_FOUND') {
      throw error
    }
    return nextResolve(specifier, { ...context, parentURL: npmPackage })
  }
}
