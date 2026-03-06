import asyncio
import logging

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from services.feedback_service import PerformanceAnalyzer
from services.telemetry_state_service import SessionState
from services.app_service import app, set_datastore, set_parser_manager
from services.voice_service import VoiceAssistant
from services.telemetry_mode_service import TelemetryModeService
from services.http_server_service import start_http_server

from db.telemetry_repository import DuckDBTelemetryRepository
from services.race_engineer_service import RaceEngineerService
from agents.strategy_agent import StrategyAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting Race Engineer...")

    repository = DuckDBTelemetryRepository("live_session.duckdb")
    set_datastore(repository)

    session_state = SessionState()
    parser_manager = TelemetryModeService()
    set_parser_manager(parser_manager)
    feedback_analyzer = PerformanceAnalyzer()
    voice_assistant = VoiceAssistant()
    race_engineer = RaceEngineerService()
    strategy_agent = StrategyAgent(repository=repository, poll_interval=15)

    _ = (session_state, feedback_analyzer, voice_assistant, race_engineer)

    strategy_task = asyncio.create_task(strategy_agent.start())

    try:
        await asyncio.gather(
            parser_manager.start(),
            start_http_server(app),
            strategy_task,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("Shutting down Race Engineer...")
        strategy_agent.stop()
        strategy_task.cancel()
        voice_assistant.stop()
        parser_manager.stop()
        repository.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


