#!/bin/bash

###############################################################################
# 多机器人调度系统 - Mac 一键部署脚本
# 适用于: macOS (Intel & Apple Silicon)
# 特别优化: Mac mini M4 (Apple Silicon)
###############################################################################

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_step() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

###############################################################################
# 步骤 1: 系统检查
###############################################################################
print_step "步骤 1/5: 系统环境检查"

# 检查操作系统
if [[ "$OSTYPE" != "darwin"* ]]; then
    print_error "此脚本仅适用于 macOS 系统"
    exit 1
fi

print_success "操作系统: macOS"

# 检查芯片架构
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
    print_success "芯片架构: Apple Silicon (M系列芯片) - $ARCH"
    IS_APPLE_SILICON=true
else
    print_success "芯片架构: Intel - $ARCH"
    IS_APPLE_SILICON=false
fi

# 检查 Python
print_info "检查 Python 环境..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    print_success "Python 版本: $PYTHON_VERSION"

    # 检查 Python 版本是否符合要求 (3.8+)
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

    if [[ $PYTHON_MAJOR -lt 3 ]] || [[ $PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -lt 8 ]]; then
        print_error "Python 版本过低，需要 3.8 或更高版本"
        print_info "请使用 Homebrew 安装: brew install python@3.11"
        exit 1
    fi
else
    print_error "未找到 Python3"
    print_info "请先安装 Python3:"
    echo "  方法1: brew install python@3.11"
    echo "  方法2: 从 https://www.python.org/downloads/macos/ 下载安装"
    exit 1
fi

# 检查 pip
if ! command -v pip3 &> /dev/null; then
    print_error "未找到 pip3"
    print_info "安装 pip: python3 -m ensurepip --upgrade"
    exit 1
fi
print_success "pip3 已安装"

###############################################################################
# 步骤 2: 创建虚拟环境
###############################################################################
print_step "步骤 2/5: 创建 Python 虚拟环境"

if [ -d "venv" ]; then
    print_warning "虚拟环境已存在，是否重新创建？(y/N)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        print_info "删除旧的虚拟环境..."
        rm -rf venv
        print_success "旧虚拟环境已删除"
    else
        print_info "使用现有虚拟环境"
    fi
fi

if [ ! -d "venv" ]; then
    print_info "创建虚拟环境..."
    python3 -m venv venv
    print_success "虚拟环境创建完成"
fi

# 激活虚拟环境
print_info "激活虚拟环境..."
source venv/bin/activate
print_success "虚拟环境已激活"

###############################################################################
# 步骤 3: 安装依赖
###############################################################################
print_step "步骤 3/5: 安装 Python 依赖包"

print_info "升级 pip..."
pip install --upgrade pip -q

print_info "安装依赖包（使用清华镜像加速）..."
print_warning "这可能需要几分钟，请耐心等待..."

# 对于 Apple Silicon，某些包可能需要特殊处理
if [ "$IS_APPLE_SILICON" = true ]; then
    print_info "检测到 Apple Silicon，使用优化的安装策略..."

    # 先安装可能有兼容性问题的包
    if grep -q "numpy" requirements.txt; then
        print_info "预安装 numpy（Apple Silicon 优化）..."
        pip install numpy -i https://pypi.tuna.tsinghua.edu.cn/simple -q
    fi
fi

# 安装所有依赖
if pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple; then
    print_success "依赖安装完成"
else
    print_error "依赖安装失败，尝试使用备用镜像源..."
    if pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple; then
        print_success "依赖安装完成（使用阿里云镜像）"
    else
        print_error "依赖安装失败"
        print_info "请检查网络连接或手动安装: pip install -r requirements.txt"
        exit 1
    fi
fi

# 验证关键依赖
print_info "验证关键依赖..."
python3 -c "import fastapi, uvicorn, httpx, pydantic, asyncio" 2>/dev/null
if [ $? -eq 0 ]; then
    print_success "关键依赖验证通过"
else
    print_error "关键依赖验证失败"
    exit 1
fi

###############################################################################
# 步骤 4: 创建必要的目录
###############################################################################
print_step "步骤 4/5: 创建必要的目录"

DIRS=("logs" "data" "maps")
for dir in "${DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        print_success "创建目录: $dir"
    else
        print_info "目录已存在: $dir"
    fi
done

###############################################################################
# 步骤 5: 配置启动脚本
###############################################################################
print_step "步骤 5/5: 配置启动脚本"

# 创建快速启动脚本
cat > start.sh << 'EOF'
#!/bin/bash
# 快速启动脚本

# 激活虚拟环境
source venv/bin/activate

# 启动服务
echo "🚀 启动多机器人调度系统..."
python main.py
EOF

chmod +x start.sh
print_success "创建启动脚本: start.sh"

# 创建停止脚本
cat > stop.sh << 'EOF'
#!/bin/bash
# 停止服务脚本

echo "⏹ 停止服务..."
PID=$(lsof -ti:8092)
if [ -z "$PID" ]; then
    echo "✓ 服务未运行"
else
    kill $PID
    echo "✓ 服务已停止 (PID: $PID)"
fi
EOF

chmod +x stop.sh
print_success "创建停止脚本: stop.sh"

# 创建重启脚本
cat > restart.sh << 'EOF'
#!/bin/bash
# 重启服务脚本

echo "🔄 重启服务..."
./stop.sh
sleep 2
./start.sh
EOF

chmod +x restart.sh
print_success "创建重启脚本: restart.sh"

# 创建后台运行脚本
cat > start_background.sh << 'EOF'
#!/bin/bash
# 后台运行脚本

# 激活虚拟环境
source venv/bin/activate

# 后台启动服务
echo "🚀 后台启动多机器人调度系统..."
nohup python main.py > logs/service.log 2>&1 &
PID=$!
echo "✓ 服务已在后台启动 (PID: $PID)"
echo "✓ 查看日志: tail -f logs/app.log"
EOF

chmod +x start_background.sh
print_success "创建后台启动脚本: start_background.sh"

###############################################################################
# 部署完成
###############################################################################
print_step "🎉 部署完成！"

echo ""
print_success "所有依赖已安装完成"
print_success "虚拟环境已配置完成"
print_success "启动脚本已创建完成"
echo ""

print_info "═══════════════════════════════════════════════════════"
print_info "  快速启动指南"
print_info "═══════════════════════════════════════════════════════"
echo ""
echo "  1️⃣  启动服务（前台运行）："
echo "      ${GREEN}./start.sh${NC}"
echo ""
echo "  2️⃣  启动服务（后台运行，推荐）："
echo "      ${GREEN}./start_background.sh${NC}"
echo ""
echo "  3️⃣  停止服务："
echo "      ${GREEN}./stop.sh${NC}"
echo ""
echo "  4️⃣  重启服务："
echo "      ${GREEN}./restart.sh${NC}"
echo ""
echo "  5️⃣  查看日志："
echo "      ${GREEN}tail -f logs/app.log${NC}"
echo ""
print_info "═══════════════════════════════════════════════════════"
echo ""
print_info "服务启动后访问："
echo "  • 首页:        ${BLUE}http://localhost:8092${NC}"
echo "  • API文档:     ${BLUE}http://localhost:8092/docs${NC}"
echo "  • 健康检查:    ${BLUE}http://localhost:8092/health${NC}"
echo ""

# 询问是否立即启动
print_warning "是否立即启动服务？(Y/n)"
read -r response
if [[ -z "$response" ]] || [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo ""
    print_info "启动服务中..."
    ./start.sh
else
    print_info "稍后可以运行 ${GREEN}./start.sh${NC} 启动服务"
fi
