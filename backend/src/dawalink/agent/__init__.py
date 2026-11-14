"""The agent: one graph, two modes (docs/07, ADR-001, ADR-002).

- `turn.py` runs one turn: lease, load, think and call tools, check, save.
- `tools/` is everything the model can do. No tool reserves, accepts, cancels, or changes
  stock, prices or priority (INV-11).
- `guards/` removes personal details on the way in and checks every reply on the way out.
- `llm/` is the model behind one small interface: scripted in tests, local in development,
  Claude for the evaluation and the demo.
"""
