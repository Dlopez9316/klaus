# 🚀 Deployment Guide

## Step 1: Push Code to GitHub

1. Download all the files from this folder
2. Navigate to your local repository:
```bash
cd reconciliation-agent
```

3. Copy all the downloaded files into this directory

4. Commit and push:
```bash
git add .
git commit -m "Add complete reconciliation agent application"
git push origin main
```

## Step 2: Railway Will Auto-Deploy

Once you push to GitHub, Railway should automatically detect the changes and start building!

### What Railway will do:
1. ✅ Detect the `Dockerfile`
2. ✅ Build the Docker image
3. ✅ Install all dependencies from `requirements.txt`
4. ✅ Start the FastAPI application on port 8000
5. ✅ Connect to PostgreSQL and Redis automatically

### Monitor the Deployment:
1. Go to Railway dashboard
2. Click on "reconciliation-agent" service
3. Click "Deployments" tab
4. Watch the build logs

## Step 3: Verify It's Working

Once deployed, Railway will give you a URL like:
```
https://reconciliation-agent-production-xxxx.up.railway.app
```

Test the endpoints:

### Health Check:
```bash
curl https://your-app.railway.app/health
```

You should see:
```json
{
  "status": "healthy",
  "timestamp": "2025-10-21T...",
  "services": {
    "plaid": "connected",
    "hubspot": "connected",
    "anthropic": "connected"
  }
}
```

## Step 4: Connect Your Chase Account

1. Go to your app URL: `https://your-app.railway.app`
2. You'll need to implement a frontend or use the API directly
3. Call `POST /plaid/link` to get a link token
4. Use Plaid Link to connect your Chase account
5. Exchange the public token with `POST /plaid/exchange`

## Step 5: Run Your First Reconciliation

```bash
curl -X POST https://your-app.railway.app/reconcile \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2025-01-01",
    "end_date": "2025-10-21",
    "auto_approve_threshold": 95.0
  }'
```

## Troubleshooting

### Build Fails
- Check Railway logs for errors
- Verify all environment variables are set
- Make sure Dockerfile is in the root directory

### No Transactions Found
- Ensure you've connected a bank account via Plaid Link
- Check that `PLAID_ACCESS_TOKEN` is set
- Verify the date range

### Can't Connect to HubSpot
- Verify `HUBSPOT_API_KEY` is correct
- Check that the private app has the right scopes
- Look for API errors in Railway logs

## Environment Variables Checklist

Make sure these are set in Railway:

- ✅ `PLAID_CLIENT_ID`
- ✅ `PLAID_SECRET`
- ✅ `PLAID_ENV` (sandbox)
- ✅ `HUBSPOT_API_KEY`
- ✅ `ANTHROPIC_API_KEY`
- ✅ `DATABASE_URL` (auto-generated)
- ✅ `REDIS_URL` (auto-generated)

## Next Steps

1. **Build a Web Dashboard** - Create a frontend to visualize matches
2. **Schedule Automatic Runs** - Set up daily reconciliation
3. **Add Email Notifications** - Get alerts for new matches
4. **Implement Webhooks** - Real-time updates from Plaid/HubSpot
5. **Switch to Production** - Move from sandbox to live bank connections

## Support

If you encounter issues:
1. Check Railway deployment logs
2. Verify all API keys are correct
3. Test each service individually (Plaid, HubSpot, Anthropic)
4. Check that databases are connected

---

🎉 **Your reconciliation agent is ready to deploy!**
