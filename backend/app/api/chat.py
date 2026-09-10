"""Chat API endpoints."""

import logging
import re
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repository import ConversationRepository, RepositoryError, UserRepository
from app.schemas.chat import (
    ChatData,
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
)
from app.services.ai_client import AIClient, AIServiceError
from app.services.qa.question_service import answer_question  # compatibility export for callers/tests
from app.services.conversation_service import ConversationNotFoundError, ConversationService
from app.services.retrieval.retrieval_service import retrieve_candidates
from app.services.retrieval.fusion_service import fuse_candidates
from app.services.retrieval.rerank_service import rerank
from app.services.retrieval.evidence_service import (
    analyze_evidence_support,
    answerability_summary,
    build_facet_recovery_query,
    build_required_facet_recovery_map,
    build_facet_trace,
    build_relation_recovery_query,
    boundary_answer,
    classify_boundary,
    diagnostic_stage_plan,
    effective_evidence_changed,
    extract_facet_requirements,
    facet_candidate_map,
    has_specific_query_support,
    relation_constraint_support,
    relation_coverage,
    select_evidence,
    relation_candidate_map,
    relation_support,
    relation_support_strength,
)
from app.services.user_service import UserNotFoundError
from app.services.query_rewrite_service import rewrite_query
from app.services.metadata.version_service import extract_version, normalize_version
from app.services.qa.question_service import determine_version_status, is_version_sensitive
from app.services.answer_validation_service import (
    build_evidence_grounded_fallback,
    salvage_supported_claims,
    soften_unverified_negative_claims,
    validate_answer,
)
from app.config import BM25_TOP_K, DIFY_TOP_K, RRF_K, RERANK_CANDIDATE_POOL, RERANK_TOP_N
from app.models import User
from app.api.user import get_current_user



router = APIRouter(prefix="/chat", tags=["chat"])
conversation_router = APIRouter(tags=["conversations"])
ai_client = AIClient()
logger = logging.getLogger(__name__)


def _trace_candidate(item: dict) -> dict:
    """Return identifier-preserving diagnostics without changing the candidate."""
    content = str(item.get("content") or item.get("quote") or "")
    return {
        "document_name": item.get("document") or item.get("source_file"),
        "source_file": item.get("source_file"),
        "segment_id": item.get("segment_id"),
        "chunk_id": item.get("chunk_id"),
        "position": item.get("position"),
        "rank": item.get("rank"),
        "rerank_rank": item.get("rerank_rank"),
        "evidence_rank": item.get("evidence_rank"),
        "raw_score": item.get("raw_score"),
        "fusion_score": item.get("fusion_score"),
        "rerank_score": item.get("rerank_score"),
        "retrieval_source": item.get("retrieval_source"),
        "recovery_retrieval": item.get("recovery_retrieval", False),
        "selection_recovery": item.get("selection_recovery", False),
        "recovery_relation_ids": item.get("recovery_relation_ids", []),
        "candidate_priority_class": item.get("candidate_priority_class"),
        "candidate_targets_supported": item.get("candidate_targets_supported", []),
        "selection_reason": item.get("selection_reason"),
        "content_preview": content[:500],
    }


def _candidate_id(item: dict) -> str:
    return str(item.get("segment_id") or item.get("chunk_id") or item.get("id") or "")


def _build_external_context(evidence: list[dict]) -> str:
    """Build a fresh context from the authoritative evidence selection."""
    return "\n\n".join(
        f"[证据{index}]\n"
        f"来源：{item.get('source_file', '')}\n"
        f"章节：{item.get('section', '')}\n"
        f"内容：{item.get('content', '')}"
        for index, item in enumerate(evidence, 1)
    )


def should_retry_generation(retry_effective_change: bool, negative_claim_targets: list[str] | tuple[str, ...]) -> bool:
    """Generation conflicts require a retry even when evidence IDs are stable."""
    return bool(retry_effective_change or negative_claim_targets)


def _is_evidence_refusal(answer: str) -> bool:
    """Recognize a conservative refusal without classifying its topic.

    This is used only for the response status after validation has observed a
    generation/evidence conflict.  It does not decide whether a question is
    answerable and never supplies domain facts.
    """
    return bool(re.search(
        r"(?:证据不足|无法(?:确定|判断|回答)|知识库[^。！？.!?\n]{0,40}(?:没有|未涉及|不包含|不足)|"
        r"insufficient\s+evidence|cannot\s+(?:determine|answer)|does\s+not\s+(?:contain|provide))",
        str(answer or ""),
        re.I,
    ))


def get_conversation_service(db: Session = Depends(get_db)) -> ConversationService:
    """Build the service for one request; the API layer never executes SQL."""
    return ConversationService(ConversationRepository(db), UserRepository(db))


def require_user(requested_user_id: str, current_user: User) -> None:
    if requested_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问其他用户的数据")


def require_conversation_owner(
    conversation_id: str, current_user: User, service: ConversationService
):
    conversation = service.get_conversation(conversation_id)
    if conversation.user_id != current_user.id:
        raise ConversationNotFoundError(f"会话不存在: {conversation_id}")
    return conversation


@conversation_router.post("/conversations", response_model=ConversationRead, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    try:
        require_user(payload.user_id, current_user)
        return service.create_conversation(payload.user_id, payload.version, payload.title)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepositoryError as exc:
        logger.exception(
            "Create conversation API failed: user_id=%s title=%s",
            payload.user_id,
            payload.title,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "创建会话时发生数据库错误",
                "error_type": type(exc.__cause__ or exc).__name__,
            },
        ) from exc


@conversation_router.get("/users/{user_id}/conversations", response_model=list[ConversationRead])
def list_conversations(
    user_id: str,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> list[ConversationRead]:
    try:
        require_user(user_id, current_user)
        return service.list_user_conversations(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@conversation_router.get("/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    try:
        return require_conversation_owner(conversation_id, current_user, service)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@conversation_router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    try:
        require_conversation_owner(conversation_id, current_user, service)
        return service.update_conversation_title(conversation_id, payload.title)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail="会话标题暂时无法保存") from exc


@conversation_router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> Response:
    try:
        require_conversation_owner(conversation_id, current_user, service)
        service.delete_conversation(conversation_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(status_code=503, detail="会话暂时无法删除") from exc


@conversation_router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=201,
)
def add_message(
    conversation_id: str,
    payload: MessageCreate,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> MessageRead:
    try:
        require_conversation_owner(conversation_id, current_user, service)
        return service.add_message(conversation_id, payload.role, payload.content)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@conversation_router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageRead],
)
def get_messages(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
) -> list[MessageRead]:
    try:
        require_conversation_owner(conversation_id, current_user, service)
        return service.get_conversation_messages(conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None),
    response: Response = None,
) -> ChatResponse:
    """Persist both sides of a chat turn and return the stable API envelope."""
    request_id = x_request_id if isinstance(x_request_id, str) and x_request_id else str(uuid4())
    if response is not None:
        response.headers["X-Request-ID"] = request_id
    logger.warning("chat_trace request_id=%s stage=request question=%r conversation_id=%s user_id=%s",
                request_id, request.question, request.conversation_id, request.user_id)
    try:
        require_user(request.user_id, current_user)
        if request.conversation_id:
            conversation = require_conversation_owner(
                request.conversation_id, current_user, conversation_service
            )
            conversation_id = conversation.id
        else:
            conversation = conversation_service.create_conversation(
                request.user_id,
                request.version,
            )
            conversation_id = conversation.id

        rewritten = rewrite_query(request.question)
        facet_requirements = extract_facet_requirements(request.question, rewritten)
        detected_version = extract_version(request.question)
        requested_version = normalize_version(request.version or detected_version)
        diagnostic_plan = diagnostic_stage_plan(request.question)
        facet_diagnostics = facet_requirements.get("facet_diagnostics", {})
        logger.warning(
            "chat_trace request_id=%s stage=facet_requirements raw_extracted_facets=%s accepted_required_facets=%s rejected_noise_facets=%s relation_facets=%s",
            request_id,
            facet_diagnostics.get("raw_extracted_facets", []),
            facet_diagnostics.get("accepted_required_facets", []),
            facet_diagnostics.get("rejected_noise_facets", []),
            facet_requirements.get("required_relation_facets", []),
        )
        logger.warning(
            "chat_trace request_id=%s stage=diagnostic_plan detected_facets=%s exact_entities=%s requested_version=%s diagnostic_stage_plan=%s",
            request_id,
            facet_requirements.get("required_facets", []),
            rewritten.technical_entities,
            requested_version,
            diagnostic_plan,
        )
        bm25_results = retrieve_candidates(
            rewritten.search_query,
            top_k=BM25_TOP_K,
            requested_version=requested_version,
        )

        dify_results = await ai_client.retrieve_knowledge(
            rewritten.search_query,
            top_k=DIFY_TOP_K,
            original_query=request.question,
        )
        logger.warning("chat_trace request_id=%s stage=dify_raw candidates=%s",
                    request_id, [_trace_candidate(item) for item in dify_results])
        logger.warning("chat_trace request_id=%s stage=bm25 candidates=%s",
                    request_id, [_trace_candidate(item) for item in bm25_results])

        required_facets = facet_requirements.get("required_facets", [])
        required_relations = facet_requirements.get("required_relation_facets", [])
        initial_candidates = bm25_results + dify_results
        missing_recovery_facets = [
            str(facet.get("id"))
            for facet in required_facets
            if not facet_candidate_map(initial_candidates, [facet]).get(str(facet.get("id")))
        ]
        relation_recovery_query = build_relation_recovery_query(
            request.question,
            required_relations,
            initial_candidates,
        )
        facet_recovery_query = build_facet_recovery_query(
            request.question, required_facets, initial_candidates
        )
        recovery_query = " ".join(dict.fromkeys(
            value for value in (relation_recovery_query, facet_recovery_query) if value
        )) or None
        recovery_bm25, recovery_dify = [], []
        recovery_support_map = {}
        recovery_facet_support_map = {}
        recovery_candidate_ids: set[str] = set()
        initial_relation_coverage = relation_coverage(initial_candidates, required_relations)
        recovery_target_relation_ids = set(initial_relation_coverage.get("recovery_target_relation_ids", []))
        recovery_target_constraints = initial_relation_coverage.get("recovery_target_constraints", {})
        required_recovery_evidence_ids: set[str] = set()
        required_recovery_target_map: dict[str, list[str]] = {}
        required_constraint_support_ids: set[str] = set()
        # A concrete compatibility rule is an answer-critical target even
        # when the first retrieval pass already found it.  Preserve one
        # strongest representative before the external reranker can evict it
        # in favor of generic status or queue-management paragraphs.
        for relation_index, relation in enumerate(required_relations):
            constraint_candidates = [
                item for item in initial_candidates
                if relation_constraint_support(item, relation)
            ]
            if constraint_candidates:
                strongest = max(
                    constraint_candidates,
                    key=lambda item: (
                        relation_support_strength(item, relation),
                        float(item.get("raw_score", 0) or 0),
                        _candidate_id(item),
                    ),
                )
                required_constraint_support_ids.add(_candidate_id(strongest))
        if recovery_query:
            # The bounded recovery pass must have enough recall to reach a
            # rule paragraph that is below the ordinary retrieval cutoff;
            # the final Evidence limit is still RERANK_TOP_N.
            recovery_top_k = max(BM25_TOP_K, RERANK_CANDIDATE_POOL * 3)
            recovery_bm25 = retrieve_candidates(recovery_query, top_k=recovery_top_k, requested_version=requested_version)
            recovery_dify = await ai_client.retrieve_knowledge(
                recovery_query, top_k=max(DIFY_TOP_K, recovery_top_k), original_query=request.question,
            )
            recovery_candidates = recovery_bm25 + recovery_dify
            relations = required_relations
            recovery_candidate_ids = {_candidate_id(item) for item in recovery_candidates}
            recovery_support_map = {
                str(index): [
                    _candidate_id(item) for item in recovery_candidates
                    if (
                        relation_constraint_support(item, relation)
                        if str(index) in set(initial_relation_coverage.get("missing_relation_constraints", []))
                        else relation_support(item, relation)
                    )
                ]
                for index, relation in enumerate(relations)
                if str(index) in recovery_target_relation_ids
            }
            recovery_facet_support_map = {
                str(facet.get("id")): [
                    _candidate_id(item) for item in recovery_candidates
                    if str(facet.get("id")) in facet_candidate_map([item], [facet]).get(str(facet.get("id")), [])
                ]
                for facet in required_facets
                if str(facet.get("id")) in missing_recovery_facets
            }
            for item in recovery_candidates:
                item["recovery_retrieval"] = True
                item["recovery_relation_ids"] = [key for key, ids in recovery_support_map.items() if _candidate_id(item) in ids]
                item["recovery_facet_ids"] = [key for key, ids in recovery_facet_support_map.items() if _candidate_id(item) in ids]
                item["recovery_candidate_ids"] = sorted(recovery_candidate_ids)
                item["recovery_support_map"] = {
                    **recovery_support_map,
                    **recovery_facet_support_map,
                }
            # Select one deterministic representative for each validated
            # recovery target.  These representatives receive reserved final
            # evidence slots; other recovery hits remain ordinary candidates.
            required_recovery_target_map = {
                key: list(values)
                for key, values in {**recovery_support_map, **recovery_facet_support_map}.items()
                if values
            }
            for target_id, candidate_ids in sorted(required_recovery_target_map.items(), key=lambda pair: str(pair[0])):
                target_candidates = [item for item in recovery_candidates if _candidate_id(item) in set(candidate_ids)]
                if target_id.isdigit() and int(target_id) < len(required_relations):
                    relation = required_relations[int(target_id)]
                    target_candidates = [item for item in target_candidates if relation_constraint_support(item, relation)]
                    required_constraint_support_ids.update(_candidate_id(item) for item in target_candidates)
                    target_candidates.sort(key=lambda item: (
                        -relation_support_strength(item, relation),
                        -float(item.get("raw_score", 0) or 0),
                        _candidate_id(item),
                    ))
                else:
                    target_candidates.sort(key=lambda item: (
                        -float(item.get("raw_score", 0) or 0),
                        _candidate_id(item),
                    ))
                if target_candidates:
                    required_recovery_evidence_ids.add(_candidate_id(target_candidates[0]))
            bm25_results.extend(recovery_bm25)
            dify_results.extend(recovery_dify)
            logger.warning("chat_trace request_id=%s stage=recovery_retrieval missing_facets=%s missing_relations=%s missing_relation_constraints=%s recovery_target_relation_ids=%s recovery_target_constraints=%s recovery_candidate_ids=%s recovery_support_map=%s query=%r bm25=%s dify=%s",
                           request_id,
                           missing_recovery_facets,
                           initial_relation_coverage.get("uncovered_relation_facets", []),
                           initial_relation_coverage.get("missing_relation_constraints", []),
                           sorted(recovery_target_relation_ids),
                           recovery_target_constraints,
                           sorted(recovery_candidate_ids),
                           {**recovery_support_map, **recovery_facet_support_map},
                           recovery_query,
                           [_trace_candidate(item) for item in recovery_bm25],
                           [_trace_candidate(item) for item in recovery_dify])

        fused = fuse_candidates(
            bm25_results,
            dify_results,
            rrf_k=RRF_K,
            top_n=None,
        )
        for item in fused:
            item_id = _candidate_id(item)
            # Fusion already carries recovery metadata through normalization
            # and source merge.  Do not infer recovery from chunk_id here:
            # chunk numbers are document-local and may collide across files.
            if item.get("recovery_retrieval"):
                item["recovery_retrieval"] = True
                item["recovery_relation_ids"] = list(item.get("recovery_relation_ids") or [key for key, ids in recovery_support_map.items() if item_id in ids])
                item["recovery_facet_ids"] = list(item.get("recovery_facet_ids") or [key for key, ids in recovery_facet_support_map.items() if item_id in ids])
                item["recovery_candidate_ids"] = sorted(recovery_candidate_ids)
                item["recovery_support_map"] = {**recovery_support_map, **recovery_facet_support_map}
        logger.warning("chat_trace request_id=%s stage=fusion candidates=%s",
                    request_id, [_trace_candidate(item) for item in fused])

        reranked = rerank(
            rewritten.search_query,
            fused,
            top_n=RERANK_CANDIDATE_POOL,
        )
        # A reranker is allowed to return a bounded pool, but it must not
        # erase recovery candidates that explicitly support a required
        # relation. Reattach only those marked candidates; ordinary recovery
        # hits remain subject to the normal pool ranking and final selector.
        reranked_ids = {_candidate_id(item) for item in reranked}
        recovery_priority_ids = set(required_recovery_evidence_ids)
        for item in fused:
            item_id = _candidate_id(item)
            if (
                item_id in (recovery_priority_ids | required_constraint_support_ids)
                and item_id not in reranked_ids
            ):
                item["rerank_score"] = float(item.get("fusion_score", 0) or 0)
                item["rerank_rank"] = len(reranked) + 1
                reranked.append(item)
                reranked_ids.add(item_id)
        logger.warning("chat_trace request_id=%s stage=rerank_candidate_pool candidate_pool_ids=%s recovery_priority_ids=%s required_recovery_evidence_ids=%s required_recovery_target_map=%s required_constraint_support_ids=%s",
                       request_id, [_candidate_id(item) for item in reranked], sorted(recovery_priority_ids),
                       sorted(required_recovery_evidence_ids), required_recovery_target_map,
                       sorted(required_constraint_support_ids))
        evidence = select_evidence(
            request.question, reranked, top_n=RERANK_TOP_N,
            requirements=facet_requirements,
            force_relation_ids=(key for key, ids in recovery_support_map.items() if ids),
            force_facet_ids=(key for key, ids in recovery_facet_support_map.items() if ids),
            preferred_candidate_ids={candidate_id for ids in required_recovery_target_map.values() for candidate_id in ids},
            recovery_support_map=required_recovery_target_map,
            required_recovery_evidence_ids=required_recovery_evidence_ids,
            required_recovery_target_map=required_recovery_target_map,
            required_constraint_support_ids=required_constraint_support_ids,
            selection_run_id=f"{request_id}:first",
        )
        reasoning_trace = analyze_evidence_support(
            request.question, evidence, facet_requirements["required_facets"],
            facet_requirements.get("required_relation_facets", []),
        )
        missing_selected_facets = [
            str(facet["id"]) for facet in required_facets
            if not facet_candidate_map(evidence, [facet]).get(str(facet["id"]))
        ]
        missing_selected_targets = list(reasoning_trace.get("uncovered_relation_facets", []))
        missing_selected_recovery = sorted(
            required_recovery_evidence_ids - {_candidate_id(item) for item in evidence}
        )
        if missing_selected_facets:
            # A facet can be present in the initial candidate pool and still
            # disappear from the bounded rerank/selection result. Build a
            # targeted recovery target from the already validated fused pool
            # instead of treating that loss as an unrecoverable retrieval
            # miss. No weaker evidence is introduced here.
            selection_recovery_map = build_required_facet_recovery_map(
                fused, required_facets, missing_selected_facets
            )
            selection_recovery_ids: set[str] = set()
            reattached_selection_recovery_ids: set[str] = set()
            reranked_ids = {_candidate_id(item) for item in reranked}
            for facet_id, candidate_ids in selection_recovery_map.items():
                if not candidate_ids:
                    continue
                recovery_facet_support_map[facet_id] = list(dict.fromkeys(candidate_ids))
                required_recovery_target_map[facet_id] = list(dict.fromkeys(candidate_ids))
                representative_id = candidate_ids[0]
                required_recovery_evidence_ids.add(representative_id)
                selection_recovery_ids.add(representative_id)
                if representative_id not in reranked_ids:
                    candidate = next(
                        (item for item in fused if _candidate_id(item) == representative_id),
                        None,
                    )
                    if candidate is not None:
                        candidate["selection_recovery"] = True
                        candidate["rerank_score"] = float(
                            candidate.get("rerank_score", 0)
                            or candidate.get("fusion_score", 0)
                            or candidate.get("raw_score", 0)
                            or 0
                        )
                        candidate["rerank_rank"] = len(reranked) + 1
                        reranked.append(candidate)
                        reranked_ids.add(representative_id)
                        reattached_selection_recovery_ids.add(representative_id)
            if selection_recovery_map:
                logger.warning(
                    "chat_trace request_id=%s stage=evidence_selection_facet_recovery missing_facets=%s recovery_support_map=%s recovery_ids=%s reattached_ids=%s",
                    request_id,
                    missing_selected_facets,
                    selection_recovery_map,
                    sorted(selection_recovery_ids),
                    sorted(reattached_selection_recovery_ids),
                )
        if reranked and (missing_selected_facets or missing_selected_targets or missing_selected_recovery):
            logger.warning(
                "chat_trace request_id=%s stage=evidence_selection_reselect reason=required_coverage_lost missing_facets=%s lost_required_targets=%s lost_required_recovery_evidence=%s",
                request_id, missing_selected_facets, missing_selected_targets, missing_selected_recovery,
            )
            evidence = select_evidence(
                request.question, reranked, top_n=RERANK_TOP_N,
                requirements=facet_requirements,
                force_relation_ids=(key for key, ids in recovery_support_map.items() if ids),
                force_facet_ids=(key for key, ids in recovery_facet_support_map.items() if ids),
                preferred_candidate_ids={candidate_id for ids in required_recovery_target_map.values() for candidate_id in ids},
                recovery_support_map=required_recovery_target_map,
                required_recovery_evidence_ids=required_recovery_evidence_ids,
                required_recovery_target_map=required_recovery_target_map,
                required_constraint_support_ids=required_constraint_support_ids,
                selection_run_id=f"{request_id}:reselect",
            )
            reasoning_trace = analyze_evidence_support(
                request.question, evidence, facet_requirements["required_facets"],
                facet_requirements.get("required_relation_facets", []),
            )
            missing_selected_facets = [
                str(facet["id"]) for facet in required_facets
                if not facet_candidate_map(evidence, [facet]).get(str(facet["id"]))
            ]
            missing_selected_targets = list(reasoning_trace.get("uncovered_relation_facets", []))
            missing_selected_recovery = sorted(
                required_recovery_evidence_ids - {_candidate_id(item) for item in evidence}
            )
            if missing_selected_facets or missing_selected_targets or missing_selected_recovery:
                logger.error(
                    "chat_trace request_id=%s stage=evidence_selection_failed missing_facets=%s lost_required_targets=%s lost_required_recovery_evidence=%s",
                    request_id, missing_selected_facets, missing_selected_targets, missing_selected_recovery,
                )
                # Missing one facet in a bounded Top-N is a coverage result,
                # not a retrieval/API failure. Keep the evidence that does
                # support the other targets and let validation/generation
                # produce a PARTIAL_ANSWER or NO_ANSWER with explicit bounds.
                logger.warning(
                    "chat_trace request_id=%s stage=evidence_selection_partial missing_facets=%s lost_required_targets=%s lost_required_recovery_evidence=%s",
                    request_id, missing_selected_facets, missing_selected_targets, missing_selected_recovery,
                )
        # Carry the already-computed generic diagnostic plan into generation.
        # This is answer-organization metadata only; it does not alter
        # Boundary classification or evidence selection.
        reasoning_trace["diagnostic_stage_plan"] = diagnostic_plan
        recovery_targets = required_recovery_target_map
        facet_trace = build_facet_trace(
            {"bm25": bm25_results, "dify": dify_results, "fusion": fused,
             "rerank": reranked, "evidence": evidence},
            facet_requirements["required_facets"],
            facet_requirements.get("required_relation_facets", []),
        )
        facet_trace.update(reasoning_trace)
        logger.warning("chat_trace request_id=%s stage=facet_coverage trace=%s", request_id, facet_trace)
        logger.warning("chat_trace request_id=%s stage=rerank candidates=%s",
                    request_id, [_trace_candidate(item) for item in reranked])
        logger.warning("chat_trace request_id=%s stage=evidence candidates=%s",
                    request_id, [_trace_candidate(item) for item in evidence])
        logger.warning("chat_trace request_id=%s stage=evidence_first first_evidence_ids=%s",
                       request_id, [_candidate_id(item) for item in evidence])
        logger.warning(
            "chat_trace request_id=%s stage=evidence_selection selection_run_id=%s required_targets_before_selection=%s required_recovery_evidence_ids=%s required_recovery_target_map=%s required_constraint_support_ids=%s final_selected_ids=%s required_targets_after_selection=%s lost_required_targets_after_selection=%s candidate_priority_class=%s candidate_score=%s candidate_targets_supported=%s selection_reason=%s",
            request_id,
            evidence[0].get("selection_run_id") if evidence else f"{request_id}:first",
            evidence[0].get("required_targets_before_selection", []) if evidence else [],
            sorted(required_recovery_evidence_ids),
            required_recovery_target_map,
            sorted(required_constraint_support_ids),
            [_candidate_id(item) for item in evidence],
            evidence[0].get("required_targets_after_selection", []) if evidence else [],
            evidence[0].get("lost_required_targets_after_selection", []) if evidence else [],
            [item.get("candidate_priority_class") for item in evidence],
            [item.get("candidate_score") for item in evidence],
            [item.get("candidate_targets_supported") for item in evidence],
            [item.get("selection_reason") for item in evidence],
        )

        logger.debug(
            "original_query=%r rewritten_query=%r rewrite_terms=%s dify_trace=%s",
            request.question,
            rewritten.search_query,
            rewritten.terms,
            ai_client.last_retrieval_trace,
        )

        logger.debug(
            "BM25 Top10=%s",
            [
                (
                    x.get("chunk_id"),
                    x.get("source_file"),
                    x.get("rank"),
                    x.get("raw_score"),
                )
                for x in bm25_results
            ],
        )

        logger.debug(
            "Dify Top10=%s",
            [
                (
                    x.get("chunk_id"),
                    x.get("source_file"),
                    x.get("rank"),
                    x.get("raw_score"),
                )
                for x in dify_results
            ],
        )

        logger.debug(
            "RRF candidates=%s",
            [
                (
                    x.get("chunk_id"),
                    x.get("source_file"),
                    x.get("fusion_score"),
                )
                for x in fused
            ],
        )
        logger.debug(
            "candidate_counts bm25=%s dify=%s before_dedup=%s after_dedup=%s removed_duplicates=%s",
            len(bm25_results), len(dify_results), len(bm25_results) + len(dify_results),
            len(fused), len(bm25_results) + len(dify_results) - len(fused),
        )

        logger.debug(
            "Rerank Top5=%s",
            [
                (
                    x.get("chunk_id"),
                    x.get("source_file"),
                    x.get("rerank_score"),
                    x.get("rerank_rank"),
                )
                for x in evidence
            ],
        )

        version_status_value = determine_version_status(
            evidence,
            ("V" + requested_version) if requested_version else None,
            is_version_sensitive(request.question, evidence),
        )
        boundary_type = classify_boundary(
            request.question,
            evidence,
            required_facets,
            # A version supplied only as an API filter is handled by the
            # normal version decision service.  Strict VERSION-GAP is a
            # question semantic boundary when the user explicitly asks for
            # that version in the wording.
            requested_version=requested_version if detected_version else None,
            version_status_value=version_status_value,
        )
        answerability = answerability_summary(
            request.question,
            evidence,
            required_facets,
            facet_requirements.get("auxiliary_facets", []),
        )
        reasoning_trace.update(answerability)
        logger.warning(
            "chat_trace request_id=%s stage=answerability detected_facets=%s core_facets=%s optional_facets=%s evidence_by_facet=%s covered_facets=%s partially_covered_facets=%s uncovered_facets=%s boundary_by_facet=%s overall_boundary=%s answerable_facets=%s unanswerable_facets=%s answerability_status=%s",
            request_id,
            answerability["detected_facets"],
            answerability["core_facets"],
            answerability["optional_facets"],
            answerability["evidence_by_facet"],
            answerability["covered_facets"],
            answerability["partially_covered_facets"],
            answerability["uncovered_facets"],
            answerability["boundary_by_facet"],
            answerability["overall_boundary"],
            answerability["answerable_facets"],
            answerability["unanswerable_facets"],
            answerability["answerability_status"],
        )
        logger.warning(
            "chat_trace request_id=%s stage=boundary_classification boundary_type=%s requested_version=%s detected_version=%s version_status=%s",
            request_id, boundary_type, requested_version, detected_version, version_status_value,
        )
        logger.warning(
            "chat_trace request_id=%s stage=diagnostic_stage_decision confirmed_stages=%s first_failure_stage=%s next_validation=%s",
            request_id,
            diagnostic_plan.get("confirmed_stages", []),
            diagnostic_plan.get("first_failure_stage"),
            diagnostic_plan.get("next_validation"),
        )

        external_context = _build_external_context(evidence)
        first_evidence_ids = [_candidate_id(item) for item in evidence]
        logger.warning(
            "chat_trace request_id=%s stage=llm_context_first first_llm_context_evidence_ids=%s recovery_evidence_ids=%s evidence=%s context=%r",
            request_id,
            first_evidence_ids,
            [_candidate_id(item) for item in evidence if item.get("recovery_retrieval")],
            [{"citation_index": index, **_trace_candidate(item)} for index, item in enumerate(evidence, 1)],
            external_context,
        )

        validation_retry_attempted = False
        if boundary_type:
            result = boundary_answer(
                boundary_type,
                ("V" + requested_version) if requested_version else None,
            )
            result["sources"] = ai_client.build_sources_from_evidence(evidence)
            result["evidence"] = result["sources"]
            result["images"] = []
            result["validation"] = {
                "status": "boundary_policy",
                "boundary_type": boundary_type,
                "evidence_strength": reasoning_trace.get("evidence_strength", {}),
                "diagnostic_stage_plan": diagnostic_plan,
                "unsupported_claims": [],
                "overclaim_detected": False,
                "validation_result": "boundary_policy_applied",
            }
            logger.warning(
                "chat_trace request_id=%s stage=generation_boundary_skipped boundary_type=%s validation_result=boundary_policy_applied",
                request_id, boundary_type,
            )
        elif evidence:
            result = await ai_client.query(
                question=request.question,
                version=request.version,
                conversation_id=conversation.dify_conversation_id,
                user_id=request.user_id,
                external_context=external_context,
                evidence=evidence,
                candidate_pool=reranked,
                required_facets=facet_requirements["required_facets"],
                relation_facets=facet_requirements.get("required_relation_facets", []),
                reasoning_trace=reasoning_trace,
                facet_diagnostics=facet_requirements.get("facet_diagnostics"),
            )
            logger.warning("chat_trace request_id=%s stage=first_generation raw_llm_answer=%r answer=%r",
                           request_id, result.get("raw_llm_answer", ""), result.get("answer", ""))
            logger.warning("chat_trace request_id=%s stage=first_validation validation_result=%s validation_required_missing=%s answer_missing_facets=%s answer_covered_facets=%s answer_facet_snippets=%s ignored_missing_facets=%s output_integrity_issues=%s parameter_name_conflicts=%s remaining_missing_relations=%s missing_relation_constraints=%s negative_claim_conflicts=%s unsupported_claims=%s overclaim_detected=%s exact_api_conflicts=%s semantic_concept_conflicts=%s causal_overclaim_claims=%s lifecycle_state_conflicts=%s numeric_unit_conflicts=%s action_applicability_conflicts=%s return_code_conflicts=%s mechanism_conflicts=%s boundary_type=%s",
                            request_id,
                           result.get("validation", {}).get("status"),
                           result.get("validation", {}).get("missing_required_facets", []),
                            result.get("validation", {}).get("answer_missing_facets", []),
                            result.get("validation", {}).get("answer_covered_facets", []),
                            result.get("validation", {}).get("answer_facet_snippets", {}),
                            result.get("validation", {}).get("ignored_missing_facets", []),
                            result.get("validation", {}).get("output_integrity_issues", []),
                            result.get("validation", {}).get("parameter_name_conflicts", []),
                           result.get("validation", {}).get("missing_relations", []),
                           result.get("validation", {}).get("missing_relation_constraints", []),
                           result.get("validation", {}).get("negative_claim_conflicts_with_coverage", []),
                           result.get("validation", {}).get("unsupported_claims", []),
                           result.get("validation", {}).get("overclaim_detected", False),
                           result.get("validation", {}).get("exact_api_conflicts", []),
                           result.get("validation", {}).get("semantic_concept_conflicts", []),
                           result.get("validation", {}).get("causal_overclaim_claims", []),
                           result.get("validation", {}).get("lifecycle_state_conflicts", []),
                           result.get("validation", {}).get("numeric_unit_conflicts", []),
                           result.get("validation", {}).get("action_applicability_conflicts", []),
                           result.get("validation", {}).get("return_code_conflicts", []),
                           result.get("validation", {}).get("mechanism_conflicts", []),
                           result.get("boundary_type"))
            # Validation is actionable, but bounded: reselect the same ranked
            # pool and make at most one fresh generation.  No new retrieval is
            # performed here, so citations remain tied to actual candidates.
            if result.get("validation", {}).get("should_retry"):
                validation_data = result.get("validation", {})
                validation_retry_attempted = False
                forced_relations = {str(value).removeprefix("relation:") for value in validation_data.get("missing_relations", [])}
                forced_relations.update(
                    str(value).removeprefix("relation:")
                    for value in validation_data.get("missing_required_facets", [])
                    if str(value).startswith("relation:")
                )
                forced_facets = {
                    str(value) for value in validation_data.get("missing_required_facets", [])
                    if not str(value).startswith("relation:")
                }
                answer_missing_facets = {
                    str(value) for value in validation_data.get("answer_missing_facets", [])
                    if str(value)
                }
                forced_facets.update(answer_missing_facets)
                validation_missing_facets = {
                    str(value) for value in validation_data.get("missing_required_facets", [])
                    if str(value) and not str(value).startswith("relation:")
                }
                forced_facets.update(validation_missing_facets)
                generation_missing_facets = answer_missing_facets | validation_missing_facets
                forced_candidates = {
                    candidate_id
                    for target_id in (*forced_relations, *forced_facets)
                    for candidate_id in recovery_targets.get(target_id, [])
                }
                retry_negative_claim_targets = list(
                    validation_data.get("negative_claim_conflicts_with_coverage", [])
                )
                retry_unsupported_claims = list(validation_data.get("unsupported_claims", []))
                retry_support_ids = {
                    str(value)
                for facet_id in generation_missing_facets
                    for value in (validation_data.get("facet_supporting_evidence_ids", {}) or {}).get(facet_id, [])
                }
                if generation_missing_facets:
                    retry_generation_reason = (
                        "上一轮回答遗漏了已有 Evidence 支持的 required facets: "
                        f"{', '.join(sorted(generation_missing_facets))}。必须为每个 facet 写一个独立的完整回答块，"
                        f"并使用对应 supporting Evidence IDs ({', '.join(sorted(retry_support_ids)) or '见 Required Facet Evidence'})；"
                        "本次是完整重写，请不要拼接上一轮答案。"
                    )
                elif retry_unsupported_claims:
                    retry_generation_reason = (
                        "上一轮回答包含 Evidence 未支持的新技术实体或具体参数。请删除这些完整句子，"
                        "只保留能够由 supplied Evidence 或用户问题直接支持的内容；不要用通用 DDS/RTPS 常识补全。"
                    )
                elif retry_negative_claim_targets:
                    retry_generation_reason = (
                        "上一轮回答声称某些方向缺少知识库证据，但系统确认这些方向已有 covered evidence "
                        f"({', '.join(retry_negative_claim_targets)})。请重新依据 supplied Evidence 回答，"
                        "不要重复该负向结论；区分 DIRECTLY_COVERED、COMPOSITIONALLY_COVERED 和 UNSUPPORTED。"
                    )
                else:
                    retry_generation_reason = (
                        "请根据本次提供的最新 Evidence 和 coverage summary 重新回答，"
                        "只对仍为 UNSUPPORTED 的方向说明证据不足。"
                    )
                retry_evidence = select_evidence(
                    request.question, reranked, top_n=RERANK_TOP_N,
                    requirements=facet_requirements,
                    force_relation_ids=forced_relations,
                    force_facet_ids=forced_facets,
                    preferred_candidate_ids=forced_candidates,
                    recovery_support_map=recovery_targets,
                )
                retry_evidence_ids = [_candidate_id(item) for item in retry_evidence]
                retry_effective_change = effective_evidence_changed(
                    evidence,
                    retry_evidence,
                    facet_requirements,
                    facet_ids=forced_facets,
                    relation_ids=forced_relations,
                )
                retry_unchanged = first_evidence_ids == retry_evidence_ids
                retry_context = _build_external_context(retry_evidence)
                logger.warning(
                    "chat_trace request_id=%s stage=retry_prompt retry_missing_facets=%s "
                    "retry_supporting_evidence_ids=%s retry_prompt=%r",
                    request_id,
                    sorted(generation_missing_facets),
                    sorted(retry_support_ids),
                    retry_generation_reason,
                )
                logger.warning("chat_trace request_id=%s stage=validation_retry first_evidence_ids=%s retry_evidence_ids=%s forced_relations=%s retry_evidence_unchanged=%s retry_generation_reason=%s retry_negative_claim_targets=%s validation=%s evidence=%s",
                               request_id, first_evidence_ids, retry_evidence_ids,
                               sorted(forced_relations), retry_unchanged,
                               retry_generation_reason, retry_negative_claim_targets,
                               result["validation"], [_trace_candidate(item) for item in retry_evidence])
                logger.warning("chat_trace request_id=%s stage=llm_context_retry retry_llm_context_evidence_ids=%s recovery_evidence_ids=%s context=%r",
                               request_id, retry_evidence_ids,
                               [_candidate_id(item) for item in retry_evidence if item.get("recovery_retrieval")], retry_context)
                first_result = result
                logger.warning("chat_trace request_id=%s stage=evidence_first first_evidence_ids=%s", request_id, first_evidence_ids)
                logger.warning("chat_trace request_id=%s stage=evidence_retry retry_evidence_ids=%s effective_change=%s", request_id, retry_evidence_ids, retry_effective_change)
                # A generation conflict is retryable even when the selected
                # evidence is unchanged: the retry changes the generation
                # contract and explicitly names the conflicting covered
                # target.  Evidence identity is therefore not a prerequisite
                # for correcting an LLM negative claim.
                retry_should_run = should_retry_generation(
                    retry_effective_change, retry_negative_claim_targets
                ) or bool(
                    answer_missing_facets
                    or validation_missing_facets
                    or retry_unsupported_claims
                    or validation_data.get("overclaim_claims")
                    or validation_data.get("exact_api_conflicts")
                    or validation_data.get("semantic_concept_conflicts")
                    or validation_data.get("action_applicability_conflicts")
                    or validation_data.get("output_integrity_issues")
                    or validation_data.get("parameter_name_conflicts")
                )
                if not retry_should_run:
                    result["answer"] = soften_unverified_negative_claims(result.get("answer", ""))
                    result["status"] = "answered"
                    result["answer_status"] = "PARTIAL_ANSWER"
                    result["validation"]["retry_evidence_unchanged"] = retry_unchanged
                    result["validation"]["retry_effective_change"] = False
                    result["validation"]["retry_generation_reason"] = retry_generation_reason
                    logger.warning("chat_trace request_id=%s stage=validation_retry_skipped reason=no_target_evidence_change", request_id)
                else:
                    validation_retry_attempted = True
                    # The latest selection is authoritative even when the
                    # second generation fails.  Keep its context/citations
                    # while preserving the first non-empty answer below.
                    evidence, external_context = retry_evidence, retry_context
                    initial_validation = dict(result.get("validation") or {})
                    try:
                        result = await ai_client.query(
                        question=request.question, version=request.version,
                        conversation_id=result.get("dify_conversation_id") or conversation.dify_conversation_id,
                        user_id=request.user_id, external_context=retry_context, evidence=retry_evidence,
                        candidate_pool=reranked, required_facets=facet_requirements["required_facets"],
                        relation_facets=facet_requirements.get("required_relation_facets", []),
                        reasoning_trace=analyze_evidence_support(
                            request.question, retry_evidence, facet_requirements["required_facets"],
                            facet_requirements.get("required_relation_facets", []),
                        ),
                         facet_diagnostics=facet_requirements.get("facet_diagnostics"),
                         retry_generation_reason=retry_generation_reason,
                    )
                        retry_answer = result.get("answer", "")
                        retry_validation = dict(result.get("validation") or {})
                        logger.warning(
                            "chat_trace request_id=%s stage=retry_generation raw_llm_answer=%r answer=%r",
                            request_id,
                            result.get("raw_llm_answer", retry_answer),
                            retry_answer,
                        )
                        logger.warning(
                            "chat_trace request_id=%s stage=retry_validation validation=%s",
                            request_id,
                            retry_validation,
                        )
                        result.setdefault("validation", {})["raw_llm_answer"] = first_result.get("raw_llm_answer", "")
                        result["validation"]["retry_llm_answer"] = retry_answer
                        result["validation"]["initial_negative_claim_conflicts"] = initial_validation.get(
                            "negative_claim_conflicts_with_coverage", []
                        )
                        result["validation"]["retry_evidence_unchanged"] = retry_unchanged
                        result["validation"]["retry_effective_change"] = retry_effective_change
                        result["validation"]["retry_generation_reason"] = retry_generation_reason
                        if retry_answer.strip():
                            # Validation retry is a complete rewrite.  Do not
                            # append or merge the stale first-generation buffer.
                            result["answer"] = retry_answer.strip()
                            result["final_answer"] = result["answer"]
                            result["validation"]["final_answer_assignment"] = "retry_replacement"
                        else:
                            # Both generations failed claim-level validation;
                            # rebuild from authoritative evidence below rather
                            # than exposing an empty or status-only response.
                            result["answer"] = build_evidence_grounded_fallback(
                                request.question,
                                retry_evidence,
                                facet_requirements.get("required_facets", []),
                                result.get("validation", {}),
                            )
                            result["final_answer"] = result["answer"]
                            result["validation"]["fallback"] = "evidence_grounded"
                        logger.warning(
                            "chat_trace request_id=%s stage=validation remaining_missing_facets=%s remaining_missing_relations=%s",
                            request_id,
                            result.get("validation", {}).get("missing_required_facets", []),
                            result.get("validation", {}).get("missing_relations", []),
                        )
                    except AIServiceError as exc:
                        result = first_result
                        result["sources"] = ai_client.build_sources_from_evidence(retry_evidence)
                        result["evidence"] = result["sources"]
                        result["status"] = "answered"
                        result["answer_status"] = "PARTIAL_ANSWER"
                        result.setdefault("validation", {})["retry_llm_answer"] = ""
                        result["validation"]["initial_negative_claim_conflicts"] = initial_validation.get(
                            "negative_claim_conflicts_with_coverage", []
                        )
                        result["validation"]["retry_generation_reason"] = retry_generation_reason
                        logger.warning("chat_trace request_id=%s stage=validation_retry_failed error=%s", request_id, type(exc).__name__)
                if result.get("validation", {}).get("should_retry"):
                    # A second retry is deliberately prohibited.  Do not turn
                    # a partial multi-facet answer into NO_ANSWER; neutralize
                    # unsupported absolute absence claims instead.
                    if result.get("validation", {}).get("unsupported_claims"):
                        result["answer"] = salvage_supported_claims(
                            result.get("answer", ""),
                            result["validation"],
                        ) or build_evidence_grounded_fallback(
                            request.question,
                            evidence,
                            facet_requirements.get("required_facets", []),
                            result.get("validation", {}),
                        )
                        result["validation"]["unsupported_claims_removed"] = True
                        result["validation"]["generation_evidence_conflict"] = True
                    elif result.get("validation", {}).get("overclaim_claims"):
                        result["answer"] = salvage_supported_claims(
                            result.get("answer", ""),
                            result["validation"],
                        ) or build_evidence_grounded_fallback(
                            request.question,
                            evidence,
                            facet_requirements.get("required_facets", []),
                            result.get("validation", {}),
                        )
                        result["validation"]["overclaim_removed"] = True
                        result["validation"]["generation_evidence_conflict"] = True
                    elif result.get("validation", {}).get("negative_claim_conflicts_with_coverage"):
                        result["answer"] = salvage_supported_claims(
                            result.get("answer", ""),
                            result["validation"],
                        ) or build_evidence_grounded_fallback(
                            request.question,
                            evidence,
                            facet_requirements.get("required_facets", []),
                            result.get("validation", {}),
                        )
                        result["validation"]["generation_evidence_conflict"] = True
                        logger.error(
                            "chat_trace request_id=%s stage=generation_evidence_conflict targets=%s",
                            request_id,
                            result["validation"].get("negative_claim_conflicts_with_coverage", []),
                        )
                    elif (
                        result.get("validation", {}).get("exact_api_conflicts")
                        or result.get("validation", {}).get("semantic_concept_conflicts")
                        or result.get("validation", {}).get("action_applicability_conflicts")
                    ):
                        result["answer"] = salvage_supported_claims(
                            result.get("answer", ""),
                            result["validation"],
                        ) or build_evidence_grounded_fallback(
                            request.question,
                            evidence,
                            facet_requirements.get("required_facets", []),
                            result.get("validation", {}),
                        )
                        result["validation"]["generation_evidence_conflict"] = True
                    else:
                        result["answer"] = soften_unverified_negative_claims(result.get("answer", ""))
                    # A failed validation retry is not an answered response.
                    # Keep the useful text/citations, but expose the unresolved
                    # state instead of silently treating salvage as success.
                    result["status"] = "insufficient_evidence" if validation_retry_attempted else "answered"
                    result["answer_status"] = "PARTIAL_ANSWER"
                    logger.warning("chat_trace request_id=%s stage=validation_downgrade validation=%s",
                                   request_id, result["validation"])
                validation_conflicts = set(
                    result.get("validation", {}).get("negative_claim_conflicts_with_coverage", [])
                    or result.get("validation", {}).get("initial_negative_claim_conflicts", [])
                )
                refusal_without_specific_support = (
                    _is_evidence_refusal(result.get("answer", ""))
                    and not has_specific_query_support(
                        request.question, evidence, facet_requirements.get("required_facets", [])
                    )
                )
                if (
                    (validation_conflicts or refusal_without_specific_support)
                    and len(facet_requirements.get("required_facets", [])) <= 1
                    and _is_evidence_refusal(result.get("answer", ""))
                ):
                    # A refusal that survived validation is not an ANSWER just
                    # because broad retrieval returned product-level context.
                    # Preserve the refusal and citations, but expose the
                    # contractually correct no-answer status to API clients.
                    result["status"] = "insufficient_evidence"
                    result["answer_status"] = "NO_ANSWER"
                    result["validation"]["answer_classification"] = "evidence_refusal"
                    result["validation"]["refusal_without_specific_support"] = refusal_without_specific_support
                    logger.warning(
                        "chat_trace request_id=%s stage=answer_status classification=evidence_refusal conflicts=%s",
                        request_id,
                        sorted(validation_conflicts),
                    )
                result["final_answer"] = result.get("answer", "")
                logger.warning(
                    "generation_answer_trace request_id=%s raw_llm_answer=%r retry_llm_answer=%r final_answer=%r",
                    request_id,
                    result.get("validation", {}).get("raw_llm_answer", result.get("raw_llm_answer", "")),
                    result.get("validation", {}).get("retry_llm_answer", ""),
                    result.get("answer", ""),
                )
            # Apply the same conservative status rule when the first
            # validation did not request a retry.  A refusal with no
            # query-specific evidence is still NO_ANSWER, even if broad
            # product-level retrieval returned filler paragraphs.
            validation_data = result.get("validation", {})
            low_information_question = len(facet_requirements.get("required_facets", [])) <= 1
            if (
                low_information_question
                and
                _is_evidence_refusal(result.get("answer", ""))
                and not has_specific_query_support(
                    request.question, evidence, facet_requirements.get("required_facets", [])
                )
            ):
                result["status"] = "insufficient_evidence"
                result["answer_status"] = "NO_ANSWER"
                validation_data["answer_classification"] = "evidence_refusal"
                validation_data["refusal_without_specific_support"] = True
                logger.warning(
                    "chat_trace request_id=%s stage=answer_status classification=evidence_refusal conflicts=%s",
                    request_id,
                    validation_data.get("negative_claim_conflicts_with_coverage", []),
                )
            elif evidence and low_information_question and not has_specific_query_support(
                request.question, evidence, facet_requirements.get("required_facets", [])
            ):
                # Do not expose a plausible-looking second-generation answer
                # when the selected evidence has no query-specific anchor.
                # This is a generic evidence gate, not a question/document
                # rule, and it prevents unsupported expansion after retry.
                result["answer"] = "当前最终证据未充分覆盖该问题，无法据此作出可靠结论。"
                result["status"] = "insufficient_evidence"
                result["answer_status"] = "NO_ANSWER"
                validation_data["answer_classification"] = "no_query_specific_support"
                validation_data["refusal_without_specific_support"] = True
                logger.warning(
                    "chat_trace request_id=%s stage=answer_status classification=no_query_specific_support",
                    request_id,
                )
        else:
            # Preserve the direct-call compatibility path used by service
            # callers and unit tests.  An actual HTTP request with no
            # retrieved evidence remains a deterministic refusal; only a
            # caller that did not receive FastAPI's Response injection may
            # invoke the legacy QA orchestration.
            if response is None:
                result = await ai_client.query(
                    question=request.question,
                    version=request.version,
                    conversation_id=conversation.dify_conversation_id,
                    user_id=request.user_id,
                )
                result.setdefault("dify_conversation_id", conversation.dify_conversation_id)
            else:
                result = {
                    "answer": "当前知识库中没有找到足够证据回答这个问题。",
                    "status": "insufficient_evidence",
                    "answer_status": "NO_ANSWER",
                    "sources": [],
                    "evidence": [],
                    "images": [],
                    "dify_conversation_id": conversation.dify_conversation_id,
                }

        if evidence and not boundary_type and result.get("answer", ""):
            final_validation = validate_answer(
                result.get("answer", ""),
                evidence,
                request.question,
                candidate_pool=reranked,
                required_facets=facet_requirements.get("required_facets", []),
                relation_facets=facet_requirements.get("required_relation_facets", []),
                facet_diagnostics=facet_requirements.get("facet_diagnostics"),
            )
            final_validation_data = {
                "status": final_validation.status,
                "should_retry": final_validation.should_retry,
                "answer_covered_facets": list(final_validation.answer_covered_facets),
                "answer_missing_facets": list(final_validation.answer_missing_facets),
                "answer_facet_snippets": final_validation.answer_facet_snippets or {},
                "output_integrity_issues": list(final_validation.output_integrity_issues),
                "parameter_name_conflicts": list(final_validation.parameter_name_conflicts),
                "reasons": list(final_validation.reasons),
                "missing_required_facets": list(final_validation.missing_required_facets),
                "unsupported_claims": list(final_validation.unsupported_claims),
                "overclaim_claims": list(final_validation.overclaim_claims),
            }
            result.setdefault("validation", {}).update({
                "final_validation_result": final_validation_data,
                "final_answer_facet_snippets": final_validation_data["answer_facet_snippets"],
                "final_validation_passed": not final_validation.should_retry,
                # Make the final validator authoritative for the serialized
                # API trace too; otherwise these fields could still describe
                # the first generation after a retry replacement.
                "status": final_validation.status,
                "should_retry": final_validation.should_retry,
                "answer_covered_facets": final_validation_data["answer_covered_facets"],
                "answer_missing_facets": final_validation_data["answer_missing_facets"],
                "answer_facet_snippets": final_validation_data["answer_facet_snippets"],
                "output_integrity_issues": final_validation_data["output_integrity_issues"],
                "parameter_name_conflicts": final_validation_data["parameter_name_conflicts"],
            })
            logger.warning(
                "chat_trace request_id=%s stage=%s final_validation_result=%s answer_covered_facets=%s answer_missing_facets=%s answer_facet_snippets=%s output_integrity_issues=%s parameter_name_conflicts=%s final_answer=%r",
                request_id,
                "retry_validation" if validation_retry_attempted else "final_answer_validation",
                final_validation.status,
                final_validation.answer_covered_facets,
                final_validation.answer_missing_facets,
                final_validation.answer_facet_snippets,
                final_validation.output_integrity_issues,
                final_validation.parameter_name_conflicts,
                result.get("answer", ""),
            )
            if final_validation.should_retry:
                result["status"] = "insufficient_evidence"
                result["answer_status"] = "PARTIAL_ANSWER"
            elif validation_retry_attempted:
                result["status"] = "answered"
                result["answer_status"] = (
                    "PARTIAL_ANSWER"
                    if final_validation.answer_missing_facets
                    or reasoning_trace.get("unsupported_facets")
                    or reasoning_trace.get("uncovered_facets")
                    else "ANSWER"
                )

        result.setdefault("requested_version", ("V" + requested_version) if requested_version else None)
        result.setdefault("detected_version", detected_version)
        result.setdefault("effective_version", ("V" + requested_version) if requested_version else None)
        result.setdefault("version_status", "VERSION-GAP" if boundary_type == "VERSION-GAP" else version_status_value)
        result.setdefault("boundary_type", boundary_type)
        result.setdefault("diagnostic_stage_plan", diagnostic_plan)
        result.setdefault("live_generation_status", "NOT_REQUIRED" if boundary_type else None)
        result.setdefault("generation_verified", False if boundary_type else None)
        # The selected Evidence is authoritative for the API citation map.
        # This also protects the endpoint when a provider adapter returns an
        # answer but omits its own retriever_resources.
        if evidence:
            result["sources"] = ai_client.build_sources_from_evidence(evidence)
        result["evidence"] = [
            {
                "chunk_id": item.get("chunk_id"),
                "segment_id": item.get("segment_id"),
                "source_file": item.get("source_file"),
                "section": item.get("section"),
                "heading_path": item.get("heading_path"),
                "page": item.get("page") or item.get("page_start"),
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "content": item.get("content"),
                "rerank_score": item.get("rerank_score"),
                "retrieval_source": item.get("retrieval_source", []),
                "evidence_rank": item.get("evidence_rank"),
                "evidence_facets": item.get("evidence_facets", []),
                "covered_facets": item.get("covered_facets", []),
                "uncovered_facets": item.get("uncovered_facets", []),
                "recovery_retrieval": item.get("recovery_retrieval", False),
                "recovery_relation_ids": item.get("recovery_relation_ids", []),
                "evidence_strength": item.get("evidence_strength", {}),
                "candidate_targets_supported": item.get("candidate_targets_supported", []),
                "selection_reason": item.get("selection_reason"),
            }
            for item in evidence
        ]
        if (
            evidence
            and result.get("answer_status") == "PARTIAL_ANSWER"
            and not result.get("sources")
        ):
            # PARTIAL_ANSWER is invalid without at least one citation.  Keep
            # legacy/direct AI callers safe by deriving sources from the same
            # authoritative selected Evidence used for the answer.
            result["sources"] = ai_client.build_sources_from_evidence(evidence)
        logger.warning(
            "chat_trace request_id=%s stage=api_mapping evidence=%s sources=%s",
            request_id,
            result["evidence"],
            result["sources"],
        )

        dify_conversation_id = result.get("dify_conversation_id")
        if (
            dify_conversation_id
            and dify_conversation_id != conversation.dify_conversation_id
        ):
            conversation_service.save_dify_conversation_id(
                conversation_id,
                dify_conversation_id,
            )
        conversation_service.save_user_message(conversation_id, request.question)
        conversation_service.save_ai_message(
            conversation_id,
            result["answer"],
            answer_status=result.get("answer_status", result.get("status")),
            sources=result.get("sources", []),
            images=result.get("images", []),
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"数据库暂时不可用: {exc}",
        ) from exc
    except AIServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    data = ChatData(
        conversation_id=conversation_id,
        answer=result["answer"],
        status=result["status"],
        sources=result.get("sources", []),
        images=result.get("images", []),
        answer_status=result.get("answer_status"),
        original_query=result.get("original_query"),
        rag_query=result.get("rag_query"),
        confidence_score=result.get("confidence_score"),
        confidence_level=result.get("confidence_level"),
        confidence_reasons=result.get("confidence_reasons", []),
        requested_version=result.get("requested_version"),
        detected_version=result.get("detected_version"),
        effective_version=result.get("effective_version"),
        version_status=result.get("version_status"),
        boundary_type=result.get("boundary_type"),
        diagnostic_stage_plan=result.get("diagnostic_stage_plan", {}),
        live_generation_status=result.get("live_generation_status"),
        generation_verified=result.get("generation_verified"),
        evidence=result.get("evidence", []),
    )
    logger.warning(
        "chat_trace request_id=%s stage=frontend_mapping mappings=%s",
        request_id,
        [
            {
                "evidence_index": source.citation_index,
                "evidence_source_id": source.source_id,
                "api_source_id": source.source_id,
                "frontend_source_id": source.source_id,
                "document": source.document,
            }
            for source in data.sources
        ],
    )
    logger.warning(
        "chat_trace request_id=%s stage=final answer_status=%s final_answer_assignment=%s boundary_type=%s version_status=%s selected_evidence_ids=%s answer_missing_facets=%s answer_covered_facets=%s evidence_strength=%s unsupported_claims=%s overclaim_detected=%s exact_api_conflicts=%s semantic_concept_conflicts=%s causal_overclaim_claims=%s lifecycle_state_conflicts=%s numeric_unit_conflicts=%s action_applicability_conflicts=%s return_code_conflicts=%s mechanism_conflicts=%s validation_result=%s retry_reason=%s live_generation_status=%s",
        request_id,
        data.answer_status,
        (result.get("validation") or {}).get("final_answer_assignment", "first_generation"),
        data.boundary_type,
        data.version_status,
        [item.get("chunk_id") or item.get("segment_id") for item in data.evidence],
        (result.get("validation") or {}).get("answer_missing_facets", []),
        (result.get("validation") or {}).get("answer_covered_facets", []),
        (result.get("validation") or {}).get("evidence_strength", {}),
        (result.get("validation") or {}).get("unsupported_claims", []),
        (result.get("validation") or {}).get("overclaim_detected", False),
        (result.get("validation") or {}).get("exact_api_conflicts", []),
        (result.get("validation") or {}).get("semantic_concept_conflicts", []),
        (result.get("validation") or {}).get("causal_overclaim_claims", []),
        (result.get("validation") or {}).get("lifecycle_state_conflicts", []),
        (result.get("validation") or {}).get("numeric_unit_conflicts", []),
        (result.get("validation") or {}).get("action_applicability_conflicts", []),
        (result.get("validation") or {}).get("return_code_conflicts", []),
        (result.get("validation") or {}).get("mechanism_conflicts", []),
        (result.get("validation") or {}).get("status"),
        (result.get("validation") or {}).get("retry_generation_reason"),
        data.live_generation_status,
    )
    return ChatResponse(code=0, message="success", data=data)
