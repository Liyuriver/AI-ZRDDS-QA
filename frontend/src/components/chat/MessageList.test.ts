import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MessageList from './MessageList.vue'

describe('MessageList', () => {
  it('updates the waiting stage as time passes', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MessageList, {
      props: { messages: [], loading: false, sending: true },
    })

    expect(wrapper.text()).toContain('正在检索知识库')
    await vi.advanceTimersByTimeAsync(9000)
    expect(wrapper.text()).toContain('正在整理检索证据')
    expect(wrapper.text()).toContain('已等待 9 秒')
    await vi.advanceTimersByTimeAsync(17000)
    expect(wrapper.text()).toContain('正在生成回答')

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('shows a specific error after the request stops', () => {
    const wrapper = mount(MessageList, {
      props: {
        messages: [],
        loading: false,
        sending: false,
        error: 'AI 服务暂时不可用，请稍后重试。',
      },
    })

    expect(wrapper.get('[role="alert"]').text()).toContain('AI 服务暂时不可用')
  })
})
