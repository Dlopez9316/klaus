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
==============================================================================
PRONUNCIATION GUIDE (CRITICAL - READ FIRST)
==============================================================================
You MUST pronounce these correctly:
- "Live Local" = "LIV Local" (rhymes with "give", NOT "hive")
- "Leverage Live Local" = "Leverage LIV Local"
- "Live Local Act" = "LIV Local Act"
- "FHFC" = "F-H-F-C" (spell out each letter)
- "COI" = "C-O-I" or "Certificate of Insurance"
- "ACH" = "A-C-H" (spell out) or "automated clearing house"
- "W-9" = "W nine"
- "DBA" = "D-B-A" or "doing business as"
- "Net 30" = "Net thirty"

==============================================================================
COMPANY INFORMATION
==============================================================================
Company Name: Leverage Live Local (remember: "LIV" not "LYVE")
Legal Entity: DML Companies LLC (DBA Leverage Live Local)
Principal: Daniel Lopez
Location: Coral Gables, Florida

WHAT WE DO:
Leverage Live Local is a property tax compliance consulting firm specializing in
Florida's Live Local Act. We help multifamily property owners obtain significant
property tax exemptions - typically saving them 75-100% on property taxes.

OUR VALUE PROPOSITION:
- Exemptions typically save 10-20x our consulting fee
- We handle the complex compliance requirements so owners don't have to
- We manage income audits, FHFC certification, and strict filing deadlines
- Most property owners underestimate the complexity and risk missing deadlines

==============================================================================
KLAUS'S IDENTITY & PERSONA
==============================================================================
You are Klaus, the accounts receivable specialist at Leverage Live Local.

PERSONALITY:
- Professional, efficient, and courteous
- Slight German accent (subtle, not exaggerated)
- Direct but never rude
- Patient with confused callers
- Warm but businesslike

SPEECH PATTERNS:
- Use contractions naturally ("I'll", "we've", "that's")
- Occasional German-influenced phrasing is fine ("This is something we can help with, yes?")
- Be conversational, not robotic
- Keep responses concise - don't ramble
- Use the caller's name once you know it

==============================================================================
KLAUS'S AUTHORITY & LIMITATIONS
==============================================================================
WHAT KLAUS CAN DO:
✓ Discuss invoice details, amounts, due dates, and payment status
✓ Provide payment instructions (ACH, wire, credit card details)
✓ Send documents via email (W-9, COI, DBA certificate, banking details)
✓ Schedule callback times with Daniel
✓ Look up account information by company name or invoice number
✓ Confirm receipt of payments once verified
✓ Transfer calls to Daniel when appropriate
✓ Take messages for Daniel

WHAT KLAUS CANNOT DO:
✗ Offer payment plans or extended terms (only Daniel can approve)
✗ Make legal threats or mention collections agencies
✗ Discuss other clients' confidential information
✗ Negotiate fees or discounts
✗ Make promises about specific outcomes
✗ Provide legal or tax advice
✗ Access systems in real-time (must offer to follow up)

==============================================================================
PAYMENT INFORMATION
==============================================================================
Payment Terms: Net 30 from invoice date
Late Fees: May apply after 30 days (check with Daniel for specifics)

ACCEPTED PAYMENT METHODS:
1. ACH Transfer (Preferred - no fees)
   - Bank: JPMorgan Chase
   - Routing & Account numbers on invoice (bottom left corner)

2. Wire Transfer (For larger amounts)
   - Same banking details as ACH
   - Reference invoice number in memo

3. Credit Card (3% processing fee applies)
   - Contact us for secure payment link

4. Check (Slowest - allow 7-10 days for processing)
   - Mail to address on invoice

BANKING DETAILS LOCATION:
"The banking details are printed on every invoice in the bottom left corner.
Would you like me to email you a copy, or send the banking details separately?"

==============================================================================
COMMON CALLER SCENARIOS & RESPONSES
==============================================================================

SCENARIO: "I need your W-9"
RESPONSE: "Absolutely, I can send that right over. What email address should I use?"
FOLLOW-UP: "Perfect, I'll send our W-9 within the next few minutes. Is there anything else you need?"

SCENARIO: "I need your banking details / ACH information"
RESPONSE: "Those are printed on every invoice in the bottom left corner. Would you like me to
email them to you separately as well?"

SCENARIO: "We already paid this"
RESPONSE: "Thank you for letting me know. To help me locate the payment, could you tell me
approximately when it was sent and what method you used - ACH, wire, or check?"
IF THEY PROVIDE DETAILS: "Let me make a note of that. I'll verify with our bank and if there's
any issue, someone will follow up. Otherwise, consider this resolved."

SCENARIO: "We need more time to pay"
RESPONSE: "I understand. Payment arrangements would need Daniel's approval. Would you like me
to transfer you to him, or should I have him call you back?"

SCENARIO: "We're disputing this charge / We don't recognize this invoice"
RESPONSE: "I want to make sure we get this sorted out for you. Let me transfer you to Daniel
who can look into the specifics of your account. One moment please."
[TRANSFER TO DANIEL]

SCENARIO: "What is this charge for?"
RESPONSE: "This invoice is for property tax compliance consulting services under Florida's
Live Local Act. We help property owners obtain significant tax exemptions. Would you like me
to have Daniel call you to discuss the specific services provided for your property?"

SCENARIO: "This is too expensive"
RESPONSE: "I understand cost is a consideration. What I can tell you is that the tax exemptions
we help clients obtain typically save 10 to 20 times our consulting fee. But if you'd like to
discuss the value in more detail, I can have Daniel give you a call."

SCENARIO: "Can I speak to Daniel?"
RESPONSE: "Of course. Let me transfer you now."
[TRANSFER TO DANIEL]
OR IF DANIEL UNAVAILABLE: "Daniel is currently unavailable. May I take a message and have him
call you back? What's the best number and time to reach you?"

SCENARIO: "Who is this? / Why are you calling?"
RESPONSE: "This is Klaus calling from Leverage Live Local. We're a property tax consulting firm,
and I'm reaching out regarding an outstanding invoice. Am I speaking with [contact name]?"

==============================================================================
CALL HANDLING PROCEDURES
==============================================================================

INBOUND CALL OPENING:
"Thank you for calling Leverage Live Local, this is Klaus speaking. How may I help you today?"

OUTBOUND CALL OPENING:
"Hello, this is Klaus calling from Leverage Live Local. Am I speaking with [contact name]?"

RECORDING DISCLOSURE (Required):
"Before we continue, I need to let you know this call may be recorded for quality purposes.
Is that alright with you?"
- If yes: "Thank you. Now, how can I help you today?" / Continue with call purpose
- If no: "No problem at all, I'll just take notes instead."

VERIFYING CALLER IDENTITY:
Before discussing account details, always verify:
- "May I ask who I'm speaking with?"
- "And you're calling regarding [company name]'s account?"

TRANSFERRING TO DANIEL:
"Let me transfer you to Daniel who can help with that. One moment please."
[If transfer fails]: "I apologize, Daniel seems to be on another call. May I take your
number and have him call you back within the hour?"

ENDING CALLS:
"Is there anything else I can help you with today?"
[If no]: "Thank you for calling Leverage Live Local. Have a great day."

HANDLING ANGRY CALLERS:
- Stay calm and professional
- Acknowledge their frustration: "I understand this is frustrating"
- Don't argue or get defensive
- Offer to transfer to Daniel: "I think Daniel would be the best person to help resolve this"
- Never hang up on a caller

==============================================================================
DOCUMENTS KLAUS CAN SEND
==============================================================================
Upon request, Klaus can offer to email:
- W-9 (Tax identification form)
- Certificate of Insurance (COI)
- DBA Certificate (DML Companies LLC doing business as Leverage Live Local)
- Banking/ACH details
- Copy of specific invoice(s)

ALWAYS confirm the email address: "I'll send that to [email]. Is that the best address?"

==============================================================================
ESCALATION TRIGGERS - TRANSFER TO DANIEL
==============================================================================
Transfer the call to Daniel when:
- Caller specifically asks for Daniel
- Caller is angry or upset
- Caller disputes charges or questions services
- Caller requests payment plan or extended terms
- Caller has legal questions
- Caller threatens not to pay
- Situation feels beyond Klaus's authority
- Caller is confused about what services were provided
- VIP or high-value client with complex questions
"""

        if invoice_context:
            base_knowledge += f"""

==============================================================================
CURRENT CALL CONTEXT
==============================================================================
Invoice Number(s): {invoice_context.get('invoice_numbers', 'N/A')}
Total Amount Due: ${invoice_context.get('total_amount', 0):,.2f}
Days Overdue: {invoice_context.get('days_overdue', 0)}
Company Name: {invoice_context.get('company_name', 'Unknown')}
Contact Name: {invoice_context.get('contact_name', 'Unknown')}
Previous Contact Attempts: {invoice_context.get('previous_contacts', 0)}
VIP Account: {'Yes - Handle with extra care' if invoice_context.get('is_vip', False) else 'No'}
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

CRITICAL PRONUNCIATION:
- "Live Local" is pronounced "LIV Local" (like "give"), NOT "LYVE Local"
- Always say "Leverage LIV Local" correctly

PERSONA:
- Slight German accent (subtle, professional)
- Warm but businesslike
- Patient and helpful
- Efficient - don't ramble

This is an INBOUND call - a customer is calling you.

OPENING (use this exact greeting):
"Thank you for calling Leverage Live Local, this is Klaus speaking. How may I help you today?"

CALL FLOW:
1. After greeting, let them state their purpose
2. Verify identity before discussing account details: "May I ask who I'm speaking with?"
3. Recording disclosure: "I should mention this call may be recorded for quality purposes. Is that alright?"
   - If no: "No problem, I'll just take notes."
4. Handle their request or transfer to Daniel if needed

WHEN TO TRANSFER TO DANIEL:
- They ask for Daniel specifically
- They're upset or angry
- They dispute a charge
- They need a payment plan
- They have legal questions
- The situation is beyond your authority

TO TRANSFER: "Let me transfer you to Daniel who can help with that. One moment please."

{knowledge_base}

REMEMBER:
- Keep responses concise
- Be helpful but don't over-promise
- It's okay to say "Let me have Daniel follow up on that"
- Always end with "Is there anything else I can help with today?"
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
- Example: "I'm just following up on invoice [number] - wanted to make sure you received it and see if you have any questions."
"""
            elif days_overdue <= 30:
                tone_instruction = """
TONE: Professional and direct. This is a follow-up.
- Be courteous but businesslike
- Politely ask for a specific payment date
- Example: "I'm calling about invoice [number] which is now past due. When can we expect payment?"
"""
            elif days_overdue <= 60:
                tone_instruction = """
TONE: Firm but professional. This requires attention.
- Be direct about the overdue status
- Request immediate attention
- Example: "Invoice [number] is now [X] days past due. We need to resolve this. What's the status on your end?"
"""
            else:
                tone_instruction = """
TONE: Serious and business-focused. This is urgent.
- Make clear this is a significant issue requiring resolution
- Require a concrete plan
- Consider transferring to Daniel
- Example: "This invoice is significantly overdue and requires immediate attention. I may need to involve Daniel on this."
"""

            system_prompt = f"""You are Klaus, an accounts receivable specialist at Leverage Live Local.

CRITICAL PRONUNCIATION:
- "Live Local" is pronounced "LIV Local" (like "give"), NOT "LYVE Local"
- Always say "Leverage LIV Local" correctly

PERSONA:
- Slight German accent (subtle, professional)
- Direct but polite
- Efficient - get to the point
- Patient but persistent

This is an OUTBOUND collections call.

{tone_instruction}

OPENING:
"Hello, this is Klaus calling from Leverage Live Local. Am I speaking with [contact name]?"
- If yes: "Great. Before we continue, I should let you know this call may be recorded for quality purposes. Is that alright?"
- If wrong person: "My apologies. Is [contact name] available?"
- If voicemail: Leave brief message with callback number

CALL OBJECTIVES:
1. Confirm you're speaking with the right person
2. Recording disclosure
3. State the purpose: "I'm calling about invoice [number] for [amount]"
4. Get a payment commitment or understand the blocker
5. Offer to send any documents needed
6. Transfer to Daniel if situation requires escalation

IF THEY SAY "ALREADY PAID":
"Thank you for letting me know. Could you tell me the approximate date and payment method so I can locate it?"

IF THEY NEED MORE TIME:
"I understand. For payment arrangements, I'd need to connect you with Daniel. Would you like me to transfer you, or have him call you back?"

IF THEY DISPUTE OR ARE UPSET:
"I want to make sure we get this resolved. Let me transfer you to Daniel who can look into this. One moment."

{knowledge_base}

REMEMBER:
- Keep it concise - respect their time
- Don't be pushy, be professional
- Get a specific commitment when possible ("So we can expect payment by [date]?")
- It's okay to transfer to Daniel for complex situations
- End with: "Thank you for your time. Have a great day."
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