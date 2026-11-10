"""模型依赖的公开失败类别；原始 HTTP 响应不得跨过此边界。"""


class ModelUnavailableError(RuntimeError):
    """连接、超时或上游协议失败，不能当作正常完整回答提交。"""


class ModelCapabilityError(RuntimeError):
    """模型不支持此次所需的工具能力；禁止默默退化为普通聊天。"""
