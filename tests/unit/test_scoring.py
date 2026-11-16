import numpy as np
import pytest

from backend.app.matching.embeddings import HashingEmbedder, cosine
from backend.app.matching.scoring import (
    ScoreInput,
    build_explanation,
    calibrate_cosine,
    compute_score,
    experience_fit,
    keyword_strength,
    normalise_weights,
    parse_experience_requirement,
    pick_excerpts,
    title_similarity,
)

W = {"skills": 0.3, "semantic": 0.3, "title": 0.15, "experience": 0.1, "keywords": 0.15}


def test_cosine_basics():
    a = np.array([1.0, 0.0])
    assert cosine(a, a) == pytest.approx(1.0)
    assert cosine(a, np.array([0.0, 1.0])) == pytest.approx(0.0)
    assert cosine(a, np.zeros(2)) == 0.0


def test_hashing_embedder_similar_text_scores_higher():
    e = HashingEmbedder()
    v = e.encode(["python backend api developer", "python api backend engineer", "pastry chef bakery"])
    assert cosine(v[0], v[1]) > cosine(v[0], v[2])
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0)


def test_calibration_clamps():
    assert calibrate_cosine(0.0, 0.1, 0.6) == 0.0
    assert calibrate_cosine(0.35, 0.1, 0.6) == pytest.approx(0.5)
    assert calibrate_cosine(0.9, 0.1, 0.6) == 1.0


def test_weights_normalise_and_reject_zero():
    n = normalise_weights({"a": 1, "b": 3})
    assert n == {"a": 0.25, "b": 0.75}
    with pytest.raises(ValueError):
        normalise_weights({"a": 0})


def test_experience_requirement_parsing():
    assert parse_experience_requirement("3-5 years of experience")[:2] == (3.0, 5.0)
    assert parse_experience_requirement("5+ years Python")[:2] == (5.0, None)
    assert parse_experience_requirement("minimum of 2 years")[:2] == (2.0, None)
    assert parse_experience_requirement("great team")[:2] == (None, None)


def test_experience_fit():
    assert experience_fit(4, 3, 5) == 1.0
    assert experience_fit(1, 4, None) == pytest.approx(0.25)
    assert experience_fit(None, 3, 5) is None
    assert experience_fit(20, 3, 5) == 0.5


def test_title_similarity_ignores_level_words():
    assert title_similarity("Senior Backend Engineer", ["Backend Engineer"]) == 1.0
    assert title_similarity("Pastry Chef", ["Backend Engineer"]) == 0.0
    assert title_similarity("x", []) is None


def test_keyword_strength_title_counts_more():
    assert keyword_strength(["A"], []) < keyword_strength(["A"], ["A"])
    assert keyword_strength(["A", "B", "C"], []) == 1.0


def test_matched_and_missing_skills_and_weighted_score():
    r = compute_score(
        ScoreInput(
            job_title="Python Engineer",
            job_skills=["Python", "AWS", "Kafka", "Docker"],
            matched_keywords=["Python"],
            title_keywords=["Python"],
            resume_skills=["python", "Docker"],
            resume_years=4,
            req_min_years=3,
            req_max_years=5,
            cosine=0.35,
            cosine_range=(0.1, 0.6),
            title_candidates=["Python Engineer"],
        ),
        W,
    )
    assert r.matched_skills == ["Python", "Docker"] and r.missing_skills == ["AWS", "Kafka"]
    assert r.components["skills"] == 0.5 and r.components["semantic"] == 0.5
    assert r.components["title"] == 1.0 and r.components["experience"] == 1.0
    expected = (0.5 * 0.3 + 0.5 * 0.3 + 1 * 0.15 + 1 * 0.1 + 0.5 * 0.15) * 100
    assert r.score == pytest.approx(round(expected, 1))
    assert 0 <= r.score <= 100


def test_without_resume_only_available_components_are_used():
    r = compute_score(
        ScoreInput(
            job_title="Python Dev",
            job_skills=["Python"],
            matched_keywords=["Python"],
            title_keywords=["Python"],
        ),
        W,
    )
    assert not r.resume_used and set(r.weights_used) == {"keywords"}
    assert r.score == pytest.approx(50.0)  # 1.5 points / 3


def test_changing_weights_changes_score():
    inp = ScoreInput(
        job_title="x",
        job_skills=["A", "B"],
        matched_keywords=["A"],
        title_keywords=[],
        resume_skills=["A"],
        cosine=0.6,
        cosine_range=(0.1, 0.6),
    )
    skills_heavy = compute_score(inp, {"skills": 1, "semantic": 0, "keywords": 0}).score
    kw_heavy = compute_score(inp, {"skills": 0, "semantic": 0, "keywords": 1}).score
    assert skills_heavy == 50.0 and kw_heavy == pytest.approx(33.3)


def test_excerpts_pick_sentences_with_terms():
    text = "Intro line here ok. We build services in Python every day. Unrelated closing sentence."
    ex = pick_excerpts(text, ["Python"])
    assert ex == ["We build services in Python every day."]


def test_explanation_mentions_not_a_probability_and_threshold_note():
    r = compute_score(ScoreInput(job_title="x", job_skills=[], matched_keywords=["A"], title_keywords=[]), W)
    text = build_explanation(r, ["A"], threshold=90)
    assert "not a hiring probability" in text and "Below your 90% AI threshold" in text
