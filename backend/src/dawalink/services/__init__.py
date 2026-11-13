"""The use cases: what a tap, a pharmacy's click, an agent tool or the clock check does.

The API and the agent's tools call the same functions here, so a tap and a tool can never
disagree (docs/06 §8). A service never commits: its caller owns the transaction.
"""
