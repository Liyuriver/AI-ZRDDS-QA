import type { ChatMessage, Citation, SendMessageRequest } from '@/types/chat'
import { readJson, writeJson } from '@/utils/storage'

const KEY = 'zrdss_qa_mock_messages'
const failedOnce = new Set<string>()
const wait = () => new Promise<void>((resolve) => window.setTimeout(resolve, 650))
const readAll = () => readJson<ChatMessage[]>(KEY, [])

function buildAnswer(query: string): string {
  return `## 排查建议\n\n针对“${query}”，建议先确认依赖库路径和当前构建配置是否一致。\n\n1. 检查库文件是否存在。\n2. 确认编译器的附加库目录。\n3. 清理缓存后重新构建。\n\n\`\`\`bash\n# Mock 示例命令\ncmake --build build --config Release\n\`\`\`\n\n| 检查项 | 预期结果 |\n| --- | --- |\n| 依赖路径 | 指向当前版本 SDK |\n| 构建配置 | 与目标平台一致 |\n\n> 当前内容为前端 Mock 数据，真实回答将在 FastAPI 与 Dify 联调后替换。`
}

function buildCitations(): Citation[] {
  return [
    {
      sourceFile: 'ZRDDS故障排查指南.pdf',
      documentId: 'zrdds-troubleshooting-guide',
      section: '3.1.7 依赖库缺失处理',
      page: 46,
      version: 'V3.2',
      versionStatus: 'compatible',
      snippet: '检查工程的库目录配置，并确认目标平台对应的依赖文件已经安装。',
    },
    {
      sourceFile: 'ZRDDS用户手册.pdf',
      documentId: 'zrdds-user-manual',
      section: '构建环境配置',
      pageStart: 18,
      pageEnd: 20,
      versionStatus: 'unknown',
      snippet: '不同开发环境的配置可能存在差异，请结合实际版本进行确认。',
    },
  ]
}

export async function mockFetchMessages(conversationId: string): Promise<ChatMessage[]> {
  await wait()
  return readAll()
    .filter((item) => item.conversationId === conversationId)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
}

export async function mockSendMessage(payload: SendMessageRequest): Promise<ChatMessage> {
  await wait()
  if (payload.userMessage.content.trim() === '/error' && !failedOnce.has(payload.userMessage.id)) {
    failedOnce.add(payload.userMessage.id)
    throw new Error('Mock 请求失败，请点击重试')
  }

  const all = readAll()
  const savedUserMessage = { ...payload.userMessage, status: 'success' as const }
  const existingIndex = all.findIndex((item) => item.id === savedUserMessage.id)
  if (existingIndex >= 0) all[existingIndex] = savedUserMessage
  else all.push(savedUserMessage)

  const assistantMessage: ChatMessage = {
    id: crypto.randomUUID(),
    conversationId: payload.conversationId,
    role: 'assistant',
    content:
      savedUserMessage.content.trim() === '/no-answer'
        ? '当前知识库中未找到足够可靠的依据。请尝试补充错误信息、使用场景或 ZRDDS 版本。'
        : buildAnswer(savedUserMessage.content),
    status: 'success',
    createdAt: new Date().toISOString(),
    answerStatus: savedUserMessage.content.trim() === '/no-answer' ? 'no_answer' : 'answered',
    citations: savedUserMessage.content.trim() === '/no-answer' ? [] : buildCitations(),
  }
  all.push(assistantMessage)
  writeJson(KEY, all)
  return assistantMessage
}
