"""
Klaus Voice Setup Script
Helps configure Vapi.ai for Klaus voice calling functionality

Run this script to:
1. Verify your Vapi API key
2. Purchase a phone number
3. Create the Klaus assistant
4. Configure inbound call handling
5. Set up webhooks
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()


class VapiSetup:
    def __init__(self):
        self.api_key = os.getenv("VAPI_API_KEY")
        self.base_url = "https://api.vapi.ai"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def verify_api_key(self):
        """Verify the Vapi API key is valid"""
        print("\n🔑 Verifying Vapi API key...")
        
        if not self.api_key:
            print("❌ VAPI_API_KEY not set in environment variables")
            return False
        
        try:
            response = requests.get(
                f"{self.base_url}/assistant",
                headers=self.headers
            )
            
            if response.status_code == 200:
                print("✅ API key is valid")
                return True
            else:
                print(f"❌ API key validation failed: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        
        except Exception as e:
            print(f"❌ Error connecting to Vapi: {e}")
            return False
    
    def list_phone_numbers(self):
        """List existing phone numbers"""
        print("\n📞 Checking existing phone numbers...")
        
        try:
            response = requests.get(
                f"{self.base_url}/phone-number",
                headers=self.headers
            )
            
            if response.status_code == 200:
                numbers = response.json()
                if numbers:
                    print(f"   Found {len(numbers)} phone number(s):")
                    for num in numbers:
                        print(f"   - {num.get('number', 'N/A')} (ID: {num.get('id', 'N/A')})")
                    return numbers
                else:
                    print("   No phone numbers configured yet")
                    return []
            else:
                print(f"❌ Failed to get phone numbers: {response.text}")
                return []
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return []
    
    def purchase_phone_number(self, area_code="305"):
        """Purchase a new phone number"""
        print(f"\n📱 Purchasing phone number with area code {area_code}...")
        
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
                data = response.json()
                print(f"✅ Phone number purchased: {data.get('number', 'N/A')}")
                print(f"   Phone Number ID: {data.get('id')}")
                print(f"\n   Add this to your .env file:")
                print(f"   VAPI_PHONE_NUMBER_ID={data.get('id')}")
                return data
            else:
                print(f"❌ Failed to purchase: {response.text}")
                return None
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return None
    
    def create_assistant(self):
        """Create the Klaus voice assistant"""
        print("\n🤖 Creating Klaus assistant...")
        
        assistant_config = {
            "name": "Klaus Collections Agent",
            "voice": {
                "provider": "11labs",
                "voiceId": "pNInz6obpgDQGcFmaJgB",
                "stability": 0.7,
                "similarityBoost": 0.8,
                "style": 0.3,
                "useSpeakerBoost": True
            },
            "model": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "temperature": 0.7,
                "systemPrompt": """You are Klaus, an accounts receivable specialist at Leverage Live Local. 
You speak with a slight German accent and are always professional.

Your role is to handle collections calls for property tax compliance services.
You can discuss invoice details, provide payment information, and send documents.
For complex issues, you should transfer to Daniel.

Communication Style:
- Professional but warm
- Patient and understanding
- Clear and direct
- Slight German accent (but fully fluent English)

Important: Always ask for permission to record at the start of each call.""",
                "maxTokens": 500
            },
            "recordingEnabled": True,
            "endCallMessage": "Thank you for your time. Have a great day.",
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "en"
            },
            "silenceTimeoutSeconds": 30,
            "maxDurationSeconds": 600
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/assistant",
                headers=self.headers,
                json=assistant_config
            )
            
            if response.status_code == 201:
                data = response.json()
                print(f"✅ Assistant created: {data.get('name')}")
                print(f"   Assistant ID: {data.get('id')}")
                print(f"\n   Add this to your .env file:")
                print(f"   VAPI_ASSISTANT_ID={data.get('id')}")
                return data
            else:
                print(f"❌ Failed to create assistant: {response.text}")
                return None
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return None
    
    def list_assistants(self):
        """List existing assistants"""
        print("\n🤖 Checking existing assistants...")
        
        try:
            response = requests.get(
                f"{self.base_url}/assistant",
                headers=self.headers
            )
            
            if response.status_code == 200:
                assistants = response.json()
                if assistants:
                    print(f"   Found {len(assistants)} assistant(s):")
                    for asst in assistants:
                        print(f"   - {asst.get('name', 'N/A')} (ID: {asst.get('id', 'N/A')})")
                    return assistants
                else:
                    print("   No assistants configured yet")
                    return []
            else:
                print(f"❌ Failed to get assistants: {response.text}")
                return []
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return []
    
    def setup_inbound(self, phone_number_id, assistant_id):
        """Configure phone number for inbound calls"""
        print(f"\n📥 Setting up inbound call handling...")
        
        try:
            response = requests.patch(
                f"{self.base_url}/phone-number/{phone_number_id}",
                headers=self.headers,
                json={
                    "assistantId": assistant_id
                }
            )
            
            if response.status_code == 200:
                print("✅ Inbound calls will be handled by Klaus")
                return True
            else:
                print(f"❌ Failed to setup inbound: {response.text}")
                return False
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def test_call(self, to_phone, to_name="Test Contact"):
        """Make a test call"""
        print(f"\n📞 Making test call to {to_phone}...")
        
        assistant_id = os.getenv("VAPI_ASSISTANT_ID")
        phone_number_id = os.getenv("VAPI_PHONE_NUMBER_ID")
        
        if not assistant_id or not phone_number_id:
            print("❌ VAPI_ASSISTANT_ID and VAPI_PHONE_NUMBER_ID must be set")
            return None
        
        call_config = {
            "assistantId": assistant_id,
            "phoneNumberId": phone_number_id,
            "customer": {
                "number": to_phone,
                "name": to_name
            },
            "assistantOverrides": {
                "firstMessage": f"Hello, this is Klaus. This is a test call to verify our voice system is working. Am I speaking with {to_name}?"
            }
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/call/phone",
                headers=self.headers,
                json=call_config
            )
            
            if response.status_code == 201:
                data = response.json()
                print(f"✅ Test call initiated!")
                print(f"   Call ID: {data.get('id')}")
                return data
            else:
                print(f"❌ Failed to make call: {response.text}")
                return None
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return None


def print_setup_guide():
    """Print setup guide"""
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                     KLAUS VOICE SETUP GUIDE                                ║
╠════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  1. GET A VAPI API KEY                                                     ║
║     - Go to https://vapi.ai and create an account                          ║
║     - Navigate to Dashboard > API Keys                                      ║
║     - Create a new API key                                                  ║
║     - Add to .env: VAPI_API_KEY=your_key_here                              ║
║                                                                            ║
║  2. PURCHASE A PHONE NUMBER                                                 ║
║     - Run: python klaus_voice_setup.py purchase-number                      ║
║     - This costs ~$15/month through Vapi                                   ║
║     - Add the ID to .env: VAPI_PHONE_NUMBER_ID=id_here                     ║
║                                                                            ║
║  3. CREATE THE ASSISTANT                                                    ║
║     - Run: python klaus_voice_setup.py create-assistant                     ║
║     - Add the ID to .env: VAPI_ASSISTANT_ID=id_here                        ║
║                                                                            ║
║  4. CONFIGURE WEBHOOK (for Railway deployment)                              ║
║     - Add to .env: KLAUS_WEBHOOK_URL=https://your-app.railway.app/webhooks/vapi
║                                                                            ║
║  5. SET DANIEL'S PHONE NUMBER                                               ║
║     - Add to .env: DANIEL_PHONE_NUMBER=+1XXXXXXXXXX                        ║
║                                                                            ║
║  6. TEST THE SETUP                                                          ║
║     - Run: python klaus_voice_setup.py test +1XXXXXXXXXX                    ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
    """)


def main():
    setup = VapiSetup()
    
    if len(sys.argv) < 2:
        print_setup_guide()
        print("\nAvailable commands:")
        print("  verify           - Verify API key")
        print("  status           - Show current configuration")
        print("  purchase-number  - Purchase a phone number")
        print("  create-assistant - Create Klaus assistant")
        print("  setup-inbound    - Configure inbound call handling")
        print("  test <phone>     - Make a test call")
        print("\nExample: python klaus_voice_setup.py verify")
        return
    
    command = sys.argv[1].lower()
    
    if command == "verify":
        setup.verify_api_key()
    
    elif command == "status":
        print("\n📊 KLAUS VOICE STATUS")
        print("=" * 50)
        
        if setup.verify_api_key():
            setup.list_phone_numbers()
            setup.list_assistants()
            
            print("\n📋 Environment Variables:")
            print(f"   VAPI_API_KEY: {'✅ Set' if os.getenv('VAPI_API_KEY') else '❌ Not set'}")
            print(f"   VAPI_PHONE_NUMBER_ID: {os.getenv('VAPI_PHONE_NUMBER_ID', '❌ Not set')}")
            print(f"   VAPI_ASSISTANT_ID: {os.getenv('VAPI_ASSISTANT_ID', '❌ Not set')}")
            print(f"   DANIEL_PHONE_NUMBER: {os.getenv('DANIEL_PHONE_NUMBER', '❌ Not set')}")
            print(f"   KLAUS_WEBHOOK_URL: {os.getenv('KLAUS_WEBHOOK_URL', '❌ Not set')}")
    
    elif command == "purchase-number":
        area_code = sys.argv[2] if len(sys.argv) > 2 else "305"
        setup.purchase_phone_number(area_code)
    
    elif command == "create-assistant":
        setup.create_assistant()
    
    elif command == "setup-inbound":
        phone_id = os.getenv("VAPI_PHONE_NUMBER_ID")
        asst_id = os.getenv("VAPI_ASSISTANT_ID")
        
        if not phone_id or not asst_id:
            print("❌ VAPI_PHONE_NUMBER_ID and VAPI_ASSISTANT_ID must be set first")
            return
        
        setup.setup_inbound(phone_id, asst_id)
    
    elif command == "test":
        if len(sys.argv) < 3:
            print("❌ Please provide a phone number: python klaus_voice_setup.py test +1XXXXXXXXXX")
            return
        
        phone = sys.argv[2]
        name = sys.argv[3] if len(sys.argv) > 3 else "Test Contact"
        setup.test_call(phone, name)
    
    else:
        print(f"❌ Unknown command: {command}")
        print("   Run without arguments to see available commands")


if __name__ == "__main__":
    main()
