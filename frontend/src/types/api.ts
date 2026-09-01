export interface ApiErrorPayload {
  message?: string
  detail?: string | { message?: string }
  code?: string
}

export interface ApiError {
  status: number | null
  code: string
  message: string
}
