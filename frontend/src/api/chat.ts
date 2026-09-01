import { mockFetchMessages, mockSendMessage } from '@/api/mock/chat'
import { appConfig } from '@/config/app'
import type { ChatMessage, Citation, SendMessageRequest } from '@/types/chat'
import { http } from './http'

interface BackendMessage {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  answer_status?: 'answered' | 'insufficient_evidence' | 'error' | null
  sources?: BackendSource[] | null
  images?: BackendImage[] | null
  created_at: string
}

interface BackendSource {
  document: string
  section: string | null
  page: number | null
  score: number | null
  quote: string
}

interface BackendImage {
  url: string
  document: string | null
}

interface BackendChatResponse {
  code: number
  message: string
  data: {
    conversation_id: string
    answer: string
    status: 'answered' | 'insufficient_evidence' | 'error'
    sources: BackendSource[]
    images: BackendImage[]
  } | null
}

export const mapHistoryMessage = (item: BackendMessage): ChatMessage => ({
  id: item.id,
  conversationId: item.conversation_id,
  role: item.role,
  content: item.content,
  status: 'success',
  createdAt: item.created_at,
  answerStatus:
    item.role === 'assistant'
      ? item.answer_status === 'insufficient_evidence'
        ? 'no_answer'
        : 'answered'
      : undefined,
  citations:
    item.role === 'assistant' ? mapCitations(item.sources || [], item.images || []) : undefined,
})

function mapCitations(sources: BackendSource[], images: BackendImage[]): Citation[] {
  return sources.map((source) => ({
    sourceFile: source.document,
    section: source.section || undefined,
    page: source.page || undefined,
    versionStatus: 'unknown',
    snippet: source.quote,
    images: images.filter((image) => image.document === source.document).map((image) => image.url),
  }))
}

export function mapChatResponse(response: BackendChatResponse): ChatMessage {
  if (!response.data || response.code !== 0 || response.data.status === 'error') {
    throw new Error(response.message || 'AI 服务暂时不可用')
  }
  return {
    id: crypto.randomUUID(),
    conversationId: response.data.conversation_id,
    role: 'assistant',
    content: response.data.answer,
    status: 'success',
    createdAt: new Date().toISOString(),
    answerStatus: response.data.status === 'insufficient_evidence' ? 'no_answer' : 'answered',
    citations: mapCitations(response.data.sources, response.data.images),
  }
}

export async function fetchMessages(conversationId: string): Promise<ChatMessage[]> {
  if (appConfig.useMock) return mockFetchMessages(conversationId)
  const { data } = await http.get<BackendMessage[]>(`/conversations/${conversationId}/messages`)
  return data.map(mapHistoryMessage)
}

export async function sendMessage(payload: SendMessageRequest): Promise<ChatMessage> {
  if (appConfig.useMock) return mockSendMessage(payload)
  const { data: response } = await http.post<BackendChatResponse>('/chat', {
    question: payload.userMessage.content,
    version: payload.version ?? null,
    conversation_id: payload.conversationId,
    user_id: payload.userId,
  })
  return mapChatResponse(response)
}
