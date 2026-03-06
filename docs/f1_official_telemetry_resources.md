# F1 Official Telemetry Resources

Last updated: March 6, 2026

## Primary Official References

- EA Forums, F1 25 game info hub (official UDP specification post):  
  https://forums.ea.com/blog/f1-games-game-info-hub-en/f1%C2%AE-25-udp-specification/12187347
- EA Forums discussion confirming the official F1 25 UDP specification location:  
  https://forums.ea.com/discussions/f1-25-general-discussion-en/re-f1-25-udp-specification/12212978
- EA help page for F1 controls and custom UDP actions (official control/telemetry settings surface):  
  https://www.ea.com/games/f1/f1-25/controls
- EA F1 25 gameplay deep dive (official game systems context for applying telemetry logic):  
  https://www.ea.com/games/f1/f1-25/news/f1-25-deep-dive-gameplay-features

## Packet Coverage Target

The agent and parser stack should support packet IDs `0..15`:

1. `0` motion
2. `1` session
3. `2` lap_data
4. `3` event
5. `4` participants
6. `5` car_setup
7. `6` car_telemetry
8. `7` car_status
9. `8` final_classification
10. `9` lobby_info
11. `10` car_damage
12. `11` session_history
13. `12` tyre_sets
14. `13` motion_ex
15. `14` time_trial
16. `15` lap_positions

## Implementation Notes

- Real parser support depends on the external `parser2025.py` ctypes schema being available.
- Mock parser should emit all packet families so agent logic can be validated without game runtime dependency.
- Agent tooling should expose both focused telemetry tools and a full snapshot tool for broad, multi-domain queries.
