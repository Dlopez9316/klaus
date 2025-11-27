"""
Klaus Collections Integration
Extends the reconciliation agent with autonomous collections

Add this to your main.py file
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import os

from klaus_engine import KlausEngine
from klaus_gmail import KlausGmailClient, KlausEmailResponder
from klaus_google_drive import KlausGoogleDrive, KlausKnowledgeBase
from klaus_voice import KlausVoiceAgent, CallScheduler

# Create router
klaus_router = APIRouter(prefix="/klaus", tags=["Klaus Collections"])

# Initialize Klaus components
klaus_engine = KlausEngine()

# Gmail client (requires setup)
try:
    klaus_gmail = KlausGmailClient(credentials_file="klaus_credentials.json")
except:
    klaus_gmail = None
    print("Klaus Gmail not configured - email features disabled")

# Google Drive client (requires setup)
try:
    klaus_drive = KlausGoogleDrive(credentials_file="klaus_credentials.json")
    klaus_kb = KlausKnowledgeBase(
        drive_client=klaus_drive,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
    )
except:
    klaus_drive = None
    klaus_kb = None
    print("Klaus Drive not configured - document features disabled")

# Voice client (optional)
try:
    klaus_voice = KlausVoiceAgent(
        vapi_api_key=os.getenv("VAPI_API_KEY"),
        google_voice_number=os.getenv("GOOGLE_VOICE_NUMBER")
    )
    call_scheduler = CallScheduler()
except:
    klaus_voice = None
    print("Klaus Voice not configured - calling features disabled")

# Email responder
klaus_email_responder = KlausEmailResponder(
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
)


# Pydantic models
class KlausAnalysisRequest(BaseModel):
    days_lookback: int = 90

class KlausEmailRequest(BaseModel):
    invoice_id: str
    override_message: Optional[str] = None

class KlausCallRequest(BaseModel):
    invoice_id: str
    phone_number: str
    contact_name: str

class KlausApprovalRequest(BaseModel):
    action_id: str
    approved: bool
    notes: Optional[str] = None

class DriveConfigRequest(BaseModel):
    w9_folder_id: str
    coi_folder_id: str
    knowledge_base_folder_id: str
    meeting_transcripts_folder_id: str

class VoiceCallWebhook(BaseModel):
    call_id: str
    status: str
    transcript: Optional[str] = None
    duration: Optional[int] = None


# ============================================================================
# ANALYSIS ENDPOINTS
# ============================================================================

@klaus_router.post("/analyze", response_model=dict)
async def analyze_collections(
    request: KlausAnalysisRequest,
    hubspot_client  # Pass from main app
):
    """
    Analyze all overdue invoices and determine collections actions
    
    Returns:
    - Autonomous actions Klaus can take
    - Actions requiring approval
    """
    
    try:
        # Get all unpaid invoices from HubSpot
        end_date = datetime.now()
        start_date = end_date - timedelta(days=request.days_lookback)
        
        invoices = await hubspot_client.get_invoices()
        
        # Filter to unpaid only
        unpaid_invoices = [
            inv for inv in invoices 
            if inv.get('payment_status') != 'Paid' and float(inv.get('balance_due', 0)) > 0
        ]
        
        # Analyze with Klaus
        analysis = klaus_engine.analyze_overdue_invoices(unpaid_invoices)
        
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "summary": analysis['summary'],
            "autonomous_actions": {
                "emails": len(analysis['autonomous_emails']),
                "calls": len(analysis['autonomous_calls']),
                "total": analysis['summary']['ready_to_send']
            },
            "pending_approvals": {
                "count": len(analysis['pending_approvals']),
                "items": analysis['pending_approvals']
            },
            "details": analysis
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@klaus_router.get("/pending-approvals", response_model=dict)
async def get_pending_approvals():
    """Get all actions awaiting approval"""
    
    pending = klaus_engine.get_pending_approvals()
    
    return {
        "status": "success",
        "count": len(pending),
        "approvals": pending
    }


# ============================================================================
# EMAIL ENDPOINTS
# ============================================================================

@klaus_router.post("/send-email", response_model=dict)
async def send_collection_email(
    request: KlausEmailRequest,
    hubspot_client,
    background_tasks: BackgroundTasks
):
    """
    Send a collection email (autonomous or approved)
    """
    
    if not klaus_gmail:
        raise HTTPException(status_code=503, detail="Gmail not configured")
    
    try:
        # Get invoice details from HubSpot
        invoice = await hubspot_client.get_invoice(request.invoice_id)
        
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        # Get contact info
        company_id = invoice.get('company_id')
        company = await hubspot_client.get_company(company_id)
        contact = await hubspot_client.get_primary_contact(company_id)
        
        if not contact or not contact.get('email'):
            raise HTTPException(status_code=400, detail="No email found for contact")
        
        # Analyze invoice to get recommended message
        analysis = klaus_engine.analyze_invoice(invoice)
        
        # Use override message or recommended
        message = request.override_message or analysis['recommended_message']
        
        # Parse subject from message
        subject_line = message.split('\n')[0].replace('Subject: ', '')
        body = '\n'.join(message.split('\n')[2:])  # Skip subject and blank line
        
        # Check if documents should be attached
        documents_to_attach = []
        if 'w-9' in message.lower() or 'w9' in message.lower():
            w9_doc = klaus_drive.get_document('w9') if klaus_drive else None
            if w9_doc:
                # Download and attach
                temp_path = f"/tmp/w9_{invoice['id']}.pdf"
                if klaus_drive.download_document(w9_doc['id'], temp_path):
                    documents_to_attach.append(temp_path)
        
        # Send email
        result = klaus_gmail.send_email(
            to_email=contact['email'],
            to_name=contact.get('name', 'there'),
            subject=subject_line,
            body=body,
            attachments=documents_to_attach if documents_to_attach else None
        )
        
        if result['status'] == 'success':
            # Log communication
            klaus_engine.log_communication(
                invoice_id=request.invoice_id,
                company_name=company.get('name'),
                method='email',
                message_type='collection_reminder'
            )
            
            # Update HubSpot with note
            await hubspot_client.add_note_to_invoice(
                invoice_id=request.invoice_id,
                note=f"Klaus sent collection email: {subject_line}"
            )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@klaus_router.post("/process-incoming-email", response_model=dict)
async def process_incoming_email(hubspot_client):
    """
    Process incoming emails and respond appropriately
    """
    
    if not klaus_gmail:
        raise HTTPException(status_code=503, detail="Gmail not configured")
    
    try:
        # Get recent unread emails
        emails = klaus_gmail.get_recent_emails(query="in:inbox is:unread")
        
        processed = []
        
        for email in emails:
            # Extract invoice number if present
            invoice_num = klaus_gmail.extract_invoice_number(email['body'])
            
            # Check for payment confirmation
            if klaus_gmail.detect_payment_confirmation(email['body']):
                # Mark invoice as paid in HubSpot
                if invoice_num:
                    await hubspot_client.update_invoice_reconciliation_status(
                        invoice_id=invoice_num,
                        status='Reconciled',
                        transaction_details='Payment confirmed via email'
                    )
                
                processed.append({
                    'email_id': email['id'],
                    'action': 'marked_paid',
                    'invoice': invoice_num
                })
            
            # Check for document request
            doc_type = klaus_gmail.detect_document_request(email['body'])
            if doc_type and klaus_drive:
                doc = klaus_drive.get_document(doc_type)
                
                if doc:
                    # Send document
                    temp_path = f"/tmp/{doc_type}_{email['id']}.pdf"
                    klaus_drive.download_document(doc['id'], temp_path)
                    
                    response = klaus_gmail.reply_to_email(
                        thread_id=email['thread_id'],
                        message_id=email['id'],
                        to_email=email['from'],
                        subject=email['subject'],
                        body=f"Here's the {doc_type.upper()} you requested. Let me know if you need anything else!\n\nBest,\nKlaus"
                    )
                    
                    processed.append({
                        'email_id': email['id'],
                        'action': 'sent_document',
                        'document': doc_type
                    })
            
            # Mark as read
            klaus_gmail.mark_as_read(email['id'])
            klaus_gmail.add_label(email['id'], 'Klaus/Processed')
        
        return {
            "status": "success",
            "processed": len(processed),
            "actions": processed
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# VOICE ENDPOINTS
# ============================================================================

@klaus_router.post("/make-call", response_model=dict)
async def make_collection_call(
    request: KlausCallRequest,
    hubspot_client
):
    """
    Make an outbound collection call
    """
    
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Voice calling not configured")
    
    try:
        # Get invoice details
        invoice = await hubspot_client.get_invoice(request.invoice_id)
        
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        # Analyze to check if call is approved
        analysis = klaus_engine.analyze_invoice(invoice)
        
        if analysis['requires_approval'] and analysis['action_required'] == 'call':
            return {
                "status": "requires_approval",
                "message": "This call requires approval before proceeding",
                "analysis": analysis
            }
        
        # Check if it's a good time to call
        if not call_scheduler.is_good_time_to_call():
            return {
                "status": "deferred",
                "message": "Outside business hours - call scheduled for next business day"
            }
        
        # Get knowledge base context
        context = ""
        if klaus_kb:
            context = klaus_kb.get_context_for_scenario(
                f"Calling about overdue invoice {request.invoice_id} for {invoice['company_name']}"
            )
        
        # Create/update assistant with context
        assistant_id = klaus_voice.create_klaus_assistant(context)
        
        # Make the call
        result = klaus_voice.make_outbound_call(
            to_phone=request.phone_number,
            to_name=request.contact_name,
            invoice_id=request.invoice_id,
            amount=float(invoice['amount_billed']),
            days_overdue=analysis['days_overdue'],
            company_name=invoice['company_name'],
            assistant_id=assistant_id
        )
        
        if result['status'] == 'success':
            # Log communication
            klaus_engine.log_communication(
                invoice_id=request.invoice_id,
                company_name=invoice['company_name'],
                method='phone',
                message_type='collection_call'
            )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@klaus_router.post("/voice-webhook", response_model=dict)
async def handle_voice_webhook(webhook: VoiceCallWebhook, hubspot_client):
    """
    Handle webhooks from Vapi when calls complete
    """
    
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Voice not configured")
    
    try:
        # Get full call details
        call_details = klaus_voice.get_call_details(webhook.call_id)
        
        # Analyze outcome
        outcome = klaus_voice._analyze_call_outcome(webhook.transcript or "")
        
        # Take follow-up action based on outcome
        if outcome['outcome'] == 'documents_requested':
            # Queue document email
            pass  # Would trigger email sending
        
        elif outcome['outcome'] == 'payment_promised':
            # Schedule follow-up
            pass  # Would schedule reminder
        
        elif outcome['outcome'] == 'dispute':
            # Escalate to Daniel
            # Send notification
            pass
        
        # Save transcript to Drive
        if klaus_drive and webhook.transcript:
            klaus_drive.create_knowledge_document(
                title=f"Call Transcript - {webhook.call_id}",
                content=webhook.transcript
            )
        
        return {
            "status": "processed",
            "outcome": outcome
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CONFIGURATION ENDPOINTS
# ============================================================================

@klaus_router.post("/configure-drive", response_model=dict)
async def configure_drive_folders(request: DriveConfigRequest):
    """Configure Google Drive folder IDs"""
    
    if not klaus_drive:
        raise HTTPException(status_code=503, detail="Drive not configured")
    
    klaus_drive.configure_folders({
        'w9': request.w9_folder_id,
        'coi': request.coi_folder_id,
        'knowledge_base': request.knowledge_base_folder_id,
        'meeting_transcripts': request.meeting_transcripts_folder_id
    })
    
    return {
        "status": "success",
        "message": "Drive folders configured"
    }


@klaus_router.get("/config", response_model=dict)
async def get_klaus_config():
    """Get Klaus configuration"""
    
    return {
        "status": "success",
        "config": klaus_engine.config,
        "features": {
            "email": klaus_gmail is not None,
            "voice": klaus_voice is not None,
            "drive": klaus_drive is not None,
            "knowledge_base": klaus_kb is not None
        }
    }


@klaus_router.post("/config", response_model=dict)
async def update_klaus_config(config: dict):
    """Update Klaus configuration"""
    
    klaus_engine.config.update(config)
    klaus_engine.save_config()
    
    return {
        "status": "success",
        "config": klaus_engine.config
    }


# ============================================================================
# AUTOMATED WORKFLOW
# ============================================================================

@klaus_router.post("/run-daily-collections", response_model=dict)
async def run_daily_collections(hubspot_client, background_tasks: BackgroundTasks):
    """
    Run automated daily collections workflow
    
    This should be scheduled to run daily at 9 AM
    """
    
    try:
        # 1. Get all unpaid invoices
        invoices = await hubspot_client.get_invoices()
        unpaid = [inv for inv in invoices if inv.get('payment_status') != 'Paid']
        
        # 2. Analyze all invoices
        analysis = klaus_engine.analyze_overdue_invoices(unpaid)
        
        results = {
            'emails_sent': 0,
            'calls_made': 0,
            'approvals_needed': len(analysis['pending_approvals']),
            'errors': []
        }
        
        # 3. Send autonomous emails
        for email_action in analysis['autonomous_emails']:
            try:
                if klaus_gmail:
                    # Get invoice and contact info
                    invoice = await hubspot_client.get_invoice(email_action['invoice_id'])
                    company = await hubspot_client.get_company(invoice['company_id'])
                    contact = await hubspot_client.get_primary_contact(invoice['company_id'])
                    
                    if contact and contact.get('email'):
                        # Parse message
                        message = email_action['recommended_message']
                        subject = message.split('\n')[0].replace('Subject: ', '')
                        body = '\n'.join(message.split('\n')[2:])
                        
                        # Send
                        result = klaus_gmail.send_email(
                            to_email=contact['email'],
                            to_name=contact.get('name', 'there'),
                            subject=subject,
                            body=body
                        )
                        
                        if result['status'] == 'success':
                            results['emails_sent'] += 1
                            
                            # Log
                            klaus_engine.log_communication(
                                invoice_id=email_action['invoice_id'],
                                company_name=company.get('name'),
                                method='email',
                                message_type='automated_collection'
                            )
            
            except Exception as e:
                results['errors'].append({
                    'invoice': email_action['invoice_id'],
                    'error': str(e)
                })
        
        # 4. Make autonomous calls (if configured and during business hours)
        if klaus_voice and call_scheduler.is_good_time_to_call():
            for call_action in analysis['autonomous_calls']:
                try:
                    invoice = await hubspot_client.get_invoice(call_action['invoice_id'])
                    # Would need phone number from contact
                    # This is a placeholder
                    pass
                
                except Exception as e:
                    results['errors'].append({
                        'invoice': call_action['invoice_id'],
                        'error': str(e)
                    })
        
        # 5. Process incoming emails
        if klaus_gmail:
            await process_incoming_email(hubspot_client)
        
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "results": results,
            "summary": {
                "total_analyzed": analysis['total_analyzed'],
                "actions_taken": results['emails_sent'] + results['calls_made'],
                "pending_approval": results['approvals_needed']
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# STATISTICS & REPORTING
# ============================================================================

@klaus_router.get("/stats", response_model=dict)
async def get_klaus_statistics():
    """Get Klaus performance statistics"""
    
    history = klaus_engine.communication_history
    
    total_contacts = len(history)
    emails = len([h for h in history if h['method'] == 'email'])
    calls = len([h for h in history if h['method'] == 'phone'])
    
    # Calculate success rate (would need outcome data)
    
    return {
        "status": "success",
        "statistics": {
            "total_communications": total_contacts,
            "emails_sent": emails,
            "calls_made": calls,
            "active_cases": len(klaus_engine.get_pending_approvals())
        },
        "history": history[-20:]  # Last 20 communications
    }
