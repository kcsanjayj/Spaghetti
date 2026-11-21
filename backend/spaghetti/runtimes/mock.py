"""Offline demo cook. Extractive, deterministic, zero network. Only for tests, eval and screenshots."""
import json
import os
import re
import time

from ..engine.python_engine import tokenize


class MockModel:
    def chat(self, messages, model):
        time.sleep(float(os.getenv("SPAGHETTI_DEMO_DELAY", "0")))  # slow it down to watch the animations
        system, user = messages[0]["content"], messages[-1]["content"]
        if system.startswith("ROLE:TASTER"):
            answer = user.split("ANSWER:", 1)[-1]
            context = user.split("ANSWER:", 1)[0]
            a, c = set(tokenize(answer)), set(tokenize(context))
            score = round(10 * len(a & c) / len(a), 1) if a else 0
            return json.dumps({"score": score, "issues": "" if score >= 7 else "Some words are not in the pantry."})
        question = user.rsplit("QUESTION:", 1)[-1].strip()
        context = user.split("QUESTION:", 1)[0]
        if system.startswith("ROLE:SECTION_SUMMARY") or system.startswith("ROLE:SUMMARY_REDUCE"):
            excerpts = []
            for line in context.splitlines():
                match = re.match(r"\[(\d+)\]\s*(.*)", line)
                if match and match.group(2).strip():
                    excerpts.append(match.group(2).strip())
            return " ".join(excerpts[:8]) or "I could not find that in the pantry."
        if "whole-document summary request" in system:
            summaries = []
            for line in context.splitlines():
                match = re.match(r"\[(\d+)\]\s*(.*)", line)
                if match and match.group(2).strip():
                    text = re.sub(r"^Source chunks \d+-\d+:\s*", "", match.group(2)).strip()
                    summaries.append(f"{text} [{match.group(1)}]")
            return " ".join(summaries) or "I could not find that in the pantry."
        q = set(tokenize(question))
        best, best_n = None, 0
        for line in context.splitlines():
            m = re.match(r"\[(\d+)\]\s*(.*)", line)
            if not m:
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", m.group(2)):
                n = len(q & set(tokenize(sentence)))
                if n > best_n:
                    best, best_n = f"{sentence.strip()} [{m.group(1)}]", n
        return best or "I could not find that in the pantry."

    def chat_stream(self, messages, model):
        for word in self.chat(messages, model).split(" "):
            time.sleep(float(os.getenv("SPAGHETTI_DEMO_TOKEN_DELAY", "0")))
            yield word + " "
