"""Suite E8, scenarios (docs/08): whole situations between a client, DawaLink's agent,
pharmacies and an admin, played through the API in three languages.

Each scenario is a small Python function that drives a `Stage` (`stage.py`): the client
writes and taps, a pharmacy marks a box, an admin replies, the clock moves. What the agent
did is then checked from the tables and the traces, at the four levels of the course's
evaluation chapter (component, step, trajectory, end to end), and a second model judges
what code can't check (`judge.py`).

Run it with `python -m dawalink.evals.scenarios.run`. It costs money.
"""
