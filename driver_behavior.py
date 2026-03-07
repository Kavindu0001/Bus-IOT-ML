import os
import cv2
import numpy as np
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
        """Load vgg16_transfer_model.keras from b_model dir."""
        try:
            if not os.path.exists(self.model_dir):
                logger.warning(f"Model directory '{self.model_dir}' not found. Using simulation mode.")
                return

            model_path = os.path.join(self.model_dir, 'vgg16_transfer_model.keras')
            if os.path.exists(model_path):
                from tensorflow.keras.models import load_model
                self.model = load_model(model_path)
                self.model_loaded = True
                logger.info("Driver behavior model (vgg16_transfer_model.keras) loaded successfully.")
            else:
                logger.warning(f"{model_path} not found. Using simulation mode.")

        except Exception as e:
            logger.error(f"Error loading driver behavior model: {e}. Falling back to simulation.")
            self.model_loaded = False

    def analyze_frame(self, frame):
        """Analyze a single frame for driver behavior"""
        if not self.model_loaded:
            return self._simulate_analysis()

        try:
            # Model expects 64x64 RGB, float32, normalised /255 then -0.5
            img = cv2.resize(frame, (64, 64))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img_array = img.astype(np.float32) / 255.0 - 0.5
            img_array = np.expand_dims(img_array, axis=0)  # (1, 64, 64, 3)

            preds = self.model.predict(img_array, verbose=0)
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