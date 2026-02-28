import asyncio
import json
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from race_engineer.core.event_bus import bus
from race_engineer.intelligence.models import StrategyInsight
from race_engineer.telemetry.models import DriverQuery

logger = logging.getLogger(__name__)

app = FastAPI(title="Race Engineer Dashboard")

class StrategyPayload(BaseModel):
    summary: str
    recommendation: str
    criticality: int

class AgentStatusPayload(BaseModel):
    message: str

class DriverQueryPayload(BaseModel):
    query: str

@app.post("/api/strategy")
async def receive_strategy_from_agent(payload: StrategyPayload):
    """Webhook endpoint for external Analyst agents to push strategic insights."""
    insight = StrategyInsight(
        summary=payload.summary,
        recommendation=payload.recommendation,
        criticality=payload.criticality
    )
    logger.info(f"Received external strategy insight via webhook: {payload.summary}")
    await bus.publish("strategy_insight", insight)
    return {"status": "success"}

@app.post("/api/agent_status")
async def receive_agent_status(payload: AgentStatusPayload):
    """Webhook for external Analyst agents to report what they are doing."""
    await bus.publish("agent_status", {"message": payload.message})
    return {"status": "success"}

@app.post("/api/driver_query")
async def receive_manual_driver_query(payload: DriverQueryPayload):
    """Endpoint to simulate the driver speaking via a UI button."""
    query = DriverQuery(query=payload.query, confidence=1.0)
    await bus.publish("driver_query", query)
    return {"status": "success"}

html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Race Engineer | Pit Wall</title>
    <style>
        :root {
            --bg-color: #0d1117;
            --panel-bg: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --accent: #58a6ff;
            --success: #2ea043;
            --warning: #d29922;
            --danger: #f85149;
        }
        * { box-sizing: border-box; }
        body { 
            background-color: var(--bg-color); color: var(--text); 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; 
            margin: 0; padding: 20px; height: 100vh; display: flex; flex-direction: column;
        }
        h1 { color: #fff; margin-top: 0; font-size: 24px; border-bottom: 1px solid var(--border); padding-bottom: 10px; }
        h2 { font-size: 16px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; margin-top: 0; }
        
        .dashboard { 
            display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; flex-grow: 1; overflow: hidden;
        }
        .panel { 
            background: var(--panel-bg); border: 1px solid var(--border); border-radius: 8px; 
            padding: 20px; display: flex; flex-direction: column;
        }
        
        /* Telemetry Panel */
        .telemetry-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .data-box { background: #000; padding: 15px; border-radius: 6px; text-align: center; border: 1px solid #222; }
        .data-label { color: #8b949e; font-size: 12px; text-transform: uppercase; }
        .data-value { font-size: 32px; font-weight: bold; color: #fff; margin-top: 5px; font-variant-numeric: tabular-nums; }
        
        .bar-container { background: #222; height: 10px; border-radius: 5px; margin-top: 8px; overflow: hidden; }
        .bar-fill { height: 100%; width: 0%; transition: width 0.1s linear; }
        .bg-throttle { background-color: var(--success); }
        .bg-brake { background-color: var(--danger); }
        .bg-rpm { background-color: var(--accent); }
        
        /* Tires */
        .tire-container { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 20px; }
        .tire-box { background: #000; padding: 10px; border-radius: 6px; text-align: center; border: 1px solid #222; }
        .tire-val { font-size: 20px; font-weight: bold; margin-top: 5px; }
        .good { color: var(--success); }
        .warn { color: var(--warning); }
        .critical { color: var(--danger); }
        
        /* Lists/Logs */
        .log-list { list-style: none; padding: 0; margin: 0; flex-grow: 1; overflow-y: auto; font-family: monospace; font-size: 13px; }
        .log-item { padding: 8px; border-bottom: 1px solid #222; }
        .time { color: #8b949e; margin-right: 8px; }
        
        .encourage { color: var(--success); }
        .warn-log { color: var(--warning); }
        .strat-log { color: #bc8cff; }
        .info-log { color: var(--accent); }
        .agent-log { color: #a5d6ff; }
        
        /* Control Panel */
        .controls { margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--border); }
        input[type="text"] { 
            width: 100%; padding: 10px; background: #000; color: #fff; border: 1px solid var(--border); 
            border-radius: 6px; margin-bottom: 10px; font-size: 14px;
        }
        button { 
            width: 100%; padding: 10px; background: var(--border); color: #fff; border: none; 
            border-radius: 6px; cursor: pointer; font-weight: bold;
        }
        button:hover { background: #4b535d; }
    </style>
</head>
<body>
    <h1>Race Engineer | Team Pit Wall</h1>
    
    <div class="dashboard">
        <!-- Panel 1: Live Telemetry -->
        <div class="panel">
            <h2>Live Telemetry</h2>
            <div class="telemetry-grid">
                <div class="data-box">
                    <div class="data-label">Speed</div>
                    <div class="data-value" id="val-speed">0</div>
                    <div style="color: #888; font-size: 12px;">km/h</div>
                </div>
                <div class="data-box">
                    <div class="data-label">Gear</div>
                    <div class="data-value" id="val-gear">N</div>
                </div>
                <div class="data-box">
                    <div class="data-label">Lap</div>
                    <div class="data-value" id="val-lap">1</div>
                    <div style="color: #888; font-size: 12px;" id="val-sector">Sector 1</div>
                </div>
                <div class="data-box">
                    <div class="data-label">RPM</div>
                    <div class="data-value" id="val-rpm" style="font-size: 20px; margin-top:10px;">0</div>
                    <div class="bar-container"><div class="bar-fill bg-rpm" id="bar-rpm"></div></div>
                </div>
            </div>
            
            <div style="margin-top: 20px;">
                <div class="data-label">Throttle</div>
                <div class="bar-container"><div class="bar-fill bg-throttle" id="bar-throttle"></div></div>
            </div>
            <div style="margin-top: 10px;">
                <div class="data-label">Brake</div>
                <div class="bar-container"><div class="bar-fill bg-brake" id="bar-brake"></div></div>
            </div>
            
            <h2 style="margin-top: 30px;">Tire Wear</h2>
            <div class="tire-container">
                <div class="tire-box"><div class="data-label">Front Left</div><div class="tire-val" id="wear-fl">0%</div></div>
                <div class="tire-box"><div class="data-label">Front Right</div><div class="tire-val" id="wear-fr">0%</div></div>
                <div class="tire-box"><div class="data-label">Rear Left</div><div class="tire-val" id="wear-rl">0%</div></div>
                <div class="tire-box"><div class="data-label">Rear Right</div><div class="tire-val" id="wear-rr">0%</div></div>
            </div>
        </div>
        
        <!-- Panel 2: OpenCode Agent Log -->
        <div class="panel">
            <h2>Backend Analyst (OpenCode Agent)</h2>
            <ul class="log-list" id="agent-log">
                <li class="log-item"><span class="time">00:00:00</span> <span class="agent-log">Waiting for agent connection...</span></li>
            </ul>
        </div>
        
        <!-- Panel 3: Race Engineer Comms & Controls -->
        <div class="panel">
            <h2>Race Engineer Comms</h2>
            <ul class="log-list" id="insights">
                <li class="log-item"><span class="time">00:00:00</span> <span class="info-log">System Ready.</span></li>
            </ul>
            
            <div class="controls">
                <h2>Control Panel</h2>
                <input type="text" id="query-input" placeholder="Type a driver query (e.g. 'What is the strategy?')">
                <button onclick="sendQuery()">Simulate Driver Radio</button>
            </div>
        </div>
    </div>
    
    <script>
        // Formatter for logs
        function getTimestamp() {
            var now = new Date();
            return now.getHours().toString().padStart(2, '0') + ":" + 
                   now.getMinutes().toString().padStart(2, '0') + ":" + 
                   now.getSeconds().toString().padStart(2, '0');
        }

        function appendLog(listId, message, className) {
            var list = document.getElementById(listId);
            var li = document.createElement("li");
            li.className = "log-item";
            li.innerHTML = `<span class="time">${getTimestamp()}</span> <span class="${className}">${message}</span>`;
            list.prepend(li);
            if (list.children.length > 50) list.removeChild(list.lastChild);
        }

        function updateTireClass(element, value) {
            element.innerText = value.toFixed(1) + "%";
            element.className = "tire-val " + (value < 25 ? "good" : (value < 45 ? "warn" : "critical"));
        }

        // Send Query to API
        function sendQuery() {
            var input = document.getElementById("query-input");
            var text = input.value;
            if(!text) return;
            
            appendLog('insights', `[DRIVER] ${text}`, 'info-log');
            
            fetch('/api/driver_query', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({query: text})
            });
            input.value = '';
        }

        // WebSockets
        var ws = new WebSocket(`ws://${location.host}/ws`);
        
        ws.onmessage = function(event) {
            var msg = JSON.parse(event.data);
            
            if (msg.topic === "telemetry_tick") {
                var d = msg.payload;
                document.getElementById('val-speed').innerText = Math.round(d.speed);
                document.getElementById('val-gear').innerText = d.gear === 0 ? 'N' : (d.gear === -1 ? 'R' : d.gear);
                document.getElementById('val-lap').innerText = d.lap;
                document.getElementById('val-sector').innerText = "Sector " + d.sector;
                document.getElementById('val-rpm').innerText = Math.round(d.engine_rpm);
                
                document.getElementById('bar-throttle').style.width = (d.throttle * 100) + "%";
                document.getElementById('bar-brake').style.width = (d.brake * 100) + "%";
                document.getElementById('bar-rpm').style.width = Math.min((d.engine_rpm / 13000) * 100, 100) + "%";
                
                updateTireClass(document.getElementById('wear-fl'), d.tire_wear_fl);
                updateTireClass(document.getElementById('wear-fr'), d.tire_wear_fr);
                updateTireClass(document.getElementById('wear-rl'), d.tire_wear_rl);
                updateTireClass(document.getElementById('wear-rr'), d.tire_wear_rr);
                
            } else if (msg.topic === "driving_insight") {
                var d = msg.payload;
                var cls = "info-log";
                if(d.type === "warning") cls = "warn-log";
                if(d.type === "encouragement") cls = "encourage";
                if(d.type === "strategy") cls = "strat-log";
                
                appendLog('insights', `[ENGINEER] ${d.message}`, cls);
                
            } else if (msg.topic === "agent_status") {
                appendLog('agent-log', `> ${msg.payload.message}`, 'agent-log');
            }
        };
        
        ws.onclose = function() {
            appendLog('insights', 'Connection lost to Pit Wall Server.', 'warn-log');
        };
    </script>
</body>
</html>
"""

@app.get("/")
async def get_dashboard():
    return HTMLResponse(html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue()

    async def telemetry_handler(data):
        await queue.put({"topic": "telemetry_tick", "payload": data.model_dump()})

    async def insight_handler(data):
        await queue.put({"topic": "driving_insight", "payload": data.model_dump()})
        
    async def agent_status_handler(data):
        await queue.put({"topic": "agent_status", "payload": data})

    bus.subscribe("telemetry_tick", telemetry_handler)
    bus.subscribe("driving_insight", insight_handler)
    bus.subscribe("agent_status", agent_status_handler)

    try:
        while True:
            msg = await queue.get()
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Websocket error: {e}")
    finally:
        bus.unsubscribe("telemetry_tick", telemetry_handler)
        bus.unsubscribe("driving_insight", insight_handler)
        bus.unsubscribe("agent_status", agent_status_handler)
