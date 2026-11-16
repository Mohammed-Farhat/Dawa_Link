"""The evaluation: datasets, scorers, runners, statistics and reports (docs/08).

Nothing here runs in the app. The suites drive the same services and the same agent as
the app does, on a database of their own, and write their results under `eval/results/`.
No suite calls a paid model unless it is asked to with `--model`.
"""
