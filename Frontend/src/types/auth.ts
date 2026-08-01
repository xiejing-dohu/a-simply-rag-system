/** 用户与鉴权相关的 TypeScript 接口类型定义 */

/** 用户实体及 Token 额度统计接口 */
export interface User {
  id: number
  username: string
  email: string
  role: 'admin' | 'employee'
  is_root_admin: boolean
  is_active: boolean
  created_at: string
  five_hour_token_limit: number | null
  weekly_token_limit: number | null
  five_hour_tokens_used: number
  weekly_tokens_used: number
  input_tokens_used: number
  output_tokens_used: number
  total_tokens_used: number
  five_hour_window_started_at: string
  weekly_window_started_at: string
  five_hour_resets_at: string
  weekly_resets_at: string
}

/** 登录表单接口 */
export interface LoginForm {
  username: string
  password: string
}

/** 注册表单接口 */
export interface RegisterForm {
  username: string
  email: string
  password: string
}

/** 登录响应 Token 数据接口 */
export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: User
}
