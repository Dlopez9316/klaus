"""
Plaid API Client
Handles bank account connections and transaction fetching
"""

from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
import plaid
from typing import List, Dict
from datetime import datetime
import json
import os


class PlaidClient:
    """Client for interacting with Plaid API"""
    
    def __init__(self, client_id: str, secret: str, environment: str = "sandbox"):
        self.client_id = client_id
        self.secret = secret
        self.environment = environment
        self.token_file = "plaid_token.json"
        
        # Configure Plaid client
        configuration = plaid.Configuration(
            host=self._get_host(environment),
            api_key={
                'clientId': client_id,
                'secret': secret,
            }
        )
        
        api_client = plaid.ApiClient(configuration)
        self.client = plaid_api.PlaidApi(api_client)
        
        # Load saved access token if it exists
        self.access_token = self._load_access_token()
    
    def _get_host(self, environment: str) -> str:
        """Get Plaid API host based on environment"""
        hosts = {
            "sandbox": plaid.Environment.Sandbox,
            "production": plaid.Environment.Production
        }
        return hosts.get(environment.lower(), plaid.Environment.Sandbox)
    
    def _save_access_token(self, access_token: str):
        """Save access token to file"""
        with open(self.token_file, 'w') as f:
            json.dump({
                'access_token': access_token,
                'saved_at': datetime.now().isoformat()
            }, f)
    
    def _load_access_token(self) -> str:
        """Load access token from file"""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    data = json.load(f)
                    return data.get('access_token')
            except:
                pass
        return None
    
    async def create_link_token(self) -> str:
        """
        Create a Link token for Plaid Link initialization
        """
        try:
            request = LinkTokenCreateRequest(
                products=[Products("transactions")],
                client_name="Reconciliation Agent",
                country_codes=[CountryCode('US')],
                language='en',
                user=LinkTokenCreateRequestUser(
                    client_user_id='user-reconciliation-agent'
                )
            )
            
            response = self.client.link_token_create(request)
            return response['link_token']
        
        except plaid.ApiException as e:
            raise Exception(f"Failed to create link token: {str(e)}")
    
    async def exchange_public_token(self, public_token: str) -> str:
        """
        Exchange public token for access token
        """
        try:
            request = ItemPublicTokenExchangeRequest(
                public_token=public_token
            )
            
            response = self.client.item_public_token_exchange(request)
            self.access_token = response['access_token']
            
            # Save token to file
            self._save_access_token(self.access_token)
            
            return self.access_token
        
        except plaid.ApiException as e:
            raise Exception(f"Failed to exchange token: {str(e)}")
    
    async def get_transactions(
        self, 
        start_date: str, 
        end_date: str
    ) -> List[Dict]:
        """
        Fetch transactions from connected bank account
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
        
        Returns:
            List of transaction dictionaries (ONLY CREDITS - money coming in)
        """
        if not self.access_token:
            raise Exception("No access token available. Please connect your bank account first.")
        
        try:
            request = TransactionsGetRequest(
                access_token=self.access_token,
                start_date=datetime.strptime(start_date, "%Y-%m-%d").date(),
                end_date=datetime.strptime(end_date, "%Y-%m-%d").date(),
                options=TransactionsGetRequestOptions()
            )
            
            response = self.client.transactions_get(request)
            
            # Format transactions
            # CRITICAL: Plaid uses POSITIVE for debits (money out), NEGATIVE for credits (money in)
            # We flip this to be intuitive: positive = money in, negative = money out
            transactions = []
            for txn in response['transactions']:
                # Flip the amount sign
                amount = -txn['amount']
                
                # ONLY include credits (money coming IN to your account)
                # Skip all debits (money going OUT like Wise payments to employees)
                if amount <= 0:
                    continue
                
                transactions.append({
                    'transaction_id': txn['transaction_id'],
                    'date': txn['date'].isoformat() if hasattr(txn['date'], 'isoformat') else str(txn['date']),
                    'amount': amount,
                    'description': txn['name'],
                    'merchant': txn.get('merchant_name', ''),
                    'category': txn.get('category', []),
                    'pending': txn.get('pending', False),
                    'is_credit': True  # All transactions in this list are credits
                })
            
            return transactions
        
        except plaid.ApiException as e:
            error_body = e.body if hasattr(e, 'body') else str(e)
            raise Exception(f"Failed to fetch transactions; {error_body}")