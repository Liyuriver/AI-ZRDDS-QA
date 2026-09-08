import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CitationList from './CitationList.vue'

describe('CitationList', () => {
  it('shows three citations by default and reveals the rest', async () => {
    const citations = Array.from({ length: 5 }, (_, index) => ({
      sourceFile: `文档${index + 1}.pdf`,
      versionStatus: 'unknown' as const,
    }))
    const wrapper = mount(CitationList, { props: { citations } })

    expect(wrapper.findAll('.citation-item')).toHaveLength(3)
    expect(wrapper.text()).toContain('查看另外 2 条依据')

    await wrapper.get('.citation-list__more').trigger('click')
    expect(wrapper.findAll('.citation-item')).toHaveLength(5)
    expect(wrapper.text()).toContain('收起额外依据')
  })
})
