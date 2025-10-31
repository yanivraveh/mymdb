import { useEffect, useRef, useState } from 'react'
import './App.css'

function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)')
  return m ? decodeURIComponent(m.pop()) : ''
}

function Lobby({ onJoin }) {
  const [rooms, setRooms] = useState([])
  const [name, setName] = useState('')

  useEffect(() => {
    fetch('/api/chat/rooms/', { credentials: 'include' })
      .then(r => r.json())
      .then(d => setRooms(d.rooms || []))
      .catch(console.error)
  }, [])

  const createRoom = async (e) => {
    e.preventDefault()
    if (!name.trim()) return
    const csrftoken = getCookie('csrftoken')
    const res = await fetch(`/api/chat/rooms/?name=${encodeURIComponent(name.trim())}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRFToken': csrftoken },
    })
    const data = await res.json()
    if (res.ok) {
      onJoin(data.slug)
    } else {
      alert(data.error || 'Failed to create room')
    }
  }

  return (
    <div className="wrap">
      <div className="card">
        <h2 className="h1">Chat Lobby</h2>
  
        <form className="row" onSubmit={createRoom}>
          <input
            className="input"
            value={name}
            onChange={e=>setName(e.target.value)}
            placeholder="New room name"
          />
          <button className="btn primary" type="submit">Create</button>
        </form>
  
        <h3 style={{marginTop:16}}>Existing rooms</h3>
        <ul className="list">
          {rooms.map(r => (
            <li key={r.slug}>
              {r.name}
              <button className="btn" onClick={()=>onJoin(r.slug)}>Join</button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function Room({ slug, onLeave }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const wsRef = useRef(null)

  useEffect(() => {
    let alive = true
    fetch(`/api/chat/rooms/${slug}/messages?limit=50`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (alive) setMessages(d.messages || []) })
      .catch(console.error)

    const ws = new WebSocket(`ws://${location.host}/ws/chat/${slug}/`)
    wsRef.current = ws
    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)
      setMessages(prev => [...prev, {
        event_id: crypto.randomUUID(),
        user_id: null,
        username: data.username,
        content: data.message,
        created_at: data.timestamp,
      }])
    }
    ws.onopen = () => console.log('WS open')
    ws.onclose = () => console.log('WS closed')
    return () => { alive = false; ws.close() }
  }, [slug])

  const send = (e) => {
    e.preventDefault()
    const msg = input.trim()
    if (!msg || !wsRef.current || wsRef.current.readyState !== 1) return
    wsRef.current.send(JSON.stringify({ message: msg }))
    setInput('')
  }

  return (
    <div className="wrap">
      <div className="card">
        <div className="room-head">
          <button className="btn" onClick={onLeave}>← Back</button>
          <h2 className="h1">Room: {slug}</h2>
        </div>
  
        <div className="log">
          {messages.map((m, i) => (
            <div className="msg" key={m.event_id || i}>
              <b>{m.username || 'Anonymous'}:</b> {m.content}
              <span className="meta">
                {new Date(m.created_at || Date.now()).toLocaleTimeString()}
              </span>
            </div>
          ))}
        </div>
  
        <form className="sticky" onSubmit={send}>
          <input
            className="input"
            value={input}
            onChange={e=>setInput(e.target.value)}
            placeholder="Type a message..."
          />
          <button className="btn primary" type="submit">Send</button>
        </form>
      </div>
    </div>
  )
}

export default function App() {
  const [slug, setSlug] = useState(null)
  return slug
    ? <Room slug={slug} onLeave={()=>setSlug(null)} />
    : <Lobby onJoin={setSlug} />
}