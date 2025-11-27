"""
Klaus Email Tester
Preview all email outputs before launching

Run with: python klaus_email_tester.py

This will:
1. Connect to HubSpot and pull real overdue invoices
2. Run them through Klaus's analysis engine
3. Generate email previews (HTML files + console output)
4. NOT send anything

Output:
- email_previews/ folder with HTML files for each email
- Console summary of what would be sent
"""

import os
import sys
import json
import re
from datetime import datetime
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from klaus_engine import KlausEngine


class InvoiceHyperlinker:
    """
    Utility class to convert invoice numbers in text to clickable HubSpot links
    (Standalone version for testing - doesn't require Google packages)
    """
    
    @staticmethod
    def hyperlink_invoices(text: str, invoice_map: dict) -> str:
        """Convert plain text to HTML with invoice numbers as hyperlinks"""
        
        # Convert text to HTML-safe
        html = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        html = html.replace('\n', '<br>\n')
        
        # Find and replace invoice numbers with hyperlinks
        # IMPORTANT: Use negative lookbehind to avoid matching inside URLs
        # Don't match if preceded by / or = (which indicates URL context)
        for invoice_number, url in invoice_map.items():
            if not url:
                continue
            
            # Patterns with negative lookbehind to avoid URL context
            # (?<![/=]) means "not preceded by / or ="
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
    def create_html_email(plain_text: str, invoice_map: dict) -> str:
        """Create a full HTML email from plain text with hyperlinked invoices"""
        
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


class KlausEmailTester:
    """Test Klaus email outputs without sending"""
    
    def __init__(self, config_path: str = "klaus_config.json"):
        self.engine = KlausEngine(config_path=config_path)
        self.preview_dir = "email_previews"
        os.makedirs(self.preview_dir, exist_ok=True)
        
    def get_mock_invoices(self) -> list:
        """
        Generate mock invoices for testing without HubSpot connection.
        Useful for testing email templates.
        """
        return [
            {
                'id': 'INV-1001',
                'hs_invoice_number': '1001',
                'company_name': 'Acme Properties LLC',
                'contact_name': 'John Smith',
                'contact_email': 'john@acmeproperties.com',
                'amount': 15000.00,
                'balance_due': 15000.00,
                'due_date': (datetime.now() - timedelta(days=10)).isoformat(),
                'hubspot_url': 'https://app.hubspot.com/contacts/44968885/record/0-52/INV-1001'
            },
            {
                'id': 'INV-1002',
                'hs_invoice_number': '1002',
                'company_name': 'Acme Properties LLC',  # Same company, different invoice
                'contact_name': 'John Smith',
                'contact_email': 'john@acmeproperties.com',
                'amount': 8500.00,
                'balance_due': 8500.00,
                'due_date': (datetime.now() - timedelta(days=14)).isoformat(),
                'hubspot_url': 'https://app.hubspot.com/contacts/44968885/record/0-52/INV-1002'
            },
            {
                'id': 'INV-1003',
                'hs_invoice_number': '1003',
                'company_name': 'Terra West Investments',  # VIP client
                'contact_name': 'Maria Garcia',
                'contact_email': 'maria@terrawest.com',
                'amount': 45000.00,
                'balance_due': 45000.00,
                'due_date': (datetime.now() - timedelta(days=21)).isoformat(),
                'hubspot_url': 'https://app.hubspot.com/contacts/44968885/record/0-52/INV-1003'
            },
            {
                'id': 'INV-1004',
                'hs_invoice_number': '1004',
                'company_name': 'Vive Apartments',  # Problem account
                'contact_name': 'Robert Chen',
                'contact_email': 'robert@viveapts.com',
                'amount': 12000.00,
                'balance_due': 12000.00,
                'due_date': (datetime.now() - timedelta(days=35)).isoformat(),
                'hubspot_url': 'https://app.hubspot.com/contacts/44968885/record/0-52/INV-1004'
            },
            {
                'id': 'INV-1005',
                'hs_invoice_number': '1005',
                'company_name': 'Sunset Heights Partners',
                'contact_name': 'Sarah Johnson',
                'contact_email': 'sarah@sunsetheights.com',
                'amount': 95000.00,  # High value - requires approval
                'balance_due': 95000.00,
                'due_date': (datetime.now() - timedelta(days=7)).isoformat(),
                'hubspot_url': 'https://app.hubspot.com/contacts/44968885/record/0-52/INV-1005'
            },
            {
                'id': 'INV-1006',
                'hs_invoice_number': '1006',
                'company_name': 'Harbor Group International',  # VIP
                'contact_name': 'Michael Davis',
                'contact_email': 'mdavis@harborgroup.com',
                'amount': 67000.00,
                'balance_due': 67000.00,
                'due_date': (datetime.now() - timedelta(days=45)).isoformat(),
                'hubspot_url': 'https://app.hubspot.com/contacts/44968885/record/0-52/INV-1006'
            },
        ]
    
    async def get_real_invoices(self) -> list:
        """Get real invoices from HubSpot"""
        try:
            # Try both import paths
            try:
                from integrations.hubspot_client import HubSpotClient
            except ImportError:
                from hubspot_client import HubSpotClient
            
            hubspot = HubSpotClient(
                api_key=os.getenv("HUBSPOT_API_KEY"),
                portal_id="44968885"
            )
            
            invoices = await hubspot.get_invoices()
            print(f"✓ Fetched {len(invoices)} invoices from HubSpot")
            return invoices
            
        except Exception as e:
            print(f"✗ Could not connect to HubSpot: {e}")
            print("  Using mock invoices instead...")
            return self.get_mock_invoices()
    
    def generate_email_preview_html(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        cc: str = None,
        invoice_map: dict = None,
        metadata: dict = None
    ) -> str:
        """Generate a full HTML preview of an email"""
        
        # Convert body to HTML with invoice links
        if invoice_map:
            body_html = InvoiceHyperlinker.create_html_email(body, invoice_map)
        else:
            body_html = body.replace('\n', '<br>\n')
        
        # Metadata section
        meta_html = ""
        if metadata:
            meta_items = []
            for key, value in metadata.items():
                meta_items.append(f"<tr><td style='padding: 5px 10px; font-weight: bold;'>{key}:</td><td style='padding: 5px 10px;'>{value}</td></tr>")
            meta_html = f"""
            <div style="background: #fff3cd; border: 1px solid #ffc107; padding: 15px; margin-bottom: 20px; border-radius: 5px;">
                <h4 style="margin: 0 0 10px 0;">⚠️ Klaus Analysis Metadata</h4>
                <table style="font-size: 14px;">
                    {''.join(meta_items)}
                </table>
            </div>
            """
        
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Email Preview: {subject}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 40px auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .preview-container {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .preview-header {{
            background: #2c3e50;
            color: white;
            padding: 20px;
        }}
        .preview-header h1 {{
            margin: 0 0 10px 0;
            font-size: 18px;
        }}
        .email-meta {{
            background: #f8f9fa;
            padding: 15px 20px;
            border-bottom: 1px solid #dee2e6;
        }}
        .email-meta p {{
            margin: 5px 0;
            font-size: 14px;
        }}
        .email-meta strong {{
            display: inline-block;
            width: 80px;
        }}
        .email-body {{
            padding: 30px;
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 10px;
        }}
        .badge-autonomous {{
            background: #28a745;
            color: white;
        }}
        .badge-approval {{
            background: #ffc107;
            color: black;
        }}
        .badge-vip {{
            background: #6f42c1;
            color: white;
        }}
        a {{
            color: #0066cc;
        }}
    </style>
</head>
<body>
    <div class="preview-container">
        <div class="preview-header">
            <h1>📧 EMAIL PREVIEW - NOT SENT</h1>
            <small>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small>
        </div>
        
        {meta_html}
        
        <div class="email-meta">
            <p><strong>To:</strong> {to_name} &lt;{to_email}&gt;</p>
            <p><strong>Subject:</strong> {subject}</p>
            {f'<p><strong>CC:</strong> {cc}</p>' if cc else ''}
        </div>
        
        <div class="email-body">
            {body_html}
        </div>
    </div>
</body>
</html>
"""
    
    def save_email_preview(
        self,
        filename: str,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        cc: str = None,
        invoice_map: dict = None,
        metadata: dict = None
    ) -> str:
        """Save an email preview to HTML file"""
        
        html = self.generate_email_preview_html(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body=body,
            cc=cc,
            invoice_map=invoice_map,
            metadata=metadata
        )
        
        filepath = os.path.join(self.preview_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        
        return filepath
    
    def run_test(self, invoices: list, use_mock: bool = False) -> dict:
        """
        Run full Klaus analysis and generate email previews
        
        Args:
            invoices: List of invoice dicts
            use_mock: If True, uses mock data regardless
        
        Returns:
            Summary of all generated previews
        """
        
        print("\n" + "="*60)
        print("🤖 KLAUS EMAIL TESTER")
        print("="*60)
        print(f"Testing with {len(invoices)} invoices\n")
        
        # Run Klaus analysis
        analysis = self.engine.analyze_overdue_invoices(invoices)
        
        results = {
            'autonomous_emails': [],
            'approval_required': [],
            'no_action': analysis['no_action_count'],
            'total_invoices': len(invoices),
            'preview_files': []
        }
        
        # Process autonomous emails
        print("\n📤 AUTONOMOUS EMAILS (would send automatically):")
        print("-" * 50)
        
        for i, action in enumerate(analysis['autonomous_emails'], 1):
            contact_name = action['contact_name']
            contact_email = action['contact_email']
            companies = ', '.join(action['companies'])
            invoice_count = action['invoice_count']
            total = action['total_balance']
            escalation = action['escalation_level']
            
            # Extract subject and body from recommended message
            message = action['recommended_message']
            subject_line = ""
            body = message
            
            if message.startswith("Subject:"):
                parts = message.split('\n\n', 1)
                subject_line = parts[0].replace('Subject:', '').strip()
                body = parts[1] if len(parts) > 1 else message
            
            # Build invoice map for hyperlinking
            invoice_map = {}
            for inv in action['invoices']:
                inv_num = inv.get('invoice_number', str(inv.get('invoice_id', '')))
                hubspot_url = inv.get('hubspot_url', f"https://app.hubspot.com/contacts/44968885/record/0-52/{inv.get('invoice_id', '')}")
                invoice_map[inv_num] = hubspot_url
            
            # Determine CC
            cc = None
            if action.get('is_vip'):
                cc = self.engine.config.get('communication_preferences', {}).get('cc_email', 'daniel@leveragelivelocal.com')
            
            # Metadata for preview
            metadata = {
                'Contact': f"{contact_name} ({contact_email})",
                'Companies': companies,
                'Invoice Count': invoice_count,
                'Total Balance': f"${total:,.2f}",
                'Days Overdue': f"{action['oldest_days_overdue']} days (oldest)",
                'Escalation Level': f"{escalation}/5",
                'VIP Client': '✓ Yes' if action.get('is_vip') else 'No',
                'Status': '✅ AUTONOMOUS - Would send without approval'
            }
            
            # Save preview
            safe_name = contact_name.replace(' ', '_').replace('/', '_')[:30]
            filename = f"{i:02d}_autonomous_{safe_name}.html"
            filepath = self.save_email_preview(
                filename=filename,
                to_email=contact_email,
                to_name=contact_name,
                subject=subject_line,
                body=body,
                cc=cc,
                invoice_map=invoice_map,
                metadata=metadata
            )
            
            results['autonomous_emails'].append({
                'contact': contact_name,
                'email': contact_email,
                'companies': action['companies'],
                'invoices': invoice_count,
                'total': total,
                'preview_file': filename
            })
            results['preview_files'].append(filepath)
            
            print(f"\n  {i}. {contact_name} <{contact_email}>")
            print(f"     Companies: {companies}")
            print(f"     Invoices: {invoice_count} | Total: ${total:,.2f}")
            print(f"     Escalation: Level {escalation} | {action['oldest_days_overdue']} days overdue")
            print(f"     → Preview: {filename}")
        
        if not analysis['autonomous_emails']:
            print("  (none)")
        
        # Process approval-required emails
        print("\n\n⏳ REQUIRES APPROVAL (would NOT send automatically):")
        print("-" * 50)
        
        for i, action in enumerate(analysis['pending_approvals'], 1):
            contact_name = action['contact_name']
            contact_email = action['contact_email']
            companies = ', '.join(action['companies'])
            invoice_count = action['invoice_count']
            total = action['total_balance']
            escalation = action['escalation_level']
            
            # Extract subject and body
            message = action['recommended_message']
            subject_line = ""
            body = message
            
            if message.startswith("Subject:"):
                parts = message.split('\n\n', 1)
                subject_line = parts[0].replace('Subject:', '').strip()
                body = parts[1] if len(parts) > 1 else message
            
            # Build invoice map
            invoice_map = {}
            for inv in action['invoices']:
                inv_num = inv.get('invoice_number', str(inv.get('invoice_id', '')))
                hubspot_url = inv.get('hubspot_url', f"https://app.hubspot.com/contacts/44968885/record/0-52/{inv.get('invoice_id', '')}")
                invoice_map[inv_num] = hubspot_url
            
            # Determine why approval is needed
            approval_reasons = []
            if total >= self.engine.config.get('approval_thresholds', {}).get('email_requires_approval_above_amount', 100000):
                approval_reasons.append(f"High value (>${total:,.0f})")
            if escalation >= 4:
                approval_reasons.append(f"High escalation (Level {escalation})")
            if action.get('is_vip'):
                approval_reasons.append("VIP client")
            if not approval_reasons:
                approval_reasons.append("Policy requires approval")
            
            # Metadata
            metadata = {
                'Contact': f"{contact_name} ({contact_email})",
                'Companies': companies,
                'Invoice Count': invoice_count,
                'Total Balance': f"${total:,.2f}",
                'Days Overdue': f"{action['oldest_days_overdue']} days (oldest)",
                'Escalation Level': f"{escalation}/5",
                'VIP Client': '✓ Yes' if action.get('is_vip') else 'No',
                'Status': '⚠️ REQUIRES APPROVAL',
                'Approval Reason': ', '.join(approval_reasons)
            }
            
            # Save preview
            safe_name = contact_name.replace(' ', '_').replace('/', '_')[:30]
            filename = f"{i:02d}_approval_{safe_name}.html"
            filepath = self.save_email_preview(
                filename=filename,
                to_email=contact_email,
                to_name=contact_name,
                subject=subject_line,
                body=body,
                cc=self.engine.config.get('communication_preferences', {}).get('cc_email'),
                invoice_map=invoice_map,
                metadata=metadata
            )
            
            results['approval_required'].append({
                'contact': contact_name,
                'email': contact_email,
                'companies': action['companies'],
                'invoices': invoice_count,
                'total': total,
                'reason': ', '.join(approval_reasons),
                'preview_file': filename
            })
            results['preview_files'].append(filepath)
            
            print(f"\n  {i}. {contact_name} <{contact_email}>")
            print(f"     Companies: {companies}")
            print(f"     Invoices: {invoice_count} | Total: ${total:,.2f}")
            print(f"     Escalation: Level {escalation} | {action['oldest_days_overdue']} days overdue")
            print(f"     ⚠️  Reason: {', '.join(approval_reasons)}")
            print(f"     → Preview: {filename}")
        
        if not analysis['pending_approvals']:
            print("  (none)")
        
        # Summary
        print("\n\n" + "="*60)
        print("📊 SUMMARY")
        print("="*60)
        print(f"Total invoices analyzed:     {len(invoices)}")
        print(f"Contacts to email:           {len(analysis['autonomous_emails']) + len(analysis['pending_approvals'])}")
        print(f"  → Autonomous (auto-send):  {len(analysis['autonomous_emails'])}")
        print(f"  → Needs approval:          {len(analysis['pending_approvals'])}")
        print(f"No action needed:            {analysis['no_action_count']}")
        print(f"\n📁 Preview files saved to:   ./{self.preview_dir}/")
        print("="*60)
        
        # Save summary JSON
        summary_path = os.path.join(self.preview_dir, '_summary.json')
        with open(summary_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n📋 Summary JSON: {summary_path}")
        
        return results


# Import for mock data
from datetime import timedelta


async def main():
    """Main test runner"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Klaus email outputs')
    parser.add_argument('--mock', action='store_true', help='Use mock data instead of HubSpot')
    parser.add_argument('--config', default='klaus_config.json', help='Path to Klaus config')
    args = parser.parse_args()
    
    tester = KlausEmailTester(config_path=args.config)
    
    if args.mock:
        print("Using mock invoice data...")
        invoices = tester.get_mock_invoices()
    else:
        print("Fetching real invoices from HubSpot...")
        invoices = await tester.get_real_invoices()
    
    results = tester.run_test(invoices)
    
    print("\n✅ Test complete! Open the HTML files in your browser to review emails.\n")
    
    # List files
    print("Generated previews:")
    for f in sorted(os.listdir(tester.preview_dir)):
        if f.endswith('.html'):
            print(f"  → file://{os.path.abspath(os.path.join(tester.preview_dir, f))}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
