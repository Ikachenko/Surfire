
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO

# Model and video locations
MODEL_PATH = Path("models/model.pt")
VIDEO_PATH = Path("test_videos/forest_fire.mp4")

if not MODEL_PATH.exists():
    raise FileNotFoundError(f"Model not found: {MODEL_PATH}")

if not VIDEO_PATH.exists():
    raise FileNotFoundError(f"Video not found: {VIDEO_PATH}")

# Load model
print("Loading YOLOv8 model...")
model = YOLO(str(MODEL_PATH))

# Inspect class names
print("\nMODEL CLASSES:")
for class_id, class_name in model.names.items():
    print(f"{class_id}: {class_name}")

print("\nStarting video analysis...")

# Store detection statistics
detection_counts = defaultdict(int)
highest_confidence = defaultdict(float)
frame_count = 0

# Process video
results = model.predict(
    source=str(VIDEO_PATH),
    imgsz=416,
    conf=0.25,
    vid_stride=2,
    stream=True,
    save=True,
    project=str(Path(__file__).resolve().parent / "test_output"),
    name="surfire_video_test_fast",
    exist_ok=True,
    verbose=False
)

for result in results:
    frame_count += 1

    if result.boxes is None:
        continue

    for box in result.boxes:
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        class_name = result.names[class_id]

        detection_counts[class_name] += 1

        highest_confidence[class_name] = max(
            highest_confidence[class_name],
            confidence
        )

    if frame_count % 100 == 0:
        print(f"Processed {frame_count} frames...")

# Display summary
print("\n========== SURFIRE TEST RESULTS ==========")
print(f"Frames processed: {frame_count}")

if detection_counts:
    for class_name, count in detection_counts.items():
        print(f"\nClass: {class_name}")
        print(f"Detections: {count}")
        print(f"Highest confidence: {highest_confidence[class_name]:.2%}")
else:
    print("No objects detected.")

print("\nAnnotated video saved to:")
print(Path(__file__).resolve().parent / "test_output" / "surfire_video_test_fast")
