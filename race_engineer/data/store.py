import duckdb
import logging
import asyncio
from typing import Optional
from race_engineer.core.event_bus import bus
from race_engineer.telemetry.models import TelemetryTick

logger = logging.getLogger(__name__)

class DataStore:
    """
    Subscribes to telemetry events and stores them in a DuckDB time-series database.
    This allows the background Analyst Team to query historical data via SQL.
    """
    def __init__(self, db_path: str = "telemetry.duckdb"):
        self.db_path = db_path
        # Connect to DuckDB (creates the file if it doesn't exist)
        self.conn = duckdb.connect(self.db_path)
        self._init_db()
        
        # We batch inserts for performance rather than writing on every single 60Hz tick
        self._insert_buffer = []
        self._batch_size = 60 # About 1 second of data at 60Hz
        
        # Subscribe to telemetry ticks
        bus.subscribe("telemetry_tick", self._handle_tick)

    def _init_db(self):
        """Creates the telemetry table if it doesn't exist."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                speed DOUBLE,
                gear INTEGER,
                throttle DOUBLE,
                brake DOUBLE,
                steering DOUBLE,
                engine_rpm INTEGER,
                tire_wear_fl DOUBLE,
                tire_wear_fr DOUBLE,
                tire_wear_rl DOUBLE,
                tire_wear_rr DOUBLE,
                lap INTEGER,
                track_position DOUBLE,
                sector INTEGER
            )
        """)
        logger.info(f"DataStore initialized at {self.db_path}")

    async def _handle_tick(self, tick: TelemetryTick):
        """Adds incoming telemetry to the buffer and flushes to DB if full."""
        self._insert_buffer.append((
            tick.speed, tick.gear, tick.throttle, tick.brake, tick.steering,
            tick.engine_rpm, tick.tire_wear_fl, tick.tire_wear_fr,
            tick.tire_wear_rl, tick.tire_wear_rr, tick.lap,
            tick.track_position, tick.sector
        ))
        
        if len(self._insert_buffer) >= self._batch_size:
            # We run the flush synchronously since duckdb is very fast, but 
            # ideally in a real high-throughput scenario, we'd run it in an executor.
            self._flush_buffer()

    def _flush_buffer(self):
        """Executes a batch insert into DuckDB."""
        if not self._insert_buffer:
            return
            
        try:
            # We use executemany for bulk insert
            self.conn.executemany("""
                INSERT INTO telemetry (
                    speed, gear, throttle, brake, steering, engine_rpm,
                    tire_wear_fl, tire_wear_fr, tire_wear_rl, tire_wear_rr,
                    lap, track_position, sector
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, self._insert_buffer)
            self._insert_buffer.clear()
        except Exception as e:
            logger.error(f"DuckDB insert error: {e}")

    def query(self, sql: str):
        """Allows other components (like StrategyTeam) to query the database."""
        # Ensure any pending data is flushed before querying
        self._flush_buffer()
        # Returns a pandas DataFrame (requires pandas installed, otherwise we'd use fetchall)
        return self.conn.execute(sql).fetchall()

    def close(self):
        self._flush_buffer()
        self.conn.close()
