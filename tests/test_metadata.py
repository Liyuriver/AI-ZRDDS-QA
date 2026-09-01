import copy
from datetime import date

from app.schemas.metadata import DocumentMetadata
from app.services.metadata.metadata_service import (
    get_document_metadata,
    list_documents,
    merge_metadata_into_chunk,
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


def test_metadata_manifest_loads_and_has_unique_keys():
    documents = list_documents()
    assert len(documents) == 5
    assert validate_metadata(documents) is True
    assert len({item.document_id for item in documents}) == 5
    assert len({item.source_file for item in documents}) == 5


def test_unknown_metadata_fields_are_valid():
    metadata = DocumentMetadata(
        document_id="doc", source_file="doc.pdf", publish_date=None,
        version=None, version_raw=None, applicable_versions=[]
    )
    assert metadata.version is None
    assert metadata.applicable_versions == []


def test_merge_does_not_mutate_original_chunk():
    metadata = get_document_metadata("zrdds_troubleshooting")
    original = {"chunk_id": "chunk-1", "content": "原文", "section": "1"}
    snapshot = copy.deepcopy(original)
    merged = merge_metadata_into_chunk(original, metadata)
    assert original == snapshot
    assert merged["content"] == original["content"]
    assert merged["document_id"] == "zrdds_troubleshooting"
    assert merged["doc_type"] == "故障排查指南"


def test_version_normalization_and_exact_match():
    assert normalize_version("V2.3.3") == "2.3.3"
    metadata = DocumentMetadata(document_id="d", source_file="d.pdf", version="2.3.3")
    assert version_matches(metadata, "2.3.3")
    assert version_status(metadata, "2.3.4") == INCOMPATIBLE


def test_x_version_range_and_three_state_unknown():
    metadata = DocumentMetadata(document_id="d", source_file="d.pdf", version="2.3.x")
    assert version_matches(metadata, "2.3.0")
    assert version_matches(metadata, "2.3.9")
    assert not version_matches(metadata, "2.4.0")

    unknown = DocumentMetadata(document_id="u", source_file="u.pdf")
    assert version_status(unknown, "2.3.3") == UNKNOWN
    assert not version_matches(unknown, "2.3.3")


def test_applicable_versions_have_priority_and_unknown_is_filtered():
    metadata = DocumentMetadata(
        document_id="d", source_file="d.pdf", version="2.3.3",
        applicable_versions=["2.4.x"],
    )
    assert version_status(metadata, "2.3.3") == INCOMPATIBLE
    assert version_status(metadata, "2.4.1") == COMPATIBLE
    unknown = DocumentMetadata(document_id="u", source_file="u.pdf")
    assert filter_by_version([metadata, unknown], "2.4.1") == [metadata]
