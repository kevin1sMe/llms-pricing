# Agents 配置说明

本项目包含多个agent，每个agent负责不同的任务。您可以通过配置来启用或禁用特定的agent进行测试。

## 可用的Agent

| Agent名称 | 环境变量 | 功能描述 |
|----------|----------|---------|
| `parser_agent` | `ENABLE_PARSER_AGENT` | 解析提供商列表的agent，将文本描述转换为结构化数据 |
| `provider_agent` | `ENABLE_PROVIDER_AGENT` | 处理单个提供商数据的agent，负责抓取网页并提取价格信息 |
| `summary_agent` | `ENABLE_SUMMARY_AGENT` | 汇总结果的agent，将所有提供商的数据合并为一个表格 |
| `notion_agent` | `ENABLE_NOTION_AGENT` | 更新Notion的agent，将汇总表格更新到Notion页面 |

## 配置方法

### 1. 通过环境变量配置

在运行程序之前，设置对应的环境变量：

```bash
# 只启用parser_agent和provider_agent
export ENABLE_PARSER_AGENT=true
export ENABLE_PROVIDER_AGENT=true
export ENABLE_SUMMARY_AGENT=false
export ENABLE_NOTION_AGENT=false

# 然后运行程序
python firecrawl.py
```

环境变量可以设置为：`true`、`1`、`t`、`y`、`yes`（不区分大小写）来启用，或设置为其他值来禁用。

### 2. 通过直接修改代码配置

您也可以直接修改代码中的`AGENT_CONFIG`字典来配置：

```python
# Agent配置 - 控制启用哪些agent
AGENT_CONFIG = {
    "parser_agent": True,      # 解析提供商列表的agent
    "provider_agent": True,    # 处理单个提供商的agent
    "summary_agent": False,    # 汇总结果的agent
    "notion_agent": False      # 更新Notion的agent
}
```

## 使用示例

### 只测试单一提供商抓取功能

```bash
export ENABLE_PARSER_AGENT=false
export ENABLE_PROVIDER_AGENT=true
export ENABLE_SUMMARY_AGENT=false
export ENABLE_NOTION_AGENT=false
python firecrawl.py
```

### 只测试汇总功能

确保`results/`目录中已有抓取的数据文件，然后运行：

```bash
export ENABLE_PARSER_AGENT=false
export ENABLE_PROVIDER_AGENT=false
export ENABLE_SUMMARY_AGENT=true
export ENABLE_NOTION_AGENT=false
python firecrawl.py
```

### 只测试Notion更新功能

确保`summary.md`文件已存在，然后运行：

```bash
export ENABLE_PARSER_AGENT=false
export ENABLE_PROVIDER_AGENT=false
export ENABLE_SUMMARY_AGENT=false
export ENABLE_NOTION_AGENT=true
python firecrawl.py
```

## 注意事项

- 当禁用上游agent时，下游agent可能无法正常工作，除非所需的输入数据已经存在。
- 程序启动时会显示当前的agent配置状态。