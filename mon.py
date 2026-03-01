#!/usr/bin/env python3
"""
MongoDB Auto-Setup Script for Passenger Anomaly Detection System
This script automatically sets up MongoDB with all required configurations.
"""

import os
import sys
import json
import logging
from datetime import datetime
import subprocess
import platform
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mongodb_setup.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class MongoDBSetup:
    def __init__(self):
        self.system = platform.system()
        self.mongodb_installed = False
        self.mongodb_running = False

    def check_mongodb_installation(self):
        """Check if MongoDB is installed"""
        logger.info("Checking MongoDB installation...")

        try:
            if self.system == "Windows":
                # Check if MongoDB is in PATH
                result = subprocess.run(['where', 'mongod'],
                                        capture_output=True,
                                        text=True,
                                        timeout=10)
                if result.returncode == 0:
                    self.mongodb_installed = True
                    logger.info("✓ MongoDB is installed (Windows)")

            else:  # Linux/macOS
                result = subprocess.run(['which', 'mongod'],
                                        capture_output=True,
                                        text=True,
                                        timeout=10)
                if result.returncode == 0:
                    self.mongodb_installed = True
                    logger.info("✓ MongoDB is installed (Unix)")

        except Exception as e:
            logger.error(f"Error checking MongoDB installation: {e}")

        if not self.mongodb_installed:
            logger.warning("✗ MongoDB is not installed")
            return False

        return True

    def check_mongodb_service(self):
        """Check if MongoDB service is running"""
        logger.info("Checking MongoDB service status...")

        try:
            import pymongo
            from pymongo import MongoClient

            client = MongoClient('mongodb://localhost:27017/',
                                 serverSelectionTimeoutMS=3000)
            client.server_info()
            self.mongodb_running = True
            logger.info("✓ MongoDB service is running")
            return True

        except Exception as e:
            logger.warning(f"MongoDB service not running: {e}")
            return False

    def install_mongodb_windows(self):
        """Install MongoDB on Windows"""
        logger.info("Installing MongoDB on Windows...")

        try:
            # Download MongoDB installer
            import urllib.request

            mongodb_url = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-6.0.0-signed.msi"
            installer_path = "mongodb-installer.msi"

            logger.info(f"Downloading MongoDB from {mongodb_url}")
            urllib.request.urlretrieve(mongodb_url, installer_path)

            # Install MongoDB
            logger.info("Installing MongoDB...")
            result = subprocess.run(['msiexec', '/i', installer_path, '/quiet', '/norestart'],
                                    capture_output=True,
                                    text=True,
                                    timeout=300)

            if result.returncode == 0:
                logger.info("✓ MongoDB installed successfully")
                # Add MongoDB to PATH
                os.environ['PATH'] += r';C:\Program Files\MongoDB\Server\6.0\bin'
                self.mongodb_installed = True
                return True
            else:
                logger.error(f"Failed to install MongoDB: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error installing MongoDB: {e}")

            # Try alternative method
            logger.info("Trying alternative installation method...")
            try:
                # Create MongoDB directory structure
                mongodb_dir = r"C:\mongodb"
                data_dir = os.path.join(mongodb_dir, "data")
                log_dir = os.path.join(mongodb_dir, "log")

                os.makedirs(data_dir, exist_ok=True)
                os.makedirs(log_dir, exist_ok=True)

                # Download portable MongoDB
                portable_url = "https://downloads.mongodb.com/windows/mongodb-windows-x86_64-6.0.0.zip"
                zip_path = "mongodb-portable.zip"

                logger.info("Downloading portable MongoDB...")
                urllib.request.urlretrieve(portable_url, zip_path)

                import zipfile
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(mongodb_dir)

                # Add to PATH
                bin_dir = os.path.join(mongodb_dir, "bin")
                os.environ['PATH'] += f';{bin_dir}'

                # Create config file
                config = {
                    "systemLog": {
                        "destination": "file",
                        "path": os.path.join(log_dir, "mongod.log"),
                        "logAppend": True
                    },
                    "storage": {
                        "dbPath": data_dir,
                        "journal": {
                            "enabled": True
                        }
                    },
                    "net": {
                        "bindIp": "127.0.0.1",
                        "port": 27017
                    }
                }

                config_path = os.path.join(mongodb_dir, "mongod.cfg")
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)

                self.mongodb_installed = True
                logger.info("✓ Portable MongoDB installed")
                return True

            except Exception as e2:
                logger.error(f"Alternative installation also failed: {e2}")
                return False

    def install_mongodb_linux(self):
        """Install MongoDB on Linux"""
        logger.info("Installing MongoDB on Linux...")

        try:
            # For Ubuntu/Debian
            if os.path.exists('/etc/debian_version'):
                logger.info("Installing MongoDB on Debian/Ubuntu...")

                # Import MongoDB GPG key
                subprocess.run(['wget', '-qO', '-', 'https://www.mongodb.org/static/pgp/server-6.0.asc'],
                               capture_output=True,
                               timeout=30)

                # Create list file
                with open('/etc/apt/sources.list.d/mongodb-org-6.0.list', 'w') as f:
                    f.write(
                        'deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/6.0 multiverse\n')

                # Update and install
                subprocess.run(['apt-get', 'update'], timeout=60)
                subprocess.run(['apt-get', 'install', '-y', 'mongodb-org'], timeout=300)

                self.mongodb_installed = True
                logger.info("✓ MongoDB installed on Ubuntu/Debian")
                return True

        except Exception as e:
            logger.error(f"Error installing MongoDB on Linux: {e}")
            return False

    def start_mongodb_service(self):
        """Start MongoDB service"""
        logger.info("Starting MongoDB service...")

        try:
            if self.system == "Windows":
                # Start MongoDB service
                result = subprocess.run(['sc', 'start', 'MongoDB'],
                                        capture_output=True,
                                        text=True,
                                        timeout=60)

                if result.returncode == 0:
                    logger.info("✓ MongoDB service started")
                    time.sleep(5)  # Wait for service to start
                    return True
                else:
                    # Try to start mongod directly
                    logger.info("Starting mongod directly...")

                    # Create data directory
                    data_dir = r"C:\data\db"
                    os.makedirs(data_dir, exist_ok=True)

                    # Start mongod
                    mongod_process = subprocess.Popen(['mongod', '--dbpath', data_dir],
                                                      stdout=subprocess.PIPE,
                                                      stderr=subprocess.PIPE)

                    time.sleep(5)

                    # Check if process is running
                    if mongod_process.poll() is None:
                        logger.info("✓ mongod started successfully")
                        return True
                    else:
                        logger.error("Failed to start mongod")
                        return False

            else:  # Linux/macOS
                # Start MongoDB service
                result = subprocess.run(['sudo', 'systemctl', 'start', 'mongod'],
                                        capture_output=True,
                                        text=True,
                                        timeout=60)

                if result.returncode == 0:
                    logger.info("✓ MongoDB service started")
                    time.sleep(3)
                    return True
                else:
                    # Try to start mongod directly
                    logger.info("Starting mongod directly...")

                    # Create data directory
                    data_dir = "./data/db"
                    os.makedirs(data_dir, exist_ok=True)

                    # Start mongod in background
                    mongod_process = subprocess.Popen(
                        ['mongod', '--dbpath', data_dir, '--fork', '--logpath', 'mongodb.log'],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)

                    time.sleep(3)

                    # Check if process is running
                    if mongod_process.poll() is None:
                        logger.info("✓ mongod started successfully")
                        return True
                    else:
                        logger.error("Failed to start mongod")
                        return False

        except Exception as e:
            logger.error(f"Error starting MongoDB service: {e}")
            return False

    def setup_database(self):
        """Setup the database with collections and sample data"""
        logger.info("Setting up database...")

        try:
            from config import db_config

            if db_config.connect():
                logger.info("✓ Database connection established")

                # Insert sample data
                db_config.insert_sample_data()

                # Get database stats
                stats = db_config.get_database_stats()
                if stats:
                    logger.info("Database Statistics:")
                    logger.info(f"  Database: {stats['database']}")
                    logger.info(f"  Total Size: {stats['total_size'] / 1024 / 1024:.2f} MB")

                    for collection, data in stats['collections'].items():
                        logger.info(f"  {collection}: {data['count']} documents")

                # Create backup
                backup_file = db_config.backup_database()
                if backup_file:
                    logger.info(f"✓ Initial backup created: {backup_file}")

                return True
            else:
                logger.error("✗ Failed to connect to database")
                return False

        except Exception as e:
            logger.error(f"Error setting up database: {e}")
            return False

    def create_windows_service(self):
        """Create Windows service for MongoDB"""
        if self.system != "Windows":
            return False

        logger.info("Creating Windows service for MongoDB...")

        try:
            # Check if service already exists
            result = subprocess.run(['sc', 'query', 'MongoDB'],
                                    capture_output=True,
                                    text=True,
                                    timeout=10)

            if result.returncode == 0:
                logger.info("MongoDB service already exists")
                return True

            # Create service
            mongod_path = r"C:\Program Files\MongoDB\Server\6.0\bin\mongod.exe"
            if not os.path.exists(mongod_path):
                # Try alternative path
                mongod_path = r"C:\mongodb\bin\mongod.exe"

            if os.path.exists(mongod_path):
                service_cmd = [
                    'sc', 'create', 'MongoDB',
                    f'binPath= "{mongod_path} --config "C:\mongodb\mongod.cfg" --service',
                    'start= auto',
                    'DisplayName= "MongoDB Server"'
                ]

                result = subprocess.run(service_cmd,
                                        capture_output=True,
                                        text=True,
                                        timeout=30)

                if result.returncode == 0:
                    logger.info("✓ MongoDB Windows service created")
                    return True
                else:
                    logger.error(f"Failed to create service: {result.stderr}")
            else:
                logger.error(f"MongoDB executable not found at: {mongod_path}")

        except Exception as e:
            logger.error(f"Error creating Windows service: {e}")

        return False

    def run(self):
        """Run complete MongoDB setup"""
        logger.info("=" * 60)
        logger.info("MongoDB Auto-Setup for Passenger Anomaly Detection System")
        logger.info("=" * 60)

        # Step 1: Check MongoDB installation
        if not self.check_mongodb_installation():
            logger.info("MongoDB not found, attempting installation...")

            if self.system == "Windows":
                if not self.install_mongodb_windows():
                    logger.error("Failed to install MongoDB")
                    return False
            elif self.system in ["Linux", "Darwin"]:
                if not self.install_mongodb_linux():
                    logger.error("Failed to install MongoDB")
                    return False
            else:
                logger.error(f"Unsupported operating system: {self.system}")
                return False

        # Step 2: Start MongoDB service
        if not self.check_mongodb_service():
            if not self.start_mongodb_service():
                logger.error("Failed to start MongoDB service")
                return False

        # Step 3: Create Windows service (if applicable)
        if self.system == "Windows":
            self.create_windows_service()

        # Step 4: Setup database
        if not self.setup_database():
            logger.error("Failed to setup database")
            return False

        logger.info("=" * 60)
        logger.info("✓ MongoDB Setup Completed Successfully!")
        logger.info("=" * 60)
        logger.info("\nNext Steps:")
        logger.info("1. Run the application: python run_system.py")
        logger.info("2. Open browser: http://localhost:5000")
        logger.info("3. Start using the Passenger Anomaly Detection System")

        return True


def main():
    """Main function"""
    setup = MongoDBSetup()

    try:
        success = setup.run()
        if success:
            print("\n✅ MongoDB setup completed successfully!")
            print("📁 Check 'mongodb_setup.log' for detailed logs")
        else:
            print("\n❌ MongoDB setup failed!")
            print("📁 Check 'mongodb_setup.log' for error details")

    except KeyboardInterrupt:
        print("\nSetup interrupted by user")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()