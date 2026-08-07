"use client";

import { FormEvent, KeyboardEvent, useMemo, useRef, useState } from "react";
import { API_BASE, apiFetch, errorMessage } from "../lib/api";

type Citation = {
  index: number;
  chunk_id: string;
  document_id: string;
  title: string;
  document_no?: string;
  page_start?: number;
  page_end?: number;
  section?: string;
  excerpt: string;
  source_url?: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  messageId?: string;
  pending?: boolean;
};

const examples = [
  { tag: "政策", question: "工商业分布式光伏有哪些主要备案要求？" },
  { tag: "并网", question: "分布式光伏接入配电网需要满足哪些技术条件？" },
  { tag: "标准", question: "GB/T 29319-2024 主要适用于哪些场景？" },
];

function sourceLabel(citation: Citation) {
  const page = citation.page_start ? `第 ${citation.page_start} 页` : citation.section;
  return [citation.document_no, page].filter(Boolean).join(" · ");
}

export function SolarChat() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [selectedCitation, setSelectedCitation] = useState<Citation>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const hasConversation = messages.length > 0;

  const history = useMemo(
    () => messages.filter((item) => !item.pending).slice(-8).map(({ role, content }) => ({ role, content })),
    [messages],
  );

  async function ask(nextQuestion?: string) {
    const value = (nextQuestion ?? question).trim();
    if (!value || busy) return;
    setBusy(true);
    setError("");
    setQuestion("");
    const user: ChatMessage = { id: crypto.randomUUID(), role: "user", content: value };
    const assistantId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      user,
      { id: assistantId, role: "assistant", content: "", citations: [], pending: true },
    ]);

    try {
      const response = await fetch(`${API_BASE}/api/v1/chat/stream`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: value, conversation_id: conversationId, history }),
      });
      if (!response.ok || !response.body) throw new Error(await errorMessage(response));
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value: bytes } = await reader.read();
        buffer += decoder.decode(bytes ?? new Uint8Array(), { stream: !done });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const event = frame.match(/^event:\s*(.+)$/m)?.[1];
          const raw = frame.match(/^data:\s*(.+)$/m)?.[1];
          if (!event || !raw) continue;
          const data = JSON.parse(raw);
          if (event === "meta") setConversationId(data.conversation_id);
          if (event === "delta") {
            setMessages((current) =>
              current.map((item) => item.id === assistantId ? { ...item, content: item.content + data.text } : item),
            );
          }
          if (event === "citation") {
            setMessages((current) =>
              current.map((item) => item.id === assistantId ? { ...item, citations: [...(item.citations ?? []), data] } : item),
            );
          }
          if (event === "done") {
            setMessages((current) =>
              current.map((item) => item.id === assistantId ? { ...item, pending: false, messageId: data.message_id } : item),
            );
          }
          if (event === "error") throw new Error(data.detail ?? "问答服务暂时不可用");
        }
        if (done) break;
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "问答服务暂时不可用";
      setError(message);
      setMessages((current) => current.filter((item) => item.id !== assistantId));
    } finally {
      setBusy(false);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void ask();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  }

  async function feedback(messageId: string, helpful: boolean) {
    await apiFetch("/api/v1/feedback", {
      method: "POST",
      body: JSON.stringify({ message_id: messageId, helpful }),
    });
  }

  function resetChat() {
    setMessages([]);
    setConversationId(undefined);
    setSelectedCitation(undefined);
    setError("");
    setSidebarOpen(false);
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="brand-row">
          <span className="brand-mark"><i /></span>
          <div><strong>光伏智库</strong><span>Solar Knowledge</span></div>
        </div>
        <button className="new-chat" onClick={resetChat}><span>＋</span> 新建问答</button>
        <nav className="side-nav" aria-label="主要导航">
          <button className="active"><span>◫</span> 知识问答</button>
          <button onClick={() => location.assign("/admin")}><span>▤</span> 资料管理</button>
        </nav>
        <div className="sidebar-spacer" />
        <div className="source-status"><span className="status-dot" /><div><strong>知识库在线</strong><small>仅依据已收录资料作答</small></div></div>
        <p className="sidebar-note">政策与标准存在时效性，重要决策请复核引用原文。</p>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="打开导航">☰</button>
          <div><span className="eyebrow">分布式光伏 · 证据优先</span><h1>专业知识问答</h1></div>
          <div className="top-actions"><span className="live-pill"><i />资料已同步</span><a href="/admin">管理后台</a></div>
        </header>

        <section className={`conversation ${hasConversation ? "conversation-active" : ""}`}>
          {!hasConversation ? (
            <div className="welcome">
              <div className="sun-orbit"><span>光</span></div>
              <p className="overline">GROUNDED SOLAR INTELLIGENCE</p>
              <h2>从资料中找到<span>可靠答案</span></h2>
              <p className="welcome-copy">检索分布式光伏政策、并网标准与设备资料。每个结论都可回到原文核验。</p>
              <div className="example-grid">
                {examples.map((item) => (
                  <button key={item.question} onClick={() => void ask(item.question)}>
                    <span>{item.tag}</span><strong>{item.question}</strong><i>↗</i>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-list" aria-live="polite">
              {messages.map((message) => (
                <article key={message.id} className={`message message-${message.role}`}>
                  <div className="message-avatar">{message.role === "user" ? "你" : "光"}</div>
                  <div className="message-body">
                    <span className="message-author">{message.role === "user" ? "你的问题" : "光伏智库"}</span>
                    <p className={message.pending && !message.content ? "thinking" : ""}>{message.content || "正在检索资料"}</p>
                    {!!message.citations?.length && (
                      <div className="citation-list">
                        {message.citations.map((citation) => (
                          <button key={citation.chunk_id} onClick={() => setSelectedCitation(citation)}>
                            <b>[{citation.index}]</b><span>{citation.title}</span><small>{sourceLabel(citation)}</small>
                          </button>
                        ))}
                      </div>
                    )}
                    {message.role === "assistant" && message.messageId && (
                      <div className="feedback"><span>这个回答有帮助吗？</span><button onClick={() => void feedback(message.messageId!, true)}>有帮助</button><button onClick={() => void feedback(message.messageId!, false)}>需改进</button></div>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <div className="composer-wrap">
          {error && <div className="error-banner">{error}</div>}
          <form className="composer" onSubmit={onSubmit}>
            <textarea ref={inputRef} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown} maxLength={1000} rows={1} placeholder="询问政策、标准、并网或设备资料…" aria-label="输入光伏问题" />
            <div className="composer-tools"><span>仅检索现行与有效资料</span><button disabled={busy || !question.trim()} aria-label="发送问题">{busy ? "···" : "↑"}</button></div>
          </form>
          <p className="disclaimer">AI 可能存在误差，请以引用的政策、标准和厂商原文为准。</p>
        </div>
      </main>

      {selectedCitation && (
        <aside className="evidence-drawer" aria-label="引用原文">
          <button className="drawer-close" onClick={() => setSelectedCitation(undefined)} aria-label="关闭引用">×</button>
          <span className="drawer-index">证据 {selectedCitation.index}</span>
          <h3>{selectedCitation.title}</h3>
          <dl><div><dt>文件编号</dt><dd>{selectedCitation.document_no || "未标注"}</dd></div><div><dt>位置</dt><dd>{sourceLabel(selectedCitation) || "正文"}</dd></div></dl>
          <blockquote>{selectedCitation.excerpt}</blockquote>
          {selectedCitation.source_url && <a href={selectedCitation.source_url} target="_blank" rel="noreferrer">打开官方来源 ↗</a>}
        </aside>
      )}
      {sidebarOpen && <button className="mobile-backdrop" onClick={() => setSidebarOpen(false)} aria-label="关闭导航" />}
    </div>
  );
}

