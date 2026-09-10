"""Tabular Q-learning only. Frozen inference has no update method or exploration."""

from dataclasses import dataclass
import math
import random
from types import MappingProxyType, SimpleNamespace

from .allocation_policy import PolicyDecision, get_valid_actions
from .allocation_state import TARGET_EXPOSURES


@dataclass(frozen=True)
class QConfig:
    alpha: float = .1
    gamma: float = .95
    epsilon_start: float = .30
    epsilon_end: float = .02
    epsilon_decay: float = .99
    episodes: int = 100
    random_seed: int = 42
    minimum_visit_count: int = 10

    def __post_init__(self):
        if not all(math.isfinite(x) and 0 <= x <= 1 for x in (
            self.alpha, self.gamma, self.epsilon_start, self.epsilon_end, self.epsilon_decay
        )) or self.alpha == 0 or self.epsilon_decay == 0:
            raise ValueError("invalid Q-learning rates")
        if self.epsilon_end > self.epsilon_start:
            raise ValueError("epsilon_end must not exceed epsilon_start")
        if type(self.episodes) is not int or not 1 <= self.episodes <= 2000:
            raise ValueError("episodes must be an integer in [1, 2000]")
        if type(self.minimum_visit_count) is not int or self.minimum_visit_count < 0:
            raise ValueError("minimum_visit_count must be a nonnegative integer")
        if type(self.random_seed) is not int:
            raise ValueError("random_seed must be an integer")


@dataclass(frozen=True)
class QEntry:
    q_value: float = 0.0
    visit_count: int = 0
    update_count: int = 0


def greedy_action(table, state, valid, preferred):
    best = max(table.get((state, action), QEntry()).q_value for action in valid)
    ties = [action for action in valid if abs(table.get((state, action), QEntry()).q_value - best) <= 1e-12]
    return preferred if preferred in ties else ties[0]


class FrozenQPolicy:
    name = "Q_LEARNING"
    learning = False

    def __init__(self, table, fallback, config):
        self.table = MappingProxyType(dict(table))
        self.fallback = fallback
        self.config = config

    def choose(self, state, trigger, portfolio):
        valid = get_valid_actions(portfolio, trigger)
        preferred = self.fallback.choose(state, trigger, portfolio).target
        action = greedy_action(self.table, state, valid, preferred)
        entry = self.table.get((state, action), QEntry())
        if entry.visit_count < self.config.minimum_visit_count:
            return PolicyDecision(preferred, "LOW_SAMPLE_FALLBACK", None, entry.visit_count)
        return PolicyDecision(action, "GREEDY_Q", entry.q_value, entry.visit_count)

    def explain(self):
        rows = []
        for state in sorted({key[0] for key in self.table}, key=repr):
            direction = state.trigger_bucket.rsplit("_", 1)[-1]
            trigger = SimpleNamespace(direction=direction)
            portfolio = SimpleNamespace(current_exposure=state.exposure_bucket)
            valid = get_valid_actions(portfolio, trigger)
            recommendation = self.choose(state, trigger, portfolio)
            for action in (*TARGET_EXPOSURES, None):
                entry = self.table.get((state, action), QEntry())
                rows.append(dict(state=state.to_dict(), target_exposure=action, q_value=entry.q_value,
                                 visit_count=entry.visit_count, update_count=entry.update_count,
                                 valid_at_bucket=action in valid,
                                 recommended_at_bucket=action == recommendation.target,
                                 recommendation_reason=recommendation.reason))
        return rows


class QLearningTrainer:
    name = "Q_LEARNING_TRAINING"
    learning = True

    def __init__(self, fallback, config=QConfig()):
        self.config, self.fallback = config, fallback
        self.table = {}
        self.support = {}
        self.rng = random.Random(config.random_seed)
        self.epsilon = config.epsilon_start

    def choose(self, state, trigger, portfolio):
        valid = get_valid_actions(portfolio, trigger)
        preferred = self.fallback.choose(state, trigger, portfolio).target
        action = self.rng.choice(valid) if self.rng.random() < self.epsilon else (
            greedy_action(self.table, state, valid, preferred))
        entry = self.table.get((state, action), QEntry())
        return PolicyDecision(action, "TRAINING_EPSILON_GREEDY", entry.q_value, entry.visit_count)

    def update(self, state, action, reward, next_state=None, valid_next=(), *, source_date="manual"):
        key = (state, action)
        entry = self.table.get(key, QEntry())
        bootstrap = max((self.table.get((next_state, a), QEntry()).q_value for a in valid_next), default=0.0)
        target = reward + (self.config.gamma * bootstrap if next_state is not None else 0.0)
        support = self.support.setdefault(key, set())
        support.add(source_date)
        self.table[key] = QEntry(entry.q_value + self.config.alpha * (target - entry.q_value),
                                 len(support), entry.update_count + 1)

    def observe(self, transition, action, next_trigger, portfolio):
        self.update(transition.state_before, action, transition.reward_after_regret, transition.state_after,
                    get_valid_actions(portfolio, next_trigger) if next_trigger else (),
                    source_date=transition.trigger_date)

    def train(self, run_training_episode):
        for episode in range(self.config.episodes):
            self.epsilon = max(self.config.epsilon_end, self.config.epsilon_start * self.config.epsilon_decay ** episode)
            # The callback creates a new PortfolioEnvironment on every episode.
            run_training_episode(self, self.observe)
        return self.freeze()

    def freeze(self):
        return FrozenQPolicy(self.table, self.fallback, self.config)
