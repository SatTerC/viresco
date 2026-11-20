# 2. Driven pipelines: state stays inside nodes

Status: accepted, November 2026.

## Context

A viresco pipeline is a DAG, and each node runs once, on whole time series.
Some models carry state through time (SPLASH's soil moisture, RothC's and SGAM's pools), and each integrates it inside its own node.
Land-surface models such as JULES instead couple components step by step, so that one component's state feeds another's next step; in a DAG that is a cycle.

## Decision

Viresco builds driven pipelines.

- **State may live inside a node.**
  A node may integrate a model through time, provided everything it consumes is available before it runs.
  A feedback is allowed within one node.
- **State does not cross a node boundary.**
  No node consumes, directly or through other nodes, anything computed from its own output.
- **Feedbacks between nodes are closed with observations.**
  Where a land-surface model would feed a modelled quantity back upstream, a pipeline takes an observed one instead: fAPAR and LAI from satellites, not from the vegetation model.
- **A calculation that needs a model's state belongs inside that model's node.**
  Anything that depends only on forcings is a separate node, so it can be swapped and reused.

## Consequences

- Splitting a model into nodes follows one rule: forcing-only calculations become nodes, and state-dependent ones stay with the state.
- Respiration schemes that need biomass derive it from observed LAI by allometry rather than from a model's pools.
- A modelled quantity whose feedback is closed with an observation is a diagnostic.
  Comparing it with the observation that drove it is not an independent test, because the two share that observation's errors.
  Calibrating it needs data that are not among the pipeline's forcings.
- Every stateful node can be run, tested, replaced and calibrated on its own, with its forcings fixed, provided its calibration data are not among its forcings, directly or upstream.
- Wrappers can call packages that run a whole time series at once without rewriting them as step functions.

## Not a goal for now

Prognostic coupling across nodes, which would need every model rewritten as a step function and a scheduler (such as Apache Burr or `jax.lax.scan`) to carry state between steps.
Revisit if a feedback cannot be closed with observations, or if a model's state must be calibrated against an observation that also drives the pipeline and no independent data exist.
