# Deployment Guide

## One-time Setup

### 1. Firebase (Google Sign-In)
1. Go to https://console.firebase.google.com → New Project
2. Authentication → Sign-in method → Enable **Google**
3. Project Settings → **Your apps** → Add a **Web app** → copy the `firebaseConfig` object
4. Project Settings → **Service Accounts** → Generate new private key → download JSON
5. Paste the `firebaseConfig` into `static/index.html` (the `FIREBASE_CONFIG` object)

### 2. Environment variables
Copy `.env.example` → `.env` and fill in:
- `GROQ_API_KEY` (free: https://console.groq.com)
- `FIREBASE_PROJECT_ID`
- `FIREBASE_SERVICE_ACCOUNT_JSON` (paste the downloaded JSON as a single-line string)
- Optionally: `TAVILY_API_KEY`, `SERPER_API_KEY`

---

## Local Development

```bash
# Install
pip install -e .

# Run backend
python -m backend

# Frontend is served at http://localhost:5000
```

---

## Deploy to Render (Backend)

1. Push repo to GitHub
2. Render Dashboard → New → Web Service → connect repo
3. Set env vars in Render dashboard (copy from `.env`)
4. Render auto-deploys on push

Alternatively, use the `render.yaml` Blueprint:
```
Render Dashboard → New → Blueprint → connect repo
```

The `render.yaml` provisions:
- A Python web service running the Flask backend
- A 5 GB persistent disk mounted at `/var/data` for ChromaDB

---

## Deploy to Vercel (Frontend)

```bash
# Install Vercel CLI
npm i -g vercel

# Update vercel.json: replace your-render-backend.onrender.com with your actual Render URL

# Deploy
cd mfg-agent
vercel deploy --prod
```

Update `CORS_ORIGINS` in your Render env vars to include your Vercel URL.

---

## Architecture

```
Browser (Vercel)
    │
    ├─ GET /           → static/index.html (Firebase Google Sign-In)
    │
    └─ POST /api/query  ──► Render (Flask)
           │                  ├─ Auth: verify Firebase token
           │                  ├─ Agents: Researcher → Writer
           │                  ├─ Scraper: Tavily / Serper / DDG / B2B dirs
           │                  └─ ChromaDB: persist suppliers + reports
           │
           └─ SSE stream back → real-time log + supplier cards + report
```

## ChromaDB Notes

- **Local**: stored at `CHROMA_PERSIST_DIR` (default `./chroma_data`). Persists on Render disk.
- **Cloud**: set `CHROMA_HOST` + `CHROMA_API_KEY` for [ChromaDB Cloud](https://www.trychroma.com/)

Collections:
| Name | Purpose |
|------|---------|
| `suppliers` | All extracted supplier records (semantic search) |
| `reports` | Full pipeline reports per session |
| `history` | Per-user query history |
