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
})
