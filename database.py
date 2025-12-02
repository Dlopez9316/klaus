"""
Database module for Railway-compatible persistent storage
Uses PostgreSQL when DATABASE_URL is set, falls back to local JSON files for development
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

# Check if we're on Railway (DATABASE_URL is set)
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    USE_DATABASE = True
else:
    USE_DATABASE = False
    psycopg2 = None


def get_connection():
    """Get a database connection"""
    if not USE_DATABASE:
        return None

    # Railway uses postgres:// but psycopg2 needs postgresql://
    db_url = DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    return psycopg2.connect(db_url)


@contextmanager
def get_cursor():
    """Context manager for database cursor"""
    conn = get_connection()
    if conn is None:
        yield None
        return

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def init_database():
    """Initialize database tables if they don't exist"""
    if not USE_DATABASE:
        print("No DATABASE_URL found - using local JSON files")
        return False

    with get_cursor() as cursor:
        if cursor is None:
            return False

        # Create reconciliation memory table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reconciliation_memory (
                id SERIAL PRIMARY KEY,
                key VARCHAR(50) UNIQUE NOT NULL,
                data JSONB NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create klaus_config table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS klaus_config (
                id SERIAL PRIMARY KEY,
                config JSONB NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create communication_history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS communication_history (
                id SERIAL PRIMARY KEY,
                invoice_id VARCHAR(100),
                company_name VARCHAR(255),
                method VARCHAR(50),
                message_type VARCHAR(50),
                sent_at TIMESTAMP,
                approved_by VARCHAR(100),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create call_history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_history (
                id SERIAL PRIMARY KEY,
                call_id VARCHAR(100) UNIQUE,
                call_data JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Create schedule_config table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedule_config (
                id SERIAL PRIMARY KEY,
                config JSONB NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        print("✓ Database tables initialized")
        return True


# ==============================================================================
# RECONCILIATION MEMORY FUNCTIONS
# ==============================================================================

def load_memory() -> Dict:
    """Load reconciliation memory from database or JSON file"""
    default_memory = {
        'associations': {},
        'processor_patterns': {},
        'denied_matches': [],
        'accounted_transactions': []
    }

    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return default_memory

            cursor.execute("SELECT key, data FROM reconciliation_memory")
            rows = cursor.fetchall()

            if not rows:
                return default_memory

            memory = default_memory.copy()
            for row in rows:
                memory[row['key']] = row['data']
            return memory
    else:
        # Fallback to JSON file
        if os.path.exists("memory.json"):
            try:
                with open("memory.json", 'r') as f:
                    return json.load(f)
            except:
                pass
        return default_memory


def save_memory(memory: Dict):
    """Save reconciliation memory to database or JSON file"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return

            for key in ['associations', 'processor_patterns', 'denied_matches', 'accounted_transactions']:
                if key in memory:
                    cursor.execute("""
                        INSERT INTO reconciliation_memory (key, data, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (key) DO UPDATE SET data = %s, updated_at = NOW()
                    """, (key, Json(memory[key]), Json(memory[key])))
    else:
        # Fallback to JSON file
        with open("memory.json", 'w') as f:
            json.dump(memory, f, indent=2)


# ==============================================================================
# KLAUS CONFIG FUNCTIONS
# ==============================================================================

def load_klaus_config() -> Dict:
    """Load Klaus configuration from database or JSON file"""
    default_config = {
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

    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return default_config

            cursor.execute("SELECT config FROM klaus_config ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()

            if row:
                return row['config']
            return default_config
    else:
        # Fallback to JSON file
        if os.path.exists("klaus_config.json"):
            try:
                with open("klaus_config.json", 'r') as f:
                    return json.load(f)
            except:
                pass
        return default_config


def save_klaus_config(config: Dict):
    """Save Klaus configuration to database or JSON file"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return

            # Check if config exists
            cursor.execute("SELECT id FROM klaus_config LIMIT 1")
            row = cursor.fetchone()

            if row:
                cursor.execute("""
                    UPDATE klaus_config SET config = %s, updated_at = NOW() WHERE id = %s
                """, (Json(config), row['id']))
            else:
                cursor.execute("""
                    INSERT INTO klaus_config (config, updated_at) VALUES (%s, NOW())
                """, (Json(config),))
    else:
        # Fallback to JSON file
        with open("klaus_config.json", 'w') as f:
            json.dump(config, f, indent=2)


# ==============================================================================
# COMMUNICATION HISTORY FUNCTIONS
# ==============================================================================

def load_communication_history() -> List[Dict]:
    """Load Klaus communication history from database or JSON file"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return []

            cursor.execute("""
                SELECT invoice_id, company_name, method, message_type,
                       sent_at, approved_by
                FROM communication_history
                ORDER BY sent_at DESC
            """)
            rows = cursor.fetchall()

            history = []
            for row in rows:
                history.append({
                    'invoice_id': row['invoice_id'],
                    'company_name': row['company_name'],
                    'method': row['method'],
                    'message_type': row['message_type'],
                    'sent_at': row['sent_at'].isoformat() if row['sent_at'] else None,
                    'approved_by': row['approved_by']
                })
            return history
    else:
        # Fallback to JSON file
        if os.path.exists("klaus_communication_history.json"):
            try:
                with open("klaus_communication_history.json", 'r') as f:
                    return json.load(f)
            except:
                pass
        return []


def save_communication_history(history: List[Dict]):
    """Save entire communication history (for migration)"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return

            for entry in history:
                sent_at = entry.get('sent_at')
                if isinstance(sent_at, str):
                    try:
                        sent_at = datetime.fromisoformat(sent_at.replace('Z', '+00:00'))
                    except:
                        sent_at = datetime.now()

                cursor.execute("""
                    INSERT INTO communication_history
                    (invoice_id, company_name, method, message_type, sent_at, approved_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    entry.get('invoice_id'),
                    entry.get('company_name'),
                    entry.get('method'),
                    entry.get('message_type'),
                    sent_at,
                    entry.get('approved_by')
                ))
    else:
        # Fallback to JSON file
        with open("klaus_communication_history.json", 'w') as f:
            json.dump(history, f, indent=2)


def add_communication(invoice_id: str, company_name: str, method: str,
                      message_type: str, approved_by: Optional[str] = None):
    """Add a single communication entry"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return

            cursor.execute("""
                INSERT INTO communication_history
                (invoice_id, company_name, method, message_type, sent_at, approved_by)
                VALUES (%s, %s, %s, %s, NOW(), %s)
            """, (invoice_id, company_name, method, message_type, approved_by))
    else:
        # Fallback - load, append, save
        history = load_communication_history()
        history.append({
            'invoice_id': invoice_id,
            'company_name': company_name,
            'method': method,
            'message_type': message_type,
            'sent_at': datetime.now().isoformat(),
            'approved_by': approved_by
        })
        save_communication_history(history)


# ==============================================================================
# CALL HISTORY FUNCTIONS
# ==============================================================================

def load_call_history() -> List[Dict]:
    """Load call history from database or JSON file"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return []

            cursor.execute("SELECT call_id, call_data FROM call_history ORDER BY created_at DESC")
            rows = cursor.fetchall()

            return [row['call_data'] for row in rows]
    else:
        # Fallback to JSON file
        if os.path.exists("klaus_call_history.json"):
            try:
                with open("klaus_call_history.json", 'r') as f:
                    return json.load(f)
            except:
                pass
        return []


def save_call_history(history: List[Dict]):
    """Save entire call history (for migration)"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return

            for call in history:
                call_id = call.get('call_id') or call.get('id') or str(hash(json.dumps(call, default=str)))
                cursor.execute("""
                    INSERT INTO call_history (call_id, call_data)
                    VALUES (%s, %s)
                    ON CONFLICT (call_id) DO UPDATE SET call_data = %s
                """, (call_id, Json(call), Json(call)))
    else:
        # Fallback to JSON file
        with open("klaus_call_history.json", 'w') as f:
            json.dump(history, f, indent=2)


def add_call(call_data: Dict):
    """Add a single call entry"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return

            call_id = call_data.get('call_id') or call_data.get('id') or str(datetime.now().timestamp())
            cursor.execute("""
                INSERT INTO call_history (call_id, call_data)
                VALUES (%s, %s)
                ON CONFLICT (call_id) DO UPDATE SET call_data = %s
            """, (call_id, Json(call_data), Json(call_data)))
    else:
        # Fallback - load, append, save
        history = load_call_history()
        history.append(call_data)
        save_call_history(history)


def update_call(call_id: str, call_data: Dict):
    """Update an existing call entry"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return

            cursor.execute("""
                UPDATE call_history SET call_data = %s WHERE call_id = %s
            """, (Json(call_data), call_id))
    else:
        # Fallback - load, update, save
        history = load_call_history()
        for i, call in enumerate(history):
            if call.get('call_id') == call_id or call.get('id') == call_id:
                history[i] = call_data
                break
        save_call_history(history)


# ==============================================================================
# SCHEDULE CONFIG FUNCTIONS
# ==============================================================================

def load_schedule_config() -> Dict:
    """Load schedule configuration from database or JSON file"""
    default_config = {'frequency': 'none', 'time': '09:00'}

    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return default_config

            cursor.execute("SELECT config FROM schedule_config ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()

            if row:
                return row['config']
            return default_config
    else:
        # Fallback to JSON file
        if os.path.exists("schedule_config.json"):
            try:
                with open("schedule_config.json", 'r') as f:
                    return json.load(f)
            except:
                pass
        return default_config


def save_schedule_config(config: Dict):
    """Save schedule configuration to database or JSON file"""
    if USE_DATABASE:
        with get_cursor() as cursor:
            if cursor is None:
                return

            # Check if config exists
            cursor.execute("SELECT id FROM schedule_config LIMIT 1")
            row = cursor.fetchone()

            if row:
                cursor.execute("""
                    UPDATE schedule_config SET config = %s, updated_at = NOW() WHERE id = %s
                """, (Json(config), row['id']))
            else:
                cursor.execute("""
                    INSERT INTO schedule_config (config, updated_at) VALUES (%s, NOW())
                """, (Json(config),))
    else:
        # Fallback to JSON file
        with open("schedule_config.json", 'w') as f:
            json.dump(config, f)


# ==============================================================================
# MIGRATION FUNCTION
# ==============================================================================

def migrate_json_to_database():
    """
    Migrate existing JSON files to database.
    Call this once after setting up DATABASE_URL.
    """
    if not USE_DATABASE:
        print("No DATABASE_URL found - migration not needed")
        return

    print("Starting migration from JSON files to PostgreSQL...")

    # Migrate memory.json
    if os.path.exists("memory.json"):
        try:
            with open("memory.json", 'r') as f:
                memory = json.load(f)
            save_memory(memory)
            print(f"✓ Migrated memory.json ({len(memory.get('associations', {}))} associations)")
        except Exception as e:
            print(f"✗ Failed to migrate memory.json: {e}")

    # Migrate klaus_config.json
    if os.path.exists("klaus_config.json"):
        try:
            with open("klaus_config.json", 'r') as f:
                config = json.load(f)
            save_klaus_config(config)
            print(f"✓ Migrated klaus_config.json")
        except Exception as e:
            print(f"✗ Failed to migrate klaus_config.json: {e}")

    # Migrate klaus_communication_history.json
    if os.path.exists("klaus_communication_history.json"):
        try:
            with open("klaus_communication_history.json", 'r') as f:
                history = json.load(f)
            save_communication_history(history)
            print(f"✓ Migrated klaus_communication_history.json ({len(history)} entries)")
        except Exception as e:
            print(f"✗ Failed to migrate klaus_communication_history.json: {e}")

    # Migrate klaus_call_history.json
    if os.path.exists("klaus_call_history.json"):
        try:
            with open("klaus_call_history.json", 'r') as f:
                calls = json.load(f)
            save_call_history(calls)
            print(f"✓ Migrated klaus_call_history.json ({len(calls)} calls)")
        except Exception as e:
            print(f"✗ Failed to migrate klaus_call_history.json: {e}")

    # Migrate schedule_config.json
    if os.path.exists("schedule_config.json"):
        try:
            with open("schedule_config.json", 'r') as f:
                config = json.load(f)
            save_schedule_config(config)
            print(f"✓ Migrated schedule_config.json")
        except Exception as e:
            print(f"✗ Failed to migrate schedule_config.json: {e}")

    print("Migration complete!")


# Initialize database on import if DATABASE_URL is set
if USE_DATABASE:
    try:
        init_database()
    except Exception as e:
        print(f"Warning: Could not initialize database: {e}")
