"""旧历史到完整轮次的转换；不修改仓储中的孤立消息或原始元数据。"""

from dokkan_agent.domain.agent.models import MessageRole
from dokkan_agent.domain.conversation.models import ConversationTurn
from dokkan_agent.domain.conversation.ports import HistoryMessage


def complete_turns(messages: tuple[HistoryMessage, ...]) -> tuple[ConversationTurn, ...]:
    turns: list[ConversationTurn] = []
    pending: str | None = None
    for message in messages:
        if message.role == MessageRole.USER:
            pending = message.content
        elif pending is not None and message.reply is not None:
            user_content = pending.strip()
            if user_content:
                content = message.reply.content
                assistant_content = content.strip()
                if assistant_content:
                    turn = ConversationTurn(pending, message.reply)
                    turns.append(turn)
            pending = None
    completed = tuple(turns)
    return completed
