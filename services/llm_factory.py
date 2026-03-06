import logging
import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from services.llm_profile_service import resolve_llm_profile

logger = logging.getLogger(__name__)


class ChatClient:
    """Thin LangChain chat wrapper with optional runtime configuration."""

    def __init__(
        self,
        *,
        role: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ):
        self.role = role
        if role and provider is None and model is None:
            profile = resolve_llm_profile(role=role, default_temperature=temperature)
            self.provider = profile.provider
            self.model = profile.model
            self.temperature = profile.temperature
            self.source = profile.source
        else:
            self.provider = provider or os.getenv("LLM_PROVIDER")
            self.model = model or os.getenv("LLM_MODEL")
            self.temperature = temperature
            self.source = "explicit_or_global"
        self._model: Any = None

        if not self.provider or not self.model:
            logger.info(
                "llm client unavailable for role=%s (provider/model unset, source=%s)",
                self.role or "default",
                self.source,
            )
            return

        try:
            self._model = init_chat_model(
                self.model,
                model_provider=self.provider,
                temperature=self.temperature,
            )
            logger.info(
                "llm client ready for role=%s provider=%s model=%s source=%s",
                self.role or "default",
                self.provider,
                self.model,
                self.source,
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

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> BaseModel | dict[str, Any] | None:
        """Generate structured output bound to a Pydantic schema."""
        if not self._model:
            return None

        try:
            model = self._model.with_structured_output(schema)
        except Exception as exc:
            logger.warning("structured output is unavailable for this model: %s", exc)
            return None

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = await model.ainvoke(messages)
        except Exception as exc:
            logger.error("structured llm request failed: %s", exc)
            return None

        if isinstance(response, BaseModel):
            return response
        if isinstance(response, dict):
            return response
        return None
