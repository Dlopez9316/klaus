"""
Klaus Google Drive Integration
Access documents (W-9s, COIs) and knowledge base (meeting transcripts)
"""

import os
import pickle
from typing import List, Dict, Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io


class KlausGoogleDrive:
    """
    Google Drive client for Klaus
    Manages documents and knowledge base
    """
    
    # Google Drive API scopes
    SCOPES = [
        'https://www.googleapis.com/auth/drive.readonly',
        'https://www.googleapis.com/auth/drive.file'
    ]
    
    def __init__(self, credentials_file: str = "klaus_credentials.json"):
        self.credentials_file = credentials_file
        self.token_file = "klaus_drive_token.pickle"
        self.service = None
        self._authenticate()
        
        # Document paths (will be configured)
        self.document_folders = {
            'w9': None,
            'coi': None,
            'dba': None,
            'ach_forms': None,
            'knowledge_base': None,
            'meeting_transcripts': None
        }
    
    def _authenticate(self):
        """Authenticate with Google Drive API"""
        creds = None
        
        # Load existing token
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        
        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save credentials
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        self.service = build('drive', 'v3', credentials=creds)
    
    def configure_folders(self, folder_config: Dict[str, str]):
        """
        Configure folder IDs for different document types
        
        Args:
            folder_config: Dict mapping document type to folder ID
            Example: {'w9': '1ABC...', 'knowledge_base': '1XYZ...'}
        """
        self.document_folders.update(folder_config)
    
    def get_document(self, doc_type: str, filename: Optional[str] = None) -> Optional[Dict]:
        """
        Get a document from Drive
        
        Args:
            doc_type: Type of document ('w9', 'coi', 'dba', etc.)
            filename: Optional specific filename
        
        Returns:
            Dict with file info and download link
        """
        
        folder_id = self.document_folders.get(doc_type)
        if not folder_id:
            return None
        
        try:
            # Search for files in folder
            query = f"'{folder_id}' in parents and trashed=false"
            
            if filename:
                query += f" and name='{filename}'"
            
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, mimeType, modifiedTime, webViewLink)',
                orderBy='modifiedTime desc'
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                # Return most recent file
                file = files[0]
                return {
                    'id': file['id'],
                    'name': file['name'],
                    'mime_type': file['mimeType'],
                    'modified': file['modifiedTime'],
                    'web_link': file['webViewLink'],
                    'download_link': self._get_download_link(file['id'])
                }
            
            return None
        
        except Exception as e:
            print(f"Error getting document: {e}")
            return None
    
    def _get_download_link(self, file_id: str) -> str:
        """Generate direct download link"""
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    
    def download_document(self, file_id: str, destination_path: str) -> bool:
        """
        Download a document from Drive
        
        Args:
            file_id: Google Drive file ID
            destination_path: Local path to save file
        
        Returns:
            True if successful
        """
        
        try:
            request = self.service.files().get_media(fileId=file_id)
            
            with io.FileIO(destination_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
            
            return True
        
        except Exception as e:
            print(f"Error downloading document: {e}")
            return False
    
    def search_knowledge_base(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Search meeting transcripts and knowledge base documents
        
        Args:
            query: Search query
            max_results: Maximum number of results
        
        Returns:
            List of relevant documents
        """
        
        knowledge_folder = self.document_folders.get('knowledge_base')
        transcripts_folder = self.document_folders.get('meeting_transcripts')
        
        if not knowledge_folder and not transcripts_folder:
            return []
        
        try:
            # Build search query
            folder_queries = []
            if knowledge_folder:
                folder_queries.append(f"'{knowledge_folder}' in parents")
            if transcripts_folder:
                folder_queries.append(f"'{transcripts_folder}' in parents")
            
            search_query = f"({' or '.join(folder_queries)}) and fullText contains '{query}' and trashed=false"
            
            results = self.service.files().list(
                q=search_query,
                spaces='drive',
                fields='files(id, name, mimeType, modifiedTime, webViewLink)',
                orderBy='modifiedTime desc',
                pageSize=max_results
            ).execute()
            
            files = results.get('files', [])
            
            return [
                {
                    'id': f['id'],
                    'name': f['name'],
                    'mime_type': f['mimeType'],
                    'modified': f['modifiedTime'],
                    'web_link': f['webViewLink']
                }
                for f in files
            ]
        
        except Exception as e:
            print(f"Error searching knowledge base: {e}")
            return []
    
    def get_document_content(self, file_id: str) -> Optional[str]:
        """
        Get text content of a Google Doc
        
        Args:
            file_id: Google Drive file ID
        
        Returns:
            Text content of document
        """
        
        try:
            # Export Google Doc as plain text
            request = self.service.files().export_media(
                fileId=file_id,
                mimeType='text/plain'
            )
            
            content = request.execute()
            return content.decode('utf-8')
        
        except Exception as e:
            print(f"Error getting document content: {e}")
            return None
    
    def create_knowledge_document(self, title: str, content: str) -> Optional[str]:
        """
        Create a new Google Doc in knowledge base
        
        Args:
            title: Document title
            content: Document content
        
        Returns:
            File ID if successful
        """
        
        knowledge_folder = self.document_folders.get('knowledge_base')
        if not knowledge_folder:
            return None
        
        try:
            # Create Google Doc
            file_metadata = {
                'name': title,
                'mimeType': 'application/vnd.google-apps.document',
                'parents': [knowledge_folder]
            }
            
            # Create empty doc
            file = self.service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            
            # Would need Google Docs API to add content
            # For now, just create the doc
            
            return file.get('id')
        
        except Exception as e:
            print(f"Error creating document: {e}")
            return None
    
    def list_all_documents(self, doc_type: str) -> List[Dict]:
        """
        List all documents of a given type
        
        Args:
            doc_type: Document type key
        
        Returns:
            List of all documents in that folder
        """
        
        folder_id = self.document_folders.get(doc_type)
        if not folder_id:
            return []
        
        try:
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces='drive',
                fields='files(id, name, mimeType, modifiedTime, webViewLink)',
                orderBy='name'
            ).execute()
            
            return results.get('files', [])
        
        except Exception as e:
            print(f"Error listing documents: {e}")
            return []


class KlausKnowledgeBase:
    """
    Knowledge base manager for Klaus
    Reads configuration and meeting transcripts
    """
    
    def __init__(self, drive_client: KlausGoogleDrive, anthropic_api_key: str):
        self.drive = drive_client
        
        from anthropic import Anthropic
        self.ai_client = Anthropic(api_key=anthropic_api_key)
        
        self.config = {}
        self.transcripts = []
    
    def load_configuration(self, config_doc_id: str):
        """Load Klaus configuration from Google Doc"""
        
        content = self.drive.get_document_content(config_doc_id)
        if content:
            # Parse configuration
            # Expected format: Key: Value pairs
            self.config = self._parse_config(content)
    
    def _parse_config(self, content: str) -> Dict:
        """Parse configuration text into dict"""
        
        config = {}
        current_section = 'general'
        
        for line in content.split('\n'):
            line = line.strip()
            
            if not line:
                continue
            
            # Section headers (e.g., "## Collections Philosophy")
            if line.startswith('##'):
                current_section = line.replace('##', '').strip().lower().replace(' ', '_')
                config[current_section] = {}
            
            # Key-value pairs
            elif ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if current_section not in config:
                    config[current_section] = {}
                
                config[current_section][key.lower().replace(' ', '_')] = value
        
        return config
    
    def search_transcripts(self, query: str) -> List[str]:
        """Search meeting transcripts for relevant context"""
        
        # Search Drive for relevant docs
        results = self.drive.search_knowledge_base(query, max_results=3)
        
        # Get content of relevant documents
        contexts = []
        for doc in results:
            content = self.drive.get_document_content(doc['id'])
            if content:
                contexts.append(content)
        
        return contexts
    
    def get_context_for_scenario(self, scenario: str) -> str:
        """
        Get relevant context from knowledge base for a scenario
        
        Args:
            scenario: Description of current situation
        
        Returns:
            Relevant context from transcripts and config
        """
        
        # Search transcripts
        contexts = self.search_transcripts(scenario)
        
        # Combine with relevant config
        relevant_config = self._get_relevant_config(scenario)
        
        combined = f"""
Configuration Guidelines:
{relevant_config}

Context from Past Conversations:
{chr(10).join(contexts[:500])}  # Limit length
"""
        
        return combined
    
    def _get_relevant_config(self, scenario: str) -> str:
        """Extract relevant configuration based on scenario"""
        
        # Simple keyword matching
        relevant = []
        
        scenario_lower = scenario.lower()
        
        for section, values in self.config.items():
            if any(keyword in scenario_lower for keyword in section.split('_')):
                relevant.append(f"## {section.replace('_', ' ').title()}")
                for key, value in values.items():
                    relevant.append(f"{key.replace('_', ' ').title()}: {value}")
        
        return '\n'.join(relevant)
    
    def ask_ai_for_guidance(self, situation: str, context: str) -> str:
        """
        Ask Claude AI for guidance given situation and context
        
        Args:
            situation: Current situation description
            context: Relevant context from knowledge base
        
        Returns:
            AI-generated guidance
        """
        
        prompt = f"""You are Klaus, an accounts receivable specialist at Leverage Live Local.

Based on the following context from our knowledge base:
{context}

Please provide guidance for this situation:
{situation}

What should I do? Be specific and reference the guidelines above."""
        
        try:
            response = self.ai_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return response.content[0].text
        
        except Exception as e:
            return f"Unable to get guidance: {str(e)}"
