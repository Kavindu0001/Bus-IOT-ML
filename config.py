from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()


class MongoDBConfig:
    def __init__(self):
        # MongoDB connection
        self.mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        self.database_name = 'Passenger_Anomaly'
        self.client = None
        self.db = None

    def connect(self):
        """Establish MongoDB connection with retry logic"""
        try:
            self.client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
            self.client.server_info()  # Will throw exception if connection fails
            self.db = self.client[self.database_name]
            print(f"Connected to MongoDB: {self.database_name}")

            # Create collections with validation schemas
            self._create_collections()
            self._update_validators()   # patch validators on already-existing collections
            self._create_indexes()

            return True
        except Exception as e:
            print(f"MongoDB connection failed: {e}")
            return False

    def _create_collections(self):
        """Create collections with schema validation"""
        collections = self.db.list_collection_names()

        # passengers collection
        if 'passengers' not in collections:
            self.db.create_collection('passengers', validator={
                '$jsonSchema': {
                    'bsonType': 'object',
                    'required': ['passenger_id', 'created_at'],
                    'properties': {
                        'passenger_id': {'bsonType': 'string'},
                        'name': {'bsonType': 'string'},
                        'total_journeys': {'bsonType': 'int', 'minimum': 0},
                        'last_seen': {'bsonType': 'date'},
                        'created_at': {'bsonType': 'date'}
                    }
                }
            })

        # journeys collection
        if 'journeys' not in collections:
            self.db.create_collection('journeys', validator={
                '$jsonSchema': {
                    'bsonType': 'object',
                    'required': ['journey_id', 'bus_turn_id', 'passenger_id', 'entrance_time'],
                    'properties': {
                        'journey_id': {'bsonType': 'string'},
                        'bus_turn_id': {'bsonType': 'string'},
                        'passenger_id': {'bsonType': 'string'},
                        'entrance_time': {'bsonType': 'date'},
                        'exit_time': {'bsonType': ['date', 'null']},
                        'travel_time_seconds': {'bsonType': ['int', 'null']},
                        'date': {'bsonType': 'date'}
                    }
                }
            })

        # images collection
        if 'images' not in collections:
            self.db.create_collection('images', validator={
                '$jsonSchema': {
                    'bsonType': 'object',
                    'required': ['image_id', 'passenger_id', 'image_type', 'timestamp'],
                    'properties': {
                        'image_id': {'bsonType': 'string'},
                        'passenger_id': {'bsonType': 'string'},
                        'image_type': {'bsonType': 'string', 'enum': ['entrance', 'exit']},
                        'image_path': {'bsonType': 'string'},
                        'timestamp': {'bsonType': 'date'},
                        'journey_id': {'bsonType': 'string'}
                    }
                }
            })

        # alerts collection
        if 'alerts' not in collections:
            self.db.create_collection('alerts', validator={
                '$jsonSchema': {
                    'bsonType': 'object',
                    'required': ['alert_id', 'passenger_id', 'alert_type', 'timestamp'],
                    'properties': {
                        'alert_id': {'bsonType': 'string'},
                        'passenger_id': {'bsonType': 'string'},
                        'journey_id': {'bsonType': 'string'},
                        'alert_type': {'bsonType': 'string', 'enum': ['anomaly', 'normal']},
                        'confidence': {'bsonType': 'double', 'minimum': 0, 'maximum': 1},
                        'timestamp': {'bsonType': 'date'},
                        'image_paths': {'bsonType': 'array', 'items': {'bsonType': 'string'}}
                    }
                }
            })

        # NEW: Driver Scores Collection
        if 'driver_scores' not in collections:
            self.db.create_collection('driver_scores', validator={
                '$jsonSchema': {
                    'bsonType': 'object',
                    'required': ['bus_turn_id', 'date', 'score', 'anomalies'],
                    'properties': {
                        'bus_turn_id': {'bsonType': 'string'},
                        'date': {'bsonType': 'date'},
                        'score': {'bsonType': 'int', 'minimum': 0, 'maximum': 100},
                        'anomalies': {'bsonType': 'int', 'minimum': 0}
                    }
                }
            })

        # system_logs collection
        if 'system_logs' not in collections:
            self.db.create_collection('system_logs', validator={
                '$jsonSchema': {
                    'bsonType': 'object',
                    'required': ['log_id', 'event_type', 'timestamp'],
                    'properties': {
                        'log_id': {'bsonType': 'string'},
                        'event_type': {'bsonType': 'string'},
                        'description': {'bsonType': 'string'},
                        'timestamp': {'bsonType': 'date'},
                        'metadata': {'bsonType': 'object'}
                    }
                }
            })

    def _update_validators(self):
        """Update validators on existing collections"""
        try:
            self.db.command('collMod', 'journeys', validator={
                '$jsonSchema': {
                    'bsonType': 'object',
                    'required': ['journey_id', 'bus_turn_id', 'passenger_id', 'entrance_time'],
                    'properties': {
                        'journey_id': {'bsonType': 'string'},
                        'bus_turn_id': {'bsonType': 'string'},
                        'passenger_id': {'bsonType': 'string'},
                        'entrance_time': {'bsonType': 'date'},
                        'exit_time': {'bsonType': ['date', 'null']},
                        'travel_time_seconds': {'bsonType': ['int', 'null']},
                        'date': {'bsonType': 'date'}
                    }
                }
            }, validationLevel='moderate')
        except Exception as e:
            print(f"[_update_validators] Could not update journeys validator: {e}")

    def _create_indexes(self):
        """Create indexes for faster queries"""
        # passengers collection indexes
        self.db.passengers.create_index([('passenger_id', 1)], unique=True)
        self.db.passengers.create_index([('last_seen', -1)])

        # journeys collection indexes
        self.db.journeys.create_index([('journey_id', 1)], unique=True)
        self.db.journeys.create_index([('passenger_id', 1)])
        self.db.journeys.create_index([('bus_turn_id', 1)])
        self.db.journeys.create_index([('date', -1)])

        # images collection indexes
        self.db.images.create_index([('image_id', 1)], unique=True)
        self.db.images.create_index([('passenger_id', 1)])
        self.db.images.create_index([('timestamp', -1)])

        # alerts collection indexes
        self.db.alerts.create_index([('alert_id', 1)], unique=True)
        self.db.alerts.create_index([('passenger_id', 1)])
        self.db.alerts.create_index([('timestamp', -1)])
        self.db.alerts.create_index([('alert_type', 1)])

        # driver scores collection indexes
        self.db.driver_scores.create_index([('date', -1)])
        self.db.driver_scores.create_index([('bus_turn_id', 1)], unique=True)

        # system_logs collection indexes
        self.db.system_logs.create_index([('log_id', 1)], unique=True)
        self.db.system_logs.create_index([('timestamp', -1)])
        self.db.system_logs.create_index([('event_type', 1)])

    def get_collection(self, collection_name):
        """Get a specific collection"""
        return self.db[collection_name]

    def log_event(self, event_type, description, metadata=None):
        """Log system event"""
        log_entry = {
            'log_id': f'log_{datetime.now().strftime("%Y%m%d%H%M%S%f")}',
            'event_type': event_type,
            'description': description,
            'timestamp': datetime.now(),
            'metadata': metadata or {}
        }
        self.db.system_logs.insert_one(log_entry)

    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()

# Global MongoDB instance
db_config = MongoDBConfig()