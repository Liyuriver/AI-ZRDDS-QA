"""Conservative version normalization and three-state matching."""

from typing import Any, Iterable, Mapping, Optional
import re

from backend.app.schemas.metadata import DocumentMetadata

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
UNKNOWN = "unknown"


def normalize_version(version: Optional[str]) -> Optional[str]:
    if version is None:
        return None
    value = str(version).strip()
    if not value:
        return None
    value = re.sub(r"^v", "", value, flags=re.IGNORECASE)
    return value.lower()


def _pattern_matches(pattern: str, requested: str) -> bool:
    pattern_parts = normalize_version(pattern).split(".")
    requested_parts = normalize_version(requested).split(".")
    if len(pattern_parts) != len(requested_parts):
        return False
    return all(left in {right, "x", "*"} for left, right in zip(pattern_parts, requested_parts))


def _metadata(value: Any) -> DocumentMetadata:
    if isinstance(value, DocumentMetadata):
        return value
    if isinstance(value, Mapping):
        validator = getattr(DocumentMetadata, "model_validate", None)
        return validator(value) if validator else DocumentMetadata.parse_obj(value)
    raise TypeError("expected DocumentMetadata or mapping")


def version_status(document_metadata: Any, requested_version: Optional[str]) -> str:
    metadata = _metadata(document_metadata)
    requested = normalize_version(requested_version)
    if requested is None:
        return UNKNOWN

    applicable = [normalize_version(item) for item in metadata.applicable_versions if normalize_version(item)]
    if applicable:
        return COMPATIBLE if any(_pattern_matches(item, requested) for item in applicable) else INCOMPATIBLE
    document_version = normalize_version(metadata.version)
    if document_version is not None:
        return COMPATIBLE if _pattern_matches(document_version, requested) else INCOMPATIBLE
    return UNKNOWN


def version_matches(document_metadata: Any, requested_version: Optional[str]) -> bool:
    return version_status(document_metadata, requested_version) == COMPATIBLE


def filter_by_version(documents_or_chunks: Iterable[Any], requested_version: str) -> list[Any]:
    """Keep only compatible documents/chunks; unknown entries are intentionally excluded."""
    result = []
    for item in documents_or_chunks:
        metadata = item
        if isinstance(item, Mapping) and not isinstance(item, DocumentMetadata):
            metadata = item
        if version_status(metadata, requested_version) == COMPATIBLE:
            result.append(item)
    return result
