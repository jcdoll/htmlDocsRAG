"""Tests for reciprocal rank fusion."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import reciprocal_rank_fusion


class TestReciprocalRankFusion:
    """Tests for RRF score combination."""

    def test_single_list(self):
        results = [
            [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)],
        ]
        fused = reciprocal_rank_fusion(results, k=60)

        # Order should be preserved
        assert fused[0][0] == "doc1"
        assert fused[1][0] == "doc2"
        assert fused[2][0] == "doc3"

    def test_two_lists_agreement(self):
        # Both lists agree on ranking
        results = [
            [("doc1", 0.9), ("doc2", 0.8)],
            [("doc1", 0.95), ("doc2", 0.85)],
        ]
        fused = reciprocal_rank_fusion(results, k=60)

        # doc1 should still be first (appears first in both)
        assert fused[0][0] == "doc1"
        # Score should be higher than single-list score
        assert fused[0][1] > 1 / 61  # More than single contribution

    def test_two_lists_disagreement(self):
        # Lists disagree on ranking
        results = [
            [("doc1", 0.9), ("doc2", 0.8)],
            [("doc2", 0.95), ("doc1", 0.85)],
        ]
        fused = reciprocal_rank_fusion(results, k=60)

        # Both should have similar scores (each is #1 in one list, #2 in other)
        scores = {doc: score for doc, score in fused}
        assert abs(scores["doc1"] - scores["doc2"]) < 0.01

    def test_non_overlapping_lists(self):
        results = [
            [("doc1", 0.9), ("doc2", 0.8)],
            [("doc3", 0.95), ("doc4", 0.85)],
        ]
        fused = reciprocal_rank_fusion(results, k=60)

        # All four docs should appear
        doc_ids = [doc for doc, _ in fused]
        assert set(doc_ids) == {"doc1", "doc2", "doc3", "doc4"}

        # First-ranked docs from each list should tie
        assert fused[0][1] == fused[1][1]

    def test_partial_overlap(self):
        results = [
            [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)],
            [("doc2", 0.95), ("doc4", 0.85)],
        ]
        fused = reciprocal_rank_fusion(results, k=60)

        # doc2 appears in both lists, should rank higher than docs in only one
        scores = {doc: score for doc, score in fused}
        assert scores["doc2"] > scores["doc1"]
        assert scores["doc2"] > scores["doc4"]

    def test_empty_lists(self):
        results = [[], []]
        fused = reciprocal_rank_fusion(results, k=60)
        assert fused == []

    def test_single_empty_list(self):
        results = [
            [("doc1", 0.9)],
            [],
        ]
        fused = reciprocal_rank_fusion(results, k=60)
        assert len(fused) == 1
        assert fused[0][0] == "doc1"

    def test_k_parameter_effect(self):
        results = [
            [("doc1", 0.9), ("doc2", 0.8)],
        ]

        # Smaller k means higher scores
        fused_small_k = reciprocal_rank_fusion(results, k=1)
        fused_large_k = reciprocal_rank_fusion(results, k=100)

        assert fused_small_k[0][1] > fused_large_k[0][1]

    def test_many_lists(self):
        results = [
            [("doc1", 0.9), ("doc2", 0.8)],
            [("doc1", 0.9), ("doc3", 0.8)],
            [("doc1", 0.9), ("doc4", 0.8)],
        ]
        fused = reciprocal_rank_fusion(results, k=60)

        # doc1 appears first in all three lists
        assert fused[0][0] == "doc1"
        # Its score should be 3x the single-list contribution
        expected_score = 3 * (1 / 61)
        assert abs(fused[0][1] - expected_score) < 0.001
