import { describe, expect, it } from 'vitest'

import { appConfig } from './app'

describe('appConfig', () => {
  it('provides a valid API configuration', () => {
    expect(appConfig.apiBaseUrl).toBeTruthy()
    expect(appConfig.apiTimeout).toBeGreaterThan(0)
    expect(typeof appConfig.useMock).toBe('boolean')
  })
})
