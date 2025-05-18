import asyncio
import shutil
import os
import re
import unicodedata
import glob
import json
from dotenv import load_dotenv
from agents.mcp import MCPServer, MCPServerStdio
from datetime import datetime
from pydantic import BaseModel

# from openai import AsyncOpenAI
from langfuse.openai import AsyncOpenAI

from agents import (
    Agent,
    Runner,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
    trace,
    function_tool,
    handoff,
    HandoffInputData,
    RunContextWrapper
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.extensions import handoff_filters

# 加载.env文件中的环境变量
load_dotenv(override=True)

# Agent配置 - 控制启用哪些agent
AGENT_CONFIG = {
    "parser_agent": False,      # 解析提供商列表的agent
    "provider_agent": False,    # 处理单个提供商的agent
    "summary_agent": True,     # 汇总结果的agent
    "notion_agent": True       # 更新Notion的agent
}

# 每次运行时重新获取环境变量
BASE_URL = os.getenv("EXAMPLE_BASE_URL") or ""
API_KEY = os.getenv("EXAMPLE_API_KEY") or ""
MODEL_NAME = os.getenv("EXAMPLE_MODEL_NAME") or ""

if not BASE_URL or not API_KEY or not MODEL_NAME:
    raise ValueError(
        "Please set EXAMPLE_BASE_URL, EXAMPLE_API_KEY, EXAMPLE_MODEL_NAME via env var or code."
    )

# 每次运行时重新创建客户端
client = AsyncOpenAI(
    base_url=BASE_URL,
    api_key=API_KEY,
)
set_default_openai_client(client=client, use_for_tracing=False)
set_default_openai_api("chat_completions")
set_tracing_disabled(disabled=True)


# def sanitize_text(text):
#     """
#     清理文本中的特殊字符和控制字符
    
#     参数:
#         text: 需要清理的文本
        
#     返回:
#         清理后的文本
#     """
#     if not isinstance(text, str):
#         text = str(text)
    
#     # 替换可能导致问题的控制字符
#     result = ""
#     for char in text:
#         # 获取字符类别
#         category = unicodedata.category(char)
        
#         # 如果是控制字符或特殊格式字符，替换为普通字符
#         if category.startswith('C') or category == 'Cf':  # C是控制字符，Cf是格式字符
#             if char == '\n' or char == '\t' or char == '\r':  # 保留这些常见控制字符
#                 result += char
#             else:
#                 # 替换为空格或适当的可见字符
#                 result += ''
#         else:
#             result += char
    
#     # 替换已知可能导致问题的特殊字符序列
#     result = result.replace('¥', 'CNY')  # 替换人民币符号
    
#     # 替换markdown表格中的价格前的特殊标记符号
#     result = re.sub(r'[\x00-\x1F](\d+\.?\d*)', r'\1', result)  # 移除数字前的控制字符
    
#     return result


@function_tool
def write_to_file(file_path: str, content: str):
    """
    将内容写入本地文件
    
    参数:
        file_path: 文件路径
        content: 要写入的内容
    
    返回:
        写入结果信息
    """
    try:
        # 确保目录存在
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        
        # 确保content是字符串类型并清理特殊字符
        # content = sanitize_text(content)
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"成功写入文件: {file_path}"
    except Exception as e:
        return f"写入文件失败: {str(e)}"


@function_tool
def current_time():
    """
    获取当前时间
    
    返回:
        当前时间字符串
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 创建一个不带装饰器的内部函数，用于直接调用
def _parse_provider_list(content: str):
    """
    解析输入的提供商列表
    
    参数:
        content: 包含提供商和URL的文本内容
        
    返回:
        解析后的提供商和URL列表
    """
    providers = []
    lines = content.strip().split('\n')
    
    current_provider = None
    current_url = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 匹配提供商行（以##开头）
        if line.startswith('##'):
            # 如果已有前一个提供商，则添加到列表
            if current_provider and current_url:
                providers.append({
                    'name': current_provider,
                    'url': current_url
                })
                
            # 提取新的提供商名称
            current_provider = line.lstrip('#').strip()
            current_url = None
        # 匹配URL行
        elif current_provider and ('http://' in line or 'https://' in line):
            # 提取URL
            match = re.search(r'(https?://\S+)', line)
            if match:
                current_url = match.group(1)
    
    # 添加最后一个提供商
    if current_provider and current_url:
        providers.append({
            'name': current_provider,
            'url': current_url
        })
    
    return providers


@function_tool
def parse_provider_list(content: str):
    """
    解析输入的提供商列表
    
    参数:
        content: 包含提供商和URL的文本内容
        
    返回:
        解析后的提供商和URL列表
    """
    return _parse_provider_list(content)


async def run_single_provider(mcp_server: MCPServer, provider: dict):
    """处理单个提供商的数据"""
    if not AGENT_CONFIG.get("provider_agent", True):
        print(f"跳过提供商处理: {provider['name']} (provider_agent已禁用)")
        return f"provider_agent已禁用，已跳过{provider['name']}"
        
    provider_name = provider['name']
    url = provider['url']
    output_file = f"results/{provider_name.strip()}.md"
    
    agent = Agent(
        name="Provider Agent",
        instructions=f"""你是一个专业的数据分析师，现在需要你分析一个网页，并整理出网页中的数据，以markdown格式输出。
你分析的是{provider_name}提供的模型价格信息，请提取所有模型的参数和价格信息，整理成表格。
你可以将结果保存到本地文件中。

重要规则：
1. 请确保你生成的是纯文本格式的markdown
2. 不要使用任何特殊字符或Unicode控制字符
3. 对于货币符号，请根据实际使用"CNY"或"USD"等纯文本描述，不要使用符号
4. 所有数字前后不要添加任何控制字符或特殊格式
""",
        mcp_servers=[mcp_server],
        model=MODEL_NAME,
        tools=[write_to_file, current_time],
    )

    message = f"""请从以下{provider_name}的网页中获得数据，并根据各个模型参数以及价格整理出一个表格，然后将结果保存为'{output_file}'文件： {url}

在结果文件中，请写上本次刷新的当前时间，格式形如：2024-05-18 10:00:00

为了保证文件格式正确，请遵循以下规则：
1. 使用纯ASCII字符和基本UTF-8文本
2. 不要使用特殊的Unicode控制字符或格式字符
3. 对于货币符号，请根据实际使用"CNY"或"USD"等纯文本描述，不要使用符号
4. 所有数字前后不要添加任何控制字符或特殊格式
"""
    
    print(f"处理提供商: {provider_name}")
    print(f"URL: {url}")
    
    result = await Runner.run(starting_agent=agent, input=message)
    print(f"处理完成: {provider_name}")
    print("-" * 50)
    
    return result.final_output


async def run_parser_agent(providers_text: str):
    """运行解析提供商列表的agent"""
    if not AGENT_CONFIG.get("parser_agent", True):
        print("跳过提供商列表解析 (parser_agent已禁用)")
        return _parse_provider_list(providers_text)
        
    agent = Agent(
        name="Parser Agent",
        instructions="""你是一个帮助解析文本内容的助手。你需要从提供的文本中识别出模型提供商名称和对应的URL。
你的任务是：
1. 接收包含提供商信息的文本
2. 识别出每个提供商的名称和URL
3. 返回结构化的提供商列表数据

重要规则：
1. 你必须记录开始和完成时间
2. 你必须报告解析到的提供商数量
3. 如果解析失败，必须提供详细的错误信息
4. 在开始任务时，必须输出：'[Parser Agent] 开始解析提供商列表'
5. 在完成任务时，必须输出：'[Parser Agent] 解析完成，共找到 X 个提供商'
6. 你必须使用parse_provider_list工具来解析文本
7. 你必须返回解析后的结果，格式为JSON字符串""",
        model=MODEL_NAME,
        tools=[parse_provider_list, current_time],
    )

    message = f"请解析以下文本，提取出所有的模型提供商和它们的URL:\n\n{providers_text}"
    result = await Runner.run(starting_agent=agent, input=message)
    
    # 期望agent会调用parse_provider_list工具并返回结果
    print("提供商解析完成")
    return result.final_output

@function_tool
def read_from_file(file_path: str):
    """
    从本地文件读取内容
    
    参数:
        file_path: 文件路径
    
    返回:
        文件内容
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        return f"读取文件失败: {str(e)}"


@function_tool
def list_files_in_directory(directory: str, pattern: str = "*"):
    """
    列出目录中匹配模式的所有文件
    
    参数:
        directory: 目录路径
        pattern: 文件匹配模式
    
    返回:
        文件列表
    """
    try:
        file_path = os.path.join(directory, pattern)
        files = glob.glob(file_path)
        return sorted(files)
    except Exception as e:
        return f"列出文件失败: {str(e)}"


async def run_summary_agent():
    """运行汇总agent，将所有结果整合为一个大表格"""
    if not AGENT_CONFIG.get("summary_agent", True):
        print("跳过结果汇总 (summary_agent已禁用)")
        return "summary_agent已禁用"
        
    agent = Agent(
        name="Summary Agent",
        instructions="""你是一个数据汇总专家，负责将多个文件中的表格数据整合为一个大表格。
规则：
1. 读取results目录下的所有markdown文件
2. 从每个文件中提取表格数据
3. 将所有数据整合为一个大表格
4. 添加一个"提供商"列，标识数据来源
5. 保持原始价格格式，不需要转换货币
6. 生成的表格应包含：提供商、模型名称、输入价格、输出价格、备注等信息
7. 如果某列信息不存在，使用空格填充
8. 在结果开头添加当前时间作为刷新时间
""",
        model=MODEL_NAME,
        tools=[read_from_file, list_files_in_directory, write_to_file, current_time],
    )

    message = """请汇总results目录下的所有markdown文件，生成一个大表格，包含所有提供商的模型价格信息。
格式如下：
```
# 大模型提供商价格汇总

* 刷新于{当前时间}，未来将会定期自动刷新，如有需求可关注。

| 提供商 | 模型名称 | 输入价格 | 输出价格 | 备注 |
| --- | --- | --- | --- | --- |
| OpenAI | gpt-4.1 | $2.00 / 1M tokens | $8.00 / 1M tokens |  |
...
```

请将结果保存到"summary.md"文件中。
"""
    
    print("开始生成汇总表格...")
    result = await Runner.run(starting_agent=agent, input=message)
    print("汇总表格生成完成")
    
    return result.final_output


async def run_notion_update_agent(summary_file_path: str):
    """运行更新Notion的agent，将汇总表格更新到Notion页面"""
    if not AGENT_CONFIG.get("notion_agent", True):
        print("跳过Notion更新 (notion_agent已禁用)")
        return "notion_agent已禁用"
        
    # 获取Notion API密钥
    notion_api_key = os.getenv("NOTION_API_KEY")
    if not notion_api_key:
        print("未设置NOTION_API_KEY环境变量，跳过Notion更新")
        return "未设置NOTION_API_KEY环境变量，跳过Notion更新"

    # 配置Notion MCP Server
    async with MCPServerStdio(
        cache_tools_list=True,
        params={
            "command": "npx", 
            "args": ["-y", "@notionhq/notion-mcp-server"],
            "env": {
                "OPENAPI_MCP_HEADERS": json.dumps({
                    "Authorization": f"Bearer {notion_api_key}",
                    "Notion-Version": "2022-06-28"
                })
            }
        },
        client_session_timeout_seconds=60,
    ) as notion_server:
        
        agent = Agent(
            name="Notion Agent",
            instructions="""你是一个Notion数据更新专家，负责将Markdown格式的表格数据更新到Notion页面中。
规则：
1. 读取指定的Markdown文件
2. 解析其中的表格数据
3. 将数据转换为Notion的Simple Table格式
4. 更新到指定的Notion页面中
5. 保持表格的格式和内容不变
6. 如果Notion页面中已有表格，先删除原表格再创建新表格
""",
            # model=MODEL_NAME,
            model='openai/azure/gpt-4.1-mini',
            # tools=[read_from_file],
            mcp_servers=[notion_server],
        )

        # 读取汇总文件内容
        try:
            with open(summary_file_path, "r", encoding="utf-8") as f:
                summary_content = f.read()
        except Exception as e:
            print(f"读取汇总文件失败: {str(e)}")
            return f"读取汇总文件失败: {str(e)}"

        # 定义Notion页面ID，可以从环境变量获取或硬编码
        notion_page_id = os.getenv("NOTION_PAGE_ID", "your-notion-page-id-here")
        
        message = f"""请将以下Markdown表格数据更新到Notion页面。
Notion页面ID: {notion_page_id}

Markdown内容:
{summary_content}

请按照以下步骤操作：
1. 获取当前页面的blocks
2. 清除页面中已有的表格（如果存在）
3. 将Markdown表格转换为Notion的Simple Table格式
4. 更新到Notion页面中
5. 确保保留表格的标题和其他说明文字
"""
        
        print("开始更新Notion页面...")
        print(message)
        result = await Runner.run(starting_agent=agent, input=message)
        print(result.final_output)
        return result.final_output


def update_agent_config_from_env():
    """从环境变量更新Agent配置"""
    for agent_name in AGENT_CONFIG.keys():
        env_name = f"ENABLE_{agent_name.upper()}"
        env_value = os.getenv(env_name)
        if env_value is not None:
            # 将字符串转换为布尔值
            enabled = env_value.lower() in ('true', '1', 't', 'y', 'yes')
            AGENT_CONFIG[agent_name] = enabled
            print(f"从环境变量设置 {agent_name}: {enabled}")


# 首先定义数据模型
class ProviderData(BaseModel):
    """单个提供商数据"""
    name: str
    url: str

class ProviderListData(BaseModel):
    """提供商列表数据"""
    providers: list[ProviderData]
    firecrawl_api_key: str

class SummaryData(BaseModel):
    """汇总数据"""
    summary_file: str = "summary.md"

class NotionData(BaseModel):
    """Notion更新数据"""
    page_id: str
    notion_api_key: str

# 创建并初始化MCP Servers
async def create_mcp_servers():
    """创建所有需要的MCP Servers"""
    servers = {}
    
    # 创建Firecrawl MCP Server
    if AGENT_CONFIG.get("provider_agent", True):
        firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        if firecrawl_api_key:
            try:
                servers["firecrawl"] = await MCPServerStdio(
                    cache_tools_list=True,
                    params={
                        "command": "npx", 
                        "args": ["-y", "firecrawl-mcp"],
                        "env": {
                            "FIRECRAWL_API_KEY": firecrawl_api_key
                        }
                    },
                    client_session_timeout_seconds=60,
                ).__aenter__()
            except Exception as e:
                print(f"创建 Firecrawl MCP Server 失败: {str(e)}")
    
    # 创建Notion MCP Server
    if AGENT_CONFIG.get("notion_agent", True):
        notion_api_key = os.getenv("NOTION_API_KEY")
        if notion_api_key:
            try:
                servers["notion"] = await MCPServerStdio(
                    cache_tools_list=True,
                    params={
                        "command": "npx", 
                        "args": ["-y", "@notionhq/notion-mcp-server"],
                        "env": {
                            "OPENAPI_MCP_HEADERS": json.dumps({
                                "Authorization": f"Bearer {notion_api_key}",
                                "Notion-Version": "2022-06-28"
                            })
                        }
                    },
                    client_session_timeout_seconds=60,
                ).__aenter__()
            except Exception as e:
                print(f"创建 Notion MCP Server 失败: {str(e)}")
    
    return servers

# 创建Parser Agent
def create_parser_agent():
    return Agent(
        name="Parser Agent",
        instructions="""你是一个帮助解析文本内容的助手。你需要从提供的文本中识别出模型提供商名称和对应的URL。
你的任务是：
1. 接收包含提供商信息的文本
2. 识别出每个提供商的名称和URL
3. 返回结构化的提供商列表数据

重要规则：
1. 你必须记录开始和完成时间
2. 你必须报告解析到的提供商数量
3. 如果解析失败，必须提供详细的错误信息
4. 在开始任务时，必须输出：'[Parser Agent] 开始解析提供商列表'
5. 在完成任务时，必须输出：'[Parser Agent] 解析完成，共找到 X 个提供商'
6. 你必须使用parse_provider_list工具来解析文本
7. 你必须返回解析后的结果，格式为JSON字符串""",
        model=MODEL_NAME,
        tools=[parse_provider_list, current_time],
    )

# 创建Provider Agent
def create_provider_agent(mcp_server):
    return Agent(
        name="Provider Agent",
        instructions="""You are a specialist agent responsible for fetching and processing data for a single specified provider.
You have been activated via a handoff.

Your Task:
1.  **Identify Provider Details**: The 'name' and 'url' of the provider you need to process are contained in the arguments of the `process_provider` tool call that initiated your current run. You MUST extract these 'name' and 'url' values from that tool call in the conversation history.
2.  **Fetch Data**: Use the extracted 'url' to access the provider's webpage and retrieve model pricing information. You have an MCP server (e.g., Firecrawl) available, which may provide tools like 'scrape_url' if complex web scraping is needed. Check your available tools.
3.  **Format Data**: Organize all extracted model parameters and pricing information into a clear markdown table.
    *   Ensure you generate plain text markdown.
    *   Use "CNY" or "USD" for currency, not symbols.
    *   Avoid special Unicode characters or control characters.
4.  **Record Timestamp**: Use your `current_time` tool to get the current time. This should be included in the output file.
5.  **Save to File**: Use your `write_to_file` tool to save the markdown table.
    *   The file path MUST be `results/<provider_name>.md`. Replace `<provider_name>` with the sanitized name of the provider you processed (e.g. replace spaces with underscores).
    *   The file content should start with the refresh timestamp. Example: `* Refreshed at: <current_time_tool_output>`
6.  **Report Result**: Your final output should be a message indicating success (including the filename) or failure (with a reason).
""",
        model=MODEL_NAME,
        mcp_servers=[mcp_server],
        tools=[write_to_file, current_time],
    )

# 创建Summary Agent
def create_summary_agent():
    return Agent(
        name="Summary Agent",
        instructions="""你是一个数据汇总专家，负责将多个文件中的表格数据整合为一个大表格。
你的任务是：
1. 读取results目录下的所有markdown文件
2. 从每个文件中提取表格数据
3. 将所有数据整合为一个大表格
4. 添加提供商信息列
5. 保存汇总结果

重要规则：
1. 你必须记录开始和完成时间
2. 你必须报告处理的文件数量
3. 你必须确认汇总文件是否成功保存
4. 如果汇总失败，必须提供详细的错误信息
5. 你必须使用read_from_file和write_to_file工具
6. 你必须返回汇总结果的状态信息""",
        model=MODEL_NAME,
        tools=[read_from_file, list_files_in_directory, write_to_file, current_time],
    )

# 创建Notion Agent
def create_notion_agent(mcp_server):
    return Agent(
        name="Notion Agent",
        instructions="""你是一个Notion数据更新专家，负责将Markdown格式的表格数据更新到Notion页面中。
你的任务是：
1. 读取汇总的markdown文件
2. 将数据转换为Notion表格格式
3. 更新到指定的Notion页面

重要规则：
1. 你必须记录开始和完成时间
2. 你必须报告更新状态
3. 你必须确认更新是否成功
4. 如果更新失败，必须提供详细的错误信息
5. 你必须使用read_from_file工具读取文件
6. 你必须返回更新结果的状态信息""",
        model='openai/azure/gpt-4.1-mini',
        mcp_servers=[mcp_server],
        tools=[read_from_file, current_time],
    )

# No-op callback for provider handoff when input_type is present
def _provider_on_handoff_noop(ctx: RunContextWrapper, data: ProviderData):
    pass

# 创建Coordinator Agent
def create_coordinator_agent(parser_agent, provider_agent, summary_agent, notion_agent):
    return Agent(
        name="Coordinator Agent",
        instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
Your are a workflow coordinator. Your primary role is to delegate tasks to specialized agents using YOUR handoff tools.

Your Handoff Tools & Workflow:

1.  **`parse_providers` (Handoff Tool)**:
    *   Use this tool FIRST to hand off the task of parsing the initial list of provider texts into structured data (name and URL for each).
    *   This tool takes no arguments from you; the provider text will be in the conversation history.
    *   The Parser Agent will return a list of provider objects (JSON string).

2.  **`process_provider` (Handoff Tool)**:
    *   After `parse_providers` returns a JSON string representing a list of providers, you must first understand this list.
    *   You MUST iterate through this list of provider objects.
    *   For EACH provider object in the list (each object will have a 'name' and a 'url' field):
        *   You MUST call YOUR `process_provider` handoff tool.
        *   When calling `process_provider`, you MUST provide the `name` and `url` arguments, taking their values from the current provider object.
        *   Example: If a provider object is `{{'name': 'Provider X', 'url': 'http://x.com'}}`, you must call `process_provider(name='Provider X', url='http://x.com')`.
    *   Await the result from EACH `process_provider` handoff before processing the next provider.

3.  **`summarize_results` (Handoff Tool)**:
    *   After all providers have been processed by `process_provider` handoffs:
    *   Call YOUR `summarize_results` handoff tool to consolidate all individual provider results.
    *   This tool currently takes no arguments from you.

4.  **`update_notion` (Handoff Tool)**:
    *   If Notion updates are enabled and after `summarize_results` is complete:
    *   Call YOUR `update_notion` handoff tool.
    *   This tool currently takes no arguments from you.

General Rules:
*   Strictly follow the sequence: Parse -> Process each Provider -> Summarize -> Update Notion (if enabled).
*   After initiating a handoff, await its completion and result before deciding on the next step.
*   If a sub-agent (via handoff) reports an error or failure, you MUST report this error and STOP the entire workflow.
*   Use your `current_time` tool if you need to report timestamps for your own coordination actions.
""",
        model=MODEL_NAME,
        tools=[current_time],
        handoffs=[
            handoff(agent=parser_agent, tool_name_override="parse_providers", input_filter=handoff_filters.remove_all_tools),
            handoff(agent=provider_agent, tool_name_override="process_provider", input_type=ProviderData, on_handoff=_provider_on_handoff_noop),
            handoff(agent=summary_agent, tool_name_override="summarize_results", input_filter=handoff_filters.remove_all_tools),
            handoff(agent=notion_agent, tool_name_override="update_notion", input_filter=handoff_filters.remove_all_tools)
        ]
    )

def log_agent_action(agent_name: str, action: str, details: str = ""):
    """记录Agent执行日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] {agent_name}: {action}"
    if details:
        log_message += f" - {details}"
    print(log_message)
    print("-" * 80)

# 主函数
async def main():
    log_agent_action("System", "开始执行流程")
    
    # 从环境变量更新Agent配置
    update_agent_config_from_env()
    log_agent_action("System", "Agent配置已更新")
    
    # 创建结果目录
    os.makedirs("results", exist_ok=True)
    log_agent_action("System", "结果目录已创建")
    
    # 初始化MCP Servers
    servers = await create_mcp_servers()
    log_agent_action("System", "MCP Servers已初始化")
    
    try:
        # 创建所有专业Agent
        parser_agent = create_parser_agent()
        provider_agent = create_provider_agent(servers.get("firecrawl"))
        summary_agent = create_summary_agent()
        notion_agent = create_notion_agent(servers.get("notion"))
        log_agent_action("System", "所有专业Agent已创建")
        
        # 创建协调Agent
        coordinator_agent = create_coordinator_agent(
            parser_agent,
            provider_agent,
            summary_agent,
            notion_agent
        )
        log_agent_action("System", "协调Agent已创建")
        
        # 提供商列表文本
        providers_text = """
## 阿里云
https://help.aliyun.com/zh/model-studio/models

## deepseek
https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
"""
        
        # 启动流程
        message = f"""Please coordinate the workflow to process the following provider list.
Start by initiating the parsing of this provider list.

Provider list:
{providers_text}

The overall workflow is:
1. Parse the provider list.
2. For each provider, process its data.
3. Summarize all results.
4. If Notion updates are enabled, update Notion.

Please ensure tasks are executed in this sequence, using the appropriate handoffs to specialized agents.
"""
        
        # 运行协调Agent
        log_agent_action("System", "开始执行协调Agent")
        result = await Runner.run(starting_agent=coordinator_agent, input=message)
        log_agent_action("System", "协调Agent执行完成")
        return result.final_output
    except Exception as e:
        log_agent_action("System", "执行出错", str(e))
        raise
    finally:
        # 关闭所有MCP Servers
        for server in servers.values():
            if server:
                try:
                    await server.__aexit__(None, None, None)
                except Exception as e:
                    print(f"关闭 MCP Server 失败: {str(e)}")
        log_agent_action("System", "MCP Servers已关闭")

if __name__ == "__main__":
    if not shutil.which("npx"):
        raise RuntimeError("npx is not installed. Please install it with `npm install -g npx`.")

    asyncio.run(main())
