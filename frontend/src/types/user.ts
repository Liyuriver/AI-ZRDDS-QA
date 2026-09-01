export interface User {
  id: string
  username: string
  displayName: string
  email?: string
}
export interface AuthSession {
  token: string
  user: User
}
export interface LoginRequest {
  username: string
  password: string
  email?: string
}
export interface RegisterRequest {
  username: string
  password: string
  email: string
}
