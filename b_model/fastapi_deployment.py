"""
FastAPI Deployment Example
File: fastapi_deployment.py
Purpose: Provides REST API for model deployment
"""

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
import uvicorn
import os
import tempfile

# Import the detector class from deploy_model
try:
    from deploy_model import DistractedDriverDetector
except ImportError:
    # If deploy_model is not in the same directory
    import sys
    sys.path.append('.')
    from deploy_model import DistractedDriverDetector

app = FastAPI(
    title="Distracted Driver Detection API",
    description="API for detecting distracted driver behaviors from images",
    version="1.0.0"
)

# Initialize detector (do this once at startup)
detector = None

@app.on_event("startup")
async def startup_event():
    """Initialize the model detector on startup."""
    global detector
    try:
        detector = DistractedDriverDetector("best_model")
        print("✓ DistractedDriverDetector initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize detector: {e}")
        raise

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Distracted Driver Detection API",
        "version": "1.0.0",
        "endpoints": {
            "GET /": "This information",
            "GET /health": "Health check",
            "GET /model-info": "Get model information",
            "POST /predict": "Predict from single image",
            "POST /batch-predict": "Predict from multiple images"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model_loaded": detector is not None,
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }

@app.get("/model-info")
async def model_info():
    """Get information about the model."""
    try:
        if detector is None:
            return JSONResponse(
                content={"error": "Model not loaded"},
                status_code=503
            )
        
        info = detector.get_model_info()
        return JSONResponse(content=info)
        
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    """Endpoint for single image prediction."""
    try:
        if detector is None:
            return JSONResponse(
                content={"error": "Model not loaded"},
                status_code=503
            )
        
        # Validate file type
        if not file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
            return JSONResponse(
                content={"error": "Unsupported file format. Use JPG, PNG, GIF, or BMP"},
                status_code=400
            )
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            content = await file.read()
            tmp.write(content)
            temp_path = tmp.name
        
        try:
            # Make prediction
            result = detector.predict(temp_path)
            
            # Clean up temporary file
            os.unlink(temp_path)
            
            return JSONResponse(content=result)
            
        except Exception as e:
            # Clean up on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
            
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

@app.post("/batch-predict")
async def batch_predict(files: list[UploadFile] = File(...)):
    """Endpoint for batch image prediction."""
    try:
        if detector is None:
            return JSONResponse(
                content={"error": "Model not loaded"},
                status_code=503
            )
        
        # Limit batch size
        if len(files) > 100:
            return JSONResponse(
                content={"error": "Batch size too large. Maximum 100 files."},
                status_code=400
            )
        
        temp_paths = []
        image_paths = []
        
        try:
            # Save all uploaded files temporarily
            for file in files:
                # Validate file type
                if not file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
                    raise ValueError(f"Unsupported file format: {file.filename}")
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
                    content = await file.read()
                    tmp.write(content)
                    temp_path = tmp.name
                    temp_paths.append(temp_path)
                    image_paths.append(temp_path)
            
            # Make batch prediction
            results = detector.predict_batch(image_paths)
            
            return JSONResponse(content={
                "predictions": results,
                "total_files": len(files),
                "successful_predictions": len(results)
            })
            
        finally:
            # Clean up all temporary files
            for temp_path in temp_paths:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )