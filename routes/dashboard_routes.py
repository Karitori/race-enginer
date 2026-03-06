from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from utils.files import read_text_file

router = APIRouter()
DASHBOARD_HTML = read_text_file(Path(__file__).with_name("web_dashboard.html"))


@router.get("/")
async def get_dashboard():
    return HTMLResponse(DASHBOARD_HTML)
