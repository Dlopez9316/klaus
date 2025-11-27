# Klaus Voice Integration Guide

## Overview

Klaus Voice enables autonomous phone calls for collections using AI-powered conversations. The system uses **Vapi.ai** for voice infrastructure, which provides:

- AI-powered phone conversations using Claude
- Automatic transcription and recording
- Inbound and outbound call handling
- Real-time webhooks for call events

**Important Note:** Google Voice doesn't have a public API for programmatic calling. This integration uses Vapi's phone infrastructure with a dedicated phone number (~$15/month).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         KLAUS VOICE SYSTEM                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐ │
│  │   Call      │    │   Call      │    │    VoiceCallQueue       │ │
│  │  Scheduler  │───▶│   Queue     │───▶│  (Rate-limited calls)   │ │
│  └─────────────┘    └─────────────┘    └───────────┬─────────────┘ │
│                                                     │               │
│                                                     ▼               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   KlausVoiceAgent                            │   │
│  │  • Creates/updates Vapi assistants                           │   │
│  │  • Makes outbound calls                                      │   │
│  │  • Handles webhooks                                          │   │
│  │  • Analyzes call outcomes                                    │   │
│  │  • Maintains call history                                    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      VAPI.AI                                 │   │
│  │  • Claude-powered conversations                              │   │
│  │  • ElevenLabs voice synthesis                                │   │
│  │  • Deepgram transcription                                    │   │
│  │  • Phone number management                                   │   │
│  │  • Call recordings                                           │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Setup Instructions

### Step 1: Create Vapi Account

1. Go to [https://vapi.ai](https://vapi.ai) and create an account
2. Navigate to Dashboard > API Keys
3. Create a new API key
4. Copy the key for your `.env` file

### Step 2: Configure Environment Variables

Add these to your `.env` file:

```bash
# Required
VAPI_API_KEY=your_vapi_api_key_here

# Set after running setup script
VAPI_PHONE_NUMBER_ID=your_phone_number_id
VAPI_ASSISTANT_ID=your_assistant_id

# Required for call transfers
DANIEL_PHONE_NUMBER=+1XXXXXXXXXX

# Webhook URL (your Railway deployment)
KLAUS_WEBHOOK_URL=https://your-app.railway.app/klaus/voice/webhook

# Optional configuration
VOICE_DAILY_CALL_LIMIT=10
VOICE_TIMEZONE=US/Eastern
```

### Step 3: Run Setup Script

```bash
# Verify your API key
python klaus_voice_setup.py verify

# See current status
python klaus_voice_setup.py status

# Purchase a phone number (~$15/month)
python klaus_voice_setup.py purchase-number 305

# Create the Klaus assistant
python klaus_voice_setup.py create-assistant

# Configure inbound call handling
python klaus_voice_setup.py setup-inbound

# Test with a call to yourself
python klaus_voice_setup.py test +1XXXXXXXXXX "Your Name"
```

### Step 4: Update main.py

See `VOICE_INTEGRATION_PATCH.py` for the exact code changes needed.

Quick summary:
1. Add the new imports
2. Replace the voice initialization section
3. Add router registration
4. Add the scheduled call processor

### Step 5: Deploy to Railway

1. Commit your changes
2. Push to Railway
3. Add all environment variables in Railway dashboard
4. Verify webhook URL is accessible

## API Endpoints

### Phone Number Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/klaus/voice/phone-numbers` | GET | List all phone numbers |
| `/klaus/voice/phone-numbers/purchase` | POST | Purchase a new number |
| `/klaus/voice/phone-numbers/setup-inbound` | POST | Configure inbound handling |

### Outbound Calls

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/klaus/voice/call` | POST | Make an immediate call |
| `/klaus/voice/call/from-invoice/{id}` | POST | Call about specific invoice |

### Call Scheduling

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/klaus/voice/schedule` | GET | List scheduled calls |
| `/klaus/voice/schedule` | POST | Schedule a call |
| `/klaus/voice/schedule/pending` | GET | Get calls ready to make |
| `/klaus/voice/schedule/{id}` | DELETE | Cancel scheduled call |

### Call Queue

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/klaus/voice/queue` | POST | Add call to queue |
| `/klaus/voice/queue/process` | POST | Process queue now |
| `/klaus/voice/queue/status` | GET | Get queue status |

### Call History

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/klaus/voice/history` | GET | Get call history |
| `/klaus/voice/history/{call_id}` | GET | Get call details |
| `/klaus/voice/history/{call_id}/transcript` | GET | Get call transcript |
| `/klaus/voice/history/{call_id}/recording` | GET | Get recording URL |

### Contact Ledger Integration

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/klaus/voice/ledger/{company_name}` | GET | Get calls for company |

### Status

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/klaus/voice/status` | GET | Get overall status |
| `/klaus/voice/business-hours` | GET | Get business hours config |

## Usage Examples

### Make an Immediate Call

```python
import requests

response = requests.post(
    "https://your-app.railway.app/klaus/voice/call",
    json={
        "phone": "+13055551234",
        "contact_name": "John Smith",
        "company_name": "Acme Properties",
        "invoice_ids": ["INV-001", "INV-002"],
        "total_amount": 15000.00,
        "days_overdue": 21,
        "is_vip": False
    }
)

print(response.json())
# {
#     "status": "success",
#     "call_id": "call_abc123",
#     "message": "Call initiated to John Smith at +13055551234"
# }
```

### Schedule a Call for Later

```python
response = requests.post(
    "https://your-app.railway.app/klaus/voice/schedule",
    json={
        "phone": "+13055551234",
        "contact_name": "Jane Doe",
        "company_name": "Harbor Properties",
        "invoice_ids": ["INV-003"],
        "total_amount": 8500.00,
        "target_time": "2025-01-15T14:00:00",
        "timezone": "US/Eastern"
    }
)
```

### Add Multiple Calls to Queue

```python
# Add high-priority call (priority 8)
requests.post(
    "https://your-app.railway.app/klaus/voice/queue",
    json={
        "phone": "+13055551234",
        "contact_name": "Urgent Client",
        "company_name": "Important Corp",
        "invoice_ids": ["INV-004"],
        "total_amount": 50000.00,
        "days_overdue": 45,
        "priority": 8
    }
)

# Process all queued calls
response = requests.post(
    "https://your-app.railway.app/klaus/voice/queue/process"
)
```

### Get Call Transcript

```python
response = requests.get(
    "https://your-app.railway.app/klaus/voice/history/call_abc123/transcript"
)

print(response.json()['transcript'])
```

## Call Outcome Analysis

Klaus automatically analyzes call transcripts to determine outcomes:

| Outcome | Triggers | Follow-up Action |
|---------|----------|------------------|
| `payment_promised` | "will pay", "send payment" | Confirm payment received |
| `documents_requested` | "need W-9", "need COI" | Send requested documents |
| `dispute` | "dispute", "wrong amount" | Escalate to Daniel |
| `claims_paid` | "already paid", "sent payment" | Verify in reconciliation |
| `needs_time` | "cash flow", "need more time" | Schedule follow-up call |
| `voicemail` | Call went to voicemail | Send email follow-up |
| `no_answer` | No answer | Schedule retry |
| `transferred_to_daniel` | "speak to Daniel" | Daniel follow-up |
| `wrong_number` | "wrong number" | Update contact info |

## Business Hours

Calls are only made during business hours:
- **Days**: Monday - Friday
- **Hours**: 9 AM - 5 PM Eastern
- **Daily Limit**: 10 calls (configurable)

Calls scheduled outside business hours are automatically moved to the next available slot.

## Voice Configuration

Klaus uses ElevenLabs for voice synthesis with these settings:
- **Voice**: Adam (professional male)
- **Stability**: 0.7
- **Similarity Boost**: 0.8
- **Style**: 0.3 (slight German accent)

## Webhook Events

Set `KLAUS_WEBHOOK_URL` to receive these events:

### end-of-call-report
Received when a call completes. Contains:
- Call duration
- Full transcript
- Recording URL
- Call status

### status-update
Real-time status changes:
- ringing
- in-progress
- completed
- failed

### transcript
Real-time transcript updates during the call.

## Integration with Contact Ledger

Klaus Voice automatically integrates with the contact ledger. Every call is recorded with:

- Call date/time
- Duration
- Direction (inbound/outbound)
- Outcome
- Transcript availability
- Recording availability
- Follow-up requirements

Query the ledger:
```python
response = requests.get(
    "https://your-app.railway.app/klaus/voice/ledger/Acme%20Properties"
)

for call in response.json()['calls']:
    print(f"{call['date']}: {call['outcome']} ({call['duration_seconds']}s)")
```

## Cost Estimates

| Item | Cost |
|------|------|
| Vapi Phone Number | ~$15/month |
| Outbound Calls | ~$0.05-0.15/minute |
| Inbound Calls | ~$0.05-0.10/minute |
| Transcription | Included |
| Recording Storage | Included |

Estimated monthly cost for 100 calls averaging 3 minutes: **~$60-75**

## Troubleshooting

### "Klaus Voice not available"
- Check `VAPI_API_KEY` is set
- Run `python klaus_voice_setup.py verify`

### "Failed to configure assistant"
- Check your Vapi API key has proper permissions
- Verify you haven't exceeded account limits

### Calls failing
- Verify phone number is in E.164 format (+1XXXXXXXXXX)
- Check the phone number ID is correct
- Look at Vapi dashboard for error details

### No webhooks received
- Verify `KLAUS_WEBHOOK_URL` is publicly accessible
- Check Railway logs for incoming requests
- Test with: `curl -X POST https://your-app.railway.app/klaus/voice/webhook -d '{}'`

### Call quality issues
- Adjust voice settings (stability, similarity boost)
- Check ElevenLabs voice is available
- Consider using Vapi's built-in voices

## Security Notes

1. **Recording Consent**: Klaus always asks for permission to record at the start of each call
2. **Data Retention**: Call recordings are stored by Vapi; set retention policies in their dashboard
3. **PII Handling**: Transcripts may contain sensitive information; handle appropriately
4. **Transfer Authorization**: Only Daniel's phone number can receive transfers

## Files Reference

| File | Description |
|------|-------------|
| `klaus_voice.py` | Core voice agent, scheduler, and queue classes |
| `klaus_voice_routes.py` | FastAPI endpoints for voice functionality |
| `klaus_voice_setup.py` | CLI setup script for Vapi configuration |
| `klaus_call_history.json` | Persisted call history |
| `klaus_scheduled_calls.json` | Persisted scheduled calls |
| `klaus_call_queue.json` | Persisted call queue |
| `VOICE_INTEGRATION_PATCH.py` | Instructions for main.py integration |
