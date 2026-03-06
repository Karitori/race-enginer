# EA Overlay Safety Notes

Date checked: March 6, 2026.

This project keeps the desktop overlay in a separate external process and limits integration to:
- reading race telemetry from the official UDP stream exposed by the game
- reading backend WebSocket/API data produced from that telemetry
- sending user-originated radio text/talk-level requests to the local backend

This companion app intentionally does **not**:
- inject code into the game process
- hook game memory
- automate gameplay inputs
- patch game files

That boundary is designed to stay aligned with EA anti-cheat and user agreement constraints around unauthorized interference/cheating behavior.

This is a technical safety boundary, not legal advice.
