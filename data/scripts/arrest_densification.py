'''
Every agency-month should be one of four states (not five — "reported" isn't
a separate state, it's the parent of the first two):

1. reported, zero arrests: agency submitted NIBRS data for that month,
   genuinely made zero custodial arrests
2. reported, N arrests: agency submitted NIBRS data, N custodial arrests recorded
3. did not submit: agency sent no NIBRS data that month - true non-participation
4. not applicable: before data_ori_went_nibrs (floor) or after agency_inactive_dt
   (ceiling, for the 30 flagged-inactive agencies)


Limitation:
The raw arrestee-level file only ever produces a row when an arrest actually
happened - there is no positive "submitted, zero arrests" signal anywhere in
this data. So for any agency-month with no row, states 1 and 3 are
indistinguishable from the data alone.

Our agency-level non-reporting work (30 inactive-flagged + 77 highest-
confidence candidates = 107 agencies) only resolves this ambiguity at the
WHOLE-WINDOW level - agencies with zero arrests across the entire 16-month
period. It does NOT resolve month-level gaps for the ~352 agencies that
report SOME months and are silent in others. For those agencies, every
individual missing month still carries the same state-1-vs-state-3
ambiguity, completely unresolved - this isn't limited to agencies that
"stopped" reporting at some point; it covers any gap pattern (a single
pause, scattered missing months, intermittent reporting).

Note: the 77 is a conservative subset of a larger ~217-agency whole-year-
zero pool. The rest were excluded either because a successor ORI explains
the gap (Camden-style consolidation) or because they're lower-confidence
(small population, or agency_indicator != City).
'''