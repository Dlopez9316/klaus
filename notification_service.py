"""
Notification Service
Sends reconciliation reports via Email and WhatsApp
Now supports Gmail API in addition to SMTP
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from twilio.rest import Client


class NotificationService:
    """Send reconciliation reports via multiple channels"""

    def __init__(self, gmail_client=None):
        # Gmail API client (preferred for Railway)
        self.gmail_client = gmail_client

        # Email config (SMTP fallback)
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.notification_email = os.getenv("NOTIFICATION_EMAIL", "daniel@leveragelivelocal.com")

        # WhatsApp config (via Twilio)
        self.twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.twilio_whatsapp_from = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g., "whatsapp:+14155238886"
        self.twilio_whatsapp_to = os.getenv("TWILIO_WHATSAPP_TO")      # e.g., "whatsapp:+1234567890"

        self.twilio_client = None
        if self.twilio_account_sid and self.twilio_auth_token:
            try:
                self.twilio_client = Client(self.twilio_account_sid, self.twilio_auth_token)
            except Exception as e:
                print(f"Failed to initialize Twilio client: {e}")
    
    def send_reconciliation_report(
        self,
        matches: List[Dict],
        suggestions: List[Dict],
        stats: Dict,
        via_email: bool = True,
        via_whatsapp: bool = True
    ):
        """Send reconciliation report via configured channels"""
        
        results = {
            "email": {"sent": False, "error": None},
            "whatsapp": {"sent": False, "error": None}
        }
        
        if via_email and self.notification_email:
            try:
                self._send_email_report(matches, suggestions, stats)
                results["email"]["sent"] = True
            except Exception as e:
                results["email"]["error"] = str(e)
        
        if via_whatsapp and self.twilio_whatsapp_to:
            try:
                self._send_whatsapp_report(matches, suggestions, stats)
                results["whatsapp"]["sent"] = True
            except Exception as e:
                results["whatsapp"]["error"] = str(e)
        
        return results
    
    def _send_email_report(self, matches: List[Dict], suggestions: List[Dict], stats: Dict):
        """Send HTML email report via Gmail API or SMTP"""

        high_confidence = [m for m in matches if m.get('confidence', 0) >= 80]
        medium_confidence = [m for m in matches if 70 <= m.get('confidence', 0) < 80]

        # Get dashboard URL from environment or use default
        dashboard_url = os.getenv("DASHBOARD_URL", "https://reconciliation-agent-production.up.railway.app")

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .header {{ background: #6366f1; color: white; padding: 20px; border-radius: 12px; }}
                .stats {{ background: #f8fafc; padding: 15px; margin: 20px 0; border-radius: 12px; }}
                .match {{ border-left: 4px solid #6366f1; padding: 10px; margin: 10px 0; background: #fff; border-radius: 8px; }}
                .high {{ border-left-color: #10b981; }}
                .medium {{ border-left-color: #f59e0b; }}
                .suggestion {{ border-left: 4px solid #f59e0b; padding: 10px; margin: 10px 0; background: #fff; border-radius: 8px; }}
                .badge {{ padding: 5px 10px; border-radius: 5px; font-weight: bold; }}
                .success {{ background: #10b981; color: white; }}
                .warning {{ background: #f59e0b; color: black; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Reconciliation Report</h1>
                <p>Your automated reconciliation has completed</p>
            </div>

            <div class="stats">
                <h2>Summary</h2>
                <p><strong>{stats.get('total_transactions', 0)}</strong> transactions analyzed</p>
                <p><strong>{stats.get('total_invoices', 0)}</strong> open invoices</p>
                <p><strong>{len(matches)}</strong> matches found</p>
                <p><strong>{len(suggestions)}</strong> new association suggestions</p>
            </div>

            <h2>High Confidence Matches (80%+)</h2>
            <p><em>These are ready to approve!</em></p>
        """

        if high_confidence:
            for match in high_confidence[:5]:  # Top 5
                html += f"""
                <div class="match high">
                    <span class="badge success">{match.get('confidence', 0)}%</span>
                    <strong>{match.get('invoice_number', 'N/A')}</strong> - {match.get('company_name', 'Unknown')}<br>
                    <small>Transaction: ${match.get('transaction_amount', 0):.2f} | Invoice: ${match.get('invoice_amount', 0):.2f}</small>
                </div>
                """
        else:
            html += "<p><em>No high-confidence matches found</em></p>"

        if medium_confidence:
            html += "<h2>Medium Confidence Matches (70-79%)</h2>"
            for match in medium_confidence[:3]:
                html += f"""
                <div class="match medium">
                    <span class="badge warning">{match.get('confidence', 0)}%</span>
                    <strong>{match.get('invoice_number', 'N/A')}</strong> - {match.get('company_name', 'Unknown')}<br>
                    <small>Transaction: ${match.get('transaction_amount', 0):.2f} | Invoice: ${match.get('invoice_amount', 0):.2f}</small>
                </div>
                """

        if suggestions:
            html += "<h2>New Association Suggestions</h2>"
            for s in suggestions[:5]:
                html += f"""
                <div class="suggestion">
                    <span class="badge warning">{s.get('confidence', 0)}%</span>
                    <strong>{s.get('transaction_name', 'N/A')}</strong> → {s.get('company_name', 'Unknown')}<br>
                    <small>Based on: {s.get('example_invoice', 'N/A')} (${s.get('example_amount', 0):.2f})</small>
                </div>
                """

        html += f"""
            <div style="margin-top: 30px; padding: 20px; background: #f8fafc; border-radius: 12px;">
                <p><strong><a href="{dashboard_url}">Review matches in dashboard</a></strong></p>
            </div>
        </body>
        </html>
        """

        subject = f"Reconciliation Report: {len(high_confidence)} matches ready"

        # Try Gmail API first (preferred for Railway)
        if self.gmail_client:
            result = self.gmail_client.send_email(
                to_email=self.notification_email,
                to_name="Daniel",
                subject=subject,
                body=html  # Gmail client handles HTML
            )
            if result.get('status') != 'success':
                raise Exception(result.get('error', 'Gmail send failed'))
            return

        # Fallback to SMTP
        if not self.smtp_user or not self.smtp_password:
            raise Exception("No email configuration available (Gmail API or SMTP)")

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.smtp_user
        msg['To'] = self.notification_email

        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
    
    def _send_whatsapp_report(self, matches: List[Dict], suggestions: List[Dict], stats: Dict):
        """Send WhatsApp message via Twilio"""
        
        if not self.twilio_client:
            raise Exception("Twilio not configured")
        
        high_confidence = [m for m in matches if m['confidence'] >= 80]
        
        message = f"""
🎯 *Reconciliation Report*

📊 Summary:
- {stats.get('total_transactions', 0)} transactions analyzed
- {stats.get('total_invoices', 0)} open invoices
- {len(matches)} matches found
- {len(suggestions)} new suggestions

✅ *High Confidence Matches ({len(high_confidence)}):*
"""
        
        if high_confidence:
            for match in high_confidence[:5]:
                message += f"\n• {match['invoice_number']} - {match['company_name'][:30]}\n  ${match['transaction_amount']:.2f} | {match['confidence']}% confidence"
        else:
            message += "\nNo high-confidence matches found"
        
        if suggestions:
            message += f"\n\n💡 *New Suggestions ({len(suggestions)}):*"
            for s in suggestions[:3]:
                message += f"\n• {s['transaction_name'][:25]} → {s['company_name'][:25]}"
        
        dashboard_url = os.getenv("DASHBOARD_URL", "https://klaus-production.up.railway.app")
        message += f"\n\n👉 Review in dashboard: {dashboard_url}"

        self.twilio_client.messages.create(
            from_=self.twilio_whatsapp_from,
            body=message,
            to=self.twilio_whatsapp_to
        )

    def send_klaus_report(
        self,
        emails_sent: int,
        pending_approvals: int,
        emails_processed: int,
        emails_responded: int,
        needs_review: int,
        via_email: bool = True,
        via_sms: bool = True
    ) -> Dict:
        """Send Klaus collections activity report via Email and SMS"""

        results = {
            "email": {"sent": False, "error": None},
            "sms": {"sent": False, "error": None}
        }

        dashboard_url = os.getenv("DASHBOARD_URL", "https://klaus-production.up.railway.app")

        # Send Email Report
        if via_email and self.notification_email:
            try:
                html = f"""
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; }}
                        .header {{ background: #6366f1; color: white; padding: 20px; border-radius: 12px; }}
                        .section {{ background: #f8fafc; padding: 15px; margin: 15px 0; border-radius: 12px; }}
                        .alert {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 15px 0; }}
                    </style>
                </head>
                <body>
                    <div class="header">
                        <h1>📧 Klaus Collections Report</h1>
                    </div>

                    <div class="section">
                        <h2>📤 Outgoing Reminders</h2>
                        <p><strong>{emails_sent}</strong> reminder emails sent</p>
                        <p><strong>{pending_approvals}</strong> emails pending your approval</p>
                    </div>

                    <div class="section">
                        <h2>📥 Incoming Email Processing</h2>
                        <p><strong>{emails_processed}</strong> emails processed</p>
                        <p><strong>{emails_responded}</strong> auto-responded</p>
                        <p><strong>{needs_review}</strong> need manual review</p>
                    </div>
                """

                if pending_approvals > 0 or needs_review > 0:
                    html += f"""
                    <div class="alert">
                        <strong>⚠️ Action Required:</strong> {pending_approvals + needs_review} items need your attention
                    </div>
                    """

                html += f"""
                    <div style="margin-top: 20px;">
                        <a href="{dashboard_url}" style="background: #6366f1; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px;">Review in Dashboard</a>
                    </div>
                </body>
                </html>
                """

                subject = f"Klaus Report: {emails_sent} sent, {pending_approvals + needs_review} need attention"

                if self.gmail_client:
                    result = self.gmail_client.send_email(
                        to_email=self.notification_email,
                        to_name="Daniel",
                        subject=subject,
                        body=html
                    )
                    if result.get('status') == 'success':
                        results["email"]["sent"] = True
                    else:
                        results["email"]["error"] = result.get('error')
                elif self.smtp_user and self.smtp_password:
                    msg = MIMEMultipart('alternative')
                    msg['Subject'] = subject
                    msg['From'] = self.smtp_user
                    msg['To'] = self.notification_email
                    msg.attach(MIMEText(html, 'html'))

                    with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                        server.starttls()
                        server.login(self.smtp_user, self.smtp_password)
                        server.send_message(msg)
                    results["email"]["sent"] = True
                else:
                    results["email"]["error"] = "No email client configured"

            except Exception as e:
                results["email"]["error"] = str(e)

        # Send SMS Report
        if via_sms and self.twilio_client:
            try:
                # Get SMS number (strip 'whatsapp:' prefix if present)
                sms_to = os.getenv("TWILIO_SMS_TO") or os.getenv("TWILIO_WHATSAPP_TO", "")
                if sms_to.startswith("whatsapp:"):
                    sms_to = sms_to.replace("whatsapp:", "")

                sms_from = os.getenv("TWILIO_SMS_FROM") or os.getenv("TWILIO_PHONE_NUMBER")

                if not sms_from or not sms_to:
                    results["sms"]["error"] = "SMS numbers not configured"
                else:
                    message = f"""Klaus Report:
📤 {emails_sent} reminders sent
⏳ {pending_approvals} pending approval
📥 {emails_processed} emails processed
✅ {emails_responded} auto-responded
👀 {needs_review} need review

{dashboard_url}"""

                    self.twilio_client.messages.create(
                        from_=sms_from,
                        body=message,
                        to=sms_to
                    )
                    results["sms"]["sent"] = True

            except Exception as e:
                results["sms"]["error"] = str(e)

        return results