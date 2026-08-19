def count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def count_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", "")) + 4
    return total
