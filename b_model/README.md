# Model Artifacts Summary

## Dataset
- **Name**: State Farm Distracted Driver Detection
- **Reliability**: 100.0%
- **Classes**: 10 distraction types
- **Samples**: 22424 training images

## Model Architecture
- **Base**: VGG16 with ImageNet weights
- **Head**: GlobalAveragePooling + Dense(10, softmax)
- **Input**: 64x64 RGB images
- **Output**: 10-class probabilities

## Performance
- **Accuracy**: 65.39%
- **Precision**: 32.62%
- **Recall**: 29.19%
- **F1-Score**: 28.35%

## Key Features
1. Transfer learning for efficient training
2. GlobalAveragePooling for parameter reduction
3. Stratified sampling for class balance
4. Comprehensive evaluation metrics

## Files Included
- Model weights (.h5)
- Label encoder (.pkl)
- Metadata and configuration (.json)
- Visualizations (.png)
- Requirements file (.txt)
