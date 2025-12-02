"""
Klaus Voice Integration
Enhanced voice calling capability using Vapi.ai
Handles outbound collections calls, inbound customer inquiries, and call scheduling
"""

import os
import json
import requests
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import pytz

# Import database module for Railway-compatible storage
import database as db


class CallOutcome(Enum):
    """Possible call outcomes"""
    PAYMENT_PROMISED = "payment_promised"
    PAYMENT_RECEIVED = "payment_received"
    DOCUMENTS_REQUESTED = "documents_requested"
    DISPUTE = "dispute"
    CLAIMS_PAID = "claims_paid"
    NEEDS_TIME = "needs_time"
    VOICEMAIL = "voicemail"
    NO_ANSWER = "no_answer"
    WRONG_NUMBER = "wrong_number"
    TRANSFERRED_TO_DANIEL = "transferred_to_daniel"
    CALLBACK_SCHEDULED = "callback_scheduled"
    UNCLEAR = "unclear"
    CALL_FAILED = "call_failed"


class CallType(Enum):
    """Type of call"""
    OUTBOUND_COLLECTION = "outbound_collection"
    OUTBOUND_FOLLOW_UP = "outbound_follow_up"
    OUTBOUND_DOCUMENT_REQUEST = "outbound_document_request"
    INBOUND_INQUIRY = "inbound_inquiry"
    INBOUND_CALLBACK = "inbound_callback"


@dataclass
class CallRecord:
    """Record of a call for the contact ledger"""
    call_id: str
    call_type: str
    phone_number: str
    contact_name: str
    company_name: str
    invoice_ids: List[str]
    total_amount: float
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    status: str = "initiated"
    outcome: Optional[str] = None
    transcript: Optional[str] = None
    recording_url: Optional[str] = None
    follow_up_required: bool = False
    follow_up_action: Optional[str] = None
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class KlausVoiceAgent:
    """
    Voice calling capability for Klaus using Vapi.ai
    Handles outbound collections calls and inbound customer inquiries
    """
    
    def __init__(
        self,
        vapi_api_key: str,
        phone_number_id: Optional[str] = None,
        anthropic_api_key: Optional[str] = None
    ):
        self.api_key = vapi_api_key
        self.phone_number_id = phone_number_id  # Vapi phone number ID
        self.anthropic_api_key = anthropic_api_key
        self.base_url = "https://api.vapi.ai"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Klaus voice configuration - ElevenLabs professional male voice
        self.voice_config = {
            "provider": "11labs",
            "voiceId": "pNInz6obpgDQGcFmaJgB",  # "Adam" - Professional male voice
            "stability": 0.7,
            "similarityBoost": 0.8,
            "style": 0.3,
            "useSpeakerBoost": True
        }
        
        # Alternative: Use Vapi's built-in voices
        self.vapi_voice_config = {
            "provider": "vapi",
            "voiceId": "mark"  # Professional male voice
        }
        
        # Call history stored in memory (also persisted to file)
        self.call_history: List[CallRecord] = []
        self.call_history_file = "klaus_call_history.json"
        self._load_call_history()
        
        # Assistant ID (created once, reused)
        self.assistant_id = os.getenv("VAPI_ASSISTANT_ID")
        
        # Daniel's number for transfers
        self.transfer_number = os.getenv("DANIEL_PHONE_NUMBER", "+1")
        
        # Webhook URL for call events
        self.webhook_url = os.getenv("KLAUS_WEBHOOK_URL", "")
    
    def _load_call_history(self):
        """Load call history from database (Railway) or JSON file (local dev)"""
        try:
            data = db.load_call_history()
            self.call_history = [CallRecord(**record) for record in data]
        except Exception as e:
            print(f"Error loading call history: {e}")
            self.call_history = []

    def _save_call_history(self):
        """Save call history to database (Railway) or JSON file (local dev)"""
        try:
            db.save_call_history([record.to_dict() for record in self.call_history])
        except Exception as e:
            print(f"Error saving call history: {e}")
    
    def get_knowledge_base(self, invoice_context: Dict = None) -> str:
        """Generate knowledge base content for the assistant"""
        
        base_knowledge = """
COMPANY INFORMATION:
- Company: Leverage Live Local
- Service: Property tax compliance consulting for Florida's Live Local Act
- Value: We help multifamily property owners save millions in property taxes through compliance management

KLAUS'S AUTHORITY:
- Can discuss invoice details and payment status
- Can provide payment instructions (ACH, wire, credit card)
- Can send documents (W-9, COI, DBA certificate, banking details)
- Can schedule callback times
- Can transfer to Daniel for complex issues
- CANNOT offer payment plans (requires Daniel's approval)
- CANNOT make legal threats
- CANNOT discuss specific client confidential information

PAYMENT INFORMATION:
- Payment Terms: Net 30
- Bank: JPMorgan Chase
- Methods Accepted: ACH (preferred), Wire Transfer, Credit Card
- Banking details are on every invoice (bottom left corner)

COMMON REQUESTS:
1. "Need W-9" → "I can send that right over. What email should I use?"
2. "Need banking details" → "Those are on the invoice, bottom left. Want me to send separately?"
3. "Already paid" → "Great! Can you tell me the payment date and method so I can locate it?"
4. "Need more time" → "I understand. Let me transfer you to Daniel to discuss options."
5. "Dispute the charge" → "I want to help resolve this. Let me get Daniel on the line."

OBJECTION HANDLING:
- "Too expensive": Focus on ROI - exemptions typically 10-20x our fee
- "Can do it ourselves": Process involves income audits, FHFC certification, strict deadlines. Most underestimate complexity.
- "Not sure it applies": Offer to have Daniel do a free assessment
"""
        
        if invoice_context:
            base_knowledge += f"""

CURRENT CALL CONTEXT:
- Invoice(s): {invoice_context.get('invoice_numbers', 'N/A')}
- Amount Due: ${invoice_context.get('total_amount', 0):,.2f}
- Days Overdue: {invoice_context.get('days_overdue', 0)}
- Company: {invoice_context.get('company_name', 'Unknown')}
- Contact: {invoice_context.get('contact_name', 'Unknown')}
- Previous Contacts: {invoice_context.get('previous_contacts', 0)}
- VIP Account: {'Yes' if invoice_context.get('is_vip', False) else 'No'}
"""
        
        return base_knowledge
    
    def create_or_update_assistant(
        self,
        invoice_context: Dict = None,
        is_inbound: bool = False
    ) -> Optional[str]:
        """
        Create or update Klaus voice assistant configuration
        
        Args:
            invoice_context: Context about the invoice/customer for this call
            is_inbound: Whether this is for inbound calls
        
        Returns:
            Assistant ID
        """
        
        knowledge_base = self.get_knowledge_base(invoice_context)
        
        # Different system prompts for inbound vs outbound
        if is_inbound:
            system_prompt = f"""You are Klaus, an accounts receivable specialist at Leverage Live Local. 
You speak with a slight German accent and are always professional.

This is an INBOUND call - a customer is calling you.

Your objectives:
1. Greet professionally and identify the caller
2. Determine why they're calling (payment question, document request, dispute, etc.)
3. Help them efficiently or transfer to Daniel if needed

IMPORTANT RULES:
1. Ask for permission to record: "I need to let you know this call may be recorded for quality purposes. Is that alright?"
2. If they decline recording, acknowledge: "No problem, I'll take notes instead."
3. Always verify who you're speaking with before discussing account details
4. For complex issues, disputes, or angry callers - transfer to Daniel
5. Be helpful but never make promises you can't keep

{knowledge_base}

Communication Style:
- Professional but warm
- Patient and understanding  
- Clear and direct
- Slight German accent (but fully fluent English)
"""
        else:
            # Outbound call - collections focus
            days_overdue = invoice_context.get('days_overdue', 0) if invoice_context else 0
            
            # Adjust tone based on days overdue
            if days_overdue <= 14:
                tone_instruction = """
TONE: Friendly and helpful. This is a gentle reminder.
- Be conversational and assume there's a simple explanation
- Focus on whether they received the invoice and if they need anything
"""
            elif days_overdue <= 30:
                tone_instruction = """
TONE: Professional and direct. This is a follow-up.
- Be courteous but businesslike
- Politely ask for a specific payment date
- Note this is your second/third contact attempt
"""
            elif days_overdue <= 60:
                tone_instruction = """
TONE: Firm but professional. This requires attention.
- Be direct about the overdue status
- Request immediate attention
- Mention potential service implications (but don't threaten)
"""
            else:
                tone_instruction = """
TONE: Serious and business-focused. This is urgent.
- Make clear this is a significant issue
- Require a concrete resolution plan
- Consider transferring to Daniel for escalation discussion
"""
            
            system_prompt = f"""You are Klaus, an accounts receivable specialist at Leverage Live Local.
You speak with a slight German accent and are always professional.

This is an OUTBOUND collections call.

Your objectives:
1. Confirm you're speaking with the right person
2. Discuss the overdue invoice(s)
3. Get a commitment for payment or understand the blocker
4. Provide any documents they need
5. Transfer to Daniel if situation requires escalation

{tone_instruction}

IMPORTANT RULES:
1. Ask for permission to record: "Before we continue, I need to let you know this call is being recorded. Is that alright with you?"
2. If they decline, say: "I understand. Let me take notes instead."
3. NEVER claim previous contact unless it's documented
4. For VIP accounts, be extra courteous but still professional about payment
5. Transfer to Daniel if: client requests him, situation is complex, client is upset
6. When transferring: "Let me get Daniel on the line who can help you with that."

{knowledge_base}

Communication Style:
- Professional but warm
- Patient and understanding
- Clear and direct
- Slight German accent (but fully fluent English)
"""
        
        assistant_config = {
            "name": "Klaus Collections Agent",
            "voice": self.voice_config,
            "model": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "temperature": 0.7,
                "systemPrompt": system_prompt,
                "maxTokens": 500
            },
            "firstMessage": None,  # Will be set per-call
            "recordingEnabled": True,
            "endCallMessage": "Thank you for your time. Have a great day.",
            "endCallPhrases": [
                "goodbye",
                "thank you goodbye",
                "that's all I need",
                "talk to you later"
            ],
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "en"
            },
            "silenceTimeoutSeconds": 30,
            "maxDurationSeconds": 600,  # 10 minute max
            "backgroundSound": "off",
            "serverUrl": self.webhook_url,
            "serverMessages": [
                "end-of-call-report",
                "status-update",
                "transcript"
            ]
        }
        
        # Add transfer functionality
        if self.transfer_number:
            assistant_config["forwardingPhoneNumber"] = self.transfer_number
        
        try:
            # Check if we need to update existing or create new
            if self.assistant_id:
                # Update existing assistant
                response = requests.patch(
                    f"{self.base_url}/assistant/{self.assistant_id}",
                    headers=self.headers,
                    json=assistant_config
                )
                
                if response.status_code == 200:
                    return self.assistant_id
                else:
                    print(f"Error updating assistant: {response.text}")
                    # Fall through to create new
            
            # Create new assistant
            response = requests.post(
                f"{self.base_url}/assistant",
                headers=self.headers,
                json=assistant_config
            )
            
            if response.status_code == 201:
                self.assistant_id = response.json()['id']
                return self.assistant_id
            else:
                print(f"Error creating assistant: {response.text}")
                return None
        
        except Exception as e:
            print(f"Error with assistant: {e}")
            return None
    
    def get_phone_numbers(self) -> List[Dict]:
        """Get all phone numbers associated with this Vapi account"""
        try:
            response = requests.get(
                f"{self.base_url}/phone-number",
                headers=self.headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error getting phone numbers: {response.text}")
                return []
        
        except Exception as e:
            print(f"Error: {e}")
            return []
    
    def purchase_phone_number(self, area_code: str = "305") -> Optional[Dict]:
        """
        Purchase a new phone number from Vapi
        
        Args:
            area_code: Desired area code (default 305 for Miami)
        
        Returns:
            Phone number details
        """
        try:
            response = requests.post(
                f"{self.base_url}/phone-number",
                headers=self.headers,
                json={
                    "provider": "twilio",
                    "areaCode": area_code,
                    "name": "Klaus Collections Line"
                }
            )
            
            if response.status_code == 201:
                phone_data = response.json()
                self.phone_number_id = phone_data['id']
                return phone_data
            else:
                print(f"Error purchasing phone number: {response.text}")
                return None
        
        except Exception as e:
            print(f"Error: {e}")
            return None
    
    def setup_inbound_handling(self, assistant_id: str) -> Dict:
        """
        Configure phone number for inbound calls
        
        Args:
            assistant_id: Assistant to handle inbound calls
        
        Returns:
            Configuration status
        """
        
        if not self.phone_number_id:
            return {
                'status': 'error',
                'error': 'No phone number configured. Call purchase_phone_number first.'
            }
        
        try:
            response = requests.patch(
                f"{self.base_url}/phone-number/{self.phone_number_id}",
                headers=self.headers,
                json={
                    "assistantId": assistant_id
                }
            )
            
            if response.status_code == 200:
                return {
                    'status': 'success',
                    'message': 'Inbound calls will be handled by Klaus'
                }
            else:
                return {
                    'status': 'error',
                    'error': response.text
                }
        
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def make_outbound_call(
        self,
        to_phone: str,
        to_name: str,
        company_name: str,
        invoice_ids: List[str],
        total_amount: float,
        days_overdue: int,
        previous_contacts: int = 0,
        is_vip: bool = False,
        use_existing_assistant: bool = True
    ) -> Dict:
        """
        Make an outbound collections call
        
        Args:
            to_phone: Customer phone number (E.164 format preferred)
            to_name: Contact name
            company_name: Company name
            invoice_ids: List of invoice IDs being discussed
            total_amount: Total amount due
            days_overdue: Days the oldest invoice is overdue
            previous_contacts: Number of previous contact attempts
            is_vip: Whether this is a VIP account
            use_existing_assistant: Use assistant ID from env var (default True)
        
        Returns:
            Call details
        """
        
        # Format phone number to E.164 if needed
        to_phone = self._format_phone_number(to_phone)
        
        if not to_phone:
            return {
                'status': 'error',
                'error': 'Invalid phone number format'
            }
        
        # Use existing assistant ID from environment
        if use_existing_assistant:
            assistant_id = self.assistant_id
            if not assistant_id:
                return {
                    'status': 'error',
                    'error': 'VAPI_ASSISTANT_ID not set in environment variables'
                }
        else:
            # Create context for the assistant
            invoice_context = {
                'invoice_numbers': ', '.join(invoice_ids),
                'total_amount': total_amount,
                'days_overdue': days_overdue,
                'company_name': company_name,
                'contact_name': to_name,
                'previous_contacts': previous_contacts,
                'is_vip': is_vip
            }
            
            # Update assistant with this context
            assistant_id = self.create_or_update_assistant(
                invoice_context=invoice_context,
                is_inbound=False
            )
            
            if not assistant_id:
                return {
                    'status': 'error',
                    'error': 'Failed to configure assistant'
                }
        
        # Generate appropriate first message based on situation
        if len(invoice_ids) == 1:
            invoice_ref = f"Invoice {invoice_ids[0]}"
        else:
            invoice_ref = f"{len(invoice_ids)} invoices"
        
        # Customize greeting based on days overdue
        if days_overdue <= 14:
            first_message = f"Hello, this is Klaus calling from Leverage Live Local. Am I speaking with {to_name}?"
        elif days_overdue <= 30:
            first_message = f"Hello, this is Klaus from Leverage Live Local calling about an overdue invoice. Am I speaking with {to_name}?"
        else:
            first_message = f"Hello, this is Klaus from Leverage Live Local. I'm calling regarding an urgent payment matter. Am I speaking with {to_name}?"
        
        # Build call configuration
        call_config = {
            "assistantId": assistant_id,
            "phoneNumberId": self.phone_number_id,
            "customer": {
                "number": to_phone,
                "name": to_name
            },
            "assistantOverrides": {
                "firstMessage": first_message,
                "variableValues": {
                    "contact_name": to_name,
                    "invoice_numbers": ', '.join(invoice_ids),
                    "amount": f"${total_amount:,.2f}",
                    "days_overdue": str(days_overdue),
                    "company_name": company_name
                }
            }
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/call/phone",
                headers=self.headers,
                json=call_config
            )
            
            if response.status_code == 201:
                call_data = response.json()
                
                # Create call record
                call_record = CallRecord(
                    call_id=call_data['id'],
                    call_type=CallType.OUTBOUND_COLLECTION.value,
                    phone_number=to_phone,
                    contact_name=to_name,
                    company_name=company_name,
                    invoice_ids=invoice_ids,
                    total_amount=total_amount,
                    started_at=datetime.now().isoformat(),
                    status='initiated'
                )
                
                self.call_history.append(call_record)
                self._save_call_history()
                
                return {
                    'status': 'success',
                    'call_id': call_data['id'],
                    'message': f"Call initiated to {to_name} at {to_phone}"
                }
            else:
                return {
                    'status': 'error',
                    'error': response.text
                }
        
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def _format_phone_number(self, phone: str) -> Optional[str]:
        """Format phone number to E.164 format"""
        
        # Remove all non-digit characters
        digits = ''.join(filter(str.isdigit, phone))
        
        # Handle US numbers
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
        elif len(digits) > 10 and phone.startswith('+'):
            return f"+{digits}"
        else:
            return None
    
    def get_call_details(self, call_id: str) -> Dict:
        """Get details of a specific call"""
        
        try:
            response = requests.get(
                f"{self.base_url}/call/{call_id}",
                headers=self.headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': response.text}
        
        except Exception as e:
            return {'error': str(e)}
    
    def get_call_transcript(self, call_id: str) -> Optional[str]:
        """Get transcript of a completed call"""
        
        call_details = self.get_call_details(call_id)
        
        if 'transcript' in call_details:
            return call_details['transcript']
        
        return None
    
    def get_call_recording_url(self, call_id: str) -> Optional[str]:
        """Get URL to call recording"""
        
        call_details = self.get_call_details(call_id)
        
        if 'recordingUrl' in call_details:
            return call_details['recordingUrl']
        
        return None
    
    def handle_webhook(self, webhook_data: Dict) -> Dict:
        """
        Process webhook events from Vapi
        
        Args:
            webhook_data: Webhook payload from Vapi
        
        Returns:
            Processing result
        """
        
        message_type = webhook_data.get('message', {}).get('type', '')
        call_id = webhook_data.get('message', {}).get('call', {}).get('id', '')
        
        if message_type == 'end-of-call-report':
            return self._handle_call_ended(webhook_data)
        elif message_type == 'status-update':
            return self._handle_status_update(webhook_data)
        elif message_type == 'transcript':
            return self._handle_transcript_update(webhook_data)
        else:
            return {'status': 'ignored', 'message_type': message_type}
    
    def _handle_call_ended(self, webhook_data: Dict) -> Dict:
        """Process end-of-call report"""
        
        message = webhook_data.get('message', {})
        call_data = message.get('call', {})
        call_id = call_data.get('id')
        
        if not call_id:
            return {'status': 'error', 'error': 'No call ID in webhook'}
        
        # Extract call details
        status = call_data.get('status', 'unknown')
        duration = message.get('durationSeconds', 0)
        transcript = message.get('transcript', '')
        recording_url = message.get('recordingUrl', '')
        ended_reason = message.get('endedReason', '')
        
        # Find and update call record
        call_record = None
        for record in self.call_history:
            if record.call_id == call_id:
                call_record = record
                break
        
        if call_record:
            call_record.ended_at = datetime.now().isoformat()
            call_record.duration_seconds = duration
            call_record.status = status
            call_record.transcript = transcript
            call_record.recording_url = recording_url
            
            # Analyze outcome
            outcome = self._analyze_call_outcome(transcript, ended_reason)
            call_record.outcome = outcome['outcome']
            call_record.follow_up_required = outcome.get('requires_followup', False)
            call_record.follow_up_action = outcome.get('followup_action')
            
            self._save_call_history()
            
            return {
                'status': 'processed',
                'call_id': call_id,
                'outcome': outcome,
                'duration': duration
            }
        else:
            # Create new record for inbound call
            call_record = CallRecord(
                call_id=call_id,
                call_type=CallType.INBOUND_CALLBACK.value,
                phone_number=call_data.get('customer', {}).get('number', 'unknown'),
                contact_name=call_data.get('customer', {}).get('name', 'Unknown'),
                company_name='Unknown',
                invoice_ids=[],
                total_amount=0,
                started_at=call_data.get('startedAt', datetime.now().isoformat()),
                ended_at=datetime.now().isoformat(),
                duration_seconds=duration,
                status=status,
                transcript=transcript,
                recording_url=recording_url
            )
            
            outcome = self._analyze_call_outcome(transcript, ended_reason)
            call_record.outcome = outcome['outcome']
            call_record.follow_up_required = outcome.get('requires_followup', False)
            call_record.follow_up_action = outcome.get('followup_action')
            
            self.call_history.append(call_record)
            self._save_call_history()
            
            return {
                'status': 'processed',
                'call_id': call_id,
                'outcome': outcome,
                'call_type': 'inbound'
            }
    
    def _handle_status_update(self, webhook_data: Dict) -> Dict:
        """Process status update"""
        
        message = webhook_data.get('message', {})
        call_id = message.get('call', {}).get('id')
        status = message.get('status')
        
        if call_id:
            for record in self.call_history:
                if record.call_id == call_id:
                    record.status = status
                    self._save_call_history()
                    break
        
        return {'status': 'updated', 'call_status': status}
    
    def _handle_transcript_update(self, webhook_data: Dict) -> Dict:
        """Process real-time transcript update"""
        # Could be used for real-time monitoring
        return {'status': 'received'}
    
    def _analyze_call_outcome(self, transcript: str, ended_reason: str = '') -> Dict:
        """
        Analyze call transcript to determine outcome
        
        Args:
            transcript: Full call transcript
            ended_reason: Why the call ended
        
        Returns:
            Dict with outcome classification and required actions
        """
        
        if not transcript:
            if ended_reason == 'no-answer':
                return {
                    'outcome': CallOutcome.NO_ANSWER.value,
                    'requires_followup': True,
                    'followup_action': 'schedule_retry'
                }
            elif ended_reason == 'voicemail':
                return {
                    'outcome': CallOutcome.VOICEMAIL.value,
                    'requires_followup': True,
                    'followup_action': 'send_email_followup'
                }
            elif ended_reason in ['busy', 'failed']:
                return {
                    'outcome': CallOutcome.CALL_FAILED.value,
                    'requires_followup': True,
                    'followup_action': 'schedule_retry'
                }
            return {
                'outcome': CallOutcome.UNCLEAR.value,
                'requires_followup': True,
                'followup_action': 'manual_review'
            }
        
        transcript_lower = transcript.lower()
        
        # Check for transfer to Daniel
        if any(phrase in transcript_lower for phrase in [
            'transfer', 'get daniel', 'speak to daniel',
            'talk to someone else', 'manager'
        ]):
            return {
                'outcome': CallOutcome.TRANSFERRED_TO_DANIEL.value,
                'requires_followup': True,
                'followup_action': 'daniel_follow_up'
            }
        
        # Payment promised
        if any(phrase in transcript_lower for phrase in [
            'will pay', 'send payment', 'process payment',
            'pay this week', 'pay by', 'pay today', 'pay tomorrow',
            'sending payment', 'wire it', 'ach it'
        ]):
            return {
                'outcome': CallOutcome.PAYMENT_PROMISED.value,
                'requires_followup': True,
                'followup_action': 'confirm_payment_received'
            }
        
        # Documents requested
        if any(phrase in transcript_lower for phrase in [
            'need w-9', 'need w9', 'need insurance', 'need coi',
            'send documents', 'send paperwork', 'vendor packet',
            'banking details', 'ach form'
        ]):
            return {
                'outcome': CallOutcome.DOCUMENTS_REQUESTED.value,
                'requires_followup': True,
                'followup_action': 'send_requested_documents'
            }
        
        # Dispute
        if any(phrase in transcript_lower for phrase in [
            'dispute', 'incorrect', 'wrong amount', 'didn\'t order',
            'not authorized', 'never received', 'not right',
            'billing error', 'overcharged'
        ]):
            return {
                'outcome': CallOutcome.DISPUTE.value,
                'requires_followup': True,
                'followup_action': 'escalate_to_daniel'
            }
        
        # Already paid claim
        if any(phrase in transcript_lower for phrase in [
            'already paid', 'sent payment', 'paid last week',
            'check mailed', 'paid it', 'payment went out'
        ]):
            return {
                'outcome': CallOutcome.CLAIMS_PAID.value,
                'requires_followup': True,
                'followup_action': 'verify_payment_reconciliation'
            }
        
        # Needs more time
        if any(phrase in transcript_lower for phrase in [
            'cash flow', 'need more time', 'pay next month',
            'payment plan', 'tight right now', 'budget',
            'end of month', 'next week'
        ]):
            return {
                'outcome': CallOutcome.NEEDS_TIME.value,
                'requires_followup': True,
                'followup_action': 'schedule_follow_up_call'
            }
        
        # Callback scheduled
        if any(phrase in transcript_lower for phrase in [
            'call back', 'call me back', 'call later',
            'try again', 'not a good time'
        ]):
            return {
                'outcome': CallOutcome.CALLBACK_SCHEDULED.value,
                'requires_followup': True,
                'followup_action': 'schedule_callback'
            }
        
        # Wrong number
        if any(phrase in transcript_lower for phrase in [
            'wrong number', 'don\'t know', 'no one by that name',
            'wrong person'
        ]):
            return {
                'outcome': CallOutcome.WRONG_NUMBER.value,
                'requires_followup': True,
                'followup_action': 'update_contact_info'
            }
        
        return {
            'outcome': CallOutcome.UNCLEAR.value,
            'requires_followup': True,
            'followup_action': 'manual_review'
        }
    
    def get_call_history(
        self,
        company_name: Optional[str] = None,
        invoice_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get filtered call history
        
        Args:
            company_name: Filter by company name
            invoice_id: Filter by invoice ID
            phone_number: Filter by phone number
            limit: Maximum records to return
        
        Returns:
            List of call records
        """
        
        filtered = self.call_history
        
        if company_name:
            filtered = [r for r in filtered if company_name.lower() in r.company_name.lower()]
        
        if invoice_id:
            filtered = [r for r in filtered if invoice_id in r.invoice_ids]
        
        if phone_number:
            formatted = self._format_phone_number(phone_number)
            if formatted:
                filtered = [r for r in filtered if r.phone_number == formatted]
        
        # Sort by date, most recent first
        filtered.sort(key=lambda x: x.started_at, reverse=True)
        
        return [r.to_dict() for r in filtered[:limit]]
    
    def get_calls_for_contact_ledger(
        self,
        company_name: str,
        invoice_ids: List[str] = None
    ) -> List[Dict]:
        """
        Get call history formatted for contact ledger integration
        
        Args:
            company_name: Company name to look up
            invoice_ids: Optional specific invoice IDs
        
        Returns:
            List of communication records for the ledger
        """
        
        calls = self.get_call_history(company_name=company_name)
        
        if invoice_ids:
            calls = [c for c in calls if any(inv in c.get('invoice_ids', []) for inv in invoice_ids)]
        
        # Format for contact ledger
        ledger_entries = []
        for call in calls:
            entry = {
                'type': 'call',
                'date': call['started_at'],
                'direction': 'outbound' if 'outbound' in call.get('call_type', '') else 'inbound',
                'duration_seconds': call.get('duration_seconds', 0),
                'outcome': call.get('outcome', 'unknown'),
                'transcript_available': bool(call.get('transcript')),
                'recording_available': bool(call.get('recording_url')),
                'follow_up_required': call.get('follow_up_required', False),
                'follow_up_action': call.get('follow_up_action'),
                'call_id': call['call_id']
            }
            ledger_entries.append(entry)
        
        return ledger_entries


class CallScheduler:
    """
    Schedules and manages call timing
    Ensures calls are made at appropriate times based on timezone
    """
    
    def __init__(self, default_timezone: str = 'US/Eastern'):
        self.default_timezone = default_timezone
        self.business_hours = {
            'start': 9,   # 9 AM
            'end': 17,    # 5 PM
        }
        self.excluded_days = ['Saturday', 'Sunday']
        self.scheduled_calls: List[Dict] = []
        self.schedule_file = "klaus_scheduled_calls.json"
        self._load_scheduled_calls()
    
    def _load_scheduled_calls(self):
        """Load scheduled calls from file"""
        try:
            if os.path.exists(self.schedule_file):
                with open(self.schedule_file, 'r') as f:
                    self.scheduled_calls = json.load(f)
        except Exception as e:
            print(f"Error loading scheduled calls: {e}")
            self.scheduled_calls = []
    
    def _save_scheduled_calls(self):
        """Save scheduled calls to file"""
        try:
            with open(self.schedule_file, 'w') as f:
                json.dump(self.scheduled_calls, f, indent=2)
        except Exception as e:
            print(f"Error saving scheduled calls: {e}")
    
    def is_good_time_to_call(self, timezone: str = None) -> bool:
        """Check if current time is appropriate for calling"""
        
        tz = pytz.timezone(timezone or self.default_timezone)
        now = datetime.now(tz)
        
        # Check if business hours
        if now.hour < self.business_hours['start'] or now.hour >= self.business_hours['end']:
            return False
        
        # Check if weekday
        if now.strftime('%A') in self.excluded_days:
            return False
        
        return True
    
    def get_next_available_slot(self, timezone: str = None) -> datetime:
        """Get the next available time slot for a call"""
        
        tz = pytz.timezone(timezone or self.default_timezone)
        now = datetime.now(tz)
        
        # Start checking from now
        candidate = now
        
        # If outside business hours, move to next business day start
        if candidate.hour >= self.business_hours['end']:
            # Move to next day at business start
            candidate = candidate.replace(
                hour=self.business_hours['start'],
                minute=0,
                second=0,
                microsecond=0
            ) + timedelta(days=1)
        elif candidate.hour < self.business_hours['start']:
            # Move to business start same day
            candidate = candidate.replace(
                hour=self.business_hours['start'],
                minute=0,
                second=0,
                microsecond=0
            )
        
        # Skip weekends
        while candidate.strftime('%A') in self.excluded_days:
            candidate += timedelta(days=1)
            candidate = candidate.replace(
                hour=self.business_hours['start'],
                minute=0,
                second=0,
                microsecond=0
            )
        
        return candidate
    
    def schedule_call(
        self,
        phone: str,
        contact_name: str,
        company_name: str,
        invoice_ids: List[str],
        total_amount: float,
        target_time: str = None,
        timezone: str = None
    ) -> Dict:
        """
        Schedule a call for later
        
        Args:
            phone: Phone number to call
            contact_name: Contact name
            company_name: Company name
            invoice_ids: Invoice IDs
            total_amount: Amount due
            target_time: Optional ISO format datetime string
            timezone: Timezone for the target time
        
        Returns:
            Scheduled call details
        """
        
        tz = pytz.timezone(timezone or self.default_timezone)
        
        if target_time:
            # Parse provided time
            try:
                scheduled_dt = datetime.fromisoformat(target_time.replace('Z', '+00:00'))
                if scheduled_dt.tzinfo is None:
                    scheduled_dt = tz.localize(scheduled_dt)
            except:
                # If parsing fails, use next available slot
                scheduled_dt = self.get_next_available_slot(timezone)
        else:
            # Use next available slot
            scheduled_dt = self.get_next_available_slot(timezone)
        
        # Validate the time is during business hours
        local_dt = scheduled_dt.astimezone(tz)
        if not (self.business_hours['start'] <= local_dt.hour < self.business_hours['end']):
            scheduled_dt = self.get_next_available_slot(timezone)
        
        scheduled_call = {
            'id': f"scheduled_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.scheduled_calls)}",
            'phone': phone,
            'contact_name': contact_name,
            'company_name': company_name,
            'invoice_ids': invoice_ids,
            'total_amount': total_amount,
            'scheduled_for': scheduled_dt.isoformat(),
            'timezone': timezone or self.default_timezone,
            'status': 'scheduled',
            'created_at': datetime.now().isoformat()
        }
        
        self.scheduled_calls.append(scheduled_call)
        self._save_scheduled_calls()
        
        return {
            'status': 'scheduled',
            'scheduled_call': scheduled_call
        }
    
    def get_pending_calls(self) -> List[Dict]:
        """Get all calls that are ready to be made"""
        
        now = datetime.now(pytz.UTC)
        pending = []
        
        for call in self.scheduled_calls:
            if call['status'] != 'scheduled':
                continue
            
            scheduled_time = datetime.fromisoformat(call['scheduled_for'].replace('Z', '+00:00'))
            if scheduled_time.tzinfo is None:
                tz = pytz.timezone(call.get('timezone', self.default_timezone))
                scheduled_time = tz.localize(scheduled_time)
            
            if scheduled_time <= now:
                pending.append(call)
        
        return pending
    
    def mark_call_completed(self, scheduled_id: str, call_id: str = None):
        """Mark a scheduled call as completed"""
        
        for call in self.scheduled_calls:
            if call['id'] == scheduled_id:
                call['status'] = 'completed'
                call['completed_at'] = datetime.now().isoformat()
                if call_id:
                    call['vapi_call_id'] = call_id
                self._save_scheduled_calls()
                return True
        
        return False
    
    def cancel_scheduled_call(self, scheduled_id: str, reason: str = None):
        """Cancel a scheduled call"""
        
        for call in self.scheduled_calls:
            if call['id'] == scheduled_id:
                call['status'] = 'cancelled'
                call['cancelled_at'] = datetime.now().isoformat()
                if reason:
                    call['cancel_reason'] = reason
                self._save_scheduled_calls()
                return True
        
        return False
    
    def get_scheduled_calls(
        self,
        company_name: str = None,
        status: str = None
    ) -> List[Dict]:
        """Get scheduled calls with optional filtering"""
        
        filtered = self.scheduled_calls
        
        if company_name:
            filtered = [c for c in filtered if company_name.lower() in c['company_name'].lower()]
        
        if status:
            filtered = [c for c in filtered if c['status'] == status]
        
        return filtered


class VoiceCallQueue:
    """
    Manages a queue of calls to be made, respecting rate limits and business hours
    """
    
    def __init__(
        self,
        voice_agent: KlausVoiceAgent,
        scheduler: CallScheduler,
        daily_limit: int = 10
    ):
        self.voice_agent = voice_agent
        self.scheduler = scheduler
        self.daily_limit = daily_limit
        self.calls_today = 0
        self.last_reset_date = datetime.now().date()
        self.queue: List[Dict] = []
        self.queue_file = "klaus_call_queue.json"
        self._load_queue()
    
    def _load_queue(self):
        """Load queue from file"""
        try:
            if os.path.exists(self.queue_file):
                with open(self.queue_file, 'r') as f:
                    data = json.load(f)
                    self.queue = data.get('queue', [])
                    self.calls_today = data.get('calls_today', 0)
                    last_reset = data.get('last_reset_date')
                    if last_reset:
                        self.last_reset_date = datetime.fromisoformat(last_reset).date()
        except Exception as e:
            print(f"Error loading call queue: {e}")
    
    def _save_queue(self):
        """Save queue to file"""
        try:
            with open(self.queue_file, 'w') as f:
                json.dump({
                    'queue': self.queue,
                    'calls_today': self.calls_today,
                    'last_reset_date': self.last_reset_date.isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"Error saving call queue: {e}")
    
    def _check_daily_reset(self):
        """Reset daily counter if it's a new day"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.calls_today = 0
            self.last_reset_date = today
            self._save_queue()
    
    def add_to_queue(
        self,
        phone: str,
        contact_name: str,
        company_name: str,
        invoice_ids: List[str],
        total_amount: float,
        days_overdue: int,
        priority: int = 5  # 1-10, higher = more urgent
    ) -> Dict:
        """Add a call to the queue"""
        
        call_item = {
            'id': f"queue_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.queue)}",
            'phone': phone,
            'contact_name': contact_name,
            'company_name': company_name,
            'invoice_ids': invoice_ids,
            'total_amount': total_amount,
            'days_overdue': days_overdue,
            'priority': priority,
            'added_at': datetime.now().isoformat(),
            'status': 'queued'
        }
        
        self.queue.append(call_item)
        self._save_queue()
        
        return {
            'status': 'queued',
            'queue_item': call_item,
            'position': len([q for q in self.queue if q['status'] == 'queued'])
        }
    
    def process_queue(self) -> List[Dict]:
        """
        Process pending calls in the queue
        Respects daily limits and business hours
        
        Returns:
            List of call results
        """
        
        self._check_daily_reset()
        results = []
        
        # Check if we can make calls now
        if not self.scheduler.is_good_time_to_call():
            return [{
                'status': 'skipped',
                'reason': 'Outside business hours'
            }]
        
        # Get queued calls sorted by priority (highest first)
        queued = [q for q in self.queue if q['status'] == 'queued']
        queued.sort(key=lambda x: (-x['priority'], x['added_at']))
        
        for call_item in queued:
            # Check daily limit
            if self.calls_today >= self.daily_limit:
                results.append({
                    'status': 'daily_limit_reached',
                    'queue_id': call_item['id']
                })
                break
            
            # Make the call
            result = self.voice_agent.make_outbound_call(
                to_phone=call_item['phone'],
                to_name=call_item['contact_name'],
                company_name=call_item['company_name'],
                invoice_ids=call_item['invoice_ids'],
                total_amount=call_item['total_amount'],
                days_overdue=call_item['days_overdue']
            )
            
            if result['status'] == 'success':
                call_item['status'] = 'completed'
                call_item['completed_at'] = datetime.now().isoformat()
                call_item['vapi_call_id'] = result['call_id']
                self.calls_today += 1
            else:
                call_item['status'] = 'failed'
                call_item['error'] = result.get('error')
            
            results.append({
                'queue_id': call_item['id'],
                **result
            })
            
            self._save_queue()
        
        return results
    
    def get_queue_status(self) -> Dict:
        """Get current queue status"""
        
        self._check_daily_reset()
        
        return {
            'queued': len([q for q in self.queue if q['status'] == 'queued']),
            'completed_today': self.calls_today,
            'daily_limit': self.daily_limit,
            'remaining_today': max(0, self.daily_limit - self.calls_today),
            'can_call_now': self.scheduler.is_good_time_to_call()
        }