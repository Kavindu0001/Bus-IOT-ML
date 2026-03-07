# 🚍 Bus-Research-373  
### IoT-Integrated Smart Bus Monitoring and ML-Driven Owner Awareness Platform

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://www.python.org/)  
[![TensorFlow Lite](https://img.shields.io/badge/TFLite-Edge%20Optimized-orange?logo=tensorflow)](https://www.tensorflow.org/lite)  
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-green?logo=mongodb)](https://www.mongodb.com/)  
[![Flask](https://img.shields.io/badge/Flask-Production-lightgrey?logo=flask)](https://flask.palletsprojects.com/)  

---

# Development of an IoT-Based Smart Bus System with Machine Learning-Powered Enhancements for Owner Awareness

---

## Abstract

Sri Lanka’s private bus transportation sector faces systemic challenges including revenue leakage, lack of operational transparency, unsafe driving practices, and absence of independent verification mechanisms for owners.

This research presents a **modular, IoT-integrated Smart Bus Monitoring Platform** combining:

- Edge-level embedded systems  
- Computer vision–based passenger re-identification  
- Lightweight TensorFlow Lite inference  
- Machine learning–based revenue prediction  
- Driver behavioral anomaly detection  
- Cloud-synchronized analytics dashboards  

The system operates using **embedding-based visual recognition rather than raw image storage**, ensuring privacy preservation while maintaining operational integrity.

---

## System Objectives

- Prevent income leakage through appearance-based passenger re-identification  
- Detect identity mismatches at exit using embedding similarity thresholds  
- Provide driver behavior anomaly monitoring  
- Enable profit prediction using ML regression models  
- Maintain privacy by avoiding raw facial image storage  
- Support low-resource edge deployment (≤2GB RAM systems)  
- Ensure offline data integrity via IoT storage buffering  

---

## System Architecture

### Multi-Layer Architecture Overview

### 1️⃣ Edge Layer (Bus Hardware Unit)
- Raspberry Pi 4 (2GB)  
- Camera module  
- ESP32 microcontroller  
- GPS module  
- Alcohol sensor  
- SD card (offline storage)  

### 2️⃣ AI Inference Layer
- TensorFlow Lite embedding model (128-dimensional vectors)  
- Cosine similarity–based passenger matching  
- Calibrated threshold decision engine  
- Multi-frame embedding comparison  

### 3️⃣ Backend Layer
- Flask REST API  
- Flask-SocketIO real-time communication  
- MongoDB database  
- Session-based RAM embedding storage  

### 4️⃣ Analytics & Dashboard Layer
- Real-time monitoring  
- Journey summaries  
- Driver scoring  
- Revenue analysis  
- Anomaly logs  

---

## Core Research Components

---

### 1️⃣ Passenger Appearance Re-Identification (Embedding-Based)

**Contributor:** Sandev Jayaweera  

#### Problem Addressed
Manual fare collection enables under-reporting and fraudulent exit events.  
The system verifies passenger identity at entry and exit without storing images.

#### Model Architecture
- Lightweight CNN backbone (MobileNet-based embedding model)  
- Converted to **TensorFlow Lite (FP16)**  
- Outputs **128-dimensional L2-normalized embeddings**  
- Cosine similarity used for comparison  

#### Matching Logic
1. Capture 3–5 images at entry  
2. Extract embeddings  
3. Capture 3–5 images at exit  
4. Compute all pairwise cosine similarities  
5. Calculate average similarity  
6. Compare against calibrated threshold (e.g., 0.80)  

**Decision Rule:**
- Similarity ≥ Threshold → MATCH  
- Similarity < Threshold → MISMATCH  

#### Why Embedding-Based Instead of GAN?

| GAN Approach | Embedding Approach |
|--------------|-------------------|
| Reconstruction-based anomaly scoring | Identity-focused feature vectors |
| Higher computational cost | Lightweight & edge deployable |
| Sensitive to background variations | Robust similarity-based separation |
| Harder to optimize for Raspberry Pi | TFLite optimized for CPU |

The embedding approach provided:
- Better separation margin  
- Lower false positives  
- Faster inference  
- Real-time feasibility on Raspberry Pi  

---

### 2️⃣ Driver Behavior & Alcohol Monitoring

**Contributor:** Jaladhi  

- Alcohol sensor data classification  
- Driver anomaly logging  
- Journey-based driver scoring  
- Time-window analytics  

---

### 3️⃣ Bus Travel Profit Prediction

**Contributor:** Sanduni  

- Historical revenue modeling  
- Demand forecasting  
- Route profitability prediction  
- Regression-based ML models  

---

### 4️⃣ IoT Revenue Integrity System

**Contributor:** Nandun  

- GPS timestamping of boarding & drop-off  
- Offline-first SD logging  
- ESP32 event buffering  
- Automatic backend synchronization  
- Anti-tampering verification  

---

## Machine Learning Details (Passenger Re-ID)

- **Embedding Size:** 128-Dimensional vector  
- **Similarity Metric:** Cosine Similarity  
- **Inference Backend:** TensorFlow Lite FP16  
- **Deployment Target:** Raspberry Pi 4 (2GB RAM)  

### Threshold Calibration Example
- Same Person Mean Similarity ≈ 0.93  
- Different Person Mean Similarity ≈ 0.55  
- Selected Threshold = 0.80  

---

## Database Design (MongoDB)

Collections:

- `passengers`
- `journeys`
- `alerts`
- `driver_scores`
- `gps_logs`
- `anomaly_events`
- `system_logs`

Embeddings are stored temporarily in RAM during active bus turn  
and cleared when the journey ends.

---

## Privacy & Ethics

- No permanent raw image storage  
- Only numerical embeddings stored  
- Session-based memory clearing  
- Privacy-by-design architecture  
- No biometric database retention  

---

## Deployment Stack

| Layer    | Technology |
|----------|------------|
| Edge     | Raspberry Pi 4, ESP32, Camera, GPS, Alcohol Sensor |
| Backend  | Flask, Python |
| AI       | TensorFlow Lite, Scikit-learn |
| Database | MongoDB |
| Frontend | Web Dashboard |

---

## Performance Characteristics

- Embedding extraction: ~50–120ms (CPU)  
- Multi-frame similarity decision: <300ms  
- Optimized for 2GB RAM systems  
- No GPU dependency  

---

## How to Run (Development)

```bash
# Activate environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Ensure model exists
models/embedding_model_fp16.tflite

# Run backend
python app.py
