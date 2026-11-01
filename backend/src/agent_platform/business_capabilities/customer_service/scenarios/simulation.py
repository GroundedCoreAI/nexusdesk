"""Deterministic, side-effect-free service-scenario simulation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import (
    HandlerCondition,
    HandlerDefinition,
    HandlerType,
    ObjectMode,
    ScenarioConfig,
    ScenarioStatus,
    SimulatedObject,
    SimulationRequest,
    SimulationTrace,
    UserDecisionKind,
)

_STEP_ORDER = ("scene", "object", "facts", "decision", "handler", "result")


@dataclass(frozen=True, slots=True)
class _Candidate:
    key: str
    name: str
    version: int | None
    status: ScenarioStatus
    config: ScenarioConfig


def _steps() -> dict[str, dict[str, Any]]:
    return {name: {"step": name, "status": "pending"} for name in _STEP_ORDER}


def _result(
    status: str,
    reason: str,
    content: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "reason_code": reason,
        "content": content,
        **extra,
    }


def _finish(
    *,
    candidate: _Candidate,
    resolved_by: str,
    steps: dict[str, dict[str, Any]],
    result: dict[str, Any],
    object_ref: dict[str, Any] | None = None,
    facts: list[dict[str, Any]] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
    handler: dict[str, Any] | None = None,
    fallback_path: list[str] | None = None,
    explanation: list[str] | None = None,
) -> SimulationTrace:
    steps["result"].update(
        {
            "status": result["status"],
            "reason": result["reason"],
            "content": result["content"],
        }
    )
    return SimulationTrace(
        scenario_key=candidate.key,
        scenario_name=candidate.name,
        scenario_version=candidate.version,
        scenario_status=candidate.status,
        resolved_by=resolved_by,
        steps=list(steps.values()),
        object_ref=object_ref,
        facts=facts or [],
        decisions=decisions or [],
        recommendations=recommendations or [],
        handler=handler,
        result=result,
        fallback_path=fallback_path or [],
        explanation=explanation or [],
    )


def _skip_after(
    steps: dict[str, dict[str, Any]],
    current: str,
    reason: str,
) -> None:
    skipping = False
    for name in _STEP_ORDER:
        if name == current:
            skipping = True
            continue
        if skipping and name != "result":
            steps[name].update({"status": "skipped", "reason": reason})


def _status(value: Any) -> ScenarioStatus:
    if isinstance(value, ScenarioStatus):
        return value
    return ScenarioStatus(str(value or ScenarioStatus.DRAFT.value))


def _candidate_from_mapping(
    key: str,
    raw: Any,
    fallback: _Candidate,
) -> _Candidate:
    if isinstance(raw, ScenarioConfig):
        return _Candidate(
            key=key,
            name=raw.name,
            version=fallback.version,
            status=fallback.status,
            config=raw,
        )
    if not isinstance(raw, Mapping):
        raise TypeError("all_scenarios entries must be mapping objects or ScenarioConfig")

    config_raw = raw.get("config")
    if config_raw is None and "handlers" in raw:
        config_raw = raw
    if config_raw is None:
        raise ValueError(f"scenario candidate '{key}' has no config")
    config = (
        config_raw
        if isinstance(config_raw, ScenarioConfig)
        else ScenarioConfig.model_validate(config_raw)
    )
    version = raw.get("version", raw.get("published_version", fallback.version))
    return _Candidate(
        key=str(raw.get("key") or raw.get("scenario_key") or key),
        name=str(raw.get("name") or raw.get("scenario_name") or config.name),
        version=int(version) if version is not None else None,
        status=_status(raw.get("status", fallback.status)),
        config=config,
    )


def _candidates(
    *,
    target: _Candidate,
    all_scenarios: Any,
) -> list[_Candidate]:
    if all_scenarios is None:
        return [target]

    result: list[_Candidate] = []
    if isinstance(all_scenarios, Mapping):
        source: Sequence[Any] = [
            {"key": key, **value} if isinstance(value, Mapping) else {"key": key, "config": value}
            for key, value in all_scenarios.items()
        ]
    elif isinstance(all_scenarios, Sequence) and not isinstance(
        all_scenarios, (str, bytes, bytearray)
    ):
        source = all_scenarios
    else:
        raise TypeError("all_scenarios must be a sequence or mapping")

    for index, raw in enumerate(source):
        if isinstance(raw, ScenarioConfig):
            key = target.key if index == 0 else raw.name
        elif isinstance(raw, Mapping):
            key = str(
                raw.get("key")
                or raw.get("scenario_key")
                or (target.key if index == 0 else raw.get("name") or index)
            )
        else:
            raise TypeError("all_scenarios entries must be mapping objects or ScenarioConfig")
        result.append(_candidate_from_mapping(key, raw, target))

    # The explicitly targeted scene is authoritative.  This prevents a stale
    # catalog payload from changing the config being simulated.
    result = [candidate for candidate in result if candidate.key != target.key]
    result.append(target)
    return result


def _score(config: ScenarioConfig, message: str) -> tuple[int, list[str]]:
    folded = message.casefold()
    if any(term.casefold() in folded for term in config.matching.negative_keywords):
        return -1, []
    matched = [
        term
        for term in [*config.matching.keywords, *config.matching.intents]
        if term and term.casefold() in folded
    ]
    # Longer terms are more specific.  Summing also rewards a scene that
    # covers several independent parts of a compound request.
    return sum(len(term) for term in matched), matched


def _resolve_candidate(
    *,
    target: _Candidate,
    request: SimulationRequest,
    all_scenarios: Any,
) -> tuple[_Candidate | None, str]:
    if all_scenarios is None:
        return target, "target"

    candidates = _candidates(target=target, all_scenarios=all_scenarios)
    if request.entry.value != "natural_language":
        target_has_entry = any(
            entry.enabled and entry.type.value == request.entry.value
            for entry in target.config.entries
        )
        if target_has_entry:
            return target, "target"

    best: _Candidate | None = None
    best_score = -1
    for candidate in candidates:
        score, _ = _score(candidate.config, request.message)
        if score < 0:
            continue
        if score > best_score or (score == best_score and candidate.key == target.key):
            best = candidate
            best_score = score
    if best is None or best_score <= 0:
        return None, "none"
    return best, "keyword"


def _value_at_path(values: dict[str, Any], source: str) -> Any:
    current: Any = values
    for part in source.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return None
    return current


def _mask(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]


def _project_facts(
    config: ScenarioConfig,
    obj: SimulatedObject,
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for fact in sorted(config.facts, key=lambda item: item.order):
        value = _value_at_path(obj.facts, fact.source)
        if fact.masked:
            value = _mask(value)
        projected.append(
            {
                "key": fact.key,
                "label": fact.label,
                "source": fact.source,
                "value": value,
                "format": fact.format,
                "order": fact.order,
                "masked": fact.masked,
                "audiences": list(fact.audiences),
                "refresh": fact.refresh,
            }
        )
    return projected


def _condition_matches(
    condition: HandlerCondition,
    *,
    obj: SimulatedObject | None,
    message: str,
    selected_decision: str | None,
) -> bool:
    if condition.object_statuses and (
        obj is None
        or obj.status.casefold() not in {status.casefold() for status in condition.object_statuses}
    ):
        return False
    if condition.message_terms:
        folded = message.casefold()
        if not any(term.casefold() in folded for term in condition.message_terms):
            return False
    if condition.decision_keys and selected_decision not in condition.decision_keys:
        return False
    return not (condition.requires_object is True and obj is None)


def _decision_projection(
    config: ScenarioConfig,
    selected_decision: str | None,
) -> list[dict[str, Any]]:
    return [
        {
            "key": decision.key,
            "kind": decision.kind.value,
            "label": decision.label,
            "required": decision.required,
            "options": [
                {
                    "value": option.value,
                    "label": option.label,
                    "description": option.description,
                    "next": option.next,
                }
                for option in decision.options
            ],
            "confirm": decision.confirm,
            "correctable": decision.correctable,
            "when": decision.when,
            "selected": decision.key == selected_decision,
        }
        for decision in config.decisions
    ]


def _recommendation_projection(
    config: ScenarioConfig,
    *,
    obj: SimulatedObject | None,
    message: str,
    selected_decision: str | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for recommendation in config.recommendations:
        condition = HandlerCondition.model_validate(recommendation.when)
        if not _condition_matches(
            condition,
            obj=obj,
            message=message,
            selected_decision=selected_decision,
        ):
            continue
        items.append(
            {
                "key": recommendation.key,
                "label": recommendation.label,
                "message": recommendation.message,
                "when": recommendation.when,
            }
        )
    return items


def _ordered_handlers(config: ScenarioConfig) -> list[HandlerDefinition]:
    handlers = [
        (index, handler) for index, handler in enumerate(config.handlers) if handler.enabled
    ]
    handlers.sort(key=lambda item: (item[1].priority, item[0]))
    return [handler for _, handler in handlers]


def _handler_payload(
    handler: HandlerDefinition,
    *,
    reason: str,
    condition_met: bool,
) -> dict[str, Any]:
    payload = handler.model_dump(mode="json")
    payload.update({"reason": reason, "condition_met": condition_met})
    return payload


def _confirmation_required(handler: HandlerDefinition) -> bool:
    return (
        handler.type == HandlerType.ACTION
        and handler.config.get("requires_confirmation", True) is not False
    )


def _is_confirmed(
    config: ScenarioConfig,
    selected_decision: str | None,
) -> bool:
    return selected_decision is not None and any(
        decision.kind == UserDecisionKind.CONFIRM_ACTION and decision.key == selected_decision
        for decision in config.decisions
    )


def _handler_result(
    handler: HandlerDefinition,
    *,
    config: ScenarioConfig,
    selected_decision: str | None,
) -> tuple[dict[str, Any], str]:
    if handler.type == HandlerType.DIRECT:
        return (
            _result("succeeded", "direct_reply", handler.reply or "", reply=handler.reply),
            handler.reply or "",
        )
    if handler.type == HandlerType.KNOWLEDGE:
        return (
            _result(
                "succeeded",
                "knowledge_answer",
                f"已命中知识承接「{handler.label}」。",
                knowledge_base=handler.config.get("knowledge_base"),
            ),
            f"选择知识承接「{handler.label}」。",
        )
    if handler.type == HandlerType.QUERY:
        return (
            _result(
                "succeeded",
                "query_executed",
                f"已按当前对象执行查询「{handler.label}」。",
                tool=handler.tool,
            ),
            f"选择查询承接「{handler.label}」。",
        )
    if handler.type == HandlerType.ACTION:
        confirmed = _is_confirmed(config, selected_decision)
        return (
            _result(
                "succeeded",
                "action_confirmed" if confirmed else "action_executed",
                f"已确认并执行「{handler.label}」。"
                if confirmed
                else f"已执行「{handler.label}」。",
                confirmation_required=_confirmation_required(handler),
                confirmation_decision=selected_decision if confirmed else None,
                tool=handler.tool,
            ),
            f"选择办理承接「{handler.label}」。",
        )
    if handler.type == HandlerType.AGENT:
        return (
            _result(
                "succeeded",
                "agent_routed",
                f"已转交 Agent「{handler.agent_name or handler.label}」处理。",
                agent_id=str(handler.agent_id) if handler.agent_id else None,
                agent_version=handler.agent_version,
                agent_name=handler.agent_name,
            ),
            f"选择 Agent 承接「{handler.label}」。",
        )
    if handler.type == HandlerType.HUMAN:
        return (
            _result(
                "handoff",
                "human_handoff",
                f"已转入人工队列「{handler.queue or 'default'}」。",
                queue=handler.queue,
            ),
            f"选择人工承接「{handler.label}」。",
        )
    return (
        _result(
            "tracking",
            "tracking_created",
            f"已建立「{handler.label}」跟踪。",
            tracking_type=handler.config.get("tracking_type"),
        ),
        f"选择跟踪承接「{handler.label}」。",
    )


def simulate(
    scenario_key: str,
    scenario_name: str,
    scenario_version: int | None,
    scenario_status: ScenarioStatus | str,
    config: ScenarioConfig | dict[str, Any],
    request: SimulationRequest | dict[str, Any],
    all_scenarios: Any = None,
) -> SimulationTrace:
    """Resolve a scene and deterministically walk its configured path.

    No provider is called and no persistence is performed.  ``all_scenarios``
    accepts the catalog shape used by the scenario service
    (``{"key", "name", "version", "status", "config"}``) or a mapping of keys
    to configs/candidate mappings.
    """

    parsed_config = (
        config if isinstance(config, ScenarioConfig) else ScenarioConfig.model_validate(config)
    )
    parsed_request = (
        request
        if isinstance(request, SimulationRequest)
        else SimulationRequest.model_validate(request)
    )
    target = _Candidate(
        key=scenario_key,
        name=scenario_name,
        version=scenario_version,
        status=_status(scenario_status),
        config=parsed_config,
    )
    steps = _steps()
    selected_candidate, resolved_by = _resolve_candidate(
        target=target,
        request=parsed_request,
        all_scenarios=all_scenarios,
    )
    if selected_candidate is None:
        steps["scene"].update(
            {
                "status": "not_matched",
                "reason": "scene_not_matched",
                "message": parsed_request.message,
            }
        )
        _skip_after(steps, "scene", "scene_not_matched")
        return _finish(
            candidate=target,
            resolved_by=resolved_by,
            steps=steps,
            result=_result(
                "needs_input",
                "scene_not_matched",
                "未找到匹配的服务场景，请补充业务信息。",
            ),
            explanation=["用户消息未命中任何可用场景的关键词或意图。"],
        )

    candidate = selected_candidate
    config = candidate.config
    steps["scene"].update(
        {
            "status": "resolved",
            "resolved_by": resolved_by,
            "scenario_key": candidate.key,
            "scenario_name": candidate.name,
            "reason": "target_key" if resolved_by == "target" else "keyword_match",
        }
    )

    decisions = _decision_projection(config, parsed_request.selected_decision)
    decisions_step = {
        "status": "selected" if parsed_request.selected_decision else "available",
        "selected_decision": parsed_request.selected_decision,
        "available_keys": [decision.key for decision in config.decisions],
        "reason": "decision_projected",
    }
    steps["decision"].update(decisions_step)

    object_config = config.object
    object_required = bool(
        object_config is not None
        and object_config.mode != ObjectMode.NONE
        and (
            object_config.required
            or object_config.mode in {ObjectMode.REQUIRED, ObjectMode.MULTIPLE}
        )
    )
    simulated_object = parsed_request.object
    project_object = (
        object_config is not None
        and object_config.mode != ObjectMode.NONE
        and simulated_object is not None
    )

    if project_object and not simulated_object.exists:
        steps["object"].update(
            {
                "status": "needs_input",
                "reason": "object_missing",
                "object_id": simulated_object.id,
                "object_type": simulated_object.type,
            }
        )
        steps["facts"].update({"status": "skipped", "reason": "object_missing"})
        steps["decision"].update({"status": "blocked", "reason": "object_missing"})
        steps["handler"].update({"status": "skipped", "reason": "object_missing"})
        _skip_after(steps, "object", "object_missing")
        return _finish(
            candidate=candidate,
            resolved_by=resolved_by,
            steps=steps,
            decisions=decisions,
            result=_result(
                "needs_input",
                "object_missing",
                "指定的业务对象不存在，请重新选择。",
            ),
            fallback_path=[],
            explanation=[
                f"场景「{candidate.name}」已解析。",
                "模拟业务对象不存在，停止后续事实投影与承接。",
            ],
        )

    if project_object and not simulated_object.accessible:
        steps["object"].update(
            {
                "status": "denied",
                "reason": "object_forbidden",
                "object_id": simulated_object.id,
                "object_type": simulated_object.type,
            }
        )
        steps["facts"].update({"status": "skipped", "reason": "object_forbidden"})
        steps["decision"].update({"status": "blocked", "reason": "object_forbidden"})
        steps["handler"].update({"status": "skipped", "reason": "object_forbidden"})
        _skip_after(steps, "object", "object_forbidden")
        return _finish(
            candidate=candidate,
            resolved_by=resolved_by,
            steps=steps,
            decisions=decisions,
            result=_result(
                "denied",
                "object_forbidden",
                "当前客户无权访问该业务对象。",
            ),
            explanation=[
                f"场景「{candidate.name}」已解析。",
                "模拟业务对象不在当前客户的权限范围内。",
            ],
        )

    if object_required and simulated_object is None:
        steps["object"].update(
            {
                "status": "needs_input",
                "reason": "object_required",
                "mode": object_config.mode.value if object_config else None,
                "object_type": object_config.type if object_config else None,
            }
        )
        steps["facts"].update({"status": "skipped", "reason": "object_required"})
        steps["decision"].update({"status": "blocked", "reason": "object_required"})
        steps["handler"].update({"status": "skipped", "reason": "object_required"})
        _skip_after(steps, "object", "object_required")
        return _finish(
            candidate=candidate,
            resolved_by=resolved_by,
            steps=steps,
            decisions=decisions,
            result=_result(
                "needs_input",
                "object_required",
                "该场景需要先选择业务对象。",
            ),
            explanation=[
                f"场景「{candidate.name}」已解析。",
                "场景要求业务对象，但模拟请求未提供对象。",
            ],
        )

    object_ref: dict[str, Any] | None = None
    projected_facts: list[dict[str, Any]] = []
    if project_object and simulated_object is not None:
        object_ref = {
            "id": simulated_object.id,
            "type": simulated_object.type,
            "status": simulated_object.status,
        }
        projected_facts = _project_facts(config, simulated_object)
        steps["object"].update(
            {
                "status": "resolved",
                "reason": "object_resolved",
                "object": object_ref,
                "mode": object_config.mode.value if object_config else None,
            }
        )
        steps["facts"].update(
            {
                "status": "projected",
                "reason": "configured_facts_only",
                "count": len(projected_facts),
                "keys": [fact["key"] for fact in projected_facts],
            }
        )
    else:
        steps["object"].update(
            {
                "status": "skipped",
                "reason": "object_not_required",
                "mode": object_config.mode.value if object_config else "none",
            }
        )
        steps["facts"].update({"status": "skipped", "reason": "no_object_context", "count": 0})

    recommendations = _recommendation_projection(
        config,
        obj=simulated_object if project_object else None,
        message=parsed_request.message,
        selected_decision=parsed_request.selected_decision,
    )

    handlers = _ordered_handlers(config)
    handler_step = steps["handler"]
    condition_obj = simulated_object if project_object else None
    selected_handler: HandlerDefinition | None = None
    fallback_path: list[str] = []

    if parsed_request.selected_handler:
        selected = next(
            (handler for handler in handlers if handler.key == parsed_request.selected_handler),
            None,
        )
        if selected is None or not _condition_matches(
            selected.when,
            obj=condition_obj,
            message=parsed_request.message,
            selected_decision=parsed_request.selected_decision,
        ):
            handler_step.update(
                {
                    "status": "condition_not_met",
                    "reason": "handler_condition_not_met",
                    "selected_handler": parsed_request.selected_handler,
                }
            )
            _skip_after(steps, "handler", "handler_condition_not_met")
            return _finish(
                candidate=candidate,
                resolved_by=resolved_by,
                steps=steps,
                object_ref=object_ref,
                facts=projected_facts,
                decisions=decisions,
                recommendations=recommendations,
                result=_result(
                    "needs_input",
                    "handler_condition_not_met",
                    "所选处理承接不满足当前对象、消息或决策条件。",
                ),
                explanation=[
                    f"场景「{candidate.name}」已解析。",
                    f"显式指定的承接「{parsed_request.selected_handler}」条件不满足。",
                ],
            )
        selected_handler = selected
        fallback_path = [selected.key]
    else:
        for handler in handlers:
            fallback_path.append(handler.key)
            if _condition_matches(
                handler.when,
                obj=condition_obj,
                message=parsed_request.message,
                selected_decision=parsed_request.selected_decision,
            ):
                selected_handler = handler
                break

    if selected_handler is None:
        handler_step.update(
            {
                "status": "missing",
                "reason": "handler_not_matched",
                "evaluated": list(fallback_path),
            }
        )
        _skip_after(steps, "handler", "handler_not_matched")
        return _finish(
            candidate=candidate,
            resolved_by=resolved_by,
            steps=steps,
            object_ref=object_ref,
            facts=projected_facts,
            decisions=decisions,
            recommendations=recommendations,
            fallback_path=fallback_path,
            result=_result(
                "needs_input",
                "handler_not_matched",
                "当前场景没有满足条件的处理承接，请补充信息或转人工。",
            ),
            explanation=[
                f"场景「{candidate.name}」已解析。",
                "已按优先级检查全部启用承接，均未满足条件。",
            ],
        )

    if _confirmation_required(selected_handler) and not _is_confirmed(
        config, parsed_request.selected_decision
    ):
        handler = _handler_payload(
            selected_handler,
            reason="confirmation_required",
            condition_met=True,
        )
        handler_step.update(
            {
                "status": "confirmation_required",
                "reason": "action_confirmation_required",
                "handler_key": selected_handler.key,
                "handler_type": selected_handler.type.value,
            }
        )
        _skip_after(steps, "handler", "action_confirmation_required")
        return _finish(
            candidate=candidate,
            resolved_by=resolved_by,
            steps=steps,
            object_ref=object_ref,
            facts=projected_facts,
            decisions=decisions,
            recommendations=recommendations,
            handler=handler,
            fallback_path=fallback_path,
            result=_result(
                "needs_input",
                "action_confirmation_required",
                "该办理动作需要用户先确认。",
                handler_key=selected_handler.key,
            ),
            explanation=[
                f"场景「{candidate.name}」已解析。",
                f"承接「{selected_handler.label}」需要 confirm_action 决策。",
            ],
        )

    handler = _handler_payload(
        selected_handler,
        reason="selected",
        condition_met=True,
    )
    result, result_explanation = _handler_result(
        selected_handler,
        config=config,
        selected_decision=parsed_request.selected_decision,
    )
    handler_step.update(
        {
            "status": "selected",
            "reason": "handler_selected",
            "handler_key": selected_handler.key,
            "handler_type": selected_handler.type.value,
            "priority": selected_handler.priority,
            "matched_explicitly": bool(parsed_request.selected_handler),
        }
    )
    explanation = [
        (
            f"按目标键进入场景「{candidate.name}」。"
            if resolved_by == "target"
            else f"按关键词命中场景「{candidate.name}」。"
        )
    ]
    if object_ref is not None:
        explanation.append(f"已绑定业务对象 {object_ref['type']}:{object_ref['id']}。")
        explanation.append(f"按场景配置投影 {len(projected_facts)} 个业务事实。")
    else:
        explanation.append("该场景不要求业务对象，跳过对象与事实投影。")
    if parsed_request.selected_decision:
        explanation.append(f"用户决策：{parsed_request.selected_decision}。")
    else:
        explanation.append("未提供用户决策。")
    explanation.append(result_explanation)
    return _finish(
        candidate=candidate,
        resolved_by=resolved_by,
        steps=steps,
        object_ref=object_ref,
        facts=projected_facts,
        decisions=decisions,
        recommendations=recommendations,
        handler=handler,
        fallback_path=fallback_path,
        result=result,
        explanation=explanation,
    )


__all__ = ["simulate"]
