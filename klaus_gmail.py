"""
Klaus Gmail Integration
Sends and receives emails for collections
NOW WITH HTML EMAILS AND INVOICE HYPERLINKING
FIXED: Hyperlinker no longer matches invoice numbers inside URLs
"""

import os
import base64
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle


class InvoiceHyperlinker:
    """
    Utility class to convert invoice numbers in text to clickable HubSpot links
    FIXED: Now uses negative lookbehind to avoid matching inside URLs
    """
    
    @staticmethod
    def hyperlink_invoices(text: str, invoice_map: Dict[str, str]) -> str:
        """
        Convert plain text to HTML with invoice numbers as hyperlinks
        
        FIXED: Uses negative lookbehind (?<![/=]) to prevent matching 
        invoice numbers that appear inside URL paths (e.g., /INV-1001)
        """
        
        # Convert text to HTML-safe (escape special characters)
        html = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Convert newlines to <br>
        html = html.replace('\n', '<br>\n')
        
        # Find and replace invoice numbers with hyperlinks
        # IMPORTANT: Use negative lookbehind to avoid matching inside URLs
        # (?<![/=]) means "not preceded by / or =" (URL context indicators)
        # (?![^<]*</a>) means "not already inside an anchor tag"
        for invoice_number, url in invoice_map.items():
            if not url:
                continue
            
            patterns = [
                rf'(?<![/=])(Invoice\s+#{invoice_number})(?![^<]*</a>)',
                rf'(?<![/=])(Invoice\s+{invoice_number})(?![^<]*</a>)',
                rf'(?<![/=])(INV-{invoice_number})(?![^<]*</a>)',
                rf'(?<![/=\d])(#{invoice_number})(?![^<]*</a>)',
            ]
            
            for pattern in patterns:
                replacement = rf'<a href="{url}" style="color: #0066cc; text-decoration: none; font-weight: bold;">\1</a>'
                html = re.sub(pattern, replacement, html, flags=re.IGNORECASE)
        
        return html
    
    @staticmethod
    def create_html_email(plain_text: str, invoice_map: Dict[str, str]) -> str:
        """
        Create a full HTML email from plain text with hyperlinked invoices
        """
        
        body_html = InvoiceHyperlinker.hyperlink_invoices(plain_text, invoice_map)
        
        html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        a {{
            color: #0066cc;
            text-decoration: none;
            font-weight: bold;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="content">
        {body_html}
    </div>
</body>
</html>
"""
        
        return html_template


class KlausGmailClient:
    """
    Gmail client for Klaus collections agent
    NOW SUPPORTS HTML EMAILS WITH HYPERLINKED INVOICES
    Supports both file-based credentials and environment variables (for Railway)
    """

    SCOPES = [
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.modify'
    ]

    def __init__(self, credentials_file: str = "klaus_credentials.json"):
        self.credentials_file = credentials_file
        self.token_file = "klaus_token.pickle"
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Gmail API - supports env vars or file-based credentials"""
        creds = None

        # Check for environment variables first (Railway deployment)
        refresh_token = os.getenv('GMAIL_REFRESH_TOKEN')
        client_id = os.getenv('GMAIL_CLIENT_ID')
        client_secret = os.getenv('GMAIL_CLIENT_SECRET')

        if refresh_token and client_id and client_secret:
            print("[GMAIL] Using credentials from environment variables")
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_id,
                client_secret=client_secret,
                scopes=self.SCOPES
            )
            # Refresh to get a valid access token
            creds.refresh(Request())
            print("[GMAIL] ✓ Credentials refreshed successfully")
        else:
            # Fall back to file-based credentials (local development)
            print("[GMAIL] Using file-based credentials")
            if os.path.exists(self.token_file):
                with open(self.token_file, 'rb') as token:
                    creds = pickle.load(token)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.credentials_file, self.SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                with open(self.token_file, 'wb') as token:
                    pickle.dump(creds, token)

        self.service = build('gmail', 'v1', credentials=creds)
        print("[GMAIL] ✓ Gmail service initialized")
    
    def send_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[List[str]] = None,
        invoice_map: Optional[Dict[str, str]] = None
    ) -> Dict:
        """
        Send an email (with HTML support and invoice hyperlinking)
        
        Args:
            to_email: Recipient email address
            to_name: Recipient name
            subject: Email subject
            body: Email body (plain text)
            cc: Optional CC email
            attachments: Optional list of file paths to attach
            invoice_map: Dict mapping invoice numbers to HubSpot URLs
                        If provided, invoice numbers will be hyperlinked
        
        Returns:
            Dict with status and message_id
        """
        
        try:
            print(f"[GMAIL] Preparing email to {to_email}")
            print(f"[GMAIL] invoice_map received: {invoice_map}")

            message = MIMEMultipart('alternative')
            message['To'] = f"{to_name} <{to_email}>"
            message['Subject'] = subject

            if cc:
                message['Cc'] = cc

            # Check if body is already HTML
            is_html = body.strip().startswith('<html') or body.strip().startswith('<!DOCTYPE') or '<html>' in body

            if is_html:
                # Body is already HTML - send as HTML
                print("[GMAIL] Body is HTML - sending as HTML email")
                # Add a plain text fallback (strip tags for plain version)
                import re
                plain_text = re.sub('<[^<]+?>', '', body)
                message.attach(MIMEText(plain_text, 'plain'))
                message.attach(MIMEText(body, 'html'))
            elif invoice_map:
                # Plain text with invoice_map - create HTML with hyperlinks
                print(f"[GMAIL] Creating HTML with hyperlinked invoices: {list(invoice_map.keys())}")
                message.attach(MIMEText(body, 'plain'))
                html_body = InvoiceHyperlinker.create_html_email(body, invoice_map)
                message.attach(MIMEText(html_body, 'html'))
                print(f"[GMAIL] HTML body preview: {html_body[:500]}...")
            else:
                # Plain text only
                print("[GMAIL] No invoice_map - sending plain text only")
                message.attach(MIMEText(body, 'plain'))
            
            # Add attachments if provided
            if attachments:
                for file_path in attachments:
                    self._attach_file(message, file_path)
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            
            sent_message = self.service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()
            
            return {
                'status': 'success',
                'message_id': sent_message['id'],
                'sent_at': datetime.now().isoformat(),
                'to': to_email,
                'subject': subject,
                'hyperlinked': bool(invoice_map)
            }
        
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'to': to_email,
                'subject': subject
            }
    
    def _attach_file(self, message: MIMEMultipart, file_path: str):
        """Attach a file to the email message"""
        from email.mime.application import MIMEApplication
        
        with open(file_path, 'rb') as f:
            file_data = f.read()
            filename = os.path.basename(file_path)
            
            part = MIMEApplication(file_data, Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            message.attach(part)
    
    def get_recent_emails(
        self,
        query: str = "in:inbox is:unread",
        max_results: int = 50
    ) -> List[Dict]:
        """Get recent emails matching query"""
        
        try:
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            
            emails = []
            for msg in messages:
                email_data = self.get_email_details(msg['id'])
                if email_data:
                    emails.append(email_data)
            
            return emails
        
        except Exception as e:
            print(f"Error getting emails: {e}")
            return []
    
    def get_email_details(self, message_id: str) -> Dict:
        """Get full details of an email"""
        
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            headers = message['payload']['headers']
            
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
            from_email = next((h['value'] for h in headers if h['name'] == 'From'), '')
            date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
            
            body = self._get_email_body(message['payload'])
            
            return {
                'id': message_id,
                'subject': subject,
                'from': from_email,
                'date': date,
                'body': body,
                'snippet': message.get('snippet', ''),
                'thread_id': message.get('threadId', '')
            }
        
        except Exception as e:
            print(f"Error getting email details: {e}")
            return {}
    
    def _get_email_body(self, payload: Dict) -> str:
        """Extract email body from payload"""
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    if data:
                        return base64.urlsafe_b64decode(data).decode('utf-8')
        
        data = payload.get('body', {}).get('data', '')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8')
        
        return ''
    
    def reply_to_email(
        self,
        thread_id: str,
        message_id: str,
        to_email: str,
        subject: str,
        body: str
    ) -> Dict:
        """Reply to an existing email thread"""
        
        try:
            message = MIMEText(body)
            message['To'] = to_email
            message['Subject'] = f"Re: {subject}" if not subject.startswith('Re:') else subject
            message['In-Reply-To'] = message_id
            message['References'] = message_id
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            
            sent_message = self.service.users().messages().send(
                userId='me',
                body={
                    'raw': raw_message,
                    'threadId': thread_id
                }
            ).execute()
            
            return {
                'status': 'success',
                'message_id': sent_message['id'],
                'thread_id': thread_id
            }
        
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def mark_as_read(self, message_id: str):
        """Mark an email as read"""
        try:
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
        except Exception as e:
            print(f"Error marking as read: {e}")
    
    def add_label(self, message_id: str, label_name: str):
        """Add a label to an email"""
        try:
            label_id = self._get_or_create_label(label_name)
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'addLabelIds': [label_id]}
            ).execute()
        except Exception as e:
            print(f"Error adding label: {e}")
    
    def _get_or_create_label(self, label_name: str) -> str:
        """Get label ID or create if doesn't exist"""
        try:
            results = self.service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])
            
            for label in labels:
                if label['name'] == label_name:
                    return label['id']
            
            label = self.service.users().labels().create(
                userId='me',
                body={
                    'name': label_name,
                    'labelListVisibility': 'labelShow',
                    'messageListVisibility': 'show'
                }
            ).execute()
            
            return label['id']
        
        except Exception as e:
            print(f"Error with labels: {e}")
            return ''
    
    def detect_payment_confirmation(self, email_body: str) -> bool:
        """Detect if an email is a payment confirmation"""
        
        payment_keywords = [
            'payment sent', 'payment processed', 'paid', 'check mailed',
            'wire sent', 'ach transfer', 'invoice paid', 'payment confirmation',
            'transaction complete'
        ]
        
        email_lower = email_body.lower()
        return any(keyword in email_lower for keyword in payment_keywords)
    
    def detect_document_request(self, email_body: str) -> Optional[str]:
        """Detect if email is requesting documents"""
        
        email_lower = email_body.lower()
        
        if any(term in email_lower for term in ['w-9', 'w9', 'ein', 'tax id']):
            return 'w9'
        if any(term in email_lower for term in ['certificate of insurance', 'coi', 'insurance cert']):
            return 'coi'
        if any(term in email_lower for term in ['dba', 'business registration', 'doing business as']):
            return 'dba'
        if 'ach' in email_lower and any(term in email_lower for term in ['form', 'information', 'details']):
            return 'ach_form'
        
        return None
    
    def extract_invoice_number(self, email_body: str) -> Optional[str]:
        """Extract invoice number from email body"""
        
        patterns = [
            r'INV-(\d+)',
            r'Invoice #(\d+)',
            r'Invoice (\d+)',
            r'#(\d{4,})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, email_body, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None


class KlausEmailResponder:
    """Automated email response handler"""
    
    def __init__(self, anthropic_api_key: str):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=anthropic_api_key)
    
    def craft_response(self, email_body: str, context: Dict, scenario: str = 'general') -> str:
        """Use Claude AI to craft appropriate response"""
        
        prompt = f"""You are Klaus, an accounts receivable specialist at Leverage Live Local. 
A client has sent this email regarding Invoice {context.get('invoice_number', 'N/A')} for ${context.get('amount', 0):,.2f}:

---
{email_body}
---

Craft a professional, helpful response. Be warm but firm. Include:
1. Acknowledge their message
2. Address their specific concern
3. Provide next steps
4. Offer assistance

Keep it concise (3-4 short paragraphs). Sign as "Klaus, Leverage Live Local".

Response:"""
        
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            return self._fallback_response(scenario, context)
    
    def _fallback_response(self, scenario: str, context: Dict) -> str:
        """Fallback template responses"""
        
        if scenario == 'payment_confirmation':
            return f"""Thank you for confirming payment on Invoice {context.get('invoice_number')}. 

I'll watch for the payment to process and update our records accordingly. If you need anything else, please let me know.

Best regards,
Klaus
Leverage Live Local"""
        
        elif scenario == 'needs_more_time':
            return f"""I understand. Thanks for letting me know.

Could you give me an expected payment date for Invoice {context.get('invoice_number')} (${context.get('amount', 0):,.2f})? That will help me update our records and avoid further reminders.

Best regards,
Klaus
Leverage Live Local"""
        
        else:
            return f"""Thank you for your message regarding Invoice {context.get('invoice_number')}.

I'll review your request and get back to you shortly. If you need immediate assistance, feel free to call our office.

Best regards,
Klaus
Leverage Live Local"""