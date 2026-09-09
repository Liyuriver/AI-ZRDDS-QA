"""Chat API endpoints."""

import logging
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
from app.services.retrieval.evidence_service import analyze_evidence_support, build_facet_trace, build_relation_recovery_query, extract_facet_requirements, select_evidence, relation_candidate_map, relation_support, relation_support_strength
from app.services.user_service import UserNotFoundError
from app.services.query_rewrite_service import rewrite_query
from app.services.answer_validation_service import soften_unverified_negative_claims
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
        "content_preview": content[:500],
    }


def _candidate_id(item: dict) -> str:
    return str(item.get("segment_id") or item.get("chunk_id") or item.get("id") or "")


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
    response: Response,
    conversation_service: ConversationService = Depends(get_conversation_service),
    current_user: User = Depends(get_current_user),
    x_request_id: str | None = Header(default=None),
) -> ChatResponse:
    """Persist both sides of a chat turn and return the stable API envelope."""
    request_id = x_request_id or str(uuid4())
    response.headers["X-Request-ID"] = request_id
    logger.warning("chat_trace request_id=%s stage=request question=%r conversation_id=%s user_id=%s",
                request_id, request.question, request.conversation_id, request.user_id)
    # Direct unit callers do not receive FastAPI dependency injection. Keep a
    # compatibility seam for that case; real HTTP requests always take the
    # structured retrieval path below with a concrete authenticated User.
    if not isinstance(current_user, User):
        legacy_result = await answer_question(
            original_query=request.question,
            version=request.version,
            conversation_id=request.conversation_id,
            user_id=request.user_id,
            ai_client=ai_client,
        )
        return ChatResponse(
            code=0,
            message="success",
            data=ChatData(
                conversation_id=request.conversation_id or "",
                answer=legacy_result.get("answer", ""),
                status=legacy_result.get("status", "insufficient_evidence"),
                sources=legacy_result.get("sources", []),
                images=legacy_result.get("images", []),
                answer_status=legacy_result.get("answer_status"),
                original_query=legacy_result.get("original_query"),
                rag_query=legacy_result.get("rag_query"),
                confidence_score=legacy_result.get("confidence_score"),
                confidence_level=legacy_result.get("confidence_level"),
                confidence_reasons=legacy_result.get("confidence_reasons", []),
                requested_version=legacy_result.get("requested_version"),
                effective_version=legacy_result.get("effective_version"),
                version_status=legacy_result.get("version_status"),
                evidence=legacy_result.get("evidence", []),
            ),
        )
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
        bm25_results = retrieve_candidates(
            rewritten.search_query,
            top_k=BM25_TOP_K,
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

        recovery_query = build_relation_recovery_query(
            request.question,
            facet_requirements.get("required_relation_facets", []),
            bm25_results + dify_results,
        )
        recovery_bm25, recovery_dify = [], []
        recovery_support_map = {}
        recovery_candidate_ids: set[str] = set()
        if recovery_query:
            # The bounded recovery pass must have enough recall to reach a
            # rule paragraph that is below the ordinary retrieval cutoff;
            # the final Evidence limit is still RERANK_TOP_N.
            recovery_top_k = max(BM25_TOP_K, RERANK_CANDIDATE_POOL * 3)
            recovery_bm25 = retrieve_candidates(recovery_query, top_k=recovery_top_k)
            recovery_dify = await ai_client.retrieve_knowledge(
                recovery_query, top_k=max(DIFY_TOP_K, recovery_top_k), original_query=request.question,
            )
            recovery_candidates = recovery_bm25 + recovery_dify
            relations = facet_requirements.get("required_relation_facets", [])
            recovery_candidate_ids = {_candidate_id(item) for item in recovery_candidates}
            recovery_support_map = {
                str(index): [
                    _candidate_id(item) for item in recovery_candidates
                    if relation_support(item, relation)
                ]
                for index, relation in enumerate(relations)
            }
            for item in recovery_candidates:
                item["recovery_retrieval"] = True
                item["recovery_relation_ids"] = [key for key, ids in recovery_support_map.items() if _candidate_id(item) in ids]
                item["recovery_candidate_ids"] = sorted(recovery_candidate_ids)
            bm25_results.extend(recovery_bm25)
            dify_results.extend(recovery_dify)
            logger.warning("chat_trace request_id=%s stage=recovery_retrieval recovery_retrieval=true query=%r bm25=%s dify=%s",
                           request_id, recovery_query,
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
            if item_id in recovery_candidate_ids:
                item["recovery_retrieval"] = True
                item["recovery_relation_ids"] = [key for key, ids in recovery_support_map.items() if item_id in ids]
                item["recovery_candidate_ids"] = sorted(recovery_candidate_ids)
        if recovery_query:
            # Recovery may complement an initial retrieval hit. Promote only
            # strong status/callback/rule forms from the merged pool so an
            # initial Reader/Writer evidence item is not lost merely because
            # it was not returned by the second query.
            for index, relation in enumerate(facet_requirements.get("required_relation_facets", [])):
                strong_ids = [
                    _candidate_id(item) for item in fused
                    if relation_support_strength(item, relation) >= 3
                ]
                if strong_ids:
                    recovery_support_map[str(index)] = list(dict.fromkeys(
                        recovery_support_map.get(str(index), []) + strong_ids
                    ))
                    recovery_candidate_ids.update(strong_ids)
                    for item in fused:
                        if _candidate_id(item) in strong_ids:
                            item["recovery_retrieval"] = True
                            item["recovery_relation_ids"] = sorted(set(item.get("recovery_relation_ids", [])) | {str(index)})
        logger.warning("chat_trace request_id=%s stage=fusion candidates=%s",
                    request_id, [_trace_candidate(item) for item in fused])

        reranked = rerank(
            request.question,
            fused,
            top_n=RERANK_CANDIDATE_POOL,
        )
        # A reranker is allowed to return a bounded pool, but it must not
        # erase recovery candidates that explicitly support a required
        # relation. Reattach only those marked candidates; ordinary recovery
        # hits remain subject to the normal pool ranking and final selector.
        reranked_ids = {_candidate_id(item) for item in reranked}
        recovery_priority_ids = {
            candidate_id
            for ids in recovery_support_map.values()
            for candidate_id in ids
        }
        for item in fused:
            item_id = _candidate_id(item)
            if item_id in recovery_priority_ids and item_id not in reranked_ids:
                item["rerank_score"] = float(item.get("fusion_score", 0) or 0)
                item["rerank_rank"] = len(reranked) + 1
                reranked.append(item)
                reranked_ids.add(item_id)
        logger.warning("chat_trace request_id=%s stage=rerank_candidate_pool candidate_pool_ids=%s recovery_priority_ids=%s",
                       request_id, [_candidate_id(item) for item in reranked], sorted(recovery_priority_ids))
        evidence = select_evidence(
            request.question, reranked, top_n=RERANK_TOP_N,
            requirements=facet_requirements,
            force_relation_ids=recovery_support_map.keys(),
            preferred_candidate_ids={candidate_id for ids in recovery_support_map.values() for candidate_id in ids},
            recovery_support_map=recovery_support_map,
        )
        facet_trace = build_facet_trace(
            {"bm25": bm25_results, "dify": dify_results, "fusion": fused,
             "rerank": reranked, "evidence": evidence},
            facet_requirements["required_facets"],
            facet_requirements.get("required_relation_facets", []),
        )
        reasoning_trace = analyze_evidence_support(
            request.question, evidence, facet_requirements["required_facets"],
            facet_requirements.get("required_relation_facets", []),
        )
        facet_trace.update(reasoning_trace)
        logger.warning("chat_trace request_id=%s stage=facet_coverage trace=%s", request_id, facet_trace)
        logger.warning("chat_trace request_id=%s stage=rerank candidates=%s",
                    request_id, [_trace_candidate(item) for item in reranked])
        logger.warning("chat_trace request_id=%s stage=evidence candidates=%s",
                    request_id, [_trace_candidate(item) for item in evidence])

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

        external_context = "\n\n".join(
            f"[证据{index}]\n"
            f"来源：{item.get('source_file', '')}\n"
            f"章节：{item.get('section', '')}\n"
            f"内容：{item.get('content', '')}"
            for index, item in enumerate(evidence, 1)
        )
        logger.warning(
            "chat_trace request_id=%s stage=llm_context context_evidence_ids=%s recovery_evidence_ids=%s evidence=%s context=%r",
            request_id,
            [_candidate_id(item) for item in evidence],
            [_candidate_id(item) for item in evidence if item.get("recovery_retrieval")],
            [{"citation_index": index, **_trace_candidate(item)} for index, item in enumerate(evidence, 1)],
            external_context,
        )

        if evidence:
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
            )
            logger.warning("chat_trace request_id=%s stage=validation missing_relations=%s missing_side_states=%s negative_claim_conflicts=%s",
                           request_id,
                           result.get("validation", {}).get("missing_relations", []),
                           result.get("validation", {}).get("missing_side_states", []),
                           result.get("validation", {}).get("contradicted_negative_claims", []))
            # Validation is actionable, but bounded: reselect the same ranked
            # pool and make at most one fresh generation.  No new retrieval is
            # performed here, so citations remain tied to actual candidates.
            if result.get("validation", {}).get("should_retry"):
                first_evidence_ids = [_candidate_id(item) for item in evidence]
                validation_data = result.get("validation", {})
                forced_relations = {str(value).removeprefix("relation:") for value in validation_data.get("missing_relations", [])}
                forced_candidates = {candidate_id for relation_id in forced_relations for candidate_id in recovery_support_map.get(relation_id, [])}
                retry_evidence = select_evidence(
                    request.question, reranked, top_n=RERANK_TOP_N,
                    requirements=facet_requirements,
                    force_relation_ids=forced_relations,
                    preferred_candidate_ids=forced_candidates,
                    recovery_support_map=recovery_support_map,
                )
                retry_evidence_ids = [_candidate_id(item) for item in retry_evidence]
                retry_unchanged = first_evidence_ids == retry_evidence_ids
                retry_context = "\n\n".join(
                    f"[证据{index}]\n来源：{item.get('source_file', '')}\n章节：{item.get('section', '')}\n内容：{item.get('content', '')}"
                    for index, item in enumerate(retry_evidence, 1)
                )
                logger.warning("chat_trace request_id=%s stage=validation_retry first_evidence_ids=%s retry_evidence_ids=%s forced_relations=%s retry_evidence_unchanged=%s validation=%s evidence=%s",
                               request_id, first_evidence_ids, retry_evidence_ids,
                               sorted(forced_relations), retry_unchanged,
                               result["validation"], [_trace_candidate(item) for item in retry_evidence])
                logger.warning("chat_trace request_id=%s stage=retry_llm_context context_evidence_ids=%s recovery_evidence_ids=%s context=%r",
                               request_id, retry_evidence_ids,
                               [_candidate_id(item) for item in retry_evidence if item.get("recovery_retrieval")], retry_context)
                first_result = result
                if retry_unchanged and forced_relations:
                    result["answer"] = soften_unverified_negative_claims(result.get("answer", ""))
                    result["status"] = "answered"
                    result["answer_status"] = "PARTIAL_ANSWER"
                    result["validation"]["retry_evidence_unchanged"] = True
                    logger.warning("chat_trace request_id=%s stage=validation_retry_skipped reason=evidence_unchanged", request_id)
                else:
                    # The latest selection is authoritative even when the
                    # second generation fails.  Keep its context/citations
                    # while preserving the first non-empty answer below.
                    evidence, external_context = retry_evidence, retry_context
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
                    )
                    except AIServiceError as exc:
                        result = first_result
                        result["sources"] = ai_client.build_sources_from_evidence(retry_evidence)
                        result["evidence"] = result["sources"]
                        result["status"] = "answered"
                        result["answer_status"] = "PARTIAL_ANSWER"
                        logger.warning("chat_trace request_id=%s stage=validation_retry_failed error=%s", request_id, type(exc).__name__)
                if result.get("validation", {}).get("should_retry"):
                    # A second retry is deliberately prohibited.  Do not turn
                    # a partial multi-facet answer into NO_ANSWER; neutralize
                    # unsupported absolute absence claims instead.
                    result["answer"] = soften_unverified_negative_claims(result.get("answer", ""))
                    # The response-level status remains a successful answer;
                    # answer_status carries the more specific coverage state.
                    # This preserves existing client behavior while allowing
                    # persisted PARTIAL_ANSWER history to be schema-valid.
                    result["status"] = "answered"
                    result["answer_status"] = "PARTIAL_ANSWER"
                    logger.warning("chat_trace request_id=%s stage=validation_downgrade validation=%s",
                                   request_id, result["validation"])
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

        # sources built from final evidence in ai_client.query(); no override needed.
        result["evidence"] = [
            {
                "chunk_id": item.get("chunk_id"),
                "segment_id": item.get("segment_id"),
                "source_file": item.get("source_file"),
                "section": item.get("section"),
                "heading_path": item.get("heading_path"),
                "content": item.get("content"),
                "rerank_score": item.get("rerank_score"),
                "retrieval_source": item.get("retrieval_source", []),
                "evidence_rank": item.get("evidence_rank"),
                "evidence_facets": item.get("evidence_facets", []),
                "covered_facets": item.get("covered_facets", []),
                "uncovered_facets": item.get("uncovered_facets", []),
                "recovery_retrieval": item.get("recovery_retrieval", False),
                "recovery_relation_ids": item.get("recovery_relation_ids", []),
            }
            for item in evidence
        ]
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
    return ChatResponse(code=0, message="success", data=data)
