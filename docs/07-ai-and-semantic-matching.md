# 07 - AI and Semantic Matching

Code: `matching/embeddings.py`, `matching/scoring.py`, `services/matching_service.py`.

## Embeddings in one paragraph

An embedding model turns text into a list of numbers (a vector) so that texts with similar
meaning get similar vectors. `all-MiniLM-L6-v2` produces 384 numbers per text, runs on CPU,
and is about 90 MB. "Built REST services in Python" and "Backend API developer, Python" end
up close together even though they share few words.

## Cosine similarity

The angle between two vectors, ignoring their length:

```
cos(a, b) = (a . b) / (|a| |b|)      range -1..1, higher = more similar
```

Our embedders return unit-length vectors, so cosine is just a dot product. NumPy does it in
microseconds.

## The hybrid score

Embeddings alone miss concrete facts ("needs 8 years", "requires Kubernetes"), so the score
blends five components, each 0..1:

| Component | Meaning | Default weight |
|---|---|---|
| skills | share of the job's detected skills that are on your resume | 0.30 |
| semantic | calibrated cosine of your profile text vs the job text | 0.30 |
| title | Dice overlap between job title and your preferred/past titles | 0.15 |
| experience | fit of your years vs the job's "N years" requirement | 0.10 |
| keywords | how many of your keywords hit (title hits count 1.5x; 3 points = max) | 0.15 |

```
score = 100 * sum(weight_i * component_i) / sum(weights of available components)
```

If a component cannot be computed (no resume uploaded, no experience stated in the job), it
is dropped and the remaining weights are re-normalised, so missing data does not drag the
score down. Weights come from `.env` and can be overridden in Settings > Preferences.

### Calibration

Raw cosine values are not 0..1 percentages. MiniLM typically gives 0.1-0.6 for
resume-versus-job comparisons, so `calibrate_cosine` maps that range linearly onto 0..1.
The range is stored on each embedder (`calibration`). These ranges are reasonable starting
points, not measured constants; tune them if scores cluster too high or low for you.

### What the score is not

It is a ranking aid. It is not the probability of an interview or an offer, and the UI says so.

## Outputs per job

Stored in `job_matches`: `score`, `score_breakdown` (components, weights used, embedder,
raw cosine), `matched_skills`, `missing_skills`, `excerpts` (sentences containing matched
keywords/skills), `explanation` (plain-language summary). No LLM is involved.

## Caching

`EmbeddingCacheRepository` stores vectors keyed by `(sha256(text), model)` in the
`embedding_cache` table. A job whose text has not changed is never re-embedded. The hashing
fallback is cheap and is not cached.

## The fallback embedder

If the MiniLM model cannot be loaded (offline first run, blocked download), `build_embedder`
logs a warning and uses `HashingEmbedder` (hashed 1-2 word n-grams, scikit-learn). It works
with no download but only captures word overlap, not meaning. Force it with
`EMBEDDING_BACKEND=hashing`.

Honest note on testing: the automated tests exercise the hashing embedder and the scoring
maths. Loading the real MiniLM model needs a download that was not possible in the
environment where this project was built, so verify it once on your machine (see below).

## Verify the real model on your machine

```bash
python - <<'EOF'
from backend.app.matching.embeddings import SentenceTransformerEmbedder
e = SentenceTransformerEmbedder("sentence-transformers/all-MiniLM-L6-v2")
v = e.encode(["Python backend engineer", "Senior Python API developer", "Pastry chef"])
print(v.shape, (v[0] @ v[1]).round(2), (v[0] @ v[2]).round(2))
EOF
```

Expected: shape `(3, 384)`, the first similarity clearly higher than the second.

## Common errors

| Symptom | Fix |
|---|---|
| Warning "Falling back to the hashing embedder" | model download blocked; check network or HF cache |
| All scores look low/high | adjust `calibration` in `embeddings.py` or the weights |
| Out of memory | embeddings are batched (16); close other apps |

## Interview questions

- What is an embedding? Why cosine similarity rather than Euclidean distance?
- Why normalise vectors? What does calibration fix?
- Why combine semantic similarity with rule-based features?
- How would you evaluate whether the scores are any good? (Hint: label a set of jobs yourself.)
