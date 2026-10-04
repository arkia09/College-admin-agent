"""
web_app.py -- web chat for the College Admin Agent (it is also an MCP Apps host).

You type to the Gemini agent in the browser. Tool calls go to the MCP server, and
when a tool is linked to a ui:// resource (generate_study_plan), the interactive
plan is shown inline in the chat and it can call the tools back through this host.

    terminal 1:  python server/server.py
    terminal 2:  export GEMINI_API_KEY=...; python server/web_app.py
    open         http://127.0.0.1:8081
Single-user demo only: one shared conversation, kept in memory.
(Opening http://127.0.0.1:8081/?prompt=something fills that text in the input box.)
"""

import asyncio
import json
import os
import threading
from datetime import date

from google import genai
from google.genai import types as gtypes

from agent import GEMINI_MODEL, MAX_TOOL_ROUNDS, SYSTEM_INSTRUCTION, mcp_tool_to_gemini
import dev_host
from dev_host import _with_session, mcp_call
from http.server import ThreadingHTTPServer

PORT = int(os.environ.get("WEB_PORT", "8081"))
# where dev_host.py (the standalone MCP App page) is running, used by the header button
PLAN_APP_URL = os.environ.get("PLAN_APP_URL", "http://127.0.0.1:8080").rstrip("/")
LOCK = threading.Lock()
STATE: dict = {}


def _init() -> None:
    if STATE:
        return
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set (https://aistudio.google.com/apikey)")

    async def list_tools(s):
        return (await s.list_tools()).tools

    tools = asyncio.run(_with_session(list_tools))
    today = date.today()
    STATE.update(
        client=genai.Client(api_key=key),
        ui={t.name for t in tools if ((t.meta or {}).get("ui") or {}).get("resourceUri")},
        config=gtypes.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION.format(
                today=today.isoformat(), weekday=today.strftime("%A")),
            tools=[gtypes.Tool(function_declarations=[mcp_tool_to_gemini(t) for t in tools])],
        ),
        history=[],
    )


def run_turn(text: str) -> dict:
    """One user message -> Gemini + tool loop -> {reply, events}."""
    with LOCK:
        _init()
        hist = STATE["history"]
        start = len(hist)
        hist.append(gtypes.Content(role="user", parts=[gtypes.Part.from_text(text=text)]))
        events = []
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                resp = STATE["client"].models.generate_content(
                    model=GEMINI_MODEL, contents=hist, config=STATE["config"])
                cand = resp.candidates[0] if resp.candidates else None
                if cand is None or cand.content is None or not cand.content.parts:
                    raise RuntimeError("empty response from the model")
                hist.append(cand.content)
                calls = [p.function_call for p in cand.content.parts if p.function_call is not None]
                if not calls:
                    return {"reply": resp.text or "", "events": events}
                parts = []
                for fc in calls:
                    args = dict(fc.args or {})
                    res = mcp_call(fc.name, args)
                    out = "".join(c.get("text", "") for c in res["content"])
                    parts.append(gtypes.Part.from_function_response(
                        name=fc.name, response={("error" if res["isError"] else "result"): out}))
                    events.append({"name": fc.name, "args": args, "result": res,
                                   "ui": fc.name in STATE["ui"]})
                hist.append(gtypes.Content(role="user", parts=parts))
            return {"reply": "(stopped after too many tool calls in a row)", "events": events}
        except Exception:
            del hist[start:]  # half-finished turn should not stay in the history
            raise


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>College Admin Agent</title>
<style>
 :root{--bg:#fff;--fg:#1f2328;--mut:#656d76;--card:#f6f8fa;--bd:#d0d7de;--acc:#2563eb}
 @media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--card:#161b22;--bd:#30363d;--acc:#58a6ff}}
 *{box-sizing:border-box} html,body{height:100%;margin:0}
 body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;display:flex;flex-direction:column;max-width:820px;margin:auto}
 header{padding:12px 16px;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center}
 header b{font-size:16px} header a{font-size:13px;text-decoration:none;color:var(--acc);border:1px solid var(--acc);border-radius:8px;padding:6px 12px}
 header .right{display:flex;gap:8px;align-items:center} button{font:inherit;cursor:pointer;border:1px solid var(--bd);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 12px}
 #msgs{flex:1;overflow:auto;padding:14px 16px;display:flex;flex-direction:column;gap:10px}
 .m{max-width:88%;padding:8px 12px;border-radius:12px;white-space:pre-wrap}
 .me{align-self:flex-end;background:var(--acc);color:#fff} .bot{align-self:flex-start;background:var(--card);border:1px solid var(--bd)}
 .tool{align-self:flex-start;font:12px monospace;color:var(--mut)} .err{align-self:flex-start;color:#cf222e}
 iframe{width:100%;border:1px solid var(--bd);border-radius:10px;min-height:120px;background:var(--bg);color-scheme:normal}
 form{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--bd)}
 input{flex:1;font:inherit;padding:9px 12px;border-radius:8px;border:1px solid var(--bd);background:var(--bg);color:var(--fg)}
 .chips{display:flex;gap:6px;flex-wrap:wrap}.chips button{font-size:13px;color:var(--mut)}
</style></head><body>
<header><b>College Admin Agent</b><div class="right">
 <a href="__PLAN_APP_URL__" target="_blank" rel="noopener" title="Opens the standalone study plan app">Generate your own study plan</a>
 <button id="reset">New chat</button></div></header>
<div id="msgs"><div class="m bot">Hi! Tell me about your assignments and I'll track them and plan your study time.
<div class="chips" style="margin-top:8px"></div></div></div>
<form id="f"><input id="in" placeholder="e.g. I have an OS lab due next Friday, plan my week at 3h/day" autocomplete="off" autofocus><button>Send</button></form>
<script>
const $=id=>document.getElementById(id), msgs=$("msgs"); let uiHtml=null, busy=false;
const api=async(n,a)=>(await fetch("/api/call",{method:"POST",body:JSON.stringify({name:n,arguments:a})})).json();
function add(cls,text){const d=document.createElement("div");d.className="m "+cls;d.textContent=text;msgs.appendChild(d);msgs.scrollTop=1e9;return d}
// One single message listener for all the plan iframes. Earlier I was adding a new
// listener on window for every iframe and never removing it, which leaks.
const apps=[];
window.addEventListener("message",async ev=>{
  const a=apps.find(x=>x.f.contentWindow===ev.source); if(!a)return;
  const m=ev.data; if(!m||m.jsonrpc!=="2.0")return;
  const post=x=>a.f.contentWindow.postMessage(Object.assign({jsonrpc:"2.0"},x),"*");
  if(m.method==="ui/initialize")post({id:m.id,result:{protocolVersion:"2026-01-26",hostInfo:{name:"college-admin-web",version:"0.1"},hostCapabilities:{serverTools:{}},
    hostContext:{theme:matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light",displayMode:"inline"}}});
  else if(m.method==="ui/notifications/initialized"){post({method:"ui/notifications/tool-input",params:{arguments:a.e.args}});post({method:"ui/notifications/tool-result",params:a.e.result})}
  else if(m.method==="tools/call")post({id:m.id,result:await api(m.params.name,m.params.arguments)});
  else if(m.method==="ui/open-link"){
    if(/^https?:\/\//.test(m.params.url)){window.open(m.params.url,"_blank","noopener");post({id:m.id,result:{}})}
    else post({id:m.id,error:{code:-32602,message:"only http(s) links are allowed"}})}
  else if(m.method==="ui/notifications/size-changed"){a.f.style.height=Math.max(120,m.params.height+4)+"px";msgs.scrollTop=1e9}
});
async function mountApp(e){
  uiHtml=uiHtml||await (await fetch("/api/ui")).text();
  const f=document.createElement("iframe"); f.setAttribute("sandbox","allow-scripts"); msgs.appendChild(f);
  apps.push({f,e});
  f.srcdoc=uiHtml;
}
async function send(text){
  if(busy||!text.trim())return; busy=true; add("me",text); const w=add("bot","\u2026");
  try{
    const r=await (await fetch("/api/chat",{method:"POST",body:JSON.stringify({message:text})})).json(); w.remove();
    if(r.error){add("err",r.error)} else {
      r.events.forEach(e=>add("tool","\u2699 "+e.name+"("+JSON.stringify(e.args)+")"));
      if(r.reply)add("bot",r.reply);
      for(const e of r.events) if(e.ui) await mountApp(e);
    }
  }catch(err){w.remove();add("err",String(err))}
  busy=false;
}
$("f").onsubmit=ev=>{ev.preventDefault();const t=$("in").value;$("in").value="";send(t)};
$("reset").onclick=async()=>{await fetch("/api/reset",{method:"POST"});apps.length=0;msgs.querySelectorAll(":scope>:not(:first-child)").forEach(n=>n.remove())};
// coming from the MCP App's "Ask agent" button? then the prompt comes in the url, just fill the box
const pre=new URLSearchParams(location.search).get("prompt"); if(pre){$("in").value=pre;$("in").focus()}
["Add an OS lab due next Friday (high priority)","What's pending?","Plan my next 7 days at 3 hours a day"].forEach(t=>{
  const b=document.createElement("button");b.type="button";b.textContent=t;b.onclick=()=>send(t);document.querySelector(".chips").appendChild(b)});
</script></body></html>"""


class Handler(dev_host.Handler):
    def do_GET(self):
        # ignore the ?query part so that /?prompt=... also opens the page
        if self.path.split("?")[0] == "/":
            return self._send(200, PAGE.replace("__PLAN_APP_URL__", PLAN_APP_URL),
                              "text/html; charset=utf-8")
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/reset":
            STATE.get("history", []).clear()
            return self._send(200, "{}", "application/json")
        if self.path == "/api/chat":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                out = run_turn(body["message"])
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"}
            return self._send(200, json.dumps(out), "application/json")
        super().do_POST()


if __name__ == "__main__":
    print(f"College Admin chat on http://127.0.0.1:{PORT}  (MCP server: {dev_host.MCP_URL}, model: {GEMINI_MODEL})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
