# Simulation analysis amendment before outcome observation

Recorded while candidate5 development validation is running, before any new paired
simulation has started. This supplements the protocol; source and active validation
harness pins remain unchanged.

The existing experiment marks a simulation incomplete when any turn fails or reaches
its cap, even when the engine finishes the whole day and records all100 requests.
Strict completed-pair estimates retain that definition. All incomplete attempts remain
visible separately, including their failures and costs.

A separately labeled secondary full-world analysis measures the product effect of
those failures. Eligibility requires100 unique request records, summary needs100,
normal return with no completion error, settled accounting, and the same world/events/
source checks as the strict analysis. Turn failures and caps remain counted; they do
not exclude an otherwise fully played world from this secondary analysis. Interrupted
worlds and missing/duplicate coverage are excluded from both paired estimates.

Report both eligibility flags and both analyses. Never describe the secondary analysis
as clean execution or combine its estimates with the strict completed-pair estimates.
One seed gives a paired difference only, without cross-world uncertainty. The existing
bootstrap interval is computed across paired seed differences only when multiple
eligible seeds exist; with at most five seeds its precision remains limited.

The engine's six-hour measure counts locked units, capped at each requested quantity.
It includes later no-shows and is not proof of dispensing. Fulfillment latency is
simulated minutes; recorded turn-span latency is a separate measure that omits untraced
overhead. Action-dependent event keys may be absent for another contender, but shared
external draw keys must agree.
