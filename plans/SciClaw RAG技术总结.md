#SciClaw RAG（检索增强生成）技术总结

> **面向读者：** AI Agent / 工程师  
> **文档版本：** 1.0  
> **最后更新：** 2026-07-02  
> **项目：** SciClaw-fe（`~/Desktop/henry/skill-compose/SciClaw-fe`）

---

## 一、概述

SciClaw-fe 的 RAG 系统是**知识库（Knowledge Base，KB）**驱动的内容检索与展示层，覆盖以下核心场景：

| 场景 | 说明 |
|------|------|
| **文件索引与展示** | 用户上传文件后，后端自动向量化并写入 Qdrant，前端在 KB 面板展示索引状态 |
| **图像相似度检索** | Agent 执行 `rag_search` 后在聊天流中展示相关图片，支持预览与下载 |
| **跨项目知识共享** | 通过 `project_references` 引用其他项目的 KB 文件，在 Referenced 视图展示 |
| **Wiki 知识管理** | 自动/手动生成项目 Wiki，版本化管理，支持拖拽引用到 Chat |
| **输出文件推广** | Agent 产出文件可一键"推广到 KB"（Promote to KB），纳入索引 |
| **Foundry 多维检索** | Foundry 交付物场景下自动构造多维度 `rag_search` 提示词 |

---

## 二、整体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                         前端 (React / TypeScript)                     │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────────────┐   │
│  │  KB Sidebar │  │ Stream Event│  │  Quota / Tier / Usage       │   │
│  │  (FilesTab) │  │   Blocks    │  │  (UsagePanel)               │   │
│  │             │  │             │  │                             │   │
│  │ KBFileRow   │  │RagSearch    │  │ TierLimitsInfo              │   │
│  │ AssetList   │  │ImagesBlock  │  │ QdrantUsage                 │   │
│  │ WikiKBSec.  │  │AskLibrary   │  │                             │   │
│  │ PromoteDlg  │  │AdoptedSrc.  │  │                             │   │
│  └──────┬──────┘  └──────┬──────┘  └──────────────┬──────────────┘   │
│         │                │                         │                  │
│         │  lib/api/      │  types/stream-events.ts │ lib/tier-api.ts  │
│         │  lib/usage-api │  lib/error-codes.ts     │                  │
└─────────┼────────────────┼─────────────────────────┼─────────────────┘
          │                │                         │
          ▼                ▼                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      后端 API (FastAPI)                               │
│  POST /api/v1/sessions/{id}/tasks/{n}/promote-to-rag  │ 推广文件     │
│  GET  /api/v1/projects/{id}/referenced-files          │ 引用文件     │
│  GET  /api/v1/tier/limits                              │ 配额查询     │
│  GET  /api/v1/usage/stats                              │ 使用量       │
└──────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      Qdrant 向量数据库                                │
│  (由后端服务端执行向量化 + 索引，前端不直接操作 Qdrant)               │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│              Python RAG Skill (rag-task-investigator)                 │
│  build_retrieval_plan.py  ── 按交付物类型生成检索维度规划             │
│  rag_processing.py        ── tokenize / score / dedupe / enrich       │
│  postprocess_rag_results.py ── 后处理 & TODO 列表生成                  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心类型定义

### 3.1 RagStatus — 文件索引状态

```typescript
// lib/types/outputs-tree.ts:1
export type RagStatus = "indexed" | "pending" | "failed" | "not_indexed" | "skipped"
```

| 状态值 | 含义 |
|--------|------|
| `indexed` | 已成功索引（向量化完成） |
| `pending` | 等待索引 |
| `indexing` | 正在索引中（中间态，由 AssetStatus.Indexing 映射） |
| `failed` | 索引失败 |
| `skipped` | 被跳过（用户手动跳过） |
| `not_indexed` | 未纳入索引 |

### 3.2 OutputFile — 含 RAG 字段的文件模型

```typescript
// lib/types/outputs-tree.ts:3–13
export interface OutputFile {
  path: string
  browser_path: string
  rel_path?: string | null
  name: string
  size: number
  content_type?: string | null
  rag_status: RagStatus          // ← 索引状态
  rag_doc_id?: string | null     // ← Qdrant 文档 ID（前端可用于关联）
  download_url: string
}
```

### 3.3 OutputTask — 含 RAG 统计的任务模型

```typescript
// lib/types/outputs-tree.ts:15–28
export interface OutputTask {
  user_task_number: number
  name: string
  status: "in_progress" | "completed" | "failed" | "abandoned"
  first_message_index?: number | null
  created_at?: string | null
  completed_at?: string | null
  files?: OutputFile[]
  files_total?: number
  has_more_files?: boolean
  rag_docs_count?: number         // ← 该任务关联的已索引文档数量
}
```

### 3.4 Stream Event 中的 RAG 类型

```typescript
// types/stream-events.ts:51–82

// 图像检索结果中的单个图片
export interface RagSearchImageItem {
  assetId?: string;
  documentId: string;
  searchCallId?: string;
  sourceFile: string;
  similarity?: number;            // ← 相似度分数 [0, 1]
  previewText?: string;
  imageUrl?: string;
  browserFilePath?: string;
  documentBrowserFilePath?: string;
  documentFileType?: string;      // ← "pdf" | "png" | ...
  documentPage?: number;          // ← PDF 页码
  width?: number;
  height?: number;
  hasSummary: boolean;
  usedInlineImage: boolean;
  sourceProjectId?: string;       // ← 跨项目来源
  sourceProjectName?: string;
  availability?: "available" | "deleted" | "unknown";
}

// 一组图片检索结果
export interface RagSearchImagesData {
  searchCallId?: string;
  searchCallIds?: string[];
  images: RagSearchImageItem[];
  count: number;
}

// 被 ask_library 采纳的知识来源（Wiki 页面 + 文档）
export interface ReferencedSourcePage {
  path: string;
  title?: string | null;
  sourceProjectId?: string | null;
  sourceProjectName?: string | null;
  sourceWikiVersionId?: string | null;
  sourceWikiVersionNumber?: number | null;
  availability?: "available" | "deleted" | "unknown";
}

export interface ReferencedSourceDocument {
  documentId?: string | null;
  filename: string;
  browserFilePath?: string | null;
  fileType?: string | null;
  sourceProjectId?: string | null;
  sourceProjectName?: string | null;
  taskName?: string | null;
  availability?: "available" | "deleted" | "unknown";
}

// 组合引用证据（Wiki + 文档 + 图片）
export interface ReferencedEvidenceData {
  pages: ReferencedSourcePage[];
  documents: ReferencedSourceDocument[];
  images: RagSearchImageItem[];
  count: number;
  searchCallIds?: string[];
}
```

### 3.5 Qdrant 用量类型

```typescript
// lib/usage-api.ts:33–37
export interface QdrantUsage {
  rag_asset_count: number       // ← RAG 索引的 asset 数量
  memory_entry_count: number    // ← 记忆条目数
  total_points: number          // ← Qdrant 总点数
}
```

### 3.6 Tier RAG 配额类型

```typescript
// lib/tier-api.ts:4–22
export interface TierLimitsInfo {
  max_skills: number
  max_scheduled_tasks: number
  storage_bytes: number
  initial_credits: number
  daily_credits: number
  rag?: {                                    // ← RAG 配额（可能有）
    quota?: {
      embedding_token_limit?: number | null  // ← embedding token 上限
      vector_point_limit?: number | null     // ← 向量存储点数上限
    } | null
  } | null
  // ... wiki / 其他字段
}

export interface TierUsageInfo {
  skills_count: number
  scheduled_tasks_count: number
  storage_used_bytes: number
  rag_embedding_tokens_used?: number          // ← 已用 embedding token
  rag_embedding_period_key?: string | null
  rag_embedding_token_limit?: number | null
  rag_vector_points_used?: number             // ← 已用向量点数
  rag_vector_point_limit?: number | null
}
```

---

## 四、错误码定义

```typescript
// lib/error-codes.ts:222–231

export const RAG_DELETE_BLOCKED_ACTIVE_INDEXING    = "RAG_DELETE_BLOCKED_ACTIVE_INDEXING"
export const RAG_INDEX_ALREADY_IN_PROGRESS          = "RAG_INDEX_ALREADY_IN_PROGRESS"
export const RAG_INDEX_ALREADY_COMPLETED            = "RAG_INDEX_ALREADY_COMPLETED"
export const RAG_INDEX_SKIPPED_BY_USER              = "RAG_INDEX_SKIPPED_BY_USER"
export const RAG_FILE_TYPE_NOT_INDEXABLE             = "RAG_FILE_TYPE_NOT_INDEXABLE"
export const RAG_IMAGE_INDEXING_DISABLED             = "RAG_IMAGE_INDEXING_DISABLED"
export const RAG_INDEX_FILE_TOO_LARGE                = "RAG_INDEX_FILE_TOO_LARGE"
export const RAG_EMBEDDING_TOKEN_LIMIT_EXCEEDED      = "RAG_EMBEDDING_TOKEN_LIMIT_EXCEEDED"
export const RAG_VECTOR_STORAGE_LIMIT_EXCEEDED       = "RAG_VECTOR_STORAGE_LIMIT_EXCEEDED"
export const RAG_DOC_EXISTS                          = "RAG_DOC_EXISTS"
```

**使用示例：**

```typescript
// KBFileRow 中的错误码映射
const QUOTA_LIMIT_ERROR_CODES = new Set([
  RAG_VECTOR_STORAGE_LIMIT_EXCEEDED,
  RAG_EMBEDDING_TOKEN_LIMIT_EXCEEDED,
  AGENT_CREDITS_INSUFFICIENT,
])

function getRagStatusLabelKey(file: KBFileRowFile): string | null {
  const errorCode = file.rag_error_code
  if (errorCode && QUOTA_LIMIT_ERROR_CODES.has(errorCode)) {
    return "sidebar.outputs.ragQuotaInsufficient"
  }
  if (errorCode === RAG_FILE_TYPE_NOT_INDEXABLE) {
    return "sidebar.outputs.ragFileTypeNotIndexable"
  }
  switch (file.rag_status) {
    case "indexed": return "sidebar.outputs.ragIndexed"
    case "pending": return "sidebar.outputs.ragPending"
    case "indexing": return "sidebar.outputs.ragIndexing"
    case "failed":  return "sidebar.outputs.ragFailed"
    case "skipped": return "sidebar.outputs.ragSkipped"
    default: return null
  }
}
```

---

## 五、KB Sidebar（知识库侧边栏）

### 5.1 整体结构

```
FilesTabContent
├── KBSourceSwitcher         ← self / referenced 切换
├── SearchBar                ← 搜索（Self 视图）
├── Upload / ManageBtn       ← 上传（Self）/ 管理引用（Referenced）
├── WikiKBSection            ← Wiki 行
└── AssetList               ← 虚拟滚动文件列表
    └── KBFileRow            ← 单文件行（含 RAG 状态点 + 操作按钮）
```

### 5.2 KBSourceSwitcher — 知识源切换

```typescript
// components/chat-sidebar/KBSourceSwitcher.tsx
export type KBSource = "self" | "referenced"

export function KBSourceSwitcher({ value, onChange }: KBSourceSwitcherProps) {
  // self  = 本项目自己的 KB 文件
  // referenced = 通过 project_references 拉取的其他项目 KB
  // 始终可切换：即使 zero referenced projects，也能进入 Referenced 视图管理引用
}
```

### 5.3 AssetList — 虚拟滚动文件列表

```typescript
// components/chat-sidebar/AssetList.tsx

// RAG 状态映射（AssetStatus → RagStatus）
function ragStatusForAsset(status?: AssetStatus): string | undefined {
  switch (status) {
    case AssetStatus.Completed: return "indexed"
    case AssetStatus.Pending:    return "pending"
    case AssetStatus.Indexing:   return "indexing"
    case AssetStatus.Skipped:    return "skipped"
    case AssetStatus.Failed:     return "failed"
    default:                     return undefined
  }
}
```

**关键特性：**
- 虚拟滚动（`visibleRows` 仅渲染视窗内行）
- 分组视图（Group by type）与扁平视图（All filter）
- 文件分类：`document`、`script-data`、`visualization`、`structure`
- 搜索高亮与滚动定位（`assetListFocusRequest`）

### 5.4 KBFileRow — 单文件行

```typescript
// components/chat-sidebar/KBFileRow.tsx

const RAG_STATUS_DOT: Record<string, { dot: string; pulse?: boolean }> = {
  completed: { dot: "bg-green-500" },
  indexed:   { dot: "bg-green-500" },
  pending:   { dot: "bg-yellow-500", pulse: true },
  indexing:  { dot: "bg-yellow-300", pulse: true },
  skipped:   { dot: "bg-muted-foreground/25" },
  failed:    { dot: "bg-red-500" },
}
```

**交互行为：**
- 点击行体 → 预览文件
- `@` 按钮 → 引用到 Chat（drag + drop）
- `...` 菜单 → 下载 / 删除（Self 视图）
- ReadOnly 模式 → 隐藏删除，仅预览/下载（Referenced 视图）

---

## 六、流式事件（Chat Stream）中的 RAG 展示

### 6.1 RagSearchImagesBlock — RAG 图片检索结果

```tsx
// components/stream-events/rag-search-images-block.tsx
export function RagSearchImagesBlock({
  data,          // RagSearchImagesData
  title,         // 可自定义标题
  defaultExpanded = false,
  variant = "hits",  // "hits" | "referenced"
}) {
  // variant = "hits":   来自 rag_search 工具调用，蓝色主题
  // variant = "referenced": 来自 ask_library 采纳来源，绿色主题
  // 图片卡片显示：缩略图、文件名、相似度 Badge
  // 操作：预览（点击图片）、下载（Download 按钮）
}
```

**核心渲染逻辑（简化）：**

```tsx
// shared/stream-events/rag-search-images.tsx:271–470
export function SharedRagSearchImagesBase({ data, variant, ... }) {
  // 1. 解析图片 URL → resolvedUrl（拼接 backendUrl）
  // 2. dedupeReferencedImages: 去重（referenced variant 专用）
  // 3. PDF 图片特殊处理：提取 documentPage → 显示"文件名 — Page N"
  // 4. 网格布局：1 张 1 列，2 张 2 列，≥3 张 3 列
  // 5. 相似度 Badge: formatSimilarity(value, template) → "87% match"
  // 6. 点击图片 → setPreviewIndex（弹窗预览）
  // 7. 点击 Download → 创建 <a> 标签触发下载
}
```

### 6.2 AskLibraryAdoptedSourcesBlock — ask_library 采纳来源

```tsx
// components/stream-events/ask-library-adopted-sources.tsx
export function AskLibraryAdoptedSourcesBlock({
  pages,       // ReferencedSourcePage[]  — Wiki 页面
  documents,   // ReferencedSourceDocument[] — 文件
  onWikiPageLink,
  onAssetLink,
  t,
}) {
  // 两个折叠区块：
  // 1. "Related Pages" (Wiki) — 可点击跳转到对应 Wiki 版本
  // 2. "Related Documents" (文件) — 可点击打开文件预览
  // 跨项目来源在底部显示 project_name + version label
}
```

### 6.3 ReferencedEvidenceBlock — 组合展示

```tsx
// components/stream-events/referenced-evidence-block.tsx
export function ReferencedEvidenceBlock({ data, onWikiPageLink, onAssetLink, t }) {
  // 组合 AskLibraryAdoptedSourcesBlock + RagSearchImagesBlock
  // 用于 stream event type = "referenced_evidence"
  // 同时展示：Wiki 页面 + 文档文件 + 图片检索结果
}
```

### 6.4 Stream Event 类型映射

```typescript
// components/stream-events/tool-display.ts
const TOOL_DISPLAY: Record<string, { label: string; color: string }> = {
  rag_search:        { label: "RAG Search",        color: "amber" },
  ask_library:       { label: "Ask Library",        color: "blue" },
  rag_inspect_image: { label: "Inspect Image (RAG)", color: "amber" },
  // ... 其他工具
}
```

---

## 七、Chat Commands — Foundry 场景

```typescript
// lib/foundry-utils.ts
export const FOUNDRY_PREFIX = "Based on the user's requested deliverable type "
const FOUNDRY_SUFFIX = ", call rag_search from multiple dimensions"
const FOUNDRY_TYPES = new Set(["pptx", "poster", "html", "csv", "markdown"])

// 检测 Foundry 消息，提取交付物类型
export function parseFoundryMessage(content: string) {
  if (!content.startsWith(FOUNDRY_PREFIX)) return null
  // 解析 → { request: string, outputType: "pptx" | "poster" | ... }
}
```

**Foundry 构造的多维度检索提示词（简化）：**

```typescript
// components/chat-commands.tsx:308
return `Based on the user's requested deliverable type ${userRequest},
call rag_search from multiple dimensions — fuse each dimension
with the topic into a natural query:
1. "${topic} ${aspect1}"
2. "${topic} ${aspect2}"
...`
```

---

## 八、Python RAG Skill：rag-task-investigator

**路径：** `skills/rag-task-investigator/`

### 8.1 脚本结构

```
skills/rag-task-investigator/
├── SKILL.md
├── scripts/
│   ├── build_retrieval_plan.py      ← 按交付物类型生成检索计划
│   ├── rag_processing.py            ← 核心处理：tokenize / score / dedupe
│   ├── postprocess_rag_results.py   ← 后处理：enrich + TODO 列表
│   └── validate_mock_pipeline.py    ← 端到端 mock 验证
└── assets/
    └── mock-rag-results.json        ← 测试用 mock 数据
```

### 8.2 build_retrieval_plan.py — 检索维度规划

```python
#!/usr/bin/env python3
"""按交付物类型生成多维度检索计划"""

CORE_COMMON_ASPECTS = [
    "background and motivation",
    "methods or workflow",
    "results and conclusions",
    "metrics and comparisons",
]

DELIVERABLE_ASPECTS = {
    "pptx": ["summary claim", "contrast or benchmark", "chart-ready metric", ...],
    "png":  ["study objective", "concise method", "strongest quantitative result", ...],
    "html": ["panel or page candidate", "structured dataset", "timeline or workflow", ...],
    "csv":  ["candidate rows or entities", "field names and definitions", ...],
    "docx": ["abstract-worthy result", "introduction background", ...],
}

def build_aspects(topic, deliverable_type, constraints, max_aspects=6):
    # 1. 取核心通用维度
    # 2. 叠加交付物特定维度
    # 3. 有约束则追加 "hard constraints and must-cover requirements"
    # 4. 输出 priority / label / query 三元组
    ...

# 使用示例
# $ python build_retrieval_plan.py --project-id myproj --topic "transformer attention" --deliverable-type pptx
```

### 8.3 rag_processing.py — 核心处理

```python
#!/usr/bin/env python3
"""RAG 结果处理核心：tokenize / score / dedupe / enrich"""

import re

TASK_PATH_RE = re.compile(r"^(/workspace/(?:[^/]+/)?tasks/[^/]+)/task_conclusion\.md$")

def tokenize(text: str) -> set[str]:
    """混合中英文分词，用于后续 overlap scoring"""
    lowered = text.lower()
    terms = set(WORD_RE.findall(lowered))  # 英文词
    terms.update(CHINESE_RE.findall(text))  # 中文词
    return terms

def overlap_score(query_terms: set[str], text: str) -> int:
    """计算 query_terms 在 text 中出现次数"""
    score = sum(1 for t in query_terms if t in text.lower() or t in text)
    return score

def sort_task_chunks(query_terms, task_chunks):
    """按 (score, overlap) 倒序排列"""
    return sorted(task_chunks, key=lambda i: (float(i.get("score", 0)), overlap_score(query_terms, i.get("chunk", ""))), reverse=True)

def dedupe_file_chunks(file_chunks):
    """按 (path, chunk_text) 去重"""
    ...

def enrich_task_chunk(query_terms, item, workspace_root, evidence_limit=5):
    """从 task_conclusion.md 中提取 key_files，再读取对应文件证据"""
    # 1. 解析 task_conclusion.md 中的 "Key files: a.py, b.csv"
    # 2. 读取这些文件中与 query_terms overlap 最高的行
    # 3. 将证据追加到 chunk → enriched["chunk"] + "evidence1: ..."
    ...

def process_results(query, results, top_tasks=10, workspace_root=None, enrich_tasks=False):
    """主流程：过滤 → 排序 → 选 Top Tasks → 可选 enrich → 生成 TODO"""
    query_terms = tokenize(query)
    task_chunks = [i for i in results if i["path"].endswith("/task_conclusion.md")]
    file_chunks = [i for i in results if "/files/" in i["path"]]
    ranked = sort_task_chunks(query_terms, task_chunks)
    todo_items = build_todo_entries(ranked)[:top_tasks]
    ...
    return { "query": query, "todo_items": todo_items, "task_conclusion_chunks": ..., "file_chunks": ... }
```

### 8.4 postprocess_rag_results.py — 后处理入口

```python
#!/usr/bin/env python3
"""RAG 结果后处理 CLI 入口"""

from rag_processing import process_results

def main():
    # 使用示例：
    # $ python postprocess_rag_results.py \
    #     --query "transformer attention mechanism" \
    #     --results /workspace/rag_results.json \
    #     --todo-path /workspace/TODO_list.md \
    #     --workspace-root /actual/workspace/path \
    #     --enrich-task-chunks
    processed = process_results(
        query=args.query,
        results=load_results(Path(args.results)),
        top_tasks=args.top_tasks,
        workspace_root=Path(args.workspace_root),
        enrich_tasks=args.enrich_task_chunks,
        evidence_limit=args.evidence_limit,
        todo_path=Path(args.todo_path),
    )
    print(json.dumps(processed, ensure_ascii=False, indent=2))
```

---

## 九、Wiki 系统

### 9.1 WikiKBSection — Sidebar Wiki 行

```tsx
// components/chat-sidebar/WikiKBSection.tsx

export type WikiKBSectionMode = "self" | "referenced"

// "self" 模式：
//  - 无 Wiki → Sparkles 按钮触发生成
//  - 有 Wiki → 显示版本号 + 更新时间
//  - 支持 tier 权限控制（canManageWikiForTierInfo）

// "referenced" 模式：
//  - 只读，无生成按钮
//  - 可点击行体打开 wiki pane
//  - @ 按钮 → 将 Wiki 引用添加到 Chat
```

**Wiki 行名逻辑：**

```
有 Wiki     → "v3 · 2026/07/02 14:30"
无 Wiki + 生成中 → "生成中…"
无 Wiki + 排队中 → "排队中…"
无 Wiki + 跳过   → "跳过：{reason}"  (i18n key: sidebar.wiki.skipReason.*)
无 Wiki + 其他   → "未生成"
```

### 9.2 Wiki 刷新状态轮询

```tsx
// FilesTabContent.tsx:74–96
const wikiStateQuery = useQuery({
  queryKey: ["wiki", projectId, "state"],
  queryFn: () => fetchWikiState(projectId),
  staleTime: 5000,
  refetchInterval(query) {
    // 有 refreshEntry 时 2s 轮询，否则 30s
    return getWikiStateRefetchInterval({ hasRefreshEntry, lastRefreshRunStatus, wikiStatus })
  },
  refetchIntervalInBackground: true,
})
```

### 9.3 Wiki 拖拽引用

```typescript
// lib/wiki-ref-drag.ts
export const WIKI_REFERENCE_DRAG_MIME = "application/x-sciclaw-wiki-ref"

export interface WikiRefDragPayload {
  project_id: string;
  version_id: string;
  title: string;
  project_name: string;
}

// serializeWikiRef / parseWikiRef: JSON.stringify / JSON.parse 封装
```

---

## 十、Promote to KB — 输出文件推广

```tsx
// components/chat-sidebar/PromoteToKBDialog.tsx

// 流程：
// 1. 用户点击 OutputFile 的 "Promote to KB" 按钮
// 2. POST /api/v1/sessions/{sessionId}/tasks/{taskNumber}/promote-to-rag
//    { file_path, overwrite }
// 3. 409 RAG_DOC_EXISTS → 弹窗提示是否覆盖（overwrite checkbox）
// 4. 成功 → toast "已加入知识库" + onPromoted() 刷新列表
// 5. 跳过  → toast "已跳过：{reason}"（如文件类型不支持索引）
```

---

## 十一、配额与使用量

### 11.1 UsagePanel 中的 RAG 展示

```tsx
// components/usage-panel.tsx
// 从 TierUsageInfo 中读取：
rag_embedding_tokens_used     // 已用 embedding token
rag_embedding_token_limit     // 上限
rag_vector_points_used        // 已用向量点数
rag_vector_point_limit        // 上限
```

### 11.2 Qdrant 用量展示

```typescript
// lib/usage-api.ts:33–37
interface QdrantUsage {
  rag_asset_count: number      // 已索引文件数
  memory_entry_count: number   // 记忆条目数
  total_points: number         // Qdrant 总点数
}
```

---

## 十二、跨项目引用知识（Referenced KB）

### 12.1 API

```typescript
// lib/projects-api.ts:1465–1501
export async function fetchReferencedFiles(projectId: string): Promise<BackendReferencedGroup[]> {
  const res = await authedFetch(`/api/v1/projects/${projectId}/referenced-files`)
  // → [{ project_id, project_name, wiki: {...}, files: [...] }]
}

interface BackendReferencedFile {
  id: string
  name: string
  path: string
  browser_path: string
  size: number
  content_type?: string | null
  rag_status?: string | null    // ← 目标项目的 RAG 状态
}
```

### 12.2 ReferencedKBList 组件

```tsx
// components/chat-sidebar/ReferencedKBList.tsx
// - 按 project 分组展示
// - 每 project 可展开看 wiki + 文件
// - 支持搜索过滤
// - 文件行 readOnly：可预览/下载，不可删除/添加引用
```

### 12.3 跨项目图片拖拽

```typescript
// lib/hooks/use-asset-drag-active.ts
// REFERENCE_DRAG_MIME 用于检测跨项目文件是否被拖入 Chat
```

---

## 十三、样板代码

### 13.1 在组件中读取 RAG 状态

```tsx
import { useQuery } from "@tanstack/react-query"
import { RAG_EMBEDDING_TOKEN_LIMIT_EXCEEDED } from "@/lib/error-codes"

// 获取项目文件列表（含 rag_status）
const { data: assets } = useQuery({
  queryKey: ["project-assets", projectId],
  queryFn: () => authedFetch(`/api/v1/projects/${projectId}/assets`).then(r => r.json()),
})

// 过滤已索引文件
const indexedFiles = assets?.filter(a => a.rag_status === "indexed")

// 检查文件是否因配额不足失败
const isQuotaError = (file) =>
  file.rag_error_code === RAG_EMBEDDING_TOKEN_LIMIT_EXCEEDED ||
  file.rag_error_code === RAG_VECTOR_STORAGE_LIMIT_EXCEEDED
```

### 13.2 消费 stream event 中的 RAG 数据

```tsx
import type { ReferencedEvidenceRecord, ReferencedEvidenceData } from "@/types/stream-events"

function handleStreamEvent(event: StreamEventRecord) {
  switch (event.type) {
    case "referenced_images": {
      const { images, count } = event.data as ReferencedEvidenceData
      // images 可以直接传给 RagSearchImagesBlock
      break
    }
    case "referenced_sources": {
      const { pages, documents } = event.data as ReferencedEvidenceData
      // 传给 AskLibraryAdoptedSourcesBlock
      break
    }
    case "referenced_evidence": {
      const data = event.data as ReferencedEvidenceData
      // 组合展示：pages + documents + images
      break
    }
  }
}
```

### 13.3 查询 RAG 配额

```typescript
import { fetchTierInfo, fetchUsageStats } from "@/lib/tier-api"

// 查询配额上限
const { limits } = await fetchTierInfo()
const ragLimit = limits.rag?.quota
// → { embedding_token_limit: 1000000, vector_point_limit: 50000 }

// 查询实际用量
const { usage } = await fetchTierInfo()
const tokensUsed = usage.rag_embedding_tokens_used        // e.g. 234_567
const pointsUsed = usage.rag_vector_points_used             // e.g. 12345
const tokenPct   = tokensUsed / (ragLimit?.embedding_token_limit ?? 1) * 100
```

### 13.4 推广输出文件到 KB

```typescript
import { authedFetch } from "@/lib/api-client"

async function promoteToKB(sessionId: string, taskNumber: number, filePath: string) {
  const res = await authedFetch(
    `/api/v1/sessions/${sessionId}/tasks/${taskNumber}/promote-to-rag`,
    { method: "POST", body: JSON.stringify({ file_path: filePath, overwrite: false }) }
  )
  if (res.status === 409) {
    const body = await res.json()
    if (body.code === "RAG_DOC_EXISTS") {
      // 提示用户是否覆盖
      return { needsOverwrite: true }
    }
  }
  return res.json()
}
```

### 13.5 Foundry 场景自动构造 rag_search 提示词

```typescript
import { parseFoundryMessage, FOUNDRY_TYPES } from "@/lib/foundry-utils"
import { buildFoundryMessage } from "@/components/chat-commands"

// 检测 Foundry 消息
const foundry = parseFoundryMessage(userMessage)
if (foundry) {
  // 生成多维度检索提示词
  const enrichedPrompt = buildFoundryMessage(userRequest, outputType)
  // → "Based on the user's requested deliverable type PPT, call rag_search...
  //    1. \"transformer attention mechanism background\"
  //    2. \"transformer attention mechanism results\" ..."
}
```

### 13.6 使用 rag-task-investigator Python 脚本

```bash
# 步骤1：构建检索计划
python3 skills/rag-task-investigator/scripts/build_retrieval_plan.py \
  --project-id myproj \
  --topic "transformer attention" \
  --deliverable-type pptx \
  --constraint "must cite original BERT paper"

# 步骤2：执行 rag_search（后端执行，此处省略）
# → 输出 /workspace/rag_results.json

# 步骤3：后处理 + 生成 TODO
python3 skills/rag-task-investigator/scripts/postprocess_rag_results.py \
  --query "transformer attention mechanism" \
  --results /workspace/rag_results.json \
  --todo-path /workspace/TODO_list.md \
  --workspace-root /actual/workspace/path \
  --enrich-task-chunks \
  --evidence-limit 5

# 输出：
# {
#   "query": "transformer attention mechanism",
#   "todo_items": [
#     { "task_id": "abc123", "task_root": "/workspace/.../tasks/abc123",
#       "task_conclusion": "/workspace/.../tasks/abc123/task_conclusion.md",
#       "reason": "...", "score": 0.87 }
#   ],
#   "task_conclusion_chunks": [...],
#   "file_chunks": [...]
# }
```

### 13.7 虚拟化文件列表（简化的 AssetList）

```tsx
const ASSET_FILE_ROW_HEIGHT = 36
const OVERSCAN = 8

function VirtualizedAssetList({ assets }: { assets: Asset[] }) {
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight] = useState(640)

  const visibleRows = useMemo(() => {
    const start = Math.max(0, scrollTop - OVERSCAN * ASSET_FILE_ROW_HEIGHT)
    const end = scrollTop + viewportHeight + OVERSCAN * ASSET_FILE_ROW_HEIGHT
    return assets
      .map((asset, i) => ({ asset, offset: i * ASSET_FILE_ROW_HEIGHT }))
      .filter(r => r.offset >= start && r.offset <= end)
  }, [assets, scrollTop, viewportHeight])

  return (
    <div style={{ height: viewportHeight, overflowY: "auto" }} onScroll={e => setScrollTop(e.currentTarget.scrollTop)}>
      <div style={{ height: assets.length * ASSET_FILE_ROW_HEIGHT, position: "relative" }}>
        {visibleRows.map(({ asset, offset }) => (
          <div key={asset.id} style={{ position: "absolute", top: offset, height: ASSET_FILE_ROW_HEIGHT, left: 0, right: 0 }}>
            <KBFileRow file={asset} ... />
          </div>
        ))}
      </div>
    </div>
  )
}
```

### 13.8 PDF 图片标题提取

```typescript
// shared/stream-events/rag-search-images.tsx:173–221

function getPdfDerivedImagePageNumber(image): number | null {
  if (image.documentFileType?.toLowerCase() !== "pdf") return null
  // 优先用 documentPage
  if (image.documentPage && image.documentPage > 0) return image.documentPage
  // 降级：从 browserFilePath 解析 "page-N-image-M"
  const match = image.browserFilePath.match(/page-(\d+)-image-\d+/i)
  return match ? Number(match[1]) : null
}

function getPdfDerivedImageDisplayName(image, formatName): string | null {
  const sourceFile = image.sourceFile?.trim()
  const page = getPdfDerivedImagePageNumber(image)
  if (sourceFile && page) return formatName(sourceFile.replace(/\.[^.]+$/, ""), page)
  return null
}
// → "paper.pdf — Page 3"  （formatName 支持 i18n 插值）
```

---

## 十四、RAG 状态机

```
         ┌──────────────┐
         │  上传文件     │
         └──────┬───────┘
                ▼
         ┌──────────────┐  用户跳过  ┌──────────────┐
         │   pending    │──────────▶│   skipped    │
         └──────┬───────┘           └──────────────┘
                │ 索引开始
                ▼
         ┌──────────────┐  成功    ┌──────────────┐  失败   ┌──────────────┐
         │  indexing    │─────────▶│   indexed    │◀───────▶│   failed     │
         └──────────────┘          └──────────────┘         └──────────────┘

/* 非索引状态 */
not_indexed  ——  文件未加入 KB（如 board notes / session outputs 未推广）
```

---

## 十五、关键文件索引

| 路径 | 角色 |
|------|------|
| `lib/types/outputs-tree.ts` | 核心类型：RagStatus、OutputFile、OutputTask |
| `lib/error-codes.ts` | 10 个 RAG 错误码常量 |
| `lib/usage-api.ts` | QdrantUsage 用量类型 |
| `lib/tier-api.ts` | TierLimitsInfo / TierUsageInfo 的 RAG 字段 |
| `lib/projects-api.ts` | fetchReferencedFiles、KB add API |
| `types/stream-events.ts` | RagSearchImageItem、ReferencedEvidenceData 等 |
| `components/stream-events/rag-search-images-block.tsx` | RAG 图片块（SciClaw 定制） |
| `shared/stream-events/rag-search-images.tsx` | RAG 图片共享组件 |
| `components/stream-events/ask-library-adopted-sources.tsx` | ask_library 采纳来源块 |
| `components/stream-events/referenced-evidence-block.tsx` | 组合证据块 |
| `components/chat-sidebar/FilesTabContent.tsx` | KB 侧边栏主容器 |
| `components/chat-sidebar/AssetList.tsx` | 虚拟滚动文件列表 |
| `components/chat-sidebar/KBFileRow.tsx` | 文件行（含 RAG 状态点） |
| `components/chat-sidebar/WikiKBSection.tsx` | Wiki 行（生成 / 刷新状态） |
| `components/chat-sidebar/PromoteToKBDialog.tsx` | 推广到 KB 弹窗 |
| `components/chat-sidebar/KBSourceSwitcher.tsx` | self / referenced 切换 |
| `components/chat-sidebar/ReferencedKBList.tsx` | 跨项目引用文件列表 |
| `components/chat-commands.tsx` | Foundry 场景 prompt 构造 |
| `lib/foundry-utils.ts` | FOUNDRY_SUFFIX / parseFoundryMessage |
| `components/usage-panel.tsx` | RAG 用量展示 |
| `lib/wiki-ref-drag.ts` | Wiki 引用拖拽 MIME 定义 |
| `lib/wiki-tier.ts` | Wiki tier 权限控制 |
| `skills/rag-task-investigator/scripts/build_retrieval_plan.py` | 检索维度规划 |
| `skills/rag-task-investigator/scripts/rag_processing.py` | 核心处理脚本 |
| `skills/rag-task-investigator/scripts/postprocess_rag_results.py` | 后处理 CLI 入口 |
| `DOCS/components/stream-events/ask-library-adopted-sources.md` | AskLibraryAdoptedSourcesBlock 文档 |
| `DOCS/shared/stream-events/rag-search-images.md` | RAG 图片流事件文档 |
