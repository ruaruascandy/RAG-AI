# 测试报告（TEST_REPORT）

- 报告时间：2026-04-22
- 测试环境：Windows（PowerShell），项目根目录 `D:\RAG-AI\code-review-rag`
- 后端虚拟环境：`D:\RAG-AI\code-review-rag\backend\.venv312`
- 关键运行参数（本次测试）：
  - `REVIEWER_NUM_CTX=1024`
  - `REVIEWER_MAX_CODE_CHARS=3000~5000`
  - `REVIEWER_MAX_TOKENS=128`
  - `REVIEWER_TIMEOUT_SECONDS=8/20`（分场景）
  - `RAG_EMBED_DEVICE=directml`
  - `RAG_HF_HOME=D:\RAG-AI\hf_cache312`

## 1) 测试范围

1. 后端依赖与基础健康检查
2. 后端 API 冒烟测试（`/health`、`/index_project`、`/get_project_files`、`/read_file`、`/review`、`/review_with_context`）
3. Ollama 连通性验证
4. 前端构建可用性验证

## 2) 执行用例与结果

| 编号 | 用例 | 命令/方式 | 结果 |
|---|---|---|---|
| T1 | Python 依赖一致性 | `python -m pip check` | 通过（No broken requirements found） |
| T2 | 后端核心源码语法检查 | `python -m compileall main.py rag.py reviewer.py chunker.py` | 通过 |
| T3 | 后端健康检查 | `GET /health` | 通过（200，约 0.012s） |
| T4 | 项目文件列表 | `POST /get_project_files` | 通过（200，4 个 `.py` 文件） |
| T5 | 文件读取接口 | `GET /read_file` | 通过（200） |
| T6 | 项目索引接口 | `POST /index_project` | 通过（200，indexed_files=4，约 10.763s） |
| T7 | 带上下文审查接口稳定性（2 次） | `POST /review_with_context` | 接口层通过（2/2 返回 200），业务结果失败（均返回 Ollama 超时问题） |
| T8 | 普通审查接口 | `POST /review` | 接口层通过（200），业务结果失败（返回 Ollama 超时问题） |
| T9 | Ollama HTTP 直连连通性 | `POST http://127.0.0.1:11434/api/generate`（短提示词） | 通过（约 4.984s 返回） |
| T10 | 前端自动化测试脚本 | `npm.cmd test -- --watchAll=false` | 未通过（`package.json` 无 `test` 脚本） |
| T11 | 前端生产构建 | `npm.cmd run build` | 未通过（`spawn EPERM`） |

## 3) 关键性能与稳定性数据

### 3.1 `/review_with_context`（真实 Ollama 集成）

- 2 次执行均返回 200
- 耗时：66.402s ~ 75.203s，平均 70.803s
- 结果内容均为降级告警 issue：
  - `Ollama 调用失败(HTTP与CLI均失败): timed out; CLI ... timed out`

### 3.2 `/review`

- 返回 200，耗时约 76.416s
- 返回内容同样为降级告警 issue（并非实际代码审查结论）

### 3.3 RAG embedding 行为

- 观察到日志：
  - `embedding encode failed: Cannot set version_counter for inference tensor`
  - `switched to directml (forced)+hashing-fallback`
- 说明：DirectML 编码阶段失败后，系统已按设计自动切换到 hashing fallback，接口可继续工作。

## 4) 主要问题记录

1. **高优先级**：审查模型链路不稳定（主要表现为超时，历史上有 WinError 10054）
2. **中优先级**：前端缺少 `test` 脚本，无法执行标准前端单元测试流程
3. **中优先级**：前端 `build` 出现 `spawn EPERM`，发布流程存在阻塞风险
4. **低优先级**：存在 deprecation/future warning（当前不阻断功能）

## 5) 结论

- **后端服务可用性**：基础 API 可用，500 错误已显著收敛（本轮均为 200）。
- **后端业务有效性**：审查结果质量当前不可接受（多数请求超时并降级为错误提示）。
- **前端交付就绪度**：尚未达到“可稳定构建与自动化测试”状态。

## 6) 建议的下一轮验证重点

1. 将审查模型切换到更轻量模型（如 3B 级）后重测 `/review_with_context` 成功率与时延。
2. 增加 reviewer 传输层日志（HTTP/CLI 路径、异常类型、重试次数）。
3. 修复前端 `spawn EPERM` 后执行一次完整 `build` 与烟测。
4. 为前端补充最小 `test` 脚本并接入 CI 基础检查。
