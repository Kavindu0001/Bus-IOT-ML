import os
import cv2
import numpy as np
import pickle
import logging
import random

logger = logging.getLogger(__name__)


class DriverBehaviorAnalyzer:
    def __init__(self, model_dir='b_model'):
        self.model_dir = model_dir
        self.model = None
        self.label_encoder = None
        self.labels_list = None
        self.model_loaded = False

        # Standard 10 classes for driver behavior
        self.classes = {
            'c0': 'normal driving',
            'c1': 'texting - right',
            'c2': 'talking on the phone - right',
            'c3': 'texting - left',
            'c4': 'talking on the phone - left',
            'c5': 'operating the radio',
            'c6': 'drinking',
            'c7': 'reaching behind',
            'c8': 'hair and makeup',
            'c9': 'talking to passenger'
        }

        self.load_models()

    def load_models(self):
        """Attempt to load the ensemble wrapper and metadata from b_model dir"""
        try:
            # Check if directory exists
            if not os.path.exists(self.model_dir):
                logger.warning(f"Model directory '{self.model_dir}' not found. Using simulation mode.")
                return

            # Attempt to load the ensemble model
            wrapper_path = os.path.join(self.model_dir, 'ensemble_wrapper.pkl')
            if os.path.exists(wrapper_path):
                with open(wrapper_path, 'rb') as f:
                    self.model = pickle.load(f)
                self.model_loaded = True
                logger.info("Driver behavior ensemble model loaded successfully.")
            else:
                logger.warning("ensemble_wrapper.pkl not found. Using simulation mode.")

            # Attempt to load metadata/labels if available
            labels_path = os.path.join(self.model_dir, 'labels_list_vgg16.pkl')
            if os.path.exists(labels_path):
                with open(labels_path, 'rb') as f:
                    self.labels_list = pickle.load(f)

        except Exception as e:
            logger.error(f"Error loading driver behavior models: {e}. Falling back to simulation.")
            self.model_loaded = False

    def analyze_frame(self, frame):
        """Analyze a single frame for driver behavior"""
        if not self.model_loaded:
            return self._simulate_analysis()

        try:
            # Standard preprocessing for VGG16/ResNet type models (224x224 RGB)
            from tensorflow.keras.preprocessing.image import img_to_array
            from tensorflow.keras.applications.vgg16 import preprocess_input

            img = cv2.resize(frame, (224, 224))
            img_array = img_to_array(img)
            img_array = np.expand_dims(img_array, axis=0)
            img_array = preprocess_input(img_array)

            # Predict using the loaded model
            preds = self.model.predict(img_array)
            class_idx = np.argmax(preds[0])
            class_id = f'c{class_idx}'
            confidence = float(preds[0][class_idx])

            return {
                'class_id': class_id,
                'behavior': self.classes.get(class_id, 'unknown'),
                'confidence': confidence,
                'is_anomaly': class_idx != 0  # c0 is normal driving
            }
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return self._simulate_analysis()

    def _simulate_analysis(self):
        """Simulate behavior analysis if the actual model is unavailable"""
        # 95% of the time, the driver is acting normally
        if random.random() < 0.95:
            return {
                'class_id': 'c0',
                'behavior': 'normal driving',
                'confidence': round(random.uniform(0.90, 0.99), 2),
                'is_anomaly': False
            }
        else:
            # 5% of the time, trigger a random anomaly
            c_idx = random.randint(1, 9)
            class_id = f'c{c_idx}'
            return {
                'class_id': class_id,
                'behavior': self.classes[class_id],
                'confidence': round(random.uniform(0.70, 0.95), 2),
                'is_anomaly': True
            }


# Instantiate globally
driver_analyzer = DriverBehaviorAnalyzer()