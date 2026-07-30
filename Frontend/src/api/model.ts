import request from './request'
import type { ModelInfo } from '../types'

export const getModels = () => {
  return request.get<ModelInfo[]>('/models/')
}
