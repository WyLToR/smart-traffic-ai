from typing import Literal

from pydantic import Field

from smarttraffic_ai.detection import DetectionConfig


class DetectionProfile(DetectionConfig):
    profile_id: Literal["fast", "balanced", "detailed"] = Field(...)
    label: str
    purpose: str
    resource_estimate: str

    def apply(self, base: DetectionConfig) -> DetectionConfig:
        fields = {
            "profile_id",
            "model_path",
            "image_size",
            "confidence",
            "max_detections",
            "processing_mode",
        }
        return DetectionConfig.model_validate(
            {**base.model_dump(), **self.model_dump(include=fields)}
        )


DETECTION_PROFILES = {
    "fast": DetectionProfile(
        profile_id="fast",
        label="Villámgyors",
        model_path="models/yolo11n.pt",
        image_size=640,
        confidence=0.25,
        max_detections=300,
        purpose="Gyors kép- és videóelemzés, kisebb inferenciamérettel.",
        resource_estimate="Becsült igény: alacsony. A tényleges sebesség a géptől függ.",
    ),
    "balanced": DetectionProfile(
        profile_id="balanced",
        label="Kiegyensúlyozott",
        model_path="models/yolo26n.pt",
        image_size=960,
        confidence=0.20,
        max_detections=500,
        purpose="Általános közlekedési képek és videók feldolgozása.",
        resource_estimate="Becsült igény: közepes, CPU-n is használható.",
    ),
    "detailed": DetectionProfile(
        profile_id="detailed",
        label="Részletes",
        model_path="models/yolo26l.pt",
        image_size=1280,
        confidence=0.15,
        max_detections=1000,
        purpose="Zsúfolt jelenetek és kisebb objektumok részletesebb vizsgálata.",
        resource_estimate=(
            "Becsült igény: magas; CPU-n lassú lehet, 4 GB GPU-memória korlátozhatja."
        ),
    ),
}
