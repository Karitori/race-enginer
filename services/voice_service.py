import asyncio
import logging
import os
import time
from typing import Any

from models.telemetry import DriverQuery, DrivingInsight
from models.voice import VoiceSummaryDecision
from services.audio_input_service import AudioInputService
from services.audio_output_service import AudioOutputService
from services.event_bus_service import bus
from services.llm_factory import ChatClient
from utils.radio_text import to_radio_brief

logger = logging.getLogger(__name__)


def _parse_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


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
        self._recent_insight_times: dict[str, float] = {}
        self._insight_repeat_window_sec = _parse_float(
            os.getenv("VOICE_INSIGHT_REPEAT_WINDOW_SEC"), 18.0
        )
        self._warning_repeat_window_sec = _parse_float(
            os.getenv("VOICE_WARNING_REPEAT_WINDOW_SEC"), 10.0
        )
        self._strategy_repeat_window_sec = _parse_float(
            os.getenv("VOICE_STRATEGY_REPEAT_WINDOW_SEC"), 14.0
        )

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
        bus.subscribe("race_session_changed", self._handle_race_session_changed)

        try:
            loop = asyncio.get_running_loop()
            self._tasks.append(loop.create_task(self._speaker_loop()))
            self._tasks.append(loop.create_task(self._batch_summarize_loop()))
            if self.audio_input.available:
                self._tasks.append(loop.create_task(self._stt_loop()))
            self._tasks.append(loop.create_task(bus.publish("stt_status", self.get_stt_status())))
        except RuntimeError:
            pass

    def get_stt_status(self) -> dict[str, Any]:
        return self.audio_input.get_control_status()

    async def apply_stt_control(
        self,
        *,
        action: str,
        enabled: bool | None = None,
        mode: str | None = None,
        mic_index: int | None = None,
    ) -> dict[str, Any]:
        status = self.audio_input.apply_control_action(
            action=action,
            enabled=enabled,
            mode=mode,
            mic_index=mic_index,
        )
        await bus.publish("stt_status", status)
        return status

    def get_stt_devices(self) -> dict[str, Any]:
        names = self.audio_input.list_microphone_names()
        return {
            "devices": [{"index": idx, "name": name} for idx, name in enumerate(names)],
            "selected_index": self.audio_input.mic_index,
        }

    async def _update_talk_level(self, data: dict[str, Any]):
        self.talk_level = int(data.get("talk_level", 5))
        logger.info("Race Engineer talk level updated to %d", self.talk_level)

    async def _handle_incoming_insight(self, insight: DrivingInsight):
        brief_message = to_radio_brief(
            insight.message,
            max_sentences=2,
            max_chars=170,
        )
        if not brief_message:
            return
        if brief_message != insight.message:
            insight = DrivingInsight(
                message=brief_message,
                type=insight.type,
                priority=insight.priority,
            )
        if not self._should_enqueue_insight(insight):
            logger.debug(
                "VOICE ENGINE: suppressing duplicate insight within cooldown: %s",
                brief_message,
            )
            return
        self._seq += 1
        queue_priority = (
            -insight.priority
            if (insight.priority >= 4 or insight.type == "warning")
            else 0
        )
        await self._priority_queue.put((queue_priority, self._seq, insight))

    def _insight_signature(self, insight: DrivingInsight) -> str:
        normalized = " ".join((insight.message or "").strip().lower().split())
        return f"{insight.type}|{insight.priority}|{normalized}"

    def _repeat_window_for(self, insight: DrivingInsight) -> float:
        if insight.type == "warning" or insight.priority >= 5:
            return self._warning_repeat_window_sec
        if insight.type == "strategy":
            return self._strategy_repeat_window_sec
        return self._insight_repeat_window_sec

    def _should_enqueue_insight(self, insight: DrivingInsight) -> bool:
        now = time.monotonic()
        signature = self._insight_signature(insight)
        window = max(0.0, self._repeat_window_for(insight))
        last_time = self._recent_insight_times.get(signature)
        if last_time is not None and (now - last_time) < window:
            return False

        self._recent_insight_times[signature] = now
        # Keep the dedupe cache bounded.
        if len(self._recent_insight_times) > 128:
            cutoff = now - max(self._insight_repeat_window_sec, 60.0)
            stale = [k for k, v in self._recent_insight_times.items() if v < cutoff]
            for key in stale:
                self._recent_insight_times.pop(key, None)
        return True

    async def _stt_loop(self) -> None:
        await self.audio_input.run(self._on_driver_transcript)

    def _prune_noncritical_queue_for_barge_in(self) -> int:
        retained: list[tuple[int, int, DrivingInsight]] = []
        dropped = 0
        while True:
            try:
                item = self._priority_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            _, _, insight = item
            if insight.priority >= 4 or insight.type == "warning":
                retained.append(item)
            else:
                dropped += 1

        for item in retained:
            self._priority_queue.put_nowait(item)
        return dropped

    def _barge_in_if_driver_speaks(self) -> None:
        if not self._is_speaking:
            return
        interrupted = self.audio_output.interrupt_playback()
        dropped = self._prune_noncritical_queue_for_barge_in()
        logger.info(
            "VOICE ENGINE: Driver barge-in detected, interrupted=%s, dropped_noncritical=%d",
            interrupted,
            dropped,
        )

    async def _on_driver_transcript(self, text: str, confidence: float) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self._barge_in_if_driver_speaks()
        logger.info("VOICE INPUT: '%s' (conf %.2f)", cleaned, confidence)
        await bus.publish(
            "driver_transcript",
            {"text": cleaned, "confidence": float(confidence)},
        )
        await bus.publish("driver_query", DriverQuery(query=cleaned, confidence=confidence))

    async def _handle_race_session_changed(self, payload: dict[str, Any] | None = None) -> None:
        cleared = 0
        while True:
            try:
                self._priority_queue.get_nowait()
                cleared += 1
            except asyncio.QueueEmpty:
                break
        self._recent_insight_times.clear()
        self._seq = 0
        self.audio_output.interrupt_playback()
        logger.info(
            "VOICE ENGINE: reset queue/dedupe for new race session (%s), cleared=%d",
            payload or {},
            cleared,
        )

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
Never output bullet points, numbering, markdown, or list formatting.

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
                    tts_text = to_radio_brief(
                        decision.tts_text,
                        max_sentences=2,
                        max_chars=170,
                    )
                    if not tts_text:
                        continue
                    logger.info("VOICE ENGINE SMART SUMMARY: %s", tts_text)
                    summary_insight = DrivingInsight(
                        message=tts_text,
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
