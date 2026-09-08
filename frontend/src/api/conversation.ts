import {
  mockCreateConversation,
  mockDeleteConversation,
  mockFetchConversations,
  mockUpdateConversationTitle,
} from '@/api/mock/conversation'
import { appConfig } from '@/config/app'
import type { Conversation } from '@/types/conversation'
import { http } from './http'

interface BackendConversation {
  id: string
  user_id: string
  title: string
  version: string | null
  created_at: string
  updated_at: string
}

const mapConversation = (item: BackendConversation): Conversation => ({
  id: item.id,
  userId: item.user_id,
  title: item.title,
  createdAt: item.created_at,
  updatedAt: item.updated_at,
})

export async function fetchConversations(userId: string): Promise<Conversation[]> {
  if (appConfig.useMock) return mockFetchConversations(userId)
  const { data } = await http.get<BackendConversation[]>(`/users/${userId}/conversations`)
  return data.map(mapConversation)
}

export async function createConversation(userId: string): Promise<Conversation> {
  if (appConfig.useMock) return mockCreateConversation(userId)
  const { data } = await http.post<BackendConversation>('/conversations', {
    user_id: userId,
    title: '新的知识问答',
    version: null,
  })
  return mapConversation(data)
}

export async function updateConversationTitle(id: string, title: string): Promise<void> {
  if (appConfig.useMock) {
    await mockUpdateConversationTitle(id, title)
    return
  }
  await http.patch(`/conversations/${id}`, { title })
}

export async function deleteConversation(id: string): Promise<void> {
  if (appConfig.useMock) return mockDeleteConversation(id)
  await http.delete(`/conversations/${id}`)
}
