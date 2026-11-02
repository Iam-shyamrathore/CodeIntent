# Code Intent: build plan

Planning baseline: 1 November 2026. Working product name: Code Intent.

This directory retains the original product, design and technical planning baseline. A deployable bounded public-workspace release now exists. Use the root [README](../README.md), [deployment guide](../docs/deployment.md), and [validation report](../docs/validation.md) for current setup and verified results. The feasibility report is historical; original targets are not blanket claims of completed hosted or human-reviewed evaluation.

## Decisions already made

- Web application, with a hosted public demonstration and a local development path.
- T1.1: explain the reasons behind code with inspectable historical evidence.
- Light silver and ink, with a restrained cobalt accent, selected by Shyam.
- Thorough completion and review take priority over a fixed delivery date.
- Vertex AI is the primary provider. After Shyam directed credential discovery to APCAN, its existing Vertex API-key configuration passed generation and embedding calls. The app references that local configuration without copying its key.
- Reuse open-source functionality extensively, with pinned versions and retained attribution.
- Plan before implementing the application.

## Read in this order

1. [Product, architecture, delivery gates, and acceptance criteria](./master-plan.md)
2. [Landing page, workbench, visual system, and interaction design](./design-brief.md)
3. [Open-source reuse decisions and inspected integration seams](./reuse-map.md)
4. [Real demonstration candidates and rehearsal plan](./demo-plan.md)

## Current deliverable

A portable web/API/worker application with durable public GitHub imports, scoped retrieval, source-backed decision history, saved reports, evidence inspection and deployment configuration. Local tests and container/provider/browser verification are documented in the validation report. Public deployment, domain configuration and environment secrets are left to Shyam as requested. Broader human semantic evaluation and untested managed database tiers remain explicitly unclaimed.

The previous in-chat mockup illustrates the concept only. Its fictional payment examples are not the demonstration dataset and its styling is not the final design.

## Design guidance attribution

The proposed design-review process incorporates [Unslop by Damir Sokolovsky](https://github.com/heydamir/unslop), licensed CC BY 4.0. Its [skill](https://github.com/heydamir/unslop/blob/1d13095e4bef6ad6c74f1dd828d84c4ba309a4dc/skills/unslop/SKILL.md) and token guidance were read for planning. It has not been installed globally or copied into the application.
