#!/bin/bash

# 检查uv是否安装
if ! command -v uv &> /dev/null; then
    echo "uv 未安装，正在尝试安装..."
    curl -sSf https://install.python-uv.org | sh
    echo "uv 安装完成，请重新运行此脚本"
    exit 1
fi

# 创建虚拟环境并安装依赖
echo "使用uv安装依赖..."
# 直接安装而不使用venv命令，让uv自己处理虚拟环境
uv pip install -e .

# 检查npx是否安装
if ! command -v npx &> /dev/null; then
    echo "npx 未安装，正在尝试安装..."
    npm install -g npx
fi

# 安装firecrawl-mcp
echo "安装firecrawl-mcp..."
npm install -g firecrawl-mcp

echo "安装完成！"
echo "运行方式: FIRECRAWL_API_KEY=你的密钥 EXAMPLE_BASE_URL=你的BASE_URL EXAMPLE_API_KEY=你的API_KEY EXAMPLE_MODEL_NAME=模型名称 python firecrawl.py" 