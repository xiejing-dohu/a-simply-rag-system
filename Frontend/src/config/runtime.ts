/** 运行时环境变量配置文件

通过 Vite 加载环境变量，统一导出 API 请求基础基准路径。
*/
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000')
  .replace(/\/$/, '')
