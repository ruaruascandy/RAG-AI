const { app, BrowserWindow, ipcMain, dialog } = require('electron');
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

ipcMain.handle('open-folder-dialog', async () => {
  const result = await dialog.showOpenDialog({ properties: ['openDirectory'] });
  return result;
});

app.whenReady().then(() => {
  createWindow();
});