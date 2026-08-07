"""Application settings.

A plain dataclass built once from ``os.environ`` and passed explicitly to whatever
needs it (DB connections, collectors, scoring config) -- never read as a hidden
global. Kept dependency-free (no pydantic): the settings surface is small enough
that hand-rolled parsing doesn't need a validation framework.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_csv(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


DEFAULT_REDDIT_SUBREDDITS: frozenset[str] = frozenset(
    {"SaaS", "Entrepreneur", "smallbusiness", "SideProject"}
)


@dataclass(frozen=True)
class Settings:
    database_url: str
    edgar_user_agent: str
    wikipedia_user_agent: str
    disabled_connectors: frozenset[str] = field(default_factory=frozenset)

    embedding_model_name: str = "intfloat/multilingual-e5-base"
    embedding_device: str = "cpu"

    momentum_recent_days: int = 7
    momentum_baseline_days: int = 56
    momentum_min_baseline_days: int = 28

    dedup_merge_threshold: float = 0.92
    dedup_novel_threshold: float = 0.75

    resurface_score_delta_pct: float = 0.40

    backlog_top_n: int = 20
    backlog_exploration_share: float = 0.25
    backlog_arbitrage_quota: float = 0.60
    backlog_max_category_share: float = 0.30

    anthropic_api_key: str = ""

    # Reddit connector is opt-in: registry.py skips building it when
    # reddit_client_id is empty, rather than failing startup, since (unlike
    # EDGAR/Wikipedia's User-Agent) a Reddit script app requires a deliberate
    # signup step most environments won't have done yet.
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = ""
    reddit_subreddits: frozenset[str] = field(default_factory=lambda: DEFAULT_REDDIT_SUBREDDITS)

    # Product Hunt is opt-in the same way: registry.py skips it when this is
    # empty, since every request needs a token (no anonymous tier at all).
    producthunt_access_token: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=_require(os.environ, "DATABASE_URL"),
            edgar_user_agent=_require(os.environ, "EDGAR_USER_AGENT"),
            wikipedia_user_agent=_require(os.environ, "WIKIPEDIA_USER_AGENT"),
            disabled_connectors=_split_csv(os.environ.get("DISABLED_CONNECTORS", "")),
            embedding_model_name=os.environ.get("EMBEDDING_MODEL_NAME", cls.embedding_model_name),
            embedding_device=os.environ.get("EMBEDDING_DEVICE", cls.embedding_device),
            momentum_recent_days=int(
                os.environ.get("MOMENTUM_RECENT_DAYS", cls.momentum_recent_days)
            ),
            momentum_baseline_days=int(
                os.environ.get("MOMENTUM_BASELINE_DAYS", cls.momentum_baseline_days)
            ),
            momentum_min_baseline_days=int(
                os.environ.get("MOMENTUM_MIN_BASELINE_DAYS", cls.momentum_min_baseline_days)
            ),
            dedup_merge_threshold=float(
                os.environ.get("DEDUP_MERGE_THRESHOLD", cls.dedup_merge_threshold)
            ),
            dedup_novel_threshold=float(
                os.environ.get("DEDUP_NOVEL_THRESHOLD", cls.dedup_novel_threshold)
            ),
            resurface_score_delta_pct=float(
                os.environ.get("RESURFACE_SCORE_DELTA_PCT", cls.resurface_score_delta_pct)
            ),
            backlog_top_n=int(os.environ.get("BACKLOG_TOP_N", cls.backlog_top_n)),
            backlog_exploration_share=float(
                os.environ.get("BACKLOG_EXPLORATION_SHARE", cls.backlog_exploration_share)
            ),
            backlog_arbitrage_quota=float(
                os.environ.get("BACKLOG_ARBITRAGE_QUOTA", cls.backlog_arbitrage_quota)
            ),
            backlog_max_category_share=float(
                os.environ.get("BACKLOG_MAX_CATEGORY_SHARE", cls.backlog_max_category_share)
            ),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            reddit_client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
            reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
            reddit_user_agent=os.environ.get("REDDIT_USER_AGENT", ""),
            reddit_subreddits=(
                _split_csv(os.environ["REDDIT_SUBREDDITS"])
                if os.environ.get("REDDIT_SUBREDDITS")
                else DEFAULT_REDDIT_SUBREDDITS
            ),
            producthunt_access_token=os.environ.get("PRODUCTHUNT_ACCESS_TOKEN", ""),
        )


def _require(env: os._Environ[str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise RuntimeError(f"missing required environment variable: {key}")
    return value
