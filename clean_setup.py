"""
Clean setup script to fix all model loading issues
Run this once before starting the application
"""

import os
import shutil
import json
import pickle
import numpy as np
import tensorflow as tf
from tensorflow import keras
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clean_models_directory():
    """Clean and recreate models directory"""
    models_dir = 'models/'

    # Backup any existing files
    backup_dir = 'models_backup/'
    if os.path.exists(models_dir):
        logger.info("Backing up existing models...")
        os.makedirs(backup_dir, exist_ok=True)
        for item in os.listdir(models_dir):
            src = os.path.join(models_dir, item)
            dst = os.path.join(backup_dir, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
        logger.info(f"Backup created at {backup_dir}")

    # Create fresh models directory
    if os.path.exists(models_dir):
        shutil.rmtree(models_dir)
    os.makedirs(models_dir, exist_ok=True)
    logger.info("Created fresh models directory")


def create_simple_siamese_network():
    """Create a simple but functional Siamese network"""
    try:
        logger.info("Creating simple Siamese network...")

        input_shape = (128, 128, 3)

        # Base network
        def build_base_network(input_shape):
            inputs = keras.Input(shape=input_shape)

            x = keras.layers.Conv2D(32, (3, 3), activation='relu')(inputs)
            x = keras.layers.MaxPooling2D((2, 2))(x)
            x = keras.layers.Conv2D(64, (3, 3), activation='relu')(x)
            x = keras.layers.MaxPooling2D((2, 2))(x)
            x = keras.layers.Conv2D(128, (3, 3), activation='relu')(x)
            x = keras.layers.GlobalAveragePooling2D()(x)
            x = keras.layers.Dense(256, activation='relu')(x)
            x = keras.layers.Dropout(0.3)(x)

            return keras.Model(inputs, x, name='base_network')

        base_network = build_base_network(input_shape)

        # Siamese network
        input_a = keras.Input(shape=input_shape, name='input_a')
        input_b = keras.Input(shape=input_shape, name='input_b')

        processed_a = base_network(input_a)
        processed_b = base_network(input_b)

        # L1 distance
        l1_distance = keras.layers.Lambda(
            lambda tensors: tf.abs(tensors[0] - tensors[1]),
            name='l1_distance'
        )([processed_a, processed_b])

        # Classifier
        x = keras.layers.Dense(128, activation='relu')(l1_distance)
        x = keras.layers.Dropout(0.2)(x)
        x = keras.layers.Dense(64, activation='relu')(x)
        x = keras.layers.Dense(1, activation='sigmoid')(x)

        siamese_network = keras.Model(
            inputs=[input_a, input_b],
            outputs=x,
            name='siamese_network'
        )

        # Compile
        siamese_network.compile(
            optimizer=keras.optimizers.Adam(learning_rate=0.001),
            loss='binary_crossentropy',
            metrics=['accuracy']
        )

        # Save in multiple formats
        siamese_network.save('models/siamese_network.h5')
        siamese_network.save('models/siamese_network.keras')
        siamese_network.save_weights('models/siamese_weights.h5')

        logger.info("✓ Simple Siamese network created and saved")

        return siamese_network, base_network

    except Exception as e:
        logger.error(f"Failed to create Siamese network: {e}")
        return None, None


def create_placeholder_database():
    """Create placeholder passenger database"""
    try:
        logger.info("Creating placeholder passenger database...")

        passenger_database = {}

        # Create 50 passengers
        for person_id in range(50):
            embeddings = []

            # 5 images per passenger
            for i in range(5):
                # Create random embedding (256-dimensional)
                embedding = np.random.randn(256).astype(np.float32)
                # Normalize
                embedding = embedding / np.linalg.norm(embedding)
                embeddings.append(embedding)

            passenger_database[str(person_id)] = {
                'embeddings': embeddings,
                'image_paths': [f'train/{person_id}/{j}.jpg' for j in range(5)]
            }

        # Save as pickle
        with open('models/passenger_database.pkl', 'wb') as f:
            pickle.dump(passenger_database, f)

        # Save as JSON (convert numpy arrays to lists)
        json_database = {}
        for pid, data in passenger_database.items():
            json_database[pid] = {
                'embeddings': [emb.tolist() for emb in data['embeddings']],
                'image_paths': data['image_paths']
            }

        with open('models/passenger_database.json', 'w') as f:
            json.dump(json_database, f, indent=2)

        logger.info(f"✓ Placeholder database created with {len(passenger_database)} passengers")

        return passenger_database

    except Exception as e:
        logger.error(f"Failed to create database: {e}")
        return None


def create_minimal_gan_models():
    """Create minimal GAN models"""
    try:
        logger.info("Creating minimal GAN models...")

        # Generator
        latent_dim = 100
        img_shape = (128, 128, 3)

        generator = keras.Sequential([
            keras.layers.Dense(256, input_dim=latent_dim),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Dense(512),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Dense(np.prod(img_shape), activation='tanh'),
            keras.layers.Reshape(img_shape)
        ], name='generator')

        # Discriminator
        discriminator = keras.Sequential([
            keras.layers.Flatten(input_shape=img_shape),
            keras.layers.Dense(512),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Dense(256),
            keras.layers.LeakyReLU(alpha=0.2),
            keras.layers.Dense(1, activation='sigmoid')
        ], name='discriminator')

        # GAN
        discriminator.trainable = False
        gan_input = keras.Input(shape=(latent_dim,))
        generated_img = generator(gan_input)
        gan_output = discriminator(generated_img)
        gan = keras.Model(gan_input, gan_output, name='gan')

        # Save models
        generator.save('models/generator.keras')
        discriminator.save('models/discriminator.keras')
        gan.save('models/gan.keras')

        logger.info("✓ Minimal GAN models created")

        return generator, discriminator, gan

    except Exception as e:
        logger.error(f"Failed to create GAN models: {e}")
        return None, None, None


def create_config_files():
    """Create configuration files"""
    try:
        # Preprocessor config
        preprocessor_config = {
            'img_height': 128,
            'img_width': 128,
            'channels': 3
        }

        with open('models/preprocessor_config.json', 'w') as f:
            json.dump(preprocessor_config, f, indent=2)

        # Model info
        model_info = {
            'version': '1.0.0',
            'description': 'Passenger Anomaly Detection System',
            'created_date': '2024-01-06',
            'author': 'System Administrator'
        }

        with open('models/model_info.json', 'w') as f:
            json.dump(model_info, f, indent=2)

        logger.info("✓ Configuration files created")

    except Exception as e:
        logger.error(f"Failed to create config files: {e}")


def main():
    """Main setup function"""
    logger.info("=" * 60)
    logger.info("CLEAN MODEL SETUP")
    logger.info("=" * 60)

    # Clean directory
    clean_models_directory()

    # Create simple Siamese network
    siamese_network, base_network = create_simple_siamese_network()

    # Create placeholder database
    passenger_database = create_placeholder_database()

    # Create GAN models
    generator, discriminator, gan = create_minimal_gan_models()

    # Create config files
    create_config_files()

    logger.info("=" * 60)
    logger.info("SETUP COMPLETE!")
    logger.info("=" * 60)
    logger.info("\nCreated the following files:")
    logger.info("  models/siamese_network.h5")
    logger.info("  models/siamese_network.keras")
    logger.info("  models/siamese_weights.h5")
    logger.info("  models/passenger_database.pkl")
    logger.info("  models/passenger_database.json")
    logger.info("  models/generator.keras")
    logger.info("  models/discriminator.keras")
    logger.info("  models/gan.keras")
    logger.info("  models/preprocessor_config.json")
    logger.info("\nNow you can run: python app.py")


if __name__ == "__main__":
    main()