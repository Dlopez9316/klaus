from google_auth_oauthlib.flow import InstalledAppFlow
import json

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify'
]

flow = InstalledAppFlow.from_client_secrets_file('klaus_credentials.json', SCOPES)
creds = flow.run_local_server(port=0)

print('\n' + '='*60)
print('SUCCESS! Copy these values to Railway environment variables:')
print('='*60)
print(f'\nGMAIL_REFRESH_TOKEN={creds.refresh_token}')
print(f'\nGMAIL_CLIENT_ID={creds.client_id}')
print(f'\nGMAIL_CLIENT_SECRET={creds.client_secret}')
print('\n' + '='*60)
