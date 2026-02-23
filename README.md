# MFG Agent — AI Supplier Finder

## Project Structure

```
mfg-agent/
├── backend/
│   ├── app.py                    # Flask app entry point
│   ├── config.py                 # Centralized config
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py               # Base agent class + LLM helper
│   │   ├── researcher.py         # ResearcherAgent
│   │   ├── writer.py             # WriterAgent
│   │   ├── orchestrator.py       # ManufacturingOrchestrator
│   │   └── state.py              # PipelineState + StreamLogger
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── config.py             # ScraperConfig
│   │   ├── engine.py             # ScraperEngine (main)
│   │   ├── sources/
│   │   │   ├── __init__.py
│   │   │   ├── tavily.py
│   │   │   ├── serper.py
│   │   │   ├── duckduckgo.py
│   │   │   └── directories.py   # IndiaMART, Alibaba, etc.
│   │   └── parser.py             # HTML parsing helpers
│   ├── db/
│   │   ├── __init__.py
│   │   ├── chroma.py             # ChromaDB client + operations
│   │   └── models.py             # Data models
│   └── auth/
│       ├── __init__.py
│       └── firebase.py           # Firebase token verification
├── frontend/
│   └── index.html                # Single-file React SPA (Vite-less)
├── static/                       # Built frontend assets (served by Flask)
├── pyproject.toml
├── render.yaml                   # Render deployment config
├── vercel.json                   # Vercel config (frontend proxy)
├── .env.example
└── README.md
```

## Deployment

### Render (Backend)
1. Connect your repo to Render
2. Set env vars in Render dashboard
3. Deploy as Web Service: `python backend/app.py --server`

### Vercel (Frontend)
1. `cd frontend && npm install && npm run build`
2. `vercel deploy`
3. Set `VITE_API_URL` to your Render backend URL

## Environment Variables

```env
GROQ_API_KEY=gsk_...
TAVILY_API_KEY=tvly-...           # optional
SERPER_API_KEY=...                # optional
FIREBASE_PROJECT_ID=your-project
FIREBASE_SERVICE_ACCOUNT_JSON=... # JSON string or path to file
CHROMA_PERSIST_DIR=./chroma_data  # local path for ChromaDB
PORT=5000
DEBUG=false
```
