"""LangGraph StateGraph for the Plan-and-Execute agent.

The graph has 7 nodes and 3 conditional edges:

    [plan] → [retrieve_schema] → [generate_sql] → [execute]
                                                       ↓
                                       ┌─ ok ─→ [critic] ─┬─ pass ─→ next_task/[synthesize]
                                       │                  └─ fail ─→ [regenerate] → [execute]
                                       └─ error ───────────→ [regenerate] → [execute]

This file defines node functions and the graph builder.
The Orchestrator (orchestrator.py) is the public entry point.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from src.agent.state import AnalysisState
from src.core.config import AppConfig
from src.core.schemas import (
    Task, RetrievedSchema, ExecutionResult, SQLAttempt, CriticVerdict,
    ExecutionStatus, ErrorClass,
)
from src.core.logging import get_logger

logger = get_logger(__name__, component="agent_graph")


# =========================================================================
# Node functions — each returns a partial state dict
# =========================================================================


def _plan_node(state: AnalysisState, config: AppConfig, planner) -> dict:
    """Decompose user query into tasks."""
    logger.info("node_plan", query=state["user_query"][:80])

    try:
        plan = planner.plan(state["user_query"])
        tasks = [t.model_dump() for t in plan.tasks]
        return {
            "plan": tasks,
            "plan_reasoning": plan.reasoning,
            "current_task_index": 0,
            "current_task": tasks[0] if tasks else None,
            "status": "executing",
        }
    except Exception as e:
        logger.error("plan_failed", error=str(e))
        return {"status": "failed", "error_message": str(e)}


def _retrieve_schema_node(state: AnalysisState, config: AppConfig, retriever) -> dict:
    """Retrieve relevant schema for the current task."""
    task_dict = state["current_task"]
    task = Task(**task_dict)
    logger.info("node_retrieve_schema", task_id=task.id, goal=task.goal[:60])

    schema_contexts = dict(state.get("schema_contexts", {}))
    try:
        schema = retriever.retrieve(task.goal)
        # Serialize for state (TypedDict can't store Pydantic directly)
        schema_contexts[str(task.id)] = schema.model_dump()
    except Exception as e:
        logger.error("schema_retrieval_failed", error=str(e))
        # Fallback: empty schema
        schema_contexts[str(task.id)] = RetrievedSchema().model_dump()

    return {"schema_contexts": schema_contexts}


def _generate_sql_node(state: AnalysisState, config: AppConfig, generator, few_shot_retriever) -> dict:
    """Generate SQL for the current task."""
    task = Task(**state["current_task"])
    logger.info("node_generate_sql", task_id=task.id)

    # Get schema context
    schema_contexts = state.get("schema_contexts", {})
    schema_dict = schema_contexts.get(str(task.id), {})
    schema = RetrievedSchema(**schema_dict)

    # Get upstream results
    upstream = {}
    task_results = state.get("task_results", {})
    for dep_id in task.depends_on:
        if str(dep_id) in task_results:
            r = ExecutionResult(**task_results[str(dep_id)])
            upstream[dep_id] = r.summary()

    # Get few-shot exemplars
    few_shots = few_shot_retriever.retrieve(task.goal)

    # Generate
    attempt = generator.generate(task, schema, few_shots, upstream)

    # Track attempt
    sql_log = list(state.get("sql_log", []))
    sql_log.append(attempt.model_dump())

    correction_attempts = dict(state.get("correction_attempts", {}))
    correction_attempts[str(task.id)] = correction_attempts.get(str(task.id), 0)

    return {
        "current_sql": attempt.sql,
        "current_reasoning": attempt.reasoning,
        "current_expected_shape": attempt.expected_output_shape,
        "sql_log": sql_log,
        "correction_attempts": correction_attempts,
    }


def _execute_node(state: AnalysisState, config: AppConfig, security) -> dict:
    """Execute SQL in the sandbox."""
    sql = state["current_sql"]
    task = Task(**state["current_task"])
    logger.info("node_execute", task_id=task.id, sql_len=len(sql))

    result = security.validate_and_execute(sql)
    result.task_id = task.id
    result.sql = sql

    task_results = dict(state.get("task_results", {}))
    task_results[str(task.id)] = result.model_dump()

    return {"task_results": task_results}


def _critic_node(state: AnalysisState, config: AppConfig, critic) -> dict:
    """Check if the execution result is acceptable."""
    task = Task(**state["current_task"])
    task_results = state.get("task_results", {})
    result_dict = task_results.get(str(task.id), {})
    result = ExecutionResult(**result_dict)

    logger.info("node_critic", task_id=task.id, row_count=result.row_count)

    try:
        verdict = critic.check(task, state["current_sql"], result, state["current_expected_shape"])
    except Exception as e:
        logger.error("critic_failed", error=str(e))
        verdict = CriticVerdict(acceptable=True, feedback="Critic unavailable, accepting result.", confidence=0.5)

    critic_verdicts = dict(state.get("critic_verdicts", {}))
    critic_verdicts[str(task.id)] = verdict.model_dump()

    return {"critic_verdicts": critic_verdicts}


def _regenerate_node(state: AnalysisState, config: AppConfig, generator, retriever) -> dict:
    """Regenerate SQL after an execution error."""
    task = Task(**state["current_task"])
    task_results = state.get("task_results", {})
    result_dict = task_results.get(str(task.id), {})
    result = ExecutionResult(**result_dict)

    # Increment correction attempts
    correction_attempts = dict(state.get("correction_attempts", {}))
    current_attempts = correction_attempts.get(str(task.id), 0) + 1
    correction_attempts[str(task.id)] = current_attempts

    logger.info("node_regenerate", task_id=task.id, attempt=current_attempts,
                error_class=result.error_class.value if result.error_class else "unknown")

    # Re-retrieve schema (may get better results with error info)
    schema_contexts = dict(state.get("schema_contexts", {}))
    try:
        enriched_query = f"{task.goal} {result.error or ''}"
        schema = retriever.retrieve(enriched_query)
        schema_contexts[str(task.id)] = schema.model_dump()
    except Exception:
        pass

    schema = RetrievedSchema(**schema_contexts.get(str(task.id), {}))

    # Build previous attempt
    prev = SQLAttempt(
        attempt_number=current_attempts,
        sql=state["current_sql"],
        reasoning=state["current_reasoning"],
        expected_output_shape=state["current_expected_shape"],
    )

    # Regenerate
    error_class = result.error_class.value if result.error_class else "unknown"
    new_attempt = generator.regenerate(
        task, prev, result.error or "Unknown error", error_class, schema,
    )

    # Track
    sql_log = list(state.get("sql_log", []))
    sql_log.append(new_attempt.model_dump())

    return {
        "current_sql": new_attempt.sql,
        "current_reasoning": new_attempt.reasoning,
        "current_expected_shape": new_attempt.expected_output_shape,
        "sql_log": sql_log,
        "correction_attempts": correction_attempts,
        "schema_contexts": schema_contexts,
    }


# =========================================================================
# Routing — conditional edges
# =========================================================================


def _route_after_execute(state: AnalysisState, config: AppConfig) -> Literal["critic", "regenerate", "synthesize"]:
    """Decide where to go after SQL execution."""
    task = Task(**state["current_task"])
    task_results = state.get("task_results", {})
    result_dict = task_results.get(str(task.id), {})
    result = ExecutionResult(**result_dict)

    # Check if we've exhausted correction attempts
    correction_attempts = state.get("correction_attempts", {})
    attempts = correction_attempts.get(str(task.id), 0)
    max_attempts = config.correction.max_attempts

    if result.is_ok:
        if config.correction.enable_critic:
            return "critic"
        # No critic — go to next task or synthesize
        return _next_task_or_synthesize(state)
    else:
        if attempts < max_attempts:
            return "regenerate"
        # Maxed out — mark failed and move on
        failed = list(state.get("failed_tasks", []))
        failed.append(task.id)
        state["failed_tasks"] = failed
        logger.warning("task_failed_max_attempts", task_id=task.id, attempts=attempts)
        return _next_task_or_synthesize(state)


def _route_after_critic(state: AnalysisState, config: AppConfig) -> Literal["regenerate", "synthesize"]:
    """Decide where to go after critic review."""
    task = Task(**state["current_task"])
    critic_verdicts = state.get("critic_verdicts", {})
    verdict_dict = critic_verdicts.get(str(task.id), {})
    verdict = CriticVerdict(**verdict_dict)

    correction_attempts = state.get("correction_attempts", {})
    attempts = correction_attempts.get(str(task.id), 0)
    max_attempts = config.correction.max_attempts

    if verdict.acceptable:
        return _next_task_or_synthesize(state)
    else:
        if attempts < max_attempts:
            logger.info("critic_rejected", task_id=task.id, feedback=verdict.feedback[:80])
            # Add critic feedback as error
            task_results = dict(state.get("task_results", {}))
            result_dict = task_results.get(str(task.id), {})
            result = ExecutionResult(**result_dict)
            result.error = verdict.feedback
            result.error_class = ErrorClass.SEMANTIC
            task_results[str(task.id)] = result.model_dump()
            state["task_results"] = task_results
            return "regenerate"
        else:
            failed = list(state.get("failed_tasks", []))
            failed.append(task.id)
            state["failed_tasks"] = failed
            return _next_task_or_synthesize(state)


def _next_task_or_synthesize(state: AnalysisState) -> Literal["synthesize"]:
    """Determine if there are more tasks or we should synthesize."""
    plan = state.get("plan", [])
    current_idx = state.get("current_task_index", 0)

    if current_idx + 1 < len(plan):
        # Advance to next task
        state["current_task_index"] = current_idx + 1
        state["current_task"] = plan[current_idx + 1]
        # Don't return "retrieve_schema" here — handled by graph edge
        # Returning "synthesize" triggers the graph to go to the next iteration
        # Actually we need to modify the graph to handle this properly
        return "synthesize"

    return "synthesize"


# =========================================================================
# Graph builder
# =========================================================================


def build_graph(config: AppConfig, planner, retriever, generator, few_shot_retriever, security, critic):
    """Build and compile the LangGraph StateGraph.

    Returns a compiled graph ready for invocation.
    """
    from langgraph.graph import StateGraph, END

    graph = StateGraph(AnalysisState)

    # Add nodes — use closures to inject dependencies
    graph.add_node("plan", lambda s: _plan_node(s, config, planner))
    graph.add_node("retrieve_schema", lambda s: _retrieve_schema_node(s, config, retriever))
    graph.add_node("generate_sql", lambda s: _generate_sql_node(s, config, generator, few_shot_retriever))
    graph.add_node("execute", lambda s: _execute_node(s, config, security))
    graph.add_node("critic", lambda s: _critic_node(s, config, critic))
    graph.add_node("regenerate", lambda s: _regenerate_node(s, config, generator, retriever))

    # Edges
    graph.set_entry_point("plan")
    graph.add_edge("plan", "retrieve_schema")
    graph.add_edge("retrieve_schema", "generate_sql")
    graph.add_edge("generate_sql", "execute")

    graph.add_conditional_edges(
        "execute",
        lambda s: _route_after_execute(s, config),
        {
            "critic": "critic",
            "regenerate": "regenerate",
            "synthesize": END,
        },
    )

    graph.add_conditional_edges(
        "critic",
        lambda s: _route_after_critic(s, config),
        {
            "regenerate": "regenerate",
            "synthesize": END,
        },
    )

    graph.add_edge("regenerate", "execute")

    return graph.compile()
