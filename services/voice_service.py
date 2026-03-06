import asyncio
import logging
from typing import Any

from models.telemetry import DriverQuery, DrivingInsight
from models.voice import VoiceSummaryDecision
from services.audio_input_service import AudioInputService
from services.audio_output_service import AudioOutputService
from services.event_bus_service import bus
from services.llm_factory import ChatClient

logger = logging.getLogger(__name__)


class VoiceAssistant:
    """
    Handles voice I/O for race engineer comms.
    - Outbound: queued TTS playback
    - Inbound: optional microphone STT -> driver_query events
    """

    def __init__(self):
        self.talk_level = 5
        self._is_speaking = False
        self._speak_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[Any]] = []

        # Priority queue: (negative_priority, sequence, insight)
        self._priority_queue: asyncio.PriorityQueue[tuple[int, int, DrivingInsight]] = (
            asyncio.PriorityQueue()
        )
        self._seq = 0

        self.summary_client = ChatClient(role="voice", temperature=0.2)
        if not self.summary_client.available:
            logger.warning(
                "voice summarizer LLM not configured. Smart summarizing disabled."
            )

        self.audio_output = AudioOutputService()
        self.audio_input = AudioInputService()
        if not self.audio_output.available:
            logger.warning("tts backend unavailable; voice output running in simulated mode.")
        if self.audio_input.enabled and not self.audio_input.available:
            logger.warning("stt enabled but backend unavailable; microphone capture disabled.")

        bus.subscribe("driving_insight", self._handle_incoming_insight)
        bus.subscribe("talk_level_changed", self._update_talk_level)

        try:
            loop = asyncio.get_running_loop()
            self._tasks.append(loop.create_task(self._speaker_loop()))
            self._tasks.append(loop.create_task(self._batch_summarize_loop()))
            if self.audio_input.available:
                self._tasks.append(loop.create_task(self._stt_loop()))
        except RuntimeError:
            pass

    async def _update_talk_level(self, data: dict[str, Any]):
        self.talk_level = int(data.get("talk_level", 5))
        logger.info("Race Engineer talk level updated to %d", self.talk_level)

    async def _handle_incoming_insight(self, insight: DrivingInsight):
        self._seq += 1
        queue_priority = (
            -insight.priority
            if (insight.priority >= 4 or insight.type == "warning")
            else 0
        )
        await self._priority_queue.put((queue_priority, self._seq, insight))

    async def _stt_loop(self) -> None:
        await self.audio_input.run(self._on_driver_transcript)

    async def _on_driver_transcript(self, text: str, confidence: float) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        logger.info("VOICE INPUT: '%s' (conf %.2f)", cleaned, confidence)
        await bus.publish("driver_query", DriverQuery(query=cleaned, confidence=confidence))

    async def _speaker_loop(self):
        while True:
            _, _, insight = await self._priority_queue.get()
            is_high_priority = insight.priority >= 4 or insight.type == "warning"

            if self._is_speaking and not is_high_priority:
                logger.info(
                    "VOICE ENGINE: Dropping low-priority message while speaking: %s...",
                    insight.message[:40],
                )
                continue

            logger.info(
                "VOICE ENGINE [%s] (Pri %d): TTS '%s...'",
                insight.type.upper(),
                insight.priority,
                insight.message[:60],
            )

            async with self._speak_lock:
                self._is_speaking = True
                try:
                    await self._speak(
                        insight.message,
                        insight_type=insight.type,
                        priority=insight.priority,
                    )
                finally:
                    self._is_speaking = False

    async def _speak(
        self,
        message: str,
        *,
        insight_type: str = "info",
        priority: int = 3,
    ):
        try:
            await self.audio_output.speak(
                message,
                style_hint=insight_type,
                priority=priority,
            )
        except Exception as exc:
            logger.error("tts speak error: %s", exc)

    async def _batch_summarize_loop(self):
        while True:
            await asyncio.sleep(8)

            if self._is_speaking or self._priority_queue.qsize() < 2:
                continue
            if not self.summary_client.available:
                continue

            batch: list[DrivingInsight] = []
            remaining: list[tuple[int, int, DrivingInsight]] = []
            while not self._priority_queue.empty():
                try:
                    item = self._priority_queue.get_nowait()
                    _, _, insight = item
                    if insight.priority >= 4 or insight.type == "warning":
                        remaining.append(item)
                    else:
                        batch.append(insight)
                except asyncio.QueueEmpty:
                    break

            for item in remaining:
                await self._priority_queue.put(item)

            if len(batch) < 2:
                for insight in batch:
                    self._seq += 1
                    await self._priority_queue.put((0, self._seq, insight))
                continue

            messages_text = "\n".join(
                f"- [Type: {i.type} | Priority: {i.priority}] {i.message}" for i in batch
            )
            user_prompt = f"""Summarize these queued engineer messages into one concise radio call.

Driver talk level is {self.talk_level}/10 (1 = very quiet, 10 = very detailed).
Respect the talk level and keep critical warnings over informational chatter.

Queued Messages:
{messages_text}
"""

            try:
                logger.info(
                    "VOICE ENGINE: Requesting structured summary for %d queued messages...",
                    len(batch),
                )
                response = await self.summary_client.generate_structured(
                    system_prompt=(
                        "You are an F1 race engineer voice summarizer. "
                        "Return a decision about whether to speak now and what to say."
                    ),
                    user_prompt=user_prompt,
                    schema=VoiceSummaryDecision,
                )
                decision: VoiceSummaryDecision | None = None
                if isinstance(response, VoiceSummaryDecision):
                    decision = response
                elif isinstance(response, dict):
                    try:
                        decision = VoiceSummaryDecision.model_validate(response)
                    except Exception:
                        decision = None

                if decision and decision.escalate and decision.tts_text.strip():
                    logger.info("VOICE ENGINE SMART SUMMARY: %s", decision.tts_text)
                    summary_insight = DrivingInsight(
                        message=decision.tts_text.strip(),
                        type="info",
                        priority=3,
                    )
                    self._seq += 1
                    await self._priority_queue.put((0, self._seq, summary_insight))
                elif decision:
                    logger.info(
                        "VOICE ENGINE SMART SUMMARY: Silence preferred based on talk level."
                    )
                elif batch:
                    self._seq += 1
                    await self._priority_queue.put((0, self._seq, batch[0]))

            except Exception as exc:
                logger.error("error during smart summarization: %s", exc)
                if batch:
                    self._seq += 1
                    await self._priority_queue.put((0, self._seq, batch[0]))

    def stop(self) -> None:
        self.audio_input.stop()
        self.audio_output.stop()
        for task in self._tasks:
            task.cancel()
