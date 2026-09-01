import { describe, expect, it } from 'vitest'

import { renderMarkdown } from './markdown'

describe('renderMarkdown', () => {
  it('renders common Markdown and highlighted code', () => {
    const html = renderMarkdown('## 标题\n\n```bash\necho hello\n```')
    expect(html).toContain('<h2>标题</h2>')
    expect(html).toContain('class="hljs language-bash"')
    expect(html).toContain('data-copy-code')
  })

  it('does not allow script injection', () => {
    const html = renderMarkdown('<script>alert(1)</script>\n[链接](javascript:alert(1))')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href="javascript:')
  })
})
