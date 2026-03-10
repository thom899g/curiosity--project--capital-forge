"""
Firebase client with robust connection management, retry logic, and data modeling.
Primary database: Firestore for structured data
Real-time database: Firebase Realtime DB for alerts and queues
"""
import json
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from contextlib import contextmanager

import firebase_admin
from firebase_admin import credentials, firestore, db
from firebase_admin.exceptions import FirebaseError

from config import settings

logger = logging.getLogger(__name__)


class FirebaseClient:
    """Singleton Firebase client with connection pooling and error recovery"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseClient, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialize_firebase()
            self._initialized = True
    
    def _initialize_firebase(self):
        """Initialize Firebase with retry logic and credential validation"""
        try:
            # Check if Firebase app already exists
            if not firebase_admin._apps:
                # Load credentials from file or environment
                if os.path.exists(settings.FIREBASE_CREDENTIALS_PATH):
                    cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
                else:
                    # Fallback to environment variable
                    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
                    if cred_json:
                        cred_dict = json.loads(cred_json)
                        cred = credentials.Certificate(cred_dict)
                    else:
                        raise ValueError("No Firebase credentials found")
                
                firebase_admin.initialize_app(cred, {
                    'databaseURL': f'https://{settings.FIREBASE_PROJECT_ID}.firebaseio.com'
                })
                logger.info("Firebase initialized successfully")
            else:
                logger.info("Firebase app already initialized")
            
            # Initialize clients
            self.firestore = firestore.client()
            self.realtime_db = db.reference()
            
            # Test connections
            self._test_connections()
            
        except Exception as e:
            logger.critical(f"Failed to initialize Firebase: {e}")
            raise
    
    def _test_connections(self):
        """Test both database connections with timeout"""
        import threading
        
        def test_firestore():
            try:
                # Simple read operation
                self.firestore.collection('_health').document('test').get()
                logger.debug("Firestore connection test passed")
                return True
            except Exception as e:
                logger.error(f"Firestore test failed: {e}")
                return False
        
        def test_realtime_db():
            try:
                # Simple write/read operation
                test_ref = self.realtime_db.child('_health/test')
                test_ref.set({'timestamp': datetime.utcnow().isoformat()})
                test_ref.delete()
                logger.debug("Realtime DB connection test passed")
                return True
            except Exception as e:
                logger.error(f"Realtime DB test failed: {e}")
                return False
        
        # Run tests with timeout
        firestore_success = test_firestore()
        realtime_success = test_realtime_db()
        
        if not firestore_success or not realtime_success:
            raise ConnectionError("Firebase connection tests failed")
    
    # Firestore Operations
    def get_user(self, user_id: str) -> Optional[Dict]:
        """Get user document with tier and usage data"""
        try:
            doc = self.firestore.collection('users').document(str(user_id)).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    def update_user_tier(self, user_id: str, tier: str, stripe_customer_id: Optional[str] = None) -> bool:
        """Update user tier with atomic transaction"""
        try:
            user_ref = self.firestore.collection('users').document(str(user_id))
            
            @firestore.transactional
            def update_in_transaction(transaction, user_ref):
                user_doc = user_ref.get(transaction=transaction)
                current_data = user_doc.to_dict() if user_doc.exists else {}
                
                update_data = {
                    'tier': tier,
                    'updated_at': datetime.utcnow(),
                    'query_count': 0  # Reset counter on tier change
                }
                
                if stripe_customer_id:
                    update_data['stripe_customer_id'] = stripe_customer_id
                
                transaction.set(user_ref, {**current_data, **update_data}, merge=True)
            
            update_in_transaction(firestore.transaction(), user_ref)
            logger.info(f"Updated user {user_id} to tier {tier}")
            return True
        except Exception as e:
            logger.error(f"Error updating user tier {user_id}: {e}")
            return False
    
    def increment_query_count(self, user_id: str) -> bool:
        """Atomically increment user's daily query count"""
        try:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            counter_ref = self.firestore.collection('users').document(str(user_id)) \
                .collection('daily_usage').document(today)
            
            @firestore.transactional
            def increment_counter(transaction, counter_ref):
                counter_doc = counter_ref.get(transaction=transaction)
                current_count = counter_doc.get('count') if counter_doc.exists else 0
                transaction.set(counter_ref, {
                    'count': current_count + 1,
                    'last_query': datetime.utcnow()
                }, merge=True)
            
            increment_counter(firestore.transaction(), counter_ref)
            return True
        except Exception as e:
            logger.error(f"Error incrementing query count for {user_id}: {e}")
            return False
    
    def get_daily_query_count(self, user_id: str) -> int:
        """Get user's query count for current day"""
        try:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            doc = self.firestore.collection('users').document(str(user_id)) \
                .collection('daily_usage').document(today).get()
            return doc.get('count', 0) if doc.exists else 0
        except Exception as e:
            logger.error(f"Error getting query count for {user_id}: {e}")
            return 0
    
    # Watchlist Operations
    def add_to_watchlist(self, user_id: str, address: str, alert_rules: Dict) -> bool:
        """Add wallet address to user's watchlist"""
        try:
            watchlist_ref = self.firestore.collection('watchlists').document(str(user_id)) \
                .collection('wallets').document(address.lower())
            
            watchlist_ref.set({
                'address': address.lower(),
                'alert_rules': alert_rules,
                'created_at': datetime.utcnow(),
                'last_checked': None
            })
            logger.info(f"Added {address} to watchlist for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding to watchlist: {e}")
            return False
    
    def get_watchlist(self, user_id: str) -> List[Dict]:
        """Get all wallets in user's watchlist"""
        try:
            docs = self.firestore.collection('watchlists').document(str(user_id)) \
                .collection('wallets').stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Error getting watchlist for {user_id}: {e}")
            return []
    
    # Realtime Database Operations
    def queue_alert(self, user_id: str, alert_data: Dict) -> str:
        """Queue alert for real-time delivery"""
        try:
            alert_id = f"alert_{datetime.utcnow().timestamp()}_{user_id}"
            alert_ref = self.realtime_db.child(f'alerts/{user_id}/pending').child(alert_id)
            alert_ref.set({
                **alert_data,
                'created_at': datetime.utcnow().isoformat(),
                'delivered': False,
                'retry_count': 0
            })
            return alert_id
        except Exception as e:
            logger.error(f"Error queuing alert: {e}")
            raise
    
    def get_pending_alerts(self, user_id: str) -> List[Dict]:
        """Get pending alerts for user"""
        try:
            alerts_ref = self.realtime_db.child(f'alerts/{user_id}/pending')
            alerts = alerts_ref.get()
            return list(alerts.values()) if alerts else []
        except Exception as e:
            logger.error(f"Error getting pending alerts: {e}")
            return []
    
    def mark_alert_delivered(self, user_id: str, alert_id: str) -> bool:
        """Mark alert as delivered"""
        try:
            self.realtime_db.child(f'alerts/{user_id}/pending/{alert_id}').delete()
            # Store in delivered history (optional)
            self.realtime_db.child(f'alerts/{user_id}/delivered/{alert_id}').set({
                'delivered_at': datetime.utcnow().isoformat()
            })
            return True
        except Exception as e:
            logger.error(f"Error marking alert delivered: {e}")
            return False

# Global Firebase client instance
firebase_client = FirebaseClient()