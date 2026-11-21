"""Reasoning models (Qwen3, DeepSeek-R1) write their thoughts inside <think>...</think>. Split them from the answer."""
import re

_BLOCK = re.compile(r"<think>(.*?)</think>", re.S)


def split_thinking(text: str) -> tuple[str, str]:
    """Return (answer, thoughts). Handles missing opening tag and truncated (unclosed) thinking."""
    thoughts = "\n".join(m.strip() for m in _BLOCK.findall(text))
    answer = _BLOCK.sub("", text)
    if "</think>" in answer:  # some builds omit the opening tag
        thoughts, _, answer = answer.partition("</think>")
    elif "<think>" in answer:  # ran out of room while thinking
        answer, _, rest = answer.partition("<think>")
        thoughts = (thoughts + "\n" + rest).strip()
    return answer.strip(), thoughts.strip()


class ThinkSplitter:
    """Incremental version for streaming: feed chunks, get [("think"|"answer", text)], even when a tag is split across chunks."""
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.buf, self.thinking = "", False

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self.buf += chunk
        out = []
        while True:
            tag = self.CLOSE if self.thinking else self.OPEN
            i = self.buf.find(tag)
            kind = "think" if self.thinking else "answer"
            if i >= 0:
                if i:
                    out.append((kind, self.buf[:i]))
                self.buf, self.thinking = self.buf[i + len(tag):], not self.thinking
                continue
            keep = next((n for n in range(min(len(tag) - 1, len(self.buf)), 0, -1) if tag.startswith(self.buf[-n:])), 0)
            emit, self.buf = self.buf[: len(self.buf) - keep], self.buf[len(self.buf) - keep:]
            if emit:
                out.append((kind, emit))
            return out

    def flush(self) -> list[tuple[str, str]]:
        rest, self.buf = self.buf, ""
        return [("think" if self.thinking else "answer", rest)] if rest else []
