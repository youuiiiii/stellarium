/**
 * 9Router Child Supervisor for Stellarium Desktop.
 *
 * Automatically manages 9Router lifecycle when Antigravity Pro is used:
 * - Checks if port 20128 is already alive.
 * - If not, spawns 9Router headless in the background using local Node runtime.
 * - Cleanly stops the 9Router child and its process tree upon app exit.
 * - Provides an in-app popup window for seamless Google / Antigravity authentication.
 */

import { spawn, type ChildProcess } from 'node:child_process'
import http from 'node:http'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'
import { BrowserWindow, ipcMain } from 'electron'

let routerProcess: ChildProcess | null = null
let supervisorStarted = false
let loginWindow: BrowserWindow | null = null

/** Check if 9Router is currently listening on port 20128 */
export function is9RouterAlive(port = 20128): Promise<boolean> {
  return new Promise(resolve => {
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port,
        path: '/',
        method: 'GET',
        timeout: 1000
      },
      res => {
        resolve(res.statusCode !== undefined && res.statusCode < 500)
      }
    )
    req.on('error', () => resolve(false))
    req.on('timeout', () => {
      req.destroy()
      resolve(false)
    })
    req.end()
  })
}

/** Resolve potential paths for 9router cli.js and node runtime */
function resolve9RouterBinary(): { nodePath: string; scriptPath: string } | null {
  const home = os.homedir()

  // Search standard locations under AppData / ProgramFiles
  const candidateNodes = [
    process.execPath, // Electron's own node or packaged node
    path.join(home, 'AppData', 'Local', 'hermes', 'node', 'node.exe'),
    path.join(home, 'AppData', 'Local', 'Programs', 'nodejs', 'node.exe'),
    'node'
  ]

  const candidateScripts = [
    path.join(home, 'AppData', 'Local', 'hermes', 'node', 'node_modules', '9router', 'cli.js'),
    path.join(home, 'AppData', 'Roaming', 'npm', 'node_modules', '9router', 'cli.js'),
    path.join(home, '.9router', 'cli.js')
  ]

  let resolvedNode = 'node'
  for (const n of candidateNodes) {
    if (n === 'node' || (fs.existsSync(n) && !n.toLowerCase().endsWith('stella.exe') && !n.toLowerCase().endsWith('hermes.exe'))) {
      resolvedNode = n
      break
    }
  }

  let resolvedScript: string | null = null
  for (const s of candidateScripts) {
    if (fs.existsSync(s)) {
      resolvedScript = s
      break
    }
  }

  if (resolvedScript) {
    return { nodePath: resolvedNode, scriptPath: resolvedScript }
  }

  return null
}

/** Spawn 9Router child process in silent background mode */
export async function ensure9RouterRunning(port = 20128): Promise<boolean> {
  if (await is9RouterAlive(port)) {
    return true
  }

  const binary = resolve9RouterBinary()
  if (!binary) {
    return false
  }

  try {
    const child = spawn(binary.nodePath, [binary.scriptPath, '-t', '-n', '-p', String(port)], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      env: {
        ...process.env,
        ELECTRON_RUN_AS_NODE: '1'
      }
    })

    child.unref()
    routerProcess = child

    // Wait up to 5 seconds for port to become alive
    for (let i = 0; i < 10; i++) {
      await new Promise(r => setTimeout(r, 500))
      if (await is9RouterAlive(port)) {
        return true
      }
    }
    return false
  } catch {
    return false
  }
}

/** Open an in-app modern popup window to connect Antigravity Pro without opening external browser */
export function open9RouterLoginWindow(parentWindow?: BrowserWindow): Promise<boolean> {
  return new Promise(resolve => {
    if (loginWindow && !loginWindow.isDestroyed()) {
      loginWindow.focus()
      resolve(true)
      return
    }

    loginWindow = new BrowserWindow({
      width: 760,
      height: 840,
      title: '✦ Antigravity Pro (9Router)',
      parent: parentWindow || undefined,
      modal: Boolean(parentWindow),
      autoHideMenuBar: true,
      backgroundColor: '#09090f',
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true
      }
    })

    loginWindow.loadURL('http://127.0.0.1:20128/')

    loginWindow.on('closed', () => {
      loginWindow = null
      resolve(true)
    })
  })
}

/** Terminate 9Router child process tree cleanly */
export function shutdown9Router(): void {
  if (routerProcess && routerProcess.pid) {
    const pid = routerProcess.pid
    routerProcess = null
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/F', '/T', '/PID', String(pid)], {
          windowsHide: true,
          stdio: 'ignore'
        })
      } else {
        process.kill(-pid, 'SIGTERM')
      }
    } catch {
      // Ignored on clean exit
    }
  }
}

/** Register IPC handlers for renderer process */
export function registerRouterIpc(): void {
  ipcMain.handle('stella:router:is-alive', async () => {
    return is9RouterAlive()
  })

  ipcMain.handle('stella:router:start', async () => {
    return ensure9RouterRunning()
  })

  ipcMain.handle('stella:router:open-login', async event => {
    const parent = BrowserWindow.fromWebContents(event.sender) ?? undefined
    await ensure9RouterRunning()
    return open9RouterLoginWindow(parent)
  })
}

/** Initialize automatic supervisor lifecycle hooks */
export function setup9RouterSupervisor(): void {
  if (supervisorStarted) return
  supervisorStarted = true

  registerRouterIpc()
  void ensure9RouterRunning()
}
