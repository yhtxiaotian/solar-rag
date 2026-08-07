# 光伏智库

面向分布式光伏场景的可追溯 RAG 网站。访客可以匿名提问，系统只使用管理员收录的政策、标准、设计资料和设备手册作答，并展示文件、页码/章节与原文证据。

## 已实现

- PDF、DOCX、XLSX、TXT、Markdown、HTML 上传与显式清单导入
- 文本 PDF 解析及扫描页中文 CPU OCR
- SHA-256 去重、文号版本管理、现行资料优先、资料归档
- pgvector 向量检索 + 中文关键词检索 + RRF 融合 + 模型重排
- 引用编号后端校验、证据不足拒答、SSE 流式输出
- 单管理员安全 Cookie、公开/仅管理员资料、匿名限流与每日预算
- Celery 后台解析、Docker Compose 单服务器部署、每日七日滚动备份
- 访客问答页、引用原文侧栏、反馈入口和资料管理后台

## 快速启动

1. 将 `.env.example` 复制为 `.env`。
2. 设置数据库密码、模型服务地址、模型名称、密钥、会话密钥和限流盐值。
3. 生成管理员密码的 Argon2 哈希并填入 `ADMIN_PASSWORD_HASH`：

   ```powershell
   docker compose run --rm --no-deps api python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('换成你的强密码'))"
   ```

4. 启动服务：

   ```powershell
   docker compose up --build -d
   ```

5. 本机访问 `http://localhost`。管理入口为 `/admin`。

AI 服务需要兼容：

- `POST {AI_BASE_URL}/chat/completions`
- `POST {AI_BASE_URL}/embeddings`

`EMBEDDING_DIMENSION` 必须与模型输出一致。首次建库后如更换 Embedding 模型或维度，应清空并重建文本块向量及 HNSW 索引，不能混用不同维度。

若只想在没有模型密钥时演示完整流程，可临时设置 `AI_OFFLINE_MODE=true`。离线模式使用确定性哈希向量和证据摘录，不代表正式回答质量。

## 知识清单

仓库根目录的 `knowledge-sources.yaml` 是可扩展资料清单。管理员后台导入时会先预览校验，再确认创建记录。只有标题而没有链接的条目会进入 `pending_source`，之后上传对应文件即可继续处理。

当前文件内含 6 条首批候选资料。上线前仍应由管理员在导入预览中复核官方链接、发布日期和有效状态；你后续提供的文件名可以直接追加为 `pending_source`。

推荐字段：

```yaml
sources:
  - title: 示例资料
    category: 政策法规
    issuer: 发布机构
    document_no: 文件编号
    region: 中国
    version: 2025年版
    published_at: 2025-01-01
    effective_at: 2025-02-01
    expires_at:
    validity_status: active
    supersedes:
    source_url: https://example.com/document.pdf
    local_file_name:
    tags: [分布式光伏, 并网]
    notes:
```

清单只会在管理员明确导入时下载，不包含定时爬虫。远程地址必须使用 HTTPS，并会拒绝内网、保留地址、危险重定向和超过大小限制的文件。请只收录有合法使用权的标准全文；仅公开元数据的标准页面不等于取得标准全文授权。

## 本地开发

前端：

```powershell
npm install
npm run dev
```

后端：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
$env:PYTHONPATH="backend"
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

本地需要 PostgreSQL/pgvector 与 Redis。也可只启动依赖：

```powershell
docker compose up -d postgres redis
```

## 测试与评测

```powershell
npm test
.venv\Scripts\python -m pytest backend\tests
$env:PYTHONPATH="backend"
.venv\Scripts\python backend\evals\run_evaluation.py
```

评测集位于 `backend/evals/questions.yaml`，包含 40 道可回答题和 10 道拒答题。导入正式知识清单后，应由光伏专业人员补充或修订标准答案。验收阈值：Top-5 文档召回率不低于 85%，开启答案评测后拒答率不低于 90%，且引用必须映射到真实文本块。

## 生产部署注意事项

- 将 `SITE_ADDRESS` 设置为真实域名，Caddy 会自动申请和续期 HTTPS 证书。
- HTTPS 环境必须设置 `COOKIE_SECURE=true`。
- 不要把 `.env`、数据库备份或知识原文件提交到版本库。
- `backup` 服务每天备份数据库和知识文件，并清除七天前备份；应另行将备份卷同步到异机存储。
- 默认访客每 IP 每小时 20 次，全站每日 500 次或 200 万 token，可在 `.env` 调整。
- 服务不提供电气安全或投资决策担保，关键设计、并网和施工结论必须复核引用原文。
