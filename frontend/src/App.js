import React, { useState, useEffect } from 'react';

const GATEWAY = 'http://localhost:8000';
const SERVICES = ['station', 'detect', 'control'];

// mapping from service to a function which fetches additional info
const DETAIL_ENDPOINT = {
  station: '/station/api/status',       // returns running info / or custom
  detect: '/detect/status-json',        // returns people/status
  control: '/control/api/status',       // returns monitoring/counters
};

function App() {
  const [status, setStatus] = useState({});
  const [details, setDetails] = useState({});

  const fetchStatus = () => {
    fetch(`${GATEWAY}/status`)
      .then(r => r.json())
      .then(st => {
        setStatus(st);
        // after we know which services are running, pull their detail endpoints
        Object.keys(DETAIL_ENDPOINT).forEach(name => {
          if (st[name]?.running) {
            fetch(`${GATEWAY}${DETAIL_ENDPOINT[name]}`)
              .then(r => r.json())
              .then(data => setDetails(d => ({ ...d, [name]: data })))
              .catch(() => {});
          }
        });
      })
      .catch(e => console.error('gateway status error', e));
  };

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 5000);
    return () => clearInterval(iv);
  }, []);

  const sendAction = (name, action) => () => {
    fetch(`${GATEWAY}/${action}/${name}`, { method: 'POST' })
      .then(fetchStatus)
      .catch(e => console.error(e));
  };

  return (
    <div style={{ padding: '1rem', fontFamily: 'sans-serif' }}>
      <h1>Integrated App Gateway</h1>
      {SERVICES.map(name => (
        <div key={name} style={{ marginBottom: '1.5rem', border: '1px solid #ccc', padding: '0.5rem' }}>
          <h2 style={{ textTransform: 'capitalize' }}>{name}</h2>
          <p>running: {String(status[name]?.running)}</p>
          <button onClick={sendAction(name, 'start')} disabled={status[name]?.running}>Start</button>{' '}
          <button onClick={sendAction(name, 'stop')} disabled={!status[name]?.running}>Stop</button>
          <div>
            <strong>port:</strong> {status[name]?.port}
          </div>
          <div>
            <strong>networks:</strong> {status[name]?.networks?.join(', ')}
          </div>
          {details[name] && (
            <pre style={{ background: '#f9f9f9', padding: '0.5rem' }}>
              {JSON.stringify(details[name], null, 2)}
            </pre>
          )}
        </div>
      ))}

      <h2>Streams (via gateway)</h2>
      <div style={{ display: 'flex', gap: '1rem' }}>
        <div>
          <h3>Control entry</h3>
          <img src={`${GATEWAY}/control/video_feed_entry`} alt="entry cam" width={320} />
        </div>
        <div>
          <h3>Control exit</h3>
          <img src={`${GATEWAY}/control/video_feed_exit`} alt="exit cam" width={320} />
        </div>
      </div>
      <div style={{ marginTop: '1rem' }}>
        <h3>Station feed</h3>
        <img src={`${GATEWAY}/station/video_feed`} alt="station" width={640} />
      </div>
      <div style={{ marginTop: '1rem' }}>
        <h3>Detect feed</h3>
        <img src={`${GATEWAY}/detect/status`} alt="detect" width={640} />
      </div>
    </div>
  );
}

export default App;
