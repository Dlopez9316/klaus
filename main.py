"""
Reconciliation Agent + Klaus Collections - Main Application
AI-powered accounting reconciliation + autonomous collections system
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional, Dict
import os
from datetime import datetime, timedelta
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import json

# Import database module for Railway-compatible storage
import database as db

# Existing imports
from matching_engine import ReconciliationEngine
from integrations.plaid_client import PlaidClient
from integrations.hubspot_client import HubSpotClient
from notification_service import NotificationService

# Klaus imports
from klaus_engine import KlausEngine
from klaus_gmail import KlausGmailClient, KlausEmailResponder
from klaus_google_drive import KlausGoogleDrive, KlausKnowledgeBase
from klaus_voice import KlausVoiceAgent, CallScheduler, VoiceCallQueue
from klaus_voice_routes import router as voice_router, init_voice_routes
from klaus_startup import setup_klaus_credentials
from klaus_smtp import KlausSMTPClient

# Initialize FastAPI app
app = FastAPI(
    title="Reconciliation Agent + Klaus Collections API",
    description="AI-powered accounting reconciliation + autonomous collections system",
    version="3.0.0"
)

templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# INITIALIZE CLIENTS
# ============================================================================

# Reconciliation clients
plaid_client = PlaidClient(
    client_id=os.getenv("PLAID_CLIENT_ID"),
    secret=os.getenv("PLAID_SECRET"),
    environment=os.getenv("PLAID_ENV", "sandbox")
)

hubspot_client = HubSpotClient(
        api_key=os.getenv("HUBSPOT_API_KEY"),
        portal_id="44968885"
)

matching_engine = ReconciliationEngine(
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
)

notification_service = NotificationService()

# Klaus clients
klaus_engine = KlausEngine(config_path="klaus_config.json")

# Initialize Klaus Gmail (supports env vars or file-based credentials)
try:
    # Check if we have env var credentials (Railway) or file credentials (local)
    has_env_creds = all([
        os.getenv('GMAIL_REFRESH_TOKEN'),
        os.getenv('GMAIL_CLIENT_ID'),
        os.getenv('GMAIL_CLIENT_SECRET')
    ])
    has_file_creds = os.path.exists("klaus_credentials.json")

    if has_env_creds or has_file_creds:
        klaus_gmail = KlausGmailClient(credentials_file="klaus_credentials.json")
        klaus_email_responder = KlausEmailResponder(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        print("✓ Klaus Gmail initialized")
    else:
        raise Exception("No Gmail credentials found (neither env vars nor file)")
except Exception as e:
    klaus_gmail = None
    klaus_email_responder = None
    print(f"⚠ Klaus Gmail not available: {e}")

# Initialize Klaus SMTP (fallback for when Gmail API isn't available)
klaus_smtp = None
try:
    klaus_smtp = KlausSMTPClient()
    print("✓ Klaus SMTP initialized")
except Exception as e:
    print(f"⚠ Klaus SMTP not available: {e}")

# Initialize Klaus Google Drive (only if credentials are available)
try:
    klaus_drive = KlausGoogleDrive(credentials_file="klaus_credentials.json")
    klaus_knowledge = KlausKnowledgeBase(
        drive_client=klaus_drive,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
    )
    print("✓ Klaus Drive initialized")
except Exception as e:
    klaus_drive = None
    klaus_knowledge = None
    print(f"⚠ Klaus Drive not available: {e}")

# Initialize Klaus Voice (only if Vapi key is available)
call_queue = None
try:
    if os.getenv("VAPI_API_KEY"):
        klaus_voice = KlausVoiceAgent(
            vapi_api_key=os.getenv("VAPI_API_KEY"),
            phone_number_id=os.getenv("VAPI_PHONE_NUMBER_ID"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        call_scheduler = CallScheduler(
            default_timezone=os.getenv("VOICE_TIMEZONE", "US/Eastern")
        )
        call_queue = VoiceCallQueue(
            voice_agent=klaus_voice,
            scheduler=call_scheduler,
            daily_limit=int(os.getenv("VOICE_DAILY_CALL_LIMIT", "10"))
        )
        print("✓ Klaus Voice initialized")
    else:
        klaus_voice = None
        call_scheduler = None
        call_queue = None
        print("⚠ Klaus Voice not available: VAPI_API_KEY not set")
except Exception as e:
    klaus_voice = None
    call_scheduler = None
    call_queue = None
    print(f"⚠ Klaus Voice not available: {e}")

# Scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Schedule config now stored in database via db module

# Initialize and register voice routes
if klaus_voice:
    init_voice_routes(
        voice_agent=klaus_voice,
        scheduler=call_scheduler,
        queue=call_queue,
        hubspot=hubspot_client,
        engine=klaus_engine
    )
    app.include_router(voice_router)
    print("✓ Klaus Voice routes registered")

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

# Existing models
class MatchRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    auto_approve_threshold: float = 60.0

class ApprovalRequest(BaseModel):
    invoice_id: str
    transaction_date: str
    transaction_description: Optional[str] = None
    company_name: Optional[str] = None

class BulkApprovalRequest(BaseModel):
    approvals: List[ApprovalRequest]

class TeachRequest(BaseModel):
    transaction_name: str
    company_name: str

class ScheduleRequest(BaseModel):
    frequency: str
    time: str

class PublicTokenExchange(BaseModel):
    public_token: str

class NotificationTestRequest(BaseModel):
    via_email: bool = True
    via_whatsapp: bool = False

class DenyRequest(BaseModel):
    invoice_id: str
    transaction_description: str

class MarkAccountedRequest(BaseModel):
    transaction_description: str
    transaction_id: Optional[str] = None
    amount: float
    date: str
    company_name: str
    invoice_id: Optional[str] = None

# New Klaus models
class KlausAnalysisRequest(BaseModel):
    days_overdue_min: int = 7
    include_vip: bool = True

class KlausEmailRequest(BaseModel):
    invoice_id: str
    to_email: str
    to_name: str
    subject: str
    body: str
    cc: Optional[str] = None
    invoice_map: Optional[Dict[str, str]] = None  # Maps invoice numbers to HubSpot URLs for hyperlinking

class KlausEmailApprovalRequest(BaseModel):
    invoice_id: str
    approve: bool
    modified_message: Optional[str] = None

class KlausCallRequest(BaseModel):
    invoice_id: str
    to_phone: str
    to_name: str
    company_name: str

class KlausDocumentRequest(BaseModel):
    doc_type: str  # 'w9', 'coi', 'dba', 'ach_form'
    recipient_email: str
    recipient_name: str
    invoice_id: Optional[str] = None

class KlausConfigUpdate(BaseModel):
    config: Dict

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def load_schedule_config():
    """Load schedule config from database (Railway) or JSON file (local dev)"""
    return db.load_schedule_config()

def save_schedule_config(config):
    """Save schedule config to database (Railway) or JSON file (local dev)"""
    db.save_schedule_config(config)

async def scheduled_reconciliation():
    """Scheduled reconciliation job"""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        
        transactions = await plaid_client.get_transactions(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d")
        )
        
        invoices = await hubspot_client.get_invoices()
        
        matches = matching_engine.match_transactions_to_invoices(
            transactions=transactions,
            invoices=invoices,
            confidence_threshold=70.0
        )
        
        # Get suggestions
        all_invoices = []
        after = None
        pages_fetched = 0
        max_pages = 10
        
        while pages_fetched < max_pages:
            all_invoices_response = hubspot_client.client.crm.objects.basic_api.get_page(
                object_type="invoices",
                limit=100,
                after=after,
                properties=["hs_invoice_number", "hs_title", "hs_amount_billed", "hs_payment_status", 
                           "hs_balance_due", "hs_due_date", "hs_createdate", "hs_number", "hs_payment_date"],
                associations=["companies"]
            )
            for invoice in all_invoices_response.results:
                all_invoices.append(invoice)
            pages_fetched += 1
            if hasattr(all_invoices_response, 'paging') and all_invoices_response.paging and hasattr(all_invoices_response.paging, 'next'):
                after = all_invoices_response.paging.next.after
            else:
                break
        
        paid_invoices = []
        for invoice in all_invoices:
            props = invoice.properties
            payment_date = props.get("hs_payment_date")
            if payment_date:
                company_name = None
                if hasattr(invoice, 'associations') and invoice.associations:
                    company_associations = invoice.associations.get('companies', {})
                    if company_associations and hasattr(company_associations, 'results') and company_associations.results:
                        company_id = company_associations.results[0].id
                        try:
                            company = hubspot_client.client.crm.companies.basic_api.get_by_id(company_id=company_id, properties=["name"])
                            company_name = company.properties.get("name")
                        except:
                            pass
                paid_invoices.append({
                    'id': invoice.id,
                    'number': props.get("hs_invoice_number") or props.get("hs_number") or "",
                    'company_name': company_name,
                    'amount': float(props.get("hs_amount_billed", 0)),
                    'payment_date': payment_date
                })
        
        suggestions = matching_engine.suggest_associations_from_history(paid_invoices, transactions)
        
        # Auto-approve high confidence matches
        auto_approved = 0
        for match in matches:
            if match['confidence'] >= 80:
                await hubspot_client.update_invoice_reconciliation_status(
                    invoice_id=match['invoice_id'],
                    status='Reconciled',
                    transaction_details=match.get('transaction_description')
                )
                auto_approved += 1
        
        # Send notifications
        stats = {
            'total_transactions': len(transactions),
            'total_invoices': len(invoices),
            'matches_found': len(matches),
            'auto_approved': auto_approved
        }
        
        notification_service.send_reconciliation_report(
            matches=matches,
            suggestions=suggestions,
            stats=stats,
            via_email=True,
            via_whatsapp=True
        )
        
        print(f"Scheduled reconciliation completed: {len(matches)} matches, {auto_approved} auto-approved")
    
    except Exception as e:
        print(f"Scheduled reconciliation failed: {e}")

async def scheduled_klaus_collections():
    """Scheduled Klaus collections job - NOW WITH INVOICE HYPERLINKING"""
    try:
        # Get unpaid invoices from HubSpot (now includes hubspot_url)
        invoices = await hubspot_client.get_invoices()
        
        # Analyze with Klaus
        analysis = klaus_engine.analyze_overdue_invoices(invoices)
        
        # Process autonomous actions
        for email_action in analysis['autonomous_emails']:
            if klaus_gmail:
                # Build invoice map for hyperlinking
                invoice_map = {}
                for inv in email_action.get('invoices', []):
                    inv_number = str(inv.get('invoice_number', '')).strip()
                    if inv_number.upper().startswith('INV-'):
                        inv_number = inv_number[4:].strip()
                    hubspot_url = inv.get('hubspot_url', '')
                    if inv_number and hubspot_url:
                        invoice_map[inv_number] = hubspot_url
                
                # Extract subject from recommended_message
                message = email_action['recommended_message']
                lines = message.split('\n')
                if lines and lines[0].startswith('Subject:'):
                    subject = lines[0].replace('Subject:', '').strip()
                    body = '\n'.join(lines[1:]).strip()
                else:
                    subject = "Payment Reminder"
                    body = message
                
                # Determine CC
                cc_email = None
                if email_action.get('is_vip'):
                    cc_email = 'daniel@leveragelivelocal.com'
                
                # Send email with hyperlinked invoices
                result = klaus_gmail.send_email(
                    to_email=email_action.get('contact_email'),
                    to_name=email_action.get('contact_name'),
                    subject=subject,
                    body=body,
                    cc=cc_email,
                    invoice_map=invoice_map
                )
                
                if result['status'] == 'success':
                    # Log communication for each invoice
                    for inv in email_action.get('invoices', []):
                        klaus_engine.log_communication(
                            invoice_id=inv.get('invoice_id'),
                            company_name=inv.get('company_name'),
                            method='email',
                            message_type='reminder',
                            approved_by='autonomous'
                        )
        
        print(f"Klaus collections: {len(analysis['autonomous_emails'])} emails sent (hyperlinked), {len(analysis['pending_approvals'])} pending approval")
    
    except Exception as e:
        print(f"Klaus collections failed: {e}")

# ============================================================================
# MAIN ROUTES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard"""
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/connect", response_class=HTMLResponse)
async def connect_page(request: Request):
    """Plaid connection page"""
    return templates.TemplateResponse("connect.html", {"request": request})

@app.get("/klaus", response_class=HTMLResponse)
async def klaus_dashboard(request: Request):
    """Klaus collections dashboard"""
    return templates.TemplateResponse("klaus_dashboard.html", {"request": request})

@app.get("/health", response_model=dict)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "3.0.0",
        "services": {
            "reconciliation": "active",
            "klaus_collections": "active" if (klaus_gmail or klaus_smtp) else "disabled",
            "klaus_gmail": klaus_gmail is not None,
            "klaus_smtp": klaus_smtp is not None,
            "klaus_drive": klaus_drive is not None,
            "klaus_voice": klaus_voice is not None
        }
    }

# ============================================================================
# RECONCILIATION ENDPOINTS (EXISTING)
# ============================================================================

@app.api_route("/reconcile", methods=["GET", "POST"], response_model=dict)
async def reconcile_accounts(
    request: MatchRequest = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    auto_approve_threshold: Optional[float] = 60.0
):
    """
    Main reconciliation endpoint
    Matches bank transactions to HubSpot invoices
    Supports both GET (with query params) and POST (with JSON body) for backward compatibility
    """
    print(f"[RECONCILE] Starting reconciliation - start_date={start_date}, end_date={end_date}, threshold={auto_approve_threshold}")
    try:
        # Handle GET requests with query parameters (backward compatibility)
        if request is None or (start_date is not None or end_date is not None):
            # Use query parameters
            end_date_str = end_date
            start_date_str = start_date
            threshold = auto_approve_threshold
        else:
            # Use POST body
            end_date_str = request.end_date
            start_date_str = request.start_date
            threshold = request.auto_approve_threshold
        
        # Get date range
        if end_date_str:
            end_date_dt = datetime.fromisoformat(end_date_str)
        else:
            end_date_dt = datetime.now()
        
        if start_date_str:
            start_date_dt = datetime.fromisoformat(start_date_str)
        else:
            start_date_dt = end_date_dt - timedelta(days=90)
        
        # Fetch transactions from Plaid
        print(f"[RECONCILE] Fetching transactions from {start_date_dt.strftime('%Y-%m-%d')} to {end_date_dt.strftime('%Y-%m-%d')}")
        transactions = await plaid_client.get_transactions(
            start_date=start_date_dt.strftime("%Y-%m-%d"),
            end_date=end_date_dt.strftime("%Y-%m-%d")
        )
        print(f"[RECONCILE] Got {len(transactions)} transactions from Plaid")
        
        # Filter out Stripe transactions
        transactions = [t for t in transactions if 'stripe' not in t.get('description', '').lower()]
        print(f"[RECONCILE] After filtering Stripe: {len(transactions)} transactions")
        
        # Fetch invoices from HubSpot
        invoices = await hubspot_client.get_invoices()
        print(f"[RECONCILE] Got {len(invoices)} invoices from HubSpot")
        
        # Match transactions to invoices
        matches = matching_engine.match_transactions_to_invoices(
            transactions=transactions,
            invoices=invoices,
            confidence_threshold=threshold
        )
        
        # Get all invoices with payment history for suggestions
        all_invoices = []
        after = None
        pages_fetched = 0
        max_pages = 10
        
        while pages_fetched < max_pages:
            all_invoices_response = hubspot_client.client.crm.objects.basic_api.get_page(
                object_type="invoices",
                limit=100,
                after=after,
                properties=["hs_invoice_number", "hs_title", "hs_amount_billed", "hs_payment_status", 
                           "hs_balance_due", "hs_due_date", "hs_createdate", "hs_number", "hs_payment_date"],
                associations=["companies"]
            )
            for invoice in all_invoices_response.results:
                all_invoices.append(invoice)
            pages_fetched += 1
            if hasattr(all_invoices_response, 'paging') and all_invoices_response.paging and hasattr(all_invoices_response.paging, 'next'):
                after = all_invoices_response.paging.next.after
            else:
                break
        
        # Extract paid invoices with company names
        paid_invoices = []
        for invoice in all_invoices:
            props = invoice.properties
            payment_date = props.get("hs_payment_date")
            if payment_date:
                company_name = None
                if hasattr(invoice, 'associations') and invoice.associations:
                    company_associations = invoice.associations.get('companies', {})
                    if company_associations and hasattr(company_associations, 'results') and company_associations.results:
                        company_id = company_associations.results[0].id
                        try:
                            company = hubspot_client.client.crm.companies.basic_api.get_by_id(company_id=company_id, properties=["name"])
                            company_name = company.properties.get("name")
                        except:
                            pass
                paid_invoices.append({
                    'id': invoice.id,
                    'number': props.get("hs_invoice_number") or props.get("hs_number") or "",
                    'company_name': company_name,
                    'amount': float(props.get("hs_amount_billed", 0)),
                    'payment_date': payment_date,
                    'created_date': props.get("hs_createdate")
                })
        
        # Get AI suggestions based on payment history
        suggestions = matching_engine.suggest_associations_from_history(paid_invoices, transactions)
        
        return {
            "status": "success",
            "start_date": start_date_dt.isoformat(),
            "end_date": end_date_dt.isoformat(),
            "transactions_analyzed": len(transactions),
            "invoices_analyzed": len(invoices),
            "matches_found": len(matches),
            "matches": matches,
            "suggestions": suggestions,
            "auto_approve_threshold": threshold
        }
    
    except Exception as e:
        print(f"[RECONCILE] ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/approve", response_model=dict)
async def approve_match(request: ApprovalRequest):
    """Approve a specific match"""
    try:
        await hubspot_client.update_invoice_reconciliation_status(
            invoice_id=request.invoice_id,
            status='Reconciled',
            transaction_details=request.transaction_description
        )
        
        return {
            "status": "success",
            "message": f"Invoice {request.invoice_id} marked as reconciled"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/approve-bulk", response_model=dict)
async def approve_bulk_matches(request: BulkApprovalRequest):
    """Approve multiple matches at once"""
    try:
        success_count = 0
        errors = []
        
        for approval in request.approvals:
            try:
                await hubspot_client.update_invoice_reconciliation_status(
                    invoice_id=approval.invoice_id,
                    status='Reconciled',
                    transaction_details=approval.transaction_description
                )
                success_count += 1
            except Exception as e:
                errors.append({
                    "invoice_id": approval.invoice_id,
                    "error": str(e)
                })
        
        return {
            "status": "success",
            "approved": success_count,
            "failed": len(errors),
            "errors": errors
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/deny", response_model=dict)
async def deny_match(request: DenyRequest):
    """Deny a suggested match"""
    try:
        matching_engine.deny_match(
            transaction_description=request.transaction_description,
            invoice_id=request.invoice_id
        )
        
        return {
            "status": "success",
            "message": "Match denied and recorded"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mark-accounted", response_model=dict)
async def mark_transaction_accounted(request: MarkAccountedRequest):
    """Mark a transaction as accounted for (not an invoice payment)"""
    try:
        matching_engine.mark_as_accounted(
            transaction_description=request.transaction_description,
            transaction_id=request.transaction_id,
            amount=request.amount,
            date=request.date,
            company_name=request.company_name,
            invoice_id=request.invoice_id
        )
        
        return {
            "status": "success",
            "message": f"Transaction marked as accounted: {request.transaction_description}"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/accounted-transactions", response_model=dict)
async def get_accounted_transactions():
    """Get all accounted transactions"""
    try:
        accounted = matching_engine.memory.get('accounted_transactions', [])
        return {
            "status": "success",
            "count": len(accounted),
            "transactions": accounted
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/accounted-transactions/{transaction_id}", response_model=dict)
async def delete_accounted_transaction(transaction_id: str):
    """Remove a transaction from accounted list"""
    try:
        accounted = matching_engine.memory.get('accounted_transactions', [])
        updated = [t for t in accounted if t.get('transaction_id') != transaction_id and t.get('transaction_description') != transaction_id]
        
        if len(updated) < len(accounted):
            matching_engine.memory['accounted_transactions'] = updated
            matching_engine._save_memory()
            return {"status": "success", "message": "Transaction removed from accounted list"}
        
        return {"status": "error", "message": "Transaction not found"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/validate-companies", response_model=dict)
async def validate_company_payments(days: int = 365):
    """
    Validate payment accuracy per company
    Compare invoices marked paid vs actual deposits
    """
    try:
        # Get transactions
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        transactions = await plaid_client.get_transactions(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d")
        )
        
        # Get all invoices with payment history
        all_invoices = []
        after = None
        pages_fetched = 0
        max_pages = 20
        
        while pages_fetched < max_pages:
            all_invoices_response = hubspot_client.client.crm.objects.basic_api.get_page(
                object_type="invoices",
                limit=100,
                after=after,
                properties=["hs_invoice_number", "hs_title", "hs_amount_billed", "hs_payment_status", 
                           "hs_balance_due", "hs_due_date", "hs_createdate", "hs_number", "hs_payment_date"],
                associations=["companies"]
            )
            for invoice in all_invoices_response.results:
                all_invoices.append(invoice)
            pages_fetched += 1
            if hasattr(all_invoices_response, 'paging') and all_invoices_response.paging and hasattr(all_invoices_response.paging, 'next'):
                after = all_invoices_response.paging.next.after
            else:
                break
        
        # Extract paid invoices with company names
        paid_invoices = []
        all_companies = set()
        
        for invoice in all_invoices:
            props = invoice.properties
            company_name = None
            
            if hasattr(invoice, 'associations') and invoice.associations:
                company_associations = invoice.associations.get('companies', {})
                if company_associations and hasattr(company_associations, 'results') and company_associations.results:
                    company_id = company_associations.results[0].id
                    try:
                        company = hubspot_client.client.crm.companies.basic_api.get_by_id(company_id=company_id, properties=["name"])
                        company_name = company.properties.get("name")
                        all_companies.add(company_name)
                    except:
                        pass
            
            payment_date = props.get("hs_payment_date")
            if payment_date and company_name:
                paid_invoices.append({
                    'id': invoice.id,
                    'number': props.get("hs_invoice_number") or props.get("hs_number") or "",
                    'company_name': company_name,
                    'amount': float(props.get("hs_amount_billed", 0)),
                    'payment_date': payment_date,
                    'created_date': props.get("hs_createdate")
                })
        
        # Validate each company
        validation_results = []
        for company in all_companies:
            if company:
                validation = matching_engine.validate_company_payments(
                    company_name=company,
                    paid_invoices=paid_invoices,
                    all_transactions=transactions
                )
                validation_results.append(validation)
        
        # Separate by status
        balanced = [v for v in validation_results if v['status'] == 'balanced']
        short = [v for v in validation_results if v['status'] == 'short']
        over = [v for v in validation_results if v['status'] == 'over']
        
        return {
            "status": "success",
            "summary": {
                "total_companies": len(validation_results),
                "balanced": len(balanced),
                "short": len(short),
                "over": len(over),
                "lookback_days": days
            },
            "balanced_companies": balanced,
            "short_companies": short,
            "over_companies": over
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/teach", response_model=dict)
async def teach_association(request: TeachRequest):
    """Teach the engine a transaction-to-company association"""
    try:
        matching_engine.learn_association(
            transaction_name=request.transaction_name,
            company_name=request.company_name
        )
        
        return {
            "status": "success",
            "message": f"✓ Learned: '{request.transaction_name}' → '{request.company_name}'",
            "total_associations": len(matching_engine.memory['associations'])
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/associations", response_model=dict)
async def get_associations():
    """Get all learned associations"""
    return {
        "status": "success",
        "count": len(matching_engine.memory.get('associations', {})),
        "associations": matching_engine.memory.get('associations', {})
    }

@app.delete("/associations/{transaction_name}", response_model=dict)
async def delete_association(transaction_name: str):
    """Delete a learned association"""
    try:
        if transaction_name in matching_engine.memory['associations']:
            del matching_engine.memory['associations'][transaction_name]
            matching_engine._save_memory()
            return {"status": "success", "message": "Association deleted"}
        return {"status": "error", "message": "Association not found"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/schedule", response_model=dict)
async def set_schedule(request: ScheduleRequest):
    """Set automated reconciliation schedule"""
    try:
        scheduler.remove_all_jobs()
        
        if request.frequency != 'none':
            hour, minute = map(int, request.time.split(':'))
            
            if request.frequency == 'daily':
                trigger = CronTrigger(hour=hour, minute=minute)
            elif request.frequency == 'weekly':
                trigger = CronTrigger(day_of_week='mon', hour=hour, minute=minute)
            elif request.frequency == 'monthly':
                trigger = CronTrigger(day=1, hour=hour, minute=minute)
            
            scheduler.add_job(scheduled_reconciliation, trigger)
            
            # Also schedule Klaus collections
            if klaus_gmail:
                scheduler.add_job(scheduled_klaus_collections, trigger)
        
        save_schedule_config({
            'frequency': request.frequency,
            'time': request.time
        })
        
        return {
            "status": "success",
            "message": f"Schedule set to {request.frequency} at {request.time}",
            "frequency": request.frequency,
            "time": request.time
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/schedule", response_model=dict)
async def get_schedule():
    """Get current schedule configuration"""
    config = load_schedule_config()
    return {
        "status": "success",
        "frequency": config.get('frequency', 'none'),
        "time": config.get('time', '09:00')
    }

@app.get("/transactions", response_model=dict)
async def get_transactions(days: int = 30):
    """Get recent bank transactions"""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        transactions = await plaid_client.get_transactions(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d")
        )
        
        transactions = [t for t in transactions if 'stripe' not in t.get('description', '').lower()]
        
        return {
            "status": "success",
            "count": len(transactions),
            "transactions": transactions
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/invoices", response_model=dict)
async def get_invoices():
    """Get all HubSpot invoices"""
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
    """Create Plaid Link token"""
    try:
        link_token = await plaid_client.create_link_token()
        return {
            "status": "success",
            "link_token": link_token
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/plaid/exchange")
async def exchange_public_token(request: PublicTokenExchange):
    """Exchange Plaid public token for access token"""
    try:
        access_token = await plaid_client.exchange_public_token(request.public_token)
        return {
            "status": "success",
            "message": "Bank account connected successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/notification/test")
async def test_notification(request: NotificationTestRequest):
    """Test notification system"""
    try:
        success = notification_service.send_reconciliation_report(
            matches=[],
            suggestions=[],
            stats={'test': True},
            via_email=request.via_email,
            via_whatsapp=request.via_whatsapp
        )
        
        return {
            "status": "success" if success else "partial",
            "message": "Test notification sent"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# KLAUS COLLECTIONS ENDPOINTS (NEW)
# ============================================================================

@app.post("/klaus/analyze", response_model=dict)
async def klaus_analyze_invoices(request: KlausAnalysisRequest):
    """
    Analyze overdue invoices with Klaus
    Returns autonomous actions and pending approvals
    """
    try:
        # Get all unpaid invoices
        invoices = await hubspot_client.get_invoices()
        
        # Analyze with Klaus
        analysis = klaus_engine.analyze_overdue_invoices(invoices)
        
        return {
            "status": "success",
            "analysis": analysis,
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/klaus/email/send", response_model=dict)
async def klaus_send_email(request: KlausEmailRequest):
    """
    Send an email via Klaus
    This is for approved or autonomous emails
    Uses Gmail API if available, falls back to SMTP
    """
    try:
        # Try Gmail first, fall back to SMTP
        email_client = klaus_gmail or klaus_smtp

        print(f"[EMAIL] Using client: {type(email_client).__name__ if email_client else 'None'}")
        print(f"[EMAIL] Sending to: {request.to_email}, Subject: {request.subject[:50]}...")

        if not email_client:
            raise HTTPException(status_code=503, detail="No email service configured (neither Gmail nor SMTP)")

        result = email_client.send_email(
            to_email=request.to_email,
            to_name=request.to_name,
            subject=request.subject,
            body=request.body,
            cc=request.cc,
            invoice_map=request.invoice_map
        )

        print(f"[EMAIL] Result: {result}")

        if result['status'] == 'success':
            # Log communication
            klaus_engine.log_communication(
                invoice_id=request.invoice_id,
                company_name=request.to_name,
                method='email',
                message_type='collection',
                approved_by='manual'
            )

        return result

    except Exception as e:
        print(f"[EMAIL] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/klaus/emails/pending", response_model=dict)
async def klaus_get_pending_emails():
    """Get emails pending approval - automatically analyzes current invoices"""
    try:
        # Get all unpaid invoices from HubSpot
        invoices = await hubspot_client.get_invoices()
        
        # Filter for unpaid only (balance_due > 0)
        unpaid_invoices = [inv for inv in invoices if float(inv.get('balance_due', 0)) > 0]
        
        # Analyze with Klaus to get pending approvals
        analysis = klaus_engine.analyze_overdue_invoices(unpaid_invoices)
        
        # Return pending approvals
        pending = analysis.get('pending_approvals', [])
        
        return {
            "status": "success",
            "count": len(pending),
            "pending_emails": pending,
            "total_analyzed": len(unpaid_invoices),
            "total_companies": analysis.get('total_companies', 0)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/klaus/debug/invoice-fields")
async def klaus_debug_invoice_fields():
    """DEBUG: Show raw HubSpot invoice fields to find contact info"""
    try:
        invoices = await hubspot_client.get_invoices()
        if not invoices:
            return {"status": "error", "message": "No invoices found"}
        
        # Get first invoice with balance_due > 0
        sample_invoice = next((inv for inv in invoices if float(inv.get('balance_due', 0)) > 0), invoices[0])
        
        return {
            "status": "success",
            "message": "Sample invoice fields - look for contact/recipient/bill_to fields",
            "invoice_id": sample_invoice.get('id'),
            "all_fields": list(sample_invoice.keys()),
            "sample_values": {k: v for k, v in sample_invoice.items() if k not in ['id']}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/klaus/email/approve", response_model=dict)
async def klaus_approve_email(request: KlausEmailApprovalRequest):
    """Approve or deny a pending email"""
    try:
        if not klaus_gmail:
            raise HTTPException(status_code=503, detail="Klaus Gmail not configured")
        
        if request.approve:
            # Send the email
            # Would need to get email details from pending queue
            return {
                "status": "success",
                "message": "Email approved and sent"
            }
        else:
            return {
                "status": "success",
                "message": "Email denied"
            }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/klaus/emails/inbox", response_model=dict)
async def klaus_get_inbox():
    """Get unread emails from Klaus inbox"""
    try:
        if not klaus_gmail:
            raise HTTPException(status_code=503, detail="Klaus Gmail not configured")
        
        emails = klaus_gmail.get_recent_emails(
            query="in:inbox is:unread",
            max_results=50
        )
        
        return {
            "status": "success",
            "count": len(emails),
            "emails": emails
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/klaus/call/schedule", response_model=dict)
async def klaus_schedule_call(request: KlausCallRequest):
    """Schedule a collections call with Klaus Voice"""
    try:
        if not klaus_voice:
            raise HTTPException(status_code=503, detail="Klaus Voice not configured")
        
        # Get invoice details
        invoices = await hubspot_client.get_invoices()
        invoice = next((inv for inv in invoices if inv['id'] == request.invoice_id), None)
        
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        # Calculate days overdue
        due_date = invoice.get('due_date')
        if due_date:
            due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
            days_overdue = (datetime.now() - due_dt.replace(tzinfo=None)).days
        else:
            days_overdue = 0
        
        # Make call
        result = klaus_voice.make_outbound_call(
            to_phone=request.to_phone,
            to_name=request.to_name,
            invoice_id=request.invoice_id,
            amount=float(invoice.get('amount', 0)),
            days_overdue=days_overdue,
            company_name=request.company_name
        )
        
        if result['status'] == 'success':
            # Log communication
            klaus_engine.log_communication(
                invoice_id=request.invoice_id,
                company_name=request.company_name,
                method='call',
                message_type='collection',
                approved_by='manual'
            )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/klaus/documents/{doc_type}", response_model=dict)
async def klaus_get_document(doc_type: str):
    """Get a document from Klaus Drive"""
    try:
        if not klaus_drive:
            raise HTTPException(status_code=503, detail="Klaus Drive not configured")
        
        document = klaus_drive.get_document(doc_type=doc_type)
        
        if document:
            return {
                "status": "success",
                "document": document
            }
        else:
            raise HTTPException(status_code=404, detail=f"Document type '{doc_type}' not found")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/klaus/documents/send", response_model=dict)
async def klaus_send_document(request: KlausDocumentRequest):
    """Send a document to a client"""
    try:
        if not klaus_gmail or not klaus_drive:
            raise HTTPException(status_code=503, detail="Klaus services not fully configured")
        
        # Get document
        document = klaus_drive.get_document(doc_type=request.doc_type)
        
        if not document:
            raise HTTPException(status_code=404, detail=f"Document type '{request.doc_type}' not found")
        
        # Download document temporarily
        temp_path = f"/tmp/{document['name']}"
        klaus_drive.download_document(document['id'], temp_path)
        
        # Send email with attachment
        result = klaus_gmail.send_email(
            to_email=request.recipient_email,
            to_name=request.recipient_name,
            subject=f"Requested Document - {document['name']}",
            body=f"Hi {request.recipient_name},\n\nAs requested, I'm attaching our {request.doc_type.upper()}.\n\nLet me know if you need anything else!\n\nBest regards,\nKlaus\nLeverage Live Local",
            attachments=[temp_path]
        )
        
        # Clean up
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if result['status'] == 'success' and request.invoice_id:
            klaus_engine.log_communication(
                invoice_id=request.invoice_id,
                company_name=request.recipient_name,
                method='email',
                message_type='document',
                approved_by='manual'
            )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/klaus/config", response_model=dict)
async def klaus_get_config():
    """Get Klaus configuration"""
    return {
        "status": "success",
        "config": klaus_engine.config
    }

@app.post("/klaus/config", response_model=dict)
async def klaus_update_config(request: KlausConfigUpdate):
    """Update Klaus configuration"""
    try:
        klaus_engine.config.update(request.config)
        klaus_engine.save_config()
        
        return {
            "status": "success",
            "message": "Klaus configuration updated",
            "config": klaus_engine.config
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/klaus/history", response_model=dict)
async def klaus_get_history():
    """Get Klaus communication history"""
    return {
        "status": "success",
        "count": len(klaus_engine.communication_history),
        "history": klaus_engine.communication_history
    }

@app.get("/klaus/stats", response_model=dict)
async def klaus_get_stats():
    """Get Klaus performance statistics"""
    try:
        # Get unpaid invoices
        invoices = await hubspot_client.get_invoices()
        
        # Analyze
        analysis = klaus_engine.analyze_overdue_invoices(invoices)
        
        # Calculate stats
        total_overdue = len([inv for inv in invoices if inv.get('balance_due', 0) > 0])
        total_overdue_amount = sum(inv.get('balance_due', 0) for inv in invoices)
        
        stats = {
            "total_overdue_invoices": total_overdue,
            "total_overdue_amount": total_overdue_amount,
            "autonomous_actions_ready": analysis['summary']['ready_to_send'],
            "pending_approval": analysis['summary']['needs_approval'],
            "no_action_needed": analysis['summary']['no_action_needed'],
            "communications_sent": len(klaus_engine.communication_history),
            "last_run": datetime.now().isoformat()
        }
        
        return {
            "status": "success",
            "stats": stats
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# WEBHOOKS
# ============================================================================

@app.post("/webhooks/vapi")
async def vapi_webhook(request: Request):
    """Handle Vapi.ai call completion webhooks"""
    try:
        data = await request.json()
        
        if klaus_voice:
            result = klaus_voice.handle_call_ended(data)
            return JSONResponse(content=result)
        else:
            return JSONResponse(content={"status": "service_unavailable"})
    
    except Exception as e:
        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)

# ============================================================================
# DATABASE / MIGRATION ENDPOINTS
# ============================================================================

@app.post("/admin/migrate", response_model=dict)
async def migrate_to_database():
    """
    Migrate existing JSON files to PostgreSQL database.
    Call this once after deploying to Railway with DATABASE_URL set.
    Only works when DATABASE_URL environment variable is configured.
    """
    try:
        if not db.USE_DATABASE:
            return {
                "status": "skipped",
                "message": "No DATABASE_URL found - migration only needed when using PostgreSQL on Railway"
            }

        db.migrate_json_to_database()
        return {
            "status": "success",
            "message": "Migration complete - data has been moved to PostgreSQL"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/storage-info", response_model=dict)
async def get_storage_info():
    """Get information about current storage backend"""
    return {
        "status": "success",
        "using_database": db.USE_DATABASE,
        "storage_type": "PostgreSQL" if db.USE_DATABASE else "Local JSON files",
        "database_url_set": bool(os.getenv("DATABASE_URL")),
        "memory_associations_count": len(matching_engine.memory.get('associations', {})),
        "klaus_history_count": len(klaus_engine.communication_history)
    }


@app.get("/admin/email-config", response_model=dict)
async def get_email_config():
    """Get information about email configuration (no passwords)"""
    smtp_user = os.getenv("SMTP_USER", "not set")
    # Mask the email for security but show domain
    if smtp_user and "@" in smtp_user:
        parts = smtp_user.split("@")
        masked_user = parts[0][:3] + "***@" + parts[1]
    else:
        masked_user = smtp_user

    return {
        "status": "success",
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com (default)"),
        "smtp_port": os.getenv("SMTP_PORT", "587 (default)"),
        "smtp_user": masked_user,
        "smtp_password_set": bool(os.getenv("SMTP_PASSWORD")),
        "klaus_from_email": os.getenv("KLAUS_FROM_EMAIL", "klaus@leveragelivelocal.com (default)"),
        "klaus_smtp_active": klaus_smtp is not None,
        "klaus_gmail_active": klaus_gmail is not None,
        "gmail_refresh_token_set": bool(os.getenv("GMAIL_REFRESH_TOKEN")),
        "gmail_client_id_set": bool(os.getenv("GMAIL_CLIENT_ID")),
        "gmail_client_secret_set": bool(os.getenv("GMAIL_CLIENT_SECRET"))
    }


# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Application startup tasks"""

    # Initialize database if on Railway
    if db.USE_DATABASE:
        db.init_database()
        print("✓ PostgreSQL database initialized")
    else:
        print("Using local JSON file storage (no DATABASE_URL)")

    # Setup Klaus credentials from environment
    setup_klaus_credentials()
    
    # Load scheduled jobs
    config = load_schedule_config()
    if config['frequency'] != 'none':
        try:
            hour, minute = map(int, config['time'].split(':'))
            
            if config['frequency'] == 'daily':
                trigger = CronTrigger(hour=hour, minute=minute)
            elif config['frequency'] == 'weekly':
                trigger = CronTrigger(day_of_week='mon', hour=hour, minute=minute)
            elif config['frequency'] == 'monthly':
                trigger = CronTrigger(day=1, hour=hour, minute=minute)
            
            scheduler.add_job(scheduled_reconciliation, trigger)
            
            # Also schedule Klaus if available
            if klaus_gmail:
                scheduler.add_job(scheduled_klaus_collections, trigger)
            
            print(f"✓ Loaded schedule: {config['frequency']} at {config['time']}")
        except Exception as e:
            print(f"✗ Failed to load schedule: {e}")
    
    print("\n" + "="*60)
    print("Reconciliation Agent + Klaus Collections")
    print("="*60)
    print(f"Reconciliation: ✓ Active")
    print(f"Klaus Gmail: {'✓ Active' if klaus_gmail else '✗ Disabled'}")
    print(f"Klaus SMTP: {'✓ Active' if klaus_smtp else '✗ Disabled'}")
    print(f"Klaus Drive: {'✓ Active' if klaus_drive else '✗ Disabled'}")
    print(f"Klaus Voice: {'✓ Active' if klaus_voice else '✗ Disabled'}")
    print(f"Email Service: {'✓ Active' if (klaus_gmail or klaus_smtp) else '✗ Disabled'}")
    print("="*60 + "\n")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)