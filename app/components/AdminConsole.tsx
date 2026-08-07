"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, errorMessage } from "../lib/api";

type DocumentItem = {
  id: string;
  title: string;
  category: string;
  issuer?: string;
  document_no?: string;
  region: string;
  version?: string;
  published_at?: string;
  effective_at?: string;
  expires_at?: string;
  validity_status: string;
  supersedes?: string;
  source_url?: string;
  local_file_name?: string;
  tags: string[];
  notes?: string;
  visibility: "public" | "admin_only";
  ingest_status: string;
  chunk_count: number;
  error_message?: string;
  updated_at: string;
};

type Preview = { total: number; valid: number; invalid: number; items: Array<{ row: number; valid: boolean; action: string; entry: { title?: string }; errors: string[] }> };
type ParsePreview = { chunks: Array<{ ordinal: number; page_start?: number; page_end?: number; section?: string; content: string }> };

const statusText: Record<string, string> = {
  pending_source: "待补充来源", queued: "等待处理", downloading: "正在下载", parsing: "正在解析",
  indexing: "正在索引", ready: "可检索", failed: "处理失败", archived: "已归档",
};

export function AdminConsole() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploading, setUploading] = useState(false);
  const [manifestFile, setManifestFile] = useState<File>();
  const [manifestPreview, setManifestPreview] = useState<Preview>();
  const [selected, setSelected] = useState<DocumentItem>();
  const [parsePreview, setParsePreview] = useState<ParsePreview>();
  const [panelLoading, setPanelLoading] = useState(false);

  const loadDocuments = useCallback(async () => {
    const response = await apiFetch("/api/v1/admin/documents");
    if (response.status === 401) { setAuthenticated(false); return; }
    if (!response.ok) throw new Error(await errorMessage(response));
    setDocuments(await response.json());
    setAuthenticated(true);
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadDocuments().catch((caught) => setError(String(caught)));
    }, 0);
    return () => clearTimeout(timer);
  }, [loadDocuments]);
  useEffect(() => {
    if (!authenticated) return;
    const timer = setInterval(() => void loadDocuments(), 5000);
    return () => clearInterval(timer);
  }, [authenticated, loadDocuments]);

  async function login(event: FormEvent) {
    event.preventDefault(); setError("");
    const response = await apiFetch("/api/v1/admin/login", { method: "POST", body: JSON.stringify({ username, password }) });
    if (!response.ok) { setError(await errorMessage(response)); return; }
    setPassword(""); setAuthenticated(true); await loadDocuments();
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setNotice(""); setUploading(true);
    const form = new FormData(event.currentTarget);
    const file = form.get("file") as File;
    const metadata = {
      title: form.get("title"), category: form.get("category") || "未分类", issuer: form.get("issuer") || null,
      document_no: form.get("document_no") || null, version: form.get("version") || null,
      validity_status: form.get("validity_status"), visibility: form.get("visibility"), region: "中国", tags: [],
    };
    const payload = new FormData(); payload.append("file", file); payload.append("metadata_json", JSON.stringify(metadata));
    const response = await apiFetch("/api/v1/admin/documents/upload", { method: "POST", body: payload });
    setUploading(false);
    if (!response.ok) { setError(await errorMessage(response)); return; }
    event.currentTarget.reset(); setNotice("资料已进入处理队列"); await loadDocuments();
  }

  async function previewManifest() {
    if (!manifestFile) return;
    const body = new FormData(); body.append("file", manifestFile);
    const response = await apiFetch("/api/v1/admin/manifests/import?preview=true", { method: "POST", body });
    if (!response.ok) { setError(await errorMessage(response)); return; }
    setManifestPreview(await response.json());
  }

  async function commitManifest() {
    if (!manifestFile || manifestPreview?.invalid) return;
    const body = new FormData(); body.append("file", manifestFile);
    const response = await apiFetch("/api/v1/admin/manifests/import?preview=false", { method: "POST", body });
    if (!response.ok) { setError(await errorMessage(response)); return; }
    const result = await response.json(); setNotice(`已新增 ${result.created} 条资料`); setManifestPreview(undefined); setManifestFile(undefined); await loadDocuments();
  }

  async function action(id: string, verb: "reindex" | "archive") {
    const response = await apiFetch(`/api/v1/admin/documents/${id}/${verb}`, { method: "POST" });
    if (!response.ok) { setError(await errorMessage(response)); return; }
    await loadDocuments();
  }

  async function openDocument(item: DocumentItem) {
    setSelected(item); setParsePreview(undefined); setPanelLoading(true); setError("");
    const response = await apiFetch(`/api/v1/admin/documents/${item.id}/preview`);
    setPanelLoading(false);
    if (!response.ok) { setError(await errorMessage(response)); return; }
    setParsePreview(await response.json());
  }

  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) || "").trim() || null;
    const metadata = {
      title: value("title"), category: value("category") || "未分类", issuer: value("issuer"),
      document_no: value("document_no"), region: value("region") || "中国", version: value("version"),
      published_at: value("published_at"), effective_at: value("effective_at"), expires_at: value("expires_at"),
      validity_status: value("validity_status") || "unknown", supersedes: value("supersedes"),
      source_url: value("source_url"), local_file_name: selected.local_file_name || null,
      tags: String(form.get("tags") || "").split(/[，,]/).map((tag) => tag.trim()).filter(Boolean),
      notes: value("notes"), visibility: value("visibility") || "public",
    };
    const response = await apiFetch(`/api/v1/admin/documents/${selected.id}`, { method: "PATCH", body: JSON.stringify(metadata) });
    if (!response.ok) { setError(await errorMessage(response)); return; }
    const updated = await response.json(); setSelected(updated); setNotice("元数据已保存"); await loadDocuments();
  }

  if (authenticated === null) return <div className="admin-loading">正在连接知识库…</div>;
  if (!authenticated) return (
    <main className="login-page">
      <Link href="/" className="back-link">← 返回知识问答</Link>
      <form className="login-card" onSubmit={login}>
        <span className="brand-mark large"><i /></span><p className="overline">KNOWLEDGE OPERATIONS</p><h1>资料管理后台</h1><p>登录后上传政策、标准和设备资料。</p>
        <label>管理员账号<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label>
        <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
        {error && <div className="form-error">{error}</div>}<button type="submit">安全登录</button>
      </form>
    </main>
  );

  return (
    <div className="admin-shell">
      <header className="admin-header"><div className="brand-row"><span className="brand-mark"><i /></span><div><strong>光伏智库</strong><span>资料管理后台</span></div></div><div><Link href="/">查看问答页 ↗</Link><button onClick={() => void apiFetch("/api/v1/admin/logout", { method: "POST" }).then(() => setAuthenticated(false))}>退出</button></div></header>
      <main className="admin-content">
        <section className="admin-intro"><div><p className="overline">KNOWLEDGE OPERATIONS</p><h1>维护可追溯的光伏知识</h1><p>上传资料、确认版本状态并跟踪解析进度。归档资料不会被访客检索。</p></div><div className="metric"><strong>{documents.filter((item) => item.ingest_status === "ready").length}</strong><span>份资料可检索</span></div></section>
        {(error || notice) && <div className={error ? "admin-alert error" : "admin-alert success"}>{error || notice}<button onClick={() => { setError(""); setNotice(""); }}>×</button></div>}
        <div className="admin-grid">
          <form className="admin-card upload-card" onSubmit={upload}>
            <div className="card-title"><span>01</span><div><h2>上传单份资料</h2><p>支持 PDF、Word、Excel、文本与网页文件</p></div></div>
            <label>文件<input required name="file" type="file" accept=".pdf,.docx,.xlsx,.txt,.md,.html,.htm" /></label>
            <div className="field-row"><label>资料标题<input required name="title" placeholder="如：分布式光伏发电开发建设管理办法" /></label><label>分类<select name="category"><option>政策法规</option><option>并网标准</option><option>设计规范</option><option>设备手册</option><option>运维资料</option><option>行业报告</option></select></label></div>
            <div className="field-row"><label>发布机构<input name="issuer" placeholder="国家能源局" /></label><label>文号/标准号<input name="document_no" placeholder="GB/T 29319-2024" /></label></div>
            <div className="field-row"><label>版本<input name="version" placeholder="2025年版" /></label><label>有效状态<select name="validity_status" defaultValue="active"><option value="active">现行</option><option value="unknown">待确认</option><option value="draft">草案</option><option value="superseded">已替代</option><option value="expired">已失效</option></select></label></div>
            <label className="checkbox"><input type="checkbox" name="visibility" value="admin_only" onChange={(event) => { event.currentTarget.value = event.currentTarget.checked ? "admin_only" : "public"; }} /> 仅管理员可见</label>
            <input type="hidden" name="visibility" value="public" />
            <button className="primary-button" disabled={uploading}>{uploading ? "正在上传…" : "上传并建立索引"}</button>
          </form>
          <section className="admin-card manifest-card">
            <div className="card-title"><span>02</span><div><h2>导入知识清单</h2><p>先预览校验，再批量创建资料记录</p></div></div>
            <label className="manifest-drop">选择 knowledge-sources.yaml<input type="file" accept=".yaml,.yml" onChange={(event) => { setManifestFile(event.target.files?.[0]); setManifestPreview(undefined); }} /><span>{manifestFile?.name || "点击选择 YAML 文件"}</span></label>
            <button className="secondary-button" disabled={!manifestFile} onClick={() => void previewManifest()}>预览清单</button>
            {manifestPreview && <div className="manifest-result"><div><strong>{manifestPreview.valid}</strong> 条有效 <span>·</span> <b>{manifestPreview.invalid}</b> 条需修正</div><ul>{manifestPreview.items.slice(0, 5).map((item) => <li key={item.row}><span>{item.row}</span>{item.entry.title || "无标题"}<b>{item.action}</b></li>)}</ul><button disabled={!!manifestPreview.invalid} onClick={() => void commitManifest()}>确认导入</button></div>}
          </section>
        </div>
        <section className="document-section"><div className="section-heading"><div><p className="overline">DOCUMENT REGISTRY</p><h2>资料目录</h2></div><button onClick={() => void loadDocuments()}>刷新状态</button></div>
          <div className="document-table"><div className="table-head"><span>资料</span><span>版本状态</span><span>处理状态</span><span>文本块</span><span>操作</span></div>
          {documents.length === 0 ? <div className="empty-table">还没有资料。上传第一份政策或标准开始构建知识库。</div> : documents.map((item) => <div className="table-row" key={item.id}><div><strong>{item.title}</strong><small>{item.document_no || item.category}{item.version ? ` · ${item.version}` : ""}</small>{item.error_message && <em>{item.error_message}</em>}</div><span className={`validity validity-${item.validity_status}`}>{item.validity_status}</span><span className={`ingest ingest-${item.ingest_status}`}><i />{statusText[item.ingest_status] || item.ingest_status}</span><span>{item.chunk_count}</span><div className="row-actions"><button onClick={() => void openDocument(item)}>查看</button><button onClick={() => void action(item.id, "reindex")}>重建</button><button onClick={() => void action(item.id, "archive")}>归档</button></div></div>)}</div>
        </section>
      </main>
      {selected && <div className="document-panel-backdrop">
        <aside className="document-panel" aria-label="资料详情与解析预览">
          <div className="panel-heading"><div><p className="overline">DOCUMENT DETAIL</p><h2>资料详情</h2></div><button aria-label="关闭" onClick={() => setSelected(undefined)}>×</button></div>
          <form className="metadata-form" onSubmit={saveMetadata} key={selected.id}>
            <div className="field-row"><label>标题<input required name="title" defaultValue={selected.title} /></label><label>分类<input required name="category" defaultValue={selected.category} /></label></div>
            <div className="field-row"><label>发布机构<input name="issuer" defaultValue={selected.issuer} /></label><label>地区<input name="region" defaultValue={selected.region} /></label></div>
            <div className="field-row"><label>文号/标准号<input name="document_no" defaultValue={selected.document_no} /></label><label>版本<input name="version" defaultValue={selected.version} /></label></div>
            <div className="field-row triple"><label>发布日期<input type="date" name="published_at" defaultValue={selected.published_at} /></label><label>生效日期<input type="date" name="effective_at" defaultValue={selected.effective_at} /></label><label>失效日期<input type="date" name="expires_at" defaultValue={selected.expires_at} /></label></div>
            <div className="field-row"><label>有效状态<select name="validity_status" defaultValue={selected.validity_status}><option value="active">现行</option><option value="unknown">待确认</option><option value="draft">草案</option><option value="superseded">已替代</option><option value="expired">已失效</option></select></label><label>可见范围<select name="visibility" defaultValue={selected.visibility}><option value="public">公开检索</option><option value="admin_only">仅管理员</option></select></label></div>
            <label>替代文号<input name="supersedes" defaultValue={selected.supersedes} /></label>
            <label>官方来源<input type="url" name="source_url" defaultValue={selected.source_url} placeholder="https://…" /></label>
            <label>标签<input name="tags" defaultValue={selected.tags?.join("，")} placeholder="备案，并网，安全" /></label>
            <label>备注<textarea name="notes" defaultValue={selected.notes} rows={3} /></label>
            <button className="primary-button">保存元数据</button>
          </form>
          <section className="parse-preview"><div><h3>解析预览</h3><span>{selected.chunk_count} 个文本块</span></div>
            {panelLoading ? <p>正在读取解析结果…</p> : !parsePreview?.chunks.length ? <p>暂无解析内容，资料可能仍在处理。</p> : parsePreview.chunks.map((chunk) => <article key={chunk.ordinal}><small>块 {chunk.ordinal + 1}{chunk.page_start ? ` · 第 ${chunk.page_start}${chunk.page_end && chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ""} 页` : ""}{chunk.section ? ` · ${chunk.section}` : ""}</small><p>{chunk.content}</p></article>)}
          </section>
        </aside>
      </div>}
    </div>
  );
}
