import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CitationItem from './CitationItem.vue'

describe('CitationItem', () => {
  it('does not present an unknown version as compatible', () => {
    const wrapper = mount(CitationItem, {
      props: {
        index: 1,
        citation: {
          sourceFile: 'ZRDDS用户手册.pdf',
          page: 18,
          versionStatus: 'unknown',
        },
      },
    })

    expect(wrapper.text()).toContain('版本适用性未知')
    expect(wrapper.find('.citation-item__status--compatible').exists()).toBe(false)
  })

  it('renders previewable evidence images', () => {
    const wrapper = mount(CitationItem, {
      props: {
        index: 1,
        citation: {
          sourceFile: 'ZRDDS故障排查指南.pdf',
          versionStatus: 'unknown',
          images: ['/static/evidence.png'],
        },
      },
    })

    expect(wrapper.find('.citation-item__images').exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ElImage' }).props('previewSrcList')).toEqual([
      '/static/evidence.png',
    ])
  })

  it('collapses a long excerpt and expands it independently', async () => {
    const wrapper = mount(CitationItem, {
      props: {
        index: 2,
        citation: {
          sourceFile: 'ZRDDS用户手册.pdf',
          snippet: '一段很长的依据内容。'.repeat(30),
          versionStatus: 'compatible',
        },
      },
    })

    const excerpt = wrapper.get('.citation-item__snippet')
    expect(excerpt.classes()).not.toContain('is-expanded')
    await wrapper.get('.citation-item__excerpt button').trigger('click')
    expect(excerpt.classes()).toContain('is-expanded')
    expect(wrapper.text()).toContain('收起')
  })

  it('removes markdown artifacts without damaging code operators', () => {
    const wrapper = mount(CitationItem, {
      props: {
        index: 1,
        citation: {
          sourceFile: '开发手册.pdf',
          snippet:
            '### 创建 DataReader\n* **准备 Topic**\n> 阅读章节\n`DataReader` * reader = nullptr;',
          versionStatus: 'unknown',
        },
      },
    })

    const text = wrapper.get('.citation-item__snippet').text()
    expect(text).toContain('创建 DataReader')
    expect(text).toContain('准备 Topic')
    expect(text).toContain('DataReader * reader = nullptr;')
    expect(text).not.toContain('###')
    expect(text).not.toContain('**')
    expect(text).not.toContain('`')
  })
})
