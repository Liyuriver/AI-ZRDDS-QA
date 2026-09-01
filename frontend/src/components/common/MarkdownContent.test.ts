import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MarkdownContent from './MarkdownContent.vue'

describe('MarkdownContent', () => {
  it('copies the plain code content from a rendered code block', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const wrapper = mount(MarkdownContent, {
      props: { content: '```bash\necho hello\n```' },
    })

    await wrapper.get('[data-copy-code]').trigger('click')

    expect(writeText).toHaveBeenCalledWith('echo hello\n')
  })
})
