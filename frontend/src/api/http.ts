import axios, { AxiosError } from 'axios'

import { appConfig } from '@/config/app'
import type { ApiError, ApiErrorPayload } from '@/types/api'
import { clearAuthSession, readAuthSession } from '@/utils/auth'

export const http = axios.create({
  baseURL: appConfig.apiBaseUrl,
  timeout: appConfig.apiTimeout,
  headers: {
    'Content-Type': 'application/json',
  },
})

http.interceptors.request.use((config) => {
  const token = readAuthSession()?.token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

function getErrorMessage(error: AxiosError<ApiErrorPayload>): string {
  if (error.code === AxiosError.ERR_NETWORK) {
    return '网络连接失败，请检查网络后重试。'
  }

  if (error.code === AxiosError.ECONNABORTED) {
    return '请求超时，请稍后重试。'
  }

  const detail = error.response?.data?.detail
  const backendMessage =
    error.response?.data?.message || (typeof detail === 'string' ? detail : detail?.message)

  if (error.response?.status === 400) return backendMessage || '提交的内容不符合要求。'
  if (error.response?.status === 403) return backendMessage || '你没有权限执行此操作。'
  if (error.response?.status === 404) return backendMessage || '请求的数据不存在或已被删除。'
  if (error.response?.status === 409) return backendMessage || '数据已存在或发生冲突。'
  if (error.response?.status === 429) return '请求过于频繁，请稍后再试。'
  if (error.response?.status === 502) return backendMessage || 'AI 服务暂时不可用，请稍后重试。'
  if (error.response?.status === 503) return backendMessage || '数据库服务暂时不可用。'
  if (error.response?.status && error.response.status >= 500) {
    return backendMessage || '服务器发生异常，请稍后重试。'
  }

  return backendMessage || '服务暂时不可用，请稍后重试。'
}

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorPayload>) => {
    const requestUrl = error.config?.url || ''
    if (error.response?.status === 401 && !requestUrl.includes('/auth/login')) {
      clearAuthSession()
      if (window.location.pathname !== '/login') window.location.assign('/login')
    }
    const apiError: ApiError = {
      status: error.response?.status ?? null,
      code: error.response?.data?.code || error.code || 'UNKNOWN_ERROR',
      message: getErrorMessage(error),
    }

    return Promise.reject(apiError)
  },
)
