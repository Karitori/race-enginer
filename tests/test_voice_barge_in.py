import asyncio

import pytest

from models.telemetry import DrivingInsight
from services.voice_service import VoiceAssistant


class _StubAudioOutput:
    def __init__(self) -> None:
        self.interrupt_calls = 0

    def interrupt_playback(self) -> bool:
        self.interrupt_calls += 1
        return True


@pytest.mark.asyncio
async def test_barge_in_interrupts_and_prunes_noncritical_queue():
    assistant = object.__new__(VoiceAssistant)
    assistant._is_speaking = True
    assistant.audio_output = _StubAudioOutput()
    assistant._priority_queue = asyncio.PriorityQueue()

    await assistant._priority_queue.put((0, 1, DrivingInsight(message="info", type="info", priority=2)))
    await assistant._priority_queue.put((0, 2, DrivingInsight(message="warn", type="warning", priority=5)))

    assistant._barge_in_if_driver_speaks()

    assert assistant.audio_output.interrupt_calls == 1
    assert assistant._priority_queue.qsize() == 1
    _, _, remaining = assistant._priority_queue.get_nowait()
    assert remaining.type == "warning"

