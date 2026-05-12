const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const fs = require('fs');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,          // 保持安全
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')  // 我们需要一个预加载脚本
    }
  });
  // 开发环境加载 localhost:3000，生产环境加载打包后的文件
  if (process.env.NODE_ENV === 'development') {
    win.loadURL('http://localhost:3000');
    win.webContents.openDevTools();
  } else {
    win.loadFile(path.join(__dirname, '../build/index.html'));
  }
}

ipcMain.handle('open-path-dialog', async (_event, options = {}) => {
  const { extensions = [] } = options;
  const result = await dialog.showOpenDialog({
    properties: ['openFile', 'openDirectory'],
    filters: extensions.length > 0 ? [{ name: 'Code Files', extensions }] : undefined,
  });

  if (result.canceled || !result.filePaths?.length) {
    return { canceled: true, filePaths: [], kind: null };
  }

  const selected = result.filePaths[0];
  let kind = null;
  try {
    const stat = fs.statSync(selected);
    kind = stat.isDirectory() ? 'directory' : 'file';
  } catch (_err) {
    kind = null;
  }
  return { canceled: false, filePaths: [selected], kind };
});

app.whenReady().then(() => {
  createWindow();
});
