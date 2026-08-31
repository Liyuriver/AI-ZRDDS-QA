"""Load and attach document metadata without changing preprocessing artifacts."""

import copy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union

from backend.app.schemas.metadata import DocumentMetadata


METADATA_PATH = Path(__file__).resolve().parents[3] / "data" / "metadata" / "document_metadata.json"
MetadataInput = Union[DocumentMetadata, Mapping[str, Any]]


def _parse_metadata(value: Mapping[str, Any]) -> DocumentMetadata:
    validator = getattr(DocumentMetadata, "model_validate", None)
    return validator(value) if validator else DocumentMetadata.parse_obj(value)


def _dump_metadata(value: DocumentMetadata) -> dict[str, Any]:
    dumper = getattr(value, "model_dump", None)
    return dumper() if dumper else value.dict()


def load_metadata(path: Optional[Path] = None) -> list[DocumentMetadata]:
    """Load the metadata manifest, validating every entry with Pydantic."""
    manifest_path = Path(path) if path else METADATA_PATH
    with manifest_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    entries = payload.get("documents", payload) if isinstance(payload, Mapping) else payload
    if not isinstance(entries, list):
        raise ValueError("metadata manifest must contain a 'documents' list")
    return [_parse_metadata(entry) for entry in entries]


def get_document_metadata(document_id: str, path: Optional[Path] = None) -> DocumentMetadata:
    for metadata in load_metadata(path):
        if metadata.document_id == document_id:
            return metadata
    raise KeyError(f"unknown document_id: {document_id}")


def get_metadata_by_source_file(source_file: str, path: Optional[Path] = None) -> DocumentMetadata:
    for metadata in load_metadata(path):
        if metadata.source_file == source_file:
            return metadata
    raise KeyError(f"unknown source_file: {source_file}")


def list_documents(path: Optional[Path] = None) -> list[DocumentMetadata]:
    return load_metadata(path)


def validate_metadata(documents: Optional[Iterable[MetadataInput]] = None) -> bool:
    """Validate schema and uniqueness constraints; raise ValueError on failure."""
    entries = [item if isinstance(item, DocumentMetadata) else _parse_metadata(item)
               for item in (documents if documents is not None else load_metadata())]
    ids = [item.document_id for item in entries]
    files = [item.source_file for item in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("document_id values must be unique")
    if len(files) != len(set(files)):
        raise ValueError("source_file values must be unique")
    return True


def _as_metadata(metadata: MetadataInput) -> DocumentMetadata:
    return metadata if isinstance(metadata, DocumentMetadata) else _parse_metadata(metadata)


def merge_metadata_into_chunk(chunk: Mapping[str, Any], metadata: MetadataInput) -> dict[str, Any]:
    """Return a new chunk enriched with metadata; never mutate the input chunk."""
    enriched = copy.deepcopy(dict(chunk))
    metadata_dict = _dump_metadata(_as_metadata(metadata))
    enriched.update(metadata_dict)
    return enriched


def merge_metadata_into_chunks(chunks: Iterable[Mapping[str, Any]], metadata: MetadataInput) -> list[dict[str, Any]]:
    return [merge_metadata_into_chunk(chunk, metadata) for chunk in chunks]
