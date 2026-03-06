"""
Deployment Utilities
File: deployment_utils.py
Purpose: Additional utilities for model deployment
"""

import os
import sys
import json
import argparse
from pathlib import Path

def setup_environment():
    """Setup environment for deployment."""
    # Add current directory to path
    sys.path.append(str(Path(__file__).parent))
    
    # Check required packages
    required_packages = ['tensorflow', 'PIL', 'numpy', 'fastapi', 'uvicorn']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"Missing packages: {', '.join(missing_packages)}")
        print("Install with: pip install " + " ".join(missing_packages))
        return False
    
    return True

def test_deployment(model_dir="best_model"):
    """Test the deployment setup."""
    try:
        from deploy_model import DistractedDriverDetector
        
        print("Testing deployment setup...")
        
        # Initialize detector
        detector = DistractedDriverDetector(model_dir)
        print("✓ Detector initialized")
        
        # Test model info
        info = detector.get_model_info()
        print(f"✓ Model info retrieved: {info['model_type']}")
        
        # Test with sample image if available
        sample_images = list(Path(model_dir).glob("*.jpg")) + list(Path(model_dir).glob("*.png"))
        
        if sample_images:
            sample_image = str(sample_images[0])
            print(f"Testing with sample image: {sample_image}")
            
            result = detector.predict(sample_image)
            if "error" not in result:
                print(f"✓ Prediction successful: {result['prediction']} ({result['confidence']:.2%})")
            else:
                print(f"✗ Prediction failed: {result['error']}")
        else:
            print("⚠ No sample images found for testing")
        
        print("\nDeployment test completed successfully!")
        return True
        
    except Exception as e:
        print(f"✗ Deployment test failed: {e}")
        return False

def create_dockerfile():
    """Create Dockerfile for containerized deployment."""
    dockerfile_lines = [
        "FROM python:3.9-slim",
        "",
        "WORKDIR /app",
        "",
        "# Install system dependencies",
        "RUN apt-get update && apt-get install -y \\",
        "    libgl1-mesa-glx \\",
        "    libglib2.0-0 \\",
        "    && rm -rf /var/lib/apt/lists/*",
        "",
        "# Copy requirements and install Python packages",
        "COPY requirements.txt .",
        "RUN pip install --no-cache-dir -r requirements.txt",
        "",
        "# Copy model files and application code",
        "COPY best_model/ ./best_model/",
        "COPY deploy_model.py .",
        "COPY fastapi_deployment.py .",
        "",
        "# Expose port",
        "EXPOSE 8000",
        "",
        "# Run the API",
        '"CMD ["uvicorn", "fastapi_deployment:app", "--host", "0.0.0.0", "--port", "8000"]'
    ]
    
    dockerfile_content = "\n".join(dockerfile_lines)
    
    with open("Dockerfile", "w") as f:
        f.write(dockerfile_content)
    
    print("✓ Dockerfile created")

def create_requirements():
    """Create requirements.txt file."""
    requirements_lines = [
        "tensorflow>=2.10.0",
        "keras>=2.10.0",
        "numpy>=1.21.0",
        "Pillow>=9.0.0",
        "fastapi>=0.95.0",
        "uvicorn>=0.21.0",
        "python-multipart>=0.0.5",
        "requests>=2.28.0",
        "scikit-learn>=1.2.0",
        "pandas>=1.5.0",
        "seaborn>=0.12.0",
        "matplotlib>=3.6.0"
    ]
    
    requirements_content = "\n".join(requirements_lines)
    
    with open("requirements.txt", "w") as f:
        f.write(requirements_content)
    
    print("✓ requirements.txt created")

def main():
    """Main function for deployment utilities."""
    parser = argparse.ArgumentParser(description="Deployment utilities for Distracted Driver Detection")
    parser.add_argument("--test", action="store_true", help="Test deployment setup")
    parser.add_argument("--create-docker", action="store_true", help="Create Dockerfile")
    parser.add_argument("--create-reqs", action="store_true", help="Create requirements.txt")
    parser.add_argument("--all", action="store_true", help="Run all setup tasks")
    
    args = parser.parse_args()
    
    if args.all or not any(vars(args).values()):
        args.test = True
        args.create_docker = True
        args.create_reqs = True
    
    if args.create_docker:
        create_dockerfile()
    
    if args.create_reqs:
        create_requirements()
    
    if args.test:
        if setup_environment():
            test_deployment()

if __name__ == "__main__":
    main()