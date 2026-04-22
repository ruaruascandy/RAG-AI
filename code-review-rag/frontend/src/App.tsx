import React, { useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import axios from 'axios';
import './App.css';

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
  const [code, setCode] = useState<string>('# 在此输入你的 Python 代码\n\ndef hello():\n    print("Hello, World!")\n');
  const [filename, setFilename] = useState<string>('untitled.py');
  const [projectPath, setProjectPath] = useState<string>('');
  const [projectFiles, setProjectFiles] = useState<string[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [reviewProgress, setReviewProgress] = useState<number>(0);
  const [reviewStage, setReviewStage] = useState<string>('');

  const editorRef = useRef<any>(null);
  const decorationIdsRef = useRef<string[]>([]);
  const progressTimerRef = useRef<number | null>(null);

  const clearProgressTimer = () => {
    if (progressTimerRef.current) {
      window.clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  };

  const startProgress = () => {
    clearProgressTimer();
    setReviewProgress(8);
    setReviewStage('准备审查任务...');
    progressTimerRef.current = window.setInterval(() => {
      setReviewProgress((prev) => {
        if (prev >= 92) {
          return prev;
        }
        if (prev < 40) {
          return prev + 8;
        }
        if (prev < 70) {
          return prev + 5;
        }
        return prev + 3;
      });
    }, 700);
  };

  const finishProgress = (nextProgress: number, stage: string) => {
    clearProgressTimer();
    setReviewProgress(nextProgress);
    setReviewStage(stage);
  };

  const handleOpenFolder = async () => {
    if (!window.electronAPI) {
      alert('当前不在 Electron 环境中，请使用 Electron 启动应用。');
      return;
    }
    const result = await window.electronAPI.openFolderDialog();
    if (!result.canceled && result.filePaths.length > 0) {
      const folder = result.filePaths[0];
      setProjectPath(folder);
      try {
        await axios.post('http://localhost:8000/index_project', { folder_path: folder });
        const filesRes = await axios.post('http://localhost:8000/get_project_files', { folder_path: folder });
        setProjectFiles(filesRes.data.files);
        alert(`项目索引完成，共 ${filesRes.data.files.length} 个文件`);
      } catch (err) {
        console.error(err);
        alert('索引项目失败，请确保后端服务已启动。');
      }
    }
  };

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
        setProjectPath('');
        setProjectFiles([]);
      }
    };
    input.click();
  };

  const handleClear = () => {
    setCode('');
    setFilename('untitled.py');
    setIssues([]);
  };

  const handleReview = async () => {
    if (!code.trim()) {
      alert('请先输入或打开代码');
      return;
    }
    setLoading(true);
    startProgress();
    try {
      setReviewStage('检索上下文...');
      const response = await axios.post('http://localhost:8000/review_with_context', {
        code,
        current_file: filename,
        project_path: projectPath,
      });
      setIssues(response.data.issues || []);
      finishProgress(100, '审查完成');
    } catch (error) {
      console.error(error);
      finishProgress(100, '审查失败');
      alert('审查失败，请确保后端服务已启动。');
    } finally {
      setLoading(false);
      window.setTimeout(() => {
        setReviewProgress(0);
        setReviewStage('');
      }, 1000);
    }
  };

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

  const handleEditorDidMount = (editor: any) => {
    editorRef.current = editor;
  };

  useEffect(() => {
    if (!editorRef.current) {
      return;
    }
    const decorations = issues.map((issue) => ({
      range: {
        startLineNumber: issue.line,
        endLineNumber: issue.line,
        startColumn: 1,
        endColumn: 1,
      },
      options: {
        isWholeLine: true,
        className:
          issue.severity === '高'
            ? 'error-line'
            : issue.severity === '中'
              ? 'warning-line'
              : 'info-line',
      },
    }));
    decorationIdsRef.current = editorRef.current.deltaDecorations(
      decorationIdsRef.current,
      decorations,
    );
  }, [issues]);

  useEffect(() => {
    if (!loading || reviewProgress < 30 || reviewProgress >= 80) {
      return;
    }
    setReviewStage('调用审查模型...');
  }, [loading, reviewProgress]);

  useEffect(() => () => clearProgressTimer(), []);

  return (
    <div className="app-shell">
      <div className="toolbar">
        <button onClick={handleFileOpen}>打开文件</button>
        <button onClick={handleOpenFolder}>打开项目</button>
        <button onClick={handleClear}>清空</button>

        <button className="primary" onClick={handleReview} disabled={loading}>
          {loading ? '审查中...' : '开始审查'}
        </button>

        <span className="filename">{filename}</span>
      </div>

      {(loading || reviewProgress > 0) && (
        <div className="progress-wrap">
          <div className="progress-meta">
            <span>{reviewStage || '处理中...'}</span>
            <span>{Math.min(reviewProgress, 100)}%</span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${Math.min(reviewProgress, 100)}%` }} />
          </div>
        </div>
      )}

      <div className="main">
        {projectPath && (
          <div className="sidebar">
            <h4>项目文件</h4>
            {projectFiles.map((file) => (
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

        <div className="panel">
          <h3>审查结果</h3>
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
                <div className="issue-suggestion">建议: {issue.suggestion}</div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
