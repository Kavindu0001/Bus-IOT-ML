// Main JavaScript file for Passenger Anomaly Detection System

class AnomalyDetectionApp {
    constructor() {
        this.socket = null;
        this.cameraActive = false;
        this.currentPassengerId = null;
        this.init();
    }

    init() {
        this.initSocket();
        this.initEventListeners();
        this.initCamera();
        this.loadInitialData();
    }

    initSocket() {
        // Initialize WebSocket connection
        this.socket = io();

        this.socket.on('connect', () => {
            console.log('Connected to WebSocket server');
            this.showNotification('Connected', 'Real-time updates enabled', 'success');
        });

        this.socket.on('passenger_exit', (data) => {
            this.handlePassengerExit(data);
        });

        this.socket.on('new_alert', (data) => {
            this.handleNewAlert(data);
        });

        this.socket.on('system_update', (data) => {
            this.handleSystemUpdate(data);
        });
    }

    initEventListeners() {
        // Global event listeners
        document.addEventListener('DOMContentLoaded', () => {
            // Initialize tooltips
            this.initTooltips();

            // Initialize charts if needed
            if (typeof Chart !== 'undefined') {
                this.initCharts();
            }
        });

        // Search functionality
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.handleSearch(e.target.value);
            });
        }

        // Form submissions
        const forms = document.querySelectorAll('form[data-ajax="true"]');
        forms.forEach(form => {
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleFormSubmit(form);
            });
        });
    }

    initCamera() {
        // Camera initialization
        const videoElement = document.getElementById('cameraFeed');
        if (videoElement && navigator.mediaDevices) {
            this.startCamera().catch(console.error);
        }
    }

    async startCamera() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 640 },
                    height: { ideal: 480 },
                    facingMode: 'user'
                }
            });

            const videoElement = document.getElementById('cameraFeed');
            if (videoElement) {
                videoElement.srcObject = stream;
                this.cameraActive = true;
                console.log('Camera started successfully');
            }
        } catch (err) {
            console.error('Error accessing camera:', err);
            this.showNotification('Camera Error', 'Could not access camera', 'error');
        }
    }

    stopCamera() {
        const videoElement = document.getElementById('cameraFeed');
        if (videoElement && videoElement.srcObject) {
            const tracks = videoElement.srcObject.getTracks();
            tracks.forEach(track => track.stop());
            videoElement.srcObject = null;
            this.cameraActive = false;
            console.log('Camera stopped');
        }
    }

    captureImage() {
        return new Promise((resolve, reject) => {
            const videoElement = document.getElementById('cameraFeed');
            if (!videoElement || !this.cameraActive) {
                reject(new Error('Camera not available'));
                return;
            }

            const canvas = document.createElement('canvas');
            canvas.width = videoElement.videoWidth;
            canvas.height = videoElement.videoHeight;

            const context = canvas.getContext('2d');
            context.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

            canvas.toBlob(blob => {
                if (blob) {
                    resolve(blob);
                } else {
                    reject(new Error('Failed to capture image'));
                }
            }, 'image/jpeg', 0.9);
        });
    }

    async captureMultipleImages(count, interval = 1000) {
        const images = [];

        for (let i = 0; i < count; i++) {
            try {
                const imageBlob = await this.captureImage();
                images.push(imageBlob);

                // Show capture feedback
                this.showCaptureFeedback(i + 1, count);

                // Wait for interval except for last image
                if (i < count - 1) {
                    await this.sleep(interval);
                }
            } catch (err) {
                console.error(`Error capturing image ${i + 1}:`, err);
                throw err;
            }
        }

        return images;
    }

    showCaptureFeedback(current, total) {
        const feedbackElement = document.getElementById('captureFeedback');
        if (feedbackElement) {
            feedbackElement.innerHTML = `
                <div class="capture-feedback">
                    <i class="fas fa-camera fa-spin"></i>
                    <span>Capturing image ${current} of ${total}</span>
                </div>
            `;

            // Clear feedback after 1 second
            setTimeout(() => {
                if (feedbackElement) {
                    feedbackElement.innerHTML = '';
                }
            }, 1000);
        }
    }

    handlePassengerExit(data) {
        // Update dashboard with real-time exit information
        this.updateDashboard(data);

        // Show notification
        const alertType = data.anomaly ? 'warning' : 'success';
        const message = data.anomaly
            ? `Anomaly detected for passenger ${data.passenger_id}`
            : `Passenger ${data.passenger_id} exited normally`;

        this.showNotification('Passenger Exit', message, alertType);

        // Add to recent activities
        this.addToRecentActivities(data);
    }

    handleNewAlert(data) {
        // Add alert to alerts list
        this.addAlertToList(data);

        // Play sound for anomaly alerts
        if (data.alert_type === 'anomaly') {
            this.playAlertSound();
        }
    }

    handleSystemUpdate(data) {
        console.log('System update:', data);
        // Update system status indicators
        this.updateSystemStatus(data);
    }

    updateDashboard(data) {
        // Update statistics
        this.updateStatistics(data);

        // Update charts
        if (typeof Chart !== 'undefined') {
            this.updateCharts(data);
        }

        // Update active passengers count
        this.updateActivePassengers();
    }

    updateStatistics(data) {
        const stats = {
            'totalPassengers': data.total_passengers || 0,
            'todayJourneys': data.today_journeys || 0,
            'anomalies': data.anomalies || 0,
            'active': data.active_passengers || 0
        };

        Object.entries(stats).forEach(([key, value]) => {
            const element = document.getElementById(key);
            if (element) {
                this.animateValue(element, parseInt(element.textContent) || 0, value, 1000);
            }
        });
    }

    animateValue(element, start, end, duration) {
        let startTimestamp = null;
        const step = (timestamp) => {
            if (!startTimestamp) startTimestamp = timestamp;
            const progress = Math.min((timestamp - startTimestamp) / duration, 1);
            const value = Math.floor(progress * (end - start) + start);
            element.textContent = value;
            if (progress < 1) {
                window.requestAnimationFrame(step);
            }
        };
        window.requestAnimationFrame(step);
    }

    addAlertToList(alert) {
        const alertsList = document.getElementById('alertsList');
        if (!alertsList) return;

        const alertElement = document.createElement('div');
        alertElement.className = `alert-item alert-${alert.alert_type}`;
        alertElement.innerHTML = `
            <div class="alert-icon">
                <i class="fas ${alert.alert_type === 'anomaly' ? 'fa-exclamation-triangle' : 'fa-check-circle'}"></i>
            </div>
            <div class="alert-content">
                <div class="alert-header">
                    <span class="alert-passenger">Passenger ${alert.passenger_id}</span>
                    <span class="alert-time">${this.formatTime(new Date())}</span>
                </div>
                <div class="alert-details">
                    ${alert.alert_type === 'anomaly' ? 'ANOMALY DETECTED' : 'Normal Exit'}
                    <span class="alert-confidence">(${(alert.confidence * 100).toFixed(1)}%)</span>
                </div>
            </div>
        `;

        alertsList.insertBefore(alertElement, alertsList.firstChild);

        // Keep only last 10 alerts
        while (alertsList.children.length > 10) {
            alertsList.removeChild(alertsList.lastChild);
        }
    }

    addToRecentActivities(data) {
        const updatesLog = document.getElementById('updatesLog');
        if (!updatesLog) return;

        const updateElement = document.createElement('div');
        updateElement.className = `update-item update-${data.anomaly ? 'anomaly' : 'normal'}`;
        updateElement.innerHTML = `
            <span class="update-time">${this.formatTime(new Date())}</span>
            <span class="update-text">
                Passenger ${data.passenger_id} exited -
                ${data.anomaly ? 'ANOMALY DETECTED' : 'Normal'}
                (${(data.confidence * 100).toFixed(1)}%)
            </span>
        `;

        updatesLog.insertBefore(updateElement, updatesLog.firstChild);

        // Keep only last 10 updates
        while (updatesLog.children.length > 10) {
            updatesLog.removeChild(updatesLog.lastChild);
        }
    }

    updateSystemStatus(data) {
        const indicators = {
            'mlStatus': data.ml_models || 'loaded',
            'dbStatus': data.database || 'connected',
            'cameraStatus': data.camera || 'active',
            'processingStatus': data.processing || 'real-time'
        };

        Object.entries(indicators).forEach(([id, status]) => {
            const indicator = document.querySelector(`[data-status="${id}"]`);
            if (indicator) {
                indicator.className = `status-indicator ${status}`;
                indicator.nextElementSibling.textContent =
                    status.charAt(0).toUpperCase() + status.slice(1);
            }
        });
    }

    async handleFormSubmit(form) {
        const formData = new FormData(form);
        const submitButton = form.querySelector('button[type="submit"]');
        const originalText = submitButton ? submitButton.innerHTML : '';

        // Disable submit button
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
        }

        try {
            const response = await fetch(form.action, {
                method: form.method,
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();

            if (data.success) {
                this.showNotification('Success', data.message || 'Operation completed successfully', 'success');

                // Handle redirect if present
                if (data.redirect) {
                    setTimeout(() => {
                        window.location.href = data.redirect;
                    }, 1500);
                } else if (data.reload) {
                    setTimeout(() => {
                        window.location.reload();
                    }, 1500);
                }
            } else {
                this.showNotification('Error', data.error || 'Operation failed', 'error');
            }
        } catch (error) {
            console.error('Form submission error:', error);
            this.showNotification('Error', 'Network error occurred', 'error');
        } finally {
            // Re-enable submit button
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = originalText;
            }
        }
    }

    handleSearch(query) {
        // Implement search functionality
        const searchableItems = document.querySelectorAll('[data-searchable]');

        searchableItems.forEach(item => {
            const text = item.textContent.toLowerCase();
            const shouldShow = text.includes(query.toLowerCase());
            item.style.display = shouldShow ? '' : 'none';
        });
    }

    showNotification(title, message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <div class="notification-icon">
                <i class="fas ${this.getNotificationIcon(type)}"></i>
            </div>
            <div class="notification-content">
                <div class="notification-title">${title}</div>
                <div class="notification-message">${message}</div>
            </div>
            <button class="notification-close" onclick="this.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        `;

        // Add to notification container
        let container = document.getElementById('notificationContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notificationContainer';
            container.className = 'notification-container';
            document.body.appendChild(container);
        }

        container.appendChild(notification);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    }

    getNotificationIcon(type) {
        const icons = {
            'success': 'fa-check-circle',
            'error': 'fa-exclamation-circle',
            'warning': 'fa-exclamation-triangle',
            'info': 'fa-info-circle'
        };
        return icons[type] || 'fa-info-circle';
    }

    playAlertSound() {
        // Create and play alert sound
        const audio = new Audio('data:audio/wav;base64,UDk0FQAAAAAA');
        audio.volume = 0.3;
        audio.play().catch(console.error);
    }

    initTooltips() {
        // Initialize Bootstrap-like tooltips
        const tooltipElements = document.querySelectorAll('[data-tooltip]');
        tooltipElements.forEach(element => {
            element.addEventListener('mouseenter', (e) => {
                const tooltipText = e.target.getAttribute('data-tooltip');
                this.showTooltip(e.target, tooltipText);
            });

            element.addEventListener('mouseleave', () => {
                this.hideTooltip();
            });
        });
    }

    showTooltip(element, text) {
        let tooltip = document.getElementById('customTooltip');
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.id = 'customTooltip';
            tooltip.className = 'custom-tooltip';
            document.body.appendChild(tooltip);
        }

        const rect = element.getBoundingClientRect();
        tooltip.textContent = text;
        tooltip.style.left = `${rect.left + rect.width / 2 - tooltip.offsetWidth / 2}px`;
        tooltip.style.top = `${rect.top - tooltip.offsetHeight - 10}px`;
        tooltip.style.visibility = 'visible';
        tooltip.style.opacity = '1';
    }

    hideTooltip() {
        const tooltip = document.getElementById('customTooltip');
        if (tooltip) {
            tooltip.style.visibility = 'hidden';
            tooltip.style.opacity = '0';
        }
    }

    initCharts() {
        // Initialize charts if on dashboard
        if (document.getElementById('activityChart')) {
            this.initActivityChart();
        }

        if (document.getElementById('anomalyChart')) {
            this.initAnomalyChart();
        }
    }

    initActivityChart() {
        const ctx = document.getElementById('activityChart').getContext('2d');
        this.activityChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: Array.from({length: 24}, (_, i) => `${i}:00`),
                datasets: [{
                    label: 'Passenger Activity',
                    data: Array.from({length: 24}, () => Math.floor(Math.random() * 100)),
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)'
                        }
                    },
                    x: {
                        grid: {
                            display: false
                        }
                    }
                }
            }
        });
    }

    initAnomalyChart() {
        const ctx = document.getElementById('anomalyChart').getContext('2d');
        this.anomalyChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: ['Normal', 'Anomalies'],
                datasets: [{
                    data: [85, 15],
                    backgroundColor: ['#2ecc71', '#e74c3c'],
                    borderWidth: 2,
                    borderColor: '#ffffff'
                }]
            },
            options: {
                responsive: true,
                cutout: '70%',
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }

    updateCharts(data) {
        // Update charts with new data
        if (this.activityChart) {
            // Add new data point to activity chart
            const newData = Math.floor(Math.random() * 100);
            this.activityChart.data.datasets[0].data.push(newData);
            this.activityChart.data.datasets[0].data.shift();
            this.activityChart.update('none');
        }
    }

    loadInitialData() {
        // Load initial data for dashboard
        if (window.location.pathname === '/dashboard') {
            this.loadDashboardData();
        }
    }

    async loadDashboardData() {
        try {
            const [alertsResponse, statsResponse] = await Promise.all([
                fetch('/api/recent_alerts'),
                fetch('/api/dashboard_stats')
            ]);

            if (alertsResponse.ok) {
                const alertsData = await alertsResponse.json();
                alertsData.alerts.forEach(alert => this.addAlertToList(alert));
            }

            if (statsResponse.ok) {
                const statsData = await statsResponse.json();
                this.updateStatistics(statsData);
            }
        } catch (error) {
            console.error('Error loading dashboard data:', error);
        }
    }

    updateActivePassengers() {
        // Fetch and update active passengers count
        fetch('/api/active_passengers')
            .then(response => response.json())
            .then(data => {
                const element = document.getElementById('activePassengers');
                if (element) {
                    this.animateValue(element, parseInt(element.textContent) || 0, data.count, 500);
                }
            })
            .catch(console.error);
    }

    formatTime(date) {
        return date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    }

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    window.app = new AnomalyDetectionApp();
});

// Utility functions
function showLoading() {
    document.body.classList.add('loading');
}

function hideLoading() {
    document.body.classList.remove('loading');
}

function confirmAction(message) {
    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.className = 'confirmation-modal';
        modal.innerHTML = `
            <div class="confirmation-content">
                <p>${message}</p>
                <div class="confirmation-actions">
                    <button class="btn btn-secondary" id="confirmCancel">Cancel</button>
                    <button class="btn btn-primary" id="confirmOk">OK</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        document.getElementById('confirmCancel').onclick = () => {
            modal.remove();
            resolve(false);
        };

        document.getElementById('confirmOk').onclick = () => {
            modal.remove();
            resolve(true);
        };
    });
}

// Global helper functions
function toggleCamera() {
    if (window.app.cameraActive) {
        window.app.stopCamera();
    } else {
        window.app.startCamera();
    }
}

function captureTestImage() {
    window.app.captureImage()
        .then(blob => {
            console.log('Image captured:', blob);
            window.app.showNotification('Success', 'Test image captured', 'success');
        })
        .catch(err => {
            console.error('Capture failed:', err);
            window.app.showNotification('Error', 'Failed to capture image', 'error');
        });
}
// Camera functionality for capture page
let cameraStream = null;
let capturedImages = [];
let isCapturing = false;

async function startCamera() {
    try {
        // Request camera with better constraints
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 1280 },
                height: { ideal: 720 },
                facingMode: 'environment', // Use rear camera if available
                frameRate: { ideal: 30 }
            },
            audio: false
        });

        const videoElement = document.getElementById('cameraPreview');
        videoElement.srcObject = cameraStream;
        videoElement.play();

        // Update button states
        document.getElementById('startCameraBtn').disabled = true;
        document.getElementById('stopCameraBtn').disabled = false;
        document.getElementById('captureBtn').disabled = false;
        document.getElementById('autoCaptureBtn').disabled = false;

        showStatus('Camera started successfully', 'success');

    } catch (error) {
        console.error('Error accessing camera:', error);
        showStatus('Failed to access camera: ' + error.message, 'error');

        // Try with less restrictive constraints
        if (error.name === 'OverconstrainedError') {
            try {
                cameraStream = await navigator.mediaDevices.getUserMedia({
                    video: true,
                    audio: false
                });

                const videoElement = document.getElementById('cameraPreview');
                videoElement.srcObject = cameraStream;
                videoElement.play();

                document.getElementById('startCameraBtn').disabled = true;
                document.getElementById('stopCameraBtn').disabled = false;
                document.getElementById('captureBtn').disabled = false;
                document.getElementById('autoCaptureBtn').disabled = false;

                showStatus('Camera started with default settings', 'success');
            } catch (fallbackError) {
                showStatus('Cannot access camera: ' + fallbackError.message, 'error');
            }
        }
    }
}

function stopCamera() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => {
            track.stop();
        });
        cameraStream = null;

        const videoElement = document.getElementById('cameraPreview');
        videoElement.srcObject = null;

        // Update button states
        document.getElementById('startCameraBtn').disabled = false;
        document.getElementById('stopCameraBtn').disabled = true;
        document.getElementById('captureBtn').disabled = true;
        document.getElementById('autoCaptureBtn').disabled = true;

        showStatus('Camera stopped', 'info');
    }
}

function captureImage() {
    if (!cameraStream) {
        showStatus('Please start camera first', 'error');
        return;
    }

    const videoElement = document.getElementById('cameraPreview');
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');

    // Set canvas dimensions to match video
    canvas.width = videoElement.videoWidth;
    canvas.height = videoElement.videoHeight;

    // Draw current video frame
    context.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

    // Convert to blob
    canvas.toBlob(function(blob) {
        if (blob) {
            const imageUrl = URL.createObjectURL(blob);
            const timestamp = new Date();

            capturedImages.push({
                blob: blob,
                url: imageUrl,
                timestamp: timestamp.toLocaleTimeString(),
                dataUrl: canvas.toDataURL('image/jpeg', 0.9)
            });

            updateCapturedImages();
            updateProgress();

            showStatus(`Image ${capturedImages.length} captured successfully`, 'success');

            // Check if we have enough images
            const requiredImages = parseInt(document.getElementById('captureProgress').textContent.split('/')[1]) || 4;
            if (capturedImages.length >= requiredImages) {
                document.getElementById('submitBtn').disabled = false;
                showStatus(`All ${requiredImages} images captured. Ready to submit.`, 'success');
            }
        }
    }, 'image/jpeg', 0.9);
}

async function autoCapture() {
    if (!cameraStream) {
        showStatus('Please start camera first', 'error');
        return;
    }

    const requiredImages = parseInt(document.getElementById('captureProgress').textContent.split('/')[1]) || 4;

    if (capturedImages.length >= requiredImages) {
        showStatus(`Already captured ${requiredImages} images`, 'warning');
        return;
    }

    isCapturing = true;
    document.getElementById('captureBtn').disabled = true;
    document.getElementById('autoCaptureBtn').disabled = true;
    document.getElementById('stopCameraBtn').disabled = true;

    const countdownElement = document.getElementById('countdown');

    // Clear existing images if starting fresh
    if (capturedImages.length === 0) {
        capturedImages = [];
        document.getElementById('imagesGrid').innerHTML = '';
    }

    for (let i = capturedImages.length; i < requiredImages; i++) {
        if (!isCapturing) break;

        // Countdown sequence
        for (let j = 3; j > 0; j--) {
            countdownElement.textContent = `Capturing image ${i + 1} in ${j}...`;
            await sleep(1000);
            if (!isCapturing) break;
        }

        if (!isCapturing) break;

        countdownElement.textContent = 'Capturing...';
        captureImage();
        await sleep(1000); // Wait between captures
    }

    countdownElement.textContent = 'Capture complete!';
    isCapturing = false;
    document.getElementById('captureBtn').disabled = false;
    document.getElementById('autoCaptureBtn').disabled = false;
    document.getElementById('stopCameraBtn').disabled = false;

    if (capturedImages.length >= requiredImages) {
        showStatus(`Auto-capture complete. ${requiredImages} images captured.`, 'success');
    }
}

function updateCapturedImages() {
    const imagesGrid = document.getElementById('imagesGrid');
    imagesGrid.innerHTML = '';

    capturedImages.forEach((img, index) => {
        const imgDiv = document.createElement('div');
        imgDiv.className = 'image-preview';
        imgDiv.innerHTML = `
            <div class="image-container">
                <img src="${img.url}" alt="Captured image ${index + 1}">
                <div class="image-overlay">
                    <span class="image-number">${index + 1}</span>
                    <span class="image-time">${img.timestamp}</span>
                    <button class="btn-remove" onclick="removeImage(${index})">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
        `;
        imagesGrid.appendChild(imgDiv);
    });
}

function updateProgress() {
    const captureProgress = document.getElementById('captureProgress');
    const requiredImages = parseInt(captureProgress.textContent.split('/')[1]) || 4;
    const progress = capturedImages.length;

    captureProgress.textContent = `${progress}/${requiredImages}`;

    if (progress >= requiredImages) {
        captureProgress.classList.add('progress-complete');
        captureProgress.classList.remove('progress-incomplete');
    } else {
        captureProgress.classList.add('progress-incomplete');
        captureProgress.classList.remove('progress-complete');
    }
}

function removeImage(index) {
    // Revoke object URL to free memory
    URL.revokeObjectURL(capturedImages[index].url);
    capturedImages.splice(index, 1);
    updateCapturedImages();
    updateProgress();

    const requiredImages = parseInt(document.getElementById('captureProgress').textContent.split('/')[1]) || 4;
    if (capturedImages.length < requiredImages) {
        document.getElementById('submitBtn').disabled = true;
    }

    showStatus(`Image ${index + 1} removed`, 'info');
}

async function submitImages() {
    const requiredImages = parseInt(document.getElementById('captureProgress').textContent.split('/')[1]) || 4;

    if (capturedImages.length < requiredImages) {
        showStatus(`Please capture ${requiredImages} images first`, 'error');
        return;
    }

    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    showStatus('Submitting images...', 'info');

    const formData = new FormData();
    const captureType = document.getElementById('captureProgress').dataset.type || 'entrance';
    const passengerId = document.getElementById('captureProgress').dataset.passengerId || 'new';

    if (captureType === 'entrance') {
        // Add passenger name
        const passengerName = document.getElementById('passengerName')?.value || 'Unknown';
        formData.append('name', passengerName);

        // Add images as files
        capturedImages.forEach((img, index) => {
            formData.append('images[]', img.blob, `entrance_${index + 1}.jpg`);
        });

        // Also add as base64 for backup
        capturedImages.forEach((img, index) => {
            formData.append('image_data[]', img.dataUrl);
        });
    } else {
        // Exit - single image
        formData.append('image', capturedImages[0].blob, 'exit.jpg');
        formData.append('image_data', capturedImages[0].dataUrl);
    }

    // Determine endpoint
    const endpoint = captureType === 'entrance'
        ? `/capture_entrance/${passengerId}`
        : `/capture_exit/${passengerId}`;

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            showStatus(data.message, 'success');

            // Clean up camera
            stopCamera();

            // Redirect after delay
            setTimeout(() => {
                if (captureType === 'exit' && data.redirect) {
                    window.location.href = data.redirect;
                } else if (captureType === 'entrance') {
                    window.location.href = '/dashboard';
                }
            }, 2000);
        } else {
            showStatus('Error: ' + data.error, 'error');
            submitBtn.disabled = false;
        }
    } catch (error) {
        showStatus('Network error: ' + error.message, 'error');
        submitBtn.disabled = false;
    }
}

// Utility functions
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function showStatus(message, type) {
    const statusMessages = document.getElementById('statusMessages');
    const statusDiv = document.createElement('div');

    const icons = {
        'success': 'fa-check-circle',
        'error': 'fa-exclamation-circle',
        'warning': 'fa-exclamation-triangle',
        'info': 'fa-info-circle'
    };

    statusDiv.className = `status-message status-${type}`;
    statusDiv.innerHTML = `
        <i class="fas ${icons[type] || 'fa-info-circle'}"></i>
        <span>${message}</span>
        <button class="btn-close" onclick="this.parentElement.remove()">
            <i class="fas fa-times"></i>
        </button>
    `;

    statusMessages.appendChild(statusDiv);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (statusDiv.parentElement) {
            statusDiv.remove();
        }
    }, 5000);
}

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
    }

    // Revoke all object URLs
    capturedImages.forEach(img => {
        URL.revokeObjectURL(img.url);
    });
});

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    updateProgress();
});