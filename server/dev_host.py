"""
dev_host.py -- a small local MCP Apps *host*, made for developing/demoing the UI.

Real MCP Apps hosts (Claude, VS Code Copilot Chat, etc.) fetch the tool's ui://
resource, show it in a sandboxed iframe and pass messages between the iframe
and MCP. This script does the same thing with your running server, so you can
see and click the study-plan UI without any chat client or API key.

    terminal 1:  python server/server.py
    terminal 2:  python server/dev_host.py      ->  http://127.0.0.1:8080
"""

import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
UI_URI = "ui://college-admin/study-plan.html"
PORT = int(os.environ.get("DEV_HOST_PORT", "8080"))


async def _with_session(fn):
    async with streamable_http_client(MCP_URL) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await fn(s)


def mcp_call(name: str, args: dict) -> dict:
    async def go(s):
        res = await s.call_tool(name, args)
        return {"content": [c.model_dump(exclude_none=True) for c in res.content],
                "isError": bool(res.is_error)}
    return asyncio.run(_with_session(go))


def mcp_ui_html() -> str:
    async def go(s):
        rr = await s.read_resource(UI_URI)
        return rr.contents[0].text
    return asyncio.run(_with_session(go))


HOST_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>MCP Apps dev host</title>
<style>
 body{font:14px system-ui,sans-serif;max-width:760px;margin:20px auto;padding:0 14px;color:#1f2328}
 fieldset{border:1px solid #d0d7de;border-radius:8px;margin-bottom:12px}
 legend{font-weight:600;padding:0 6px} input,select,button{font:inherit;padding:4px 8px;margin:2px}
 iframe{width:100%;border:1px dashed #8b949e;border-radius:8px;min-height:120px;background:#fff}
 #log{font:12px monospace;color:#656d76;white-space:pre-wrap;max-height:140px;overflow:auto}
</style></head><body>
<h2>College Admin &mdash; MCP Apps dev host</h2>
<fieldset><legend>1. Add a task (calls add_task)</legend>
 <input id="t" placeholder="Title"> <input id="s" placeholder="Subject">
 <input id="d" type="date"> <select id="p"><option>medium</option><option>high</option><option>low</option></select>
 <button id="add">Add</button> <span id="addmsg"></span></fieldset>
<fieldset><legend>2. Call generate_study_plan (UI renders below)</legend>
 Start <input id="a" type="date"> End <input id="b" type="date"> Hours/day <input id="h" type="number" value="3" min="0.5" step="0.5" style="width:70px">
 <button id="run">Generate plan</button></fieldset>
<iframe id="app" sandbox="allow-scripts"></iframe>
<div id="log"></div>
<script>
const $=id=>document.getElementById(id), frame=$("app");
const iso=d=>d.toISOString().slice(0,10), today=new Date();
$("a").value=iso(today); $("b").value=iso(new Date(today.getTime()+7*864e5)); $("d").value=iso(new Date(today.getTime()+5*864e5));
const log=m=>{$("log").textContent+=m+"\n";$("log").scrollTop=1e9};
const api=async(name,args)=>(await fetch("/api/call",{method:"POST",body:JSON.stringify({name,arguments:args})})).json();
let ready=false, queued=null, uiHtml=null;
const post=m=>frame.contentWindow.postMessage(Object.assign({jsonrpc:"2.0"},m),"*");
const reply=(id,result)=>post({id,result});
function deliver(q){post({method:"ui/notifications/tool-input",params:{arguments:q.args}});
                    post({method:"ui/notifications/tool-result",params:q.result});log("host -> view: tool-input, tool-result")}
window.addEventListener("message",async e=>{
  if(e.source!==frame.contentWindow)return; const m=e.data; if(!m||m.jsonrpc!=="2.0")return;
  if(m.method==="ui/initialize"){log("view -> host: ui/initialize");
    reply(m.id,{protocolVersion:"2026-01-26",hostInfo:{name:"dev-host",version:"0.1"},hostCapabilities:{serverTools:{}},
      hostContext:{theme:matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light",displayMode:"inline"}});}
  else if(m.method==="ui/notifications/initialized"){log("view -> host: initialized");ready=true;if(queued){deliver(queued);queued=null}}
  else if(m.method==="tools/call"){log("view -> host: tools/call "+m.params.name);reply(m.id,await api(m.params.name,m.params.arguments))}
  else if(m.method==="ui/open-link"){log("view -> host: open-link "+m.params.url);
    if(/^https?:\/\//.test(m.params.url)){window.open(m.params.url,"_blank","noopener");reply(m.id,{})}
    else post({id:m.id,error:{code:-32602,message:"only http(s) links are allowed"}})}
  else if(m.method==="ui/notifications/size-changed"){frame.style.height=Math.max(120,m.params.height+4)+"px"}
});
$("add").onclick=async()=>{const r=await api("add_task",{title:$("t").value,subject:$("s").value,due_date:$("d").value,priority:$("p").value});
  $("addmsg").textContent=JSON.parse(r.content[0].text).ok?"added \u2713":"error: "+JSON.parse(r.content[0].text).error};
$("run").onclick=async()=>{
  if(!uiHtml)uiHtml=await (await fetch("/api/ui")).text();
  const args={start_date:$("a").value,end_date:$("b").value,hours_per_day:Number($("h").value)};
  log("host: calling generate_study_plan, fetching ui:// resource");
  const result=await api("generate_study_plan",args);
  ready=false; queued={args,result}; frame.srcdoc=uiHtml;   // new iframe each time, so handshake happens fresh
};
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path == "/":
                self._send(200, HOST_PAGE, "text/html; charset=utf-8")
            elif self.path == "/api/ui":
                self._send(200, mcp_ui_html(), "text/html; charset=utf-8")
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:
            self._send(502, f"MCP server unreachable ({e!r}). Is server.py running?", "text/plain")

    def do_POST(self):
        if self.path != "/api/call":
            return self._send(404, "not found", "text/plain")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            out = mcp_call(body["name"], body.get("arguments") or {})
            self._send(200, json.dumps(out), "application/json")
        except Exception as e:
            self._send(200, json.dumps({"isError": True, "content": [
                {"type": "text", "text": json.dumps({"ok": False, "error": repr(e)})}]}), "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Dev host on http://127.0.0.1:{PORT}  (MCP server: {MCP_URL})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
