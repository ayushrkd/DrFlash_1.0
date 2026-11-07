const { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')

const API_PORT = 7827
const DEV_PORT = 7828
const isDev = !app.isPackaged

let mainWindow = null
let tray = null
let serverProcess = null

// ─── Window ─────────────────────────────────────────────────

function createWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show()
    mainWindow.focus()
    return
  }

  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: 'Dr. Flash',
    icon: path.join(__dirname, '..', '..', 'assets', 'drflash.ico'),
    frame: true,
    backgroundColor: '#09090b',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false,
  })

  const url = isDev
    ? `http://localhost:${DEV_PORT}`
    : `http://localhost:${API_PORT}`

  mainWindow.loadURL(url)

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.on('close', (e) => {
    // Minimize to tray instead of closing
    e.preventDefault()
    mainWindow.hide()
  })
}

// ─── Tray ───────────────────────────────────────────────────

function createTray() {
  const iconPath = path.join(__dirname, '..', '..', 'assets', 'icon-32.png')
  const icon = nativeImage.createFromPath(iconPath)
  tray = new Tray(icon)

  const menu = Menu.buildFromTemplate([
    { label: 'Open Dr. Flash', click: createWindow },
    { label: 'Chat', click: () => { createWindow(); mainWindow.loadURL(`http://localhost:${isDev ? DEV_PORT : API_PORT}/chat`) } },
    { label: 'Dashboard', click: () => { createWindow(); mainWindow.loadURL(`http://localhost:${isDev ? DEV_PORT : API_PORT}/`) } },
    { type: 'separator' },
    { label: 'API Docs', click: () => shell.openExternal(`http://127.0.0.1:${API_PORT}/docs`) },
    { type: 'separator' },
    { label: 'Quit Dr. Flash', click: () => {
      if (serverProcess) serverProcess.kill()
      app.exit(0)
    }},
  ])

  tray.setToolTip('Dr. Flash — AI Companion')
  tray.setContextMenu(menu)
  tray.on('double-click', createWindow)
}

// ─── Server ─────────────────────────────────────────────────

function startServer() {
  const projectDir = path.join(__dirname, '..', '..')
  const pythonPath = path.join(projectDir, '.venv', 'Scripts', 'python.exe')

  try {
    serverProcess = spawn(pythonPath, ['run_server.py'], {
      cwd: projectDir,
      stdio: 'ignore',
      windowsHide: true,
    })
    serverProcess.on('error', (err) => {
      console.log('Server start failed:', err.message)
    })
  } catch (e) {
    console.log('Could not start server:', e.message)
  }
}

// ─── App lifecycle ──────────────────────────────────────────

app.whenReady().then(() => {
  // Register global shortcut
  globalShortcut.register('CommandOrControl+Alt+D', () => {
    createWindow()
    if (mainWindow) {
      mainWindow.loadURL(`http://localhost:${isDev ? DEV_PORT : API_PORT}/chat`)
    }
  })

  startServer()

  // Wait a bit for server to start
  setTimeout(() => {
    createTray()
    createWindow()
  }, 3000)
})

app.on('window-all-closed', (e) => {
  // Don't quit — keep in tray
  e.preventDefault?.()
})

app.on('activate', createWindow)

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  if (serverProcess) serverProcess.kill()
})
