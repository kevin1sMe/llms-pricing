import asyncio
import shutil
import os
from dotenv import load_dotenv
from agents.mcp import MCPServer, MCPServerStdio

from openai import AsyncOpenAI

from agents import (
    Agent,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)

# 加载.env文件中的环境变量
load_dotenv()

BASE_URL = os.getenv("EXAMPLE_BASE_URL") or ""
API_KEY = os.getenv("EXAMPLE_API_KEY") or ""
MODEL_NAME = os.getenv("EXAMPLE_MODEL_NAME") or ""

if not BASE_URL or not API_KEY or not MODEL_NAME:
    raise ValueError(
        "Please set EXAMPLE_BASE_URL, EXAMPLE_API_KEY, EXAMPLE_MODEL_NAME via env var or code."
    )
client = AsyncOpenAI(
    base_url=BASE_URL,
    api_key=API_KEY,
)
set_default_openai_client(client=client, use_for_tracing=False)
set_default_openai_api("chat_completions")
set_tracing_disabled(disabled=True)



async def run(mcp_server: MCPServer, url: str):
    agent = Agent(
        name="Assistant",
        instructions=f"你是一个专业的数据分析师，现在需要你分析一个网页，并整理出网页中的数据，以markdown格式输出",
        mcp_servers=[mcp_server],
        model=MODEL_NAME,
    )

    message = f"请从以下网页中获得数据，并根据各个模型参数以及价格整理出一个表格： {url}"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)


async def main():
    url = "https://www.volcengine.com/docs/82379/1544106" 
    
    # 从环境变量获取FIRECRAWL_API_KEY
    firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
    if not firecrawl_api_key:
        raise ValueError("请设置FIRECRAWL_API_KEY环境变量")

    async with MCPServerStdio(
        cache_tools_list=True,  # 缓存工具列表，用于演示
        params={
            "command": "npx", 
            "args": ["-y", "firecrawl-mcp"],
            "env": {
                "FIRECRAWL_API_KEY": firecrawl_api_key
            }
        },
        client_session_timeout_seconds=60,
    ) as server:
        with trace(workflow_name="Firecrawl Example"):
            await run(server, url)


if __name__ == "__main__":
    if not shutil.which("npx"):
        raise RuntimeError("npx is not installed. Please install it with `npm install -g npx`.")

    asyncio.run(main())
