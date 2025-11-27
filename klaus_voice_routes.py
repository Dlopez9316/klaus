"""
Klaus Voice API Routes
FastAPI endpoints for voice calling functionality
"""

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import os

# These will be injected from main.py
klaus_voice = None
call_scheduler = None
call_queue = None
hubspot_client = None
klaus_engine = None


def init_voice_routes(
    voice_agent,
    scheduler,
    queue,
    hubspot,
    engine
):
    """Initialize voice routes with dependencies"""
    global klaus_voice, call_scheduler, call_queue, hubspot_client, klaus_engine
    klaus_voice = voice_agent
    call_scheduler = scheduler
    call_queue = queue
    hubspot_client = hubspot
    klaus_engine = engine


router = APIRouter(prefix="/klaus/voice", tags=["Klaus Voice"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class OutboundCallRequest(BaseModel):
    """Request to initiate an outbound call"""
    phone: str = Field(..., description="Phone number to call (E.164 or 10-digit)")
    contact_name: str = Field(..., description="Name of the person to call")
    company_name: str = Field(..., description="Company name")
    invoice_ids: List[str] = Field(..., description="Invoice ID(s) to discuss")
    total_amount: float = Field(..., description="Total amount due")
    days_overdue: int = Field(default=0, description="Days overdue")
    is_vip: bool = Field(default=False, description="Is this a VIP account")


class ScheduleCallRequest(BaseModel):
    """Request to schedule a call for later"""
    phone: str
    contact_name: str
    company_name: str
    invoice_ids: List[str]
    total_amount: float
    target_time: Optional[str] = Field(None, description="ISO datetime for the call")
    timezone: Optional[str] = Field("US/Eastern", description="Timezone for the call")


class QueueCallRequest(BaseModel):
    """Request to add a call to the queue"""
    phone: str
    contact_name: str
    company_name: str
    invoice_ids: List[str]
    total_amount: float
    days_overdue: int = 0
    priority: int = Field(default=5, ge=1, le=10, description="Priority 1-10, higher is more urgent")


class PhoneNumberPurchaseRequest(BaseModel):
    """Request to purchase a phone number"""
    area_code: str = Field(default="305", description="Desired area code")


# ============================================================================
# PHONE NUMBER MANAGEMENT
# ============================================================================

@router.get("/phone-numbers")
async def get_phone_numbers():
    """Get all phone numbers associated with the Vapi account"""
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    numbers = klaus_voice.get_phone_numbers()
    return {
        "status": "success",
        "phone_numbers": numbers
    }


@router.post("/phone-numbers/purchase")
async def purchase_phone_number(request: PhoneNumberPurchaseRequest):
    """Purchase a new phone number from Vapi"""
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    result = klaus_voice.purchase_phone_number(area_code=request.area_code)
    
    if result:
        return {
            "status": "success",
            "phone_number": result
        }
    else:
        raise HTTPException(status_code=400, detail="Failed to purchase phone number")


@router.post("/phone-numbers/setup-inbound")
async def setup_inbound():
    """Configure the phone number to handle inbound calls"""
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    # Create/update assistant for inbound calls
    assistant_id = klaus_voice.create_or_update_assistant(is_inbound=True)
    
    if not assistant_id:
        raise HTTPException(status_code=500, detail="Failed to configure assistant")
    
    result = klaus_voice.setup_inbound_handling(assistant_id)
    return result


# ============================================================================
# OUTBOUND CALLS
# ============================================================================

@router.post("/call")
async def make_outbound_call(request: OutboundCallRequest, background_tasks: BackgroundTasks):
    """
    Initiate an outbound collections call immediately
    """
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    # Check if it's a good time to call (warning only, still proceeds)
    outside_hours = call_scheduler and not call_scheduler.is_good_time_to_call()
    
    # Get previous contact count for this company
    previous_contacts = 0
    if klaus_engine:
        history = [h for h in klaus_engine.communication_history if h.get('company_name') == request.company_name]
        previous_contacts = len(history)
    
    result = klaus_voice.make_outbound_call(
        to_phone=request.phone,
        to_name=request.contact_name,
        company_name=request.company_name,
        invoice_ids=request.invoice_ids,
        total_amount=request.total_amount,
        days_overdue=request.days_overdue,
        previous_contacts=previous_contacts,
        is_vip=request.is_vip,
        use_existing_assistant=True  # Use assistant from env var
    )
    
    # Log communication if successful
    if result['status'] == 'success' and klaus_engine:
        for invoice_id in request.invoice_ids:
            klaus_engine.log_communication(
                invoice_id=invoice_id,
                company_name=request.company_name,
                method='call',
                message_type='collection',
                approved_by='manual'
            )
    
    # Add warning if outside business hours
    if outside_hours and result['status'] == 'success':
        result['warning'] = "Outside business hours - customer may not answer"
    
    return result


@router.post("/call/from-invoice/{invoice_id}")
async def call_from_invoice(invoice_id: str):
    """
    Initiate a call for a specific invoice, automatically fetching details from HubSpot
    """
    if not klaus_voice or not hubspot_client:
        raise HTTPException(status_code=503, detail="Required services not configured")
    
    try:
        # Get invoice details from HubSpot
        invoices = await hubspot_client.get_invoices()
        invoice = next((inv for inv in invoices if inv['id'] == invoice_id), None)
        
        if not invoice:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        
        # Get contact info
        company_name = invoice.get('company_name', 'Unknown')
        contact_name = invoice.get('contact_name', 'Unknown')
        phone = invoice.get('phone', '')
        amount = float(invoice.get('balance_due', invoice.get('amount', 0)))
        
        if not phone:
            raise HTTPException(status_code=400, detail="No phone number on file for this invoice")
        
        # Calculate days overdue
        due_date = invoice.get('due_date')
        days_overdue = 0
        if due_date:
            due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
            days_overdue = max(0, (datetime.now() - due_dt.replace(tzinfo=None)).days)
        
        # Check VIP status
        is_vip = False
        if klaus_engine:
            vip_list = klaus_engine.config.get('vip_contacts', [])
            is_vip = any(vip.lower() in company_name.lower() for vip in vip_list)
        
        # Make the call
        result = klaus_voice.make_outbound_call(
            to_phone=phone,
            to_name=contact_name,
            company_name=company_name,
            invoice_ids=[invoice_id],
            total_amount=amount,
            days_overdue=days_overdue,
            is_vip=is_vip
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CALL SCHEDULING
# ============================================================================

@router.post("/schedule")
async def schedule_call(request: ScheduleCallRequest):
    """Schedule a call for a specific time"""
    if not call_scheduler:
        raise HTTPException(status_code=503, detail="Call scheduler not configured")
    
    result = call_scheduler.schedule_call(
        phone=request.phone,
        contact_name=request.contact_name,
        company_name=request.company_name,
        invoice_ids=request.invoice_ids,
        total_amount=request.total_amount,
        target_time=request.target_time,
        timezone=request.timezone
    )
    
    return result


@router.get("/schedule")
async def get_scheduled_calls(
    company_name: Optional[str] = None,
    status: Optional[str] = None
):
    """Get all scheduled calls"""
    if not call_scheduler:
        raise HTTPException(status_code=503, detail="Call scheduler not configured")
    
    calls = call_scheduler.get_scheduled_calls(
        company_name=company_name,
        status=status
    )
    
    return {
        "status": "success",
        "scheduled_calls": calls
    }


@router.get("/schedule/pending")
async def get_pending_calls():
    """Get calls that are ready to be made"""
    if not call_scheduler:
        raise HTTPException(status_code=503, detail="Call scheduler not configured")
    
    pending = call_scheduler.get_pending_calls()
    
    return {
        "status": "success",
        "pending_calls": pending
    }


@router.delete("/schedule/{scheduled_id}")
async def cancel_scheduled_call(scheduled_id: str, reason: Optional[str] = None):
    """Cancel a scheduled call"""
    if not call_scheduler:
        raise HTTPException(status_code=503, detail="Call scheduler not configured")
    
    success = call_scheduler.cancel_scheduled_call(scheduled_id, reason)
    
    if success:
        return {"status": "success", "message": "Call cancelled"}
    else:
        raise HTTPException(status_code=404, detail="Scheduled call not found")


# ============================================================================
# CALL QUEUE
# ============================================================================

@router.post("/queue")
async def add_to_queue(request: QueueCallRequest):
    """Add a call to the queue"""
    if not call_queue:
        raise HTTPException(status_code=503, detail="Call queue not configured")
    
    result = call_queue.add_to_queue(
        phone=request.phone,
        contact_name=request.contact_name,
        company_name=request.company_name,
        invoice_ids=request.invoice_ids,
        total_amount=request.total_amount,
        days_overdue=request.days_overdue,
        priority=request.priority
    )
    
    return result


@router.post("/queue/process")
async def process_queue():
    """Process pending calls in the queue"""
    if not call_queue:
        raise HTTPException(status_code=503, detail="Call queue not configured")
    
    results = call_queue.process_queue()
    
    return {
        "status": "success",
        "results": results
    }


@router.get("/queue/status")
async def get_queue_status():
    """Get current queue status"""
    if not call_queue:
        raise HTTPException(status_code=503, detail="Call queue not configured")
    
    status = call_queue.get_queue_status()
    
    return {
        "status": "success",
        **status
    }


# ============================================================================
# CALL HISTORY
# ============================================================================

@router.get("/history")
async def get_call_history(
    company_name: Optional[str] = None,
    invoice_id: Optional[str] = None,
    phone_number: Optional[str] = None,
    limit: int = 50
):
    """Get call history with optional filters"""
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    history = klaus_voice.get_call_history(
        company_name=company_name,
        invoice_id=invoice_id,
        phone_number=phone_number,
        limit=limit
    )
    
    return {
        "status": "success",
        "count": len(history),
        "calls": history
    }


@router.get("/history/{call_id}")
async def get_call_details(call_id: str):
    """Get details of a specific call"""
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    details = klaus_voice.get_call_details(call_id)
    
    if 'error' in details:
        raise HTTPException(status_code=404, detail=details['error'])
    
    return {
        "status": "success",
        "call": details
    }


@router.get("/history/{call_id}/transcript")
async def get_call_transcript(call_id: str):
    """Get transcript of a call"""
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    transcript = klaus_voice.get_call_transcript(call_id)
    
    if transcript:
        return {
            "status": "success",
            "call_id": call_id,
            "transcript": transcript
        }
    else:
        raise HTTPException(status_code=404, detail="Transcript not found")


@router.get("/history/{call_id}/recording")
async def get_call_recording(call_id: str):
    """Get recording URL for a call"""
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    recording_url = klaus_voice.get_call_recording_url(call_id)
    
    if recording_url:
        return {
            "status": "success",
            "call_id": call_id,
            "recording_url": recording_url
        }
    else:
        raise HTTPException(status_code=404, detail="Recording not found")


# ============================================================================
# CONTACT LEDGER INTEGRATION
# ============================================================================

@router.get("/ledger/{company_name}")
async def get_contact_ledger_calls(company_name: str, invoice_ids: Optional[str] = None):
    """
    Get call history formatted for contact ledger integration
    """
    if not klaus_voice:
        raise HTTPException(status_code=503, detail="Klaus Voice not configured")
    
    invoice_list = invoice_ids.split(',') if invoice_ids else None
    
    ledger_entries = klaus_voice.get_calls_for_contact_ledger(
        company_name=company_name,
        invoice_ids=invoice_list
    )
    
    return {
        "status": "success",
        "company_name": company_name,
        "call_count": len(ledger_entries),
        "calls": ledger_entries
    }


# ============================================================================
# WEBHOOKS
# ============================================================================

@router.post("/webhook")
async def vapi_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Handle Vapi.ai call webhooks
    This endpoint receives:
    - end-of-call-report: When a call completes
    - status-update: Call status changes
    - transcript: Real-time transcript updates
    """
    try:
        data = await request.json()
        
        if not klaus_voice:
            return JSONResponse(
                content={"status": "service_unavailable"},
                status_code=503
            )
        
        result = klaus_voice.handle_webhook(data)
        
        # If call ended and follow-up required, trigger appropriate action
        if result.get('status') == 'processed' and result.get('outcome', {}).get('requires_followup'):
            followup_action = result['outcome'].get('followup_action')
            call_id = result.get('call_id')
            
            # Log for now - could trigger automated follow-up
            print(f"Call {call_id} requires follow-up: {followup_action}")
        
        return JSONResponse(content=result)
    
    except Exception as e:
        return JSONResponse(
            content={"status": "error", "error": str(e)},
            status_code=500
        )


# ============================================================================
# STATUS & CONFIG
# ============================================================================

@router.get("/status")
async def get_voice_status():
    """Get overall voice system status"""
    
    status = {
        "voice_agent": "active" if klaus_voice else "inactive",
        "scheduler": "active" if call_scheduler else "inactive",
        "queue": "active" if call_queue else "inactive",
        "phone_number_id": klaus_voice.phone_number_id if klaus_voice else None,
        "assistant_id": klaus_voice.assistant_id if klaus_voice else None,
    }
    
    if call_scheduler:
        status["can_call_now"] = call_scheduler.is_good_time_to_call()
        status["next_available_slot"] = call_scheduler.get_next_available_slot().isoformat()
    
    if call_queue:
        queue_status = call_queue.get_queue_status()
        status["queue_status"] = queue_status
    
    return {
        "status": "success",
        **status
    }


@router.get("/business-hours")
async def get_business_hours():
    """Get configured business hours for calling"""
    if not call_scheduler:
        raise HTTPException(status_code=503, detail="Call scheduler not configured")
    
    return {
        "status": "success",
        "business_hours": {
            "start": call_scheduler.business_hours['start'],
            "end": call_scheduler.business_hours['end'],
            "excluded_days": call_scheduler.excluded_days,
            "timezone": call_scheduler.default_timezone
        },
        "can_call_now": call_scheduler.is_good_time_to_call()
    }