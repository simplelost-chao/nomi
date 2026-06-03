# 管理后台升级设计文档

## 概述

升级现有 `admin_panel.html` 单页面管理后台，增加角色详情页、图片/语音版本管理、记忆展示，以及从网络构建虚拟角色的新创建模式。

## 现状

- `backend/app/admin_panel.html`：单文件 HTML 页面，3 个 tab（角色列表、创建角色、生成图片）
- `backend/app/api/admin.py`：后端 API，管理角色和图片生成（Gemini Imagen）
- 图片存储在 `desktop/assets/characters/{name}/{state}.png`，每次生成直接覆盖
- 语音存储在 `desktop/assets/voices/{name}/`，配置在 `Robot.voice_profile` JSONB 字段
- 记忆存储在 `yearly_memories` 表，按年龄和批次组织

## 设计

### 1. 页面结构改造

从 tab 切换改为列表 → 详情的导航模式：

**角色列表页（首页）**
- 保持现有卡片网格布局
- 每张卡片显示：头像、名字、语音状态、表情完成度
- 点击卡片进入角色详情页
- 顶部保留"创建角色"入口（支持两种模式）

**角色详情页**
- 返回按钮 + 角色名标题
- 分区展示：
  - **基本信息区**：名字、性格、背景故事、系统提示词（可编辑）
  - **表情图片区**：7 个状态的图片网格，每个状态可展开查看版本历史
  - **语音区**：当前语音配置、试听、版本历史
  - **记忆区**：按年龄排列的时间线，可展开查看每条记忆的内容

### 2. 版本管理系统

#### 数据库：新增 `asset_versions` 表

```sql
CREATE TABLE asset_versions (
    id UUID PRIMARY KEY,
    robot_id UUID REFERENCES robots(id),
    asset_type VARCHAR(20) NOT NULL,      -- 'image' | 'voice_config'
    asset_key VARCHAR(100) NOT NULL,       -- 图片: state 名 (如 'idle')；语音: 'voice_profile'
    version_number INTEGER NOT NULL,       -- 自增版本号
    file_path VARCHAR(500),                -- 文件相对路径
    metadata JSONB,                        -- 生成参数、prompt 等
    is_current BOOLEAN DEFAULT FALSE,      -- 当前使用的版本
    is_starred BOOLEAN DEFAULT FALSE,      -- 用户收藏标记
    created_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(robot_id, asset_type, asset_key, version_number)
);
```

#### 文件存储结构

```
desktop/assets/characters/{name}/
├── idle.png                              # 当前使用的版本（软链接或复制）
├── versions/
│   ├── idle_v1_20260527_143000.png
│   ├── idle_v2_20260527_150000.png
│   └── happy_v1_20260527_143500.png
├── prompts.json
└── reference.png

desktop/assets/voices/{name}/
├── voice1.wav                            # 当前使用
├── versions/
│   ├── voice_config_v1.json              # 语音配置快照
│   └── voice_config_v2.json
└── voice_long.wav
```

#### 版本管理逻辑

- **自动保存**：每次生成图片时，先将当前图片移入 `versions/` 并记录到 `asset_versions` 表，再保存新图片
- **语音版本**：每次语音配置变更时，将当前 `voice_profile` JSONB 快照保存为版本
- **切换版本**：将选中版本的文件复制为当前文件（如 `idle.png`），更新 `is_current` 标记
- **收藏**：用户可以给满意的版本打星标，方便找回

#### 新增 API 端点

```
GET    /api/admin/characters/{id}/versions?asset_type=image&asset_key=idle
       → 获取某个资源的版本列表

POST   /api/admin/characters/{id}/versions/{version_id}/activate
       → 切换到指定版本（设为当前使用）

POST   /api/admin/characters/{id}/versions/{version_id}/star
       → 标记/取消收藏

DELETE /api/admin/characters/{id}/versions/{version_id}
       → 删除某个版本

GET    /api/admin/characters/{id}/versions/{version_id}/file
       → 获取某个版本的图片文件
```

### 3. 记忆展示

在角色详情页中展示 `yearly_memories` 表的数据：

- 按年龄分组，时间线样式展示
- 每条记忆显示：标题、年龄、记忆类型（vivid/fragment/feeling）、重要程度条
- 点击展开查看完整内容、情感核心、符号标签
- 记忆强度用透明度或颜色深浅表示（强度高的更醒目）

#### 新增 API 端点

```
GET /api/admin/characters/{id}/memories
    → 获取角色的所有记忆，按年龄排序
```

### 4. 从网络构建角色（新创建模式）

#### 流程

1. 用户输入角色名（如"芙莉莲"）和来源作品名（如"葬送的芙莉莲"）
2. 后端调用 `web_search` 搜索角色信息：
   - 角色基本设定、外貌、性格
   - 角色经历、关键事件、人物关系
   - 角色语录、说话风格
3. LLM 整理搜索结果，生成结构化的角色数据：
   - 性格、背景故事、说话风格（与现有 Robot 模型字段对应）
   - 按时间线整理的记忆列表（与现有 YearlyMemory 模型对应）
   - 系统提示词
4. 创建 Robot 记录 + 批量创建 YearlyMemory 记录
5. 进入角色详情页，用户可审核和调整

#### 新增 API 端点

```
POST /api/admin/characters/create-from-web
     Body: { "character_name": "芙莉莲", "source": "葬送的芙莉莲" }
     → 异步任务，返回 job_id

GET  /api/admin/characters/create-from-web/status/{job_id}
     → 查询创建进度（搜索中 → 整理中 → 生成记忆中 → 完成）
```

#### 搜索策略

使用现有 `web_search.py` 服务，分多次搜索：
- `"{角色名}" 角色设定 性格`
- `"{角色名}" 经历 故事线 时间线`
- `"{角色名}" 人物关系`
- `"{角色名}" 语录 说话方式`

将搜索结果合并后交给 LLM（Claude）生成结构化数据，复用现有的记忆格式（`build_batch_memories_prompt` 的变体）。

### 5. 现有功能保留

- 从照片创建角色的流程不变
- 图片生成（Gemini Imagen）流程不变，只是增加了版本保存的步骤
- 去除背景功能不变
- 上传参考图/参考语音功能不变

## 技术决策

- **保持单文件 HTML**：不引入构建工具，继续用原生 JS，适合管理工具的简单性
- **版本文件存储在本地文件系统**：与现有资源存储方式一致
- **版本元数据存数据库**：便于查询、排序、标记
- **异步任务用内存 dict 追踪**：与现有 `_creation_jobs` 模式一致

## 不在范围内

- 登录认证（后续再加）
- 记忆编辑/删除（只展示）
- 角色删除确认流程
- 移动端适配
