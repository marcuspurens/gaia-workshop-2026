# sw_trace self-eval — natural-language answers

_These are the reviewer-facing prose renderings of the four self-eval answers. Ids, citation triples, and grounding metrics are omitted on purpose; they live in the JSON sidecars under `logs/self_eval/`. The prose uses the post-demote effective answer when available, falling back to the raw hand-authored response._

# Q1

## Question
Which function and design requirements will get affected if the legal requirement "UNECE Regulation No.155" gets removed?

## Answer
Removing the Legal Requirement 'UNECE Regulation No.155' directly breaks the Req Trace Item chain to one Function Requirement and two Design Requirements: FR 'Engine start/stop' traced from UNECE via the RTI 'UNECE Regulation No.155' (SP0003 to UNECE, SP0006 to the FR); and two DRs one step further via the RTI 'Engine start/stop' — 'Key authentication before engine start' and 'Engine stop on key removal'. No Function Requirement is affected at the 'function requirements' level beyond Engine start/stop under the requirement_trace whitelist, because all other FRs in the packet derive from a Stakeholder Req (not from UNECE directly).

### Findings supported by the evidence
- **Engine start/stop** — _Function Requirement_
  - Function Requirement directly derived from UNECE via the Req Trace Item 'UNECE Regulation No.155'. The RTI's SP0003 edge identifies UNECE as the source and SP0006 identifies this FR as the target — so removing UNECE breaks this derivation.
- **Key authentication before engine start** — _Design Requirement_
  - Design Requirement derived from FR 'Engine start/stop' via the Req Trace Item 'Engine start/stop': SP0003 to the FR (source) and SP0006 to this DR (target). Because the FR itself is derived from UNECE, removing UNECE cascades to this DR.
- **Engine stop on key removal** — _Design Requirement_
  - Design Requirement derived from FR 'Engine start/stop' via the Req Trace Item 'Engine start/stop': SP0003 to the FR (source) and SP0006 to this DR (target). Same cascade as 'Key authentication before engine start'.

**Confidence in the evidence:** strong

### Caveats
- The packet also contains FR 'Engine start time', FR 'Compliance for anti theft system', DR 'Ensure timely engine start', and DR 'Apply engine start timeout'. These are reachable through RTI 'Anti theft system', whose SP0003 edge identifies SR 'Anti theft system' as source — not UNECE. They are therefore *siblings* of FR Engine start/stop under a shared stakeholder parent, not direct descendants of UNECE. They are excluded from graph_proven_items because removing UNECE does not sever their requirement-trace chain (the SR 'Anti theft system' remains). The extractor reaches them because graph reachability is undirected across the whitelist, not because they are semantically impacted.
- The RTI 'Compliance' has an SP0006 edge to UNECE but no downstream SP0006 leading to an FR/DR in the packet — so it contributes no claimed item.
- The planner inferred target_item_types = ['Design Requirement'] only, despite the question explicitly asking about 'function and design requirements'. I included FR 'Engine start/stop' in graph_proven_items anyway because (a) it appears in the packet with a valid chain to root and (b) the question explicitly asks for FRs. This is a planner-side quirk that does not change the answer.

### Recommended human checks
- Confirm the SP0003-direction semantic interpretation above: in SystemWeaver, an RTI's SP0003 edge identifies the single upstream source; items reached by traversing another RTI's SP0006 edges 'sideways' are siblings, not descendants. If a human reviewer wants the broader reading (sibling-reachability treated as impact), Q1 should be rephrased to ask explicitly about graph-structural relatedness rather than impact-via-removal.
- Verify the exported graph has UNECE R155's full RTI chain captured — only one RTI was found as the direct SP0003 source for UNECE; if additional RTIs are expected, this is a data-completeness issue.

---

# Q2

## Question
Does the requirement "Keyless entry" (x0400000000038EAE) have any test cases?

## Answer
Yes. The Function Requirement 'Keyless entry' has five test cases. One test case is linked directly via ITRQ (Keyless entry Test Case), and four more are linked through the Test Specification 'Key mangement', which itself traces to the requirement via ITTR and contains the four Test Cases via ITEC.

### Findings supported by the evidence
- **Keyless entry Test Case** — _Test Case_
  - Test Case linked directly to the Keyless entry Function Requirement via an ITRQ edge — a test-to-requirement trace.
- **Key encryption and decryption Test Case** — _Test Case_
  - Test Case contained by the Test Specification 'Key mangement' (via ITEC); that same Test Specification traces to the Keyless entry requirement via ITTR.
- **Key managment Test Case** — _Test Case_
  - Test Case contained by the Test Specification 'Key mangement' (via ITEC); that Test Specification traces to the Keyless entry requirement via ITTR.
- **Authentication Test Case** — _Test Case_
  - Test Case contained by the Test Specification 'Key mangement' (via ITEC); that Test Specification traces to the Keyless entry requirement via ITTR.
- **Compliance for key management Test Case** — _Test Case_
  - Test Case contained by the Test Specification 'Key mangement' (via ITEC); that Test Specification traces to the Keyless entry requirement via ITTR.

**Confidence in the evidence:** strong

### Caveats
- The Test Specification node is named 'Key mangement' (typo in source); this is a data-side quirk, not a semantic concern.
- All five test cases are at status 'Work' — not yet released — which may matter for readiness but does not affect the existence of the trace.

### Recommended human checks
- Confirm the typo in the Test Specification name 'Key mangement' in SystemWeaver source data.
- Verify that the four test cases linked via the Test Specification are the intended coverage set for the Keyless entry requirement (i.e. no additional test cases are expected but missing).

---

# Q3

## Question
Starting from the Stakeholder Requirement "Unauthorized start detection", which Function Requirements appear in the local downstream trace tree, and which Design Requirements appear one level further downstream?

## Answer
Starting from the Stakeholder Requirement 'Unauthorized start detection', three Function Requirements appear in the local downstream trace tree — 'Diagnostic communication manager', 'Authentication time', and 'Alarm for unauthorized entry' — all linked via the Req Trace Item 'Unauthorized start detection' using SP0003 upward to the SR and SP0006 downward to each FR. One level further downstream, three Design Requirements are reached: 'Limit authentication time' from FR 'Authentication time' via RTI; 'Trigger alarm for unauthorized start' and 'Activate acoustic alarm' from FR 'Alarm for unauthorized entry' via RTI. FR 'Diagnostic communication manager' does not have a Design Requirement reached in this packet under the chosen whitelists.

### Findings supported by the evidence
- **Diagnostic communication manager** — _Function Requirement_
  - Function Requirement traced from SR 'Unauthorized start detection' via the Req Trace Item 'Unauthorized start detection': SP0003 to the SR (root) and SP0006 down to this FR.
- **Authentication time** — _Function Requirement_
  - Function Requirement traced from SR 'Unauthorized start detection' via the Req Trace Item 'Unauthorized start detection': SP0003 to the SR (root) and SP0006 down to this FR.
- **Alarm for unauthorized entry** — _Function Requirement_
  - Function Requirement traced from SR 'Unauthorized start detection' via the Req Trace Item 'Unauthorized start detection': SP0003 to the SR (root) and SP0006 down to this FR.
- **Limit authentication time** — _Design Requirement_
  - Design Requirement one level further downstream from FR 'Authentication time'. Req Trace Item 'Authentication time' links SP0003 to the FR and SP0006 to this DR; the FR itself traces to SR root via RTI. Description mentions 'authentication takes longer than specified N threshold' — semantically consistent.
- **Trigger alarm for unauthorized start** — _Design Requirement_
  - Design Requirement one level further downstream from FR 'Alarm for unauthorized entry'. Req Trace Item 'Alarm for unauthorized entry' links SP0003 to the FR and SP0006 to this DR; the FR traces to SR root via RTI.
- **Activate acoustic alarm** — _Design Requirement_
  - Design Requirement one level further downstream from FR 'Alarm for unauthorized entry'. Req Trace Item 'Alarm for unauthorized entry' links SP0003 to the FR and SP0006 to this DR; the FR traces to SR root via RTI.

**Confidence in the evidence:** strong

### Caveats
- The FR 'Diagnostic communication manager' has no Design Requirement reached in this packet under the chosen whitelist — meaning at the time of extraction no DR was traced below it. If such a DR exists in SystemWeaver, either it is not yet in the exported graph or requires a different relation whitelist to be reached.
- The planner also targeted 'Functional safety requirement' in addition to FR and DR; none were reached from this root under the chosen whitelist, as reflected in the 'target_item_types_not_reached' warning.
- The packet contains duplicate-name variants for 'Unauthorized start detection', 'Authentication time', and 'Alarm for unauthorized entry' across Stakeholder Req, Req Trace Item, and Function Requirement types; the citations above use exact ids so the duplication is a data-side quirk only.

### Recommended human checks
- Confirm whether the FR 'Diagnostic communication manager' is expected to derive any Design Requirement; if yes, inspect why the trace does not appear in the exported graph.
- Confirm that the three downstream Design Requirements (Limit authentication time, Trigger alarm for unauthorized start, Activate acoustic alarm) are the intended one-hop-further coverage set.

---

# Q4

## Question
If the Function Requirement "Engine start time" is tightened (smaller N), which Design Requirements are impacted downstream? Optionally: Which of them mention timing or timeout explicitly?

## Answer
Two Design Requirements are impacted downstream of the Function Requirement 'Engine start time': 'Ensure timely engine start' and 'Apply engine start timeout'. Both trace to the FR via the Req Trace Item 'Engine start time' (, SP0003 upward to the FR, SP0006 downward to each DR). Both Design Requirements explicitly mention timing or timeout in their descriptions: 'within N time' and 'predefined timeout' respectively.

### Findings supported by the evidence
- **Ensure timely engine start** — _Design Requirement_
  - Design Requirement traced from the Engine start time Function Requirement via the Req Trace Item 'Engine start time' (SP0003 to the FR, SP0006 to this DR). Description states 'ImbobMgr send engine start signal to ECM within N time' — explicitly timing-related, so a change in N directly impacts this DR.
- **Apply engine start timeout** — _Design Requirement_
  - Design Requirement traced from the Engine start time Function Requirement via the Req Trace Item 'Engine start time' (SP0003 to the FR, SP0006 to this DR). Description states 'If authentication process exceeds predefined timeout, then ImobMgr send an engine start block signal to ECM' — explicitly timeout-related, so a tightened N that reduces headroom directly impacts this DR.

**Confidence in the evidence:** strong

### Caveats
- The packet contains a Design Requirement Group 'Engine start time' linked to both DRs via SP0129 (Design Requirement Group -> Design Requirement). This is structural containment, not an additional trace path, so it is not included in graph_proven_items.
- The planner targeted 'Functional safety requirement' in addition to Design Requirement; none were reached from this root under the chosen whitelists, as reflected in the 'target_item_types_not_reached' warning. If safety-level analysis is expected, the question needs rewording or the graph needs a safety-level trace.

### Recommended human checks
- Confirm the numeric value of 'N time' in the DR 'Ensure timely engine start' matches the intended engine start time on the FR.
- Confirm the 'predefined timeout' in DR 'Apply engine start timeout' is consistent with the FR's 'predefined time limit'.
- If any Functional Safety Requirement derives from this FR, check whether the graph is missing a safety-level trace edge.

---
