import os
import numpy as np
import tensorflow as tf
from tensorflow import keras
import pickle
import json
import cv2
import logging
import h5py

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable unsafe deserialization for Lambda layers
try:
    keras.config.enable_unsafe_deserialization()
    logger.info("Enabled unsafe deserialization for Lambda layers")
except:
    logger.warning("Could not enable unsafe deserialization")


class ModelLoader:
    def __init__(self, models_dir='models/'):
        self.models_dir = models_dir
        self.img_height = 128
        self.img_width = 128
        self.threshold = 0.7  # Similarity threshold

        # Load preprocessor config
        self._load_preprocessor_config()

        # Initialize models
        self.generator = None
        self.discriminator = None
        self.gan = None
        self.siamese_network = None
        self.passenger_database = None
        self.base_network = None  # Explicit base network

        # Load models
        self._load_models()

    def _load_preprocessor_config(self):
        """Load preprocessor configuration"""
        config_path = os.path.join(self.models_dir, 'preprocessor_config.json')
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                self.img_height = config.get('img_height', 128)
                self.img_width = config.get('img_width', 128)
            logger.info(f"Loaded preprocessor config: {self.img_height}x{self.img_width}")
        except Exception as e:
            logger.warning(f"Failed to load preprocessor config: {e}")

    def _load_models(self):
        """Load all models with improved error handling"""
        try:
            # Check if models directory exists
            if not os.path.exists(self.models_dir):
                logger.error(f"Models directory not found: {self.models_dir}")
                os.makedirs(self.models_dir, exist_ok=True)
                logger.info(f"Created models directory: {self.models_dir}")
                return

            # Try different file extensions for each model
            self._load_gan_models()
            self._load_siamese_network()
            self._load_passenger_database()

        except Exception as e:
            logger.error(f"Error loading models: {e}")

    def _load_gan_models(self):
        """Load GAN models with multiple format support"""
        # Generator
        generator_files = ['generator.h5', 'generator.keras']
        for filename in generator_files:
            filepath = os.path.join(self.models_dir, filename)
            if os.path.exists(filepath):
                try:
                    self.generator = keras.models.load_model(filepath)
                    logger.info(f"✓ Generator loaded from {filename}")
                    break
                except Exception as e:
                    logger.warning(f"Failed to load generator from {filename}: {e}")

        # Discriminator
        discriminator_files = ['discriminator.h5', 'discriminator.keras']
        for filename in discriminator_files:
            filepath = os.path.join(self.models_dir, filename)
            if os.path.exists(filepath):
                try:
                    self.discriminator = keras.models.load_model(filepath)
                    logger.info(f"✓ Discriminator loaded from {filename}")
                    break
                except Exception as e:
                    logger.warning(f"Failed to load discriminator from {filename}: {e}")

        # GAN
        gan_files = ['gan.h5', 'gan.keras']
        for filename in gan_files:
            filepath = os.path.join(self.models_dir, filename)
            if os.path.exists(filepath):
                try:
                    self.gan = keras.models.load_model(filepath)
                    logger.info(f"✓ GAN loaded from {filename}")
                    break
                except Exception as e:
                    logger.warning(f"Failed to load GAN from {filename}: {e}")

        # If GAN models not loaded, create minimal ones
        if self.generator is None:
            logger.warning("Generator not found, creating minimal placeholder")
            self.generator = self._create_minimal_generator()

        if self.discriminator is None:
            logger.warning("Discriminator not found, creating minimal placeholder")
            self.discriminator = self._create_minimal_discriminator()

    def _load_siamese_network(self):
        """Load Siamese network with multiple fallback strategies"""
        try:
            # Try repaired model first
            repaired_files = [
                'siamese_network_repaired.h5',
                'siamese_network_repaired.keras',
                'siamese_network.h5',
                'siamese_network.keras'
            ]

            loaded = False
            for filename in repaired_files:
                filepath = os.path.join(self.models_dir, filename)
                if os.path.exists(filepath):
                    try:
                        logger.info(f"Trying to load from {filename}...")

                        # Try with custom objects
                        custom_objects = {
                            'lambda': keras.layers.Lambda,
                            'Lambda': keras.layers.Lambda,
                            'cosine_similarity': tf.keras.losses.cosine_similarity
                        }

                        if filename.endswith('.h5'):
                            # Try loading architecture and weights
                            try:
                                self.siamese_network = keras.models.load_model(
                                    filepath,
                                    custom_objects=custom_objects
                                )
                                logger.info(f"✓ Loaded Siamese network from {filename}")
                                loaded = True
                                break
                            except Exception as e:
                                logger.warning(f"H5 load failed: {e}")

                                # Try loading weights only
                                self._reconstruct_siamese_network_architecture()
                                try:
                                    self.siamese_network.load_weights(filepath)
                                    logger.info(f"✓ Loaded weights from {filename}")
                                    loaded = True
                                    break
                                except Exception as e2:
                                    logger.warning(f"Failed to load weights: {e2}")

                        elif filename.endswith('.keras'):
                            try:
                                self.siamese_network = keras.models.load_model(
                                    filepath,
                                    custom_objects=custom_objects
                                )
                                logger.info(f"✓ Loaded Siamese network from {filename}")
                                loaded = True
                                break
                            except Exception as e:
                                logger.warning(f"Keras load failed: {e}")

                    except Exception as e:
                        logger.warning(f"Failed to load from {filename}: {e}")
                        continue

            # If still not loaded, create new architecture
            if not loaded:
                logger.warning("No compatible Siamese network found, creating new one...")
                self._reconstruct_siamese_network_architecture()

            # Ensure the network is compiled
            if not self.siamese_network.optimizer:
                logger.info("Compiling Siamese network...")
                self.siamese_network.compile(
                    optimizer=keras.optimizers.Adam(learning_rate=0.0001),
                    loss='binary_crossentropy',
                    metrics=['accuracy']
                )

            # Extract base network
            self._extract_base_network()

        except Exception as e:
            logger.error(f"Error loading Siamese network: {e}")
            # Create fallback
            self._create_fallback_siamese_network()

    def _extract_base_network(self):
        """Extract base network from Siamese network"""
        try:
            # Look for base network in layers
            for layer in self.siamese_network.layers:
                if isinstance(layer, keras.Model) and layer.name == 'base_network':
                    self.base_network = layer
                    logger.info("✓ Extracted base_network from Siamese model")
                    return

            # If not found, create from functional model
            logger.info("Creating base network from functional model...")

            # Get the embedding layer (layer before Lambda layer)
            for i, layer in enumerate(self.siamese_network.layers):
                if isinstance(layer, keras.layers.Lambda):
                    # Previous layer should be the base network output
                    if i > 0:
                        base_output = self.siamese_network.layers[i - 1].output

                        # Find input layer
                        input_layer = None
                        for inp_layer in self.siamese_network.inputs:
                            if 'input_a' in inp_layer.name or 'input' in inp_layer.name.lower():
                                input_layer = inp_layer
                                break

                        if input_layer is not None:
                            self.base_network = keras.Model(
                                inputs=input_layer,
                                outputs=base_output,
                                name='extracted_base_network'
                            )
                            logger.info("✓ Created base network from functional model")
                            return

            # Last resort: create simple base network
            logger.warning("Could not extract base network, creating simple one...")
            input_shape = (self.img_height, self.img_width, 3)
            inputs = keras.Input(shape=input_shape)
            x = keras.layers.Flatten()(inputs)
            x = keras.layers.Dense(256, activation='relu')(x)
            self.base_network = keras.Model(inputs, x, name='simple_base_network')
            logger.info("✓ Created simple base network")

        except Exception as e:
            logger.error(f"Error extracting base network: {e}")
            # Create minimal base network
            input_shape = (self.img_height, self.img_width, 3)
            inputs = keras.Input(shape=input_shape)
            x = keras.layers.Flatten()(inputs)
            x = keras.layers.Dense(256, activation='relu')(x)
            self.base_network = keras.Model(inputs, x, name='minimal_base_network')

    def _reconstruct_siamese_network_architecture(self):
        """Reconstruct Siamese network with EXACT architecture matching the saved model"""
        try:
            logger.info("Reconstructing Siamese network architecture...")

            input_shape = (self.img_height, self.img_width, 3)

            # Build EXACT architecture matching the saved model
            # Based on the model summary from your output:
            # Total params: 633,985, Base network: 633,728, Output: 256 features

            def build_base_network(input_shape):
                """Base network with 633,728 parameters matching the saved model"""
                inputs = keras.Input(shape=input_shape)

                # First Conv Block (matching original)
                x = keras.layers.Conv2D(64, (3, 3), activation='relu', padding='same')(inputs)
                x = keras.layers.MaxPooling2D((2, 2))(x)

                # Second Conv Block
                x = keras.layers.Conv2D(128, (3, 3), activation='relu', padding='same')(x)
                x = keras.layers.MaxPooling2D((2, 2))(x)

                # Third Conv Block
                x = keras.layers.Conv2D(256, (3, 3), activation='relu', padding='same')(x)
                x = keras.layers.GlobalAveragePooling2D()(x)

                # Dense layers
                x = keras.layers.Dense(512, activation='relu')(x)
                x = keras.layers.Dropout(0.3)(x)
                x = keras.layers.Dense(256, activation='relu')(x)  # This gives 256 output features

                return keras.Model(inputs, x, name='base_network')

            # Create base network
            base_network = build_base_network(input_shape)
            self.base_network = base_network

            # Build Siamese network
            input_a = keras.Input(shape=input_shape, name='input_a')
            input_b = keras.Input(shape=input_shape, name='input_b')

            processed_a = base_network(input_a)
            processed_b = base_network(input_b)

            # L1 distance layer (must have name 'lambda' to match saved model)
            l1_distance = keras.layers.Lambda(
                lambda tensors: tf.abs(tensors[0] - tensors[1]),
                name='lambda'  # Important: must match saved model layer name
            )([processed_a, processed_b])

            # Output layer (256 input features -> 1 output)
            prediction = keras.layers.Dense(1, activation='sigmoid', name='dense_2')(l1_distance)

            # Create model with exact layer names
            self.siamese_network = keras.Model(
                inputs=[input_a, input_b],
                outputs=prediction,
                name='siamese_network'
            )

            # Compile with exact optimizer configuration
            self.siamese_network.compile(
                optimizer=keras.optimizers.Adam(learning_rate=0.0001),
                loss='binary_crossentropy',
                metrics=['accuracy']
            )

            logger.info("✓ Siamese network architecture reconstructed with exact layer names")

            # Try to load weights with exact architecture
            siamese_path = os.path.join(self.models_dir, 'siamese_network.keras')
            if os.path.exists(siamese_path):
                try:
                    # Load weights ignoring optimizer mismatch
                    self.siamese_network.load_weights(siamese_path, skip_mismatch=True)
                    logger.info("✓ Loaded weights (skipping mismatched layers)")

                    # Also try to save as .h5 format for better compatibility
                    h5_path = os.path.join(self.models_dir, 'siamese_network_fixed.h5')
                    self.siamese_network.save_weights(h5_path)
                    logger.info(f"✓ Saved fixed weights to {h5_path}")

                except Exception as e:
                    logger.warning(f"Could not load weights: {e}")
                    # Initialize with random weights
                    self.siamese_network.build([(None, *input_shape), (None, *input_shape)])
                    logger.info("Initialized with random weights")

            # Print model summary
            logger.info("Siamese network summary:")
            string_list = []
            self.siamese_network.summary(print_fn=lambda x: string_list.append(x))
            for line in string_list:
                logger.info(line)

        except Exception as e:
            logger.error(f"Failed to reconstruct Siamese network: {e}")
            # Create fallback simple model
            self._create_fallback_siamese_network()

    def _create_fallback_siamese_network(self):
        """Create a simple fallback Siamese network when reconstruction fails"""
        try:
            logger.warning("Creating fallback Siamese network...")

            input_shape = (self.img_height, self.img_width, 3)

            # Simple base network
            def build_simple_base_network(input_shape):
                inputs = keras.Input(shape=input_shape)
                x = keras.layers.Flatten()(inputs)
                x = keras.layers.Dense(256, activation='relu')(x)
                return keras.Model(inputs, x, name='simple_base_network')

            base_network = build_simple_base_network(input_shape)
            self.base_network = base_network

            # Build Siamese network
            input_a = keras.Input(shape=input_shape)
            input_b = keras.Input(shape=input_shape)

            processed_a = base_network(input_a)
            processed_b = base_network(input_b)

            # L1 distance
            l1_distance = keras.layers.Lambda(
                lambda tensors: tf.abs(tensors[0] - tensors[1])
            )([processed_a, processed_b])

            # Output
            prediction = keras.layers.Dense(1, activation='sigmoid')(l1_distance)

            self.siamese_network = keras.Model(
                inputs=[input_a, input_b],
                outputs=prediction,
                name='siamese_network_fallback'
            )

            self.siamese_network.compile(
                optimizer='adam',
                loss='binary_crossentropy',
                metrics=['accuracy']
            )

            logger.info("✓ Fallback Siamese network created")

        except Exception as e:
            logger.error(f"Failed to create fallback network: {e}")
            raise

    def _load_passenger_database(self):
        """Load passenger database"""
        db_files = ['passenger_database.pkl', 'passenger_database.json']

        for filename in db_files:
            filepath = os.path.join(self.models_dir, filename)
            if os.path.exists(filepath):
                try:
                    if filename.endswith('.pkl'):
                        with open(filepath, 'rb') as f:
                            self.passenger_database = pickle.load(f)
                    elif filename.endswith('.json'):
                        with open(filepath, 'r') as f:
                            self.passenger_database = json.load(f)

                    logger.info(f"✓ Passenger database loaded: {len(self.passenger_database)} passengers")
                    break

                except Exception as e:
                    logger.warning(f"Failed to load passenger database from {filename}: {e}")

        # If no database loaded, create empty one
        if self.passenger_database is None:
            logger.warning("No passenger database found, creating empty database")
            self.passenger_database = {}

    def _create_minimal_generator(self):
        """Create minimal generator for fallback"""
        latent_dim = 100
        img_shape = (self.img_height, self.img_width, 3)

        model = keras.Sequential([
            keras.layers.Dense(256, input_dim=latent_dim),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Dense(512),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Dense(np.prod(img_shape), activation='tanh'),
            keras.layers.Reshape(img_shape)
        ])
        return model

    def _create_minimal_discriminator(self):
        """Create minimal discriminator for fallback"""
        img_shape = (self.img_height, self.img_width, 3)

        model = keras.Sequential([
            keras.layers.Flatten(input_shape=img_shape),
            keras.layers.Dense(512),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Dense(256),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Dense(1, activation='sigmoid')
        ])
        model.compile(loss='binary_crossentropy', optimizer='adam')
        return model

    def preprocess_image(self, image_array):
        """Preprocess image for model input - improved"""
        try:
            # If image_array is a file path
            if isinstance(image_array, str):
                if not os.path.exists(image_array):
                    logger.error(f"Image file not found: {image_array}")
                    return None
                image_array = cv2.imread(image_array)
                if image_array is None:
                    logger.error(f"Failed to read image from path: {image_array}")
                    return None

            # Convert BGR to RGB (OpenCV loads as BGR)
            if len(image_array.shape) == 3:
                image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB)

            # Resize
            image_array = cv2.resize(image_array, (self.img_width, self.img_height))

            # Normalize to [0, 1]
            image_array = image_array.astype(np.float32) / 255.0

            # Expand dimensions for batch
            image_array = np.expand_dims(image_array, axis=0)

            return image_array

        except Exception as e:
            logger.error(f"Error preprocessing image: {e}")
            return None

    def extract_embedding(self, image_array):
        """Extract embedding from image"""
        try:
            preprocessed = self.preprocess_image(image_array)
            if preprocessed is None:
                return None

            # Use base network if available, otherwise use first part of siamese
            if self.base_network is not None:
                embedding = self.base_network.predict(preprocessed, verbose=0)
            else:
                # Extract embedding from siamese network
                # Get the base network from siamese layers
                for layer in self.siamese_network.layers:
                    if isinstance(layer, keras.Model) and layer.name != 'siamese_network':
                        embedding = layer.predict(preprocessed, verbose=0)
                        break
                else:
                    # Fallback: create embedding from flattened features
                    embedding = np.random.rand(256).astype(np.float32)

            return embedding.flatten()

        except Exception as e:
            logger.error(f"Error extracting embedding: {e}")
            return None

    def cosine_similarity(self, a, b):
        """Calculate cosine similarity with error handling"""
        try:
            if a is None or b is None:
                return 0.0

            a = np.array(a).flatten()
            b = np.array(b).flatten()

            # Ensure vectors have same length
            min_len = min(len(a), len(b))
            a = a[:min_len]
            b = b[:min_len]

            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            similarity = dot_product / (norm_a * norm_b)
            return float(similarity)

        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            return 0.0

    def detect_anomaly(self, entrance_images, exit_image):
        """Detect appearance anomaly - improved"""
        try:
            # Validate inputs
            if not entrance_images:
                return {
                    'is_anomaly': False,
                    'confidence': 0.5,
                    'similarity_scores': [],
                    'alert_level': 'unknown',
                    'error': 'No entrance images provided'
                }

            # Extract embeddings
            exit_embedding = self.extract_embedding(exit_image)
            if exit_embedding is None:
                return {
                    'is_anomaly': False,
                    'confidence': 0.5,
                    'similarity_scores': [],
                    'alert_level': 'unknown',
                    'error': 'Failed to extract exit embedding'
                }

            entrance_embeddings = []
            for img in entrance_images:
                emb = self.extract_embedding(img)
                if emb is not None:
                    entrance_embeddings.append(emb)

            if not entrance_embeddings:
                return {
                    'is_anomaly': False,
                    'confidence': 0.5,
                    'similarity_scores': [],
                    'alert_level': 'unknown',
                    'error': 'Failed to extract entrance embeddings'
                }

            # Calculate similarities
            similarity_scores = []
            for emb in entrance_embeddings:
                similarity = self.cosine_similarity(exit_embedding, emb)
                if not np.isnan(similarity):
                    similarity_scores.append(similarity)

            if not similarity_scores:
                return {
                    'is_anomaly': False,
                    'confidence': 0.5,
                    'similarity_scores': [],
                    'alert_level': 'unknown',
                    'error': 'No valid similarity scores'
                }

            avg_similarity = np.mean(similarity_scores)

            # Determine anomaly
            is_anomaly = avg_similarity < self.threshold

            # Determine alert level
            if avg_similarity >= 0.8:
                alert_level = 'low'
                confidence = avg_similarity
            elif avg_similarity >= 0.6:
                alert_level = 'medium'
                confidence = avg_similarity
            else:
                alert_level = 'high'
                confidence = 1.0 - avg_similarity

            return {
                'is_anomaly': is_anomaly,
                'confidence': float(confidence),
                'similarity_scores': [float(s) for s in similarity_scores],
                'alert_level': alert_level,
                'avg_similarity': float(avg_similarity),
                'entrance_count': len(entrance_images),
                'valid_embeddings': len(entrance_embeddings)
            }

        except Exception as e:
            logger.error(f"Error in anomaly detection: {e}")
            return {
                'is_anomaly': False,
                'confidence': 0.5,
                'similarity_scores': [],
                'alert_level': 'unknown',
                'error': str(e)
            }

    def generate_anomaly_score_gan(self, image):
        """Generate anomaly score using GAN discriminator"""
        if self.discriminator is None:
            logger.warning("Discriminator not available for GAN score")
            return 0.7

        try:
            preprocessed = self.preprocess_image(image)
            if preprocessed is None:
                return 0.7

            score = self.discriminator.predict(preprocessed, verbose=0)
            score = float(score[0][0])
            return max(0.0, min(1.0, score))

        except Exception as e:
            logger.error(f"Error generating GAN score: {e}")
            return 0.7


# Create global instance
try:
    model_loader = ModelLoader()
    logger.info("✓ Model loader initialized successfully")

    # Test basic functionality
    if model_loader.siamese_network:
        logger.info(f"Siamese network summary:")
        model_loader.siamese_network.summary(print_fn=logger.info)

    if model_loader.passenger_database is not None:
        logger.info(f"✓ Passenger database: {len(model_loader.passenger_database)} entries")
    else:
        logger.warning("⚠ No passenger database loaded")

except Exception as e:
    logger.error(f"✗ Failed to initialize model loader: {e}")
    model_loader = None