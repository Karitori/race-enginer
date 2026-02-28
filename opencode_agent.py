import os
import time
import json
import httpx
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [OPENCODE AGENT] %(message)s")
logger = logging.getLogger(__name__)

# Config
WORKSPACE_DIR = os.path.join(os.path.dirname(__file__), "workspace")
DUCKDB_PATH = os.path.join(os.path.dirname(__file__), "live_session.duckdb")
API_URL = "http://localhost:8000/api/strategy"

def read_workspace_files():
    """Reads the contextual markdown files from the workspace."""
    context = ""
    for filename in os.listdir(WORKSPACE_DIR):
        if filename.endswith(".md"):
            with open(os.path.join(WORKSPACE_DIR, filename), "r") as f:
                context += f"\n\n--- {filename} ---\n{f.read()}"
    return context

def broadcast_status(message: str):
    """Sends a status update to the UI dashboard so the user can see what the agent is doing."""
    logger.info(message)
    try:
        httpx.post("http://localhost:8000/api/agent_status", json={"message": message})
    except Exception:
        pass

def query_telemetry():
    """Queries the DuckDB instance for the latest lap data."""
    try:
        import duckdb
        # We open the DB in read_only mode to avoid locking conflicts with the main server
        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        query = """
            SELECT lap, 
                   MAX(tire_wear_fl) as max_wear_fl, 
                   MAX(tire_wear_rr) as max_wear_rr 
            FROM telemetry 
            GROUP BY lap 
            ORDER BY lap DESC 
            LIMIT 3
        """
        results = conn.execute(query).fetchall()
        conn.close()
        
        if not results:
            return "No telemetry data available yet."
            
        data_summary = "Recent Laps Tire Wear (Lap, FL%, RR%):\n"
        for row in results:
            data_summary += f"- Lap {row[0]}: Front-Left {row[1]:.1f}%, Rear-Right {row[2]:.1f}%\n"
        return data_summary
    except Exception as e:
        logger.error(f"DuckDB query failed: {e}")
        return "Failed to read telemetry database."

# Define the Tool for Gemini to call
def send_insight_to_race_engineer(summary: str, recommendation: str, criticality: int):
    """
    Sends a strategic insight to the main Race Engineer server.
    Use this tool when you have formed a concrete recommendation based on telemetry and workspace knowledge.
    
    Args:
        summary: A short description of the current situation (e.g. "Rear right wear is 46%").
        recommendation: What the driver should do (e.g. "Box this lap for hard tires").
        criticality: Priority level 1 to 5. 5 is extremely critical (immediate pit stop required).
    """
    logger.info(f"Tool called! Sending insight to Race Engineer: {recommendation} (Criticality: {criticality})")
    try:
        response = httpx.post(API_URL, json={
            "summary": summary,
            "recommendation": recommendation,
            "criticality": criticality
        })
        response.raise_for_status()
        return "Successfully sent to Race Engineer."
    except Exception as e:
        logger.error(f"Failed to push to Race Engineer webhook: {e}")
        return f"Error sending insight: {e}"

def run_agent_loop():
    logger.info("Starting OpenCode Analyst Agent Workspace Server...")
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else None
    
    while True:
        try:
            broadcast_status("Reading workspace markdown files...")
            workspace_context = read_workspace_files()
            system_instruction = (
                "You are an OpenCode Agent acting as a backend Strategy Analyst for an F1 team. "
                "You sit in a remote garage reading historical workspace files and live database queries. "
                "Your job is to cross-reference the live telemetry with your workspace learnings. "
                f"Here is your Workspace Knowledge:\n{workspace_context}\n\n"
                "If you see a situation that warrants action (e.g., tire wear crossing a critical threshold "
                "mentioned in past_learnings.md), you MUST use the `send_insight_to_race_engineer` tool "
                "to alert the Race Engineer. If everything is fine, just say 'No action needed'."
            )

            broadcast_status("Querying historical telemetry database (DuckDB)...")
            telemetry_data = query_telemetry()
            broadcast_status("Analyzing data context using Gemini 2.5 Flash...")
            
            prompt = f"Live Database Query Results:\n{telemetry_data}\n\nDo we need to send an insight?"
            
            # Using function calling (tools)
            if client:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                        tools=[send_insight_to_race_engineer]
                    )
                )
                
                # Check for function calls
                if hasattr(response, 'function_calls') and response.function_calls:
                    for function_call in response.function_calls:
                        if function_call.name == "send_insight_to_race_engineer":
                            args = function_call.args
                            if args:
                                broadcast_status("CRITICAL: Executing 'send_insight_to_race_engineer' tool.")
                                # Execute the local function
                                result = send_insight_to_race_engineer(
                                    summary=args.get("summary", ""),
                                    recommendation=args.get("recommendation", ""),
                                    criticality=int(args.get("criticality", 3))
                                )
                else:
                    if response.text:
                        broadcast_status(f"Analysis Complete: {response.text.strip()}")
            else:
                broadcast_status("No API key, running MOCK Tool Call...")
                send_insight_to_race_engineer(
                    summary="Rear tire wear is high due to aggressive driving",
                    recommendation="Tell Tushar to chill on exits or box next lap.",
                    criticality=4
                )
                
        except Exception as e:
            logger.error(f"Agent loop error: {e}")
            
        # Poll every 15 seconds
        broadcast_status("Sleeping for 15 seconds before next analysis loop.")
        time.sleep(15)

if __name__ == "__main__":
    run_agent_loop()
