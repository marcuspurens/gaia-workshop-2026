# Workshop Quick-Start Guide

This guide gets you exploring the Immobilizer System Model with TReqs. Full CLI documentation is in `treqs_cli_reference.md`.

---

## 1. Install the TReqs CLI

The CLI is a standalone binary — no runtime or package manager needed. You can find binaries for Windows, Linux & Mac in the `treqs_cli_expire2026-04-22/` folder

**macOS / Linux**
```bash
chmod +x treqs-darwin-arm64      # replace with your downloaded filename
mv treqs-darwin-arm64 /usr/local/bin/treqs
```

**Windows**
1. Rename the file to `treqs.exe`.
2. Move it to a folder such as `C:\tools\`.
3. Add that folder to your PATH: **Start → "Environment Variables" → Path → New → enter the folder path → OK**.
4. Open a new terminal for the change to take effect.

**Verify**
```bash
treqs --version
```

---

## 2. Manual Exploration — Example Run

All commands must be run from this folder, where `ttim.yaml` lives.

**Browse a type to get an overview**
```bash
treqs list --type Hazard
```
Pick an element that looks interesting. For example:

```
x0400000000038EFA  Hazard  Immobilizer shuts down the engine while driving
```

**Trace downstream from that element**

Links are directed. `--outlinks` walks the links *declared on* the element — towards what it derives or specifies. `--inlinks` walks the reverse — finding elements that point *to* it.

```bash
treqs list --uid x0400000000038EFA --followlinks --outlinks
```

Result: the hazard links to its failure mode (`Generic_Failure_Mode: Omission`) and the safety requirement it produced (`Functional_safety_requirement: Prevention of unintended Engine shutdown`).

**Export as a Mermaid graph**

Add `-o mermaid` to any `--followlinks` command:
```bash
treqs list --uid x0400000000038EFA --followlinks --outlinks -o mermaid
```

Copy the output and paste it into **[mermaid.live](https://mermaid.live)** to render an interactive graph.

---

## 3. AI Assistance

### Without Claude Code

Add `CLAUDE.md` and `treqs_cli_reference.md` into any AI assistant (Claude, ChatGPT, etc.), and ask something like:

> *"Use these files to give me the commands I need to run to answer the following traceability question: does the requirement 'Keyless entry' have any test cases?"*

The AI will suggest the exact commands. You run them yourself and paste the output back if you want it to interpret the results.

### With Claude Code

This folder is already set up for Claude Code CLI — `CLAUDE.md` describes the model and workflow, and the `treqs` CLI is available on your PATH, so no additional configuration is needed. Launch Claude Code CLI in this folder and ask traceability questions directly — it will run the CLI commands, interpret the output, and report findings in one step. Example questions to try:

- *Does the requirement "Keyless entry" (`x0400000000038EAE`) have any test cases?*
- *Starting from "Unauthorized start detection", which Function Requirements are downstream, and which Design Requirements are one level further?*
- *If "Engine start time" is tightened, which Design Requirements are impacted? Which mention timing or timeout?*


## Other Element Types Intersting to Explore

Some other element types that might be interesting to explore:

| Type | What it represents |
|---|---|
| `Stakeholder_Req` | Top-level needs |
| `Legal_Requirement` | Regulatory drivers (FMVSS, ISO/SAE 21434) |
| `Function_Requirement` | What the system shall do |
| `Design_Requirement` | How it does it |
| `Req_Trace_Item` | Traceability bridges between levels — start `--followlinks` from here |
| `Test_Case` | Verification coverage |
| `Hazardous_Event` | Safety analysis scenarios |
| `Safety_Goal` | High-level safety objectives |
| `Hazard` | Root hazards identified in the HARA |
| `Functional_safety_requirement` | Safety requirements derived from hazard analysis |
| `Threat_Scenario` | Cybersecurity attack scenarios specific to this system |
| `Generic_Threat` | Reusable threat catalogue entries |
| `Attack_Method` | How a threat is carried out (technique-level) |
| `Attack_Vector` | Specific entry points exploited in an attack |
| `Damage_Scenario` | Concrete impact if a threat is realised |
| `Cybersecurity_Goal` | High-level security objectives |
| `Cybersecurity_Requirement` | Concrete security controls (SecOC, encryption, firmware update) |
| `Generic_Asset` | Protected assets catalogue (IMMO ECU, CAN Bus, Key Fob) |
| `Conceptual_System_Component` | System components and their interfaces — starting point for asset analysis |
| `Standard_Process_Requirement` | ISO/SAE 21434 process-level requirements |
