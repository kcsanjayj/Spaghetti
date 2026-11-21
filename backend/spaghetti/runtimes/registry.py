from ..config import Settings
from .mock import MockModel
from .ollama import Ollama


def build_model(settings: Settings, model: str):
    """Ollama for everything; the offline mock only when SPAGHETTI_DEMO=1 and the model is called 'mock'."""
    return MockModel() if (settings.demo and model == "mock") else Ollama(settings.ollama_host)
