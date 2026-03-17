# Parcl Intelligence — Deployment Guide

## Architecture

```
Vercel (Frontend)              Render (Backend)              Supabase (Database)
sentinel-agent-alpha.vercel.app → parcl-intelligence-api.onrender.com → tkexrzohviadsgolmupa.supabase.co
```

## Step 1: Deploy Backend to Render (5 minutes)

1. Go to [render.com/new/blueprint](https://render.com/new/blueprint)
2. Connect your GitHub repo: `AlvaroEspinal/sentinel-agent`
3. Render will auto-detect `render.yaml` and create the service
4. Set the required environment variables:

| Variable | Value |
|----------|-------|
| `SUPABASE_URL` | `https://tkexrzohviadsgolmupa.supabase.co` |
| `SUPABASE_SERVICE_KEY` | *(from .env file)* |
| `OPENROUTER_API_KEY` | *(from .env file)* |
| `FIRECRAWL_API_KEY` | *(from .env file)* |

5. Click **Apply** — Render will build the Docker image and deploy
6. Wait for the service to show "Live" (takes ~3-5 minutes)
7. Note your backend URL (e.g., `https://parcl-intelligence-api.onrender.com`)

### Verify Backend

```bash
curl https://parcl-intelligence-api.onrender.com/api/health
```

Should return `{"status": "ok", ...}`

## Step 2: Connect Frontend to Backend (2 minutes)

1. Go to [vercel.com](https://vercel.com) → Your project → Settings → Environment Variables
2. Add or update:

| Variable | Value |
|----------|-------|
| `VITE_API_URL` | `https://parcl-intelligence-api.onrender.com` |

3. Trigger a redeploy: Deployments → latest → **Redeploy**

## Step 3: Verify

Visit [sentinel-agent-alpha.vercel.app](https://sentinel-agent-alpha.vercel.app) and:
- Search for "45 Harvard St Newton MA" — should return parcel data
- Click a town (e.g., Weston) — should show dashboard with stats
- Click "Map View" — should open the CesiumJS globe with data layers

## Alternative: Deploy Backend to Railway

```bash
railway login          # Opens browser for auth
railway init           # Link to project
railway up             # Deploy
railway variables set SUPABASE_URL=https://tkexrzohviadsgolmupa.supabase.co
railway variables set SUPABASE_SERVICE_KEY=<key>
```

## Local Development

```bash
# Backend
cd backend && python3 main.py     # http://localhost:8000

# Frontend
cd frontend && npm run dev         # http://localhost:3000
```

## Current Data (as of March 2026)

| Dataset | Records |
|---------|---------|
| Permits | 104,257 across 12 towns |
| Properties (MassGIS) | 91,983 parcels |
| MEPA Filings | 5,557 |
| Municipal Documents | 8,001 |
| Geocoded Permits | 68,532 (95.7% of addressable linked) |

## Render Free Tier Notes

- Free tier services spin down after 15 min of inactivity
- First request after idle takes ~30-60 seconds (cold start)
- For production, upgrade to Render's $7/mo Starter plan
