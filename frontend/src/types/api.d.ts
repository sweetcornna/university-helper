/**
 * Shared API contracts — kept in a single file while the codebase is mid-migration
 * from JSX to TSX. New typed modules import from here; .jsx files ignore it.
 */

export type Json =
  | string
  | number
  | boolean
  | null
  | Json[]
  | { [key: string]: Json }

export interface AuthResponse {
  access_token: string
  token_type: 'bearer'
  user_id: number
  tenant_db_name: string
  shuake_token?: string
}

export interface ApiErrorPayload {
  code?: string
  message?: string
  detail?:
    | string
    | Array<{
        loc?: (string | number)[]
        msg?: string
        message?: string
        type?: string
      }>
  error?: string
  msg?: string
  data?: { message?: string }
  status?: boolean
}

export interface CourseTaskStatus {
  task_id: string
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
  progress?: number
  message?: string
  updated_at?: string
}

declare module '*.svg' {
  const src: string
  export default src
}

declare module '*.png' {
  const src: string
  export default src
}
