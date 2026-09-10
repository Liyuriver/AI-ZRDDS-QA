const DEFAULT_API_BASE_URL = '/api/v1'
// A live RAG turn may include Dify retrieval, recovery retrieval, reranking,
// and one bounded validation retry. Keep the browser request alive while the
// backend completes that chain instead of reporting a client-side timeout.
const DEFAULT_API_TIMEOUT = 180_000

function parsePositiveNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value)

  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export const appConfig = Object.freeze({
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL,
  apiTimeout: parsePositiveNumber(import.meta.env.VITE_API_TIMEOUT, DEFAULT_API_TIMEOUT),
  useMock: import.meta.env.VITE_USE_MOCK !== 'false',
})
