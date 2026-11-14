"""The guards around the model (docs/07 §7).

- `redact`: personal details are removed before a message is stored or sent to the model.
- `injection`: suspicious messages are flagged, never blocked.
- `clinical`: medical advice in a reply.
- `output`: every reply is checked before a client sees it.
"""
