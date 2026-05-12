import React, { useEffect, useMemo, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import axios from 'axios';
import './App.css';

declare global {
  interface Window {
    electronAPI?: {
      openPathDialog: (options: {
        extensions: string[];
      }) => Promise<{ canceled: boolean; filePaths: string[]; kind: 'file' | 'directory' | null }>;
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

interface LanguageProfile {
  key: string;
  label: string;
  monacoLanguage: string;
  extensions: string[];
}

const normalizeRelPath = (value: string) => value.replace(/\\/g, '/');

const LANGUAGE_PROFILES: LanguageProfile[] = [
  {
    key: 'auto',
    label: '自动(多语言)',
    monacoLanguage: 'plaintext',
    extensions: ['.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.go', '.rs', '.cpp', '.cc', '.cxx', '.c', '.h', '.hh', '.hpp', '.hxx', '.cs', '.php', '.rb', '.kt', '.swift'],
  },
  { key: 'python', label: 'Python', monacoLanguage: 'python', extensions: ['.py'] },
  { key: 'java', label: 'Java', monacoLanguage: 'java', extensions: ['.java'] },
  { key: 'cpp', label: 'C/C++', monacoLanguage: 'cpp', extensions: ['.cpp', '.cc', '.cxx', '.c', '.h', '.hh', '.hpp', '.hxx'] },
  { key: 'web', label: 'JS/TS', monacoLanguage: 'typescript', extensions: ['.js', '.jsx', '.ts', '.tsx'] },
];

const inferMonacoLanguageFromFilename = (name: string) => {
  const lower = name.toLowerCase();
  if (lower.endsWith('.py')) return 'python';
  if (lower.endsWith('.java')) return 'java';
  if (lower.endsWith('.go')) return 'go';
  if (lower.endsWith('.rs')) return 'rust';
  if (lower.endsWith('.ts') || lower.endsWith('.tsx')) return 'typescript';
  if (lower.endsWith('.js') || lower.endsWith('.jsx')) return 'javascript';
  if (lower.endsWith('.cpp') || lower.endsWith('.cc') || lower.endsWith('.cxx') || lower.endsWith('.c') || lower.endsWith('.h') || lower.endsWith('.hh') || lower.endsWith('.hpp') || lower.endsWith('.hxx')) return 'cpp';
  if (lower.endsWith('.cs')) return 'csharp';
  if (lower.endsWith('.php')) return 'php';
  if (lower.endsWith('.rb')) return 'ruby';
  if (lower.endsWith('.kt')) return 'kotlin';
  if (lower.endsWith('.swift')) return 'swift';
  return 'plaintext';
};

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

const resolveIssueLine = (issue: Issue, sourceCode: string): number => {
  const lines = sourceCode.split(/\r?\n/);
  const maxLine = Math.max(lines.length, 1);
  const rawLine = Number.parseInt(String(issue.line), 10);
  let line = Number.isFinite(rawLine) && rawLine > 0 ? rawLine : 1;
  line = Math.min(Math.max(line, 1), maxLine);

  const joined = `${issue.message || ''} ${issue.suggestion || ''}`;
  const tokens = Array.from(joined.matchAll(/`([^`]{2,80})`/g)).map((m) => m[1].trim());
  const candidates = new Set<string>();
  for (const token of tokens) {
    if (!token) continue;
    candidates.add(token);
    const fnName = token.split('(')[0].trim();
    if (fnName) candidates.add(fnName);
  }

  for (const candidate of Array.from(candidates)) {
    const lower = candidate.toLowerCase();
    for (let i = 0; i < lines.length; i += 1) {
      const lineText = lines[i].toLowerCase();
      if (lineText.includes(`def ${lower}`) || lineText.includes(lower)) {
        const guessed = i + 1;
        if (Math.abs(guessed - line) > 2) {
          return guessed;
        }
        break;
      }
    }
  }
  return line;
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
  const [languageProfileKey, setLanguageProfileKey] = useState<string>('auto');

  const editorRef = useRef<any>(null);
  const decorationIdsRef = useRef<string[]>([]);
  const progressTimerRef = useRef<number | null>(null);

  const tree = useMemo(() => buildFileTree(projectFiles), [projectFiles]);
  const languageProfile = useMemo(
    () => LANGUAGE_PROFILES.find((item) => item.key === languageProfileKey) || LANGUAGE_PROFILES[0],
    [languageProfileKey],
  );
  const editorLanguage = useMemo(
    () => (languageProfile.key === 'auto' ? inferMonacoLanguageFromFilename(filename) : languageProfile.monacoLanguage),
    [languageProfile, filename],
  );

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

  const syncProjectFiles = async (folder: string, extensions: string[]) => {
    await axios.post('http://localhost:8000/index_project', {
      folder_path: folder,
      extensions,
    });
    const filesRes = await axios.post('http://localhost:8000/get_project_files', {
      folder_path: folder,
      extensions,
    });
    const normalizedFiles: string[] = (filesRes.data.files || []).map((item: string) => normalizeRelPath(item));
    setProjectFiles(normalizedFiles);
    setExpandedFolders(buildDefaultExpandedFolders(normalizedFiles));
    setRootExpanded(true);
    return normalizedFiles;
  };

  const handleOpenPath = async () => {
    const extensions = languageProfile.extensions;
    if (window.electronAPI) {
      const result = await window.electronAPI.openPathDialog({
        extensions: extensions.map((item) => item.replace('.', '')),
      });
      if (result.canceled || result.filePaths.length === 0) {
        return;
      }
      const selected = result.filePaths[0];
      if (result.kind === 'directory') {
        setProjectPath(selected);
        setSingleFileLabel('');
        setProjectStats(null);
        try {
          const files = await syncProjectFiles(selected, extensions);
          alert(`项目索引完成，共 ${files.length} 个文件`);
        } catch (err) {
          console.error(err);
          alert('索引项目失败，请确保后端服务已启动。');
        }
        return;
      }
      if (result.kind === 'file') {
        try {
          const res = await axios.get(`http://localhost:8000/read_file?path=${encodeURIComponent(selected)}`);
          const leaf = normalizeRelPath(selected).split('/').pop() || selected;
          setFilename(leaf);
          setSingleFileLabel(leaf);
          setCode(res.data.content || '');
          setProjectPath('');
          setProjectFiles([]);
          setExpandedFolders(new Set());
          setProjectStats(null);
        } catch (err) {
          console.error(err);
          alert('打开文件失败');
        }
      }
      return;
    }

    const input = document.createElement('input');
    input.type = 'file';
    input.accept = extensions.join(',');
    input.onchange = async (e: any) => {
      const file = e.target.files[0];
      if (!file) return;
      setFilename(file.name);
      setSingleFileLabel(file.name);
      setCode(await file.text());
      setProjectPath('');
      setProjectFiles([]);
      setExpandedFolders(new Set());
      setProjectStats(null);
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

  const handleUnifiedReview = async () => {
    if (!projectPath && !code.trim()) {
      alert('请先打开路径或输入代码');
      return;
    }

    setLoading(true);
    startProgress();
    const extensions = languageProfile.extensions;

    try {
      if (projectPath) {
        setReviewStage('扫描项目文件...');
        const response = await axios.post('http://localhost:8000/review_project', {
          folder_path: projectPath,
          extensions,
          max_files: 60,
          max_file_chars: 7000,
        });
        setIssues(response.data.issues || []);
        setProjectStats({
          reviewed_files: response.data.reviewed_files || 0,
          total_files: response.data.total_files || 0,
          skipped_files: response.data.skipped_files || 0,
          duration_seconds: response.data.duration_seconds || 0,
        });
        finishProgress(100, '全项目审查完成');
      } else {
        setProjectStats(null);
        setReviewStage('检索上下文...');
        const response = await axios.post('http://localhost:8000/review_with_context', {
          code,
          current_file: filename,
          project_path: '',
        });
        setIssues(response.data.issues || []);
        finishProgress(100, '单文件审查完成');
      }
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

  const handleNextLanguageProfile = () => {
    const idx = LANGUAGE_PROFILES.findIndex((item) => item.key === languageProfileKey);
    const next = LANGUAGE_PROFILES[(idx + 1) % LANGUAGE_PROFILES.length];
    setLanguageProfileKey(next.key);
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

  const focusIssue = async (issue: Issue) => {
    if (issue.file && projectPath) {
      const issuePath = normalizeRelPath(issue.file);
      const current = normalizeRelPath(filename);
      if (issuePath !== current) {
        await handleFileClick(issue.file);
      }
    }

    window.setTimeout(() => {
      if (!editorRef.current) return;
      const targetLine = resolveIssueLine(issue, code);
      editorRef.current.revealLineInCenter?.(targetLine);
      editorRef.current.setPosition?.({ lineNumber: targetLine, column: 1 });
      editorRef.current.focus?.();
    }, 80);
  };

  useEffect(() => {
    if (!editorRef.current) {
      return;
    }
    const model = editorRef.current.getModel?.();
    const maxLine = model?.getLineCount?.() || 1;
    const currentRelPath = normalizeRelPath(filename);

    const visibleIssues = issues.filter((issue) => {
      if (!issue.file) {
        return true;
      }
      const issuePath = normalizeRelPath(issue.file);
      return issuePath === currentRelPath;
    });

    const decorations = visibleIssues.map((issue) => {
      const resolvedLine = resolveIssueLine(issue, code);
      return {
      range: {
        startLineNumber: Math.min(Math.max(resolvedLine || 1, 1), maxLine),
        endLineNumber: Math.min(Math.max(resolvedLine || 1, 1), maxLine),
        startColumn: 1,
        endColumn: 1,
      },
      options: {
        isWholeLine: true,
        glyphMarginClassName:
          issue.severity === '高'
            ? 'error-line-margin'
            : issue.severity === '中'
              ? 'warning-line-margin'
              : 'info-line-margin',
        className:
          issue.severity === '高'
            ? 'error-line'
            : issue.severity === '中'
              ? 'warning-line'
              : 'info-line',
      },
    };
    });
    decorationIdsRef.current = editorRef.current.deltaDecorations(decorationIdsRef.current, decorations);
  }, [issues, filename, code]);

  useEffect(() => {
    if (!loading || reviewProgress < 30 || reviewProgress >= 80) {
      return;
    }
    setReviewStage('调用审查模型...');
  }, [loading, reviewProgress]);

  useEffect(() => () => clearProgressTimer(), []);

  useEffect(() => {
    if (!projectPath) {
      return;
    }
    syncProjectFiles(projectPath, languageProfile.extensions).catch((err) => {
      console.error(err);
    });
  }, [projectPath, languageProfile]);

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
          <button onClick={handleOpenPath}>打开路径</button>
          <button onClick={handleNextLanguageProfile}>高级语言: {languageProfile.label}</button>
          <button onClick={handleClear}>清空</button>
          <button className="primary" onClick={handleUnifiedReview} disabled={loading}>
            {loading ? '审查中...' : projectPath ? '开始审查(项目)' : '开始审查(文件)'}
          </button>
        </div>
        <div className="toolbar-meta">
          <span>{projectName || (singleFileLabel ? `单文件: ${singleFileLabel}` : '未打开项目')}</span>
          <span>语言: {languageProfile.label}</span>
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
            language={editorLanguage}
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
                onClick={() => focusIssue(issue)}
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
