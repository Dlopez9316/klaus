"""
HubSpot API Client
Handles invoice and deal management
NOW WITH INVOICE URL GENERATION FOR HYPERLINKING
"""

from hubspot import HubSpot
from hubspot.crm.objects import SimplePublicObjectInput, ApiException
from typing import List, Dict, Optional
from datetime import datetime
import os


class HubSpotClient:
    """Client for interacting with HubSpot CRM"""
    
    def __init__(self, api_key: str, portal_id: Optional[str] = None):
        self.api_key = api_key
        self.client = HubSpot(access_token=api_key)
        
        # Portal ID for generating invoice URLs
        # Hardcoded for Leverage Live Local
        self.portal_id = portal_id or os.getenv("HUBSPOT_PORTAL_ID") or "44968885"
        print(f"✓ HubSpot Portal ID: {self.portal_id}")
    
    def get_invoice_url(self, invoice_id: str) -> str:
        """
        Generate HubSpot URL for an invoice
        
        Args:
            invoice_id: HubSpot invoice object ID
        
        Returns:
            Direct URL to the invoice in HubSpot
        """
        if not self.portal_id:
            return ""
        
        # HubSpot invoice URLs follow this pattern:
        # https://app.hubspot.com/contacts/{PORTAL_ID}/record/2-130/{INVOICE_ID}
        # Object type 2-130 is for invoices
        return f"https://app.hubspot.com/contacts/{self.portal_id}/record/2-130/{invoice_id}"
    
    async def get_invoices(self, status: str = "open") -> List[Dict]:
        """
        Fetch UNPAID invoices from HubSpot - paginate to get RECENT ones
        NOW INCLUDES CONTACT INFORMATION (Bill To person) AND HUBSPOT URL
        """
        try:
            all_invoices = []
            after = None
            pages_fetched = 0
            max_pages = 20
            
            while pages_fetched < max_pages:
                invoices_response = self.client.crm.objects.basic_api.get_page(
                    object_type="invoices",
                    limit=100,
                    after=after,
                    properties=[
                        "hs_invoice_number",
                        "hs_title",
                        "hs_amount_billed",
                        "hs_payment_status",
                        "hs_balance_due",
                        "hs_due_date",
                        "hs_createdate",
                        "hs_number",
                        "hs_payment_date",
                        "hs_invoice_link"
                    ],
                    associations=["companies", "contacts"]
                )
                
                for invoice in invoices_response.results:
                    props = invoice.properties
                    
                    payment_status = (props.get("hs_payment_status") or "").lower().strip()
                    payment_date = props.get("hs_payment_date")
                    balance_due = float(props.get("hs_balance_due", 0))
                    
                    # Get company name
                    company_name = None
                    if hasattr(invoice, 'associations') and invoice.associations:
                        company_associations = invoice.associations.get('companies', {})
                        if company_associations and hasattr(company_associations, 'results') and company_associations.results:
                            company_id = company_associations.results[0].id
                            try:
                                company = self.client.crm.companies.basic_api.get_by_id(
                                    company_id=company_id,
                                    properties=["name"]
                                )
                                company_name = company.properties.get("name")
                            except:
                                pass
                    
                    # Get contact info
                    contact_name = None
                    contact_email = None
                    contact_firstname = None
                    contact_lastname = None
                    
                    if hasattr(invoice, 'associations') and invoice.associations:
                        contact_associations = invoice.associations.get('contacts', {})
                        if contact_associations and hasattr(contact_associations, 'results') and contact_associations.results:
                            contact_id = contact_associations.results[0].id
                            try:
                                contact = self.client.crm.contacts.basic_api.get_by_id(
                                    contact_id=contact_id,
                                    properties=["firstname", "lastname", "email"]
                                )
                                contact_props = contact.properties
                                contact_firstname = contact_props.get("firstname", "")
                                contact_lastname = contact_props.get("lastname", "")
                                contact_name = f"{contact_firstname} {contact_lastname}".strip()
                                contact_email = contact_props.get("email", "")
                            except Exception as e:
                                print(f"Could not fetch contact for invoice {invoice.id}: {e}")
                    
                    # Fallback: if no contact, use company name
                    if not contact_name:
                        contact_name = company_name or props.get("hs_title", "Unknown")
                    if not contact_email:
                        contact_email = "unknown@email.com"
                    
                    invoice_number = props.get("hs_invoice_number") or props.get("hs_number") or props.get("hs_title") or ""

                    # Use the public invoice link from HubSpot (preferred) or fall back to internal URL
                    hubspot_url = props.get("hs_invoice_link") or self.get_invoice_url(invoice.id)
                    
                    all_invoices.append({
                        'id': invoice.id,
                        'number': invoice_number,
                        'company_name': company_name or props.get("hs_title", ""),
                        'contact_name': contact_name,
                        'contact_email': contact_email,
                        'contact_firstname': contact_firstname,
                        'contact_lastname': contact_lastname,
                        'amount': float(props.get("hs_amount_billed", 0)) if props.get("hs_amount_billed") else 0.0,
                        'balance_due': balance_due,
                        'due_date': props.get("hs_due_date", ""),
                        'created_date': props.get("hs_createdate", ""),
                        'payment_date': payment_date,
                        'status': payment_status,
                        'hubspot_url': hubspot_url
                    })
                
                pages_fetched += 1
                
                if hasattr(invoices_response, 'paging') and invoices_response.paging and hasattr(invoices_response.paging, 'next'):
                    after = invoices_response.paging.next.after
                else:
                    break
            
            all_invoices.sort(key=lambda x: x['created_date'], reverse=True)
            
            unpaid_invoices = [
                inv for inv in all_invoices 
                if inv['balance_due'] > 0 and inv['payment_date'] is None
            ]
            
            print(f"Fetched {len(all_invoices)} total invoices across {pages_fetched} pages, {len(unpaid_invoices)} are UNPAID and RECENT")
            return unpaid_invoices
        
        except ApiException as e:
            raise Exception(f"Failed to fetch invoices: {str(e)}")
    
    async def update_invoice_reconciliation_status(self, invoice_id: str, status: str, transaction_details: Optional[str] = None) -> bool:
        """
        Update invoice reconciliation status using custom property
        """
        try:
            properties = {
                "reconciliation_status": status
            }
            
            self.client.crm.objects.basic_api.update(
                object_type="invoices",
                object_id=invoice_id,
                simple_public_object_input=SimplePublicObjectInput(properties=properties)
            )
            
            print(f"✅ Updated invoice {invoice_id} to status: {status}")
            return True
        
        except ApiException as e:
            raise Exception(f"Failed to update invoice reconciliation status: {str(e)}")
    
    async def add_note_to_deal(self, deal_id: str, note: str) -> bool:
        """Add a note to a deal"""
        try:
            engagement = {
                "engagement": {
                    "active": True,
                    "type": "NOTE"
                },
                "associations": {
                    "dealIds": [int(deal_id)]
                },
                "metadata": {
                    "body": note
                }
            }
            return True
        except Exception as e:
            print(f"Failed to add note: {str(e)}")
            return False
    
    def _extract_invoice_number(self, deal_name: str) -> str:
        """Extract invoice number from deal name"""
        import re
        match = re.search(r'INV-(\d+)', deal_name, re.IGNORECASE)
        if match:
            return f"INV-{match.group(1)}"
        return deal_name