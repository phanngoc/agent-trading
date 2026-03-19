"""
analyst_runner.py — Safe ReAct loop for analyst nodes.

Each analyst gets a clean local message history (isolated from global state["messages"]).
This prevents payload bloat from accumulated cross-analyst context.
Tool-call/result pairs are maintained locally until the analyst finishes,
then only the final text report is propagated back to global state.
"""

from copy import copy
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


def run_analyst_loop(
    chain,
    tools: list,
    initial_prompt: str,
    max_iterations: int = 15,
    max_tool_content_chars: int = 8000,
) -> str:
    """
    Run a ReAct-style tool-calling loop for an analyst in isolation.

    Args:
        chain: LangChain chain (prompt | llm.bind_tools(tools))
        tools: List of LangChain tool objects
        initial_prompt: The human message to start with (ticker + date context)
        max_iterations: Safety cap on tool-call iterations
        max_tool_content_chars: Truncate individual tool results to this length

    Returns:
        Final text report from the analyst (str)
    """
    # Build tool lookup map
    tool_map = {t.name: t for t in tools}

    # Local isolated message history — never touches state["messages"]
    local_messages = [HumanMessage(content=initial_prompt)]

    for iteration in range(max_iterations):
        # Call LLM with local history only
        result = chain.invoke(local_messages)
        local_messages.append(result)

        # No tool calls → analyst is done, return the report
        if not result.tool_calls:
            return result.content if isinstance(result.content, str) else str(result.content)

        # Execute each tool call and collect results
        for tc in result.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            tool_id = tc["id"]

            if tool_name not in tool_map:
                tool_output = f"Error: tool '{tool_name}' not found."
            else:
                try:
                    tool_output = tool_map[tool_name].invoke(tool_args)
                except Exception as e:
                    tool_output = f"Tool error: {e}"

            # Truncate oversized tool output
            if isinstance(tool_output, str) and len(tool_output) > max_tool_content_chars:
                tool_output = tool_output[:max_tool_content_chars] + "\n...[truncated for context limit]"

            local_messages.append(
                ToolMessage(content=str(tool_output), tool_call_id=tool_id)
            )

    # Safety: hit max_iterations without finishing — return last AI content
    for m in reversed(local_messages):
        if isinstance(m, AIMessage) and m.content:
            return m.content
    return "Analysis incomplete (max iterations reached)."
