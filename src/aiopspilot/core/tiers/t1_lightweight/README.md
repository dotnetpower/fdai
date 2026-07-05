# `src/aiopspilot/core/tiers/t1_lightweight`

T1 tier. Uses pgvector similarity search against the pattern library and a small
classifier to reuse prior resolutions. Abstains when similarity is below threshold.
