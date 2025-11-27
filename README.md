# Reconciliation Agent

AI-powered accounting reconciliation system that automatically matches bank transactions with invoices.

## Features

- 🤖 **AI-Powered Matching** - Uses Claude AI for intelligent transaction-to-invoice matching
- 🏦 **Plaid Integration** - Fetches bank transactions automatically
- 📊 **HubSpot Integration** - Syncs with your CRM invoices
- ⚡ **Auto-Reconciliation** - Automatically marks invoices as paid
- 📈 **Confidence Scoring** - Each match includes a confidence score
- 🔄 **Background Processing** - Handles large volumes efficiently

## Architecture

```
┌─────────────┐
│   Plaid     │ ───► Bank Transactions
└─────────────┘
       │
       ▼
┌─────────────┐      ┌──────────────┐
│  Matching   │ ◄──► │  Claude AI   │
│   Engine    │      └──────────────┘
└─────────────┘
       │
       ▼
┌─────────────┐
│  HubSpot    │ ───► Update Invoices
└─────────────┘
```

## API Endpoints

### Health Check
```
GET /health
```

### Run Reconciliation
```
POST /reconcile
{
  "start_date": "2025-01-01",
  "end_date": "2025-10-21",
  "auto_approve_threshold": 95.0
}
```

### Get Transactions
```
GET /transactions?days=30
```

### Get Invoices
```
GET /invoices
```

### Plaid Link (Connect Bank)
```
POST /plaid/link
POST /plaid/exchange
```

## Deployment

This app is configured to deploy on Railway.app.

### Required Environment Variables

```
PLAID_CLIENT_ID=your_client_id
PLAID_SECRET=your_secret
PLAID_ENV=sandbox
HUBSPOT_API_KEY=your_api_key
ANTHROPIC_API_KEY=your_api_key
DATABASE_URL=auto_generated
REDIS_URL=auto_generated
```

## Tech Stack

- **FastAPI** - Modern Python web framework
- **PostgreSQL** - Database
- **Redis** - Background task queue
- **Plaid** - Banking data
- **HubSpot** - CRM integration
- **Anthropic Claude** - AI matching

## Matching Strategies

The engine uses multiple strategies to match transactions:

1. **Amount Matching** - Exact or fuzzy amount comparison
2. **Name Matching** - Fuzzy company name matching
3. **Date Proximity** - Matches based on transaction/invoice dates
4. **Invoice Number Detection** - Finds invoice numbers in descriptions
5. **AI Disambiguation** - Claude AI resolves ambiguous matches

## License

Proprietary - Leverage Live Local
