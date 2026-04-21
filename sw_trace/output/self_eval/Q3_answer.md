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
