# Highlight Learning Engine

Phase 7.0D.4 personalizes highlight ranking using the creator's own decisions
and published results.

## Feedback sources

- creator approval or rejection
- editor approval
- published views
- retention
- engagement
- subscribers gained
- revenue

## Features

The first model learns from:

- original highlight score
- confidence
- recommended output format
- highlight categories

## Training

The engine uses a small regularized logistic model implemented locally in
Python. It does not require a cloud AI service.

Training updates transparent feature weights and records:

- sample count
- loss before training
- loss after training
- improvement
- model version

## Personalized score

The personalized result blends:

- original heuristic highlight score
- learned audience-fit probability

Every result stores the feature contributions used to produce the adjustment.

## Cold-start behavior

With little or no feedback, original highlight scores remain dominant. Model
confidence grows gradually as reviewed and published examples accumulate.

This phase does not claim accurate performance prediction from only a few
examples. Personalized ranking becomes more useful after repeated review and
publication cycles.
