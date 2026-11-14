"""Building the agent from the settings (docs/07 §10; docs/12 §2).

Which model, routing service and tracer run is a matter of settings, never of code.
Under `app_env = "test"` nothing real can be built here: a test that forgot to use a
fake fails at once instead of spending money or sending data anywhere.
"""

import structlog
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.llm import ChatModel
from dawalink.agent.llm.base import has_price
from dawalink.agent.llm.claude import ClaudeModel
from dawalink.agent.llm.ollama import DEFAULT_MODEL, OllamaModel
from dawalink.agent.tracing import NoTracer, Tracer
from dawalink.agent.turn import Agent
from dawalink.config import ConfigError, Settings
from dawalink.domain.clock import Clock
from dawalink.routing import OpenRouteService
from dawalink.services.travel import RoutingService

log = structlog.get_logger(__name__)


def _no_real_services_in_tests(settings: Settings, what: str) -> None:
    if settings.app_env == "test":
        raise ConfigError(f"A test must not build a real {what}. Use the fake one.")


def build_model(settings: Settings) -> ChatModel | None:
    """The model the settings ask for, or None when the assistant is switched off."""
    if settings.llm_provider == "none":
        return None
    _no_real_services_in_tests(settings, "model")
    if settings.llm_provider == "ollama":
        return OllamaModel(base_url=settings.ollama_url, model=settings.llm_model or DEFAULT_MODEL)
    if settings.anthropic_api_key is None or not settings.llm_model:
        raise ConfigError("Missing or invalid settings: ANTHROPIC_API_KEY, LLM_MODEL")
    if not has_price(settings.llm_model):
        # Without a price the spend caps would count this model as free.
        raise ConfigError("LLM_MODEL has no price in dawalink/agent/llm/base.py")
    return ClaudeModel(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.llm_model,
        effort=settings.llm_effort,
    )


def build_routing(settings: Settings) -> RoutingService | None:
    """The routing service, or None: every travel time is then the straight-line estimate."""
    if settings.ors_api_key is None:
        return None
    _no_real_services_in_tests(settings, "routing service")
    return OpenRouteService(
        api_key=settings.ors_api_key.get_secret_value(), base_url=settings.ors_url
    )


def build_tracer(settings: Settings) -> Tracer:
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        return NoTracer()
    _no_real_services_in_tests(settings, "tracer")
    # Imported here: without keys, the tracing client is never even loaded.
    from dawalink.agent.tracing_langfuse import LangfuseTracer

    return LangfuseTracer(
        public_key=settings.langfuse_public_key.get_secret_value(),
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
        release=settings.app_version,
    )


def build_agent(settings: Settings, sessions: sessionmaker[Session], clock: Clock) -> Agent | None:
    """The agent, or None when no model is configured (the rest of the app still works)."""
    model = build_model(settings)
    if model is None:
        report = log.error if settings.app_env == "aws" else log.warning
        report("assistant_not_configured", effect="no agent turn runs; search still works")
        return None
    routing = build_routing(settings)
    if routing is None:
        log.warning("routing_not_configured", effect="travel times are straight-line estimates")
    tracer = build_tracer(settings)
    log.info(
        "agent_ready",
        provider=settings.llm_provider,
        model=model.name,
        routing=routing is not None,
        tracing=not isinstance(tracer, NoTracer),
    )
    return Agent(
        sessions=sessions,
        clock=clock,
        model=model,
        routing=routing,
        tracer=tracer,
        monthly_budget_usd=settings.llm_monthly_budget_usd,
    )
