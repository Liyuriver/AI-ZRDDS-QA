"""Application configuration for the first-stage API."""

PROJECT_NAME = "ZRDDS Knowledge Base QA API"
PROJECT_VERSION = "0.1.0"
API_V1_PREFIX = "/api/v1"

# Evidence-based QA thresholds. Keep these in one place for later calibration.
CONFIDENCE_HIGH_THRESHOLD = 0.75
CONFIDENCE_LOW_THRESHOLD = 0.50
CONFIDENCE_SCORE_NORMALIZATION = "auto"  # auto: 0..1 as-is, otherwise min-max-like clamp
