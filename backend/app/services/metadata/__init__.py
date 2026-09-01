"""Document metadata and version management services."""

from app.services.metadata.metadata_service import (
    get_document_metadata,
    get_metadata_by_source_file,
    list_documents,
    load_metadata,
    merge_metadata_into_chunk,
    merge_metadata_into_chunks,
    validate_metadata,
)
from app.services.metadata.version_service import (
    COMPATIBLE,
    INCOMPATIBLE,
    UNKNOWN,
    filter_by_version,
    normalize_version,
    version_matches,
    version_status,
)

__all__ = [
    "COMPATIBLE", "INCOMPATIBLE", "UNKNOWN", "filter_by_version",
    "get_document_metadata", "get_metadata_by_source_file", "list_documents",
    "load_metadata", "merge_metadata_into_chunk", "merge_metadata_into_chunks",
    "normalize_version", "validate_metadata", "version_matches", "version_status",
]

