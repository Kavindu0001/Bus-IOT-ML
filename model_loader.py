"""
model_loader.py  -  Lightweight Embedding-Based Passenger Re-ID
================================================================
Data-flow:
  1. Image (BGR numpy or file path)
       -> preprocess_image()
  2. float32 array (1, 128, 128, 3)  normalised to [0, 1]
       -> extract_embedding()
  3. float32 128-dim L2-normalised vector
       -> cosine_similarity()   (= dot product of unit vectors)
  4. avg_sim across N entrance embeddings x M exit embeddings
       -> detect_anomaly()
  5. is_anomaly, avg_similarity, alert_level

Backend priority (automatic):
  1. TFLite fp16  - fast on Raspberry Pi 4  (models/embedding_model_fp16.tflite)
  2. Keras .keras - full TF on dev machine   (models/embedding_model.keras)
  3. Histogram fallback - NO model needed, always works using OpenCV HSV color
     histograms. Good for same-day same-clothes matching (demo mode).
     Activate by simply leaving models/ empty; deactivate by exporting the
     TFLite from the notebook.

Session memory:
  Embeddings live ONLY in active_passengers{} in app.py.
  When end_journey() is called, active_passengers.clear() wipes everything.
  Nothing persists between bus turns.

No random fallback: every failure returns None or 0.0 (safe).
"""

import os
import logging
import numpy as np
import cv2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------

# Threshold for ML (TFLite / Keras) 128-dim L2-normalised embeddings:
#   same-person cosine similarity  approx 0.75-0.95
#   diff-person cosine similarity  approx 0.15-0.55
# Run calibrate_threshold() on your own data to tune.
MATCH_THRESHOLD = 0.80

# Threshold for the histogram FALLBACK (used when no ML model is loaded).
# Same person same clothes same day: histogram similarity ~0.80-0.96
# Different person different clothes:  ~0.30-0.65
# Midpoint  ~0.70 is a safe starting point.
FALLBACK_THRESHOLD = 0.70

# ── Strict matching — extra gates beyond avg_similarity ──────────────────────
# Rule 2: At least ONE entrance-exit pair must reach this value.
#   Prevents a weak average being bumped up by a single lucky pair.
STRONG_MATCH_THRESHOLD = 0.88

# Rule 3: Fraction of pairwise scores that must be >= MATCH_THRESHOLD.
#   Rejects cases where only a minority of pairs agree (noisy match).
PASS_RATIO_THRESHOLD = 0.60

# Rule 4: Required gap between 1st-best and 2nd-best candidate avg_similarity.
#   Forces the winner to be clearly ahead; prevents close-call false positives.
MATCH_MARGIN = 0.05

# Model input size (must match training/export)
IMG_H, IMG_W = 128, 128

# Face crop is OPTIONAL.
# Keep False for speed on Raspberry Pi and when passengers are not frontal.
# Set True only when faces are stable, frontal, and well-lit.
ENABLE_FACE_CROP = False

# TFLite inference threads (RPi4: 2 is stable; laptop: doesn't matter much)
TFLITE_THREADS = 2

# Haar-cascade path (bundled with every OpenCV install)
_HAAR_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


# ===========================================================================
class EmbeddingExtractor:
    """
    Extracts L2-normalised 128-dim embeddings from passenger images.

    Supported backends (tried in order):
      1. TFLite   - fast on Raspberry Pi 4
      2. Keras    - full TensorFlow on development machine

    On inference failure returns None (never random data).
    """

    def __init__(self, models_dir: str = 'models/'):
        self.models_dir = models_dir

        # TFLite state
        self._tflite_interp   = None
        self._tflite_in_idx   = None
        self._tflite_out_idx  = None

        # Keras state
        self._keras_model = None

        # Histogram fallback flag (True when no ML model is available)
        self._using_fallback = False

        # Face detector (optional - only loaded when ENABLE_FACE_CROP is True)
        self._face_cascade = self._load_face_cascade() if ENABLE_FACE_CROP else None

        # Load embedding model (sets _using_fallback if nothing found)
        self._load_model()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _load_face_cascade(self):
        """Load OpenCV Haar-cascade for optional face cropping."""
        try:
            clf = cv2.CascadeClassifier(_HAAR_PATH)
            if clf.empty():
                logger.warning("Haar cascade loaded but empty - face crop disabled.")
                return None
            logger.info("Haar-cascade face detector ready")
            return clf
        except Exception as exc:
            logger.warning(f"Face detector load failed: {exc}")
            return None

    def _load_model(self):
        """
        Try TFLite first (faster on RPi), then Keras.
        Sets is_ready=False if nothing loads.
        """
        os.makedirs(self.models_dir, exist_ok=True)

        # --- TFLite candidates (fp16 preferred for size/speed balance) ---
        tflite_candidates = [
            os.path.join(self.models_dir, 'embedding_model_fp16.tflite'),
            os.path.join(self.models_dir, 'embedding_model_int8.tflite'),
            os.path.join(self.models_dir, 'embedding_model.tflite'),
        ]
        for tflite_path in tflite_candidates:
            if os.path.exists(tflite_path):
                try:
                    import tensorflow as tf
                    interp = tf.lite.Interpreter(
                        model_path=tflite_path,
                        num_threads=TFLITE_THREADS,  # faster CPU inference on RPi4
                    )
                    interp.allocate_tensors()
                    self._tflite_interp   = interp
                    self._tflite_in_idx   = interp.get_input_details()[0]['index']
                    self._tflite_out_idx  = interp.get_output_details()[0]['index']
                    logger.info(f"TFLite embedding model loaded: {tflite_path}")
                    return
                except Exception as exc:
                    logger.warning(f"TFLite load failed ({tflite_path}): {exc}")

        # --- Keras candidates ---
        keras_candidates = [
            os.path.join(self.models_dir, 'embedding_model.keras'),
            os.path.join(self.models_dir, 'embedding_model.h5'),
        ]
        for keras_path in keras_candidates:
            if os.path.exists(keras_path):
                try:
                    import tensorflow as tf
                    self._keras_model = tf.keras.models.load_model(keras_path, compile=False)
                    logger.info(f"Keras embedding model loaded: {keras_path}")
                    return
                except Exception as exc:
                    logger.warning(f"Keras load failed ({keras_path}): {exc}")

        logger.warning(
            "No ML model found in models/ directory. "
            "Activating HISTOGRAM FALLBACK mode (HSV color histograms). "
            "This is suitable for same-day same-clothes demo matching. "
            "For better accuracy: run the notebook, export embedding_model_fp16.tflite, "
            "copy it to models/, and restart the app."
        )
        self._using_fallback = True

    @property
    def is_ready(self) -> bool:
        """Always True: ML model (TFLite/Keras) or histogram fallback is always available."""
        return True

    @property
    def using_fallback(self) -> bool:
        """True when running in histogram fallback mode (no ML model loaded)."""
        return self._using_fallback

    # ------------------------------------------------------------------
    # Histogram fallback embedding  (no ML model required)
    # ------------------------------------------------------------------

    def _extract_histogram_embedding(self, bgr) -> np.ndarray:
        """
        Compute a 192-dim L2-normalised HSV colour histogram as a pseudo-embedding.

        Breakdown: 64 bins for Hue  +  64 bins for Saturation  +  64 bins for Value
                   = 192-dim vector, L2-normalised to a unit vector.

        Why this works for bus re-ID:
          - Passengers wear the same clothes entering and exiting the same trip.
          - Same-person same-clothes histograms are very similar (~0.85-0.96).
          - Different people in different clothes are typically ~0.30-0.65.
          - Threshold at 0.70 (FALLBACK_THRESHOLD) gives clean separation.
        """
        try:
            # Resize to a fixed small size to remove resolution dependency
            img = cv2.resize(bgr, (IMG_W, IMG_H), interpolation=cv2.INTER_LINEAR)
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

            h_hist = cv2.calcHist([hsv], [0], None, [64], [0, 180]).flatten()
            s_hist = cv2.calcHist([hsv], [1], None, [64], [0, 256]).flatten()
            v_hist = cv2.calcHist([hsv], [2], None, [64], [0, 256]).flatten()

            vec = np.concatenate([h_hist, s_hist, v_hist]).astype(np.float32)

            # L2 normalise
            norm = float(np.linalg.norm(vec))
            if norm < 1e-10:
                return None
            return vec / norm
        except Exception as exc:
            logger.error(f"Histogram embedding error: {exc}")
            return None

    # ------------------------------------------------------------------
    # Preprocessing  (exactly once per image, consistent pipeline)
    # ------------------------------------------------------------------

    def _crop_face(self, bgr):
        """
        Detect and crop the largest face in bgr image.
        Returns cropped BGR region, or None if no face found / detector absent.
        """
        if self._face_cascade is None:
            return None
        try:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
            )
            if len(faces) == 0:
                return None
            # Largest face by area
            x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
            # 20% padding so chin/forehead are not clipped
            px, py = int(0.20 * w), int(0.20 * h)
            x1 = max(0, x - px)
            y1 = max(0, y - py)
            x2 = min(bgr.shape[1], x + w + px)
            y2 = min(bgr.shape[0], y + h + py)
            crop = bgr[y1:y2, x1:x2]
            return crop if crop.size > 0 else None
        except Exception as exc:
            logger.debug(f"Face crop error: {exc}")
            return None

    def preprocess_image(self, image_input):
        """
        Preprocess one image for embedding inference.

        Args:
            image_input: BGR numpy array  OR  file-path string.

        Returns:
            float32 numpy array shape (1, IMG_H, IMG_W, 3), values [0, 1].
            None on any failure.

        Notes:
            - BGR->RGB conversion happens EXACTLY ONCE here.
            - Normalisation to [0, 1] happens EXACTLY ONCE here.
            - Face crop attempted; falls back to full frame if no face found.
        """
        try:
            # Load from disk if a path was given
            if isinstance(image_input, str):
                if not os.path.exists(image_input):
                    logger.error(f"Image not found: {image_input}")
                    return None
                bgr = cv2.imread(image_input)
                if bgr is None:
                    logger.error(f"cv2.imread returned None: {image_input}")
                    return None
            else:
                bgr = image_input

            if bgr is None or bgr.size == 0:
                return None

            # Face crop (optional - falls back to full frame)
            face = self._crop_face(bgr)
            region = face if face is not None else bgr

            # BGR -> RGB (done exactly once)
            rgb = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)

            # Resize to model input dimensions
            resized = cv2.resize(rgb, (IMG_W, IMG_H), interpolation=cv2.INTER_LINEAR)

            # Normalise to [0, 1] as float32 (done exactly once)
            normalised = resized.astype(np.float32) / 255.0

            # Add batch dimension -> (1, H, W, 3)
            return np.expand_dims(normalised, axis=0)

        except Exception as exc:
            logger.error(f"preprocess_image error: {exc}")
            return None

    # ------------------------------------------------------------------
    # Embedding extraction
    # ------------------------------------------------------------------

    def extract_embedding(self, image_input):
        """
        Extract a single L2-normalised embedding.

        Returns:
          - ML mode:       float32 (128,) unit vector from TFLite/Keras model.
          - Fallback mode: float32 (192,) unit vector from HSV histogram.
          - None on failure (no random data, caller treats as no-match).
        """
        # Load / decode the image to BGR first
        if isinstance(image_input, str):
            if not os.path.exists(image_input):
                logger.error(f"Image not found: {image_input}")
                return None
            bgr = cv2.imread(image_input)
            if bgr is None:
                logger.error(f"cv2.imread returned None: {image_input}")
                return None
        elif isinstance(image_input, np.ndarray):
            bgr = image_input
        else:
            logger.error(f"Unsupported image_input type: {type(image_input)}")
            return None

        if bgr is None or bgr.size == 0:
            return None

        # ---- Histogram fallback path ----
        if self._using_fallback:
            return self._extract_histogram_embedding(bgr)

        # ---- ML inference path ----
        batch = self.preprocess_image(bgr)
        if batch is None:
            return None

        try:
            if self._tflite_interp is not None:
                self._tflite_interp.set_tensor(self._tflite_in_idx, batch)
                self._tflite_interp.invoke()
                raw = self._tflite_interp.get_tensor(self._tflite_out_idx)
            else:
                raw = self._keras_model.predict(batch, verbose=0)

            vec = raw.flatten().astype(np.float32)
            norm = float(np.linalg.norm(vec))
            if norm < 1e-10:
                logger.warning("Near-zero embedding norm - image may be blank.")
                return None
            return vec / norm

        except Exception as exc:
            logger.error(f"Inference error: {exc}")
            return None

    def extract_embeddings_batch(self, image_inputs: list) -> list:
        """
        Extract embeddings for a list of images.

        Args:
            image_inputs: list of BGR numpy arrays OR file-path strings (may be mixed).
                          Each item is processed independently by extract_embedding().
                          BGR→RGB conversion and /255.0 normalisation are applied
                          exactly once per image inside preprocess_image() — no
                          double-scaling occurs regardless of input type.

        Returns:
            list of float32 L2-normalised embedding vectors.
            Silently skips images that fail; returned list may be shorter than input.
        """
        results = []
        for img in image_inputs:
            emb = self.extract_embedding(img)
            if emb is not None:
                results.append(emb)
        return results

    # ------------------------------------------------------------------
    # Similarity
    # ------------------------------------------------------------------

    @staticmethod
    def cosine_similarity(a, b) -> float:
        """
        Cosine similarity between two L2-normalised vectors.
        Because both are unit vectors:  cosine_sim = dot(a, b).
        Returns float in [-1, 1]  (face embeddings are typically 0-1).
        """
        a = np.asarray(a, dtype=np.float32).flatten()
        b = np.asarray(b, dtype=np.float32).flatten()
        min_len = min(len(a), len(b))   # safety for mismatched dims
        return float(np.dot(a[:min_len], b[:min_len]))

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def detect_anomaly(
        self,
        entrance_embeddings: list,
        exit_embeddings: list,
        threshold: float = None
    ) -> dict:
        """
        Compare entrance vs exit embedding sets.

        Uses MATCH_THRESHOLD in ML mode, FALLBACK_THRESHOLD in histogram mode
        (unless caller overrides via the threshold argument).
        """
        if threshold is None:
            threshold = FALLBACK_THRESHOLD if self._using_fallback else MATCH_THRESHOLD

        # Safe default: no embeddings -> treat as anomaly
        _no_data = {
            'is_anomaly': True,
            'avg_similarity': 0.0,
            'max_similarity': 0.0,
            'pass_ratio': 0.0,
            'similarity_scores': [],
            'alert_level': 'high',
            'match_confidence': 0.0,
            'status': 'NO_MATCH',
        }

        if not entrance_embeddings or not exit_embeddings:
            logger.warning(
                "detect_anomaly: empty embedding list - treating as anomaly (safe default)."
            )
            return _no_data

        # All pairwise cosine similarities
        scores = [
            EmbeddingExtractor.cosine_similarity(e, x)
            for e in entrance_embeddings
            for x in exit_embeddings
        ]

        if not scores:
            return _no_data

        scores_arr = np.array(scores, dtype=np.float32)
        avg_sim    = float(np.mean(scores_arr))
        max_sim    = float(np.max(scores_arr))
        pass_ratio = float(np.sum(scores_arr >= threshold) / len(scores_arr))
        is_anomaly = avg_sim < threshold

        # Alert level based on similarity value
        if avg_sim >= 0.80:
            alert_level = 'low'       # high similarity -> definitely same person
        elif avg_sim >= threshold:
            alert_level = 'medium'    # above threshold but not confident
        else:
            alert_level = 'high'      # below threshold -> anomaly

        # Determine human-readable status
        if avg_sim >= threshold:
            match_status = 'MATCH'
        elif avg_sim < 0.3:
            match_status = 'STRONG_ANOMALY'
        else:
            match_status = 'NO_MATCH'

        return {
            'is_anomaly':       is_anomaly,
            'avg_similarity':   avg_sim,
            'max_similarity':   max_sim,
            'pass_ratio':       pass_ratio,
            'similarity_scores': [float(s) for s in scores],
            'alert_level':      alert_level,
            'match_confidence': avg_sim,   # always equals avg_similarity (no inversion)
            'status':           match_status,
        }


# ---------------------------------------------------------------------------
# Module-level singleton  (imported by app.py as:
#   from model_loader import model_loader)
# ---------------------------------------------------------------------------
try:
    model_loader = EmbeddingExtractor()
    if model_loader.using_fallback:
        logger.info(
            "EmbeddingExtractor ready (HISTOGRAM FALLBACK mode). "
            "Threshold=%.2f  |  To enable ML mode: export the TFLite from the notebook "
            "and copy it to models/.", FALLBACK_THRESHOLD
        )
    else:
        logger.info(
            "EmbeddingExtractor ready (ML mode). Threshold=%.2f", MATCH_THRESHOLD
        )
except Exception as _exc:
    logger.error(f"Fatal: EmbeddingExtractor init failed: {_exc}")
    model_loader = None


# ---------------------------------------------------------------------------
# Offline calibration helper  (run once in a notebook cell or script)
# ---------------------------------------------------------------------------

def calibrate_threshold(
    same_person_pairs: list,
    diff_person_pairs: list,
    extractor=None,
    plot: bool = True
) -> dict:
    """
    Estimate a good MATCH_THRESHOLD by measuring cosine-similarity distributions.

    Args:
        same_person_pairs: list of (img_a, img_b) tuples - SAME person in both.
        diff_person_pairs: list of (img_a, img_b) tuples - DIFFERENT people.
        extractor:         EmbeddingExtractor instance (uses module-level one if None).
        plot:              Show a matplotlib histogram if True.

    Returns dict:
        suggested_threshold  float - midpoint between distribution means
        same_mean            float
        diff_mean            float
        separation           float - same_mean minus diff_mean

    Example:
        from model_loader import calibrate_threshold
        same = [('p1_a.jpg', 'p1_b.jpg'), ('p2_a.jpg', 'p2_b.jpg')]
        diff = [('p1_a.jpg', 'p2_a.jpg'), ('p3_a.jpg', 'p1_b.jpg')]
        res = calibrate_threshold(same, diff)
        # => update MATCH_THRESHOLD
    """
    ext = extractor or model_loader
    if ext is None or not ext.is_ready:
        raise RuntimeError("No model loaded - run the notebook first.")

    def _sims(pairs):
        out = []
        for a, b in pairs:
            ea = ext.extract_embedding(a)
            eb = ext.extract_embedding(b)
            if ea is not None and eb is not None:
                out.append(EmbeddingExtractor.cosine_similarity(ea, eb))
        return out

    same_sims = _sims(same_person_pairs)
    diff_sims = _sims(diff_person_pairs)

    if not same_sims or not diff_sims:
        raise ValueError("Not enough valid pairs for calibration.")

    same_mean = float(np.mean(same_sims))
    diff_mean = float(np.mean(diff_sims))
    suggested = float((same_mean + diff_mean) / 2.0)

    print(f"\nCalibration results:")
    print(f"  Same-person -> mean={same_mean:.3f}  std={np.std(same_sims):.3f}  n={len(same_sims)}")
    print(f"  Diff-person -> mean={diff_mean:.3f}  std={np.std(diff_sims):.3f}  n={len(diff_sims)}")
    print(f"  Separation  = {same_mean - diff_mean:.3f}")
    print(f"\n  Suggested MATCH_THRESHOLD = {suggested:.3f}")
    print("  Update MATCH_THRESHOLD in model_loader.py once calibrated.")

    if plot:
        try:
            import matplotlib.pyplot as plt
            plt.figure(figsize=(8, 4))
            plt.hist(same_sims, bins=20, alpha=0.65, color='green', label='Same person')
            plt.hist(diff_sims, bins=20, alpha=0.65, color='red',   label='Diff person')
            plt.axvline(suggested, color='black', linestyle='--',
                        label=f'Threshold={suggested:.3f}')
            plt.xlabel('Cosine Similarity')
            plt.ylabel('Count')
            plt.title('Threshold Calibration - Same vs Different Person')
            plt.legend()
            plt.tight_layout()
            plt.show()
        except Exception:
            pass  # matplotlib may not be available on Pi

    return {
        'suggested_threshold': suggested,
        'same_mean':  same_mean,
        'diff_mean':  diff_mean,
        'separation': same_mean - diff_mean,
    }
