export type MessageRole = 'user' | 'assistant'
export type MessageStatus = 'sending' | 'success' | 'error'
export type AnswerStatus = 'answered' | 'no_answer'
export type VersionStatus = 'compatible' | 'incompatible' | 'unknown'

export interface Citation {
  sourceFile: string
  documentId?: string
  section?: string
  page?: number
  pageStart?: number
  pageEnd?: number
  version?: string
  versionStatus: VersionStatus
  snippet?: string
  images?: string[]
}

export interface ChatMessage {
  id: string
  conversationId: string
  role: MessageRole
  content: string
  status: MessageStatus
  createdAt: string
  answerStatus?: AnswerStatus
  citations?: Citation[]
  errorMessage?: string
}

export interface SendMessageRequest {
  conversationId: string
  userMessage: ChatMessage
  userId: string
  version?: string | null
}
