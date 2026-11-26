import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import hljs from 'highlight.js/lib/common'

// ---------------------------------------------------------------- api helpers
const api = {
  list: () => fetch('/api/sessions').then((r) => r.json()),
  create: (kind) =>
    fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind }),
    }).then((r) => r.json()),
  remove: (id) => fetch(`/api/sessions/${id}`, { method: 'DELETE' }),
  send: (id, content) =>
    fetch(`/api/sessions/${id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),
  cancel: (id) => fetch(`/api/sessions/${id}/cancel`, { method: 'POST' }),
  files: (id) => fetch(`/api/sessions/${id}/files`).then((r) => r.json()),
  upload: (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch(`/api/sessions/${id}/files`, { method: 'POST', body: fd }).then((r) => r.json())
  },
}

function upsert(list, m) {
  const i = list.findIndex((x) => x.seq === m.seq)
  if (i >= 0) {
    const copy = list.slice()
    copy[i] = m
    return copy
  }
  const copy = [...list, m]
  copy.sort((a, b) => a.seq - b.seq)
  return copy
}

function fmtSize(n) {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtInput(input) {
  if (input == null) return ''
  if (typeof input === 'string') return input
  try {
    return JSON.stringify(input, null, 2)
  } catch {
    return String(input)
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ))
}

function highlightCode(code, lang) {
  try {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
    }
    return hljs.highlightAuto(code).value
  } catch {
    return escapeHtml(code)
  }
}

// ---------------------------------------------------------------- preview modal
function PreviewModal({ data, onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const html = useMemo(
    () => (data.binary ? '' : highlightCode(data.content || '', data.language)),
    [data]
  )
  const dl = `/api/sessions/${data.sid}/files/download?path=${encodeURIComponent(data.path)}`

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title" title={data.path}>{data.path}</span>
          <span className="modal-meta">
            {fmtSize(data.size)}
            {data.truncated ? ' · 已截断（仅显示前 200KB）' : ''}
          </span>
          <a className="btn" href={dl}>下载</a>
          <button className="btn" onClick={onClose}>关闭</button>
        </div>
        <div className="modal-body">
          {data.binary ? (
            <div className="no-files">二进制文件，无法预览。请下载后查看。</div>
          ) : (
            <pre className="code">
              <code className="hljs" dangerouslySetInnerHTML={{ __html: html }} />
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- tool card
function ToolCard({ tool }) {
  const [open, setOpen] = useState(false)
  const st = tool.status || 'running'
  const stLabel = st === 'done' ? '完成' : st === 'error' ? '失败' : '执行中'
  return (
    <div className="tool">
      <div className="tool-head" onClick={() => setOpen((o) => !o)}>
        <span>{open ? '▾' : '▸'}</span>
        <span className="name">{tool.name}</span>
        <span className={`st ${st}`}>{stLabel}</span>
      </div>
      {open && (
        <div className="tool-body">
          <div className="label">输入</div>
          <pre>{fmtInput(tool.input)}</pre>
          {tool.output != null && tool.output !== '' && (
            <>
              <div className="label">输出</div>
              <pre>{tool.output}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- app
export default function App() {
  const [sessions, setSessions] = useState([])
  const [active, setActive] = useState(null)
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState('')
  const [status, setStatus] = useState('idle')
  const [files, setFiles] = useState([])
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem('theme') || 'dark'
    } catch {
      return 'dark'
    }
  })
  const [preview, setPreview] = useState(null)

  const wsRef = useRef(null)
  const activeRef = useRef(null)
  const endRef = useRef(null)

  const loadSessions = useCallback(async () => {
    try {
      setSessions(await api.list())
    } catch {}
  }, [])

  const loadFiles = useCallback(async (id) => {
    if (!id) return
    try {
      setFiles(await api.files(id))
    } catch {}
  }, [])

  const openPreview = async (path) => {
    if (!active) return
    setError('')
    try {
      const r = await fetch(
        `/api/sessions/${active}/files/content?path=${encodeURIComponent(path)}`
      )
      if (!r.ok) throw new Error('failed')
      const d = await r.json()
      setPreview({ ...d, sid: active })
    } catch {
      setError('无法加载文件预览')
    }
  }

  // Theme: persist the choice and reflect it on <html data-theme>.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try {
      localStorage.setItem('theme', theme)
    } catch {}
  }, [theme])

  // Poll session list (keeps sidebar status/preview fresh across sessions).
  useEffect(() => {
    loadSessions()
    const t = setInterval(loadSessions, 5000)
    return () => clearInterval(t)
  }, [loadSessions])

  // Connect/disconnect WebSocket when the active session changes.
  useEffect(() => {
    if (!active) return
    activeRef.current = active
    setMessages([])
    setStreaming('')
    setError('')
    setStatus('idle')
    setFiles([])
    loadFiles(active)

    let closed = false
    let retry = 0
    let ws = null

    const connect = () => {
      if (closed) return
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/${active}`)
      wsRef.current = ws
      ws.onopen = () => {
        retry = 0
        ws.send(JSON.stringify({ type: 'subscribe', after_seq: 0 }))
      }
      ws.onmessage = (e) => {
        let ev
        try {
          ev = JSON.parse(e.data)
        } catch {
          return
        }
        if (ev.type === 'session_status') {
          setStatus(ev.status)
        } else if (ev.type === 'delta') {
          setStreaming((s) => s + ev.text)
        } else if (ev.type === 'message') {
          const m = ev.message
          if (m.type === 'text' && m.role === 'assistant') setStreaming('')
          setMessages((prev) => upsert(prev, m))
        } else if (ev.type === 'tool_update') {
          setMessages((prev) =>
            prev.map((x) => (x.seq === ev.seq ? { ...x, tool: ev.tool } : x))
          )
        } else if (ev.type === 'result') {
          setStreaming('')
          setStatus('idle')
          loadFiles(active)
        } else if (ev.type === 'error') {
          setError(ev.error || '发生错误')
          setStatus('idle')
        }
      }
      ws.onclose = () => {
        if (closed) return
        retry += 1
        setTimeout(connect, Math.min(800 * retry, 4000))
      }
      ws.onerror = () => {
        try {
          ws.close()
        } catch {}
      }
    }

    connect()
    return () => {
      closed = true
      try {
        wsRef.current && wsRef.current.close()
      } catch {}
    }
  }, [active, loadFiles])

  // Auto-scroll on new content.
  useEffect(() => {
    endRef.current && endRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming])

  const createSession = async (kind) => {
    try {
      const s = await api.create(kind)
      await loadSessions()
      setActive(s.id)
    } catch {
      setError('创建会话失败')
    }
  }

  const deleteSession = async (id, e) => {
    e.stopPropagation()
    if (!confirm('删除该会话及其文件？')) return
    await api.remove(id)
    if (activeRef.current === id) setActive(null)
    loadSessions()
  }

  const send = async () => {
    const text = input.trim()
    if (!text || !active || status === 'running') return
    setInput('')
    setError('')
    try {
      const r = await api.send(active, text)
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        setError(j.detail || '发送失败')
      }
    } catch {
      setError('发送失败')
    }
  }

  const cancel = async () => {
    if (active) await api.cancel(active)
  }

  const onUpload = async (e) => {
    const file = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!file || !active) return
    await api.upload(active, file)
    loadFiles(active)
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const activeSession = sessions.find((s) => s.id === active)

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="title">
            云端 <span>Agent</span> 工作台
          </span>
          <button
            className="theme-toggle"
            title="切换日间 / 夜间模式"
            onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
          >
            {theme === 'dark' ? '☀ 日间' : '☾ 夜间'}
          </button>
        </div>
        <div className="newbtns">
          <button onClick={() => createSession('dev')}>+ 开发会话</button>
          <button onClick={() => createSession('daily')}>+ 日常会话</button>
        </div>
        <div className="sessionlist">
          {sessions.length === 0 && (
            <div className="no-files" style={{ paddingTop: 24 }}>
              还没有会话，先新建一个吧
            </div>
          )}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`session ${s.id === active ? 'active' : ''}`}
              onClick={() => setActive(s.id)}
            >
              <div className="title">
                <span className={`badge ${s.kind}`}>{s.kind === 'dev' ? '开发' : '日常'}</span>
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {s.title}
                </span>
                <span className={`dot ${s.status === 'running' ? 'running' : ''}`} />
              </div>
              <div className="last">{s.last || '（空）'}</div>
              <span className="del" onClick={(e) => deleteSession(s.id, e)}>
                删除
              </span>
            </div>
          ))}
        </div>
      </aside>

      <main className="chat">
        <div className="chat-header">
          <h2>{activeSession ? activeSession.title : '未选择会话'}</h2>
          {active && (
            <span className={`status ${status === 'running' ? 'running' : ''}`}>
              {status === 'running' ? '助手工作中…' : '空闲'}
            </span>
          )}
          <div className="grow" />
          {active && status === 'running' && (
            <button className="btn danger" onClick={cancel}>
              取消
            </button>
          )}
        </div>

        <div className="messages">
          {!active && (
            <div className="empty">
              选择左侧会话，或新建一个。
              <br />
              “开发会话”适合写代码 / 跑测试；“日常会话”适合分析材料、整理报告。
            </div>
          )}
          {active && messages.length === 0 && !streaming && (
            <div className="empty">
              这是一个新会话，发点什么让助手开始工作吧。
              <br />
              例如：「写一个 Python 小工具，把 CSV 转成 Markdown 表格，并加测试」
            </div>
          )}
          {messages.map((m) =>
            m.type === 'tool' ? (
              <div className="msg assistant" key={m.seq}>
                <ToolCard tool={m.tool} />
              </div>
            ) : (
              <div className={`msg ${m.role === 'user' ? 'user' : 'assistant'}`} key={m.seq}>
                <div className="bubble">{m.text}</div>
              </div>
            )
          )}
          {streaming && (
            <div className="msg assistant">
              <div className="bubble">
                {streaming}
                <span className="cursor">▋</span>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {error && <div className="errorbar">{error}</div>}

        <div className="composer">
          <textarea
            value={input}
            placeholder={active ? '描述你的任务…（Enter 发送，Shift+Enter 换行）' : '请先选择或新建会话'}
            disabled={!active || status === 'running'}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button className="send" onClick={send} disabled={!active || status === 'running' || !input.trim()}>
            发送
          </button>
        </div>
      </main>

      <aside className="files">
        <div className="files-head">
          <span>工作区文件</span>
          <div className="grow" />
          <button className="btn" onClick={() => active && loadFiles(active)}>
            刷新
          </button>
        </div>
        <div className="files-actions">
          <label className="upload">
            上传材料
            <input type="file" style={{ display: 'none' }} onChange={onUpload} disabled={!active} />
          </label>
        </div>
        <div className="filelist">
          {active && files.length === 0 && <div className="no-files">暂无文件</div>}
          {files.map((f) => (
            <div className="file" key={f.path}>
              <button
                className="file-name"
                title={`预览 ${f.path}`}
                onClick={() => openPreview(f.path)}
              >
                {f.path}
              </button>
              <span className="size">{fmtSize(f.size)}</span>
              <a
                className="file-dl"
                href={`/api/sessions/${active}/files/download?path=${encodeURIComponent(f.path)}`}
                title="下载"
              >
                ↓
              </a>
            </div>
          ))}
        </div>
      </aside>

      {preview && <PreviewModal data={preview} onClose={() => setPreview(null)} />}
    </div>
  )
}
