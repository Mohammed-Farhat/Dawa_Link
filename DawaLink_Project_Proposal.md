# DawaLink: An Agentic System for Redistributing Near-Expiry Medicines to Patients in Need

Agentic Systems (503P / 798S) · Dr. Ammar Mohanna · Fall 2026 · Project Proposal · Path A: Application-Oriented

## Team Members

- Mohammed Farhat
- Mohamad Natafgi
- Anthony John Kanaan

## 1. Problem

Pharmacies regularly hold medicines that approach their expiry date before they are sold. Unless they are returned to the distributor in time, these items are discarded, wasting medicine that is still usable. At the same time, many patients in Lebanon cannot afford their medicines and need them by a specific date. Today the two sides meet only informally, through phone calls, WhatsApp groups and word of mouth: near-expiry stock is invisible to the people who need it, and there is no transparent way to decide who receives limited stock first.

**Core question:** How can near-expiry medicine reach the patients who need it, by the date they need it, before it is wasted?

**Target users:** verified pharmacies (supply), patients in need (demand), and pharmacists or admins who review flagged cases.

## 2. Proposed Approach

A non-profit platform in which verified pharmacies list medicines nearing expiry, and patients submit a request (medicine, prescription, date needed). The system is built in layers; the LLM is only one of them:

- **Verification:** only real pharmacies join (license and identity checks, admin approval, trust score); duplicate and fake accounts are flagged.
- **Shared inventory:** medicine, batch, quantity, and expiry date across all pharmacies.
- **Matching and prioritization:** requests are ranked by the date the patient needs the medicine, then matched to the nearest pharmacy, using the soonest-expiring stock first. Rules are transparent and no clinical triage is done by the AI.
- **Alternative medicines:** suggested from a structured reference (same active ingredient, strength, and form) and always presented as suggestions for a pharmacist or the patient to confirm.
- **Agent:** contacts pharmacies to confirm availability, tries the next pharmacy if stock is gone or there is no reply, proposes a valid alternative, and escalates to a human when it cannot resolve the request. It acts only through limited tools.
- **Output and human layer:** the patient receives the pharmacy's location; delivery is an optional extension. A pharmacist or admin reviews flagged cases and approves sensitive ones.
