import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatComposer from './ChatComposer.vue'

describe('ChatComposer', () => {
  it('emits a trimmed query when Enter is pressed', async () => {
    const wrapper = mount(ChatComposer)
    const textarea = wrapper.get('textarea')

    await textarea.setValue('  Psapi.lib 丢失怎么办  ')
    await textarea.trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('send')).toEqual([['Psapi.lib 丢失怎么办']])
  })

  it('does not emit an empty query', async () => {
    const wrapper = mount(ChatComposer)
    const textarea = wrapper.get('textarea')

    await textarea.setValue('   ')
    await textarea.trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('send')).toBeUndefined()
  })
})
