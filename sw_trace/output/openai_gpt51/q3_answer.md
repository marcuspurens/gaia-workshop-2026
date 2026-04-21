# Q3

## Question
Starting from the Stakeholder Requirement "Unauthorized start detection", which Function Requirements appear in the local downstream trace tree, and which Design Requirements appear one level further downstream?

## Answer
Downstream of the Stakeholder Requirement "Unauthorized start detection", the trace tree shows three Function Requirements and three Design Requirements, all connected via SP0003/SP0006 through intermediate Req Trace Items.

Function Requirements (directly downstream of the stakeholder requirement via Req Trace Item):
1) – Function Requirement "Diagnostic communication manager"
 • Trace chain to root (using only SP0003/SP0006):
 - → (SP0003)
 - → (SP0006)

2) – Function Requirement "Authentication time"
 • Trace chain to root:
 - → (SP0003)
 - → (SP0006)

3) – Function Requirement "Alarm for unauthorized entry"
 • Trace chain to root:
 - → (SP0003)
 - → (SP0006)

Design Requirements (one level further downstream from Function Requirements via Req Trace Items and):
4) – Design Requirement "Limit authentication time" (downstream of Function Requirement "Authentication time")
 • Trace chain to root:
 - → (SP0003)
 - → (SP0006)
 - → (SP0003)
 - → (SP0006)

5) – Design Requirement "Activate acoustic alarm" (downstream of Function Requirement "Alarm for unauthorized entry")
 • Trace chain to root:
 - → (SP0003)
 - → (SP0006)
 - → (SP0003)
 - → (SP0006)

6) – Design Requirement "Trigger alarm for unauthorized start" (also downstream of Function Requirement "Alarm for unauthorized entry")
 • Trace chain to root:
 - → (SP0003)
 - → (SP0006)
 - → (SP0003)
 - → (SP0006)

Within the local trace tree, these are all the Function Requirements and the next-level Design Requirements reachable from the Stakeholder Requirement using only the allowed SP0003/SP0006 relations. The evidence is consistent and fully rooted in the provided graph.

### Findings supported by the evidence
- **Diagnostic communication manager** — _Function Requirement_
  - This Function Requirement appears in the local downstream trace tree from the Stakeholder Requirement "Unauthorized start detection" via the intermediate Req Trace Item using allowed trace relations.
- **Authentication time** — _Function Requirement_
  - This Function Requirement is directly downstream of the Stakeholder Requirement through the Req Trace Item, forming a valid trace chain with SP0003 and SP0006 relations.
- **Alarm for unauthorized entry** — _Function Requirement_
  - This Function Requirement is shown as downstream of the Stakeholder Requirement via the Req Trace Item with an SP0006 relation, establishing its position in the local trace tree.
- **Limit authentication time** — _Design Requirement_
  - This Design Requirement is one level further downstream from the Function Requirement "Authentication time" via Req Trace Item, using only allowed SP0003 and SP0006 relations back to the Stakeholder Requirement.
- **Activate acoustic alarm** — _Design Requirement_
  - This Design Requirement is downstream of the Function Requirement "Alarm for unauthorized entry" via Req Trace Item, with an SP0006 relation, and the full chain to the Stakeholder Requirement uses only SP0003/SP0006.
- **Trigger alarm for unauthorized start** — _Design Requirement_
  - This Design Requirement is also one level further downstream from the Function Requirement "Alarm for unauthorized entry" via Req Trace Item, with a valid SP0006 link and a complete SP0003/SP0006 chain back to the Stakeholder Requirement.

**Confidence in the evidence:** strong

### Caveats
- The notion of "one level further downstream" is interpreted based on the provided graph hops and Req Trace Items; the packet does not explicitly define levels, but the design requirements at hop 4 are consistently connected via Req Trace Items at hop 3 from the function requirements at hop 2.

### Recommended human checks
- Confirm that the interpretation of levels (Function Requirements as the first downstream tier and Design Requirements at hop 4 as the next tier) matches project conventions.
- Verify in the full requirements repository that there are no additional Function or Design Requirements downstream of "Unauthorized start detection" that lie outside this local subgraph.
