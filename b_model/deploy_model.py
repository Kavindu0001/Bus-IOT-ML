"""
Model Deployment Support Code
File: deploy_model.py
Purpose: Provides ready-to-use functions for model deployment
"""

import os
import numpy as np
from PIL import Image
import json
import pickle

class DistractedDriverDetector:
    """
    Main class for distracted driver detection model deployment.
    Handles loading, preprocessing, and prediction.
    """
    
    def __init__(self, model_dir="best_model"):
        """
        Initialize the detector with model directory.
        
        Args:
            model_dir: Path to directory containing model files
        """
        self.model_dir = model_dir
        self.model = None
        self.label_encoder = None
        self.metadata = None
        self.input_shape = (128, 128)
        
        # Load all necessary components
        self._load_components()
        
    def _load_components(self):
        """Load model and all supporting components."""
        try:
            # Load metadata
            metadata_path = os.path.join(self.model_dir, "metadata.json")
            with open(metadata_path, 'r') as f:
                self.metadata = json.load(f)
            
            # Load label encoder
            encoder_path = os.path.join(self.model_dir, "label_encoder.pkl")
            with open(encoder_path, 'rb') as f:
                self.label_encoder = pickle.load(f)
            
            # Create reverse mapping
            self.id_to_label = {v: k for k, v in self.label_encoder.items()}
            
            # Load model (adjust based on your model type)
            model_path = None
            for file in os.listdir(self.model_dir):
                if file.endswith('.h5') or file.endswith('.keras'):
                    model_path = os.path.join(self.model_dir, file)
                    break
            
            if model_path:
                from tensorflow.keras.models import load_model
                self.model = load_model(model_path)
                print(f"✓ Model loaded from {model_path}")
            else:
                print("⚠ No model file found (.h5 or .keras)")
                
        except Exception as e:
            print(f"Error loading components: {e}")
            raise
    
    def preprocess_image(self, image_path):
        """
        Preprocess an image for model prediction.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Preprocessed image array
        """
        try:
            # Load and resize image
            img = Image.open(image_path).convert('RGB')
            img = img.resize(self.input_shape)
            
            # Convert to array and normalize
            from tensorflow.keras.applications.vgg16 import preprocess_input as vgg_preprocess
            img_array = vgg_preprocess(np.array(img).astype('float32'))
            
            # Add batch dimension
            img_array = np.expand_dims(img_array, axis=0)
            
            return img_array
            
        except Exception as e:
            print(f"Error preprocessing image: {e}")
            return None
    
    def predict(self, image_path, return_confidence=True):
        """
        Make prediction on a single image.
        
        Args:
            image_path: Path to image file
            return_confidence: Whether to return confidence score
            
        Returns:
            Dictionary with prediction results
        """
        # Preprocess image
        processed_image = self.preprocess_image(image_path)
        
        if processed_image is None:
            return {"error": "Could not process image"}
        
        # Make prediction
        try:
            predictions = self.model.predict(processed_image, verbose=0)
            
            # Get top prediction
            pred_idx = np.argmax(predictions[0])
            confidence = float(np.max(predictions[0]))
            
            # Map to label
            pred_label = self.id_to_label.get(pred_idx, f"Unknown_{pred_idx}")
            
            # Prepare result
            result = {
                "prediction": pred_label,
                "confidence": confidence,
                "all_probabilities": {
                    self.id_to_label.get(i, f"Class_{i}"): float(prob)
                    for i, prob in enumerate(predictions[0])
                }
            }
            
            return result
            
        except Exception as e:
            return {"error": f"Prediction failed: {str(e)}"}
    
    def predict_batch(self, image_paths, batch_size=32):
        """
        Make predictions on a batch of images.
        
        Args:
            image_paths: List of image paths
            batch_size: Batch size for prediction
            
        Returns:
            List of prediction results
        """
        results = []
        
        # Process in batches
        for i in range(0, len(image_paths), batch_size):
            batch_paths = image_paths[i:i+batch_size]
            batch_images = []
            
            # Preprocess batch
            for path in batch_paths:
                processed = self.preprocess_image(path)
                if processed is not None:
                    batch_images.append(processed)
            
            if batch_images:
                # Stack batch
                batch_array = np.vstack(batch_images)
                
                # Predict
                batch_predictions = self.model.predict(batch_array, verbose=0)
                
                # Process results
                for j, pred in enumerate(batch_predictions):
                    pred_idx = np.argmax(pred)
                    confidence = float(np.max(pred))
                    pred_label = self.id_to_label.get(pred_idx, f"Unknown_{pred_idx}")
                    
                    results.append({
                        "image": batch_paths[j],
                        "prediction": pred_label,
                        "confidence": confidence
                    })
        
        return results
    
    def get_model_info(self):
        """Get information about the loaded model."""
        if self.metadata:
            return {
                "model_type": self.metadata.get("model_type", "Unknown"),
                "input_shape": self.metadata.get("input_shape", "Unknown"),
                "classes": list(self.label_encoder.keys()),
                "training_samples": self.metadata.get("training_samples", 0),
                "accuracy": self.metadata.get("final_val_accuracy", 0.0)
            }
        return {"error": "No metadata available"}


# Example usage function
def example_usage():
    """
    Example of how to use the DistractedDriverDetector class.
    """
    print("Example Usage:")
    print("1. Initialize detector:")
    print("   detector = DistractedDriverDetector('best_model')")
    print()
    print("2. Make single prediction:")
    print("   result = detector.predict('path/to/image.jpg')")
    print("   print(f\"Prediction: {result['prediction']}\")")
    print("   print(f\"Confidence: {result['confidence']:.2%}\")")
    print()
    print("3. Get model info:")
    print("   info = detector.get_model_info()")
    print("   print(f\"Model trained on {info['training_samples']} samples\")")
    print()
    print("4. Batch prediction:")
    print("   image_paths = ['img1.jpg', 'img2.jpg', 'img3.jpg']")
    print("   results = detector.predict_batch(image_paths)")
    print("   for res in results:")
    print("       print(f\"{res['image']}: {res['prediction']} ({res['confidence']:.2%})\")")