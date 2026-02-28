# Frontend for Integrated App

This directory holds a simple React frontend that interacts with the API gateway
running on `http://localhost:8000`.

## Setup

From the `frontend` folder:

```bash
npm install   # or yarn (will pull in Vite + plugins)
npm run dev   # starts development server on http://localhost:3000
```

The project uses Vite for fast React development; configuration is in `vite.config.js`.

The UI now:

* shows service running status, port, network names
* buttons to start/stop each service (disabled appropriately)
* fetches additional detail JSON from each backend via the gateway
* embeds MJPEG streams as `<img>` elements so you can watch cameras inline

The app displays the status of the three backend services and provides buttons
to start/stop them. It also includes links to each service's video stream via
the gateway proxy.
