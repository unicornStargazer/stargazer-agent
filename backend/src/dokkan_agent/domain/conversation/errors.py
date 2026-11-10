"""会话用例的稳定失败语义；不携带数据库文本、模型响应或用户正文。"""


class ConversationStorageError(RuntimeError):
    """读写失败；成功轮次不能部分保存，调用方可以稍后用同一请求 ID 重试。"""


class RequestConflictError(ValueError):
    """同一请求 ID 对应不同指纹，不能覆盖原请求。"""


class SessionBusyError(RuntimeError):
    """会话有运行中或排队请求，暂时不允许删除。"""


class UnknownProfileError(ValueError):
    """显式选择或已保存的模型配置已不存在，需要重新选择。"""


class RequestAttemptsExceeded(RuntimeError):
    """同一失败请求已达到三次尝试；新操作应使用新的请求 ID。"""


class InterruptedRequestError(RuntimeError):
    """等待中的原请求失败或取消；本次等待不能隐式重新执行。"""
