# F1 Realism Research Notes

## Objective
Ground strategy behavior in real F1 race-wall practice while only enforcing constraints that are plausible in F1 25 gameplay.

## Sources Reviewed
- FIA Formula One Sporting Regulations index (latest 2026 issue listing):  
  https://www.fia.com/regulation/category/110
- FIA Formula One Sporting Regulations (Issue 4, 2025-12-10) PDF used for tyre-usage and VSC process references:  
  https://www.fia.com/sites/default/files/fia_2026_formula_1_sporting_regulations_-_issue_4_-_2025-12-10.pdf
- Formula1.com strategy guide (pit windows, one-stop vs two-stop patterns):  
  https://www.formula1.com/en/latest/article/strategy-101-how-do-formula-1-strategies-work-and-what-are-undercuts-and.4K2k4ybz9muM96LsNtj58R
- Formula1.com pit stop anatomy article (box-to-overtake, SC pit opportunities):  
  https://www.formula1.com/en/latest/article/the-anatomy-of-a-formula-1-pit-stop-how-do-the-teams-execute-a-2-second.7LFTfS8RddX6LjxWf6Z5bR
- Formula1.com glossary terms (pit window, undercut, overcut, VSC):  
  https://www.formula1.com/en/latest/article/how-well-do-you-know-your-formula-1-glossary.4fM4Nh4jgrfCJf0M2SzM58
- Formula1.com Monaco tyre-rule explainer (2025 change):  
  https://www.formula1.com/en/latest/article/explained-what-is-the-new-two-stop-rule-for-the-monaco-grand-prix-and-how.73QblvxNqQfK5Yv6f4LxDf
- EA SPORTS F1 25 patch notes v1.11 (Monaco two-stop enforcement fix):  
  https://www.ea.com/games/f1/f1-25/news/f1-25-patch-notes-v111
- EA SPORTS F1 25 patch notes v1.03 (engineer comms quality around SC/VSC):  
  https://www.ea.com/it-it/games/f1/f1-25/news/f1-25-patch-notes-v103

## Applicability Matrix (Real F1 -> F1 25)
- Tyre compound obligations in dry races: apply as a high-confidence strategy constraint.
- Monaco multi-stop constraint: apply explicitly (confirmed by official F1 25 patch notes).
- SC/VSC tactical behavior: apply, but keep as guidance signals (pit opportunity and no overtake calls), not hard simulation rules.
- Fine-grained FIA procedural timing details (e.g., exact race-control timing windows): treat as advisory only unless game telemetry exposes matching signals.

## Refactor Outcomes
- Added a dedicated `regulations` desk node to guard tyre-compliance risks.
- Added a `strategy_wall` desk node for undercut/overcut and neutralized-race pit opportunities.
- Added track-aware strategy profiles so tactics adapt across multiple tracks, not Monaco only.
- Added SC/VSC guardrails to suppress unrealistic overtake calls during neutralized phases.
