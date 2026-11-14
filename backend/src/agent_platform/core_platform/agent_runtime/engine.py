import asyncio
import json
import time
from typing import TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from agent_platform.core_platform.agent_execution.contracts.instructions import (
    PreparedInstructions,
    ReactMessagePlan,
    instruction_contract_error,
    react_native_history_item,
    react_native_input_parts,
)
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault


class RunState(TypedDict):
    messages: list[BaseMessage]
    rounds: int
    tool_calls: int
    signatures: list[str]
    output: str


class RuntimeEngine:
    def __init__(self, model, tools, settings):
        self.model, self.tools, self.settings = model, tools, settings
        graph = StateGraph(RunState)
        graph.add_node("model", self._model)
        graph.add_node("tools", self._tools)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", self._route, {"tools": "tools", "end": END})
        graph.add_edge("tools", "model")
        self.graph = graph.compile()

    async def _model(self, state, config):
        emit = config["configurable"]["emit"]
        if state["rounds"] >= self.settings.max_model_rounds:
            raise RuntimeFault("model_round_limit")
        round_no = state["rounds"] + 1
        started = time.monotonic()
        await emit("model.started", {"round": round_no})
        # Time to the first visible character of this round. Recorded so the console
        # can report how long a customer waited for the answer to start, which is
        # what the typewriter effect is really for.
        first_token_ms = None

        async def on_delta(delta):
            nonlocal first_token_ms
            # Forward only content and reasoning; tool_calls here are partial JSON
            # arguments and arrive complete with model.completed instead.
            piece = {}
            if delta.get("content"):
                piece["text"] = delta["content"]
            if delta.get("reasoning_content"):
                piece["reasoning"] = delta["reasoning_content"]
            if piece:
                if first_token_ms is None:
                    first_token_ms = int((time.monotonic() - started) * 1000)
                await emit("model.delta", {"round": round_no, **piece})

        try:
            async with asyncio.timeout(self.settings.model_timeout_seconds):
                stream = getattr(self.model, "ainvoke_stream", None)
                if self.settings.stream_model_deltas and stream is not None:
                    reply = await stream(state["messages"], on_delta)
                else:
                    reply = await self.model.ainvoke(state["messages"])
        except TimeoutError as exc:
            raise RuntimeFault("model_timeout") from exc
        if not isinstance(reply, AIMessage) or reply.invalid_tool_calls:
            raise RuntimeFault("invalid_model_response")
        if len({call["id"] for call in reply.tool_calls}) != len(reply.tool_calls):
            raise RuntimeFault("duplicate_tool_call_id")
        if state["tool_calls"] + len(reply.tool_calls) > self.settings.max_tool_calls:
            raise RuntimeFault("tool_call_limit")
        output = (
            reply.content
            if isinstance(reply.content, str)
            else "".join(
                block.get("text", "")
                for block in reply.content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        )
        if not reply.tool_calls and not output.strip():
            raise RuntimeFault("empty_model_response")
        if len(output) > 64000:
            raise RuntimeFault("model_output_too_large")
        await emit(
            "model.completed",
            {
                "round": state["rounds"] + 1,
                "tool_calls": len(reply.tool_calls),
                "usage": reply.usage_metadata or {},
                "gateway_call_id": reply.response_metadata.get("gateway_call_id"),
                # Milliseconds from model.started to the first visible character, or
                # null when the round produced no text at all (a pure tool call).
                "first_token_ms": first_token_ms,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return {
            "messages": [*state["messages"], reply],
            "rounds": state["rounds"] + 1,
            "output": output if not reply.tool_calls else "",
        }

    def _route(self, state):
        return "tools" if state["messages"][-1].tool_calls else "end"

    async def _tools(self, state, config):
        emit = config["configurable"]["emit"]
        calls = state["messages"][-1].tool_calls
        signatures = list(state["signatures"])
        for call in calls:
            signature = json.dumps([call["name"], call["args"]], sort_keys=True)
            if signature in signatures:
                raise RuntimeFault("repeated_tool_call")
            signatures.append(signature)

        async def invoke(call):
            await emit("tool.started", {"name": call["name"], "call_id": call["id"]})
            tool_started = time.monotonic()
            result = await self.tools.execute(call["name"], call["args"])
            await emit(
                "tool.completed",
                {
                    "name": call["name"],
                    "call_id": call["id"],
                    "ok": result["ok"],
                    "error": result.get("error"),
                    "gateway_call_id": result.get("call_id"),
                    "execution_status": result.get("execution_status"),
                    "tool_version": result.get("tool_version"),
                    "duration_ms": int((time.monotonic() - tool_started) * 1000),
                },
            )
            return ToolMessage(
                content=json.dumps(result, ensure_ascii=False), tool_call_id=call["id"]
            )

        # The gateway only exposes independent read-only GET tools in this release.
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(invoke(call)) for call in calls]
        return {
            "messages": [*state["messages"], *(task.result() for task in tasks)],
            "tool_calls": state["tool_calls"] + len(calls),
            "signatures": signatures,
        }

    def _baseline_messages(
        self,
        message: str,
        kept: list[dict[str, object]],
        summary_message: str | None,
        customer_memory: str | None,
    ) -> list[BaseMessage]:
        """Assemble the run input exactly as Phase 2 always did.

        Kept as the untouched Phase 2 path: when no prepared instructions are
        supplied this is the only assembly the Engine performs.
        """
        messages: list[BaseMessage] = [SystemMessage(content=self.settings.system_prompt)]
        if summary_message and self.settings.summary_enabled:
            # Rolling summary of everything the sliding window dropped. It sits
            # between the system prompt and the kept history; an empty summary
            # (or the kill switch) keeps the message sequence exactly as before.
            # The text is rendered by the memory capability and inserted verbatim:
            # the Runtime only owns the switch, not the wording.
            messages.append(SystemMessage(content=summary_message))
        if customer_memory:
            # Customer profile/preference memory (Phase 2, FR-3): right after
            # the summary and before the kept history. The worker already
            # applied the agent switch and the count/token budgets.
            messages.append(SystemMessage(content=customer_memory))
        for item in kept:
            messages.append(
                HumanMessage(content=item["content"])
                if item["role"] == "user"
                else AIMessage(
                    content=item["content"],
                    additional_kwargs={"reasoning_content": item["reasoning_content"]}
                    if item.get("reasoning_content") is not None
                    else {},
                )
            )
        messages.append(HumanMessage(content=message))
        return messages

    def _prepared_messages(
        self,
        prepared: PreparedInstructions,
        message: str,
        kept: list[dict[str, object]],
        summary_message: str | None,
        customer_memory: str | None,
    ) -> list[BaseMessage]:
        """Consume an instruction provider's native sequence; assemble nothing.

        Phase 3 moves message selection ahead of ``Adapter.start`` but not the
        business rendering behind it, so the Engine's only remaining job here is
        the format step: one provider entry becomes one LangChain message. A
        payload from a provider other than the registered React one, or one that
        violates the order contract, raises a configuration error instead of
        falling back to ``_baseline_messages``; a silent fallback would let a
        broken provider look like a successful run.

        The payload is first checked against the arguments it replaces
        (:meth:`_check_prepared_inputs`), so ignoring a contradiction is not an
        option either.
        """
        plan = react_native_input_parts(prepared)
        self._check_prepared_inputs(plan, message, kept, summary_message, customer_memory)
        messages: list[BaseMessage] = []
        for item in plan.messages:
            content = item["content"]
            if item["role"] == "system":
                messages.append(SystemMessage(content=content))
            elif item["role"] == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(
                    AIMessage(
                        content=content,
                        additional_kwargs=(
                            {"reasoning_content": item["reasoning_content"]}
                            if "reasoning_content" in item
                            else {}
                        ),
                    )
                )
        return messages

    @staticmethod
    def _check_prepared_inputs(
        plan: ReactMessagePlan,
        message: str,
        kept: list[dict[str, object]],
        summary_message: str | None,
        customer_memory: str | None,
    ) -> None:
        """Fail closed on a prepared payload that disagrees with this run.

        A prepared payload replaces the assembly, so the arguments alongside it
        are either a copy of something already inside it or a contradiction.
        Quietly preferring the payload was the defect: the model then saw one
        current input while the caller persisted another, a second Summary/Memory
        render disappeared without a trace, and two settings objects with
        different history windows produced identical messages whose kept/dropped
        split — the persisted history and the rollup queue — drifted apart. These
        are pure in-memory comparisons over data already validated once, and they
        run before the model is called; ``ConfigurationError`` is the same
        controlled error the payload grammar itself raises, never a fallback.
        """
        if plan.current_user_input != message:
            raise instruction_contract_error("instruction_consume", "current_user_input")
        # Business rendering happened during preparation; re-supplying it here
        # would mean the run has two sources of truth for one message sequence.
        if summary_message is not None:
            raise instruction_contract_error("instruction_consume", "summary_message")
        if customer_memory is not None:
            raise instruction_contract_error("instruction_consume", "customer_memory")
        # The Engine's own kept slice, projected exactly the way the Producer
        # projects it, must be the history the payload carries.
        if plan.history != tuple(react_native_history_item(item) for item in kept):
            raise instruction_contract_error("instruction_consume", "history")

    async def run(
        self,
        message,
        history,
        emit,
        summary_message=None,
        customer_memory=None,
        prepared_instructions=None,
    ):
        """Execute one ReAct loop and return ``(output, history, dropped)``.

        ``summary_message`` replaced the earlier ``summary`` parameter: it must
        already be rendered by the memory capability, and the Runtime inserts it
        verbatim. This is a deliberate breaking rename with no compatibility
        alias — accepting raw summary text under the old name would put the
        rendering (and its business wording) back inside the Runtime, which is
        the coupling the rename removed.

        ``prepared_instructions`` is the Phase 3 addition (FR-7): one
        ``PreparedInstructions`` produced before the run started. When present it
        is the sole source of the message sequence; ``message`` must be the very
        current input it already carries and ``summary_message``/
        ``customer_memory`` must be omitted, because the business rendering they
        stand for was done during preparation and a second copy here would mean
        two sources of truth for one run. ``_check_prepared_inputs`` enforces
        that, including that the payload's history is this Engine's own kept
        slice, so a mismatch fails closed instead of being quietly ignored.
        ``history`` keeps its original job either way — it is the sliding
        window the Engine writes back and reports as ``dropped``, which is why
        preparation hands over the same retained slice instead of replacing it.
        """
        kept = history[-self.settings.history_turns * 2 :] if self.settings.history_turns else []
        messages = (
            self._prepared_messages(
                prepared_instructions, message, kept, summary_message, customer_memory
            )
            if prepared_instructions is not None
            else self._baseline_messages(message, kept, summary_message, customer_memory)
        )
        async with asyncio.timeout(self.settings.run_timeout_seconds):
            result = await self.graph.ainvoke(
                {
                    "messages": messages,
                    "rounds": 0,
                    "tool_calls": 0,
                    "signatures": [],
                    "output": "",
                },
                config={
                    "recursion_limit": self.settings.max_model_rounds * 2 + 2,
                    "configurable": {"emit": emit},
                },
            )
        new_history = [
            *kept,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": result["output"],
                **(
                    {
                        "reasoning_content": result["messages"][-1].additional_kwargs[
                            "reasoning_content"
                        ]
                    }
                    if "reasoning_content" in result["messages"][-1].additional_kwargs
                    else {}
                ),
            },
        ]
        final = (
            new_history[-self.settings.history_turns * 2 :] if self.settings.history_turns else []
        )
        # Messages that fell out of the window this run; finish() feeds them to
        # the rolling-summary task queue. They always come from the old history,
        # never from the just-finished turn.
        dropped = new_history[: len(new_history) - len(final)]
        return result["output"], final, dropped
