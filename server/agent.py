"""
agent.py
The "brain" of the College Admin Agent. Connects to our own MCP server
(server.py) as a real MCP client, discovers its tools, hands them to
Gemini as function declarations, and runs a tool-calling loop:

    user message -> Gemini decides a tool call -> we execute it against
    the MCP server -> feed the result back -> repeat until Gemini gives
    a final text answer.

Prerequisites:
    1. server.py must be running separately, in another terminal:
           python server.py
       (it serves the MCP endpoint at http://127.0.0.1:8000/mcp)
    2. Set an environment variable with a free Gemini API key:
           export GEMINI_API_KEY="your-key-here"
       Get one free at https://aistudio.google.com/apikey

Run with:
    python agent.py
"""

import asyncio
import os
import sys
from datetime import date

from google import genai
from google.genai import types as gtypes

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")

# NOTE on model choice: as of writing, Google's free tier reliably covers
# the Gemini 2.5 line (gemini-2.5-flash / gemini-2.5-flash-lite). Some
# reports say Gemini 2.5 models may be retired around October 16, 2026 --
# if that happens before your demo, check https://aistudio.google.com for
# current free-tier model availability and either set the GEMINI_MODEL
# env var or edit the default below. gemini-2.5-flash-lite is the
# higher-rate-limit free option if you hit rate limits during testing.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_INSTRUCTION = """Today's date is {today} ({weekday}). Use it to resolve phrases \
like "tomorrow" or "next week" into ISO dates. You are a college admin assistant that helps a student track \
assignments and plan study time. You have tools to add tasks, list tasks, \
mark tasks done, and generate a day-wise study plan. Always use ISO dates \
(YYYY-MM-DD) when calling tools. When a task's due date isn't given \
explicitly, ask the student rather than guessing it. After using tools, \
summarize the result for the student in plain, friendly language -- don't \
just dump raw JSON at them. If a tool returns ok=false, explain the problem \
and fix it (or ask the student) instead of pretending it worked."""

MAX_TOOL_ROUNDS = 6  # safety cap so a confused model can't loop forever


def mcp_tool_to_gemini(tool) -> gtypes.FunctionDeclaration:
    """Convert an MCP Tool (from tools/list) into a Gemini FunctionDeclaration.
    Gemini accepts a raw JSON schema directly via parameters_json_schema, so
    no manual schema translation is needed -- whatever server.py declares
    (derived automatically from our Python type hints) is what Gemini sees."""
    return gtypes.FunctionDeclaration(
        name=tool.name,
        description=tool.description or "",
        parameters_json_schema=tool.input_schema,
    )


async def run_agent():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "ERROR: GEMINI_API_KEY is not set.\n"
            "Get a free key at https://aistudio.google.com/apikey and run:\n"
            '    export GEMINI_API_KEY="your-key-here"',
            file=sys.stderr,
        )
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    print(f"Connecting to MCP server at {MCP_SERVER_URL} ...")
    try:
        async with streamable_http_client(MCP_SERVER_URL) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                tools_result = await session.list_tools()
                mcp_tools = tools_result.tools
                print(
                    f"Connected. Discovered {len(mcp_tools)} tools: "
                    f"{', '.join(t.name for t in mcp_tools)}"
                )

                gemini_tool = gtypes.Tool(
                    function_declarations=[mcp_tool_to_gemini(t) for t in mcp_tools]
                )
                today = date.today()
                config = gtypes.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION.format(
                        today=today.isoformat(), weekday=today.strftime("%A")
                    ),
                    tools=[gemini_tool],
                )

                history: list[gtypes.Content] = []

                print("\nCollege Admin Agent ready. Type 'quit' to exit.\n")
                while True:
                    try:
                        user_input = input("You: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if not user_input:
                        continue
                    if user_input.lower() in {"quit", "exit"}:
                        break

                    history.append(
                        gtypes.Content(
                            role="user",
                            parts=[gtypes.Part.from_text(text=user_input)],
                        )
                    )

                    turn_start = len(history) - 1  # so we can roll back on failure
                    for _ in range(MAX_TOOL_ROUNDS):
                        try:
                            response = await client.aio.models.generate_content(
                                model=GEMINI_MODEL,
                                contents=history,
                                config=config,
                            )
                        except Exception as e:  # bad key, quota, retired model...
                            print(f"Agent: Gemini API error ({GEMINI_MODEL}): {e}\n"
                                  "       (check GEMINI_API_KEY / GEMINI_MODEL)\n")
                            del history[turn_start:]
                            break

                        candidate = response.candidates[0] if response.candidates else None
                        if candidate is None or candidate.content is None or not candidate.content.parts:
                            reason = candidate.finish_reason if candidate else "no candidates"
                            print(f"Agent: (empty response from model: {reason})\n")
                            del history[turn_start:]
                            break
                        history.append(candidate.content)

                        function_calls = [
                            part.function_call
                            for part in candidate.content.parts
                            if part.function_call is not None
                        ]

                        if not function_calls:
                            text = response.text or "(no response text)"
                            print(f"Agent: {text}\n")
                            break

                        # Execute every requested tool call against the real MCP server.
                        response_parts = []
                        for fc in function_calls:
                            args = dict(fc.args or {})
                            print(f"  [calling tool: {fc.name}({args})]")
                            try:
                                result = await session.call_tool(fc.name, args)
                                result_text = "".join(
                                    block.text
                                    for block in result.content
                                    if hasattr(block, "text")
                                )
                                key = "error" if result.is_error else "result"
                                payload = {key: result_text}
                            except Exception as e:
                                payload = {"error": str(e)}

                            response_parts.append(
                                gtypes.Part.from_function_response(
                                    name=fc.name, response=payload
                                )
                            )

                        history.append(gtypes.Content(role="user", parts=response_parts))
                    else:
                        print(
                            "Agent: (stopped after too many tool calls in a row -- "
                            "something may be looping)\n"
                        )
    except Exception as eg:
        print(f"\nFailed to connect to MCP server at {MCP_SERVER_URL}.")
        print("Is server.py running in another terminal? Start it with: python server.py")
        print(f"Details: {eg.exceptions}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_agent())
