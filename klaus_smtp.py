"""
Klaus SMTP Email Client
Sends collection emails via SMTP when Gmail API credentials are not available
Saves sent emails to Sent folder via IMAP
"""

import os
import smtplib
import imaplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, Optional, List
from datetime import datetime
import time


class KlausSMTPClient:
    """Send Klaus collection emails via SMTP with Sent folder saving"""
    
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        
        if not self.smtp_user or not self.smtp_password:
            raise ValueError("SMTP_USER and SMTP_PASSWORD environment variables required")
    
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
        Send an email via SMTP and save to Sent folder
        
        Args:
            to_email: Recipient email address
            to_name: Recipient name
            subject: Email subject
            body: Email body (plain text)
            cc: Optional CC email address
            attachments: Optional list of file paths to attach
            invoice_map: Optional dict mapping invoice IDs to HubSpot URLs (for hyperlinking)
        
        Returns:
            Dict with status and message_id
        """
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.smtp_user
            msg['To'] = to_email
            msg['Date'] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
            
            if cc:
                msg['Cc'] = cc
            
            # Convert body to HTML with proper formatting
            html_body = self._text_to_html(body, invoice_map)
            
            # Attach both plain text and HTML versions
            msg.attach(MIMEText(body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
            
            # Add attachments if any
            if attachments:
                for filepath in attachments:
                    if os.path.exists(filepath):
                        with open(filepath, 'rb') as f:
                            part = MIMEBase('application', 'octet-stream')
                            part.set_payload(f.read())
                            encoders.encode_base64(part)
                            part.add_header(
                                'Content-Disposition',
                                f'attachment; filename="{os.path.basename(filepath)}"'
                            )
                            msg.attach(part)
            
            # Send email
            recipients = [to_email]
            if cc:
                recipients.append(cc)
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            # Save to Sent folder via IMAP
            self._save_to_sent(msg)
            
            return {
                "status": "success",
                "message_id": f"smtp-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "to": to_email,
                "subject": subject
            }
            
        except smtplib.SMTPAuthenticationError as e:
            return {
                "status": "error",
                "error": f"SMTP authentication failed: {str(e)}"
            }
        except smtplib.SMTPException as e:
            return {
                "status": "error",
                "error": f"SMTP error: {str(e)}"
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }
    
    def _save_to_sent(self, msg: MIMEMultipart) -> bool:
        """Save email to Sent folder via IMAP"""
        try:
            # Connect to IMAP
            imap = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            imap.login(self.smtp_user, self.smtp_password)
            
            # Select the Sent folder (Gmail uses "[Gmail]/Sent Mail")
            sent_folder = "[Gmail]/Sent Mail"
            
            # Append message to Sent folder
            imap.append(
                sent_folder,
                "\\Seen",
                imaplib.Time2Internaldate(time.time()),
                msg.as_bytes()
            )
            
            imap.logout()
            return True
            
        except Exception as e:
            print(f"⚠ Failed to save to Sent folder: {e}")
            return False
    
    def _text_to_html(self, text: str, invoice_map: Optional[Dict[str, str]] = None) -> str:
        """Convert plain text email to HTML with proper formatting"""
        
        # Escape HTML special characters
        html = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Convert newlines to <br>
        html = html.replace('\n', '<br>\n')
        
        # If invoice_map provided, convert invoice numbers to hyperlinks
        if invoice_map:
            for invoice_id, url in invoice_map.items():
                # Look for invoice number patterns
                for pattern in [invoice_id, f"#{invoice_id}", f"Invoice {invoice_id}"]:
                    if pattern in html:
                        html = html.replace(
                            pattern,
                            f'<a href="{url}" style="color: #0066cc;">{pattern}</a>'
                        )
        
        # Wrap in HTML template
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    font-size: 14px;
                    line-height: 1.6;
                    color: #333;
                }}
                a {{
                    color: #0066cc;
                }}
            </style>
        </head>
        <body>
            {html}
        </body>
        </html>
        """
        
        return html_template


# Initialize global SMTP client
klaus_smtp = None

def get_klaus_smtp():
    """Get or create Klaus SMTP client"""
    global klaus_smtp
    if klaus_smtp is None:
        try:
            klaus_smtp = KlausSMTPClient()
        except ValueError as e:
            print(f"⚠ Klaus SMTP not available: {e}")
            return None
    return klaus_smtp
