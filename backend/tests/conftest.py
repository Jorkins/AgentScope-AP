import os

# 在导入 app.config 前提供隔离的测试身份配置，环境变量优先于本地 .env。
os.environ["JWT_SECRET"] = "test-only-jwt-secret-0123456789abcdef0123456789abcdef"
os.environ["AUTH_ENABLED"] = "true"
