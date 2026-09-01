import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

const projectDirectory = path.dirname(fileURLToPath(import.meta.url))
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.resolve(
  projectDirectory,
  '..',
  '..',
  'playwright-browsers',
)

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      VITE_USE_MOCK: 'true',
      VITE_API_TIMEOUT: '30000',
    },
  },
})
