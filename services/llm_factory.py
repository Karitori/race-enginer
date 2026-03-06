import logging
import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


class ChatClient:
    """Thin LangChain chat wrapper with optional runtime configuration."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ):
        self.provider = provider or os.getenv("LLM_PROVIDER")
        self.model = model or os.getenv("LLM_MODEL")
        self.temperature = temperature
        self._model: Any = None

        if not self.provider or not self.model:
            return

        try:
            self._model = init_chat_model(
                self.model,
                model_provider=self.provider,
                temperature=self.temperature,
            )
        except Exception as exc:
            logger.warning("failed to initialize chat model: %s", exc)
            self._model = None

    @property
    def available(self) -> bool:
        return self._model is not None

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str | None:
        if not self._model:
            return None

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        try:
            response = await self._model.ainvoke(messages)
        except Exception as exc:
            logger.error("llm request failed: %s", exc)
            return None

        content = getattr(response, "content", None)
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    text_parts.append(str(item["text"]))
            text = "\n".join(p for p in text_parts if p).strip()
            return text or None
        return None
