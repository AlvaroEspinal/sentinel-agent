#!/usr/bin/env bash
# ============================================================
# Parcl Intelligence — Backend Deployment to Railway
# Run: bash deploy-backend.sh
# ============================================================
set -euo pipefail

echo "═══════════════════════════════════════════════"
echo "  PARCL INTELLIGENCE — Backend Deploy (Railway)"
echo "═══════════════════════════════════════════════"

# Step 1: Login to Railway
echo ""
echo "Step 1: Logging in to Railway..."
railway login

# Step 2: Init or link project
echo ""
echo "Step 2: Creating Railway project..."
cd backend
railway init --name parcl-intelligence-api

# Step 3: Set environment variables
echo ""
echo "Step 3: Setting environment variables..."
echo "  Reading from backend/.env..."

if [ -f .env ]; then
    # Read vars from .env
    set -a; source .env; set +a
fi

# Set required env vars (prompts if not in .env)
railway variables set \
    SUPABASE_URL="${SUPABASE_URL:?Set SUPABASE_URL in .env}" \
    SUPABASE_SERVICE_KEY="${SUPABASE_SERVICE_KEY:?Set SUPABASE_SERVICE_KEY in .env}" \
    FRONTEND_URL="https://sentinel-agent-alpha.vercel.app" \
    NOMINATIM_USER_AGENT="parcl-intelligence/1.0" \
    LLM_PROVIDER="${LLM_PROVIDER:-anthropic}" \
    PORT="8000"

# Optional vars
[ -n "${ANTHROPIC_API_KEY:-}" ] && railway variables set ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"
[ -n "${FIRECRAWL_API_KEY:-}" ] && railway variables set FIRECRAWL_API_KEY="$FIRECRAWL_API_KEY"
[ -n "${OPENROUTER_API_KEY:-}" ] && railway variables set OPENROUTER_API_KEY="$OPENROUTER_API_KEY"

# Step 4: Deploy
echo ""
echo "Step 4: Deploying..."
railway up --detach

# Step 5: Get domain
echo ""
echo "Step 5: Setting up public domain..."
railway domain

echo ""
echo "═══════════════════════════════════════════════"
echo "  DEPLOYMENT COMPLETE"
echo "═══════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Copy the Railway domain URL above"
echo "  2. Go to Vercel → sentinel-agent → Settings → Environment Variables"
echo "  3. Add: VITE_API_URL = https://<your-railway-domain>"
echo "  4. Redeploy the Vercel frontend"
echo ""
