# The simulated world

The fixed map that every simulation run plays on (plan: [`docs/08_evaluation.md`](../../docs/08_evaluation.md) §2.3).

| File | What | Made by |
|---|---|---|
| `world.json` | 30 pharmacies and 200 client points in 8 districts, with each pharmacy's opening hours and each client's hidden situation (car or not, free hours, language, preference) | `python -m dawalink.sim.geometry`, inside `backend/` |
| `travel.json` | Road travel times by car and on foot from every client point and every pharmacy to every pharmacy: 13,620 trips, fetched on 2026-11-14 | `python -m dawalink.sim.travel_table`, inside `backend/` (20 requests to OpenRouteService with the key of `.env`) |

- **Generated, not edited by hand.** Running the command again gives the same file; a test checks it.
- **Nobody real is here.** Every point is a town or neighbourhood of Lebanon moved by up to about 300 m. No pharmacy and no person exists at these points; the names are "Beirut Pharmacy 3" and "Sim Client 041".
- **The same map for every seed,** because road travel times are computed once. A run's seed decides the stock on each shelf, who asks for what and when, and how people behave.
- **No routing call in a run.** The simulation reads the times from `travel.json`, so a run is free and gives the same times every time.
- **Credit.** The places come from our list of areas, whose centres are © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, available under the Open Database License. The travel times were computed by [openrouteservice.org](https://openrouteservice.org) on OpenStreetMap's road data.
