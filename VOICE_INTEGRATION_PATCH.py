"""
MAIN.PY VOICE INTEGRATION PATCH

This file contains the code snippets you need to add to main.py to integrate
the new Klaus Voice functionality.

Instructions:
1. Add the imports at the top of main.py
2. Replace the voice initialization section
3. Add the router registration after app initialization
"""

# =============================================================================
# STEP 1: ADD THESE IMPORTS (near the top of main.py, after existing imports)
# =============================================================================

"""
# Add after: from klaus_voice import KlausVoiceAgent, CallScheduler
from klaus_voice import KlausVoiceAgent, CallScheduler, VoiceCallQueue
from klaus_voice_routes import router as voice_router, init_voice_routes
"""


# =============================================================================
# STEP 2: REPLACE THE VOICE INITIALIZATION SECTION
# =============================================================================

"""
# Find and replace this section (around lines 102-118):

# Initialize Klaus Voice (only if Vapi key is available)
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
"""


# =============================================================================
# STEP 3: ADD ROUTER REGISTRATION (after app.add_middleware section)
# =============================================================================

"""
# Add after the CORSMiddleware section (around line 50):

# Initialize voice routes with dependencies
init_voice_routes(
    voice_agent=klaus_voice,
    scheduler=call_scheduler,
    queue=call_queue,
    hubspot=hubspot_client,
    engine=klaus_engine
)

# Register voice router
app.include_router(voice_router)
"""


# =============================================================================
# STEP 4: UPDATE THE STARTUP EVENT (add call queue processing)
# =============================================================================

"""
# Add this to the startup_event function to process scheduled calls:

# Start scheduled call processor
if call_queue:
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.add_job(
        process_scheduled_voice_calls,
        IntervalTrigger(minutes=5),
        id='voice_call_processor'
    )
    print("✓ Voice call processor scheduled")
"""


# =============================================================================
# STEP 5: ADD THIS HELPER FUNCTION (before the startup_event function)
# =============================================================================

"""
async def process_scheduled_voice_calls():
    '''Process pending scheduled calls and queue'''
    
    if not call_queue or not call_scheduler:
        return
    
    # Check for pending scheduled calls
    pending = call_scheduler.get_pending_calls()
    
    for scheduled_call in pending:
        # Add to queue with high priority
        call_queue.add_to_queue(
            phone=scheduled_call['phone'],
            contact_name=scheduled_call['contact_name'],
            company_name=scheduled_call['company_name'],
            invoice_ids=scheduled_call['invoice_ids'],
            total_amount=scheduled_call['total_amount'],
            days_overdue=0,
            priority=8  # High priority for scheduled calls
        )
        
        # Mark as processed
        call_scheduler.mark_call_completed(scheduled_call['id'])
    
    # Process the queue
    if call_scheduler.is_good_time_to_call():
        results = call_queue.process_queue()
        if results:
            print(f"Voice queue processed: {len(results)} calls")
"""


# =============================================================================
# COMPLETE UPDATED SECTION (copy-paste ready)
# =============================================================================

COMPLETE_VOICE_INIT_SECTION = '''
# Klaus imports
from klaus_engine import KlausEngine
from klaus_gmail import KlausGmailClient, KlausEmailResponder
from klaus_google_drive import KlausGoogleDrive, KlausKnowledgeBase
from klaus_voice import KlausVoiceAgent, CallScheduler, VoiceCallQueue
from klaus_voice_routes import router as voice_router, init_voice_routes
from klaus_startup import setup_klaus_credentials

# ... (after app and middleware setup) ...

# Initialize Klaus Voice (only if Vapi key is available)
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
        
        # Initialize voice routes with dependencies
        init_voice_routes(
            voice_agent=klaus_voice,
            scheduler=call_scheduler,
            queue=call_queue,
            hubspot=hubspot_client,
            engine=klaus_engine
        )
        
        # Register voice router
        app.include_router(voice_router)
        
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
'''

if __name__ == "__main__":
    print(COMPLETE_VOICE_INIT_SECTION)
