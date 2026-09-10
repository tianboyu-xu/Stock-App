import pytest

from src.services.allocation.fixed_score_policy import FixedScorePolicy
from src.services.allocation.tuned_fixed_policy import tune_fixed, mapping_candidates
from src.services.allocation.q_learning_policy import QConfig, QEntry, QLearningTrainer
from src.services.allocation.allocation_state import StateEncoder
from src.services.allocation.trigger_event import TriggerEvent
from src.services.allocation import PortfolioEnvironment


def test_invalid_mapping_rejected_and_candidates_always_valid():
    with pytest.raises(ValueError, match="monotonic"):
        FixedScorePolicy(strong_buy_target=.2)
    with pytest.raises(ValueError, match="grid"):
        FixedScorePolicy(strong_buy_target=1.2)
    for policy in mapping_candidates(FixedScorePolicy()):
        assert all(0 <= v <= 1 for v in policy.targets)
        assert policy.targets[0] >= policy.targets[1] >= policy.targets[2]
        assert policy.targets[3] >= policy.targets[4] >= policy.targets[5]


def test_tuner_searches_training_objective_with_valid_mapping():
    evaluated = []
    def objective(policy):
        evaluated.append(policy.targets)
        return policy.weak_buy_target + policy.medium_buy_target
    best, count = tune_fixed(objective)
    assert best.weak_buy_target == best.medium_buy_target == 1
    assert count == len(set(evaluated)) == len(evaluated)


def test_exact_q_update_and_masked_bootstrap():
    trainer = QLearningTrainer(FixedScorePolicy(), QConfig(alpha=.1, gamma=.95))
    trigger = TriggerEvent("d", "BUY", 7, 100, 100)
    state = StateEncoder().encode(trigger, PortfolioEnvironment(0).snapshot)
    trainer.table[(state, 0.0)] = QEntry(1000)
    trainer.table[(state, 1.0)] = QEntry(.2)
    trainer.update(state, .6, .1, state, (1.0,))
    assert trainer.table[(state, .6)].q_value == pytest.approx(.1 * (.1 + .95 * .2))


def test_seed_exploration_and_mask_are_deterministic():
    env = PortfolioEnvironment(0)
    env.rebalance(.8, 100)
    trigger = TriggerEvent("d", "BUY", 7, 100, 100)
    state = StateEncoder().encode(trigger, env.snapshot)
    trainers = [QLearningTrainer(FixedScorePolicy(), QConfig(epsilon_start=1)) for _ in range(2)]
    choices = [[t.choose(state, trigger, env.snapshot).target for _ in range(100)] for t in trainers]
    assert choices[0] == choices[1]
    assert set(choices[0]) == {.8, 1.0, None}


def test_frozen_policy_cannot_mutate_table_or_entries():
    trainer = QLearningTrainer(FixedScorePolicy())
    trigger = TriggerEvent("d", "BUY", 7, 100, 100)
    snapshot = PortfolioEnvironment(0).snapshot
    state = StateEncoder().encode(trigger, snapshot)
    trainer.update(state, 1.0, .1)
    frozen = trainer.freeze()
    before = frozen.explain()
    for _ in range(10):
        frozen.choose(state, trigger, snapshot)
    assert before == frozen.explain()
    assert not hasattr(frozen, "update")
    with pytest.raises(TypeError):
        frozen.table[(state, 1.0)] = QEntry(99)


def test_low_support_fallback_uses_distinct_dates_not_episode_repetitions():
    trainer = QLearningTrainer(FixedScorePolicy(), QConfig(minimum_visit_count=2))
    trigger = TriggerEvent("d", "BUY", 5, 100, 100)
    snapshot = PortfolioEnvironment(0).snapshot
    state = StateEncoder().encode(trigger, snapshot)
    for _ in range(100):
        trainer.update(state, 1.0, .1, source_date="2026-01-01")
    choice = trainer.freeze().choose(state, trigger, snapshot)
    assert choice.reason == "LOW_SAMPLE_FALLBACK" and choice.target == .8
    assert trainer.table[(state, 1.0)].visit_count == 1
    assert trainer.table[(state, 1.0)].update_count == 100
    trainer.update(state, 1.0, .1, source_date="2026-01-02")
    choice = trainer.freeze().choose(state, trigger, snapshot)
    assert choice.reason == "GREEDY_Q" and choice.target == 1
    rows = trainer.freeze().explain()
    assert len(rows) == 7  # Six targets and explicit HOLD, including unvisited entries.
    assert next(row for row in rows if row["recommended_at_bucket"])["target_exposure"] == 1
    assert all("visit_count" in row and "update_count" in row for row in rows)
