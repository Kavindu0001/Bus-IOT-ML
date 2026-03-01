#!/usr/bin/env python3
"""
Setup script for Passenger Anomaly Detection System
"""

import os
import sys
import subprocess
import shutil


def create_directory_structure():
    """Create the required directory structure"""
    directories = [
        'models',
        'static/Entrance',
        'static/Exit',
        'static/css',
        'static/js',
        'templates'
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"Created directory: {directory}")

    # Create placeholder files in models directory
    placeholder_files = [
        'models/preprocessor_config.json',
        'models/__init__.py'
    ]

    for file in placeholder_files:
        if not os.path.exists(file):
            if file.endswith('.json'):
                with open(file, 'w') as f:
                    f.write('{"img_height": 128, "img_width": 128}')
            else:
                with open(file, 'w') as f:
                    f.write('# Models package\n')
            print(f"Created placeholder: {file}")


def install_dependencies():
    """Install required Python packages"""
    print("\nInstalling dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("Dependencies installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Error installing dependencies: {e}")
        sys.exit(1)


def check_mongodb():
    """Check if MongoDB is running"""
    print("\nChecking MongoDB connection...")
    try:
        import pymongo
        client = pymongo.MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
        client.server_info()
        print("✓ MongoDB is running")
        return True
    except Exception as e:
        print(f"✗ MongoDB connection failed: {e}")
        print("\nPlease make sure MongoDB is installed and running:")
        print("1. Install MongoDB: https://docs.mongodb.com/manual/installation/")
        print("2. Start MongoDB service: sudo systemctl start mongodb")
        print("3. Enable MongoDB on startup: sudo systemctl enable mongodb")
        return False


def create_environment_file():
    """Create .env file if it doesn't exist"""
    if not os.path.exists('.env'):
        print("\nCreating .env file...")
        with open('.env', 'w') as f:
            f.write('''MONGO_URI=mongodb://localhost:27017/
SECRET_KEY=your-secret-key-change-this-in-production
FLASK_ENV=development
''')
        print("Created .env file. Please update the SECRET_KEY for production.")


def copy_model_files():
    """Copy model files to models directory"""
    print("\nPlease copy your trained model files to the models/ directory:")
    print("1. generator.keras")
    print("2. discriminator.keras")
    print("3. gan.keras")
    print("4. siamese_network.keras")
    print("5. passenger_database.pkl")
    print("\nThese files should be placed in: models/")


def setup_complete():
    """Display completion message"""
    print("\n" + "=" * 50)
    print("SETUP COMPLETE!")
    print("=" * 50)
    print("\nNext steps:")
    print("1. Copy your trained model files to models/ directory")
    print("2. Start MongoDB: sudo systemctl start mongodb")
    print("3. Run the application: python app.py")
    print("4. Open browser: http://localhost:5000")
    print("\nDefault credentials:")
    print("- No authentication required for demo")
    print("\nTo start a bus turn:")
    print("1. Click 'Start Bus Turn' on home page")
    print("2. Use 'New Passenger' to capture entrance images")
    print("3. Use 'Passenger Exit' to capture exit and detect anomalies")
    print("\nFor more information, visit /about page")


def main():
    """Main setup function"""
    print("=" * 50)
    print("Passenger Anomaly Detection System - Setup")
    print("=" * 50)

    create_directory_structure()
    create_environment_file()

    # Check if requirements.txt exists
    if not os.path.exists('requirements.txt'):
        print("\nCreating requirements.txt...")
        with open('requirements.txt', 'w') as f:
            f.write('''Flask==2.3.3
flask-socketio==5.3.4
pymongo==4.5.0
opencv-python==4.8.1.78
tensorflow==2.13.0
Pillow==10.0.1
python-dotenv==1.0.0
numpy==1.24.3
eventlet==0.33.3
''')

    install_dependencies()

    if check_mongodb():
        copy_model_files()
        setup_complete()
    else:
        print("\nSetup incomplete. Please fix MongoDB issues and run setup again.")


if __name__ == "__main__":
    main()