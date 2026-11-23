"""Author development-only cases independently of model answers; exclusive output."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASES = []


def facts(qty=1, days=7, day=0, budget=None, walk=False, extra=False):
    value = {"intent": "find", "items": [{"match": {"name": "concor", "strength": "5mg"},
                                         "qty": qty}],
             "days_of_use": days, "pickup_in_days": day,
             "situation": ["no_car" if walk else "has_car"],
             "expected": "propose_plan" if extra else "propose_options"}
    if extra:
        value["items"].append({"match": {"name": "glucophage", "strength": "850mg"}, "qty": 1})
    if budget:
        value["budget"] = {"amount": budget, "currency": "USD"}
    if walk:
        value["preference"] = "walkable"
    return value


def add(lang, purpose, turns):
    CASES.append({"id": f"M-{len(CASES)+1:04d}", "lang": lang, "purpose": purpose,
                  "turns": [{"text": text, "gold": gold, "behavior": behavior}
                            for text, gold, behavior in turns], "author": "Codex reconciliation"})


add("english", "partial answers over four messages", [
    ("One box of Concor 5mg please.", facts(days=None, day=None), "clarify"),
    ("I have a car.", facts(days=None, day=None), "clarify"),
    ("Today.", facts(days=None), "clarify"),
    ("For seven days.", facts(), "propose"),
])
# Remove unspoken transport from the first cumulative label.
CASES[0]["turns"][0]["gold"]["situation"] = []
add("english", "quantity correction must replace earlier one-box facts", [
    ("Concor 5mg, one box, seven days, today. I drive.", facts(), "propose"),
    ("Correction: two boxes, not one.", facts(qty=2), "propose"),
])
add("arabizi", "budget reduction across turns", [
    ("concor 5mg 3elbe, la 7 iyyem, lyom, siyyara, budget 10 USD", facts(budget=10), "propose"),
    ("la2, l budget sar 5 USD maximum", facts(budget=5), "propose"),
])
add("arabic", "pickup day correction across turns", [
    ("بدي كونكور ٥ ملغ علبة لأسبوع، بكرا، معي سيارة", facts(day=1), "propose"),
    ("لا، بقدر اجي اليوم بدل بكرا", facts(day=0), "propose"),
])
add("mixed", "transport changed after an initial proposal", [
    ("Concor 5mg one box for 7 days today, معي سيارة", facts(), "propose"),
    ("السيارة تعطلت. Only walking now, keep it walkable.", facts(walk=True), "propose"),
])
add("english", "drop one medicine without keeping it in the final proposal", [
    ("Concor 5mg and Glucophage 850mg, one box each, 7 days, today, by car.",
     facts(extra=True), "propose"),
    ("Remove Glucophage. I only need Concor now.", facts(), "propose"),
])
add("english", "long conversation retains facts and applies final correction", [
    ("Concor 5mg one box for 7 days today. I drive. Maximum 10 USD.", facts(budget=10), "propose"),
    ("I will pay at the pharmacy, correct?", facts(budget=10), "reply"),
    ("Do I need to approve the proposal?", facts(budget=10), "reply"),
    ("Please keep the same medicine.", facts(budget=10), "reply"),
    ("I have not approved anything yet.", facts(budget=10), "reply"),
    ("Show the options again.", facts(budget=10), "propose"),
    ("Correction: tomorrow, two boxes, with the same 10 USD limit per box.",
     facts(qty=2, day=1, budget=10), "propose"),
    ("Now show the current proposal again.", facts(qty=2, day=1, budget=10), "propose"),
])
ambiguous = facts()
ambiguous["expected"] = "ask"
ambiguous["must_ask"] = ["quantity"]
add("english", "unresolved quantity conflict requires clarification", [
    ("Concor 5mg today for 7 days, by car. I need one box or two; I haven't decided.",
     ambiguous, "clarify"),
    ("Two boxes, final answer.", facts(qty=2), "propose"),
])
with (ROOT / "eval/datasets/multiturn.jsonl").open("x") as stream:
    for case in CASES:
        stream.write(json.dumps(case, ensure_ascii=False) + "\n")
print(f"Authored {len(CASES)} development conversations, {sum(len(c['turns']) for c in CASES)} turns")
