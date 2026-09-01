import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import cpp from 'highlight.js/lib/languages/cpp'
import ini from 'highlight.js/lib/languages/ini'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import typescript from 'highlight.js/lib/languages/typescript'
import MarkdownIt from 'markdown-it'

hljs.registerLanguage('bash', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('ini', ini)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('python', python)
hljs.registerLanguage('typescript', typescript)

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  highlight(code, language): string {
    const languageLabel = language && hljs.getLanguage(language) ? language : 'text'
    const copyButton =
      '<button type="button" class="code-copy-button" data-copy-code>复制代码</button>'
    if (language && hljs.getLanguage(language)) {
      return `<div class="code-block"><span class="code-block__language">${languageLabel}</span>${copyButton}<pre><code class="hljs language-${language}">${hljs.highlight(code, { language }).value}</code></pre></div>`
    }
    return `<div class="code-block"><span class="code-block__language">${languageLabel}</span>${copyButton}<pre><code class="hljs">${escapeHtml(code)}</code></pre></div>`
  },
})

export function renderMarkdown(content: string): string {
  return DOMPurify.sanitize(markdown.render(content), {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target', 'rel'],
  })
}
