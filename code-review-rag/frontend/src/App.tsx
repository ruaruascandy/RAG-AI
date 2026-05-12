import React, { useEffect, useMemo, useRef, useState } from 'react';
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
  file?: string;
  line: number;
  severity: string;
  message: string;
  suggestion: string;
}

interface ProjectReviewStats {
  reviewed_files: number;
  total_files: number;
  skipped_files: number;
  duration_seconds: number;
}

interface TreeNode {
  name: string;
  path: string;
  type: 'folder' | 'file';
  children?: TreeNode[];
}

interface MutableTreeNode {
  name: string;
  path: string;
  type: 'folder' | 'file';
  children: MutableTreeNode[];
}

const normalizeRelPath = (value: string) => value.replace(/\\/g, '/');

const buildFileTree = (files: string[]): TreeNode[] => {
  const root: MutableTreeNode = { name: '', path: '', type: 'folder', children: [] };

  const ensureFolder = (parent: MutableTreeNode, name: string, path: string): MutableTreeNode => {
    const exists = parent.children.find((item) => item.type === 'folder' && item.name === name);
    if (exists) {
      return exists;
    }
    const created: MutableTreeNode = { name, path, type: 'folder', children: [] };
    parent.children.push(created);
    return created;
  };

  for (const rawPath of files) {
    const path = normalizeRelPath(rawPath);
    const parts = path.split('/').filter(Boolean);
    if (!parts.length) {
      continue;
    }

    let cursor = root;
    for (let idx = 0; idx < parts.length; idx += 1) {
      const part = parts[idx];
      const currentPath = parts.slice(0, idx + 1).join('/');
      const isFile = idx === parts.length - 1;

      if (isFile) {
        const fileExists = cursor.children.find((item) => item.type === 'file' && item.path === currentPath);
        if (!fileExists) {
          cursor.children.push({
            name: part,
            path: currentPath,
            type: 'file',
            children: [],
          });
        }
      } else {
        cursor = ensureFolder(cursor, part, currentPath);
      }
    }
  }

  const sortNodes = (nodes: MutableTreeNode[]): TreeNode[] => {
    const sorted = [...nodes].sort((a, b) => {
      if (a.type !== b.type) {
        return a.type === 'folder' ? -1 : 1;
      }
      return a.name.localeCompare(b.name, 'zh-Hans-CN');
    });

    return sorted.map((node) => ({
      name: node.name,
      path: node.path,
      type: node.type,
      children: node.type === 'folder' ? sortNodes(node.children) : undefined,
    }));
  };

  return sortNodes(root.children);
};

const buildDefaultExpandedFolders = (files: string[]) => {
  const expanded = new Set<string>();
  for (const file of files) {
    const parts = normalizeRelPath(file).split('/').filter(Boolean);
    if (parts.length > 1) {
      expanded.add(parts[0]);
    }
  }
  return expanded;
};

function App() {
  const [code, setCode] = useState<string>('# 在此输入你的代码\n\ndef hello():\n    print("Hello, World!")\n');
  const [filename, setFilename] = useState<string>('untitled.py');
  const [singleFileLabel, setSingleFileLabel] = useState<string>('');
  const [projectPath, setProjectPath] = useState<string>('');
  const [projectFiles, setProjectFiles] = useState<string[]>([]);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [rootExpanded, setRootExpanded] = useState<boolean>(true);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [projectStats, setProjectStats] = useState<ProjectReviewStats | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [reviewProgress, setReviewProgress] = useState<number>(0);
  const [reviewStage, setReviewStage] = useState<string>('');

  const editorRef = useRef<any>(null);
  const decorationIdsRef = useRef<string[]>([]);
  const progressTimerRef = useRef<number | null>(null);

  const tree = useMemo(() => buildFileTree(projectFiles), [projectFiles]);

  const projectName = useMemo(() => {
    if (!projectPath) {
      return '';
    }
    const parts = normalizeRelPath(projectPath).split('/').filter(Boolean);
    return parts.length ? parts[parts.length - 1] : projectPath;
  }, [projectPath]);

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

  const toggleFolder = (folderPath: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folderPath)) {
        next.delete(folderPath);
      } else {
        next.add(folderPath);
      }
      return next;
    });
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
      setSingleFileLabel('');

      try {
        await axios.post('http://localhost:8000/index_project', { folder_path: folder });
        const filesRes = await axios.post('http://localhost:8000/get_project_files', { folder_path: folder });
        const normalizedFiles: string[] = (filesRes.data.files || []).map((item: string) => normalizeRelPath(item));
        setProjectFiles(normalizedFiles);
        setExpandedFolders(buildDefaultExpandedFolders(normalizedFiles));
        setRootExpanded(true);
        alert(`项目索引完成，共 ${normalizedFiles.length} 个文件`);
      } catch (err) {
        console.error(err);
        alert('索引项目失败，请确保后端服务已启动。');
      }
    }
  };

  const handleFileOpen = async () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.py,.js,.jsx,.ts,.tsx,.java,.go,.rs,.cpp,.c,.h,.hpp,.cs,.php,.rb,.kt,.swift';
    input.onchange = async (e: any) => {
      const file = e.target.files[0];
      if (file) {
        setFilename(file.name);
        setSingleFileLabel(file.name);
        const text = await file.text();
        setCode(text);
        setProjectPath('');
        setProjectFiles([]);
        setExpandedFolders(new Set());
        setProjectStats(null);
      }
    };
    input.click();
  };

  const handleClear = () => {
    setCode('');
    setFilename('untitled.py');
    setSingleFileLabel('');
    setProjectPath('');
    setProjectFiles([]);
    setExpandedFolders(new Set());
    setIssues([]);
    setProjectStats(null);
  };

  const handleReview = async () => {
    if (!code.trim()) {
      alert('请先输入或打开代码');
      return;
    }

    setLoading(true);
    startProgress();
    setProjectStats(null);
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

  const handleProjectReview = async () => {
    if (!projectPath) {
      alert('请先打开项目目录');
      return;
    }

    setLoading(true);
    startProgress();
    setReviewStage('扫描项目文件...');

    try {
      const response = await axios.post('http://localhost:8000/review_project', {
        folder_path: projectPath,
        max_files: 25,
        max_file_chars: 4500,
      });
      setIssues(response.data.issues || []);
      setProjectStats({
        reviewed_files: response.data.reviewed_files || 0,
        total_files: response.data.total_files || 0,
        skipped_files: response.data.skipped_files || 0,
        duration_seconds: response.data.duration_seconds || 0,
      });
      finishProgress(100, '全项目审查完成');
    } catch (error) {
      console.error(error);
      finishProgress(100, '全项目审查失败');
      alert('全项目审查失败，请确保后端服务已启动。');
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
    const fullPath = `${projectPath}\\${fileRelPath.replace(/\//g, '\\')}`;
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
    decorationIdsRef.current = editorRef.current.deltaDecorations(decorationIdsRef.current, decorations);
  }, [issues]);

  useEffect(() => {
    if (!loading || reviewProgress < 30 || reviewProgress >= 80) {
      return;
    }
    setReviewStage('调用审查模型...');
  }, [loading, reviewProgress]);

  useEffect(() => () => clearProgressTimer(), []);

  const getSeverityClass = (severity: string) => {
    if (severity === '高') return 'severity-high';
    if (severity === '中') return 'severity-mid';
    return 'severity-low';
  };

  const renderTree = (nodes: TreeNode[], depth = 0): React.ReactNode[] => {
    return nodes.map((node) => {
      if (node.type === 'folder') {
        const expanded = expandedFolders.has(node.path);
        return (
          <div key={node.path}>
            <div
              className="tree-row folder-row"
              style={{ paddingLeft: `${10 + depth * 14}px` }}
              onClick={() => toggleFolder(node.path)}
            >
              <span className="tree-arrow">{expanded ? 'v' : '>'}</span>
              <span className="tree-folder-mark" />
              <span className="tree-label">{node.name}</span>
            </div>
            {expanded && node.children && renderTree(node.children, depth + 1)}
          </div>
        );
      }

      return (
        <div
          key={node.path}
          className={`tree-row file-row ${filename === node.path ? 'active' : ''}`}
          style={{ paddingLeft: `${26 + depth * 14}px` }}
          onClick={() => handleFileClick(node.path)}
        >
          <span className="tree-file-mark" />
          <span className="tree-label">{node.name}</span>
        </div>
      );
    });
  };

  return (
    <div className="app-shell">
      <div className="toolbar">
        <div className="toolbar-title">Code Review</div>
        <div className="toolbar-actions">
          <button onClick={handleFileOpen}>打开文件</button>
          <button onClick={handleOpenFolder}>打开项目</button>
          <button onClick={handleClear}>清空</button>
          <button className="primary" onClick={handleReview} disabled={loading}>
            {loading ? '审查中...' : '审查当前文件'}
          </button>
          <button onClick={handleProjectReview} disabled={loading || !projectPath}>
            全项目审查
          </button>
        </div>
        <div className="toolbar-meta">
          <span>{projectName || (singleFileLabel ? `单文件: ${singleFileLabel}` : '未打开项目')}</span>
          <span>问题: {issues.length}</span>
        </div>
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
          <aside className="sidebar">
            <div className="sidebar-head">
              <div className="sidebar-title">EXPLORER</div>
            </div>
            <div className="tree-root" onClick={() => setRootExpanded((prev) => !prev)}>
              <span className="tree-arrow">{rootExpanded ? 'v' : '>'}</span>
              <span className="tree-folder-mark" />
              <span className="tree-label">{projectName}</span>
            </div>
            <div className="tree-wrap">{rootExpanded ? renderTree(tree, 1) : null}</div>
          </aside>
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

        <aside className="panel">
          <div className="panel-title">审查结果</div>
          {projectStats && (
            <div className="review-summary">
              <div>已审查文件: {projectStats.reviewed_files}</div>
              <div>项目文件总数: {projectStats.total_files}</div>
              <div>跳过文件: {projectStats.skipped_files}</div>
              <div>耗时: {projectStats.duration_seconds}s</div>
            </div>
          )}

          {issues.length === 0 ? (
            <div className="empty-text">暂无问题</div>
          ) : (
            issues.map((issue, idx) => (
              <div
                key={idx}
                className={`issue-card ${
                  issue.severity === '高' ? 'issue-high' : issue.severity === '中' ? 'issue-mid' : 'issue-low'
                }`}
              >
                <div className="issue-title">
                  {issue.file ? `${issue.file} · ` : ''}行 {issue.line}
                </div>
                <div className={`severity-tag ${getSeverityClass(issue.severity)}`}>{issue.severity}</div>
                <div>{issue.message}</div>
                <div className="issue-suggestion">建议: {issue.suggestion}</div>
              </div>
            ))
          )}
        </aside>
      </div>
    </div>
  );
}

export default App;
