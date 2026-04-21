import React, { useState, useRef, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import axios from 'axios';
import './App.css';

// 声明 Electron API 类型（如果你使用了 preload 脚本）
declare global {
  interface Window {
    electronAPI?: {
      openFolderDialog: () => Promise<{ canceled: boolean; filePaths: string[] }>;
    };
  }
}

interface Issue {
  line: number;
  severity: string;
  message: string;
  suggestion: string;
}

function App() {
  // 状态定义
  const [code, setCode] = useState<string>('# 在此输入你的 Python 代码\n\ndef hello():\n    print("Hello, World!")\n');
  const [filename, setFilename] = useState<string>('未命名.py');
  const [projectPath, setProjectPath] = useState<string>('');
  const [projectFiles, setProjectFiles] = useState<string[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const editorRef = useRef<any>(null);

  // 打开项目文件夹（通过 Electron IPC）
  const handleOpenFolder = async () => {
    if (!window.electronAPI) {
      alert('当前不在 Electron 环境中，请使用 Electron 运行本应用');
      return;
    }
    const result = await window.electronAPI.openFolderDialog();
    if (!result.canceled && result.filePaths.length > 0) {
      const folder = result.filePaths[0];
      setProjectPath(folder);
      try {
        // 1. 索引项目
        await axios.post('http://localhost:8000/index_project', { folder_path: folder });
        // 2. 获取文件列表
        const filesRes = await axios.post('http://localhost:8000/get_project_files', { folder_path: folder });
        setProjectFiles(filesRes.data.files);
        alert(`项目索引完成，共 ${filesRes.data.files.length} 个文件`);
      } catch (err) {
        console.error(err);
        alert('索引项目失败，请确保后端服务已启动');
      }
    }
  };

  // 打开单个文件（传统文件对话框，用于非项目模式）
  const handleFileOpen = async () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.py';
    input.onchange = async (e: any) => {
      const file = e.target.files[0];
      if (file) {
        setFilename(file.name);
        const text = await file.text();
        setCode(text);
        // 清空项目相关状态（可选）
        setProjectPath('');
        setProjectFiles([]);
      }
    };
    input.click();
  };

  // 清空编辑器
  const handleClear = () => {
    setCode('');
    setFilename('未命名.py');
    setIssues([]);
  };

  // 开始审查（使用项目上下文）
  const handleReview = async () => {
    if (!code.trim()) {
      alert('请先输入或打开代码');
      return;
    }
    setLoading(true);
    try {
      const response = await axios.post('http://localhost:8000/review_with_context', {
        code,
        current_file: filename,
        project_path: projectPath   // 如果没有项目，则为空字符串，后端会降级处理
      });
      setIssues(response.data.issues);
    } catch (error) {
      console.error(error);
      alert('审查失败，请确保后端服务已启动');
    } finally {
      setLoading(false);
    }
  };

  // 点击文件列表项，加载文件内容
  const handleFileClick = async (fileRelPath: string) => {
    if (!projectPath) return;
    const fullPath = `${projectPath}/${fileRelPath}`;
    try {
      const res = await axios.get(`http://localhost:8000/read_file?path=${encodeURIComponent(fullPath)}`);
      setCode(res.data.content);
      setFilename(fileRelPath);
    } catch (err) {
      console.error(err);
      alert('读取文件失败');
    }
  };

  // 编辑器挂载回调
  const handleEditorDidMount = (editor: any) => {
    editorRef.current = editor;
  };

  // 根据问题列表高亮编辑器中的行
  useEffect(() => {
    if (editorRef.current && issues.length) {
      const decorations = issues.map(issue => ({
        range: {
          startLineNumber: issue.line,
          endLineNumber: issue.line,
          startColumn: 1,
          endColumn: 1
        },
        options: {
          isWholeLine: true,
          className: issue.severity === '高' ? 'error-line' : (issue.severity === '中' ? 'warning-line' : 'info-line')
        }
      }));
      editorRef.current.deltaDecorations([], decorations);
    }
  }, [issues]);

  return (
    <div>
      {/* 顶部 */}
      <div className="toolbar">
        <button onClick={handleFileOpen}> 打开文件</button>
        <button onClick={handleOpenFolder}> 打开项目</button>
        <button onClick={handleClear}> 清空</button>
  
        <button
          className="primary"
          onClick={handleReview}
          disabled={loading}
        >
          {loading ? '审查中...' : '🔍 开始审查'}
        </button>
  
        <span className="filename"> {filename}</span>
      </div>
  
      {/* 主体 */}
      <div className="main">
        {/* 左侧 */}
        {projectPath && (
          <div className="sidebar">
            <h4> 项目文件</h4>
            {projectFiles.map(file => (
              <div
                key={file}
                className={`file-item ${filename === file ? 'active' : ''}`}
                onClick={() => handleFileClick(file)}
              >
                {file}
              </div>
            ))}
          </div>
        )}
  
        {/* 中间 */}
        <div className="editor-container">
          <Editor
            height="100%"
            language="python"
            value={code}
            onChange={(v) => setCode(v || '')}
            onMount={handleEditorDidMount}
            theme="vs-dark"
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              smoothScrolling: true,
            }}
          />
        </div>
  
        {/* 右侧 */}
        <div className="panel">
          <h3> 审查结果</h3>
  
          {issues.length === 0 ? (
            <p>暂无问题</p>
          ) : (
            issues.map((issue, idx) => (
              <div
                key={idx}
                className={`issue-card ${
                  issue.severity === '高'
                    ? 'issue-high'
                    : issue.severity === '中'
                    ? 'issue-mid'
                    : 'issue-low'
                }`}
              >
                <div className="issue-title">
                  行 {issue.line} [{issue.severity}]
                </div>
                <div>{issue.message}</div>
                <div className="issue-suggestion">
                  💡 {issue.suggestion}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default App;