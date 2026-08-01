/** 模型目录发现 API 模块 */

import request from './request'
import type { ModelInfo } from '../types'

/** 获取系统发现的可用模型列表 */
export const getModels = () => {
  return request.get<ModelInfo[]>('/models/')
}
