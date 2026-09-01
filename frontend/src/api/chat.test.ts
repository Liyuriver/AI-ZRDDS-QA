import { describe, expect, it } from 'vitest'

import { mapChatResponse, mapHistoryMessage } from './chat'

describe('real chat response mapping', () => {
  it('maps backend evidence without claiming version compatibility', () => {
    const message = mapChatResponse({
      code: 0,
      message: 'success',
      data: {
        conversation_id: 'conversation-1',
        answer: '测试回答',
        status: 'answered',
        sources: [
          {
            document: '排障指南.pdf',
            section: '依赖配置',
            page: 46,
            score: 0.91,
            quote: '检查库目录。',
          },
        ],
        images: [],
      },
    })
    expect(message.citations?.[0]?.sourceFile).toBe('排障指南.pdf')
    expect(message.citations?.[0]?.versionStatus).toBe('unknown')
  })

  it('maps insufficient evidence to the no-answer state', () => {
    const message = mapChatResponse({
      code: 0,
      message: 'success',
      data: {
        conversation_id: 'conversation-1',
        answer: '当前证据不足',
        status: 'insufficient_evidence',
        sources: [],
        images: [],
      },
    })
    expect(message.answerStatus).toBe('no_answer')
  })

  it('restores persisted citations and images from assistant history', () => {
    const message = mapHistoryMessage({
      id: 'message-1',
      conversation_id: 'conversation-1',
      role: 'assistant',
      content: '历史回答',
      answer_status: 'answered',
      sources: [
        {
          document: '故障排查指南.pdf',
          section: '编译失败',
          page: 46,
          score: 0.9,
          quote: '检查 Psapi.lib。',
        },
      ],
      images: [{ url: '/static/example.png', document: '故障排查指南.pdf' }],
      created_at: '2026-09-01T12:00:00',
    })

    expect(message.citations?.[0]?.page).toBe(46)
    expect(message.citations?.[0]?.images).toEqual(['/static/example.png'])
  })
})
