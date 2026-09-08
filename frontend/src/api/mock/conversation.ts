import type { Conversation } from '@/types/conversation'
import { readJson, writeJson } from '@/utils/storage'

const KEY = 'zrdss_qa_mock_conversations'
const wait = () => new Promise<void>((resolve) => window.setTimeout(resolve, 160))
const readAll = () => readJson<Conversation[]>(KEY, [])

export async function mockFetchConversations(userId: string): Promise<Conversation[]> {
  await wait()
  return readAll()
    .filter((item) => item.userId === userId)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
}

export async function mockCreateConversation(userId: string): Promise<Conversation> {
  await wait()
  const all = readAll()
  const now = new Date().toISOString()
  const conversation: Conversation = {
    id: crypto.randomUUID(),
    userId,
    title: '新的知识问答',
    createdAt: now,
    updatedAt: now,
  }
  all.push(conversation)
  writeJson(KEY, all)
  return conversation
}

export async function mockUpdateConversationTitle(
  id: string,
  title: string,
): Promise<Conversation> {
  const all = readAll()
  const conversation = all.find((item) => item.id === id)
  if (!conversation) throw new Error('当前会话不存在')
  conversation.title = title
  conversation.updatedAt = new Date().toISOString()
  writeJson(KEY, all)
  return conversation
}

export async function mockDeleteConversation(id: string): Promise<void> {
  await wait()
  const all = readAll()
  const next = all.filter((item) => item.id !== id)
  if (next.length === all.length) throw new Error('当前会话不存在')
  writeJson(KEY, next)
}
