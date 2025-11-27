"""
Klaus Collections Engine
Autonomous collections agent that manages accounts receivable
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import os
from collections import defaultdict


class KlausEngine:
    """
    Klaus - Autonomous Collections Agent
    
    Determines when to contact clients about unpaid invoices,
    manages escalation paths, and tracks all communications.
    
    CONSOLIDATES INVOICES BY COMPANY - sends one email per company
    """
    
    def __init__(self, config_path: str = "klaus_config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self.communication_history = []
        self._load_history()
        
        # Autonomy thresholds
        self.high_value_threshold = self.config.get('high_value_threshold', 5000)
        self.auto_approval_enabled = self.config.get('auto_approval_enabled', True)
        
        # Timing rules
        self.days_until_first_reminder = self.config.get('days_until_first_reminder', 7)
        self.days_between_reminders = self.config.get('days_between_reminders', 7)
        self.max_autonomous_reminders = self.config.get('max_autonomous_reminders', 3)
    
    def _load_config(self) -> Dict:
        """Load Klaus configuration"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        # Default configuration
        return {
            'high_value_threshold': 5000,
            'auto_approval_enabled': True,
            'days_until_first_reminder': 7,
            'days_between_reminders': 7,
            'max_autonomous_reminders': 3,
            'escalation_days': [7, 14, 21, 30, 45, 60],
            'klaus_persona': {
                'name': 'Klaus',
                'company': 'Leverage Live Local',
                'tone': 'professional_friendly',
                'email_signature': 'Klaus\nAccounts Receivable Specialist\nLeverage Live Local\n\nPhone: 305-209-7218\nEmail: klaus@leveragelivelocal.com'
            },
            'blacklisted_contacts': [],
            'vip_contacts': []
        }
    
    def save_config(self):
        """Save current configuration"""
        with open(self.config_path, 'w') as f:
            json.dump(self.config, indent=2, fp=f)
    
    def _extract_invoice_number(self, invoice: Dict) -> str:
        """
        Extract the actual 4-digit invoice number from HubSpot invoice
        Tries multiple fields in priority order
        """
        # Try common HubSpot invoice number fields
        invoice_number = (
            invoice.get('hs_invoice_number') or
            invoice.get('hs_number') or
            invoice.get('invoice_number') or
            invoice.get('number') or
            invoice.get('id')  # Fallback to ID if nothing else
        )
        
        # If it's still the long HubSpot ID, try to extract a shorter number
        if invoice_number and len(str(invoice_number)) > 6:
            # Look for a shorter number in properties
            for key in ['hs_invoice_number', 'hs_number', 'properties.hs_invoice_number']:
                val = invoice.get(key)
                if val and len(str(val)) <= 6:
                    return str(val)
        
        return str(invoice_number) if invoice_number else "Unknown"
    
    def _extract_contact_name(self, invoice: Dict) -> str:
        """Extract contact person's name from invoice"""
        # Try various HubSpot fields for contact name
        name = (
            invoice.get('contact_name') or
            invoice.get('recipient_name') or
            invoice.get('hs_contact_name') or
            invoice.get('to_name') or
            # Try combining first/last name
            self._combine_name(
                invoice.get('hs_contact_firstname'),
                invoice.get('hs_contact_lastname')
            ) or
            invoice.get('company_name', 'Unknown')  # Fallback to company
        )
        return str(name).strip()
    
    def _extract_contact_email(self, invoice: Dict) -> str:
        """Extract contact person's email from invoice"""
        # Try various HubSpot fields for email
        email = (
            invoice.get('contact_email') or
            invoice.get('recipient_email') or
            invoice.get('hs_contact_email') or
            invoice.get('to_email') or
            invoice.get('email') or
            'unknown'
        )
        return str(email).strip().lower()
    
    def _combine_name(self, first: Optional[str], last: Optional[str]) -> Optional[str]:
        """Combine first and last name"""
        if first and last:
            return f"{first} {last}"
        elif first:
            return first
        elif last:
            return last
        return None
    
    def _extract_first_name(self, full_name: str) -> str:
        """Extract first name from full name"""
        if not full_name or full_name == 'Unknown':
            return ''
        
        # Handle company names (don't try to extract first name)
        if any(suffix in full_name.upper() for suffix in ['LLC', 'INC', 'CORP', 'LTD', 'LP']):
            return ''
        
        # Split and get first word
        parts = full_name.strip().split()
        if parts:
            return parts[0]
        return ''
    
    def analyze_invoice(self, invoice: Dict) -> Dict:
        """
        Analyze an unpaid invoice and determine action needed
        
        Returns:
        {
            'invoice_id': str (HubSpot ID),
            'invoice_number': str (4-digit invoice number),
            'company_name': str,
            'contact_name': str (person's name),
            'contact_email': str (person's email),
            'amount': float,
            'balance_due': float,
            'days_overdue': int,
            'due_date': str,
            'action_required': 'email' | 'call' | 'escalate' | 'none',
            'urgency': 'low' | 'medium' | 'high' | 'critical',
            'requires_approval': bool,
            'escalation_level': int (0-5),
            'previous_contacts': list of contact dates
        }
        """
        
        # Get HubSpot ID and actual invoice number
        invoice_id = invoice.get('id')
        invoice_number = self._extract_invoice_number(invoice)
        
        # Get balance due (the actual amount owed)
        balance_due = float(invoice.get('balance_due', 0))
        
        # Get other fields
        due_date = invoice.get('due_date')
        company_name = invoice.get('company_name', 'Unknown')
        
        # Extract contact information
        contact_name = self._extract_contact_name(invoice)
        contact_email = self._extract_contact_email(invoice)
        
        # Calculate days overdue
        if due_date:
            try:
                due_dt = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                days_overdue = (datetime.now() - due_dt.replace(tzinfo=None)).days
            except:
                days_overdue = 0
        else:
            days_overdue = 0
        
        # Check communication history for THIS invoice
        previous_contacts = self._get_contact_history(invoice_id)
        contact_count = len(previous_contacts)
        last_contact = previous_contacts[-1] if previous_contacts else None
        
        # Determine if action is needed
        action_required = 'none'
        urgency = 'low'
        escalation_level = 0
        requires_approval = False
        
        # First reminder (autonomous)
        if days_overdue >= self.days_until_first_reminder and contact_count == 0:
            action_required = 'email'
            urgency = 'low'
            escalation_level = 1
        
        # Follow-up reminders
        elif contact_count > 0 and last_contact:
            days_since_last = (datetime.now() - datetime.fromisoformat(last_contact['sent_at'])).days
            
            if days_since_last >= self.days_between_reminders:
                if contact_count < self.max_autonomous_reminders:
                    action_required = 'email'
                    urgency = 'medium'
                    escalation_level = contact_count + 1
                else:
                    # Beyond autonomous limit
                    if balance_due >= self.high_value_threshold:
                        action_required = 'call'
                        urgency = 'high'
                        requires_approval = True
                    else:
                        action_required = 'escalate'
                        urgency = 'high'
                        requires_approval = True
                    escalation_level = 4
        
        # Critical overdue
        if days_overdue >= 60:
            action_required = 'escalate'
            urgency = 'critical'
            escalation_level = 5
            requires_approval = True
        
        # High-value invoices require approval for calls
        if balance_due >= self.high_value_threshold and action_required == 'call':
            requires_approval = True
        
        # Check if contact is blacklisted or VIP
        if company_name in self.config.get('blacklisted_contacts', []):
            action_required = 'none'
            requires_approval = True
        
        if company_name in self.config.get('vip_contacts', []):
            requires_approval = True
        
        return {
            'invoice_id': invoice_id,
            'invoice_number': invoice_number,
            'company_name': company_name,
            'contact_name': contact_name,
            'contact_email': contact_email,
            'amount': balance_due,
            'balance_due': balance_due,
            'days_overdue': days_overdue,
            'due_date': due_date,
            'action_required': action_required,
            'urgency': urgency,
            'requires_approval': requires_approval,
            'escalation_level': escalation_level,
            'contact_count': contact_count,
            'last_contact_date': last_contact['sent_at'] if last_contact else None,
            'previous_contacts': [c['sent_at'] for c in previous_contacts]
        }
    
    def _get_contact_history(self, invoice_id: str) -> List[Dict]:
        """Get all previous contacts for this invoice"""
        return [c for c in self.communication_history if c['invoice_id'] == invoice_id]
    
    def _get_company_contact_history(self, company_name: str) -> List[Dict]:
        """Get all previous contacts for any invoice from this company"""
        return [c for c in self.communication_history if c['company_name'] == company_name]
    
    def _format_contact_history(self, previous_contacts: List[Dict]) -> str:
        """Format previous contact attempts for inclusion in messages"""
        if not previous_contacts:
            return ""
        
        # Sort by date, most recent first
        sorted_contacts = sorted(
            previous_contacts, 
            key=lambda x: x['sent_at'], 
            reverse=True
        )
        
        contact_lines = []
        for i, contact in enumerate(sorted_contacts[:5], 1):  # Show up to 5 most recent
            try:
                date = datetime.fromisoformat(contact['sent_at']).strftime('%B %d, %Y')
                contact_lines.append(f"  {i}. {date}")
            except:
                contact_lines.append(f"  {i}. Previous contact")
        
        return "\n".join(contact_lines)
    
    def _generate_consolidated_message(
        self,
        contact_name: str,
        companies: List[str],
        invoices: List[Dict],
        escalation_level: int,
        all_company_contacts: List[Dict],
        is_vip: bool = False
    ) -> str:
        """
        Generate a consolidated message for multiple invoices from same contact person
        
        Args:
            contact_name: Contact person's name
            companies: List of company names (may be multiple)
            invoices: List of invoice analysis dicts
            escalation_level: Highest escalation level among all invoices
            all_company_contacts: All previous contacts with this person
            is_vip: Whether this is a VIP contact
        """
        
        persona = self.config.get('klaus_persona', {})
        signature = persona.get('email_signature', 'Klaus\nAccounts Receivable Specialist\nLeverage Live Local')
        
        # Extract first name for greeting
        first_name = self._extract_first_name(contact_name)
        greeting = f"Hi {first_name}," if first_name else "Hi,"
        
        # Calculate totals
        total_balance = sum(inv['balance_due'] for inv in invoices)
        oldest_days = max(inv['days_overdue'] for inv in invoices)
        invoice_count = len(invoices)
        
        # Sort invoices by days overdue (oldest first)
        sorted_invoices = sorted(invoices, key=lambda x: x['days_overdue'], reverse=True)
        
        # Create invoice table
        invoice_lines = []
        for inv in sorted_invoices:
            due_date_str = ""
            if inv.get('due_date'):
                try:
                    due_dt = datetime.fromisoformat(inv['due_date'].replace('Z', '+00:00'))
                    due_date_str = due_dt.strftime('%m/%d/%Y')
                except:
                    due_date_str = "Unknown"
            
            # Include company name if multiple companies
            company_str = f" | {inv['company_name'][:25]}" if len(companies) > 1 else ""
            
            invoice_lines.append(
                f"  Invoice {inv['invoice_number']:>6} | "
                f"Due: {due_date_str:>10} | "
                f"{inv['days_overdue']:>3} days overdue | "
                f"${inv['balance_due']:>10,.2f}"
                f"{company_str}"
            )
        
        invoice_table = "\n".join(invoice_lines)
        
        # Format contact history
        contact_history = self._format_contact_history(all_company_contacts)
        
        # Use VIP-friendly messages or standard messages
        if is_vip:
            return self._generate_vip_message(
                greeting=greeting,
                companies=companies,
                invoice_count=invoice_count,
                invoice_table=invoice_table,
                total_balance=total_balance,
                oldest_days=oldest_days,
                escalation_level=escalation_level,
                contact_history=contact_history,
                signature=signature
            )
        else:
            return self._generate_standard_message(
                greeting=greeting,
                companies=companies,
                invoice_count=invoice_count,
                invoice_table=invoice_table,
                total_balance=total_balance,
                oldest_days=oldest_days,
                escalation_level=escalation_level,
                contact_history=contact_history,
                signature=signature
            )
        
        # Level 1: Friendly first reminder (7-14 days)
        if escalation_level == 1:
            plural = "invoices" if invoice_count > 1 else "invoice"
            
            # Check if this is truly first contact
            has_history = len(all_company_contacts) > 0
            
            if has_history:
                intro = f"I wanted to follow up regarding {invoice_count} outstanding {plural} with a total balance of ${total_balance:,.2f}."
            else:
                intro = f"I hope this message finds you well. I'm reaching out regarding {invoice_count} outstanding {plural} with a total balance of ${total_balance:,.2f}."
            
            return f"""Subject: Payment Reminder - {invoice_count} Outstanding {plural.title()}

Hi,

{intro}

Outstanding Invoices:
{invoice_table}

Total Amount Due: ${total_balance:,.2f}

We haven't received payment yet and wanted to check if there's anything preventing payment from being processed. If you need any documentation (W-9, certificate of insurance, etc.), I'm happy to provide those right away.

Please let me know if you have any questions or if there's anything I can help with.

Best regards,
{signature}"""
        
        # Level 2: Follow-up reminder (14-21 days)
        elif escalation_level == 2:
            plural = "invoices" if invoice_count > 1 else "invoice"
            
            # Check if we've contacted before
            has_history = len(all_company_contacts) > 0
            
            if has_history:
                followup = "We sent a reminder last week but haven't heard back. I want to make sure everything is in order on your end."
            else:
                followup = "I want to make sure everything is in order on your end and that you received these invoices."
            
            return f"""Subject: Follow-up - {invoice_count} Outstanding {plural.title()}

Hi,

I wanted to follow up on the following outstanding {plural}:

{invoice_table}

Total Amount Due: ${total_balance:,.2f}

{followup}

Is there anything blocking payment? I'm here to help resolve any issues.

Best regards,
{signature}"""
        
        # Level 3: Firmer reminder (21-30 days)
        elif escalation_level == 3:
            plural = "invoices" if invoice_count > 1 else "invoice"
            
            # Only show history section if there IS history
            history_section = ""
            if contact_history:
                history_section = f"""
Previous contact attempts:
{contact_history}

"""
                contact_language = "We've reached out multiple times but haven't received payment or a response."
            else:
                contact_language = "These invoices are significantly overdue and we haven't received payment or a response."
            
            return f"""Subject: Important - {invoice_count} Overdue {plural.title()} Require Attention

Hi,

I'm writing regarding {invoice_count} overdue {plural}, with the oldest now {oldest_days} days past due:

{invoice_table}

Total Amount Due: ${total_balance:,.2f}
{history_section}{contact_language} I'd like to resolve this quickly to avoid any impact on our continued service.

Could you please provide an update on when we can expect payment, or let me know if there's a specific issue preventing payment?

I'm available to discuss this directly at 305-209-7218 if that would be helpful.

Best regards,
{signature}"""
        
        # Level 4: Escalation warning (30-60 days)
        elif escalation_level == 4:
            plural = "invoices" if invoice_count > 1 else "invoice"
            
            # Only show history section if there IS history
            history_section = ""
            if contact_history:
                history_section = f"""
Previous contact attempts:
{contact_history}

"""
                urgency_language = "Despite multiple reminders, the following"
            else:
                urgency_language = "The following"
            
            return f"""Subject: URGENT - {invoice_count} Overdue {plural.title()} Require Immediate Attention

Hi,

{urgency_language} {plural} remain unpaid:

{invoice_table}

Total Amount Due: ${total_balance:,.2f}
Oldest Invoice: {oldest_days} days overdue
{history_section}This is significantly overdue and requires immediate attention. If we don't receive payment or establish a payment plan within 7 days, we will need to suspend services.

Please contact me immediately at 305-209-7218 to resolve this matter.

Best regards,
{signature}"""
        
        # Level 5: Final notice (60+ days)
        else:
            plural = "invoices" if invoice_count > 1 else "invoice"
            
            # Only show history section if there IS history
            history_section = ""
            if contact_history:
                history_section = f"""
Previous contact attempts:
{contact_history}

"""
                attempts_language = "Despite our repeated attempts to reach you, these"
            else:
                attempts_language = "These"
            
            return f"""Subject: FINAL NOTICE - {invoice_count} Severely Overdue {plural.title()}

Hi,

This is a final notice regarding the following severely overdue {plural}:

{invoice_table}

Total Amount Due: ${total_balance:,.2f}
Oldest Invoice: {oldest_days} days overdue
{history_section}{attempts_language} invoices remain unpaid. This requires immediate resolution.

Without payment or a commitment to a payment plan within 48 hours, we will be forced to suspend all services.

Please contact me immediately at 305-209-7218 or reply to this email to avoid service interruption.

Best regards,
{signature}"""
    
    
    def _generate_vip_message(
        self,
        greeting: str,
        companies: List[str],
        invoice_count: int,
        invoice_table: str,
        total_balance: float,
        oldest_days: int,
        escalation_level: int,
        contact_history: str,
        signature: str
    ) -> str:
        """Generate VIP-friendly message (no threats, professional tone)"""
        
        plural = "invoices" if invoice_count > 1 else "invoice"
        companies_str = ", ".join(companies) if len(companies) <= 3 else f"{companies[0]}, {companies[1]}, and {len(companies)-2} other properties"
        
        # VIP messages are always friendly, regardless of age
        if escalation_level <= 2:
            # Early stage - very friendly
            return f"""Subject: Outstanding Invoices - {companies[0] if len(companies) == 1 else 'Multiple Properties'}

{greeting}

I wanted to reach out regarding some outstanding {plural} across your properties. I know you're managing {companies_str}, so I've consolidated everything here for your review.

Outstanding Invoices:
{invoice_table}

Total Outstanding: ${total_balance:,.2f}

I wanted to make sure these are on your radar. If you need any documentation or have questions about any of these invoices, I'm happy to help.

Looking forward to hearing from you.

Best regards,
{signature}"""
        
        elif escalation_level <= 4:
            # Mid-stage - still friendly but more direct
            history_section = ""
            if contact_history:
                history_section = f"""
I've reached out a couple times:
{contact_history}

"""
            
            return f"""Subject: Following Up - Outstanding Invoices

{greeting}

I wanted to follow up regarding the outstanding {plural} across {companies_str}. {history_section}I know managing multiple properties keeps you busy, so I've consolidated everything in one place:

Outstanding Invoices:
{invoice_table}

Total Outstanding: ${total_balance:,.2f}
Oldest Invoice: {oldest_days} days past due

I understand cash flow timing can be challenging with multiple properties. Could we schedule a quick call to discuss payment timing? I want to make sure we're aligned and can support you however needed.

You can reach me directly at 305-209-7218.

Best regards,
{signature}"""
        
        else:
            # Final stage - direct but still respectful
            history_section = ""
            if contact_history:
                history_section = f"""
Previous contact attempts:
{contact_history}

"""
            
            return f"""Subject: Important - Outstanding Balance Requiring Attention

{greeting}

I need to bring some outstanding {plural} to your attention. {history_section}These invoices have been pending for some time:

Outstanding Invoices:
{invoice_table}

Total Outstanding: ${total_balance:,.2f}
Oldest Invoice: {oldest_days} days past due

I'd really appreciate if we could get these resolved. I understand things get busy managing multiple properties, but this balance is significantly overdue and needs attention.

Can we schedule a call this week to discuss? I'm available at your convenience and want to work with you to get this sorted out.

Please call me at 305-209-7218 or reply to this email.

Best regards,
{signature}"""
    
    def _generate_standard_message(
        self,
        greeting: str,
        companies: List[str],
        invoice_count: int,
        invoice_table: str,
        total_balance: float,
        oldest_days: int,
        escalation_level: int,
        contact_history: str,
        signature: str
    ) -> str:
        """Generate standard firm (but professional) message"""
        
        plural = "invoices" if invoice_count > 1 else "invoice"
        
        # Level 1: Friendly first reminder (7-14 days)
        if escalation_level == 1:
            # Check if this is truly first contact
            has_history = len(contact_history) > 0
            
            if has_history:
                intro = f"I wanted to follow up regarding {invoice_count} outstanding {plural} with a total balance of ${total_balance:,.2f}."
            else:
                intro = f"I hope this message finds you well. I'm reaching out regarding {invoice_count} outstanding {plural} with a total balance of ${total_balance:,.2f}."
            
            return f"""Subject: Payment Reminder - {invoice_count} Outstanding {plural.title()}

{greeting}

{intro}

Outstanding Invoices:
{invoice_table}

Total Amount Due: ${total_balance:,.2f}

We haven't received payment yet and wanted to check if there's anything preventing payment from being processed. If you need any documentation (W-9, certificate of insurance, etc.), I'm happy to provide those right away.

Please let me know if you have any questions or if there's anything I can help with.

Best regards,
{signature}"""
        
        # Level 2: Follow-up reminder (14-21 days)
        elif escalation_level == 2:
            # Check if we've contacted before
            has_history = len(contact_history) > 0
            
            if has_history:
                followup = "We sent a reminder last week but haven't heard back. I want to make sure everything is in order on your end."
            else:
                followup = "I want to make sure everything is in order on your end and that you received these invoices."
            
            return f"""Subject: Follow-up - {invoice_count} Outstanding {plural.title()}

{greeting}

I wanted to follow up on the following outstanding {plural}:

{invoice_table}

Total Amount Due: ${total_balance:,.2f}

{followup}

Is there anything blocking payment? I'm here to help resolve any issues.

Best regards,
{signature}"""
        
        # Level 3: Firmer reminder (21-30 days)
        elif escalation_level == 3:
            # Only show history section if there IS history
            history_section = ""
            if contact_history:
                history_section = f"""
Previous contact attempts:
{contact_history}

"""
                contact_language = "We've reached out multiple times but haven't received payment or a response."
            else:
                contact_language = "These invoices are significantly overdue and we haven't received payment or a response."
            
            return f"""Subject: Important - {invoice_count} Overdue {plural.title()} Require Attention

{greeting}

I'm writing regarding {invoice_count} overdue {plural}, with the oldest now {oldest_days} days past due:

{invoice_table}

Total Amount Due: ${total_balance:,.2f}
{history_section}{contact_language} I'd like to resolve this quickly to avoid any impact on our continued service.

Could you please provide an update on when we can expect payment, or let me know if there's a specific issue preventing payment?

I'm available to discuss this directly at 305-209-7218 if that would be helpful.

Best regards,
{signature}"""
        
        # Level 4: Escalation warning (30-60 days)
        elif escalation_level == 4:
            # Only show history section if there IS history
            history_section = ""
            if contact_history:
                history_section = f"""
Previous contact attempts:
{contact_history}

"""
                urgency_language = "Despite multiple reminders, the following"
            else:
                urgency_language = "The following"
            
            return f"""Subject: URGENT - {invoice_count} Overdue {plural.title()} Require Immediate Attention

{greeting}

{urgency_language} {plural} remain unpaid:

{invoice_table}

Total Amount Due: ${total_balance:,.2f}
Oldest Invoice: {oldest_days} days overdue
{history_section}This is significantly overdue and requires immediate attention. If we don't receive payment or establish a payment plan within 7 days, we will need to suspend services.

Please contact me immediately at 305-209-7218 to resolve this matter.

Best regards,
{signature}"""
        
        # Level 5: Final notice (60+ days)
        else:
            # Only show history section if there IS history
            history_section = ""
            if contact_history:
                history_section = f"""
Previous contact attempts:
{contact_history}

"""
                attempts_language = "Despite our repeated attempts to reach you, these"
            else:
                attempts_language = "These"
            
            return f"""Subject: FINAL NOTICE - {invoice_count} Severely Overdue {plural.title()}

{greeting}

This is a final notice regarding the following severely overdue {plural}:

{invoice_table}

Total Amount Due: ${total_balance:,.2f}
Oldest Invoice: {oldest_days} days overdue
{history_section}{attempts_language} invoices remain unpaid. This requires immediate resolution.

Without payment or a commitment to a payment plan within 48 hours, we will be forced to suspend all services.

Please contact me immediately at 305-209-7218 or reply to this email to avoid service interruption.

Best regards,
{signature}"""
    
    def log_communication(
        self,
        invoice_id: str,
        company_name: str,
        method: str,
        message_type: str,
        approved_by: Optional[str] = None
    ):
        """Log a communication attempt"""
        self.communication_history.append({
            'invoice_id': invoice_id,
            'company_name': company_name,
            'method': method,
            'message_type': message_type,
            'sent_at': datetime.now().isoformat(),
            'approved_by': approved_by
        })
        
        # Save to file
        self._save_history()
    
    def _save_history(self):
        """Save communication history"""
        with open('klaus_communication_history.json', 'w') as f:
            json.dump(self.communication_history, indent=2, fp=f)
    
    def _load_history(self):
        """Load communication history"""
        if os.path.exists('klaus_communication_history.json'):
            try:
                with open('klaus_communication_history.json', 'r') as f:
                    self.communication_history = json.load(f)
            except:
                self.communication_history = []
    
    def get_pending_approvals(self) -> List[Dict]:
        """Get all actions that require approval"""
        # This will be populated by analyze_overdue_invoices
        return getattr(self, '_pending_approvals', [])
    
    def analyze_overdue_invoices(self, invoices: List[Dict]) -> Dict:
        """
        Analyze all unpaid invoices and determine actions
        
        CONSOLIDATES INVOICES BY CONTACT PERSON (not company)
        Multiple companies with same accounting contact = one email
        
        Returns summary of:
        - Autonomous actions (can be taken without approval)
        - Pending approvals (require human review)
        - No action needed
        """
        
        # First, analyze each invoice individually
        all_analyses = []
        for invoice in invoices:
            analysis = self.analyze_invoice(invoice)
            all_analyses.append(analysis)
        
        # Group invoices by CONTACT PERSON (not company)
        by_contact = defaultdict(list)
        for analysis in all_analyses:
            if analysis['action_required'] != 'none':
                # Get contact email as unique identifier
                contact_email = analysis.get('contact_email', 'unknown')
                contact_name = analysis.get('contact_name', analysis['company_name'])
                
                # Use email as key (unique per person)
                # Fall back to company name if no email
                key = contact_email if contact_email != 'unknown' else analysis['company_name']
                
                by_contact[key].append(analysis)
        
        # Now create consolidated actions per contact person
        autonomous_emails = []
        autonomous_calls = []
        pending_approvals = []
        no_action = []
        
        for contact_key, contact_invoices in by_contact.items():
            # Determine highest escalation level for this contact
            max_escalation = max(inv['escalation_level'] for inv in contact_invoices)
            requires_approval = any(inv['requires_approval'] for inv in contact_invoices)
            total_balance = sum(inv['balance_due'] for inv in contact_invoices)
            
            # Get contact info from first invoice (all same person)
            first_invoice = contact_invoices[0]
            contact_name = first_invoice.get('contact_name', first_invoice['company_name'])
            contact_email = first_invoice.get('contact_email', 'unknown')
            
            # Check if this is a VIP contact (check all companies)
            # Use substring matching - e.g., "Terra" matches "TERRA WEST MF INVESTMENTS LLC"
            vip_keywords = self.config.get('vip_contacts', [])
            is_vip = any(
                any(
                    vip_keyword.upper() in inv['company_name'].upper()
                    for vip_keyword in vip_keywords
                )
                for inv in contact_invoices
            )
            
            # Get all contact history for this person (across all their companies)
            all_contact_history = []
            for inv in contact_invoices:
                all_contact_history.extend(self._get_contact_history(inv['invoice_id']))
            
            # Deduplicate contact history by date
            unique_contacts = {}
            for contact in all_contact_history:
                unique_contacts[contact['sent_at']] = contact
            company_contacts = list(unique_contacts.values())
            
            # Generate consolidated message
            consolidated_message = self._generate_consolidated_message(
                contact_name=contact_name,
                companies=list(set(inv['company_name'] for inv in contact_invoices)),
                invoices=contact_invoices,
                escalation_level=max_escalation,
                all_company_contacts=company_contacts,
                is_vip=is_vip
            )
            
            # Create consolidated action
            action = {
                'contact_name': contact_name,
                'contact_email': contact_email,
                'companies': list(set(inv['company_name'] for inv in contact_invoices)),
                'invoice_count': len(contact_invoices),
                'invoices': contact_invoices,
                'total_balance': total_balance,
                'oldest_days_overdue': max(inv['days_overdue'] for inv in contact_invoices),
                'escalation_level': max_escalation,
                'requires_approval': requires_approval,
                'is_vip': is_vip,
                'recommended_message': consolidated_message,
                'action_required': 'call' if any(inv['action_required'] == 'call' for inv in contact_invoices) else 'email'
            }
            
            if requires_approval:
                pending_approvals.append(action)
            else:
                if action['action_required'] == 'email':
                    autonomous_emails.append(action)
                elif action['action_required'] == 'call':
                    autonomous_calls.append(action)
        
        # Count invoices that need no action
        no_action_invoices = [a for a in all_analyses if a['action_required'] == 'none']
        
        self._pending_approvals = pending_approvals
        
        return {
            'total_analyzed': len(invoices),
            'total_contacts': len(by_contact),
            'autonomous_emails': autonomous_emails,
            'autonomous_calls': autonomous_calls,
            'pending_approvals': pending_approvals,
            'no_action_count': len(no_action_invoices),
            'summary': {
                'contacts_to_email': len(autonomous_emails) + len(autonomous_calls),
                'contacts_need_approval': len(pending_approvals),
                'invoices_no_action': len(no_action_invoices)
            }
        }