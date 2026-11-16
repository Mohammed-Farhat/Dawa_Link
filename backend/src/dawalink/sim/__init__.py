"""The simulated world and day (docs/08 §2.3, §2.4): pharmacies, clients, stock and
requests generated from a seed, played on a simulated clock through the real services.

It always runs on a database of its own (`dawalink_sim_...`), never on the app's, and it
calls no paid model and no outside service unless a run is asked to.
"""
