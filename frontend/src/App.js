import { useState, useEffect, useRef } from 'react';
import './App.css';

const endpointMap = {
  station: [
    { name: 'Video feed', path: '/station/video_feed', type: 'stream' },
    { name: 'Alerts (JSON)', path: '/station/alerts', type: 'json' },
    { name: 'Status (JSON)', path: '/station/status', type: 'json' }
  ],
  detect: [
    { name: 'Room stream', path: '/detect/status', type: 'stream' },
    { name: 'Snapshot (JSON)', path: '/detect/status-json', type: 'json' },
    { name: 'SSE events', path: '/detect/status-stream', type: 'sse' }
  ],
  control: [
    { name: 'Entry cam', path: '/control/video_feed_entry', type: 'stream' },
    { name: 'Exit cam', path: '/control/video_feed_exit', type: 'stream' },
    { name: 'Status (JSON)', path: '/control/status', type: 'json' },
    { name: 'People list', path: '/control/people', type: 'json' },
    { name: 'Activity log', path: '/control/activity', type: 'json' }
  ]
};

function App() {
  const [server, setServer] = useState('station');
  const [streamSrc, setStreamSrc] = useState('');
  const [output, setOutput] = useState('');
  const [autoData, setAutoData] = useState({});
  const [starting, setStarting] = useState(false);
  const eventSourceRef = useRef(null);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, [server]);

  useEffect(() => {
    setAutoData({});
    if (!streamSrc) return;

    const endpoints = endpointMap[server] || [];
    const jsonEps = endpoints.filter(ep => ep.type === 'json');

    const interval = setInterval(() => {
      jsonEps.forEach(ep => {
        fetch(ep.path)
          .then(r => r.json())
          .then(j => {
            setAutoData(prev => ({ ...prev, [ep.name]: j }));
          })
          .catch(() => {});
      });
    }, 2000);

    return () => clearInterval(interval);
  }, [server, streamSrc]);

  const wait = (ms) => new Promise(r => setTimeout(r, ms));

  const startProcessOnly = async () => {
    setStarting(true);
    try {
      await fetch(`/start/${server}`, { method: 'POST' });
      await wait(2500); // wait for Flask server to boot
      return true;
    } catch (err) {
      setOutput('Process start failed: ' + err.toString());
      return false;
    } finally {
      setStarting(false);
    }
  };

  const handleEndpoint = async (ep) => {
    setStreamSrc('');
    setOutput('');

    if (ep.type === 'stream') {
      const started = await startProcessOnly();
      if (!started) return;

      setStreamSrc(ep.path);
      return;
    }

    try {
      const res = await fetch(ep.path);
      const data = await res.json();
      setOutput(JSON.stringify(data, null, 2));
    } catch (err) {
      setOutput('error: ' + err.toString());
    }
  };

  const available = endpointMap[server] || [];

  return (
    <div className="app">
      <h1>Model Gateway Control</h1>

      <div className="controls">
        <label>
          Select server:{' '}
          <select value={server} onChange={e => setServer(e.target.value)}>
            <option value="station">Station</option>
            <option value="detect">Detect</option>
            <option value="control">Control</option>
          </select>
        </label>

        <button
          disabled={starting}
          onClick={() => fetch(`/start/${server}`, { method: 'POST' })}
        >
          {starting ? 'Starting…' : 'Start Process'}
        </button>

        <button disabled={starting} onClick={() => fetch(`/stop/${server}`, { method: 'POST' })}>
          Stop Process
        </button>

        <button
          disabled={starting}
          onClick={() =>
            fetch('/status')
              .then(r => r.json())
              .then(j => setOutput(JSON.stringify(j, null, 2)))
          }
        >
          Gateway Status
        </button>
      </div>

      <h2>Server endpoints</h2>
      <div className="endpoints">
        {available.map(ep => (
          <button
            key={ep.path}
            onClick={() => handleEndpoint(ep)}
          >
            {ep.name}
          </button>
        ))}
      </div>

      {streamSrc && (
        <div className="stream-section">
          <h3>Stream</h3>
          <img src={streamSrc} alt="stream" />
        </div>
      )}

      {Object.keys(autoData).length > 0 && (
        <div className="live-section">
          <h3>Live status / alerts</h3>
          {Object.entries(autoData).map(([name, data]) => (
            <div key={name}>
              <strong>{name}:</strong>
              <pre>{JSON.stringify(data, null, 2)}</pre>
            </div>
          ))}
        </div>
      )}

      <div className="output-section">
        <h2>Response</h2>
        <pre>{output || '(click a button)'}</pre>
      </div>
    </div>
  );
}

export default App;