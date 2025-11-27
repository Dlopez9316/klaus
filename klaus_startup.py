"""
Klaus startup helper - decodes tokens from environment variables
"""
import os
import base64


def setup_klaus_credentials():
    """Decode Klaus credentials from environment variables"""
    
    # Decode Gmail token
    if os.getenv("KLAUS_TOKEN_BASE64"):
        try:
            with open("klaus_token.pickle", "wb") as f:
                f.write(base64.b64decode(os.getenv("KLAUS_TOKEN_BASE64")))
            print("✓ Klaus Gmail token loaded")
        except Exception as e:
            print(f"✗ Error loading Gmail token: {e}")
    
    # Decode Drive token
    if os.getenv("KLAUS_DRIVE_TOKEN_BASE64"):
        try:
            with open("klaus_drive_token.pickle", "wb") as f:
                f.write(base64.b64decode(os.getenv("KLAUS_DRIVE_TOKEN_BASE64")))
            print("✓ Klaus Drive token loaded")
        except Exception as e:
            print(f"✗ Error loading Drive token: {e}")
    
    print("Klaus credentials setup complete")


if __name__ == "__main__":
    # Test the setup
    setup_klaus_credentials()
