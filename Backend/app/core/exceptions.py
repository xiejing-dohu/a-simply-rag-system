"""应用层共享异常定义模块

包含传输层和服务层共享的自定义异常类。
"""


class TransientUpstreamError(RuntimeError):
    """上游网络或服务暂态异常

    当上游依赖服务（如 LLM、Embedding、Rerank API 等）发生临时性故障时抛出，
    提示该请求在稍后重试时有可能成功。
    """
