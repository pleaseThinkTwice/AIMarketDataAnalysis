"""Configuration loader: YAML → frozen dataclasses, env var overrides.

Usage:
    from src.core.config import load_config
    cfg = load_config()
    print(cfg.llm.model)  # "deepseek-chat"
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# .env file loader (no extra dependency)
# ---------------------------------------------------------------------------

def _load_dotenv(dotenv_path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Only sets variables that aren't already set in the environment.
    Lines starting with # are treated as comments.
    """
    if dotenv_path is None:
        dotenv_path = _project_root() / ".env"
    if not dotenv_path.exists():
        return
    with open(dotenv_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Resolve project root (where config/ lives)
# ---------------------------------------------------------------------------
def _project_root() -> Path:
    """Return the project root directory (parent of src/)."""
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Dataclasses mirroring config/default.yaml
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMRetryConfig:
    max_attempts: int = 3
    base_delay_s: float = 2.0
    backoff_multiplier: float = 2.0


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_base: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    api_key: str = ""  # resolved from env at load time
    temperature_sql: float = 0.1
    temperature_plan: float = 0.3
    temperature_narrative: float = 0.5
    temperature_critic: float = 0.1
    max_tokens: int = 4096
    timeout_s: int = 30
    retry: LLMRetryConfig = field(default_factory=LLMRetryConfig)


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str = "BAAI/bge-large-zh-v1.5"
    dimension: int = 1024
    normalize: bool = True


@dataclass(frozen=True)
class SchemaRAGFusionConfig:
    rrf_k: int = 60
    vector_weight: float = 0.6
    bm25_weight: float = 0.4


@dataclass(frozen=True)
class SchemaRAGChunkConfig:
    top_k: int = 15


@dataclass(frozen=True)
class SchemaRAGConfig:
    chunk: SchemaRAGChunkConfig = field(default_factory=SchemaRAGChunkConfig)
    fusion: SchemaRAGFusionConfig = field(default_factory=SchemaRAGFusionConfig)


@dataclass(frozen=True)
class FewShotConfig:
    max_exemplars_per_query: int = 3
    exemplar_file: str = "data/exemplars.jsonl"


@dataclass(frozen=True)
class SandboxDBConfig:
    host: str = "localhost"
    port: int = 5432
    dbname: str = "ecommerce_analytics"
    user: str = "agent_readonly"
    password_env: str = "SANDBOX_DB_PASSWORD"
    password: str = ""


@dataclass(frozen=True)
class SandboxLimitsConfig:
    statement_timeout_s: int = 30
    max_rows: int = 100_000
    work_mem_mb: int = 64


@dataclass(frozen=True)
class SandboxConfig:
    db: SandboxDBConfig = field(default_factory=SandboxDBConfig)
    limits: SandboxLimitsConfig = field(default_factory=SandboxLimitsConfig)


@dataclass(frozen=True)
class CriticConfig:
    max_null_ratio: float = 0.30


@dataclass(frozen=True)
class CorrectionConfig:
    max_attempts: int = 3
    enable_critic: bool = True
    critic: CriticConfig = field(default_factory=CriticConfig)


@dataclass(frozen=True)
class SecurityConfig:
    sensitive_fields: tuple[str, ...] = (
        "phone", "email", "address", "cpf", "cnpj", "password", "credit_card",
    )
    forbidden_keywords_sql: tuple[str, ...] = (
        "DROP", "ALTER", "CREATE", "INSERT", "UPDATE", "DELETE",
        "TRUNCATE", "CALL", "DO", "EXECUTE", "GRANT", "REVOKE",
    )
    pg_system_schemas: tuple[str, ...] = ("pg_catalog", "information_schema")


@dataclass(frozen=True)
class VizConfig:
    font_family: str = "Noto Sans CJK SC"
    default_format: str = "png"
    dpi: int = 150


@dataclass(frozen=True)
class EvalConfig:
    spider_mini_path: str = "data/eval/spider_mini.jsonl"
    business_scenarios_path: str = "data/eval/business_scenarios.jsonl"
    judge_model: str = "claude-sonnet-4-20250514"
    judge_api_key_env: str = "ANTHROPIC_API_KEY"
    judge_api_key: str = ""
    eval_output_dir: str = "data/eval/reports"


@dataclass(frozen=True)
class AppConfig:
    """Top-level configuration aggregating all sub-sections."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    schema_rag: SchemaRAGConfig = field(default_factory=SchemaRAGConfig)
    few_shot: FewShotConfig = field(default_factory=FewShotConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    correction: CorrectionConfig = field(default_factory=CorrectionConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    viz: VizConfig = field(default_factory=VizConfig)
    eval: EvalConfig = field(default_factory=EvalConfig)


# ---------------------------------------------------------------------------
# YAML loading + env resolution
# ---------------------------------------------------------------------------

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_env(value: Any) -> Any:
    """Recursively resolve ${ENV_VAR} patterns in string values."""
    if isinstance(value, str):
        def _replace(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), "")
        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _dict_to_config(data: dict) -> AppConfig:
    """Convert a nested dict to AppConfig (and sub-dataclasses)."""

    def _populate(cls: type, d: dict) -> Any:
        import dataclasses as dc
        # Use typing.get_type_hints to resolve string annotations caused
        # by `from __future__ import annotations` (PEP 563).
        from typing import get_type_hints
        resolved_types = get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        for key, value in d.items():
            if key not in resolved_types:
                continue
            ftype = resolved_types[key]
            # Handle nested dataclass
            if dc.is_dataclass(ftype) and isinstance(value, dict):
                kwargs[key] = _populate(ftype, value)
            elif (origin := getattr(ftype, "__origin__", None)) and origin is tuple:
                # tuple[str, ...] → convert list to tuple
                kwargs[key] = tuple(value) if isinstance(value, list) else value
            else:
                kwargs[key] = value
        return cls(**kwargs)

    return _populate(AppConfig, data)  # type: ignore[return-value]


def _resolve_api_keys(cfg: AppConfig) -> AppConfig:
    """Resolve api_key fields from environment variables.

    Uses object.__setattr__ to bypass frozen dataclass restrictions during init.
    """
    updates: dict[str, Any] = {}

    # LLM API key
    if cfg.llm.api_key_env:
        key = os.environ.get(cfg.llm.api_key_env, "")
        updates["llm"] = {"api_key": key}

    # Sandbox DB password
    if cfg.sandbox.db.password_env:
        pw = os.environ.get(cfg.sandbox.db.password_env, "")
        updates["sandbox"] = {"db": {"password": pw}}

    # Eval judge API key
    if cfg.eval.judge_api_key_env:
        jk = os.environ.get(cfg.eval.judge_api_key_env, "")
        updates["eval"] = {"judge_api_key": jk}

    if not updates:
        return cfg

    # Rebuild config with resolved keys — use _apply_overrides helper
    raw = _config_to_dict(cfg)
    merged = _deep_merge(raw, updates)
    return _dict_to_config(merged)


def _config_to_dict(cfg: AppConfig) -> dict:
    """Convert AppConfig back to dict for merging."""
    import dataclasses as dc

    def _to_dict(obj: Any) -> Any:
        if dc.is_dataclass(obj):
            return {f.name: _to_dict(getattr(obj, f.name)) for f in dc.fields(obj)}
        if isinstance(obj, tuple):
            return list(obj)
        return obj

    return _to_dict(cfg)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file, with env var resolution.

    Args:
        config_path: Path to YAML config file. If None, uses config/default.yaml
                     relative to the project root.

    Returns:
        A frozen AppConfig instance with all values resolved.

    Environment variables used:
        DEEPSEEK_API_KEY     — LLM API key
        SANDBOX_DB_PASSWORD  — PostgreSQL sandbox password
        ANTHROPIC_API_KEY    — Claude judge API key
    """
    # Load .env before resolving config (only once, before first YAML read)
    _load_dotenv()

    if config_path is None:
        config_path = _project_root() / "config" / "default.yaml"

    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    # Resolve ${ENV_VAR} in YAML values
    resolved = _resolve_env(raw)

    # Build dataclass tree
    cfg = _dict_to_config(resolved)

    # Resolve api_key fields from environment
    cfg = _resolve_api_keys(cfg)

    return cfg


def reload_config(config_path: str | Path | None = None) -> AppConfig:
    """Force-reload config, bypassing the LRU cache."""
    load_config.cache_clear()
    return load_config(config_path)
