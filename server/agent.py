"""
agent.py
The "brain" of College Admin Agent. It connects to our own MCP server
(server.py) as a proper MCP client, finds out which tools are there, gives them
to Gemini as function declarations, and then runs a tool-calling loop:

    user message -> Gemini picks a tool call -> we run it on the MCP server
    -> send the result back to Gemini -> repeat till Gemini gives final text

Before running:
    1. server.py should already be running in another terminal:
           python server/server.py
       (MCP endpoint will be http://127.0.0.1:8000/mcp)
    2. Set a free Gemini API key as environment variable:
           export GEMINI_API_KEY="your-key-here"
       You can get one from https://aistudio.google.com/apikey

Then run:
    python server/agent.py
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

# About the model: gemini-2.5-flash was giving 404 for new API users, so I switched.
# The default below worked for me on the free tier. Model names keep changing, so if
# you get a 404 just set GEMINI_MODEL to something else, list is here:
# https://ai.google.dev/gemini-api/docs/models
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

SYSTEM_INSTRUCTION = """Today's date is {today} ({weekday}). Use it to resolve phrases \
like "tomorrow" or "next week" into ISO dates. You are a college admin assistant that helps a student track \
assignments and plan study time. You have tools to add tasks, list tasks, \
mark tasks done, and generate a day-wise study plan. Always use ISO dates \
(YYYY-MM-DD) when calling tools. When a task's due date isn't given \
explicitly, ask the student rather than guessing it. After using tools, \
summarize the result for the student in plain, friendly language -- don't \
just dump raw JSON at them. If a tool returns ok=false, explain the problem \
and fix it (or ask the student) instead of pretending it worked."""

MAX_TOOL_ROUNDS = 6  # safety limit, so a confused model cannot keep looping forever


def mcp_tool_to_gemini(tool) -> gtypes.FunctionDeclaration:
    """Convert an MCP tool (from tools/list) into a Gemini FunctionDeclaration.
    Gemini takes the raw JSON schema directly through parameters_json_schema,
    so no manual conversion is needed. Whatever server.py declares (it comes
    from our Python type hints) is exactly what Gemini sees."""
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
    connected = False  # to know later whether the error came before or after connecting
    try:
        async with streamable_http_client(MCP_SERVER_URL) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                connected = True

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

                    turn_start = len(history) - 1  # remember this, to roll back if something fails
                    for _ in range(MAX_TOOL_ROUNDS):
                        try:
                            response = await client.aio.models.generate_content(
                                model=GEMINI_MODEL,
                                contents=history,
                                config=config,
                            )
                        except Exception as e:  # wrong key, quota over, model retired, etc.
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

                        # run every tool call that Gemini asked for, on the real MCP server
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
    except Exception as e:
        # anyio wraps errors in an ExceptionGroup, but a normal exception has no
        # .exceptions attribute, so use getattr (earlier this line itself used to crash)
        details = "; ".join(repr(x) for x in getattr(e, "exceptions", [e]))
        if connected:
            print(f"\nLost the MCP connection while chatting: {details}")
        else:
            print(f"\nFailed to connect to MCP server at {MCP_SERVER_URL}.")
            print("Is server.py running in another terminal? Start it with: python server/server.py")
            print(f"Details: {details}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_agent())
