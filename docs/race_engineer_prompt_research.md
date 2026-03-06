# Race Engineer Prompt Research Notes

## Goal
Upgrade the race engineer system prompt to behave more like a real F1 radio engineer while staying robust on local models.

## Sources Reviewed
- LangChain context engineering: https://docs.langchain.com/oss/python/langchain/context-engineering
- Anthropic prompt engineering guide: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview
- Aston Martin F1 race engineer role breakdown: https://www.astonmartinf1.com/en-GB/news/feature/what-does-a-race-engineer-do
- Mercedes AMG F1 engineer interview (Pete Bonnington): https://www.mercedesamgf1.com/news/revelations-with-pete-bonnington
- EA SPORTS F1 25 deep dive (handling and race dynamics context): https://www.ea.com/games/f1/f1-25/news/f1-25-deep-dive-gameplay-features

## Design Translation
- Use explicit sectioned prompt structure for reliability on smaller/local models.
- Put decision hierarchy before style to enforce race-critical triage.
- Add telemetry-first answering protocol for metric questions.
- Add strict output contract to prevent role-label and metadata echo.
- Keep personality/banter logic but gate it behind risk priority.
- Include F1 25 adaptation notes (ERS windows, tyre temps, dirty air, track evolution).

## Expected Behavior Impact
- Better direct answers for telemetry questions.
- Fewer support-assistant style responses.
- Less prompt-header echo and role-prefix artifacts.
- More realistic race-radio cadence under pressure.
