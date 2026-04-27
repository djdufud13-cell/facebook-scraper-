---
name: "facebook-scraper"
description: "从Facebook搜索用户并提取电话、邮箱、网站、WhatsApp等联系方式。Invoke when user asks to scrape Facebook for business leads or contact information."
---

# Facebook 信息抓取工具 (facebook-scraper)

这是一个功能强大的Facebook信息抓取工具，可以从Facebook搜索用户并提取完整的联系方式。

## 功能特性

- 🔍 按关键词搜索Facebook公共主页
- 📱 提取电话号码
- 💬 提取WhatsApp号码
- 📧 提取邮箱地址
- 🌐 提取企业官网
- ⏱️ 异步任务处理
- 📊 进度实时反馈

## 使用前准备

### 1. 安装依赖

```bash
pip install -r requirements_api.txt
```

### 2. 启动API服务器

```bash
python api_server.py
```

### 3. 登录Facebook

在打开的浏览器中登录您的Facebook账号。

## 使用方法

### 方法1：使用测试脚本（推荐）

```bash
python test_api.py
```

### 方法2：直接调用API

#### 1. 创建完整抓取任务

```python
import requests
import time

# 创建任务
response = requests.post("http://localhost:5000/api/tasks", json={
    "type": "scrape",
    "params": {
        "keyword": "coffee shop",
        "callback_url": "https://your-webhook-url.com/notify"  # 可选
    }
})
task_id = response.json()["task_id"]

# 轮询查询任务状态
while True:
    response = requests.get(f"http://localhost:5000/api/tasks/{task_id}")
    result = response.json()
    
    status = result["status"]
    progress = result["progress"]
    message = result["message"]
    
    print(f"进度: {progress}% - {message}")
    
    if status == "completed":
        print("任务完成!")
        print(result["result"])
        break
    elif status == "failed":
        print("任务失败:", result["error"])
        break
    
    time.sleep(2)
```

## API端点说明

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/login/status` | GET | 检查登录状态 |
| `/api/tasks` | POST | 创建异步任务 |
| `/api/tasks/<task_id>` | GET | 查询任务状态（轮询） |
| `/api/tasks` | GET | 列出所有任务 |

## 任务类型

### 1. search - 仅搜索用户链接

```json
{
  "type": "search",
  "params": {
    "keyword": "coffee shop"
  }
}
```

### 2. user_info - 获取单个用户信息

```json
{
  "type": "user_info",
  "params": {
    "url": "https://www.facebook.com/..."
  }
}
```

### 3. scrape - 完整抓取（推荐）

```json
{
  "type": "scrape",
  "params": {
    "keyword": "coffee shop",
    "callback_url": "https://your-webhook-url.com"
  }
}
```

## 返回数据格式

```json
{
  "success": true,
  "count": 10,
  "results": [
    {
      "link": "https://www.facebook.com/...",
      "phone": "+1 234 567 890",
      "whatsapp": "+1234567890",
      "email": "info@example.com",
      "website": "https://example.com",
      "address": ""
    }
  ]
}
```

## 注意事项

⚠️ 重要提示：
1. 请遵守Facebook的使用条款和服务条款
2. 建议适当控制抓取频率，避免触发反垃圾机制
3. 抓取的数据仅供合法商业用途使用
4. 请妥善保管您的Facebook账号安全

## 故障排除

### 浏览器无法启动
- 检查是否已安装Playwright: `playwright install chromium`
- 确保有足够的系统资源

### 无法登录
- 请手动在打开的浏览器中登录
- 检查网络连接

### 抓取失败
- 检查Facebook账号是否正常
- 查看日志文件: `api_server.log`
- 适当增加延迟时间

## 文件说明

| 文件 | 说明 |
|------|------|
| `api_server.py` | API服务器主程序 |
| `test_api.py` | API测试脚本 |
| `requirements_api.txt` | 依赖包列表 |
| `api_server.log` | 运行日志 |
| `UserData/` | Chrome用户数据目录 |

## 技术栈

- Python 3.8+
- Flask (Web框架)
- Playwright (浏览器自动化)
- CORS (跨域支持)
- 异步任务处理

---

**版本**: 1.0.0  
**最后更新**: 2026-04-14
