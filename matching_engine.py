"""
Intelligent Reconciliation Matching Engine
Learns from approvals and understands payment processors
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from fuzzywuzzy import fuzz
import anthropic
import re
import json
import os

# Import database module for Railway-compatible storage
import database as db


class ReconciliationEngine:
    """
    Intelligent matching engine that learns from your approvals
    """

    PROCESSORS = {
        'stripe': {'keywords': ['stripe', 'st-'], 'fee_percent': 3.5, 'fee_fixed': 0.30},
        'avidpay': {'keywords': ['avidpay'], 'fee_percent': 1.0, 'fee_fixed': 0.0},
        'ach': {'keywords': ['ach', 'sec:ccd', 'sec:ppd'], 'fee_percent': 0.0, 'fee_fixed': 0.0},
        'wire': {'keywords': ['fedwire', 'chips', 'wire'], 'fee_percent': 0.0, 'fee_fixed': 0.0},
        'rtp': {'keywords': ['real time payment'], 'fee_percent': 0.0, 'fee_fixed': 0.0},
        'zelle': {'keywords': ['zelle'], 'fee_percent': 0.0, 'fee_fixed': 0.0},
        'amex': {'keywords': ['american express'], 'fee_percent': 0.0, 'fee_fixed': 0.0}
    }

    def __init__(self, anthropic_api_key: str, memory_file: str = "memory.json"):
        self.anthropic_api_key = anthropic_api_key
        self.client = anthropic.Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None
        self.memory_file = memory_file
        # Use database module for persistent storage (works on Railway)
        self.memory = self._load_memory()

    def _load_memory(self) -> Dict:
        """Load memory from database (Railway) or JSON file (local dev)"""
        return db.load_memory()

    def _save_memory(self):
        """Save memory to database (Railway) or JSON file (local dev)"""
        db.save_memory(self.memory)
    
    def learn_association(self, transaction_name: str, company_name: str):
        trans_clean = self._clean_company_name(transaction_name)
        comp_clean = self._clean_company_name(company_name)
        self.memory['associations'][trans_clean] = comp_clean
        self._save_memory()
        print(f"Learned: '{trans_clean}' -> '{comp_clean}'")
    
    def deny_match(self, transaction_description: str, invoice_id: str):
        """
        Record a denied match so it won't be suggested again
        Only blocks this specific transaction-invoice pairing
        """
        denial = {
            'transaction_description': transaction_description,
            'invoice_id': invoice_id,
            'denied_at': datetime.now().isoformat()
        }
        
        if 'denied_matches' not in self.memory:
            self.memory['denied_matches'] = []
        
        # Check if already denied
        for existing in self.memory['denied_matches']:
            if (existing['transaction_description'] == transaction_description and 
                existing['invoice_id'] == invoice_id):
                print(f"Match already denied: {transaction_description[:50]}... -> {invoice_id}")
                return
        
        self.memory['denied_matches'].append(denial)
        self._save_memory()
        print(f"Denied: {transaction_description[:50]}... -> Invoice {invoice_id}")
    
    def is_match_denied(self, transaction_description: str, invoice_id: str) -> bool:
        """
        Check if this EXACT transaction-invoice pair has been denied.
        Only blocks the specific transaction description matched to the specific invoice.
        """
        if 'denied_matches' not in self.memory:
            return False

        for denial in self.memory['denied_matches']:
            if (denial['transaction_description'] == transaction_description and
                denial['invoice_id'] == invoice_id):
                return True

        return False
    
    def mark_transaction_accounted(self, transaction_description: str, transaction_id: Optional[str], 
                                   amount: float, date: str, company_name: str, invoice_id: Optional[str] = None):
        """
        Mark a transaction as historically reconciled/accounted for
        These transactions won't be suggested for matching
        """
        if 'accounted_transactions' not in self.memory:
            self.memory['accounted_transactions'] = []
        
        # Check if already accounted
        for existing in self.memory['accounted_transactions']:
            if existing.get('transaction_description') == transaction_description:
                return
        
        accounted = {
            'transaction_id': transaction_id,
            'transaction_description': transaction_description,
            'amount': amount,
            'date': date,
            'company_name': company_name,
            'invoice_id': invoice_id,
            'accounted_at': datetime.now().isoformat()
        }
        
        self.memory['accounted_transactions'].append(accounted)
        self._save_memory()
        print(f"Marked as accounted: {transaction_description[:50]}... (${amount})")
    
    def is_transaction_accounted(self, transaction_description: str) -> bool:
        """Check if transaction is already accounted for"""
        if 'accounted_transactions' not in self.memory:
            return False
        
        for accounted in self.memory['accounted_transactions']:
            if accounted['transaction_description'] == transaction_description:
                return True
        return False
    
    def validate_company_payments(self, company_name: str, paid_invoices: List[Dict], 
                                  all_transactions: List[Dict]) -> Dict:
        """
        Validate that payments match paid invoices for a company
        Returns status and details about payment history
        """
        # Get paid invoices for this company
        company_paid_invoices = [inv for inv in paid_invoices if inv.get('company_name') == company_name]
        
        # Calculate total of paid invoices
        paid_invoices_total = sum(inv.get('amount', 0) for inv in company_paid_invoices)
        
        # Find transactions that match this company (using fuzzy matching)
        company_clean = self._clean_company_name(company_name)
        matching_transactions = []
        
        for txn in all_transactions:
            txn_desc_clean = self._clean_company_name(txn.get('description', ''))
            
            # Check if company name appears in transaction
            similarity = fuzz.partial_ratio(company_clean, txn_desc_clean)
            if similarity >= 80:  # High confidence match
                matching_transactions.append(txn)
        
        # Calculate total of matching transactions (excluding already accounted ones)
        unaccounted_transactions = [
            txn for txn in matching_transactions 
            if not self.is_transaction_accounted(txn.get('description', ''))
        ]
        
        payments_total = sum(abs(txn.get('amount', 0)) for txn in matching_transactions)
        
        # Determine status with tolerance
        tolerance = max(paid_invoices_total * 0.01, 5.0)  # 1% or $5, whichever is larger
        discrepancy = payments_total - paid_invoices_total
        
        if abs(discrepancy) <= tolerance:
            status = 'balanced'
        elif discrepancy < -tolerance:
            status = 'short'  # Missing payments
        else:
            status = 'over'  # Extra payments
        
        # Sort transactions by date to identify "new" ones
        matching_transactions.sort(key=lambda x: x.get('date', ''))
        
        # Find the date of the last paid invoice
        last_paid_date = None
        if company_paid_invoices:
            paid_dates = [inv.get('payment_date') or inv.get('created_date') for inv in company_paid_invoices]
            paid_dates = [d for d in paid_dates if d]
            if paid_dates:
                paid_dates.sort()
                last_paid_date = paid_dates[-1]
        
        # Identify new transactions (after last paid invoice)
        new_transactions = []
        accounted_transactions = []
        
        for txn in matching_transactions:
            txn_date = txn.get('date', '')
            is_accounted = self.is_transaction_accounted(txn.get('description', ''))
            
            if is_accounted:
                accounted_transactions.append(txn)
            elif last_paid_date and txn_date > last_paid_date:
                new_transactions.append(txn)
            else:
                # Transaction is before or at last paid date, should be accounted for
                accounted_transactions.append(txn)
        
        return {
            'company_name': company_name,
            'status': status,
            'paid_invoices_total': paid_invoices_total,
            'paid_invoices_count': len(company_paid_invoices),
            'payments_total': payments_total,
            'payments_count': len(matching_transactions),
            'discrepancy': discrepancy,
            'tolerance': tolerance,
            'accounted_transactions': accounted_transactions,
            'new_transactions': new_transactions,
            'last_paid_date': last_paid_date,
            'message': self._get_validation_message(status, discrepancy, tolerance)
        }
    
    def _get_validation_message(self, status: str, discrepancy: float, tolerance: float) -> str:
        """Generate human-readable validation message"""
        if status == 'balanced':
            return f"✓ Payment history is balanced (within ${tolerance:.2f} tolerance)"
        elif status == 'short':
            return f"⚠️ Missing ${abs(discrepancy):.2f} in payments"
        else:  # over
            return f"⚠️ Extra ${discrepancy:.2f} in payments (may be applied to open invoice)"
    
    def auto_account_historical_transactions(self, company_name: str, paid_invoices: List[Dict], 
                                            transactions: List[Dict], auto_approve: bool = False):
        """
        Mark transactions as accounted if payment history is balanced.
        By default, this only suggests - does NOT auto-mark unless auto_approve=True.
        
        Args:
            company_name: Company to validate
            paid_invoices: List of paid invoices
            transactions: List of all transactions
            auto_approve: If True, automatically mark as accounted (default: False)
        
        Returns:
            Dictionary with suggestions for accounting, not auto-applied
        """
        validation = self.validate_company_payments(company_name, paid_invoices, transactions)
        
        if validation['status'] == 'balanced':
            # History matches up - return suggestions for user approval
            suggestions = []
            for txn in validation['accounted_transactions']:
                if not self.is_transaction_accounted(txn.get('description', '')):
                    suggestions.append({
                        'transaction_id': txn.get('transaction_id'),
                        'transaction_description': txn.get('description', ''),
                        'amount': abs(txn.get('amount', 0)),
                        'date': txn.get('date', ''),
                        'company_name': company_name,
                        'reason': 'Historical transaction - company payment history is balanced'
                    })
                    
                    # Only auto-mark if explicitly approved
                    if auto_approve:
                        self.mark_transaction_accounted(
                            transaction_description=txn.get('description', ''),
                            transaction_id=txn.get('transaction_id'),
                            amount=abs(txn.get('amount', 0)),
                            date=txn.get('date', ''),
                            company_name=company_name
                        )
            
            if auto_approve and suggestions:
                print(f"Auto-accounted {len(suggestions)} transactions for {company_name}")
            elif suggestions:
                print(f"Suggested {len(suggestions)} transactions for accounting approval for {company_name}")
            
            return {
                'approved': auto_approve,
                'suggestions': suggestions,
                'count': len(suggestions)
            }
        else:
            print(f"Cannot auto-account for {company_name}: {validation['message']}")
            return {
                'approved': False,
                'suggestions': [],
                'count': 0,
                'message': validation['message']
            }
    
    def suggest_associations_from_history(self, paid_invoices: List[Dict], transactions: List[Dict]) -> List[Dict]:
        """
        Analyze historical paid invoices and transactions to suggest associations
        """
        suggestions = []
        
        for invoice in paid_invoices:
            if not invoice.get('payment_date') or not invoice.get('company_name'):
                continue
            
            try:
                payment_date = datetime.fromisoformat(invoice['payment_date'].replace('Z', '+00:00'))
            except:
                continue
            
            matching_transactions = []
            for txn in transactions:
                try:
                    txn_date = datetime.fromisoformat(txn['date'].replace('Z', '+00:00'))
                    days_diff = abs((txn_date - payment_date).days)
                    
                    if days_diff <= 30:
                        amount_diff = abs(txn['amount'] - invoice['amount'])
                        amount_diff_percent = (amount_diff / invoice['amount']) * 100 if invoice['amount'] > 0 else 100
                        
                        if amount_diff_percent < 20:
                            matching_transactions.append({
                                'transaction': txn,
                                'days_diff': days_diff,
                                'amount_diff_percent': amount_diff_percent
                            })
                except:
                    continue
            
            for match in matching_transactions:
                txn_desc = match['transaction']['description']
                company_name = invoice['company_name']
                
                txn_company = self._extract_company_from_transaction(txn_desc)
                
                similarity = fuzz.partial_ratio(
                    self._clean_company_name(txn_company),
                    self._clean_company_name(company_name)
                )
                
                trans_clean = self._clean_company_name(txn_company)
                comp_clean = self._clean_company_name(company_name)
                
                if trans_clean in self.memory['associations']:
                    continue
                
                if similarity > 30:
                    confidence = (
                        similarity * 0.5 +
                        (100 - match['amount_diff_percent']) * 0.3 +
                        max(0, 100 - match['days_diff'] * 3) * 0.2
                    )
                    
                    suggestions.append({
                        'transaction_name': txn_company,
                        'company_name': company_name,
                        'confidence': round(confidence, 1),
                        'example_invoice': invoice['number'],
                        'example_transaction': txn_desc[:100],
                        'example_amount': invoice['amount'],
                        'example_date': invoice['payment_date']
                    })
        
        seen = set()
        unique_suggestions = []
        for suggestion in suggestions:
            key = (suggestion['transaction_name'].lower(), suggestion['company_name'].lower())
            if key not in seen:
                seen.add(key)
                unique_suggestions.append(suggestion)
        
        unique_suggestions.sort(key=lambda x: x['confidence'], reverse=True)
        return unique_suggestions[:20]
    
    def _extract_company_from_transaction(self, description: str) -> str:
        """
        Extract company name from transaction description
        """
        patterns = [
            r'ORIG CO NAME:([^O]+?)(?:ORIG|$)',
            r'B/O:\s*([^R]+?)(?:REF:|$)',
            r'FROM:\s*([^R]+?)(?:REF:|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description)
            if match:
                company = match.group(1).strip()
                company = re.sub(r'\s+ORIG ID:.*', '', company)
                company = re.sub(r'\s+\d{9,}', '', company)
                return company
        
        return description[:50]
    
    def detect_processor(self, transaction: Dict) -> Optional[Dict]:
        description = transaction.get('description', '').lower()
        for processor_name, config in self.PROCESSORS.items():
            for keyword in config['keywords']:
                if keyword.lower() in description:
                    return {'name': processor_name, 'fee_percent': config['fee_percent'], 'fee_fixed': config['fee_fixed']}
        return None
    
    def calculate_expected_amount(self, invoice_amount: float, processor: Optional[Dict]) -> float:
        """
        Return invoice amount without fee deduction
        We now assume direct payment matching, allowing 1-5% variance for fees
        """
        return invoice_amount
    
    def match_transactions_to_invoices(self, transactions: List[Dict], invoices: List[Dict], confidence_threshold: float = 70.0) -> List[Dict]:
        """
        Match transactions to invoices with validation
        - Filters out already accounted transactions
        - Only matches to unpaid invoices
        - Respects denied matches
        """
        matches = []
        matched_invoices = set()
        
        # Filter to only unpaid invoices
        unpaid_invoices = [inv for inv in invoices if inv.get('status', '').upper() in ['UNPAID', 'OPEN', 'OUTSTANDING', '']]
        
        for transaction in transactions:
            if transaction.get('amount', 0) <= 0:
                continue
            if not transaction.get('is_credit', True):
                continue
            
            # Skip if transaction is already accounted for
            if self.is_transaction_accounted(transaction.get('description', '')):
                continue
            
            available_invoices = [inv for inv in unpaid_invoices if inv['id'] not in matched_invoices]
            best_match = self._find_best_match(transaction, available_invoices)
            if best_match and best_match['confidence'] >= confidence_threshold:
                matches.append(best_match)
                matched_invoices.add(best_match['invoice_id'])
        return matches
    
    def _find_best_match(self, transaction: Dict, invoices: List[Dict]) -> Optional[Dict]:
        candidates = []
        processor = self.detect_processor(transaction)
        transaction_desc = transaction.get('description', '')
        
        for invoice in invoices:
            # Skip if this match was previously denied
            if self.is_match_denied(transaction_desc, invoice['id']):
                continue
            
            memory_match = self._check_memory(transaction, invoice)
            amount_match = self._match_amount_smart(transaction, invoice, processor)
            name_match = self._match_names_smart(transaction, invoice)
            date_match = self._match_dates(transaction, invoice)
            invoice_num_match = self._match_invoice_number(transaction, invoice)
            confidence = self._calculate_confidence_smart(memory_match, amount_match, name_match, date_match, invoice_num_match, processor)
            if confidence > 50:
                candidates.append({
                    'invoice': invoice,
                    'confidence': confidence,
                    'processor': processor,
                    'reasons': {
                        'memory_match': memory_match,
                        'amount_match': amount_match,
                        'name_match': name_match,
                        'date_match': date_match,
                        'invoice_num_match': invoice_num_match,
                        'processor_detected': processor['name'] if processor else None
                    }
                })
        if not candidates:
            return None
        candidates.sort(key=lambda x: x['confidence'], reverse=True)
        best = candidates[0]
        return {
            'transaction_id': transaction.get('transaction_id'),
            'transaction_date': transaction.get('date'),
            'transaction_amount': transaction.get('amount'),
            'transaction_description': transaction.get('description'),
            'invoice_id': best['invoice'].get('id'),
            'invoice_number': best['invoice'].get('number'),
            'invoice_amount': best['invoice'].get('amount'),
            'invoice_date': best['invoice'].get('created_date'),
            'company_name': best['invoice'].get('company_name'),
            'confidence': best['confidence'],
            'processor': best['processor']['name'] if best['processor'] else 'direct',
            'expected_amount': self.calculate_expected_amount(best['invoice'].get('amount', 0), best['processor']),
            'match_reasons': best['reasons']
        }
    
    def _check_memory(self, transaction: Dict, invoice: Dict) -> float:
        trans_desc = self._clean_company_name(transaction.get('description', ''))
        company_name = self._clean_company_name(invoice.get('company_name', ''))
        for learned_trans, learned_company in self.memory['associations'].items():
            if learned_trans in trans_desc and learned_company in company_name:
                return 100
        return 0
    
    def _match_amount_smart(self, transaction: Dict, invoice: Dict, processor: Optional[Dict]) -> float:
        trans_amount = abs(transaction.get('amount', 0))
        inv_amount = invoice.get('amount', 0)
        if trans_amount == 0 or inv_amount == 0:
            return 0
        
        # Compare transaction amount directly to invoice amount (no fee deduction by default)
        diff = abs(trans_amount - inv_amount)
        diff_percent = (diff / inv_amount) * 100
        
        # Exact match or within $1
        if diff < 1.0:
            return 100
        
        # Within 1% - very likely a match (small rounding or minor fee)
        if diff_percent < 1:
            return 95
        
        # Within 2% - likely a match (small transaction fee)
        if diff_percent < 2:
            return 85
        
        # Within 5% - possible match (larger transaction fee)
        if diff_percent < 5:
            return 70
        
        # 5-10% difference - unlikely but possible
        if diff_percent < 10:
            return 50
        
        # >10% difference - not a match
        return 0
    
    def _match_names_smart(self, transaction: Dict, invoice: Dict) -> float:
        trans_desc = self._clean_company_name(transaction.get('description', ''))
        company_name = self._clean_company_name(invoice.get('company_name', ''))
        if not trans_desc or not company_name:
            return 0

        # Remove processor names from transaction description
        for processor in self.PROCESSORS.keys():
            trans_desc = trans_desc.replace(processor, '')
        trans_desc = ' '.join(trans_desc.split())

        # Extract core company name (remove common suffixes)
        company_core = self._extract_company_core(company_name)

        # === TIER 1: Exact substring match (highest confidence) ===
        # If the core company name appears exactly in transaction
        if len(company_core) >= 5 and company_core in trans_desc:
            return 100

        # === TIER 2: Fuzzy substring match (handles misspellings) ===
        # Check if core company name is similar to any part of the transaction
        fuzzy_substring_score = self._fuzzy_substring_match(company_core, trans_desc)
        if fuzzy_substring_score >= 90:
            return 98
        if fuzzy_substring_score >= 80:
            return 92

        # === TIER 3: Word-by-word matching ===
        trans_words = set(trans_desc.split())
        company_words_meaningful = self._get_meaningful_words(company_name)

        if company_words_meaningful:
            # Check for exact word matches
            exact_matches = trans_words & company_words_meaningful

            # Check for fuzzy word matches (handles misspellings like PNAMA vs PANAMA)
            fuzzy_matches = self._count_fuzzy_word_matches(company_words_meaningful, trans_words)

            total_matches = len(exact_matches) + fuzzy_matches
            match_ratio = total_matches / len(company_words_meaningful)

            if match_ratio >= 0.9:
                return 95
            if match_ratio >= 0.75:
                return 90
            if match_ratio >= 0.5:
                return 75 + (match_ratio * 20)

        # === TIER 4: Fuzzy ratio matching (fallback) ===
        # Standard fuzzy matching for edge cases
        ratio = fuzz.partial_ratio(trans_desc, company_name)
        token_ratio = fuzz.token_set_ratio(trans_desc, company_name)

        # Use the better of the two fuzzy methods
        best_ratio = max(ratio, token_ratio)

        # Boost if there's a substring relationship
        if company_name in trans_desc or trans_desc in company_name:
            best_ratio = min(100, best_ratio + 20)

        return best_ratio

    def _extract_company_core(self, company_name: str) -> str:
        """Extract the meaningful core of a company name, removing common suffixes"""
        core = company_name
        suffixes = [
            'LLC', 'INC', 'CORP', 'CORPORATION', 'LTD', 'LIMITED', 'LP', 'LLP',
            'OWNER', 'OWNERS', 'OWNERSHIP',
            'PROPERTIES', 'PROPERTY', 'PROP',
            'GROUP', 'HOLDINGS', 'HOLDING',
            'INVESTMENTS', 'INVESTMENT', 'INVEST',
            'MANAGEMENT', 'MGMT', 'MGT',
            'PARTNERS', 'PARTNER',
            'ASSOCIATES', 'ASSOC',
            'ENTERPRISES', 'ENTERPRISE',
            'COMPANY', 'CO',
            'REAL ESTATE', 'REALTY',
            'DEVELOPMENT', 'DEV',
            'CAPITAL', 'CAP',
            'VENTURES', 'VENTURE',
            'TRUST', 'TR',
            'FUND', 'FUNDS',
            'MF',  # Multifamily
        ]
        for suffix in suffixes:
            # Remove suffix with word boundary (space or end of string)
            core = core.replace(' ' + suffix + ' ', ' ')
            core = core.replace(' ' + suffix, '')
            if core.endswith(suffix):
                core = core[:-len(suffix)]
        return ' '.join(core.split()).strip()

    def _get_meaningful_words(self, company_name: str) -> set:
        """Get meaningful words from company name, filtering out common business terms"""
        ignore_words = {
            'LLC', 'INC', 'CORP', 'LTD', 'LP', 'LLP',
            'THE', 'OF', 'AND', 'AT', 'IN', 'ON', 'FOR', 'A', 'AN',
            'OWNER', 'OWNERS', 'CO', 'COMPANY',
            'PROPERTIES', 'PROPERTY', 'GROUP', 'HOLDINGS',
            'MANAGEMENT', 'MGMT', 'PARTNERS', 'ASSOCIATES',
            'INVESTMENTS', 'INVESTMENT', 'ENTERPRISES',
            'REAL', 'ESTATE', 'REALTY', 'DEVELOPMENT',
            'CAPITAL', 'VENTURES', 'TRUST', 'FUND',
        }
        words = set(company_name.split())
        return words - ignore_words

    def _fuzzy_substring_match(self, needle: str, haystack: str) -> float:
        """Check if needle appears as a fuzzy substring anywhere in haystack"""
        if len(needle) < 3:
            return 0

        needle_len = len(needle)
        best_score = 0

        # Slide a window across haystack and check similarity
        words = haystack.split()
        for i in range(len(words)):
            for j in range(i + 1, min(i + 5, len(words) + 1)):  # Check up to 4-word combinations
                window = ' '.join(words[i:j])
                if len(window) >= len(needle) * 0.7:  # Window should be reasonably sized
                    score = fuzz.ratio(needle, window)
                    best_score = max(best_score, score)

        return best_score

    def _count_fuzzy_word_matches(self, company_words: set, trans_words: set, threshold: int = 80) -> int:
        """Count company words that fuzzy-match transaction words (handles misspellings)"""
        fuzzy_count = 0
        for cw in company_words:
            if cw in trans_words:
                continue  # Already counted as exact match
            if len(cw) < 3:
                continue  # Skip very short words
            for tw in trans_words:
                if len(tw) < 3:
                    continue
                # Check fuzzy similarity
                if fuzz.ratio(cw, tw) >= threshold:
                    fuzzy_count += 1
                    break
        return fuzzy_count
    
    def _clean_company_name(self, name: str) -> str:
        if not name:
            return ""
        name = name.lower()
        suffixes = ['llc', 'inc', 'corp', 'ltd', 'co', 'l.l.c.', 'l.p.', 'lp']
        for suffix in suffixes:
            name = re.sub(rf'\b{suffix}\b', '', name)
        name = re.sub(r'[^\w\s]', ' ', name)
        name = ' '.join(name.split())
        return name.strip()
    
    def _match_dates(self, transaction: Dict, invoice: Dict) -> float:
        try:
            trans_date_str = transaction.get('date', '')
            inv_created_str = invoice.get('created_date', '')
            if not trans_date_str or not inv_created_str:
                return 20
            trans_date = datetime.fromisoformat(trans_date_str.replace('Z', '+00:00'))
            inv_created = datetime.fromisoformat(inv_created_str.replace('Z', '+00:00'))
            days_diff = (trans_date - inv_created).days
            if days_diff < 0:
                return 0
            if days_diff <= 30:
                return 100
            if days_diff <= 60:
                return 90
            if days_diff <= 90:
                return 80
            if days_diff <= 120:
                return 60
            return 30
        except:
            return 20
    
    def _match_invoice_number(self, transaction: Dict, invoice: Dict) -> float:
        trans_desc = (transaction.get('description') or '').upper()
        invoice_num = str(invoice.get('number') or '').upper()
        if invoice_num and invoice_num in trans_desc:
            return 100
        return 0
    
    def _calculate_confidence_smart(self, memory_match: float, amount_match: float, name_match: float, date_match: float, invoice_num_match: float, processor: Optional[Dict]) -> float:
        # If we have a strong name match (company name clearly in transaction), boost confidence significantly
        if name_match >= 95 and amount_match >= 90:
            # Strong name + exact amount = very high confidence
            return min(100, 85 + (name_match * 0.1) + (amount_match * 0.05))

        if memory_match > 0:
            weights = {'memory': 0.5, 'amount': 0.3, 'name': 0.1, 'date': 0.05, 'invoice': 0.05}
        else:
            # Increased name weight from 0.35 to 0.40 for better company matching
            weights = {'memory': 0.0, 'amount': 0.35, 'name': 0.40, 'date': 0.15, 'invoice': 0.10}
        score = (memory_match * weights['memory'] + amount_match * weights['amount'] + name_match * weights['name'] + date_match * weights['date'] + invoice_num_match * weights['invoice'])
        if processor:
            score = min(100, score + 5)
        return round(score, 2)