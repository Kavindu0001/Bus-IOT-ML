import cv2
import numpy as np
import time
import threading
import queue
from datetime import datetime
import json
import os


class DrivingAbilityMonitor:
    def __init__(self):
        self.cap = None
        self.is_running = False
        self.violations = []
        self.lane_violation_count = 0
        self.start_time = None
        self.alert_queue = queue.Queue()

        # Lane detection parameters
        self.lane_width = 100  # pixels between lanes
        self.left_lane_boundary = None
        self.right_lane_boundary = None
        self.lane_center = None

        # Camera settings
        self.frame_width = 640
        self.frame_height = 480
        self.fps = 30

        # Alert thresholds
        self.violation_threshold = 3  # Minimum violations before alert
        self.min_violation_duration = 2  # seconds

        # Create output directory
        self.output_dir = "driving_alerts"
        os.makedirs(self.output_dir, exist_ok=True)

    def start_camera(self):
        """Start camera capture"""
        try:
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)

            if not self.cap.isOpened():
                print("Error: Could not open camera. Using simulated feed.")
                return False

            self.is_running = True
            self.start_time = datetime.now()
            print(f"Camera started at {self.start_time}")
            return True

        except Exception as e:
            print(f"Error starting camera: {e}")
            return False

    def stop_camera(self):
        """Stop camera capture"""
        self.is_running = False
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
        print("Camera stopped")

    def detect_lanes(self, frame):
        """Detect lane boundaries using edge detection"""
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Apply Gaussian blur
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)

            # Apply Canny edge detection
            edges = cv2.Canny(blurred, 50, 150)

            # Create region of interest (ROI) - focus on bottom half
            height, width = edges.shape
            mask = np.zeros_like(edges)

            # Define polygon for ROI (trapezoidal shape for road)
            polygon = np.array([[
                (width * 0.1, height),
                (width * 0.4, height * 0.6),
                (width * 0.6, height * 0.6),
                (width * 0.9, height)
            ]], np.int32)

            cv2.fillPoly(mask, polygon, 255)
            roi = cv2.bitwise_and(edges, mask)

            # Detect lines using Hough Transform
            lines = cv2.HoughLinesP(roi, 1, np.pi / 180, 50,
                                    minLineLength=50, maxLineGap=100)

            left_lines = []
            right_lines = []

            if lines is not None:
                for line in lines:
                    x1, y1, x2, y2 = line[0]

                    # Calculate slope
                    if x2 - x1 == 0:
                        continue

                    slope = (y2 - y1) / (x2 - x1)

                    # Filter lines based on slope and position
                    if abs(slope) > 0.3:  # Filter horizontal lines
                        if slope < 0 and x1 < width / 2 and x2 < width / 2:
                            left_lines.append(line[0])
                        elif slope > 0 and x1 > width / 2 and x2 > width / 2:
                            right_lines.append(line[0])

            return left_lines, right_lines, roi

        except Exception as e:
            print(f"Error in lane detection: {e}")
            return [], [], None

    def calculate_lane_boundaries(self, left_lines, right_lines, width):
        """Calculate lane boundaries from detected lines"""
        try:
            left_lane = None
            right_lane = None

            if left_lines:
                # Average left lane lines
                left_x = []
                left_y = []
                for line in left_lines:
                    left_x.extend([line[0], line[2]])
                    left_y.extend([line[1], line[3]])

                if left_x:
                    # Fit polynomial
                    poly = np.polyfit(left_y, left_x, 1)
                    left_lane = poly

            if right_lines:
                # Average right lane lines
                right_x = []
                right_y = []
                for line in right_lines:
                    right_x.extend([line[0], line[2]])
                    right_y.extend([line[1], line[3]])

                if right_x:
                    # Fit polynomial
                    poly = np.polyfit(right_y, right_x, 1)
                    right_lane = poly

            # Set lane boundaries
            if left_lane is not None:
                self.left_lane_boundary = left_lane
            if right_lane is not None:
                self.right_lane_boundary = right_lane

            # Calculate lane center
            if self.left_lane_boundary is not None and self.right_lane_boundary is not None:
                # Calculate at bottom of frame
                y = self.frame_height
                left_x = np.polyval(self.left_lane_boundary, y)
                right_x = np.polyval(self.right_lane_boundary, y)
                self.lane_center = (left_x + right_x) / 2
            else:
                # Use default center if lanes not detected
                self.lane_center = width / 2

        except Exception as e:
            print(f"Error calculating lane boundaries: {e}")
            self.lane_center = width / 2

    def check_lane_violation(self, vehicle_position, frame):
        """Check if vehicle has crossed lane boundaries"""
        try:
            if self.left_lane_boundary is None or self.right_lane_boundary is None:
                return False, "No lane detected"

            # Calculate lane boundaries at vehicle position
            left_boundary = np.polyval(self.left_lane_boundary, vehicle_position[1])
            right_boundary = np.polyval(self.right_lane_boundary, vehicle_position[1])

            # Check if vehicle is outside lane boundaries
            if vehicle_position[0] < left_boundary - 10:  # Left violation with margin
                violation_type = "LEFT_LANE_VIOLATION"
                severity = "HIGH"
                return True, (violation_type, severity, left_boundary)

            elif vehicle_position[0] > right_boundary + 10:  # Right violation with margin
                violation_type = "RIGHT_LANE_VIOLATION"
                severity = "HIGH"
                return True, (violation_type, severity, right_boundary)

            # Check for lane departure (approaching boundary)
            elif vehicle_position[0] < left_boundary + 20:  # Close to left boundary
                violation_type = "LANE_DEPARTURE_LEFT"
                severity = "MEDIUM"
                return True, (violation_type, severity, left_boundary)

            elif vehicle_position[0] > right_boundary - 20:  # Close to right boundary
                violation_type = "LANE_DEPARTURE_RIGHT"
                severity = "MEDIUM"
                return True, (violation_type, severity, right_boundary)

            return False, "Within lane"

        except Exception as e:
            print(f"Error checking lane violation: {e}")
            return False, f"Error: {str(e)}"

    def detect_vehicle(self, frame):
        """Simple vehicle detection (placeholder for actual ML model)"""
        try:
            # For demo purposes, use a fixed position
            # In real implementation, use YOLO or other object detection

            # Using simple center of frame as vehicle position
            height, width = frame.shape[:2]
            vehicle_center = (width // 2, height * 0.8)  # Bottom center

            # Draw vehicle detection box for visualization
            box_size = 60
            cv2.rectangle(frame,
                          (vehicle_center[0] - box_size // 2, vehicle_center[1] - box_size // 2),
                          (vehicle_center[0] + box_size // 2, vehicle_center[1] + box_size // 2),
                          (0, 255, 255), 2)

            return vehicle_center

        except Exception as e:
            print(f"Error in vehicle detection: {e}")
            return (self.frame_width // 2, self.frame_height * 0.8)

    def save_violation(self, violation_type, severity, frame, vehicle_position):
        """Save violation data and screenshot"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

            # Save violation data
            violation_data = {
                "timestamp": timestamp,
                "violation_type": violation_type,
                "severity": severity,
                "vehicle_position": vehicle_position,
                "lane_center": self.lane_center,
                "duration": (datetime.now() - self.start_time).total_seconds()
            }

            # Save JSON data
            json_path = os.path.join(self.output_dir, f"violation_{timestamp}.json")
            with open(json_path, 'w') as f:
                json.dump(violation_data, f, indent=4)

            # Save screenshot
            screenshot_path = os.path.join(self.output_dir, f"violation_{timestamp}.jpg")
            cv2.imwrite(screenshot_path, frame)

            # Add to violations list
            self.violations.append(violation_data)

            # Add to alert queue
            self.alert_queue.put({
                "type": violation_type,
                "severity": severity,
                "timestamp": timestamp,
                "screenshot": screenshot_path
            })

            print(f"Violation recorded: {violation_type} - {severity}")
            return violation_data

        except Exception as e:
            print(f"Error saving violation: {e}")
            return None

    def generate_alert_sound(self, severity):
        """Generate alert sound based on severity"""
        try:
            # Platform-specific sound generation
            import platform
            system = platform.system()

            if system == "Windows":
                import winsound
                if severity == "HIGH":
                    winsound.Beep(1000, 500)  # High-pitched long beep
                elif severity == "MEDIUM":
                    winsound.Beep(800, 300)  # Medium beep
                else:
                    winsound.Beep(600, 200)  # Low beep

            elif system == "Darwin":  # macOS
                import os
                if severity == "HIGH":
                    os.system('say "Lane violation detected"')
                else:
                    os.system('say "Warning"')

            elif system == "Linux":
                import os
                os.system(f'echo -e "\a"')  # Terminal bell

        except:
            pass  # Silently fail if sound not available

    def draw_lanes(self, frame, left_lines, right_lines):
        """Draw detected lanes on frame"""
        try:
            height, width = frame.shape[:2]

            # Draw detected lines
            if left_lines:
                for line in left_lines:
                    x1, y1, x2, y2 = line
                    cv2.line(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)

            if right_lines:
                for line in right_lines:
                    x1, y1, x2, y2 = line
                    cv2.line(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)

            # Draw lane boundaries if calculated
            if self.left_lane_boundary is not None and self.right_lane_boundary is not None:
                # Draw left boundary
                y1, y2 = height, int(height * 0.6)
                x1 = int(np.polyval(self.left_lane_boundary, y1))
                x2 = int(np.polyval(self.left_lane_boundary, y2))
                cv2.line(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)

                # Draw right boundary
                x1 = int(np.polyval(self.right_lane_boundary, y1))
                x2 = int(np.polyval(self.right_lane_boundary, y2))
                cv2.line(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)

                # Draw lane center
                if self.lane_center:
                    cv2.line(frame, (int(self.lane_center), height),
                             (int(self.lane_center), int(height * 0.6)),
                             (255, 255, 0), 2)

            return frame

        except Exception as e:
            print(f"Error drawing lanes: {e}")
            return frame

    def run_monitoring(self):
        """Main monitoring loop"""
        print("Starting driving ability monitoring...")

        if not self.start_camera():
            print("Failed to start camera. Exiting.")
            return

        last_violation_time = None
        consecutive_violations = 0

        try:
            while self.is_running:
                ret, frame = self.cap.read()

                if not ret:
                    print("Failed to grab frame. Retrying...")
                    time.sleep(0.1)
                    continue

                # Detect lanes
                left_lines, right_lines, roi = self.detect_lanes(frame)

                # Calculate lane boundaries
                self.calculate_lane_boundaries(left_lines, right_lines, frame.shape[1])

                # Detect vehicle (simplified)
                vehicle_position = self.detect_vehicle(frame)

                # Check for lane violations
                is_violation, violation_info = self.check_lane_violation(vehicle_position, frame)

                current_time = time.time()

                if is_violation:
                    violation_type, severity, boundary = violation_info

                    # Check if this is a new violation or continuation
                    if last_violation_time and (current_time - last_violation_time < 1.0):
                        consecutive_violations += 1
                    else:
                        consecutive_violations = 1

                    last_violation_time = current_time

                    # Only save if violation persists or is severe
                    if consecutive_violations >= self.violation_threshold or severity == "HIGH":
                        # Save violation
                        violation_data = self.save_violation(violation_type, severity,
                                                             frame.copy(), vehicle_position)

                        # Generate alert sound
                        self.generate_alert_sound(severity)

                        # Reset consecutive count after saving
                        consecutive_violations = 0

                        # Draw violation alert on frame
                        cv2.putText(frame, f"ALERT: {violation_type}",
                                    (50, 50), cv2.FONT_HERSHEY_SIMPLEX,
                                    1, (0, 0, 255), 3)

                # Draw lanes and information on frame
                frame = self.draw_lanes(frame, left_lines, right_lines)

                # Display statistics
                cv2.putText(frame, f"Violations: {len(self.violations)}",
                            (10, 100), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (255, 255, 255), 2)

                cv2.putText(frame, f"Time: {datetime.now().strftime('%H:%M:%S')}",
                            (10, 130), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (255, 255, 255), 2)

                # Show frame
                cv2.imshow('Driving Ability Monitor', frame)

                # Check for exit key
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:  # 'q' or ESC
                    break

        except KeyboardInterrupt:
            print("Monitoring interrupted by user")
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
        finally:
            self.stop_camera()
            self.generate_summary_report()

    def generate_summary_report(self):
        """Generate summary report of driving session"""
        try:
            if not self.violations:
                print("No violations detected during session.")
                return

            total_duration = (datetime.now() - self.start_time).total_seconds()

            summary = {
                "session_start": self.start_time.isoformat(),
                "session_end": datetime.now().isoformat(),
                "total_duration_seconds": total_duration,
                "total_violations": len(self.violations),
                "violations_per_hour": len(self.violations) / (total_duration / 3600),
                "violations_by_type": {},
                "violations_by_severity": {},
                "all_violations": self.violations
            }

            # Count violations by type and severity
            for violation in self.violations:
                v_type = violation["violation_type"]
                severity = violation["severity"]

                summary["violations_by_type"][v_type] = summary["violations_by_type"].get(v_type, 0) + 1
                summary["violations_by_severity"][severity] = summary["violations_by_severity"].get(severity, 0) + 1

            # Save summary report
            report_path = os.path.join(self.output_dir,
                                       f"session_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(report_path, 'w') as f:
                json.dump(summary, f, indent=4)

            print(f"\n{'=' * 50}")
            print("DRIVING SESSION SUMMARY")
            print('=' * 50)
            print(f"Duration: {total_duration / 60:.1f} minutes")
            print(f"Total Violations: {len(self.violations)}")
            print(f"Violations per hour: {summary['violations_per_hour']:.1f}")
            print("\nViolations by type:")
            for v_type, count in summary["violations_by_type"].items():
                print(f"  {v_type}: {count}")
            print("\nViolations by severity:")
            for severity, count in summary["violations_by_severity"].items():
                print(f"  {severity}: {count}")
            print(f"\nDetailed report saved to: {report_path}")
            print('=' * 50)

        except Exception as e:
            print(f"Error generating summary report: {e}")

    def get_alerts(self):
        """Get pending alerts from queue"""
        alerts = []
        while not self.alert_queue.empty():
            alerts.append(self.alert_queue.get())
        return alerts


# Flask integration for web interface
def create_flask_app(monitor):
    from flask import Flask, render_template, jsonify, Response

    app = Flask(__name__)

    @app.route('/')
    def index():
        return render_template('driving_ability.html')

    @app.route('/start_monitoring')
    def start_monitoring():
        if not monitor.is_running:
            # Start monitoring in a separate thread
            threading.Thread(target=monitor.run_monitoring, daemon=True).start()
            return jsonify({'status': 'started', 'message': 'Monitoring started'})
        return jsonify({'status': 'already_running', 'message': 'Monitoring already in progress'})

    @app.route('/stop_monitoring')
    def stop_monitoring():
        monitor.is_running = False
        return jsonify({'status': 'stopped', 'message': 'Monitoring stopped'})

    @app.route('/get_alerts')
    def get_alerts():
        alerts = monitor.get_alerts()
        return jsonify({'alerts': alerts})

    @app.route('/get_summary')
    def get_summary():
        summary = {
            'violations': len(monitor.violations),
            'is_running': monitor.is_running,
            'session_duration': (datetime.now() - monitor.start_time).total_seconds() if monitor.start_time else 0
        }
        return jsonify(summary)

    @app.route('/video_feed')
    def video_feed():
        def generate():
            while monitor.is_running:
                if monitor.cap and monitor.cap.isOpened():
                    ret, frame = monitor.cap.read()
                    if ret:
                        # Encode frame as JPEG
                        ret, buffer = cv2.imencode('.jpg', frame)
                        if ret:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' +
                                   buffer.tobytes() + b'\r\n')

        return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

    return app


if __name__ == "__main__":
    # Create monitor instance
    monitor = DrivingAbilityMonitor()

    # Run directly (console mode)
    monitor.run_monitoring()

    # Or run with Flask web interface
    # app = create_flask_app(monitor)
    # app.run(host='0.0.0.0', port=5001, debug=True)