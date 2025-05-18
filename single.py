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
    # Handoff related imports removed as they are no longer used
    # handoff,
    # HandoffInputData,
    # RunContextWrapper
)
# from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX # Removed
# from agents.extensions import handoff_filters # Removed

# 加载.env文件中的环境变量
load_dotenv(override=True)

# Agent配置 - 控制启用哪些agent
AGENT_CONFIG = {
    "parser_agent": False,      # 解析提供商列表的agent (controls parsing step)
    "provider_agent": False,    # 处理单个提供商的agent (controls provider processing step)
    "summary_agent": False,     # 汇总结果的agent (controls summary step)
    "notion_agent": True       # 更新Notion的agent (controls Notion update step)
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
        
        # 确保content是字符串类型
        # content = sanitize_text(content) # Sanitization can be handled by agent if needed
            
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
        解析后的提供商和URL列表 (JSON string or list of dicts)
    """
    # The tool should ideally return a JSON string or list of dicts directly usable by the agent
    return _parse_provider_list(content)


# run_single_provider function removed, its logic will be part of OrchestratorAgent

# run_parser_agent function removed, its logic will be part of OrchestratorAgent

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
        return sorted(files) # Return sorted list of files
    except Exception as e:
        return f"列出文件失败: {str(e)}"


@function_tool
def parse_markdown_table(markdown_content: str):
    """
    Parses a Markdown table into a list of dictionaries.
    Each dictionary represents a row, with keys from the table header.
    Handles simple Markdown tables with | and - characters for structure.

    Args:
        markdown_content: A string containing the Markdown table.

    Returns:
        A list of dictionaries, where each dictionary is a row.
        Returns an empty list if parsing fails or no table is found.
        Example: [{'Header1': 'Row1Col1', 'Header2': 'Row1Col2'}, ...]
    """
    lines = markdown_content.strip().split('\n')
    
    processed_lines = [line.strip() for line in lines if line.strip()]
    if not processed_lines:
        return []

    header_line_text = ""
    header_idx_in_processed = -1
    data_start_idx = -1

    # Try to find header and separator robustly
    # A header line contains '|' but not all '---' segments
    # A separator line contains '|' and all '---' segments
    for i in range(len(processed_lines) - 1):
        line_i = processed_lines[i]
        line_i_plus_1 = processed_lines[i+1]

        if '|' in line_i and '|' in line_i_plus_1:
            # Check if line_i_plus_1 is a valid separator
            sep_parts = [part.strip() for part in line_i_plus_1.strip('|').split('|')]
            if sep_parts and all(all(c == '-' for c in p) for p in sep_parts if p):
                # Check if line_i is likely a header (not all dashes)
                header_parts = [part.strip() for part in line_i.strip('|').split('|')]
                if not all(all(c == '-' for c in p) for p in header_parts if p):
                    header_line_text = line_i
                    header_idx_in_processed = i
                    data_start_idx = i + 2
                    break
    
    if not header_line_text: # If robust check fails, try simpler heuristic (might be less accurate)
        try:
            # Simplified: find first line with '|' not being a separator as header
            header_idx_in_processed = next(i for i, line in enumerate(processed_lines) if '|' in line and not all(all(c == '-' for c in p.strip()) for p in line.strip('|').split('|') if p.strip()))
            # Separator must be next and be a proper separator
            if header_idx_in_processed + 1 < len(processed_lines):
                sep_line_candidate = processed_lines[header_idx_in_processed+1]
                sep_parts = [part.strip() for part in sep_line_candidate.strip('|').split('|')]
                if '|' in sep_line_candidate and sep_parts and all(all(c == '-' for c in p) for p in sep_parts if p):
                    header_line_text = processed_lines[header_idx_in_processed]
                    data_start_idx = header_idx_in_processed + 2
                else: # Not a valid separator after candidate header
                    return []
            else: # No line after candidate header
                return []
        except StopIteration: # No lines matching even basic criteria
             return []

    headers = [h.strip() for h in header_line_text.strip('|').split('|')]
    headers = [h for h in headers if h] # Filter out empty headers from `||` or trailing `|`
    if not headers:
        return []

    data_rows = []
    if data_start_idx <= len(processed_lines): # Check should be < not <= for index
        for i in range(data_start_idx, len(processed_lines)):
            line = processed_lines[i]
            if not line.startswith('|'): # Potential end of table
                # Allow for tables that might not have a blank line after them
                # but ensure it's not just a random non-table line
                if any(c != ' ' and c != '|' and c != '-' for c in line): # if it has non-table chars
                    break
                if not '|' in line: # definitely not a table row
                    break
            
            cols_raw = line.strip('|').split('|')
            # Ensure cols list matches header length by padding with empty strings if shorter
            # and truncating if longer (though Markdown usually implies shorter is empty)
            cols = [c.strip() for c in cols_raw[:len(headers)]]
            while len(cols) < len(headers):
                cols.append("") # Pad if MD row has fewer cells than header
            
            row_dict = dict(zip(headers, cols))
            data_rows.append(row_dict)
            
    return data_rows


# run_summary_agent function removed, its logic will be part of OrchestratorAgent

# run_notion_update_agent function removed, its logic will be part of OrchestratorAgent

def update_agent_config_from_env():
    """从环境变量更新Agent配置"""
    for agent_key in AGENT_CONFIG.keys(): # Changed agent_name to agent_key for clarity
        env_name = f"ENABLE_{agent_key.upper()}" # agent_name changed to agent_key
        env_value = os.getenv(env_name)
        if env_value is not None:
            # 将字符串转换为布尔值
            enabled = env_value.lower() in ('true', '1', 't', 'y', 'yes')
            AGENT_CONFIG[agent_key] = enabled # agent_name changed to agent_key
            print(f"从环境变量设置 {agent_key}: {enabled}") # agent_name changed to agent_key


# 首先定义数据模型
class ProviderData(BaseModel):
    """单个提供商数据"""
    name: str
    url: str

# ProviderListData, SummaryData, NotionData removed as they were for handoffs

# 创建并初始化MCP Servers
async def create_mcp_servers():
    """创建所有需要的MCP Servers"""
    servers = {}
    
    # 创建Firecrawl MCP Server
    # Check AGENT_CONFIG to see if provider processing is enabled
    if AGENT_CONFIG.get("provider_agent", True):
        firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
        if firecrawl_api_key:
            try:
                print("尝试创建 Firecrawl MCP Server...")
                servers["firecrawl"] = await MCPServerStdio(
                    cache_tools_list=True,
                    params={
                        "command": "npx", 
                        "args": ["-y", "firecrawl-mcp"],
                        "env": {
                            "FIRECRAWL_API_KEY": firecrawl_api_key
                        }
                    },
                    client_session_timeout_seconds=120,
                ).__aenter__()
                print("Firecrawl MCP Server 创建成功。")
            except Exception as e:
                print(f"创建 Firecrawl MCP Server 失败: {str(e)}")
        else:
            print("FIRECRAWL_API_KEY 未设置，跳过 Firecrawl MCP Server 创建。")
    
    # 创建Notion MCP Server
    # Check AGENT_CONFIG to see if Notion updates are enabled
    if AGENT_CONFIG.get("notion_agent", True):
        notion_api_key = os.getenv("NOTION_API_KEY")
        if notion_api_key:
            try:
                print("尝试创建 Notion MCP Server...")
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
                print("Notion MCP Server 创建成功。")
            except Exception as e:
                print(f"创建 Notion MCP Server 失败: {str(e)}")
        else:
            print("NOTION_API_KEY 未设置，跳过 Notion MCP Server 创建。")
            
    return servers

# create_parser_agent, create_provider_agent, create_summary_agent, create_notion_agent removed.
# create_coordinator_agent removed.

# Orchestrator Agent definition
def create_orchestrator_agent(mcp_servers_list=None):
    if mcp_servers_list is None:
        mcp_servers_list = []
        
    # 定义Notion页面ID，可以从环境变量获取或硬编码
    notion_page_id = os.getenv("NOTION_PAGE_ID", "your-notion-page-id-here")
    print(f"Notion Page ID: {notion_page_id}")

    return Agent(
        name="Orchestrator Agent",
        instructions=f"""You are an AI assistant responsible for orchestrating a data processing workflow.
You will be given a list of tasks to perform based on the initial user message.
Your goal is to process a list of providers, fetch their model pricing data, summarize it, and optionally update a Notion page.
You have a set of tools to help you achieve this. Follow the enabled steps as outlined in the user's request.

Detailed Operational Instructions for Each Potential Step:

1.  **Parse Provider List**:
    *   You will be given a text block containing provider names and their URLs.
    *   Use the `parse_provider_list` tool to extract a structured list of providers (each with 'name' and 'url').
    *   Log the number of providers found. This result (list of provider dicts) will be used in the next step.

2.  **Process Each Provider**:
    *   Iterate through the list of provider objects obtained from the parsing step.
    *   For each provider (object with 'name' and 'url' fields):
        *   Log that you are starting to process this provider (e.g., "Processing provider: [name]").
        *   The provider's URL needs to be scraped for model pricing information. You should have access to an MCP server (e.g., Firecrawl, if enabled and available) which provides tools like `scrape_url` or `crawl_url`. Use such a tool to get the content of the provider's page.
        *   After scraping, analyze the retrieved content. Extract all relevant model parameters and pricing information.
        *   Format this information into a Markdown table.
            *   Ensure you generate plain text markdown.
            *   Use "CNY" or "USD" (or other appropriate currency codes) for currency values, not symbols like '$' or '¥'.
            *   Avoid special Unicode characters or control characters that might cause issues in file writing or rendering.
        *   Use the `current_time` tool to get a timestamp for when the data was refreshed.
        *   Construct the output file path as `results/<provider_name>.md`. Sanitize `<provider_name>` by replacing spaces or special characters with underscores if necessary, to make it a valid filename.
        *   The content of this file should start with the refresh timestamp, e.g., `* Refreshed at: [timestamp_from_current_time_tool]`.
        *   Use the `write_to_file` tool to save the Markdown table to this file.
        *   Log the successful processing of the provider and the output file name.
        *   If an error occurs during processing a provider (e.g., scraping fails, data not found), log the error clearly (e.g., "Error processing provider [name]: [error_details]") and continue to the next provider. Do not let one provider's failure stop the entire workflow if others can be processed.

3.  **Summarize Results**:
    *   After attempting to process all providers:
    *   Use the `list_files_in_directory` tool to get a list of all `.md` files from the `results/` directory.
    *   Log the number of result files found.
    *   Initialize an empty list or structure to hold data from all files.
    *   For each file in the list:
        *   Use the `read_from_file` tool to read its content.
        *   Parse the Markdown content to extract the table data and the provider name (which might be inferred from the filename or file content if not explicitly in the table).
    *   Consolidate all extracted data into a single, large Markdown table.
        *   This summary table should typically include a "Provider" column identifying the source of each row of data.
        *   Common columns are: Provider, Model Name, Input Price, Output Price, Notes/Remarks, etc.
        *   Use the `current_time` tool to get a timestamp for the summary.
        *   The summary file should start with a title like `# 大模型提供商价格汇总` and the refresh timestamp: `* 刷新于 [timestamp_from_current_time_tool]`.
    *   Use the `write_to_file` tool to save this consolidated Markdown table to a file named `summary.md` in the root directory.
    *   Log the completion of the summary generation and the name of the output file (`summary.md`).

4.  **Update Notion**:
    *   This step is conditional, based on whether Notion updates are indicated as ENABLED in your initial instructions and if the Notion MCP server is available.
    *   Notion Target Page ID: {notion_page_id}
    *   If enabled:
        *   Even if other steps like 'Summarize Results' (Step 3) were disabled in the current workflow configuration, you must still proceed with this step if it's enabled.
        *   Attempt to read the `summary.md` file from the root directory using the `read_from_file` tool. This is a critical check for an existing file.
        *   If the `read_from_file` tool successfully returns content for `summary.md` (indicating the file exists and is readable):
            *   Log that `summary.md` was found and its content will be used for the Notion update.
            *   Log that you will now update the configured Notion page. The Notion tools/MCP server are expected to use the target Page ID: {notion_page_id} (as specified above) for their operations.
            *   You should have access to an MCP server for Notion which provides tools to interact with the configured Notion page (e.g., list child blocks, delete blocks, append blocks using specific block type structures).
            *   **Separate non-table content and Markdown table from `summary.md`:**
                a.  Identify any leading text in `summary.md` (like a title `# ...` or a refresh line `* Refreshed at ...`) that is *not* part of the main Markdown table.
                b.  If such leading text exists, instruct the Notion tools to append this text as standard paragraph or heading blocks to the target page ({notion_page_id}) first (after the page content has been cleared as per previous sub-step).
                c.  Extract the actual Markdown table string from `summary.md`.
            *   **Parse the Markdown table and construct Notion Simple Table blocks:**
                a.  Use the `parse_markdown_table` tool with the extracted Markdown table string to get structured data. This should return a list of dictionaries (rows), where keys are headers.
                b.  If parsing fails or returns no data, log this (e.g., "Failed to parse Markdown table from summary.md or table was empty. Skipping Notion Simple Table creation.") and do not attempt to create a table. The non-table content (if any) might have already been added.
                c.  If parsing is successful and data is available:
                    i.  Log that the Markdown table was parsed. Get the headers (e.g., from the keys of the first data dictionary). Determine `table_width` (number of headers).
                    ii. Construct an array of `table_row` block objects according to Notion API for Simple Tables:
                        1.  **Header Row**: Create one `table_row` block. Its `cells` property will be an array where each element is `[{{"type": "text", "text": {{"content": "HeaderName"}}}}]` for each header.
                        2.  **Data Rows**: For each dictionary in the parsed data, create a `table_row` block. Its `cells` property will be an array structured similarly, using the data values for `content`, ensuring values correspond to the order of headers.
                    iii.Instruct the Notion tools to append a single block of type `table` to the target page ({notion_page_id}). This `table` block object must be constructed with:
                        - `"table_width"`: (the number of columns/headers you determined)
                        - `"has_column_header"`: `true`
                        - `"has_row_header"`: `false` (usually)
                        - `"children"`: The array of `table_row` block objects you constructed in the preceding step (containing the header row first, then all data rows).
            *   Log the overall status (e.g., "Successfully appended content and a Simple Table with X rows to Notion page {notion_page_id}." or "Appended non-table content, but failed to create Simple Table: [error_details]").
        *   Else (if the `read_from_file` tool indicates that `summary.md` cannot be read, e.g., file not found, permission issues, or the tool returns an error/empty content signifying failure):
            *   Log that `summary.md` was not found or is unreadable at the root directory, and therefore the Notion update will be skipped. This is the primary condition for skipping an enabled Step 4 if `summary.md` is its required input.
    *   If Notion updates are disabled, or the Notion MCP server is not available, log that this step is being skipped.

General Rules:
*   Strictly follow the sequence of enabled steps.
*   Log your major actions, decisions, and any errors encountered for each step. Use `print()` for logging if no specific logging tool is provided.
*   If a critical prerequisite step fails (e.g., parsing provider list if provider processing is enabled), you may need to report the error and halt further dependent steps.
*   Manage API keys and sensitive data carefully. MCP servers should handle their own API key configurations.
*   Your final output should be a summary of what was done, including paths to any generated files and status of Notion update if attempted.
""",
        model=MODEL_NAME,
        tools=[
            parse_provider_list,
            write_to_file,
            current_time,
            read_from_file,
            list_files_in_directory,
            parse_markdown_table
        ],
        mcp_servers=mcp_servers_list if mcp_servers_list else None, # Pass MCP servers here
    )

def log_agent_action(agent_name: str, action: str, details: str = ""):
    """记录Agent执行日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] {agent_name}: {action}"
    if details:
        log_message += f" - {details}"
    print(log_message)
    # Removed the separator line print("-" * 80) to reduce console noise, can be re-added if desired

# 主函数
async def main():
    log_agent_action("System", "开始执行流程")
    
    # 从环境变量更新Agent配置
    update_agent_config_from_env()
    log_agent_action("System", f"Agent配置加载完成: {AGENT_CONFIG}")
    
    # 创建结果目录
    os.makedirs("results", exist_ok=True)
    log_agent_action("System", "结果目录 'results' 已确保存在")
    
    # 初始化MCP Servers
    servers = await create_mcp_servers()
    log_agent_action("System", "MCP Servers初始化尝试完成")
    
    try:
        # Prepare MCP server list for the agent
        active_mcp_servers = []
        if servers.get("firecrawl"):
            active_mcp_servers.append(servers["firecrawl"])
            log_agent_action("System", "Firecrawl MCP Server将传递给Agent")
        if servers.get("notion"):
            active_mcp_servers.append(servers["notion"])
            log_agent_action("System", "Notion MCP Server将传递给Agent")

        orchestrator_agent = create_orchestrator_agent(active_mcp_servers if active_mcp_servers else None)
        log_agent_action("System", "Orchestrator Agent已创建")
        
        # 提供商列表文本
        providers_text = """
## 阿里云
https://help.aliyun.com/zh/model-studio/models

"""
        
        # Construct initial message based on AGENT_CONFIG
        instruction_parts = ["You are an Orchestrator Agent. Please manage the following data processing workflow according to your detailed operational instructions for enabled steps."]
        instruction_parts.append(f"\nProvider list text to process:\n```\n{providers_text}\n```")
        
        instruction_parts.append("\nWorkflow Configuration:")
        
        parser_enabled = AGENT_CONFIG.get("parser_agent", True)
        provider_processing_enabled = AGENT_CONFIG.get("provider_agent", True)
        summary_enabled = AGENT_CONFIG.get("summary_agent", True)
        notion_enabled = AGENT_CONFIG.get("notion_agent", True)

        if parser_enabled:
            instruction_parts.append("- **Step 1 (Parse Providers): ENABLED.** You should parse the provider list text.")
        else:
            instruction_parts.append("- **Step 1 (Parse Providers): DISABLED.** Skip parsing.")
            # If parsing is disabled, subsequent steps that depend on it should also be considered disabled or warned.
            if provider_processing_enabled:
                log_agent_action("System", "Warning: Provider processing is enabled but parsing is disabled. This may lead to errors.")


        if provider_processing_enabled:
            if not parser_enabled:
                 instruction_parts.append("- **Step 2 (Process Providers): DISABLED** (dependent on parsing).")
            else:
                instruction_parts.append("- **Step 2 (Process Providers): ENABLED.** For each parsed provider, fetch, process, and save its data.")
        else:
            instruction_parts.append("- **Step 2 (Process Providers): DISABLED.** Skip processing individual providers.")

        if summary_enabled:
            if not provider_processing_enabled and parser_enabled : # Summarization might still run on existing files even if provider processing is off
                 instruction_parts.append("- **Step 3 (Summarize Results): ENABLED.** Summarize data from `results/` directory. Note: Provider processing might be disabled, so this will summarize existing files if any.")
            elif not parser_enabled and not provider_processing_enabled: # If parsing and provider processing are off, summarization likely has no new input
                 instruction_parts.append("- **Step 3 (Summarize Results): ENABLED.** Summarize data from `results/` directory. Note: Parsing and provider processing are disabled, this will act on pre-existing files.")
            else: # Standard case
                instruction_parts.append("- **Step 3 (Summarize Results): ENABLED.** Summarize all processed provider data.")

        else:
            instruction_parts.append("- **Step 3 (Summarize Results): DISABLED.** Skip summarization.")

        if notion_enabled:
            instruction_parts.append("- **Step 4 (Update Notion): ENABLED.** If a `summary.md` file exists in the root directory and is readable, use its content to update the configured Notion page. The Notion tools/MCP server are expected to know the target Page ID.")
        else:
            instruction_parts.append("- **Step 4 (Update Notion): DISABLED.** Skip Notion update.")
        
        initial_message = "\n".join(instruction_parts)
        log_agent_action("System", "给Orchestrator Agent的初始消息", f"\n{initial_message}")
        
        # 运行协调Agent
        log_agent_action("System", "开始执行Orchestrator Agent")
        result = await Runner.run(
            starting_agent=orchestrator_agent, 
            input=initial_message,
            max_turns=20 # 增加轮次上限
        )
        log_agent_action("System", "Orchestrator Agent执行完成")
        
        final_output = result.final_output
        if isinstance(final_output, str) and len(final_output) > 1000: # Avoid printing huge outputs
            log_agent_action("System", "Orchestrator Agent Final Output (truncated)", final_output[:1000] + "...")
        else:
            log_agent_action("System", "Orchestrator Agent Final Output", str(final_output))
        return final_output

    except Exception as e:
        log_agent_action("System", "执行主流程出错", str(e))
        # Optionally re-raise or handle more gracefully
        raise
    finally:
        # 关闭所有MCP Servers
        log_agent_action("System", "开始关闭MCP Servers")
        closed_count = 0
        for server_name, server_instance in servers.items():
            if server_instance:
                try:
                    await server_instance.__aexit__(None, None, None)
                    log_agent_action("System", f"MCP Server '{server_name}' 已关闭")
                    closed_count +=1
                except Exception as e:
                    print(f"关闭 MCP Server '{server_name}' 失败: {str(e)}")
        if closed_count == 0 and (AGENT_CONFIG.get("provider_agent") or AGENT_CONFIG.get("notion_agent")):
            log_agent_action("System", "没有MCP servers被激活或关闭。")
        else:
            log_agent_action("System", f"总共 {closed_count} MCP Servers 已关闭")
        log_agent_action("System", "流程执行完毕")

if __name__ == "__main__":
    if not shutil.which("npx"):
        # This check might be too strict if npx is only needed for specific MCPs
        # Consider making it conditional based on AGENT_CONFIG enabling those MCPs.
        print("Warning: npx command not found. This might be an issue if Firecrawl or Notion MCP servers are used.")
        # raise RuntimeError("npx is not installed. Please install it with `npm install -g npx`.")

    asyncio.run(main())

