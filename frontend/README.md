# MedGuard — frontend

React + Vite. This is the client half of MedGuard; see the
[project README](../README.md) for what MedGuard is, how access decisions
work, and full setup instructions.

## Quick start

```bash
npm install
npm run dev
```

The backend must be running too (`cd ../backend && python manage.py runserver
0.0.0.0:8000`). The API base URL is derived from the page's own hostname in
development, so `localhost` and a LAN IP both work with no configuration. In
production, set `VITE_API_BASE_URL` to the deployed backend's `/api` URL.

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | Lint with oxlint |

## Layout

```
src/
  api/       one thin module per backend app
  capture/   behavioural + contextual signal capture
  pages/     login + the three role dashboards
  App.css    all styling (design tokens at the top)
```

three.js is deliberately limited to two places — the login page's shield scene
and the Security Dashboard's event-breakdown donut. Record-access screens stay
plain React for clarity and speed.
