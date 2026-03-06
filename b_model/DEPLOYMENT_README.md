# Distracted Driver Detection Model - Deployment Guide

## Overview
This directory contains a trained machine learning model for detecting distracted driver behaviors from images. The model can classify images into 10 distraction categories (c0-c9).

## Model Details
- **Architecture**: VGG16 Transfer Learning with custom classification head
- **Input**: 64x64 RGB images
- **Output**: 10 distraction classes with confidence scores
- **Accuracy**: [See performance_summary.json for details]

## Deployment Options

### Option 1: Python Script
```bash
# Test the detector
python deploy_model.py

# Start REST API
python fastapi_deployment.py
```

### Option 2: Docker Container
```bash
# Create Dockerfile and requirements
python deployment_utils.py --create-docker --create-reqs

# Build Docker image
docker build -t distracted-driver-detector .

# Run container
docker run -p 8000:8000 distracted-driver-detector
```

### Option 3: Python Module
```python
from deploy_model import DistractedDriverDetector

# Initialize detector
detector = DistractedDriverDetector("best_model")

# Make prediction
result = detector.predict("path/to/image.jpg")
print(f"Prediction: {result['prediction']}")
print(f"Confidence: {result['confidence']:.2%}")
```

## API Endpoints (FastAPI)
- `GET /` - API information
- `GET /health` - Health check
- `GET /model-info` - Model information
- `POST /predict` - Single image prediction
- `POST /batch-predict` - Multiple images prediction

Access interactive documentation at: http://localhost:8000/docs

## File Structure
```
best_model/
├── model files (.h5/.keras)          # Trained model weights
├── metadata.json                     # Model metadata
├── label_encoder.pkl                 # Class label mapping
├── performance_summary.json          # Performance metrics
├── confusion_matrix.png              # Confusion matrix visualization
├── deploy_model.py                   # Main detector class
├── fastapi_deployment.py             # REST API server
└── deployment_utils.py               # Deployment utilities
```

## Requirements
- Python 3.8+
- TensorFlow 2.10+
- FastAPI 0.95+
- See requirements.txt for complete list

## Quick Test
```bash
# Test deployment setup
python deployment_utils.py --test
```

## Troubleshooting
1. **Model not loading**: Ensure all model files are in the 'best_model' directory
2. **Missing dependencies**: Run `pip install -r requirements.txt`
3. **Port in use**: Change port in fastapi_deployment.py or Dockerfile
4. **Memory issues**: Reduce batch size in predict_batch() method

## Support
For issues or questions, please refer to the model documentation or contact the development team.