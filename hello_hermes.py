import sys
import nautilus_trader

print("🚀 [Hermes AI] 正在执行系统自检...")
print("-" * 30)
print(f"Python 环境: {sys.version}")
print(f"虚拟环境路径: {sys.prefix}")
print(f"量化引擎版本: NautilusTrader {nautilus_trader.__version__}")
print("-" * 30)
print("✅ 恭喜！生产环境已就绪，hermes ai 准备起飞！")