"""
Reconciliation Agent - Main Application
AI-powered accounting reconciliation system
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional
import os
from datetime import datetime, timedelta
import uvicorn

# Import our modules
from matching_engine import ReconciliationEngine
from integrations.plaid_client import PlaidClient
from integrations.hubspot_client import HubSpotClient

# Initialize FastAPI app
app = FastAPI(
    title="Reconciliation Agent API",
    description="AI-powered accounting reconciliation system",
    version="1.0.0"
)

# Setup templates
templates = Jinja2Templates(directory="templates")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize clients
plaid_client = PlaidClient(
    client_id=os.getenv("PLAID_CLIENT_ID"),
    secret=os.getenv("PLAID_SECRET"),
    environment=os.getenv("PLAID_ENV", "sandbox")
)

hubspot_client = HubSpotClient(
    api_key=os.getenv("HUBSPOT_API_KEY")
)

# Initialize matching engine
matching_engine = ReconciliationEngine(
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
)

# Pydantic models
class MatchRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    auto_approve_threshold: float = 95.0

class MatchResult(BaseModel):
    transaction_id: str
    invoice_id: str
    confidence: float
    amount: float
    status: str
    matched_at: datetime

class HealthCheck(BaseModel):
    status: str
    timestamp: datetime
    services: dict

# Routes
@app.get("/", response_model=dict)
async def root():
    """Root endpoint"""
    return {
        "message": "Reconciliation Agent API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "connect_bank": "/connect",
            "reconcile": "/reconcile",
            "transactions": "/transactions",
            "invoices": "/invoices"
        }
    }

@app.get("/connect", response_class=HTMLResponse)
async def connect_page(request: Request):
    """
    Serve the Plaid Link connection page
    """
    return templates.TemplateResponse("connect.html", {"request": request})

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Health check endpoint"""
    services = {
        "plaid": "connected" if plaid_client.client_id else "disconnected",
        "hubspot": "connected" if hubspot_client.api_key else "disconnected",
        "anthropic": "connected" if matching_engine.anthropic_api_key else "disconnected"
    }
    
    return {
        "status": "healthy",
        "timestamp": datetime.now(),
        "services": services
    }

@app.post("/reconcile", response_model=dict)
async def run_reconciliation(request: MatchRequest, background_tasks: BackgroundTasks):
    """
    Run reconciliation between bank transactions and invoices
    """
    try:
        # Set date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)  # Default 90 days
        
        if request.start_date:
            start_date = datetime.fromisoformat(request.start_date)
        if request.end_date:
            end_date = datetime.fromisoformat(request.end_date)
        
        # Fetch transactions from Plaid
        transactions = await plaid_client.get_transactions(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d")
        )
        
        # Fetch invoices from HubSpot
        invoices = await hubspot_client.get_invoices()
        
        # Run matching engine
        matches = matching_engine.match_transactions_to_invoices(
            transactions=transactions,
            invoices=invoices,
            confidence_threshold=request.auto_approve_threshold
        )
        
        # Auto-approve high confidence matches
        auto_approved = []
        for match in matches:
            if match['confidence'] >= request.auto_approve_threshold:
                # Update HubSpot
                await hubspot_client.update_invoice_status(
                    invoice_id=match['invoice_id'],
                    status='paid',
                    payment_date=match['transaction_date']
                )
                auto_approved.append(match)
        
        return {
            "status": "success",
            "total_transactions": len(transactions),
            "total_invoices": len(invoices),
            "matches_found": len(matches),
            "auto_approved": len(auto_approved),
            "matches": matches
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/transactions", response_model=dict)
async def get_transactions(days: int = 30):
    """
    Get recent bank transactions
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        transactions = await plaid_client.get_transactions(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d")
        )
        
        return {
            "status": "success",
            "count": len(transactions),
            "transactions": transactions
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/invoices", response_model=dict)
async def get_invoices():
    """
    Get open invoices from HubSpot
    """
    try:
        invoices = await hubspot_client.get_invoices()
        
        return {
            "status": "success",
            "count": len(invoices),
            "invoices": invoices
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/plaid/link")
async def create_link_token():
    """
    Create Plaid Link token for connecting bank accounts
    """
    try:
        link_token = await plaid_client.create_link_token()
        return {
            "status": "success",
            "link_token": link_token
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/plaid/exchange")
async def exchange_public_token(public_token: str):
    """
    Exchange Plaid public token for access token
    """
    try:
        access_token = await plaid_client.exchange_public_token(public_token)
        return {
            "status": "success",
            "message": "Bank account connected successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
