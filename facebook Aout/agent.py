import sys
import os
import time
import subprocess
import requests
import json
import threading
from pathlib import Path

class FacebookScraperSkill:
    def __init__(self):
        self.base_url = "http://localhost:5000"
        self.api_process = None
        self.script_dir = Path(__file__).parent.parent.parent.parent.absolute()
        
    def check_api_running(self):
        """检查API服务器是否正在运行"""
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def start_api_server(self):
        """启动API服务器"""
        print("正在启动API服务器...")
        try:
            api_script = self.script_dir / "api_server.py"
            if not api_script.exists():
                print(f"错误: 找不到 api_server.py 在 {api_script}")
                return False
            
            self.api_process = subprocess.Popen(
                [sys.executable, str(api_script)],
                cwd=str(self.script_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            print("等待API服务器启动...")
            for i in range(30):
                if self.check_api_running():
                    print("✓ API服务器已启动!")
                    return True
                time.sleep(2)
            
            print("✗ API服务器启动超时")
            return False
        except Exception as e:
            print(f"✗ 启动API服务器失败: {e}")
            return False
    
    def check_login_status(self):
        """检查Facebook登录状态"""
        try:
            response = requests.get(f"{self.base_url}/api/login/status", timeout=10)
            result = response.json()
            return result.get('is_logged_in', False)
        except Exception as e:
            print(f"检查登录状态失败: {e}")
            return False
    
    def create_scrape_task(self, keyword, callback_url=None):
        """创建抓取任务"""
        try:
            params = {"keyword": keyword}
            if callback_url:
                params["callback_url"] = callback_url
            
            response = requests.post(
                f"{self.base_url}/api/tasks",
                json={
                    "type": "scrape",
                    "params": params
                },
                timeout=30
            )
            result = response.json()
            return result.get('task_id')
        except Exception as e:
            print(f"创建任务失败: {e}")
            return None
    
    def poll_task_status(self, task_id):
        """轮询任务状态"""
        print(f"正在执行任务: {task_id}")
        while True:
            try:
                response = requests.get(f"{self.base_url}/api/tasks/{task_id}", timeout=10)
                result = response.json()
                
                status = result.get('status')
                progress = result.get('progress', 0)
                message = result.get('message', '')
                
                print(f"\r进度: {progress:3}% - {message}", end='', flush=True)
                
                if status == "completed":
                    print("\n✓ 任务完成!")
                    return result.get('result')
                elif status == "failed":
                    print(f"\n✗ 任务失败: {result.get('error')}")
                    return None
                
                time.sleep(2)
            except Exception as e:
                print(f"\n查询任务状态失败: {e}")
                time.sleep(2)
    
    def scrape(self, keyword, callback_url=None):
        """完整的抓取流程"""
        print("=" * 70)
        print("Facebook 信息抓取工具")
        print("=" * 70)
        
        # 1. 检查并启动API服务器
        if not self.check_api_running():
            print("API服务器未运行，正在启动...")
            if not self.start_api_server():
                return None
        else:
            print("✓ API服务器已在运行")
        
        # 2. 检查登录状态
        print("\n检查登录状态...")
        if not self.check_login_status():
            print("\n⚠️ 请在打开的浏览器中登录Facebook账号")
            print("登录完成后按回车键继续...")
            input()
            
            if not self.check_login_status():
                print("✗ 仍然未登录，无法继续")
                return None
        
        print("✓ 已登录Facebook")
        
        # 3. 创建任务
        print(f"\n开始搜索: {keyword}")
        task_id = self.create_scrape_task(keyword, callback_url)
        if not task_id:
            print("✗ 无法创建任务")
            return None
        
        # 4. 轮询任务状态
        result = self.poll_task_status(task_id)
        
        # 5. 显示结果
        if result:
            print("\n" + "=" * 70)
            print("抓取结果:")
            print("=" * 70)
            
            count = result.get('count', 0)
            print(f"\n共获取到 {count} 条客户数据\n")
            
            results = result.get('results', [])
            for i, data in enumerate(results[:10], 1):
                print(f"【客户 {i}】")
                print(f"  链接: {data.get('link', '')}")
                print(f"  电话: {data.get('phone', '未找到')}")
                print(f"  WhatsApp: {data.get('whatsapp', '未找到')}")
                print(f"  邮箱: {data.get('email', '未找到')}")
                print(f"  网站: {data.get('website', '未找到')}")
                print()
            
            if len(results) > 10:
                print(f"... 还有 {len(results) - 10} 条数据")
            
            # 保存结果
            save_file = self.script_dir / f"facebook_scrape_results_{int(time.time())}.json"
            with open(save_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\n结果已保存到: {save_file}")
        
        return result
    
    def cleanup(self):
        """清理资源"""
        if self.api_process:
            print("\n正在停止API服务器...")
            self.api_process.terminate()
            try:
                self.api_process.wait(timeout=5)
            except:
                self.api_process.kill()
            print("✓ API服务器已停止")

def main():
    """主函数 - 从命令行调用"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Facebook信息抓取工具')
    parser.add_argument('keyword', help='搜索关键词')
    parser.add_argument('--callback', help='回调URL (可选)')
    
    args = parser.parse_args()
    
    skill = FacebookScraperSkill()
    try:
        result = skill.scrape(args.keyword, args.callback)
        if result:
            return 0
        return 1
    finally:
        # 不清理，保持API服务器运行供后续使用
        # skill.cleanup()
        pass

if __name__ == "__main__":
    main()
