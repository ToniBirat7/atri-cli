import React, { useState, useEffect, useRef } from 'react';

// BUG: One massive component, no separation of concerns
// BUG: No error boundaries
function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [userId] = useState(Math.floor(Math.random() * 1000));
  const [isConnected, setIsConnected] = useState(false);
  const [typingUsers, setTypingUsers] = useState([]);
  const socket = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    // BUG: Hardcoded URL — breaks in production
    socket.current = new WebSocket(`ws://localhost:8000/ws/${userId}`);

    socket.current.onopen = () => setIsConnected(true);
    socket.current.onclose = () => setIsConnected(false);

    socket.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setMessages((prev) => [...prev, data]);
      } catch {
        setMessages((prev) => [...prev, { content: event.data, sender: 'system' }]);
      }
    };

    // BUG: No reconnection logic
    // BUG: No cleanup of event listeners
    return () => socket.current.close();
  }, [userId]);

  const sendMessage = () => {
    if (input.trim() && socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(input);
      setInput('');
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') sendMessage();
  };

  // BUG: No auto-scroll to latest message
  // BUG: No message grouping by sender
  // BUG: Re-renders entire list on every keypress
  return (
    <div style={{ padding: '20px', fontFamily: 'Arial, sans-serif', maxWidth: '800px', margin: '0 auto' }}>
      <header style={{ marginBottom: '20px', borderBottom: '2px solid #333', paddingBottom: '10px' }}>
        <h1 style={{ margin: 0 }}>🚀 Nebula Chat</h1>
        <span style={{ color: isConnected ? 'green' : 'red' }}>
          {isConnected ? '● Connected' : '○ Disconnected'}
        </span>
        <span style={{ marginLeft: '20px', color: '#666' }}>User #{userId}</span>
      </header>

      {/* BUG: Fixed height, no responsive design */}
      <div style={{
        height: '500px',
        border: '1px solid #ddd',
        borderRadius: '8px',
        overflowY: 'scroll',
        padding: '10px',
        backgroundColor: '#fafafa',
        marginBottom: '15px'
      }}>
        {messages.length === 0 && (
          <p style={{ color: '#999', textAlign: 'center', marginTop: '200px' }}>
            No messages yet. Start chatting!
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{
            padding: '8px 12px',
            marginBottom: '8px',
            borderRadius: '6px',
            backgroundColor: msg.sender === userId ? '#007bff' : '#e9ecef',
            color: msg.sender === userId ? 'white' : 'black',
            maxWidth: '70%',
            marginLeft: msg.sender === userId ? 'auto' : '0',
            wordWrap: 'break-word'
          }}>
            <small style={{ opacity: 0.7 }}>
              {msg.sender === 'system' ? 'System' : `User #${msg.sender}`}
            </small>
            <div>{msg.content}</div>
            {msg.timestamp && (
              <small style={{ opacity: 0.5, fontSize: '0.75em' }}>{msg.timestamp}</small>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div style={{ display: 'flex', gap: '10px' }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Type a message..."
          style={{
            flex: 1,
            padding: '12px',
            borderRadius: '6px',
            border: '1px solid #ddd',
            fontSize: '14px'
          }}
        />
        <button
          onClick={sendMessage}
          disabled={!isConnected}
          style={{
            padding: '12px 24px',
            borderRadius: '6px',
            backgroundColor: isConnected ? '#007bff' : '#ccc',
            color: 'white',
            border: 'none',
            cursor: isConnected ? 'pointer' : 'not-allowed',
            fontSize: '14px'
          }}
        >
          Send
        </button>
      </div>

      {/* BUG: Online users feature is not implemented */}
      <div style={{ marginTop: '15px', color: '#999', fontSize: '12px' }}>
        <em>TODO: Show online users list here</em>
      </div>
    </div>
  );
}

export default App;
