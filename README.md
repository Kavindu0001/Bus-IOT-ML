# Bus-Research-373 🚍📊

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://www.python.org/) 
[![TensorFlow](https://img.shields.io/badge/TensorFlow-2.x-orange?logo=tensorflow)](https://www.tensorflow.org/) 
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-green?logo=mongodb)](https://www.mongodb.com/) 
[![Flask](https://img.shields.io/badge/Flask-2.x-lightgrey?logo=flask)](https://flask.palletsprojects.com/)  

---

## **Development of an IoT-Based Smart Bus System with Machine Learning-Powered Enhancements for Owner Awareness**

---

## **Abstract** 📝

Income leakage, unsafe driving behavior, and lack of operational transparency are major challenges in Sri Lanka’s private bus transportation system. Conductors and drivers often under-report ticket revenue, buses operate without real-time tracking, and owners have no independent method to verify operational data.

This research proposes a **Smart Bus Monitoring and Analytics Platform** that integrates **IoT devices, computer vision, machine learning, and cloud-based analytics** to provide:

- Real-time passenger tracking  
- Automated revenue verification  
- Anomaly detection  
- Profit forecasting  
- Driver safety monitoring  

The system combines edge-level IoT data collection, AI-based vision and learning models, and web-based dashboards to deliver a **secure, transparent, and intelligent transport management platform** for bus owners.

---

## **System Objectives** 🎯

- Prevent income leakage using automated passenger counting and AI-based anomaly detection  
- Predict profits, demand, and route performance using ML  
- Detect driver alcohol usage and unsafe behavior  
- Ensure zero data loss using offline-first IoT logging  
- Provide real-time and historical analytics to bus owners  
- Protect passenger privacy via embedding-based vision processing  

---

## System Architecture 🏗️

Here is the overall system architecture diagram for the project:

![Overall System Diagram](docs/Overall%20Diagram.png)

**Description:**  

1. **Bus IoT Layer** – ESP32 microcontroller, GPS module, passenger camera, alcohol sensor, SD card storage for offline-first logging  
2. **Cloud Backend** – Flask API for ML inference, data aggregation, alerts, and database sync  
3. **Owner Dashboard** – Web interface for live monitoring, revenue reports, anomaly alerts, and predictive insights  

---

## **Research Components (Member-Wise)** 👥

### **1. Passenger Appearance Anomaly Detection (GAN-Based)**  
**Contributor:** Sandev Jayaweera  
**Notebook:** `gan-for-passenger-appearance-anomaly-detection.ipynb`  

**Description:**  
- Detects fraud and suspicious passenger behavior using a **Generative Adversarial Network (GAN)**  
- Extracts deep visual embeddings instead of storing images  
- Flags anomalies such as repeated boarding, fare-evasion, or abnormal movement  

**Why GAN?**  
- Learns “normal” behavior without labeled fraud data  
- Provides reconstruction-based anomaly scoring  
- Ideal for unsupervised real-world surveillance  

**Technologies:** TensorFlow / Keras, OpenCV, Feature embeddings + GAN discriminator  

---

### **2. Alcohol Level Detection System** 🍷  
**Contributor:** Jaladhi  
**Notebook:** `alcohol-level-detection.ipynb`  

**Description:**  
- Detects driver alcohol influence using sensor readings from ESP32  
- Classifies driver state: sober, mildly intoxicated, unsafe to drive  
- Generates real-time alerts to bus owners  

**Technologies:** Sensor-based data acquisition, Python ML classification, Flask API  

---

### **3. Bus Travel Profit Prediction Using Machine Learning** 💰  
**Contributor:** Sanduni  
**Notebook:** `bus-travel-profit-prediction-using-ml.ipynb`  

**Description:**  
- Predicts revenue, demand, and profitability using historical and live bus data  
- Supports route planning, trip scheduling, and investment decisions  
- Outputs trip-wise revenue, time-based demand, and route/monthly profit trends  

**Technologies:** Scikit-learn, Pandas, NumPy, Regression & ensemble ML models  

---

### **4. IoT-Based Passenger Event & Revenue Collection System** 🛰️  
**Contributor:** Nandun  

**Description:**  
- Cyber-physical backbone of the system  
- Ensures **100% data integrity** for revenue and anomaly detection  

**Hardware Architecture:**  
- ESP32 central controller  
- GPS module for boarding/drop-off location & timestamps  
- Passenger camera  
- Alcohol sensor for driver monitoring  
- SD card for offline data storage  

**Offline-First Design:**  
- Data stored locally when network coverage is poor  
- Automatic upload to backend when connectivity is restored  

---

## **Database Design (MongoDB)** 🗄️

Collections:

- `passenger_embeddings` – feature embeddings for passengers  
- `journeys` – trip-level data  
- `gps_logs` – boarding/drop-off GPS data  
- `revenue_records` – collected fare records  
- `alcohol_alerts` – driver alcohol warnings  
- `anomaly_events` – passenger anomaly logs  
- `system_logs` – operational and event logs  

Indexes optimized for **real-time queries** and **historical analytics**.  

---

## **Deployment Stack** 🛠️

| Layer    | Technology                                    |
|----------|-----------------------------------------------|
| Edge     | ESP32, GPS, Camera, Alcohol Sensor, SD Card  |
| Backend  | Flask, Python                                 |
| AI Models| TensorFlow, Scikit-learn                      |
| Database | MongoDB                                       |
| Frontend | Web Dashboard                                 |

---

## **Privacy & Ethics** 🔒

- No raw passenger images are stored  
- Only numerical embeddings are saved  
- GPS and revenue data are encrypted  
- Designed using privacy-by-design principles  

---

## **How to Run (Development)** 💻

```bash
# Activate environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run backend
python app.py
