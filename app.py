<<<<<<< HEAD
import os
import cv2
import uuid
import json
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for
from flask_socketio import SocketIO, emit
import threading
import time
from functools import wraps
import base64
import random

from config import db_config, DEBUG_MATCHING
from model_loader import (
    model_loader,
    MATCH_THRESHOLD as MODEL_MATCH_THRESHOLD,
    FALLBACK_THRESHOLD,
    STRONG_MATCH_THRESHOLD,
    PASS_RATIO_THRESHOLD,
    MATCH_MARGIN,
)

# --- ROBUST IMPORT FOR NEW BEHAVIOR ANALYZER ---
try:
    from driver_behavior import driver_analyzer

    print("Driver behavior module loaded successfully.")
except Exception as e:
    print(f"Warning: Could not import driver_behavior: {e}. Using DummyAnalyzer fallback.")


    class DummyAnalyzer:
        def analyze_frame(self, frame):
            return {'class_id': 'c0', 'behavior': 'normal driving (simulated)', 'confidence': 0.99, 'is_anomaly': False}


    driver_analyzer = DummyAnalyzer()

# ---------------- Optional native WebSocket support (flask-sock) ----------------
try:
    from flask_sock import Sock

    _FLASK_SOCK_AVAILABLE = True
except Exception:
    _FLASK_SOCK_AVAILABLE = False
# -------------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Socket.IO server
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    serve_client=True
)

# Optional native WebSocket
if _FLASK_SOCK_AVAILABLE:
    sock = Sock(app)
else:
    sock = None

# Global state
current_bus_turn = None
active_passengers = {}

# Global camera variables
camera_active = False
camera_thread = None
latest_frame = None
frame_lock = threading.Lock()


def camera_feed_generator():
    """Background thread that acquires frames from the camera, runs behavior models, etc."""
    global camera_active, latest_frame, current_bus_turn

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Warning: Cannot open camera. Using simulated feed.")
        while camera_active:
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.rectangle(img, (50, 50), (590, 430), (0, 255, 0), 2)
            cv2.putText(img, "Camera Not Available", (140, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            with frame_lock:
                latest_frame = img.copy()
            time.sleep(0.1)
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    frame_counter = 0

    while camera_active:
        ret, frame = cap.read()
        if ret:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, current_time, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            if current_bus_turn:
                cv2.putText(frame, f"Bus: {current_bus_turn['bus_turn_id']}", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                # --- Driver Behavior Analysis every 15 frames ---
                frame_counter += 1
                if frame_counter % 15 == 0:
                    try:
                        behavior_res = driver_analyzer.analyze_frame(frame)

                        # If it's an anomaly, count it and emit event
                        if behavior_res['is_anomaly']:
                            current_bus_turn['driver_anomaly_count'] += 1
                            current_bus_turn['driver_live_score'] = max(
                                0, 100 - current_bus_turn['driver_anomaly_count'] * 2
                            )
                            log_event('driver_behavior_anomaly', f"Detected: {behavior_res['behavior']}", behavior_res)

                        # Emit to frontend for UI updates
                        socketio.emit('driver_behavior_alert', {
                            'behavior': behavior_res['behavior'],
                            'confidence': behavior_res['confidence'],
                            'is_anomaly': behavior_res['is_anomaly'],
                            'live_score': current_bus_turn.get('driver_live_score', 100),
                            'timestamp': datetime.now().isoformat()
                        })
                    except Exception as e:
                        print(f"Error in behavior analysis: {e}")

            with frame_lock:
                latest_frame = frame.copy()
        else:
            print("Failed to grab frame")
            time.sleep(0.05)

        time.sleep(0.03)

    cap.release()


def get_camera_frame():
    with frame_lock:
        if latest_frame is not None:
            return latest_frame.copy()
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(img, "Camera Feed", (220, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    return img


def start_camera():
    global camera_active, camera_thread
    if not camera_active:
        camera_active = True
        camera_thread = threading.Thread(target=camera_feed_generator, name="CameraThread", daemon=True)
        camera_thread.start()
        log_event('camera_started', 'Camera feed started')
        print("Camera started")


def stop_camera():
    global camera_active, camera_thread
    if camera_active:
        camera_active = False
        if camera_thread:
            camera_thread.join(timeout=2.0)
            camera_thread = None
        log_event('camera_stopped', 'Camera feed stopped')
        print("Camera stopped")


def generate_feed():
    if not camera_active:
        start_camera()
    while True:
        frame = get_camera_frame()
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85, cv2.IMWRITE_JPEG_OPTIMIZE, 1])
        if ret:
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            time.sleep(0.05)
        time.sleep(0.033)


def log_event(event_type, description, metadata=None):
    try:
        db_config.log_event(event_type, description, metadata)
    except Exception as e:
        print(f"[log_event] Failed to log event: {e}")


def requires_bus_turn(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_bus_turn is None:
            return jsonify({'error': 'No active bus turn. Start a journey first.'}), 400
        return f(*args, **kwargs)

    return decorated_function


# ==================== HOME ====================
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/home_redirect')
def home_redirect():
    return redirect(url_for('home'))


# ==================== JOURNEY ====================
@app.route('/start_journey', methods=['POST'])
def start_journey():
    global current_bus_turn
    bus_turn_id = f"bus_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    current_bus_turn = {
        'bus_turn_id': bus_turn_id,
        'start_time': datetime.now(),
        'active': True,
        'passenger_count': 0,
        'anomaly_count': 0,
        'driver_anomaly_count': 0,  # Added for driver behavior scoring
        'driver_live_score': 100,   # Live score decreases with each anomaly
        'end_time': None
    }
    log_event('journey_started', f'Bus turn {bus_turn_id} started')
    socketio.emit('bus_turn_started', {
        'bus_turn_id': bus_turn_id,
        'start_time': current_bus_turn['start_time'].isoformat()
    })
    return jsonify(
        {'success': True, 'bus_turn_id': bus_turn_id, 'start_time': current_bus_turn['start_time'].isoformat()})


@app.route('/end_journey', methods=['POST'])
def end_journey():
    global current_bus_turn
    if current_bus_turn is None:
        return jsonify({'error': 'No active bus turn'}), 400
    try:
        end_time = datetime.now()
        current_bus_turn['end_time'] = end_time
        current_bus_turn['active'] = False

        # Calculate driver score for the journey (baseline 100, -2 points per anomaly)
        driver_anomalies = current_bus_turn.get('driver_anomaly_count', 0)
        journey_score = max(0, 100 - (driver_anomalies * 2))

        # Store score in DB
        db_config.db.driver_scores.insert_one({
            'bus_turn_id': current_bus_turn['bus_turn_id'],
            'date': datetime.now(),
            'score': journey_score,
            'anomalies': driver_anomalies
        })

        report = {
            'bus_turn_id': current_bus_turn['bus_turn_id'],
            'start_time': current_bus_turn['start_time'].isoformat(),
            'end_time': end_time.isoformat(),
            'duration_seconds': int((end_time - current_bus_turn['start_time']).total_seconds()),
            'total_passengers': current_bus_turn['passenger_count'],
            'anomalies_detected': current_bus_turn['anomaly_count'],
            'driver_anomalies': driver_anomalies,
            'driver_journey_score': journey_score,
            'active_passengers_remaining': len(active_passengers)
        }
        log_event('journey_ended', f'Bus turn {current_bus_turn["bus_turn_id"]} ended', report)
        active_passengers.clear()
        socketio.emit('journey_ended', report)
        current_bus_turn = None
        return jsonify({'success': True, 'report': report, 'message': 'Bus turn ended successfully'})
    except Exception as e:
        log_event('end_journey_error', f'Error ending journey: {str(e)}')
        return jsonify({'error': str(e)}), 500


# ==================== CAPTURE ENTRANCE / EXIT ====================
@app.route('/capture')
def capture_page():
    passenger_id = request.args.get('passenger_id', 'new')
    capture_type = request.args.get('type', 'entrance')

    if passenger_id == 'new':
        passenger_id = str(random.randint(1, 54))

    stop_camera()
    return render_template('capture.html',
                           passenger_id=passenger_id,
                           capture_type=capture_type,
                           image_count=5 if capture_type == 'entrance' else 1,
                           current_bus_turn=current_bus_turn)


@app.route('/capture_entrance_auto', methods=['POST'])
@requires_bus_turn
def capture_entrance_auto():
    """Handles auto-allocating an ID (1-54) and saving 5 entrance images"""
    try:
        if len(active_passengers) >= 54:
            return jsonify({'error': 'Bus is fully occupied (54/54 seats). No more passengers can enter.'}), 400

        active_ids = []
        for pid in active_passengers.keys():
            try:
                active_ids.append(int(pid))
            except:
                pass

        available_ids = [i for i in range(1, 55) if i not in active_ids]
        if not available_ids:
            return jsonify({'error': 'Capacity error.'}), 400

        effective_pid = str(min(available_ids))

        entrance_dir = os.path.join('static', 'Entrance', effective_pid)
        os.makedirs(entrance_dir, exist_ok=True)
        images_data, image_paths = [], []

        if 'image_data[]' in request.form:
            try:
                image_data_list = json.loads(request.form['image_data[]'])
                for i, image_data in enumerate(image_data_list[:5]):
                    if image_data:
                        if ',' in image_data:
                            _, encoded = image_data.split(',', 1)
                        else:
                            encoded = image_data
                        binary_data = base64.b64decode(encoded)
                        filename = f"entrance_{i + 1}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
                        filepath = os.path.join(entrance_dir, filename)
                        with open(filepath, 'wb') as f:
                            f.write(binary_data)
                        img = cv2.imread(filepath)
                        if img is not None:
                            images_data.append(img)
                            image_paths.append(filepath)
            except Exception as e:
                log_event('image_decode_error', f'Error decoding base64 images: {str(e)}')

        if not images_data or len(images_data) < 5:
            return jsonify({'error': 'Insufficient images captured'}), 400

        journey_id = f"journey_{effective_pid}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        passenger_name = f"Passenger {effective_pid}"

        passenger_update = {
            '$setOnInsert': {'passenger_id': effective_pid, 'name': passenger_name, 'created_at': datetime.now()},
            '$set': {'last_seen': datetime.now()},
            '$inc': {'total_journeys': 1}
        }
        db_config.db.passengers.update_one({'passenger_id': effective_pid}, passenger_update, upsert=True)

        now = datetime.now()
        journey_data = {
            'journey_id': journey_id, 'bus_turn_id': current_bus_turn['bus_turn_id'],
            'passenger_id': effective_pid, 'entrance_time': now, 'date': datetime(now.year, now.month, now.day),
            'exit_time': None, 'travel_time_seconds': None, 'status': 'active'
        }
        db_config.db.journeys.insert_one(journey_data)

        for i, img_path in enumerate(image_paths):
            db_config.db.images.insert_one({
                'image_id': str(uuid.uuid4()), 'passenger_id': effective_pid, 'image_type': 'entrance',
                'image_path': img_path.replace('static/', ''), 'timestamp': datetime.now(),
                'journey_id': journey_id, 'sequence': i + 1
            })

        # Extract embeddings at entrance time and keep them in session memory.
        # model_loader returns None safely if the model is not loaded yet.
        entrance_embeddings = (
            model_loader.extract_embeddings_batch(image_paths)
            if model_loader and model_loader.is_ready
            else []
        )
        if not entrance_embeddings:
            log_event('embedding_warning',
                      f'No entrance embeddings extracted for passenger {effective_pid}. '
                      'Model may not be loaded. Storing image paths as fallback.')

        active_passengers[effective_pid] = {
            'journey_id': journey_id,
            'entrance_time': datetime.now(),
            'entrance_images': image_paths,
            'embeddings': entrance_embeddings,  # L2-normalised 128-dim vectors (session only)
            'name': passenger_name
        }

        current_bus_turn['passenger_count'] += 1

        log_event('passenger_entered', f'Passenger {effective_pid} entered', {
            'passenger_id': effective_pid, 'journey_id': journey_id
        })
        socketio.emit('passenger_entered', {
            'passenger_id': effective_pid, 'name': passenger_name,
            'journey_id': journey_id, 'timestamp': datetime.now().isoformat()
        })

        result_txt = f"ID {effective_pid} - Image - No Anomaly Detected"

        return jsonify({
            'success': True,
            'passenger_id': effective_pid,
            'active_count': current_bus_turn['passenger_count'],
            'result_text': result_txt,
            'message': 'Seat allocated successfully.'
        })
    except Exception as e:
        log_event('capture_error', f'Error capturing entrance images: {str(e)}')
        return jsonify({'error': str(e)}), 500


@app.route('/capture_exit_auto', methods=['POST'])
@requires_bus_turn
def capture_exit_auto():
    """Handles checking 5 exit images against all active passengers via Siamese matching."""
    try:
        if not active_passengers:
            return jsonify({
                'match_found': False,
                'result_text': 'ID Unknown - Image - No matching Found',
                'message': 'No active passengers.'
            }), 200

        exit_images_data = []
        exit_paths_temp = []

        temp_dir = os.path.join('static', 'Exit', 'Temp')
        os.makedirs(temp_dir, exist_ok=True)

        if 'image_data[]' in request.form:
            try:
                image_data_list = json.loads(request.form['image_data[]'])
                for i, image_data in enumerate(image_data_list[:5]):
                    if image_data:
                        if ',' in image_data:
                            _, encoded = image_data.split(",", 1)
                        else:
                            encoded = image_data
                        binary_data = base64.b64decode(encoded)
                        filepath = os.path.join(temp_dir, f"temp_{i}_{uuid.uuid4().hex[:8]}.jpg")
                        with open(filepath, 'wb') as f:
                            f.write(binary_data)
                        img = cv2.imread(filepath)
                        if img is not None:
                            exit_images_data.append(img)
                            exit_paths_temp.append(filepath)
            except Exception as e:
                pass

        if not exit_images_data:
            return jsonify({'error': 'Failed to capture exit images'}), 400

        # --- EMBEDDING-BASED MATCHING LOGIC ---
        # Step 1: Extract embeddings for ALL exit images (not just the first).
        if model_loader and model_loader.is_ready:
            exit_embeddings = model_loader.extract_embeddings_batch(exit_images_data)
        else:
            exit_embeddings = []

        if not exit_embeddings:
            # Image decode failed for all exit images (e.g. corrupt JPEG).
            log_event('embedding_error', 'Failed to extract exit embeddings from captured images.')
            for p in exit_paths_temp:
                if os.path.exists(p):
                    os.remove(p)
            return jsonify({
                'match_found': False,
                'result_text': 'ID Unknown - Image - No matching Found',
                'message': 'Could not process exit images. Please retake the photos.'
            }), 200

        best_match_id   = None
        best_sim        = -1.0
        second_best_sim = -1.0
        best_res        = None

        # Step 2: Compare exit embeddings against every active passenger's entrance embeddings.
        for pid, pdata in active_passengers.items():
            entrance_embeddings = pdata.get('embeddings', [])

            # Fallback: re-extract from saved image paths if embeddings weren't stored
            if not entrance_embeddings:
                ent_paths = pdata.get('entrance_images', [])
                if model_loader and model_loader.is_ready and ent_paths:
                    entrance_embeddings = model_loader.extract_embeddings_batch(
                        [p for p in ent_paths if os.path.exists(p)]
                    )

            if not entrance_embeddings:
                # No usable entrance data for this passenger — skip (treat as no match)
                continue

            res     = model_loader.detect_anomaly(entrance_embeddings, exit_embeddings)
            avg_sim = res.get('avg_similarity', 0.0)

            if DEBUG_MATCHING:
                print(f"[MATCH] pid={pid:>4s}  sim={avg_sim:.4f}  "
                      f"max={res.get('max_similarity',0):.4f}  "
                      f"ratio={res.get('pass_ratio',0):.2f}  "
                      f"threshold={MODEL_MATCH_THRESHOLD:.2f}  status={res.get('status', '?')}")

            if avg_sim > best_sim:
                second_best_sim = best_sim
                best_sim        = avg_sim
                best_match_id   = pid
                best_res        = res
            elif avg_sim > second_best_sim:
                second_best_sim = avg_sim

        # Step 3: 4-rule strict match gate.
        _margin     = best_sim - second_best_sim
        _max_sim    = best_res.get('max_similarity', 0.0) if best_res else 0.0
        _pass_ratio = best_res.get('pass_ratio', 0.0)    if best_res else 0.0
        _rule1 = best_match_id is not None and best_sim >= MODEL_MATCH_THRESHOLD
        _rule2 = _max_sim    >= STRONG_MATCH_THRESHOLD
        _rule3 = _pass_ratio >= PASS_RATIO_THRESHOLD
        _rule4 = _margin     >= MATCH_MARGIN
        _match_accepted = _rule1 and _rule2 and _rule3 and _rule4

        if DEBUG_MATCHING:
            print(f"[MATCH] best_id={best_match_id}  best_sim={best_sim:.4f}  "
                  f"second={second_best_sim:.4f}  margin={_margin:.4f}")
            print(f"[MATCH] rules  R1(avg>={MODEL_MATCH_THRESHOLD})={_rule1}  "
                  f"R2(max>={STRONG_MATCH_THRESHOLD})={_rule2}  "
                  f"R3(ratio>={PASS_RATIO_THRESHOLD})={_rule3}  "
                  f"R4(margin>={MATCH_MARGIN})={_rule4}  => {'ACCEPTED' if _match_accepted else 'REJECTED'}")

        if not _match_accepted:
            for p in exit_paths_temp:
                if os.path.exists(p): os.remove(p)
            _reject_reason = (
                'avg_similarity below threshold' if not _rule1 else
                'max_similarity too low (STRONG_MATCH failed)' if not _rule2 else
                'pass_ratio too low (inconsistent pairs)' if not _rule3 else
                'margin too small (ambiguous match)'
            )
            # active_passengers is non-empty here (checked at top), so this is a MISMATCH
            return jsonify({
                'match_found':    False,
                'status':         'MISMATCH',
                'message':        'Mismatch Detected',
                'result_text':    'Mismatch Detected',
                'reject_reason':  _reject_reason,
                'similarity':     round(best_sim, 4) if best_sim >= 0 else 0.0,
                'avg_similarity': round(best_sim, 4) if best_sim >= 0 else None,
                'max_similarity': round(_max_sim, 4),
                'pass_ratio':     round(_pass_ratio, 3),
                'margin':         round(_margin, 4),
                'threshold':      MODEL_MATCH_THRESHOLD,
                'threshold_used': MODEL_MATCH_THRESHOLD,
            }), 200

        # --- MATCH FOUND: Process Exit ---
        passenger_id = best_match_id

        final_dir = os.path.join('static', 'Exit', passenger_id)
        os.makedirs(final_dir, exist_ok=True)
        exit_paths_final = []
        for i, temp_p in enumerate(exit_paths_temp):
            final_p = os.path.join(final_dir, f"exit_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
            os.rename(temp_p, final_p)
            exit_paths_final.append(final_p)

        is_anomaly_bool        = bool(best_res.get('is_anomaly', False))
        final_confidence_float = float(best_res.get('avg_similarity', 0.0))
        _exit_max_sim    = float(best_res.get('max_similarity', 0.0))
        _exit_pass_ratio = float(best_res.get('pass_ratio', 0.0))

        for i, exit_path in enumerate(exit_paths_final):
            db_config.db.images.insert_one({
                'image_id': str(uuid.uuid4()), 'passenger_id': passenger_id, 'image_type': 'exit',
                'image_path': exit_path.replace('static/', ''), 'timestamp': datetime.now(),
                'journey_id': active_passengers[passenger_id]['journey_id'], 'sequence': i + 1
            })

        exit_time = datetime.now()
        entrance_time = active_passengers[passenger_id]['entrance_time']
        travel_time = int((exit_time - entrance_time).total_seconds())

        db_config.db.journeys.update_one(
            {'journey_id': active_passengers[passenger_id]['journey_id']},
            {'$set': {'exit_time': exit_time, 'travel_time_seconds': travel_time, 'status': 'completed'}}
        )
        db_config.db.passengers.update_one({'passenger_id': passenger_id}, {'$set': {'last_seen': exit_time}})

        all_image_paths = [p.replace('static/', '') for p in
                           active_passengers[passenger_id]['entrance_images'] + exit_paths_final]

        alert_type = 'anomaly' if is_anomaly_bool else 'normal'

        alert_data = {
            'alert_id': str(uuid.uuid4()), 'passenger_id': passenger_id,
            'journey_id': active_passengers[passenger_id]['journey_id'],
            'alert_type': alert_type,
            'confidence': final_confidence_float, 'timestamp': datetime.now(),
            'image_paths': all_image_paths,
            'similarity_scores': [float(s) for s in best_res.get('similarity_scores', [])],
            'alert_level': best_res.get('alert_level', 'LOW')
        }
        alert_result = db_config.db.alerts.insert_one(alert_data)

        if is_anomaly_bool:
            current_bus_turn['anomaly_count'] += 1

        # Free up the seat
        passenger_data = active_passengers.pop(passenger_id, {'name': 'Unknown'})
        current_bus_turn['passenger_count'] -= 1

        log_event('passenger_exited', f'Passenger {passenger_id} exited', {
            'passenger_id':   passenger_id,
            'anomaly':        is_anomaly_bool,
            'avg_similarity': round(final_confidence_float, 4),
            'max_similarity': round(_exit_max_sim, 4),
            'pass_ratio':     round(_exit_pass_ratio, 3),
            'best_sim':       round(best_sim, 4),
            'second_best':    round(second_best_sim, 4),
            'margin':         round(_margin, 4),
            'threshold':      MODEL_MATCH_THRESHOLD,
            'travel_time':    travel_time,
        })

        socketio.emit('passenger_exit', {
            'passenger_id': passenger_id, 'name': passenger_data['name'],
            'anomaly': is_anomaly_bool, 'confidence': final_confidence_float,
            'travel_time': travel_time, 'timestamp': datetime.now().isoformat(),
            'alert_id': str(alert_result.inserted_id)
        })

        # Format Result Text per user request
        if is_anomaly_bool:
            result_txt = f"ID {passenger_id} - Image - Anomaly Detected"
        else:
            result_txt = f"ID {passenger_id} - Image - No Anomaly Detected"

        return jsonify({
            'success':          True,
            'match_found':      True,
            'passenger_id':     passenger_id,
            'anomaly':          is_anomaly_bool,
            'confidence':       final_confidence_float,
            'active_count':     current_bus_turn['passenger_count'],
            'result_text':      result_txt,
            # ── matching metadata ──
            'match_status':     best_res.get('status', 'MATCH'),
            'avg_similarity':   round(final_confidence_float, 4),
            'max_similarity':   round(_exit_max_sim, 4),
            'pass_ratio':       round(_exit_pass_ratio, 3),
            'similarity_pct':   round(final_confidence_float * 100, 1),
            'best_sim':         round(best_sim, 4),
            'second_best_sim':  round(second_best_sim, 4),
            'margin':           round(_margin, 4),
            'threshold_used':   MODEL_MATCH_THRESHOLD,
            'model_backend':    'Histogram' if (model_loader and model_loader.using_fallback) else 'TFLite',
        })
    except Exception as e:
        log_event('exit_error', f'Error processing auto exit: {str(e)}')
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# RAM-ONLY PASSENGER RE-IDENTIFICATION API
# ==============================================================================
# These routes implement a pure in-memory passenger flow:
#
#   POST /api/passenger/enter   — decode base64 images → extract embeddings
#                                  → store under a new UUID in active_passengers
#
#   POST /api/passenger/exit    — decode base64 images → extract embeddings
#                                  → compare against ALL active passengers
#                                  → return best match + anomaly decision
#                                  → remove matched passenger from memory
#
#   POST /api/passenger/exit/<passenger_uuid>
#                               — same as above but match against ONE specific
#                                  passenger (useful if UUID is known at exit)
#
#   GET  /api/passenger/active  — list all in-memory passengers (debug / UI)
#
#   POST /api/bus/end_turn      — clear entire active_passengers dict
#
# Data never touches disk.  Embeddings are numpy float32 arrays in RAM only.
# Active passenger dict is wiped automatically on end_journey() as well.
# ==============================================================================

# ─── helpers ────────────────────────────────────────────────────────────────

def _decode_b64_images(form_field: str) -> list:
    """
    Decode a JSON-encoded list of base64 image strings from a form field.

    Accepts both  'data:image/jpeg;base64,<data>'  and  plain '<data>'  strings.

    Returns a list of BGR numpy arrays (decoded with cv2.imdecode).
    Silently skips any entry that cannot be decoded — caller checks length.
    """
    frames = []
    raw = request.form.get(form_field)
    if not raw:
        return frames
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Try treating it as a single base64 string
        items = [raw]

    for item in items:
        if not item:
            continue
        try:
            # Strip the data-URI header if present
            encoded = item.split(',', 1)[1] if ',' in item else item
            binary  = base64.b64decode(encoded)
            arr     = np.frombuffer(binary, dtype=np.uint8)
            img     = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR
            if img is not None and img.size > 0:
                frames.append(img)
        except Exception:
            pass  # skip corrupt frames silently
    return frames


def _extract_or_fail(frames: list) -> tuple:
    """
    Extract embeddings for a list of BGR frames using model_loader.

    Returns (embeddings_list, error_str).
    embeddings_list is [] and error_str is non-empty on failure.
    """
    if not frames:
        return [], 'No valid frames decoded from the uploaded images.'
    if model_loader is None:
        return [], 'model_loader is not initialised.'

    embeddings = model_loader.extract_embeddings_batch(frames)
    if not embeddings:
        return [], 'Embedding extraction returned no results. Check image quality.'
    return embeddings, ''


# ─── POST /api/passenger/enter ──────────────────────────────────────────────

@app.route('/api/passenger/enter', methods=['POST'])
@requires_bus_turn
def api_passenger_enter():
    """
    Register a new passenger at the bus entrance.

    Expected form fields:
        image_data[]  – JSON-encoded list of 3–5 base64 JPEG strings

    Returns JSON:
        {
            "success": true,
            "passenger_uuid": "a1b2c3...",
            "embeddings_stored": 5,
            "active_count": 12,
            "bus_turn_id": "bus_20260302_...",
            "timestamp": "2026-03-02T..."
        }
    """
    try:
        # ── 1. Decode images (RAM only — nothing written to disk) ──────────
        frames = _decode_b64_images('image_data[]')
        if not frames:
            return jsonify({
                'success': False,
                'error': 'No images received. Send 3–5 JPEG frames in image_data[].'
            }), 400

        if len(frames) < 3:
            return jsonify({
                'success': False,
                'error': f'Only {len(frames)} image(s) decoded. Need at least 3 for reliable matching.'
            }), 400

        # ── 2. Extract embeddings ──────────────────────────────────────────
        embeddings, err = _extract_or_fail(frames)
        if err:
            return jsonify({'success': False, 'error': err}), 422

        # ── 3. Assign UUID and store in RAM ────────────────────────────────
        passenger_uuid  = str(uuid.uuid4())
        now             = datetime.now()
        journey_id      = f"journey_{passenger_uuid[:8]}_{now.strftime('%Y%m%d%H%M%S')}"

        active_passengers[passenger_uuid] = {
            'passenger_uuid': passenger_uuid,
            'journey_id':     journey_id,
            'bus_turn_id':    current_bus_turn['bus_turn_id'],
            'entrance_time':  now,
            # L2-normalised numpy arrays — stored in RAM, never on disk
            'embeddings':     embeddings,
            'embedding_count': len(embeddings),
            'status':         'active',
        }

        # ── 4. Update bus-turn counter ─────────────────────────────────────
        current_bus_turn['passenger_count'] += 1

        # ── 5. Emit live update to dashboard ──────────────────────────────
        socketio.emit('passenger_entered', {
            'passenger_uuid': passenger_uuid,
            'journey_id':     journey_id,
            'timestamp':      now.isoformat(),
            'active_count':   len(active_passengers),
        })

        log_event('passenger_entered', f'UUID={passenger_uuid[:8]} entered — '
                  f'{len(embeddings)} embeddings stored.')

        return jsonify({
            'success':          True,
            'passenger_uuid':   passenger_uuid,
            'journey_id':       journey_id,
            'embeddings_stored': len(embeddings),
            'active_count':     len(active_passengers),
            'bus_turn_id':      current_bus_turn['bus_turn_id'],
            'timestamp':        now.isoformat(),
            # Hint for the frontend: display short ID to operator
            'display_id':       passenger_uuid[:8].upper(),
        })

    except Exception as exc:
        log_event('enter_error', f'api_passenger_enter error: {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 500


# ─── POST /api/passenger/exit  (scan all passengers) ────────────────────────

@app.route('/api/passenger/exit', methods=['POST'])
@requires_bus_turn
def api_passenger_exit():
    """
    Process a passenger exit by comparing exit images against ALL active
    passengers and selecting the best match.

    Expected form fields:
        image_data[]  – JSON-encoded list of 3–5 base64 JPEG strings

    Returns JSON:
        {
            "success": true,
            "match_found": true,
            "passenger_uuid": "a1b2c3...",
            "display_id": "A1B2C3D4",
            "is_anomaly": false,
            "avg_similarity": 0.87,
            "alert_level": "low",
            "match_confidence": 0.87,
            "result_text": "ID A1B2C3D4 - Image - No Anomaly Detected",
            "travel_time_seconds": 312,
            "active_count": 11
        }
    """
    try:
        # ── 0. Guard: need active passengers ──────────────────────────────
        if not active_passengers:
            return jsonify({
                'success':     False,
                'match_found': False,
                'result_text': 'No active passengers on this bus turn.',
            }), 200

        # ── 1. Decode exit images (RAM only) ───────────────────────────────
        frames = _decode_b64_images('image_data[]')
        if not frames:
            return jsonify({
                'success': False,
                'error': 'No images received. Send 3–5 JPEG frames in image_data[].'
            }), 400

        # ── 2. Extract exit embeddings ─────────────────────────────────────
        exit_embeddings, err = _extract_or_fail(frames)
        if err:
            # Embedding failure = safe default: treat as no match
            log_event('exit_embedding_fail', err)
            return jsonify({
                'success':     True,
                'match_found': False,
                'result_text': 'ID Unknown - Image - No matching Found',
                'error_detail': err,
            }), 200

        # ── 3. Compare against every active passenger ──────────────────────
        best_uuid       = None
        best_sim        = -1.0
        second_best_sim = -1.0
        best_result     = None

        for p_uuid, pdata in active_passengers.items():
            ent_embs = pdata.get('embeddings', [])
            if not ent_embs:
                continue  # no entrance embeddings — skip safely

            res = model_loader.detect_anomaly(ent_embs, exit_embeddings)
            sim = res.get('avg_similarity', 0.0)

            if sim > best_sim:
                second_best_sim = best_sim
                best_sim        = sim
                best_uuid       = p_uuid
                best_result     = res
            elif sim > second_best_sim:
                second_best_sim = sim

        # ── 4. Threshold decision ──────────────────────────────────────────
        # Use the threshold that matches the active backend (ML or histogram)
        active_threshold = (
            FALLBACK_THRESHOLD
            if getattr(model_loader, 'using_fallback', False)
            else MODEL_MATCH_THRESHOLD
        )

        _margin     = best_sim - second_best_sim
        _max_sim    = best_result.get('max_similarity', 0.0) if best_result else 0.0
        _pass_ratio = best_result.get('pass_ratio', 0.0)    if best_result else 0.0
        _api_r1 = best_uuid is not None and best_sim >= active_threshold
        _api_r2 = _max_sim    >= STRONG_MATCH_THRESHOLD
        _api_r3 = _pass_ratio >= PASS_RATIO_THRESHOLD
        _api_r4 = _margin     >= MATCH_MARGIN
        _api_match = _api_r1 and _api_r2 and _api_r3 and _api_r4

        if not _api_match:
            _reject_reason = (
                'avg_similarity below threshold' if not _api_r1 else
                'max_similarity too low (STRONG_MATCH failed)' if not _api_r2 else
                'pass_ratio too low (inconsistent pairs)' if not _api_r3 else
                'margin too small (ambiguous match)'
            )
            return jsonify({
                'success':        True,
                'match_found':    False,
                'best_sim':       round(best_sim, 4) if best_sim >= 0 else None,
                'max_similarity': round(_max_sim, 4),
                'pass_ratio':     round(_pass_ratio, 3),
                'margin':         round(_margin, 4),
                'threshold':      active_threshold,
                'reject_reason':  _reject_reason,
                'result_text':    'ID Unknown - Image - No matching Found',
            }), 200

        confidence   = float(best_result.get('avg_similarity', best_sim))
        exit_time    = datetime.now()
        travel_secs  = int((exit_time - pdata['entrance_time']).total_seconds())
        display_id   = best_uuid[:8].upper()

        result_text = (
            f"ID {display_id} - Image - Anomaly Detected"
            if is_anomaly
            else f"ID {display_id} - Image - No Anomaly Detected"
        )

        # ── 6. Remove passenger from RAM (session over for this person) ────
        del active_passengers[best_uuid]
        current_bus_turn['passenger_count'] = max(0, current_bus_turn['passenger_count'] - 1)
        if is_anomaly:
            current_bus_turn['anomaly_count'] += 1

        # ── 7. Emit live update ────────────────────────────────────────────
        socketio.emit('passenger_exit', {
            'passenger_uuid': best_uuid,
            'display_id':     display_id,
            'is_anomaly':     is_anomaly,
            'avg_similarity': round(best_sim, 4),
            'alert_level':    alert_level,
            'travel_time':    travel_secs,
            'timestamp':      exit_time.isoformat(),
            'active_count':   len(active_passengers),
        })

        log_event('passenger_exited',
                  f'UUID={best_uuid[:8]} exited — sim={best_sim:.3f} '
                  f'anomaly={is_anomaly} travel={travel_secs}s', {
                      'avg_similarity': round(best_sim, 4),
                      'max_similarity': round(_max_sim, 4),
                      'pass_ratio':     round(_pass_ratio, 3),
                      'best_sim':       round(best_sim, 4),
                      'second_best':    round(second_best_sim, 4),
                      'margin':         round(_margin, 4),
                      'threshold':      active_threshold,
                  })

        return jsonify({
            'success':            True,
            'match_found':        True,
            'passenger_uuid':     best_uuid,
            'journey_id':         pdata.get('journey_id'),
            'display_id':         display_id,
            'is_anomaly':         is_anomaly,
            'avg_similarity':     round(best_sim, 4),
            'max_similarity':     round(_max_sim, 4),
            'pass_ratio':         round(_pass_ratio, 3),
            'similarity_scores':  [round(s, 4) for s in best_result.get('similarity_scores', [])],
            'alert_level':        alert_level,
            'match_confidence':   round(confidence, 4),
            'threshold_used':     active_threshold,
            'best_sim':           round(best_sim, 4),
            'second_best_sim':    round(second_best_sim, 4),
            'margin':             round(_margin, 4),
            'result_text':        result_text,
            'travel_time_seconds': travel_secs,
            'active_count':        len(active_passengers),
            'timestamp':           exit_time.isoformat(),
        })

    except Exception as exc:
        log_event('exit_error', f'api_passenger_exit error: {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 500


# ─── POST /api/passenger/exit/<passenger_uuid>  (match one specific person) ─

@app.route('/api/passenger/exit/<passenger_uuid>', methods=['POST'])
@requires_bus_turn
def api_passenger_exit_by_id(passenger_uuid):
    """
    Compare exit images against ONE known passenger UUID.

    Useful when the operator scans a ticket / QR code at exit and already
    knows which passenger should be leaving.

    Returns the same JSON shape as POST /api/passenger/exit.
    """
    try:
        if passenger_uuid not in active_passengers:
            return jsonify({
                'success':     False,
                'match_found': False,
                'result_text': f'UUID {passenger_uuid[:8]} not found in active passengers.',
            }), 404

        frames = _decode_b64_images('image_data[]')
        exit_embeddings, err = _extract_or_fail(frames)
        if err:
            return jsonify({
                'success':     True,
                'match_found': False,
                'result_text': 'ID Unknown - Image - No matching Found',
                'error_detail': err,
            }), 200

        pdata    = active_passengers[passenger_uuid]
        ent_embs = pdata.get('embeddings', [])

        if not ent_embs:
            return jsonify({
                'success': False,
                'error':   'No entrance embeddings stored for this passenger.',
            }), 422

        result      = model_loader.detect_anomaly(ent_embs, exit_embeddings)
        avg_sim     = float(result.get('avg_similarity', 0.0))
        max_sim     = float(result.get('max_similarity', 0.0))
        pass_ratio  = float(result.get('pass_ratio', 0.0))
        alert_level = result.get('alert_level', 'high')

        # Rules 1-3 (no margin: only one candidate for targeted exit)
        _t_threshold  = (
            FALLBACK_THRESHOLD if getattr(model_loader, 'using_fallback', False)
            else MODEL_MATCH_THRESHOLD
        )
        _t_r1 = avg_sim    >= _t_threshold
        _t_r2 = max_sim    >= STRONG_MATCH_THRESHOLD
        _t_r3 = pass_ratio >= PASS_RATIO_THRESHOLD
        _t_match = _t_r1 and _t_r2 and _t_r3

        if not _t_match:
            _t_reason = (
                'avg_similarity below threshold' if not _t_r1 else
                'max_similarity too low' if not _t_r2 else
                'pass_ratio too low'
            )
            log_event('exit_mismatch',
                      f'UUID={passenger_uuid[:8]} targeted exit REJECTED — {_t_reason}', {
                          'avg_similarity': round(avg_sim, 4),
                          'max_similarity': round(max_sim, 4),
                          'pass_ratio':     round(pass_ratio, 3),
                          'threshold':      _t_threshold,
                      })
            return jsonify({
                'success':        True,
                'match_found':    False,
                'result_text':    f'ID {passenger_uuid[:8].upper()} - Appearance Mismatch Detected',
                'reject_reason':  _t_reason,
                'avg_similarity': round(avg_sim, 4),
                'max_similarity': round(max_sim, 4),
                'pass_ratio':     round(pass_ratio, 3),
                'threshold_used': _t_threshold,
            }), 200

        is_anomaly  = bool(result.get('is_anomaly', False))
        confidence  = float(result.get('avg_similarity', avg_sim))
        exit_time   = datetime.now()
        travel_secs = int((exit_time - pdata['entrance_time']).total_seconds())
        display_id  = passenger_uuid[:8].upper()

        result_text = (
            f"ID {display_id} - Image - Anomaly Detected"
            if is_anomaly
            else f"ID {display_id} - Image - No Anomaly Detected"
        )

        # Remove from RAM
        del active_passengers[passenger_uuid]
        current_bus_turn['passenger_count'] = max(0, current_bus_turn['passenger_count'] - 1)
        if is_anomaly:
            current_bus_turn['anomaly_count'] += 1

        socketio.emit('passenger_exit', {
            'passenger_uuid': passenger_uuid,
            'display_id':     display_id,
            'is_anomaly':     is_anomaly,
            'avg_similarity': round(avg_sim, 4),
            'alert_level':    alert_level,
            'travel_time':    travel_secs,
            'timestamp':      exit_time.isoformat(),
            'active_count':   len(active_passengers),
        })

        log_event('passenger_exited',
                  f'UUID={passenger_uuid[:8]} (targeted) exited — '
                  f'sim={avg_sim:.3f} anomaly={is_anomaly}', {
                      'avg_similarity': round(avg_sim, 4),
                      'max_similarity': round(max_sim, 4),
                      'pass_ratio':     round(pass_ratio, 3),
                      'threshold':      _t_threshold,
                  })

        return jsonify({
            'success':            True,
            'match_found':        True,
            'passenger_uuid':     passenger_uuid,
            'journey_id':         pdata.get('journey_id'),
            'display_id':         display_id,
            'is_anomaly':         is_anomaly,
            'avg_similarity':     round(avg_sim, 4),
            'max_similarity':     round(max_sim, 4),
            'pass_ratio':         round(pass_ratio, 3),
            'similarity_scores':  [round(s, 4) for s in result.get('similarity_scores', [])],
            'alert_level':        alert_level,
            'match_confidence':   round(confidence, 4),
            'threshold_used':     _t_threshold,
            'result_text':        result_text,
            'travel_time_seconds': travel_secs,
            'active_count':        len(active_passengers),
            'timestamp':           exit_time.isoformat(),
        })

    except Exception as exc:
        log_event('exit_error', f'api_passenger_exit_by_id error: {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 500


# ─── GET /api/passenger/active ───────────────────────────────────────────────

@app.route('/api/passenger/active', methods=['GET'])
def api_active_passengers_detail():
    """
    Return a summary of all passengers currently in RAM.

    Each entry shows the UUID, display ID, journey ID, boarding time,
    how many embeddings are stored, and elapsed time on the bus.
    """
    now     = datetime.now()
    summary = []
    for p_uuid, pdata in active_passengers.items():
        elapsed = int((now - pdata['entrance_time']).total_seconds())
        summary.append({
            'passenger_uuid':  p_uuid,
            'display_id':      p_uuid[:8].upper(),
            'journey_id':      pdata.get('journey_id'),
            'bus_turn_id':     pdata.get('bus_turn_id'),
            'entrance_time':   pdata['entrance_time'].isoformat(),
            'elapsed_seconds': elapsed,
            'embeddings_stored': pdata.get('embedding_count', len(pdata.get('embeddings', []))),
            'status':          pdata.get('status', 'active'),
        })

    return jsonify({
        'active_count': len(summary),
        'passengers':   summary,
        'bus_turn_id':  current_bus_turn['bus_turn_id'] if current_bus_turn else None,
        'timestamp':    now.isoformat(),
    })


# ─── POST /api/bus/end_turn ───────────────────────────────────────────────────

@app.route('/api/bus/end_turn', methods=['POST'])
def api_bus_end_turn():
    """
    Clear all in-memory passenger state for the current bus turn.

    Call this when the bus completes its route and all passengers should
    have exited.  Any passengers still in active_passengers are logged as
    'did not exit' and then cleared.

    This is INDEPENDENT of end_journey() (which also clears the dict) —
    you can call either one depending on your frontend flow.
    """
    global current_bus_turn
    try:
        remaining = list(active_passengers.keys())
        count     = len(remaining)

        if remaining:
            log_event('bus_turn_force_clear',
                      f'{count} passenger(s) still in RAM at turn end: '
                      + ', '.join(p[:8] for p in remaining))

        # Wipe all session embeddings from RAM
        active_passengers.clear()

        if current_bus_turn:
            current_bus_turn['active'] = False

        socketio.emit('bus_turn_cleared', {
            'cleared_count': count,
            'timestamp':     datetime.now().isoformat(),
        })

        return jsonify({
            'success':         True,
            'cleared_count':   count,
            'did_not_exit':    [p[:8].upper() for p in remaining],
            'timestamp':       datetime.now().isoformat(),
        })

    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


# ==================== RESULT & DASHBOARD ====================
@app.route('/result/<passenger_id>')
def show_result(passenger_id):
    alert = db_config.db.alerts.find_one(
        {'passenger_id': passenger_id},
        sort=[('timestamp', -1)]
    )
    if not alert:
        return render_template('result.html', passenger={'passenger_id': passenger_id}, alert=None, journey=None,
                               images=[])
    journey = db_config.db.journeys.find_one({'journey_id': alert['journey_id']})
    passenger = db_config.db.passengers.find_one({'passenger_id': passenger_id})
    images = list(db_config.db.images.find({'journey_id': alert['journey_id']}, sort=[('sequence', 1)]))
    return render_template('result.html', alert=alert, journey=journey, passenger=passenger, images=images)


@app.route('/dashboard')
def dashboard():
    if not camera_active:
        start_camera()

    recent_alerts = list(db_config.db.alerts.find(sort=[('timestamp', -1)], limit=10))
    total_passengers = db_config.db.passengers.count_documents({})
    total_journeys = db_config.db.journeys.count_documents({})
    total_alerts = db_config.db.alerts.count_documents({'alert_type': 'anomaly'})

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    today_journeys = db_config.db.journeys.count_documents(
        {'entrance_time': {'$gte': today_start, '$lt': tomorrow_start}})

    active_journeys = list(db_config.db.journeys.find({'status': 'active'}, sort=[('entrance_time', -1)]))

    return render_template('dashboard.html',
                           current_bus_turn=current_bus_turn,
                           active_passengers=len(active_passengers),
                           recent_alerts=recent_alerts,
                           total_passengers=total_passengers,
                           total_journeys=total_journeys,
                           total_alerts=total_alerts,
                           today_journeys=today_journeys,
                           active_journeys=active_journeys)


@app.route('/history')
def history():
    passenger_id = request.args.get('passenger_id')
    date_filter = request.args.get('date')
    alert_type = request.args.get('alert_type')

    query = {}
    if passenger_id: query['passenger_id'] = passenger_id
    if date_filter:
        try:
            d = datetime.strptime(date_filter, '%Y-%m-%d')
            start_dt = d.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(days=1)
            query['entrance_time'] = {'$gte': start_dt, '$lt': end_dt}
        except:
            pass

    journeys = list(db_config.db.journeys.find(query, sort=[('entrance_time', -1)], limit=50))

    for journey in journeys:
        alert = db_config.db.alerts.find_one({'journey_id': journey['journey_id']})
        journey['alert'] = alert

    if alert_type:
        journeys = [j for j in journeys if j.get('alert') and j['alert'].get('alert_type') == alert_type]

    passenger_ids = db_config.db.passengers.distinct('passenger_id')
    return render_template('history.html', journeys=journeys, passenger_ids=passenger_ids,
                           filters={'passenger_id': passenger_id, 'date': date_filter, 'alert_type': alert_type})


# ==================== PROFIT ASSESSMENT ====================
@app.route('/profit_assessment')
def profit_assessment():
    return render_template('profit_pred.html')

# ==================== DRIVER ANOMALY & ABILITY ====================
@app.route('/driving_ability')
def driving_ability():
    return render_template('driving_ability.html')


@app.route('/driving_ab')
def driving_ab():
    return render_template('driving_ab.html')


@app.route('/driver_behavior')
def driver_behavior():
    return render_template('driver_behavior.html')


@app.route('/api/driver_scores')
def get_driver_scores():
    try:
        now = datetime.now()
        scores = {'day': 100, 'week': 100, 'month': 100, 'quarter': 100, 'annual': 100}

        def get_avg_score(start_date, end_date):
            records = list(db_config.db.driver_scores.find({'date': {'$gte': start_date, '$lte': end_date}}))
            if not records: return 100
            total = sum(r.get('score', 100) for r in records)
            return round(total / len(records))

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        scores['day'] = get_avg_score(today_start, now)
        scores['week'] = get_avg_score(today_start - timedelta(days=now.weekday()), now)
        scores['month'] = get_avg_score(today_start.replace(day=1), now)
        scores['quarter'] = get_avg_score(today_start.replace(month=((now.month - 1) // 3) * 3 + 1, day=1), now)
        scores['annual'] = get_avg_score(today_start.replace(month=1, day=1), now)

        return jsonify(scores)
    except Exception as e:
        return jsonify({'error': str(e), 'day': 100, 'week': 100, 'month': 100, 'quarter': 100, 'annual': 100})


# ==================== SIMPLE APIS ====================
@app.route('/api/system_status')
def api_system_status():
    try:
        status = {
            'server_time': datetime.now().isoformat(), 'camera_active': camera_active,
            'current_bus_turn_active': bool(current_bus_turn and current_bus_turn.get('active')),
            'socketio': 'ready', 'db_connected': True
        }
        return jsonify(status)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/passenger_history/<passenger_id>')
def get_passenger_history(passenger_id):
    journeys = list(db_config.db.journeys.find(
        {'passenger_id': passenger_id},
        sort=[('entrance_time', -1)]
    ))
    for journey in journeys:
        journey['_id'] = str(journey['_id'])
        if journey.get('entrance_time'):
            journey['entrance_time'] = journey['entrance_time'].isoformat()
        if journey.get('exit_time'):
            journey['exit_time'] = journey['exit_time'].isoformat()
        if journey.get('date'):
            try:
                journey['date'] = journey['date'].isoformat()
            except Exception:
                pass
    return jsonify({'journeys': journeys})


@app.route('/api/recent_alerts')
def get_recent_alerts():
    alerts = list(db_config.db.alerts.find(
        sort=[('timestamp', -1)],
        limit=20
    ))
    for alert in alerts:
        alert['_id'] = str(alert['_id'])
        if alert.get('timestamp'):
            alert['timestamp'] = alert['timestamp'].isoformat()
    return jsonify({'alerts': alerts})


@app.route('/api/dashboard_stats')
def get_dashboard_stats():
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    stats = {
        'total_passengers': db_config.db.passengers.count_documents({}),
        'today_journeys': db_config.db.journeys.count_documents(
            {'entrance_time': {'$gte': today_start, '$lt': tomorrow_start}}),
        'anomalies': db_config.db.alerts.count_documents({'alert_type': 'anomaly'}),
        'active_passengers': len(active_passengers)
    }
    return jsonify(stats)


@app.route('/api/active_passengers')
def api_active_passengers():
    return jsonify({
        'count': len(active_passengers),
        'passengers': list(active_passengers.keys())
    })


@app.route('/api/check_passenger/<passenger_id>')
def check_passenger(passenger_id):
    passenger = db_config.db.passengers.find_one({'passenger_id': passenger_id})
    if passenger:
        return jsonify({
            'exists': True,
            'name': passenger.get('name', 'Unknown'),
            'total_journeys': passenger.get('total_journeys', 0),
            'last_seen': passenger.get('last_seen').isoformat() if passenger.get('last_seen') else None
        })
    return jsonify({'exists': False})


# ==================== SOCKET.IO EVENTS ====================
@socketio.on('connect')
def handle_connect():
    print('Client connected (Socket.IO)')
    emit('connection_established', {'data': 'Connected to anomaly detection system'})


@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected (Socket.IO)')


# ==================== CAMERA STREAM ENDPOINTS ====================
@app.route('/video_feed')
def video_feed():
    return Response(generate_feed(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/camera/start', methods=['POST'])
def api_start_camera():
    start_camera()
    return jsonify({'success': True, 'message': 'Camera started'})


@app.route('/api/camera/stop', methods=['POST'])
def api_stop_camera():
    stop_camera()
    return jsonify({'success': True, 'message': 'Camera stopped'})


@app.route('/api/camera/status', methods=['GET'])
def api_camera_status():
    return jsonify({'active': camera_active})


@app.route('/api/camera/test', methods=['POST'])
def api_test_camera():
    try:
        frame = get_camera_frame()
        test_path = 'static/test_capture.jpg'
        cv2.imwrite(test_path, frame)
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            return jsonify({'success': False, 'error': 'JPEG encoding failed'}), 500
        img_str = base64.b64encode(buffer).decode('utf-8')
        return jsonify({
            'success': True,
            'message': 'Camera test successful',
            'image': f'data:image/jpeg;base64,{img_str}',
            'path': test_path
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== ABOUT ====================
@app.route('/about')
def about():
    return render_template('about.html')


# ==================== DRUNKARD DETECTION (Simulated) ====================
@app.route('/drunkard_level')
def drunkard_level():
    return render_template('drunkard_level.html')


@app.route('/drunkard_video_feed')
def drunkard_video_feed():
    return Response(generate_drunkard_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def generate_drunkard_frames():
    if not camera_active:
        start_camera()
    while True:
        frame = get_camera_frame()
        ret, buffer = cv2.imencode('.jpg', frame)
        if ret:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        else:
            time.sleep(0.05)
        time.sleep(0.033)


@app.route('/start_drunkard_detection', methods=['POST'])
def start_drunkard_detection():
    try:
        return jsonify({
            'success': True,
            'message': 'Drunkard detection started',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/stop_drunkard_detection', methods=['POST'])
def stop_drunkard_detection():
    return jsonify({
        'success': True,
        'message': 'Drunkard detection stopped',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/get_drunkard_data')
def get_drunkard_data():
    import random
    alcohol_level = random.uniform(0.0, 0.15)
    return jsonify({
        'alcohol_level': alcohol_level,
        'timestamp': datetime.now().isoformat(),
        'status': 'detecting'
    })


@app.route('/get_drunkard_status')
def get_drunkard_status():
    return jsonify({
        'detection_active': False,
        'timestamp': datetime.now().isoformat()
    })


# ==================== DRIVING ABILITY (Simulated) ====================
@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    return jsonify({
        'status': 'started',
        'message': 'Monitoring started',
        'session_start': datetime.now().isoformat()
    })


@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    return jsonify({
        'status': 'stopped',
        'message': 'Monitoring stopped',
        'session_end': datetime.now().isoformat()
    })


@app.route('/get_alerts')
def get_alerts_api():
    alerts = []
    import random
    if random.random() < 0.2:
        alert_types = ['LANE_DEPARTURE', 'SPEEDING', 'SUDDEN_BRAKING', 'SWERVING']
        severities = ['LOW', 'MEDIUM', 'HIGH']
        alerts.append({
            'type': random.choice(alert_types),
            'severity': random.choice(severities),
            'timestamp': datetime.now().isoformat(),
            'confidence': random.uniform(0.7, 0.99)
        })
    return jsonify({'alerts': alerts, 'total': len(alerts)})


@app.route('/get_summary')
def get_summary():
    return jsonify({
        'is_running': False,
        'session_start': datetime.now().isoformat(),
        'violations': 0,
        'high_severity': 0,
        'driving_score': 95,
        'session_duration': '00:05:00'
    })


# ==================== NATIVE WEBSOCKET AT /ws (optional) ====================
if _FLASK_SOCK_AVAILABLE:

    @sock.route('/ws')
    def ws_endpoint(ws):
        try:
            ws.send(json.dumps({
                'type': 'hello',
                'message': 'Native WebSocket connected',
                'timestamp': datetime.now().isoformat()
            }))
            while True:
                data = ws.receive()
                if data is None:
                    break
                ws.send(json.dumps({
                    'type': 'echo',
                    'received': data,
                    'timestamp': datetime.now().isoformat()
                }))
        except Exception as e:
            print(f"[ws_endpoint] WebSocket error: {e}")

else:
    @app.route('/ws', methods=['GET'])
    def http_ws_placeholder():
        return jsonify({
            'ok': False,
            'message': 'Native WebSocket not enabled. Install flask-sock + simple-websocket for /ws.',
            'hint': "For Socket.IO, use the Socket.IO client and connect to '/socket.io'."
        }), 426


# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


# ==================== APP START ====================
if __name__ == '__main__':
    if db_config.connect():
        print("Database connected successfully")
        log_event('system_start', 'Flask application started')
        os.makedirs('static/Entrance', exist_ok=True)
        os.makedirs('static/Exit', exist_ok=True)
        socketio.run(app, host='0.0.0.0', port=5005, debug=True, allow_unsafe_werkzeug=True)
    else:
        print("Failed to connect to database. Exiting.")

=======
import os
import cv2
import uuid
import json
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for
from flask_socketio import SocketIO, emit
import threading
import time
from functools import wraps
import base64
import random
import requests

from config import db_config
from model_loader import model_loader

# ── Route journey durations (one-way bus travel, minutes) ────────────────────
# Sources: busbooking.lk, NTC timetables, rome2rio (bus option only)
# Turnaround at destination: 30 min
# Total block = one_way * 2 + 30  (bus must return before it can be scheduled again)
ROUTE_DURATIONS_ONE_WAY = {
    'Colombo ↔ Kandy':           210,   # ~3h 30m
    'Colombo ↔ Galle':           150,   # ~2h 30m
    'Colombo ↔ Jaffna':          480,   # ~8h
    'Colombo ↔ Matara':          210,   # ~3h 30m
    'Colombo ↔ Kurunegala':      120,   # ~2h
    'Colombo ↔ Negombo':          75,   # ~1h 15m
    'Kandy ↔ Nuwara Eliya':      150,   # ~2h 30m
    'Kandy ↔ Badulla':           240,   # ~4h
    'Galle ↔ Matara':             60,   # ~1h
    'Colombo ↔ Ratnapura':       150,   # ~2h 30m
    'Colombo ↔ Anuradhapura':    270,   # ~4h 30m
    'Colombo ↔ Polonnaruwa':     300,   # ~5h
}
TURNAROUND_MINS = 30  # rest + turnaround at destination

def get_route_block_mins(route: str) -> int:
    """Total minutes a bus is blocked: (one_way * 2) + turnaround."""
    one_way = ROUTE_DURATIONS_ONE_WAY.get(route, 90)  # default 90 min if unknown
    return one_way * 2 + TURNAROUND_MINS

def time_to_mins(t: str) -> int | None:
    """'HH:MM' -> minutes from midnight. Returns None on error."""
    try:
        hh, mm = t.strip().split(':')
        return int(hh) * 60 + int(mm)
    except Exception:
        return None

def schedules_overlap(start_a: int, block_a: int, start_b: int, block_b: int) -> bool:
    """Return True if two [start, start+block) intervals overlap."""
    return start_a < start_b + block_b and start_b < start_a + block_a

# --- ROBUST IMPORT FOR NEW BEHAVIOR ANALYZER ---
try:
    from driver_behavior import driver_analyzer

    print("Driver behavior module loaded successfully.")
except Exception as e:
    print(f"Warning: Could not import driver_behavior: {e}. Using DummyAnalyzer fallback.")


    class DummyAnalyzer:
        def analyze_frame(self, frame):
            return {'class_id': 'c0', 'behavior': 'normal driving (simulated)', 'confidence': 0.99, 'is_anomaly': False}


    driver_analyzer = DummyAnalyzer()

# ---------------- Optional native WebSocket support (flask-sock) ----------------
try:
    from flask_sock import Sock

    _FLASK_SOCK_AVAILABLE = True
except Exception:
    _FLASK_SOCK_AVAILABLE = False
# -------------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Socket.IO server
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    serve_client=True
)

# Optional native WebSocket
if _FLASK_SOCK_AVAILABLE:
    sock = Sock(app)
else:
    sock = None

# Global state
current_bus_turn = None
active_passengers = {}


@app.context_processor
def inject_global_sidebar():
    """Inject current_bus_turn into every template for the sidebar."""
    return dict(current_bus_turn=current_bus_turn)


# Global camera variables
camera_active = False
camera_thread = None
latest_frame = None
frame_lock = threading.Lock()


def camera_feed_generator():
    """Background thread that acquires frames from the camera, runs behavior models, etc."""
    global camera_active, latest_frame, current_bus_turn

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Warning: Cannot open camera. Using simulated feed.")
        while camera_active:
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.rectangle(img, (50, 50), (590, 430), (0, 255, 0), 2)
            cv2.putText(img, "Camera Not Available", (140, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            with frame_lock:
                latest_frame = img.copy()
            time.sleep(0.1)
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    frame_counter = 0

    while camera_active:
        ret, frame = cap.read()
        if ret:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame, current_time, (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            if current_bus_turn:
                cv2.putText(frame, f"Bus: {current_bus_turn['bus_turn_id']}", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                # --- Driver Behavior Analysis every 15 frames ---
                frame_counter += 1
                if frame_counter % 15 == 0:
                    try:
                        behavior_res = driver_analyzer.analyze_frame(frame)

                        # If it's an anomaly, count it and emit event
                        if behavior_res['is_anomaly']:
                            current_bus_turn['driver_anomaly_count'] += 1
                            log_event('driver_behavior_anomaly', f"Detected: {behavior_res['behavior']}", behavior_res)

                        # Emit to frontend for UI updates
                        socketio.emit('driver_behavior_alert', {
                            'behavior': behavior_res['behavior'],
                            'confidence': behavior_res['confidence'],
                            'is_anomaly': behavior_res['is_anomaly'],
                            'timestamp': datetime.now().isoformat()
                        })
                    except Exception as e:
                        print(f"Error in behavior analysis: {e}")

            with frame_lock:
                latest_frame = frame.copy()
        else:
            print("Failed to grab frame")
            time.sleep(0.05)

        time.sleep(0.03)

    cap.release()


def get_camera_frame():
    with frame_lock:
        if latest_frame is not None:
            return latest_frame.copy()
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(img, "Camera Feed", (220, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    return img


def start_camera():
    global camera_active, camera_thread
    if not camera_active:
        camera_active = True
        camera_thread = threading.Thread(target=camera_feed_generator, name="CameraThread", daemon=True)
        camera_thread.start()
        log_event('camera_started', 'Camera feed started')
        print("Camera started")


def stop_camera():
    global camera_active, camera_thread
    if camera_active:
        camera_active = False
        if camera_thread:
            camera_thread.join(timeout=2.0)
            camera_thread = None
        log_event('camera_stopped', 'Camera feed stopped')
        print("Camera stopped")


def generate_feed():
    if not camera_active:
        start_camera()
    while True:
        frame = get_camera_frame()
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85, cv2.IMWRITE_JPEG_OPTIMIZE, 1])
        if ret:
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            time.sleep(0.05)
        time.sleep(0.033)


def log_event(event_type, description, metadata=None):
    try:
        db_config.log_event(event_type, description, metadata)
    except Exception as e:
        print(f"[log_event] Failed to log event: {e}")

def get_embedding_from_cloud(image_path):
    """
    Send one image file to the cloud ML API and get embedding back.
    """
    try:
        with open(image_path, "rb") as f:
            files = {
                "file": (os.path.basename(image_path), f, "image/jpeg")
            }
            response = requests.post("http://localhost:8000/embed", files=files, timeout=30)

        if response.status_code != 200:
            print(f"[ML API] Bad status: {response.status_code}, body: {response.text}")
            return None

        data = response.json()
        if not data.get("success"):
            print(f"[ML API] success=False: {data}")
            return None

        return data.get("embedding")
    except Exception as e:
        print(f"[ML API] Error getting embedding: {e}")
        return None


def average_embeddings(embeddings):
    """
    Average multiple embeddings into one embedding.
    """
    if not embeddings:
        return None

    arr = np.array(embeddings, dtype=np.float32)
    avg = np.mean(arr, axis=0)

    norm = np.linalg.norm(avg)
    if norm > 0:
        avg = avg / norm

    return avg.tolist()


def cosine_similarity(vec1, vec2):
    """
    Cosine similarity between two embeddings.
    """
    v1 = np.array(vec1, dtype=np.float32)
    v2 = np.array(vec2, dtype=np.float32)

    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return float(np.dot(v1, v2) / (norm1 * norm2))


def get_average_embedding_for_images(image_paths):
    """
    For a list of image paths, call cloud /embed for each image,
    then average the embeddings.
    """
    embeddings = []

    for path in image_paths:
        if os.path.exists(path):
            emb = get_embedding_from_cloud(path)
            if emb is not None:
                embeddings.append(emb)

    if not embeddings:
        return None

    return average_embeddings(embeddings)

def requires_bus_turn(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_bus_turn is None:
            return jsonify({'error': 'No active bus turn. Start a journey first.'}), 400
        return f(*args, **kwargs)

    return decorated_function


# ==================== HOME ====================
@app.route('/')
def home():
    return render_template('home.html')


@app.route('/home_redirect')
def home_redirect():
    return redirect(url_for('home'))


# ==================== JOURNEY ====================
@app.route('/start_journey', methods=['POST'])
def start_journey():
    global current_bus_turn
    bus_turn_id = f"bus_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    current_bus_turn = {
        'bus_turn_id': bus_turn_id,
        'start_time': datetime.now(),
        'active': True,
        'passenger_count': 0,
        'anomaly_count': 0,
        'driver_anomaly_count': 0,  # Added for driver behavior scoring
        'end_time': None
    }
    log_event('journey_started', f'Bus turn {bus_turn_id} started')
    socketio.emit('bus_turn_started', {
        'bus_turn_id': bus_turn_id,
        'start_time': current_bus_turn['start_time'].isoformat()
    })
    return jsonify(
        {'success': True, 'bus_turn_id': bus_turn_id, 'start_time': current_bus_turn['start_time'].isoformat()})


@app.route('/end_journey', methods=['POST'])
def end_journey():
    global current_bus_turn
    if current_bus_turn is None:
        return jsonify({'error': 'No active bus turn'}), 400
    try:
        end_time = datetime.now()
        current_bus_turn['end_time'] = end_time
        current_bus_turn['active'] = False

        # Calculate driver score for the journey (baseline 100, -2 points per anomaly)
        driver_anomalies = current_bus_turn.get('driver_anomaly_count', 0)
        journey_score = max(0, 100 - (driver_anomalies * 2))

        # Store score in DB
        db_config.db.driver_scores.insert_one({
            'bus_turn_id': current_bus_turn['bus_turn_id'],
            'date': datetime.now(),
            'score': journey_score,
            'anomalies': driver_anomalies
        })

        report = {
            'bus_turn_id': current_bus_turn['bus_turn_id'],
            'start_time': current_bus_turn['start_time'].isoformat(),
            'end_time': end_time.isoformat(),
            'duration_seconds': int((end_time - current_bus_turn['start_time']).total_seconds()),
            'total_passengers': current_bus_turn['passenger_count'],
            'anomalies_detected': current_bus_turn['anomaly_count'],
            'driver_anomalies': driver_anomalies,
            'driver_journey_score': journey_score,
            'active_passengers_remaining': len(active_passengers)
        }
        log_event('journey_ended', f'Bus turn {current_bus_turn["bus_turn_id"]} ended', report)
        active_passengers.clear()
        socketio.emit('journey_ended', report)
        current_bus_turn = None
        return jsonify({'success': True, 'report': report, 'message': 'Bus turn ended successfully'})
    except Exception as e:
        log_event('end_journey_error', f'Error ending journey: {str(e)}')
        return jsonify({'error': str(e)}), 500


# ==================== CAPTURE ENTRANCE / EXIT ====================
@app.route('/capture')
def capture_page():
    passenger_id = request.args.get('passenger_id', 'new')
    capture_type = request.args.get('type', 'entrance')

    if passenger_id == 'new':
        passenger_id = str(random.randint(1, 54))

    stop_camera()
    return render_template('capture.html',
                           passenger_id=passenger_id,
                           capture_type=capture_type,
                           image_count=5 if capture_type == 'entrance' else 1,
                           current_bus_turn=current_bus_turn)


@app.route('/capture_entrance_auto', methods=['POST'])
@requires_bus_turn
def capture_entrance_auto():
    """Handles auto-allocating an ID (1-54) and saving 5 entrance images"""
    try:
        if len(active_passengers) >= 54:
            return jsonify({'error': 'Bus is fully occupied (54/54 seats). No more passengers can enter.'}), 400

        active_ids = []
        for pid in active_passengers.keys():
            try:
                active_ids.append(int(pid))
            except:
                pass

        available_ids = [i for i in range(1, 55) if i not in active_ids]
        if not available_ids:
            return jsonify({'error': 'Capacity error.'}), 400

        effective_pid = str(min(available_ids))

        entrance_dir = os.path.join('static', 'Entrance', effective_pid)
        os.makedirs(entrance_dir, exist_ok=True)
        images_data, image_paths = [], []

        if 'image_data[]' in request.form:
            try:
                image_data_list = json.loads(request.form['image_data[]'])
                for i, image_data in enumerate(image_data_list[:5]):
                    if image_data:
                        if ',' in image_data:
                            _, encoded = image_data.split(',', 1)
                        else:
                            encoded = image_data
                        binary_data = base64.b64decode(encoded)
                        filename = f"entrance_{i + 1}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
                        filepath = os.path.join(entrance_dir, filename)
                        with open(filepath, 'wb') as f:
                            f.write(binary_data)
                        img = cv2.imread(filepath)
                        if img is not None:
                            images_data.append(img)
                            image_paths.append(filepath)
            except Exception as e:
                log_event('image_decode_error', f'Error decoding base64 images: {str(e)}')

        if not images_data or len(images_data) < 5:
            return jsonify({'error': 'Insufficient images captured'}), 400

        journey_id = f"journey_{effective_pid}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        passenger_name = f"Passenger {effective_pid}"

        passenger_update = {
            '$setOnInsert': {'passenger_id': effective_pid, 'name': passenger_name, 'created_at': datetime.now()},
            '$set': {'last_seen': datetime.now()},
            '$inc': {'total_journeys': 1}
        }
        db_config.db.passengers.update_one({'passenger_id': effective_pid}, passenger_update, upsert=True)

        now = datetime.now()
        journey_data = {
            'journey_id': journey_id, 'bus_turn_id': current_bus_turn['bus_turn_id'],
            'passenger_id': effective_pid, 'entrance_time': now, 'date': datetime(now.year, now.month, now.day),
            'exit_time': None, 'travel_time_seconds': None, 'status': 'active'
        }
        db_config.db.journeys.insert_one(journey_data)

        for i, img_path in enumerate(image_paths):
            db_config.db.images.insert_one({
                'image_id': str(uuid.uuid4()), 'passenger_id': effective_pid, 'image_type': 'entrance',
                'image_path': img_path.replace('static/', ''), 'timestamp': datetime.now(),
                'journey_id': journey_id, 'sequence': i + 1
            })

        active_passengers[effective_pid] = {
            'journey_id': journey_id, 'entrance_time': datetime.now(),
            'entrance_images': image_paths, 'name': passenger_name
        }

        current_bus_turn['passenger_count'] += 1

        log_event('passenger_entered', f'Passenger {effective_pid} entered', {
            'passenger_id': effective_pid, 'journey_id': journey_id
        })
        socketio.emit('passenger_entered', {
            'passenger_id': effective_pid, 'name': passenger_name,
            'journey_id': journey_id, 'timestamp': datetime.now().isoformat(),
            'active_count': current_bus_turn['passenger_count']
        })

        result_txt = f"ID {effective_pid} - Image - No Anomaly Detected"

        return jsonify({
            'success': True,
            'passenger_id': effective_pid,
            'active_count': current_bus_turn['passenger_count'],
            'result_text': result_txt,
            'message': 'Seat allocated successfully.'
        })
    except Exception as e:
        log_event('capture_error', f'Error capturing entrance images: {str(e)}')
        return jsonify({'error': str(e)}), 500


@app.route('/capture_exit_auto', methods=['POST'])
@requires_bus_turn
def capture_exit_auto():
    """Handles checking 5 exit images against all active passengers via Siamese matching."""
    try:
        if not active_passengers:
            return jsonify({
                'match_found': False,
                'result_text': 'ID Unknown - Image - No matching Found',
                'message': 'No active passengers.'
            }), 200

        exit_images_data = []
        exit_paths_temp = []

        temp_dir = os.path.join('static', 'Exit', 'Temp')
        os.makedirs(temp_dir, exist_ok=True)

        if 'image_data[]' in request.form:
            try:
                image_data_list = json.loads(request.form['image_data[]'])
                for i, image_data in enumerate(image_data_list[:5]):
                    if image_data:
                        if ',' in image_data:
                            _, encoded = image_data.split(",", 1)
                        else:
                            encoded = image_data
                        binary_data = base64.b64decode(encoded)
                        filepath = os.path.join(temp_dir, f"temp_{i}_{uuid.uuid4().hex[:8]}.jpg")
                        with open(filepath, 'wb') as f:
                            f.write(binary_data)
                        img = cv2.imread(filepath)
                        if img is not None:
                            exit_images_data.append(img)
                            exit_paths_temp.append(filepath)
            except Exception as e:
                pass

        if not exit_images_data:
            return jsonify({'error': 'Failed to capture exit images'}), 400

                # --- CLOUD EMBEDDING MATCHING LOGIC ---
        best_match_id = None
        best_sim = -1.0
        best_res = None

        # Get one averaged embedding for the 5 exit images
        exit_embedding = get_average_embedding_for_images(exit_paths_temp)

        if exit_embedding is None:
            return jsonify({'error': 'Failed to generate exit embedding from cloud ML API'}), 500

        for pid, pdata in active_passengers.items():
            ent_paths = pdata['entrance_images']
            entry_embedding = get_average_embedding_for_images(ent_paths)

            if entry_embedding is None:
                continue

            avg_sim = cosine_similarity(entry_embedding, exit_embedding)

            res = {
                'similarity_scores': [avg_sim],
                'confidence': avg_sim,
                'is_anomaly': avg_sim < 0.80,
                'alert_level': 'HIGH' if avg_sim < 0.60 else ('MEDIUM' if avg_sim < 0.80 else 'LOW')
            }

            if avg_sim > best_sim:
                best_sim = avg_sim
                best_match_id = pid
                best_res = res

        MATCH_THRESHOLD = 0.80
        if best_match_id is None or best_sim < MATCH_THRESHOLD:
            for p in exit_paths_temp:
                if os.path.exists(p): os.remove(p)
            return jsonify({
                'match_found': False,
                'result_text': 'ID Unknown - Image - No matching Found'
            }), 200

        # --- MATCH FOUND: Process Exit ---
        passenger_id = best_match_id

        final_dir = os.path.join('static', 'Exit', passenger_id)
        os.makedirs(final_dir, exist_ok=True)
        exit_paths_final = []
        for i, temp_p in enumerate(exit_paths_temp):
            final_p = os.path.join(final_dir, f"exit_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg")
            os.rename(temp_p, final_p)
            exit_paths_final.append(final_p)

        is_anomaly_bool = bool(best_res.get('is_anomaly', False))
        final_confidence_float = float(best_res.get('confidence', 0.85))

        for i, exit_path in enumerate(exit_paths_final):
            db_config.db.images.insert_one({
                'image_id': str(uuid.uuid4()), 'passenger_id': passenger_id, 'image_type': 'exit',
                'image_path': exit_path.replace('static/', ''), 'timestamp': datetime.now(),
                'journey_id': active_passengers[passenger_id]['journey_id'], 'sequence': i + 1
            })

        exit_time = datetime.now()
        entrance_time = active_passengers[passenger_id]['entrance_time']
        travel_time = int((exit_time - entrance_time).total_seconds())

        db_config.db.journeys.update_one(
            {'journey_id': active_passengers[passenger_id]['journey_id']},
            {'$set': {'exit_time': exit_time, 'travel_time_seconds': travel_time, 'status': 'completed'}}
        )
        db_config.db.passengers.update_one({'passenger_id': passenger_id}, {'$set': {'last_seen': exit_time}})

        all_image_paths = [p.replace('static/', '') for p in
                           active_passengers[passenger_id]['entrance_images'] + exit_paths_final]

        alert_type = 'anomaly' if is_anomaly_bool else 'normal'

        alert_data = {
            'alert_id': str(uuid.uuid4()), 'passenger_id': passenger_id,
            'journey_id': active_passengers[passenger_id]['journey_id'],
            'alert_type': alert_type,
            'confidence': final_confidence_float, 'timestamp': datetime.now(),
            'image_paths': all_image_paths,
            'similarity_scores': [float(s) for s in best_res.get('similarity_scores', [])],
            'alert_level': best_res.get('alert_level', 'LOW')
        }
        alert_result = db_config.db.alerts.insert_one(alert_data)

        if is_anomaly_bool:
            current_bus_turn['anomaly_count'] += 1

        # Free up the seat
        passenger_data = active_passengers.pop(passenger_id, {'name': 'Unknown'})
        current_bus_turn['passenger_count'] -= 1

        log_event('passenger_exited', f'Passenger {passenger_id} exited', {
            'passenger_id': passenger_id, 'anomaly': is_anomaly_bool,
            'confidence': final_confidence_float, 'travel_time': travel_time
        })

        socketio.emit('passenger_exit', {
            'passenger_id': passenger_id, 'name': passenger_data['name'],
            'anomaly': is_anomaly_bool, 'confidence': final_confidence_float,
            'travel_time': travel_time, 'timestamp': datetime.now().isoformat(),
            'alert_id': str(alert_result.inserted_id),
            'active_count': current_bus_turn['passenger_count']
        })

        # Format Result Text per user request
        if is_anomaly_bool:
            result_txt = f"ID {passenger_id} - Image - Anomaly Detected"
        else:
            result_txt = f"ID {passenger_id} - Image - No Anomaly Detected"

        return jsonify({
            'success': True,
            'match_found': True,
            'passenger_id': passenger_id,
            'anomaly': is_anomaly_bool,
            'confidence': final_confidence_float,
            'active_count': current_bus_turn['passenger_count'],
            'result_text': result_txt
        })
    except Exception as e:
        log_event('exit_error', f'Error processing auto exit: {str(e)}')
        return jsonify({'error': str(e)}), 500


# ==================== RESULT & DASHBOARD ====================
@app.route('/result/<passenger_id>')
def show_result(passenger_id):
    alert = db_config.db.alerts.find_one(
        {'passenger_id': passenger_id},
        sort=[('timestamp', -1)]
    )
    if not alert:
        return render_template('result.html', passenger={'passenger_id': passenger_id}, alert=None, journey=None,
                               images=[])
    journey = db_config.db.journeys.find_one({'journey_id': alert['journey_id']})
    passenger = db_config.db.passengers.find_one({'passenger_id': passenger_id})
    images = list(db_config.db.images.find({'journey_id': alert['journey_id']}, sort=[('sequence', 1)]))
    return render_template('result.html', alert=alert, journey=journey, passenger=passenger, images=images)


@app.route('/dashboard')
def dashboard():
    if not camera_active:
        start_camera()

    recent_alerts = list(db_config.db.alerts.find(sort=[('timestamp', -1)], limit=10))
    total_passengers = db_config.db.passengers.count_documents({})
    total_journeys = db_config.db.journeys.count_documents({})
    total_alerts = db_config.db.alerts.count_documents({'alert_type': 'anomaly'})

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    today_journeys = db_config.db.journeys.count_documents(
        {'entrance_time': {'$gte': today_start, '$lt': tomorrow_start}})

    active_journeys = list(db_config.db.journeys.find({'status': 'active'}, sort=[('entrance_time', -1)]))

    return render_template('dashboard.html',
                           current_bus_turn=current_bus_turn,
                           active_passengers=len(active_passengers),
                           recent_alerts=recent_alerts,
                           total_passengers=total_passengers,
                           total_journeys=total_journeys,
                           total_alerts=total_alerts,
                           today_journeys=today_journeys,
                           active_journeys=active_journeys)


@app.route('/history')
def history():
    passenger_id = request.args.get('passenger_id')
    date_filter  = request.args.get('date')
    alert_type   = request.args.get('alert_type')
    trip_bus_id  = request.args.get('trip_bus_id', '').strip()
    trip_route   = request.args.get('trip_route', '').strip()

    # ── Passenger journeys ─────────────────────────────────────
    query = {}
    if passenger_id: query['passenger_id'] = passenger_id
    if date_filter:
        try:
            d = datetime.strptime(date_filter, '%Y-%m-%d')
            start_dt = d.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt   = start_dt + timedelta(days=1)
            query['entrance_time'] = {'$gte': start_dt, '$lt': end_dt}
        except Exception:
            pass

    journeys = list(db_config.db.journeys.find(query, sort=[('entrance_time', -1)], limit=50))

    for journey in journeys:
        alert = db_config.db.alerts.find_one({'journey_id': journey['journey_id']})
        journey['alert'] = alert

    if alert_type:
        journeys = [j for j in journeys if j.get('alert') and j['alert'].get('alert_type') == alert_type]

    passenger_ids = db_config.db.passengers.distinct('passenger_id')

    # ── Completed Assessment Trips ──────────────────────────────
    trip_query = {}
    if trip_bus_id: trip_query['bus_id'] = trip_bus_id
    if trip_route:  trip_query['route']  = trip_route

    completed_trips = list(db_config.db.completed_trips.find(
        trip_query, sort=[('completed_at', -1)], limit=100
    ))
    for t in completed_trips:
        t['_id'] = str(t['_id'])
        if t.get('completed_at'):
            t['completed_at_str'] = t['completed_at'].strftime('%d %b %Y, %H:%M')

    trip_bus_ids = db_config.db.completed_trips.distinct('bus_id')
    trip_routes  = db_config.db.completed_trips.distinct('route')

    return render_template(
        'history.html',
        journeys=journeys,
        passenger_ids=passenger_ids,
        filters={'passenger_id': passenger_id, 'date': date_filter, 'alert_type': alert_type},
        completed_trips=completed_trips,
        trip_bus_ids=trip_bus_ids,
        trip_routes=trip_routes,
        trip_filters={'bus_id': trip_bus_id, 'route': trip_route}
    )


# ==================== PROFIT ASSESSMENT ====================
@app.route('/profit_assessment')
def profit_assessment():
    return render_template('profit_pred.html')


@app.route('/api/assess_profit', methods=['POST'])
def api_assess_profit():
    """
    Full server-side profit assessment.
    Accepts JSON: {daily_collection, total_distance, fuel_cost_per_l,
                   trips_count, bus_age_years, maintenance_cost,
                   driver_salary, conductor_salary}
    Returns the same shape as the frontend simulate() function.
    """
    try:
        data = request.get_json(force=True)

        # ── Inputs ──────────────────────────────────────────────
        daily_collection = float(data.get('daily_collection', 0))
        total_distance   = float(data.get('total_distance', 1))
        fuel_cost_per_l  = float(data.get('fuel_cost_per_l', 360))
        trips_count      = int(data.get('trips_count', 1))
        bus_age_years    = float(data.get('bus_age_years', 0))
        maintenance_cost = float(data.get('maintenance_cost', 0))
        driver_salary    = float(data.get('driver_salary', 0))
        conductor_salary = float(data.get('conductor_salary', 0))

        if daily_collection <= 0 or total_distance <= 0:
            return jsonify({'error': 'daily_collection and total_distance must be positive'}), 400

        # ── Core calculations ────────────────────────────────────
        # Average Sri Lankan bus: ~3.5 km/litre (adjust per bus age)
        efficiency     = max(2.0, 3.5 - bus_age_years * 0.05)
        fuel_litres    = total_distance / efficiency
        fuel_cost_total = fuel_litres * fuel_cost_per_l

        labour_cost    = driver_salary + conductor_salary
        operational_cost = fuel_cost_total + maintenance_cost + labour_cost
        profit         = daily_collection - operational_cost
        profit_margin  = (profit / daily_collection) * 100
        revenue_per_km = daily_collection / total_distance

        # ── Status ──────────────────────────────────────────────
        if profit >= 50000:
            profit_status = 'Highly Profitable'
            status_color  = 'success'
            rec_level     = 'EXCELLENT'
        elif profit >= 0:
            profit_status = 'Profitable'
            status_color  = 'success'
            rec_level     = 'GOOD'
        else:
            profit_status = 'Loss Making'
            status_color  = 'danger'
            rec_level     = 'NEEDS IMPROVEMENT'

        # ── Risk Assessment ──────────────────────────────────────
        risk_score   = 0
        risk_factors = []

        if fuel_cost_per_l > 370:
            risk_score += 30
            risk_factors.append('High fuel costs above LKR 370/L')
        if bus_age_years > 10:
            risk_score += 25
            risk_factors.append(f'Ageing vehicle ({int(bus_age_years)} years)')
        if total_distance > 350:
            risk_score += 20
            risk_factors.append('Long-distance operation increases wear')
        if profit < 0:
            risk_score += 30
            risk_factors.append('Currently operating at a loss')
        if maintenance_cost > 1500:
            risk_score += 15
            risk_factors.append('High maintenance costs')
        if trips_count < 2:
            risk_score += 10
            risk_factors.append('Low number of daily trips')

        risk_score = min(risk_score, 100)

        if risk_score >= 70:
            risk_level = 'HIGH'
        elif risk_score >= 40:
            risk_level = 'MEDIUM'
        else:
            risk_level = 'LOW'

        # ── Recommendations ──────────────────────────────────────
        recommendations = []

        if profit < 0:
            recommendations.append({
                'priority': 'HIGH',
                'title': 'Reduce Operational Costs',
                'desc': 'Route is currently loss-making. Immediate action required.',
                'action': 'Review fuel usage, renegotiate maintenance contracts, optimise trip count.'
            })
        if fuel_cost_per_l > 350:
            recommendations.append({
                'priority': 'MEDIUM',
                'title': 'Optimise Fuel Costs',
                'desc': f'Fuel at LKR {fuel_cost_per_l}/L is above the optimal threshold.',
                'action': 'Consider bulk purchasing agreements or alternative fuel stations.'
            })
        if bus_age_years > 10:
            recommendations.append({
                'priority': 'MEDIUM',
                'title': 'Vehicle Maintenance Review',
                'desc': f'Bus age ({int(bus_age_years)} yrs) negatively impacts fuel efficiency.',
                'action': 'Schedule a comprehensive mechanical inspection.'
            })
        if total_distance > 300:
            recommendations.append({
                'priority': 'LOW',
                'title': 'Route Optimisation',
                'desc': 'Long-distance operations detected.',
                'action': 'Analyse route distances and consider redistribution of trips.'
            })
        if profit_margin > 30 and not recommendations:
            recommendations.append({
                'priority': 'LOW',
                'title': 'Maintain Performance',
                'desc': 'Operations are running efficiently.',
                'action': 'Continue current operational strategy and monitor monthly.'
            })

        # ── Temporal Projections ─────────────────────────────────
        temporal_predictions = {}
        periods = [
            ('daily', 1), ('weekly', 7), ('monthly', 30),
            ('quarterly', 90), ('annually', 365)
        ]
        for name, days in periods:
            base = profit * days
            projected = base * 1.05 if profit >= 0 else base
            temporal_predictions[name] = {
                'base': round(base, 2),
                'projected': round(projected, 2),
                'period_name': name.capitalize()
            }

        # ── Persist to DB (best-effort) ──────────────────────────
        try:
            db_config.db.profit_assessments.insert_one({
                'timestamp': datetime.now(),
                'inputs': data,
                'profit': profit,
                'profit_margin': profit_margin,
                'risk_level': risk_level,
                'risk_score': risk_score
            })
        except Exception:
            pass  # DB errors must not break the response

        return jsonify({
            'profit': round(profit, 2),
            'profit_status': profit_status,
            'status_color': status_color,
            'recommendation_level': rec_level,
            'key_metrics': {
                'daily_collection': round(daily_collection, 2),
                'total_distance': round(total_distance, 2),
                'fuel_cost_total': round(fuel_cost_total, 2),
                'labor_cost': round(labour_cost, 2),
                'maintenance': round(maintenance_cost, 2),
                'operational_cost': round(operational_cost, 2),
                'profit_margin': round(profit_margin, 2),
                'revenue_per_km': round(revenue_per_km, 2),
                'fuel_efficiency_kpl': round(efficiency, 2),
                'fuel_litres_used': round(fuel_litres, 2)
            },
            'recommendations': recommendations,
            'risk_assessment': {
                'risk_level': risk_level,
                'risk_score': risk_score,
                'risk_factors': risk_factors
            },
            'temporal_predictions': temporal_predictions,
            'generated_at': datetime.now().isoformat()
        })

    except (ValueError, TypeError) as e:
        return jsonify({'error': f'Invalid input: {e}'}), 400
    except Exception as e:
        print(f"[assess_profit] Unexpected error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ── Schedule endpoints ────────────────────────────────────────────────────────

@app.route('/api/schedules', methods=['GET'])
def api_get_schedules():
    """Return all saved assessment schedules, newest first."""
    try:
        docs = list(db_config.db.assessment_schedules.find(
            {}, {'_id': 1, 'bus_id': 1, 'route': 1, 'assessment_type': 1,
                 'scheduled_date': 1, 'scheduled_time': 1, 'notes': 1, 'status': 1, 'created_at': 1},
            sort=[('created_at', -1)]
        ))
        for d in docs:
            d['id'] = str(d.pop('_id'))
            if d.get('created_at'):
                d['created_at'] = d['created_at'].isoformat()
        return jsonify({'schedules': docs, 'count': len(docs)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedules', methods=['POST'])
def api_create_schedule():
    """Save a new assessment schedule entry."""
    try:
        data = request.get_json(force=True)

        bus_id          = str(data.get('bus_id', '')).strip()
        route           = str(data.get('route', '')).strip()
        assessment_type = str(data.get('assessment_type', 'Profit Analysis')).strip()
        scheduled_date  = str(data.get('scheduled_date', '')).strip()
        scheduled_time  = str(data.get('scheduled_time', '')).strip()
        notes           = str(data.get('notes', '')).strip()

        if not bus_id or not route or not scheduled_date:
            return jsonify({'error': 'bus_id, route and scheduled_date are required'}), 400

        # ── Time-aware conflict check ─────────────────────────────────────────
        new_block = get_route_block_mins(route)
        new_start = time_to_mins(scheduled_time) if scheduled_time else None

        existing_day = list(db_config.db.assessment_schedules.find({
            'bus_id': bus_id,
            'scheduled_date': scheduled_date,
            'status': {'$nin': ['Done', 'Cancelled']}
        }))
        for ex in existing_day:
            ex_route = ex.get('route', route)
            ex_block  = get_route_block_mins(ex_route)
            ex_start  = time_to_mins(ex.get('scheduled_time', ''))
            # If either side has no time → treat whole day as conflict
            if new_start is None or ex_start is None:
                t_label = f" at {scheduled_time}" if scheduled_time else ""
                return jsonify({'error':
                    f"Bus {bus_id} is already scheduled on {scheduled_date}{t_label}. "
                    f"It is busy for the full day (no time set on existing entry)."
                }), 409
            if schedules_overlap(new_start, new_block, ex_start, ex_block):
                ex_end_m = ex_start + ex_block
                ex_end   = f"{ex_end_m // 60:02d}:{ex_end_m % 60:02d}"
                return jsonify({'error':
                    f"Bus {bus_id} is still on its trip on {scheduled_date} until {ex_end} "
                    f"(route {ex_route} takes {ex_block} min round-trip). "
                    f"Schedule after {ex_end}."
                }), 409
        # ──────────────────────────────────────────────────────────────────────

        doc = {
            'bus_id': bus_id,
            'route': route,
            'assessment_type': assessment_type,
            'scheduled_date': scheduled_date,
            'scheduled_time': scheduled_time,
            'notes': notes,
            'status': 'Scheduled',
            'created_at': datetime.now()
        }
        result = db_config.db.assessment_schedules.insert_one(doc)
        doc.pop('_id', None)   # remove ObjectId added by PyMongo — not JSON serializable

        return jsonify({
            'success': True,
            'id': str(result.inserted_id),
            'message': f'Assessment scheduled for {scheduled_date}',
            'schedule': {**doc, 'id': str(result.inserted_id), 'created_at': doc['created_at'].isoformat()}
        }), 201

    except Exception as e:
        print(f"[create_schedule] Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedules/<schedule_id>', methods=['PATCH'])
def api_update_schedule(schedule_id):
    """Update schedule fields: status, bus_id, route, scheduled_date, scheduled_time."""
    try:
        from bson import ObjectId
        data = request.get_json(force=True)

        update_fields = {'updated_at': datetime.now()}

        # Allow updating any of these fields if provided
        for field in ('status', 'bus_id', 'route', 'assessment_type', 'scheduled_date', 'scheduled_time', 'notes'):
            if field in data:
                update_fields[field] = str(data[field]).strip()

        # ── Time-aware conflict check on PATCH ────────────────────────────────
        new_bus_id  = update_fields.get('bus_id')
        new_date    = update_fields.get('scheduled_date')
        new_time    = update_fields.get('scheduled_time')
        new_status  = update_fields.get('status', '')
        upd_route   = update_fields.get('route')
        if new_bus_id and new_date and new_status not in ('Done', 'Cancelled'):
            # Resolve final route (may be changing)
            current_doc = db_config.db.assessment_schedules.find_one({'_id': ObjectId(schedule_id)})
            final_route  = upd_route or (current_doc.get('route', '') if current_doc else '')
            final_time   = new_time or (current_doc.get('scheduled_time', '') if current_doc else '')
            new_block    = get_route_block_mins(final_route)
            new_start    = time_to_mins(final_time) if final_time else None

            existing_day = list(db_config.db.assessment_schedules.find({
                '_id':            {'$ne': ObjectId(schedule_id)},
                'bus_id':         new_bus_id,
                'scheduled_date': new_date,
                'status':         {'$nin': ['Done', 'Cancelled']}
            }))
            for ex in existing_day:
                ex_route  = ex.get('route', final_route)
                ex_block  = get_route_block_mins(ex_route)
                ex_start  = time_to_mins(ex.get('scheduled_time', ''))
                if new_start is None or ex_start is None:
                    return jsonify({'error':
                        f"Bus {new_bus_id} already has a schedule on {new_date} with no time set. "
                        "Please add a time to both schedules."
                    }), 409
                if schedules_overlap(new_start, new_block, ex_start, ex_block):
                    ex_end_m = ex_start + ex_block
                    ex_end   = f"{ex_end_m // 60:02d}:{ex_end_m % 60:02d}"
                    return jsonify({'error':
                        f"Bus {new_bus_id} is still on its trip on {new_date} until {ex_end} "
                        f"({ex_route} takes {ex_block} min). Schedule after {ex_end}."
                    }), 409
        # ──────────────────────────────────────────────────────────────────────

        # When marking Done, log a trip completion event
        if update_fields.get('status') == 'Done':
            schedule = db_config.db.assessment_schedules.find_one({'_id': ObjectId(schedule_id)})
            if schedule:
                try:
                    db_config.db.completed_trips.insert_one({
                        'schedule_id': schedule_id,
                        'bus_id': schedule.get('bus_id', ''),
                        'route': schedule.get('route', ''),
                        'scheduled_date': schedule.get('scheduled_date', ''),
                        'scheduled_time': schedule.get('scheduled_time', ''),
                        'completed_at': datetime.now(),
                        'assessment_type': schedule.get('assessment_type', 'Profit Analysis')
                    })
                except Exception:
                    pass  # best-effort

        db_config.db.assessment_schedules.update_one(
            {'_id': ObjectId(schedule_id)},
            {'$set': update_fields}
        )
        return jsonify({'success': True, 'id': schedule_id, 'updated': update_fields})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/schedules/<schedule_id>', methods=['DELETE'])
def api_delete_schedule(schedule_id):
    """Delete a schedule entry."""
    try:
        from bson import ObjectId
        db_config.db.assessment_schedules.delete_one({'_id': ObjectId(schedule_id)})
        return jsonify({'success': True, 'id': schedule_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Route Availability / Free Time Gaps ───────────────────────────────────────

@app.route('/api/free_time')
def api_free_time():
    """
    Given a route and date, compute free time gaps where no assessments are scheduled.

    Query params: route, date (YYYY-MM-DD)
    Service window: 05:00 – 22:00
    Assumed trip duration per slot: 90 minutes (configurable via TRIP_DURATION_MINS env var)
    """
    try:
        route = request.args.get('route', '').strip()
        date  = request.args.get('date', '').strip()

        if not route or not date:
            return jsonify({'error': 'route and date are required'}), 400

        trip_mins = get_route_block_mins(route)  # full round-trip block

        # Fetch all *active* (non-Done/Cancelled) schedules for this **bus fleet** on this date
        # (free_time shows availability for this route — any bus on this route)
        docs = list(db_config.db.assessment_schedules.find({
            'route': route,
            'scheduled_date': date,
            'status': {'$nin': ['Done', 'Cancelled']}
        }))

        booked = []
        for doc in docs:
            t = doc.get('scheduled_time', '')
            if not t:
                continue
            start_m = time_to_mins(t)
            if start_m is not None:
                booked.append((start_m, start_m + trip_mins))

        booked.sort()

        # Service window 05:00 – 22:00 in minutes
        window_start = 5 * 60    # 300
        window_end   = 22 * 60   # 1320

        def m_to_hhmm(mins):
            h = mins // 60
            m = mins % 60
            ampm = 'AM' if h < 12 else 'PM'
            h12  = h % 12 or 12
            return f"{h12:02d}:{m:02d} {ampm}"

        gaps = []
        cursor = window_start
        for (bs, be) in booked:
            if cursor < bs:
                gaps.append({'start': m_to_hhmm(cursor), 'end': m_to_hhmm(bs)})
            cursor = max(cursor, be)
        if cursor < window_end:
            gaps.append({'start': m_to_hhmm(cursor), 'end': m_to_hhmm(window_end)})

        return jsonify({
            'route': route,
            'date': date,
            'trip_duration_mins': trip_mins,
            'booked_count': len(booked),
            'gaps': gaps
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/route_durations')
def api_route_durations():
    """Return all route one-way durations and computed block times."""
    data = {}
    for route, one_way in ROUTE_DURATIONS_ONE_WAY.items():
        block = one_way * 2 + TURNAROUND_MINS
        h_ow, m_ow   = divmod(one_way, 60)
        h_bl, m_bl   = divmod(block, 60)
        data[route] = {
            'one_way_mins':  one_way,
            'one_way_label': f"{h_ow}h {m_ow:02d}m" if m_ow else f"{h_ow}h",
            'block_mins':    block,
            'block_label':   f"{h_bl}h {m_bl:02d}m" if m_bl else f"{h_bl}h",
            'turnaround_mins': TURNAROUND_MINS
        }
    return jsonify({'durations': data})


# ── Trip History (Completed Assessments) ───────────────────────────────────────

@app.route('/api/trip_history')
def api_trip_history():
    """
    Return completed assessment trips stored in completed_trips collection.
    Supports filtering by bus_id and route.
    """
    try:
        bus_id = request.args.get('bus_id', '').strip()
        route  = request.args.get('route', '').strip()

        query = {}
        if bus_id:
            query['bus_id'] = bus_id
        if route:
            query['route'] = route

        docs = list(db_config.db.completed_trips.find(
            query, sort=[('completed_at', -1)], limit=100
        ))
        for d in docs:
            d['id'] = str(d.pop('_id'))
            if d.get('completed_at'):
                d['completed_at'] = d['completed_at'].isoformat()

        # Unique bus IDs for filter dropdown
        bus_ids = db_config.db.completed_trips.distinct('bus_id')
        routes  = db_config.db.completed_trips.distinct('route')

        return jsonify({'trips': docs, 'count': len(docs), 'bus_ids': bus_ids, 'routes': routes})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Scheduler Page (redirects to the Scheduler tab inside profit_assessment) ───

@app.route('/scheduler')
def scheduler():
    return redirect(url_for('profit_assessment') + '#sched')


# ==================== DRIVER ANOMALY & ABILITY ====================
@app.route('/driving_ability')
def driving_ability():
    return render_template('driving_ability.html')


@app.route('/driving_ab')
def driving_ab():
    return render_template('driving_ab.html')


@app.route('/driver_behavior')
def driver_behavior():
    return render_template('driver_behavior.html')


@app.route('/api/driver_scores')
def get_driver_scores():
    try:
        now = datetime.now()
        scores = {'day': 100, 'week': 100, 'month': 100, 'quarter': 100, 'annual': 100}

        def get_avg_score(start_date, end_date):
            records = list(db_config.db.driver_scores.find({'date': {'$gte': start_date, '$lte': end_date}}))
            if not records: return 100
            total = sum(r.get('score', 100) for r in records)
            return round(total / len(records))

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        scores['day'] = get_avg_score(today_start, now)
        scores['week'] = get_avg_score(today_start - timedelta(days=now.weekday()), now)
        scores['month'] = get_avg_score(today_start.replace(day=1), now)
        scores['quarter'] = get_avg_score(today_start.replace(month=((now.month - 1) // 3) * 3 + 1, day=1), now)
        scores['annual'] = get_avg_score(today_start.replace(month=1, day=1), now)

        return jsonify(scores)
    except Exception as e:
        return jsonify({'error': str(e), 'day': 100, 'week': 100, 'month': 100, 'quarter': 100, 'annual': 100})


# ==================== SIMPLE APIS ====================
@app.route('/api/system_status')
def api_system_status():
    try:
        status = {
            'server_time': datetime.now().isoformat(), 'camera_active': camera_active,
            'current_bus_turn_active': bool(current_bus_turn and current_bus_turn.get('active')),
            'socketio': 'ready', 'db_connected': True
        }
        return jsonify(status)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/passenger_history/<passenger_id>')
def get_passenger_history(passenger_id):
    journeys = list(db_config.db.journeys.find(
        {'passenger_id': passenger_id},
        sort=[('entrance_time', -1)]
    ))
    for journey in journeys:
        journey['_id'] = str(journey['_id'])
        if journey.get('entrance_time'):
            journey['entrance_time'] = journey['entrance_time'].isoformat()
        if journey.get('exit_time'):
            journey['exit_time'] = journey['exit_time'].isoformat()
        if journey.get('date'):
            try:
                journey['date'] = journey['date'].isoformat()
            except Exception:
                pass
    return jsonify({'journeys': journeys})


@app.route('/api/recent_alerts')
def get_recent_alerts():
    alerts = list(db_config.db.alerts.find(
        sort=[('timestamp', -1)],
        limit=20
    ))
    for alert in alerts:
        alert['_id'] = str(alert['_id'])
        if alert.get('timestamp'):
            alert['timestamp'] = alert['timestamp'].isoformat()
    return jsonify({'alerts': alerts})


@app.route('/api/dashboard_stats')
def get_dashboard_stats():
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    stats = {
        'total_passengers': db_config.db.passengers.count_documents({}),
        'today_journeys': db_config.db.journeys.count_documents(
            {'entrance_time': {'$gte': today_start, '$lt': tomorrow_start}}),
        'anomalies': db_config.db.alerts.count_documents({'alert_type': 'anomaly'}),
        'active_passengers': len(active_passengers)
    }
    return jsonify(stats)


@app.route('/api/active_passengers')
def api_active_passengers():
    return jsonify({
        'count': len(active_passengers),
        'passengers': list(active_passengers.keys())
    })


@app.route('/api/check_passenger/<passenger_id>')
def check_passenger(passenger_id):
    passenger = db_config.db.passengers.find_one({'passenger_id': passenger_id})
    if passenger:
        return jsonify({
            'exists': True,
            'name': passenger.get('name', 'Unknown'),
            'total_journeys': passenger.get('total_journeys', 0),
            'last_seen': passenger.get('last_seen').isoformat() if passenger.get('last_seen') else None
        })
    return jsonify({'exists': False})


# ==================== SOCKET.IO EVENTS ====================
@socketio.on('connect')
def handle_connect():
    print('Client connected (Socket.IO)')
    emit('connection_established', {'data': 'Connected to anomaly detection system'})


@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected (Socket.IO)')


# ==================== CAMERA STREAM ENDPOINTS ====================
@app.route('/video_feed')
def video_feed():
    return Response(generate_feed(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/camera/start', methods=['POST'])
def api_start_camera():
    start_camera()
    return jsonify({'success': True, 'message': 'Camera started'})


@app.route('/api/camera/stop', methods=['POST'])
def api_stop_camera():
    stop_camera()
    return jsonify({'success': True, 'message': 'Camera stopped'})


@app.route('/api/camera/status', methods=['GET'])
def api_camera_status():
    return jsonify({'active': camera_active})


@app.route('/api/camera/test', methods=['POST'])
def api_test_camera():
    try:
        frame = get_camera_frame()
        test_path = 'static/test_capture.jpg'
        cv2.imwrite(test_path, frame)
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            return jsonify({'success': False, 'error': 'JPEG encoding failed'}), 500
        img_str = base64.b64encode(buffer).decode('utf-8')
        return jsonify({
            'success': True,
            'message': 'Camera test successful',
            'image': f'data:image/jpeg;base64,{img_str}',
            'path': test_path
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== ABOUT ====================
@app.route('/about')
def about():
    return render_template('about.html')


# ==================== DRUNKARD DETECTION (Simulated) ====================
@app.route('/drunkard_level')
def drunkard_level():
    return render_template('drunkard_level.html')


@app.route('/drunkard_video_feed')
def drunkard_video_feed():
    return Response(generate_drunkard_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def generate_drunkard_frames():
    if not camera_active:
        start_camera()
    while True:
        frame = get_camera_frame()
        ret, buffer = cv2.imencode('.jpg', frame)
        if ret:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        else:
            time.sleep(0.05)
        time.sleep(0.033)


@app.route('/start_drunkard_detection', methods=['POST'])
def start_drunkard_detection():
    try:
        return jsonify({
            'success': True,
            'message': 'Drunkard detection started',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/stop_drunkard_detection', methods=['POST'])
def stop_drunkard_detection():
    return jsonify({
        'success': True,
        'message': 'Drunkard detection stopped',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/get_drunkard_data')
def get_drunkard_data():
    import random
    alcohol_level = random.uniform(0.0, 0.15)
    return jsonify({
        'alcohol_level': alcohol_level,
        'timestamp': datetime.now().isoformat(),
        'status': 'detecting'
    })


@app.route('/get_drunkard_status')
def get_drunkard_status():
    return jsonify({
        'detection_active': False,
        'timestamp': datetime.now().isoformat()
    })


# ==================== DRIVING ABILITY (Simulated) ====================
@app.route('/start_monitoring', methods=['POST'])
def start_monitoring():
    return jsonify({
        'status': 'started',
        'message': 'Monitoring started',
        'session_start': datetime.now().isoformat()
    })


@app.route('/stop_monitoring', methods=['POST'])
def stop_monitoring():
    return jsonify({
        'status': 'stopped',
        'message': 'Monitoring stopped',
        'session_end': datetime.now().isoformat()
    })


@app.route('/get_alerts')
def get_alerts_api():
    alerts = []
    import random
    if random.random() < 0.2:
        alert_types = ['LANE_DEPARTURE', 'SPEEDING', 'SUDDEN_BRAKING', 'SWERVING']
        severities = ['LOW', 'MEDIUM', 'HIGH']
        alerts.append({
            'type': random.choice(alert_types),
            'severity': random.choice(severities),
            'timestamp': datetime.now().isoformat(),
            'confidence': random.uniform(0.7, 0.99)
        })
    return jsonify({'alerts': alerts, 'total': len(alerts)})


@app.route('/get_summary')
def get_summary():
    return jsonify({
        'is_running': False,
        'session_start': datetime.now().isoformat(),
        'violations': 0,
        'high_severity': 0,
        'driving_score': 95,
        'session_duration': '00:05:00'
    })


# ==================== NATIVE WEBSOCKET AT /ws (optional) ====================
if _FLASK_SOCK_AVAILABLE:

    @sock.route('/ws')
    def ws_endpoint(ws):
        try:
            ws.send(json.dumps({
                'type': 'hello',
                'message': 'Native WebSocket connected',
                'timestamp': datetime.now().isoformat()
            }))
            while True:
                data = ws.receive()
                if data is None:
                    break
                ws.send(json.dumps({
                    'type': 'echo',
                    'received': data,
                    'timestamp': datetime.now().isoformat()
                }))
        except Exception as e:
            print(f"[ws_endpoint] WebSocket error: {e}")

else:
    @app.route('/ws', methods=['GET'])
    def http_ws_placeholder():
        return jsonify({
            'ok': False,
            'message': 'Native WebSocket not enabled. Install flask-sock + simple-websocket for /ws.',
            'hint': "For Socket.IO, use the Socket.IO client and connect to '/socket.io'."
        }), 426


# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# ==================== ML host Route ====================
@app.route("/test-embed", methods=["GET", "POST"])
def test_embed():
    if request.method == "GET":
        return '''
        <h2>Test Embed Upload</h2>
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="image" accept="image/*" required>
            <button type="submit">Upload</button>
        </form>
        '''

    if "image" not in request.files:
        return "No image uploaded", 400

    file = request.files["image"]

    if file.filename == "":
        return "No selected file", 400

    files = {
        "file": (file.filename, file.stream, file.mimetype)
    }

    try:
        response = requests.post("http://localhost:8000/embed", files=files)
        return jsonify(response.json())

    except Exception as e:
        return f"Error talking to ML API: {str(e)}", 500



# ==================== APP START ====================
if __name__ == '__main__':
    if db_config.connect():
        print("Database connected successfully")
        log_event('system_start', 'Flask application started')
        os.makedirs('static/Entrance', exist_ok=True)
        os.makedirs('static/Exit', exist_ok=True)
        socketio.run(app, host='0.0.0.0', port=5003, debug=True, allow_unsafe_werkzeug=True)
    else:
        print("Failed to connect to database")
>>>>>>> 3b4f695 (Updated passenger re-identification system, UI improvements, and driver behavior model deployment)
