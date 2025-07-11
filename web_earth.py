from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import win32serviceutil
import win32service
import psutil
import os
import json
import threading
import queue
import time
import re
from PIL import Image, ImageDraw
import sys

app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading')  # 使用threading模式而不是eventlet

class ServiceManager:
    def __init__(self):
        # 定义需要管理的服务名称
        self.services = {
            "MongoDB": "we_mongo",
            "PostgreSQL": "we_postgress"
        }
        
        # 配置文件路径
        self.config_file = "java_services_config.json"
        self.middleware_config_file = "middleware_config.json"
        
        # 加载配置
        self.java_services = self.load_java_services()
        self.middlewares = self.load_middlewares()
        
        # 添加进程状态缓存
        self.process_cache = {}
        self.last_check_time = 0
        self.CHECK_INTERVAL = 2  # 将检查间隔从10秒降低到2秒
        
        # 操作锁，防止并发操作导致的问题
        self.operation_lock = threading.Lock()
        
        # 状态检查线程
        self.is_running = True
        self.status_thread = threading.Thread(target=self.background_status_check, daemon=True)
        self.status_thread.start()

    def load_java_services(self):
        try:
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # 添加运行时需要的字段
                    for service in data.values():
                        service["pid"] = None
                    return data
                except json.JSONDecodeError:
                    print("配置文件格式错误，将创建新的配置文件")
                    os.remove(self.config_file)
                    
            # 如果配置文件不存在或已被删除，创建新的配置文件
            empty_config = {}
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(empty_config, f, ensure_ascii=False, indent=4)
            return empty_config
            
        except Exception as e:
            print(f"配置文件操作失败: {e}")
            return {}

    def load_middlewares(self):
        try:
            if os.path.exists(self.middleware_config_file):
                try:
                    with open(self.middleware_config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # 添加运行时需要的字段
                    for middleware in data.values():
                        middleware["pid"] = None
                    return data
                except json.JSONDecodeError:
                    print("中间件配置文件格式错误，将创建新的配置文件")
                    os.remove(self.middleware_config_file)
            
            # 如果配置文件不存在或已被删除，创建新的配置文件
            empty_config = {}
            with open(self.middleware_config_file, 'w', encoding='utf-8') as f:
                json.dump(empty_config, f, ensure_ascii=False, indent=4)
            return empty_config
            
        except Exception as e:
            print(f"中间件配置文件操作失败: {e}")
            return {}

    def save_java_services(self):
        try:
            # 创建一个不包含UI元素的副本
            services_to_save = {}
            for name, service in self.java_services.items():
                services_to_save[name] = {
                    "process": service["process"],
                    "jar_name": service["jar_name"],
                    "script": service.get("script", "")
                }
            
            # 保存到文件
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(services_to_save, f, ensure_ascii=False, indent=4)
            return {"status": "success", "message": "配置已保存"}
        except Exception as e:
            return {"status": "error", "message": f"保存配置文件失败: {str(e)}"}

    def save_middlewares(self):
        try:
            # 创建一个不包含UI元素的副本
            middlewares_to_save = {}
            for name, middleware in self.middlewares.items():
                middlewares_to_save[name] = {
                    "process_name": middleware["process_name"],
                    "start_cmd": middleware["start_cmd"],
                    "reload_cmd": middleware["reload_cmd"],
                    "work_dir": middleware.get("work_dir", ""),
                    "port": middleware.get("port", None)
                }
            
            # 保存到文件
            with open(self.middleware_config_file, 'w', encoding='utf-8') as f:
                json.dump(middlewares_to_save, f, ensure_ascii=False, indent=4)
            return {"status": "success", "message": "配置已保存"}
        except Exception as e:
            return {"status": "error", "message": f"保存中间件配置失败: {str(e)}"}

    def background_status_check(self):
        while self.is_running:
            try:
                # 检查服务状态
                service_status = {}
                for service_name in self.services:
                    service_status[service_name] = self.is_service_running(service_name)
                
                # 检查Java进程状态
                java_status = self.check_java_processes_status()
                
                # 检查中间件状态
                middleware_status = self.check_middleware_processes_status()
                
                # 通过WebSocket发送状态更新
                socketio.emit('status_update', {
                    'services': service_status,
                    'java': java_status,
                    'middleware': middleware_status
                })
                
                time.sleep(self.CHECK_INTERVAL)
            except Exception as e:
                print(f"状态检查错误: {e}")
                time.sleep(1)

    def is_service_running(self, service_name):
        service = self.services[service_name]
        try:
            status = win32serviceutil.QueryServiceStatus(service)
            return status[1] == win32service.SERVICE_RUNNING
        except Exception as e:
            print(f"检查服务状态失败: {e}")
            return False

    def check_java_processes_status(self):
        status = {}
        for service_name in self.java_services:
            status[service_name] = {"pid": None}
            
        for process in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = " ".join(process.info['cmdline']) if process.info['cmdline'] else ""
                for service_name, service_info in self.java_services.items():
                    jar_name = service_info.get("jar_name", "")
                    if jar_name and jar_name in cmdline:
                        status[service_name]["pid"] = process.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
                
        return status

    def check_middleware_processes_status(self):
        current_time = time.time()
        
        # 每次请求都检查进程状态，不使用缓存
        status = {}
        for middleware_name in self.middlewares:
            status[middleware_name] = {"pid": None}
            
        try:
            # 方法1: 使用tasklist命令
            import subprocess
            tasklist_output = subprocess.check_output('tasklist /FO CSV /NH', shell=True).decode('gbk', errors='ignore')
            
            # 为每个中间件检查进程
            for middleware_name, middleware_info in self.middlewares.items():
                process_name = middleware_info['process_name'].lower()
                
                # 在tasklist输出中查找进程
                for line in tasklist_output.splitlines():
                    if process_name in line.lower():
                        try:
                            pid = int(line.split('"')[1])  # CSV格式，PID在第2个字段
                            status[middleware_name]["pid"] = pid
                            break
                        except:
                            continue
        except Exception as e:
            print(f"tasklist检查失败: {e}")
            
        # 方法2: 如果tasklist方法没有找到某些进程，使用psutil作为备选方案
        for middleware_name, info in status.items():
            if info["pid"] is None:
                try:
                    process_name = self.middlewares[middleware_name]['process_name'].lower()
                    work_dir = self.middlewares[middleware_name].get("work_dir", "").lower()
                    
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'exe']):
                        try:
                            # 检查进程名是否匹配
                            proc_name = proc.info['name'].lower() if proc.info.get('name') else ""
                            proc_exe = os.path.basename(proc.info['exe']).lower() if proc.info.get('exe') else ""
                            proc_cmd = " ".join(proc.info['cmdline']).lower() if proc.info.get('cmdline') else ""
                            
                            if (process_name in proc_name or 
                                process_name in proc_exe or 
                                process_name in proc_cmd):
                                
                                # 如果配置了工作目录，进行检查
                                if work_dir:
                                    try:
                                        proc_cwd = proc.cwd().lower()
                                        if not (work_dir in proc_cwd or 
                                               proc_cwd in work_dir or 
                                               os.path.normpath(work_dir) == os.path.normpath(proc_cwd)):
                                            continue
                                    except:
                                        continue
                                
                                status[middleware_name]["pid"] = proc.pid
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"psutil检查失败: {e}")
                    
        # 方法3: 对于nginx特殊处理，尝试使用其工作目录判断
        for middleware_name, info in status.items():
            if info["pid"] is None and "nginx" in middleware_name.lower():
                try:
                    work_dir = self.middlewares[middleware_name].get("work_dir", "")
                    if work_dir:
                        # 检查是否有nginx.pid文件
                        pid_file = os.path.join(work_dir, "logs", "nginx.pid")
                        if os.path.exists(pid_file):
                            try:
                                with open(pid_file, 'r') as f:
                                    pid = int(f.read().strip())
                                    try:
                                        # 检查PID是否有效
                                        proc = psutil.Process(pid)
                                        status[middleware_name]["pid"] = pid
                                    except:
                                        pass
                            except:
                                pass
                except Exception as e:
                    print(f"Nginx PID文件检查失败: {e}")
            
        # 更新缓存和最后检查时间
        self.process_cache = status
        self.last_check_time = current_time
                
        return status
        
    def get_nginx_port(self, nginx_conf_path):
        """读取nginx配置文件中的端口号"""
        try:
            with open(nginx_conf_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # 使用简单的文本匹配查找端口号
                match = re.search(r'listen\s+(\d+)', content)
                if match:
                    return match.group(1)
        except Exception as e:
            print(f"读取nginx配置文件失败: {e}")
        return None

    def update_nginx_port(self, nginx_conf_path, new_port):
        """更新nginx配置文件中的端口号"""
        try:
            with open(nginx_conf_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 使用正则表达式替换端口号
            new_content = re.sub(r'(listen\s+)\d+', rf'\g<1>{new_port}', content)
            
            with open(nginx_conf_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            return True
        except Exception as e:
            print(f"更新nginx配置文件失败: {e}")
            return False

# 创建服务管理器实例
service_manager = ServiceManager()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/services')
def get_services():
    return jsonify(list(service_manager.services.keys()))

@app.route('/api/services/start/<service_name>', methods=['POST'])
def start_service(service_name):
    try:
        with service_manager.operation_lock:
            win32serviceutil.StartService(service_manager.services[service_name])
        return jsonify({"status": "success", "message": f"{service_name} 已启动"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"启动 {service_name} 失败: {str(e)}"})

@app.route('/api/services/stop/<service_name>', methods=['POST'])
def stop_service(service_name):
    try:
        with service_manager.operation_lock:
            win32serviceutil.StopService(service_manager.services[service_name])
        return jsonify({"status": "success", "message": f"{service_name} 已停止"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"停止 {service_name} 失败: {str(e)}"})

@app.route('/api/services/restart/<service_name>', methods=['POST'])
def restart_service(service_name):
    try:
        with service_manager.operation_lock:
            win32serviceutil.RestartService(service_manager.services[service_name])
        return jsonify({"status": "success", "message": f"{service_name} 已重启"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"重启 {service_name} 失败: {str(e)}"})

@app.route('/api/middleware')
def get_middlewares():
    return jsonify(service_manager.middlewares)

@app.route('/api/middleware/add', methods=['POST'])
def add_middleware():
    try:
        data = request.json
        name = data.get('name')
        process_name = data.get('process_name')
        start_cmd = data.get('start_cmd')
        reload_cmd = data.get('reload_cmd')
        work_dir = data.get('work_dir')
        
        if not all([name, process_name, start_cmd]):
            return jsonify({"status": "error", "message": "缺少必要参数"})
            
        if name in service_manager.middlewares:
            return jsonify({"status": "error", "message": "中间件名称已存在"})
            
        # 确保进程名以.exe结尾
        if not process_name.lower().endswith('.exe'):
            process_name = f"{process_name}.exe"
            
        service_manager.middlewares[name] = {
            "process_name": process_name,
            "start_cmd": start_cmd,
            "reload_cmd": reload_cmd,
            "work_dir": work_dir,
            "pid": None
        }
        
        result = service_manager.save_middlewares()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/middleware/start/<middleware_name>', methods=['POST'])
def start_middleware(middleware_name):
    try:
        middleware = service_manager.middlewares.get(middleware_name)
        if not middleware:
            return jsonify({"status": "error", "message": "中间件不存在"})
            
        work_dir = middleware.get("work_dir", "")
        if work_dir:
            current_dir = os.getcwd()
            os.chdir(work_dir)
            
        with service_manager.operation_lock:
            os.system(middleware["start_cmd"])
            
        if work_dir:
            os.chdir(current_dir)
            
        return jsonify({"status": "success", "message": f"{middleware_name} 已启动"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/middleware/stop/<middleware_name>', methods=['POST'])
def stop_middleware(middleware_name):
    try:
        middleware = service_manager.middlewares.get(middleware_name)
        if not middleware:
            return jsonify({"status": "error", "message": "中间件不存在"})
            
        process_name = middleware['process_name'].lower()
        work_dir = middleware.get("work_dir", "").lower()
        stopped = False
        
        with service_manager.operation_lock:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cwd']):
                try:
                    if (proc.info['name'].lower() == process_name or
                        (proc.info['exe'] and os.path.basename(proc.info['exe']).lower() == process_name)):
                        
                        if work_dir:
                            try:
                                proc_cwd = proc.cwd().lower()
                                if not (work_dir in proc_cwd or 
                                      proc_cwd in work_dir or 
                                      os.path.normpath(work_dir) == os.path.normpath(proc_cwd)):
                                    continue
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                        
                        proc.terminate()
                        stopped = True
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                    
        if stopped:
            return jsonify({"status": "success", "message": f"{middleware_name} 已停止"})
        else:
            return jsonify({"status": "success", "message": f"{middleware_name} 未运行"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/middleware/reload/<middleware_name>', methods=['POST'])
def reload_middleware(middleware_name):
    try:
        middleware = service_manager.middlewares.get(middleware_name)
        if not middleware:
            return jsonify({"status": "error", "message": "中间件不存在"})
            
        if not middleware.get("reload_cmd"):
            return jsonify({"status": "error", "message": "未配置重载命令"})
            
        work_dir = middleware.get("work_dir", "")
        if work_dir:
            current_dir = os.getcwd()
            os.chdir(work_dir)
            
        with service_manager.operation_lock:
            result = os.system(middleware["reload_cmd"])
            
        if work_dir:
            os.chdir(current_dir)
            
        if result == 0:
            return jsonify({"status": "success", "message": f"{middleware_name} 重载成功"})
        else:
            return jsonify({"status": "error", "message": f"{middleware_name} 重载失败，返回代码：{result}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/middleware/delete/<middleware_name>', methods=['POST'])
def delete_middleware(middleware_name):
    try:
        if middleware_name not in service_manager.middlewares:
            return jsonify({"status": "error", "message": "中间件不存在"})
            
        # 如果进程正在运行，先终止它
        if service_manager.middlewares[middleware_name]["pid"]:
            stop_middleware(middleware_name)
            
        # 删除配置
        del service_manager.middlewares[middleware_name]
        result = service_manager.save_middlewares()
        
        if result["status"] == "success":
            result["message"] = f"{middleware_name} 已删除"
            
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/java')
def get_java_processes():
    return jsonify(service_manager.java_services)

@app.route('/api/java/add', methods=['POST'])
def add_java_process():
    try:
        data = request.json
        name = data.get('name')
        jar_name = data.get('jar_name')
        script = data.get('script', '')
        
        if not all([name, jar_name]):
            return jsonify({"status": "error", "message": "缺少必要参数"})
            
        if name in service_manager.java_services:
            return jsonify({"status": "error", "message": "进程名称已存在"})
            
        service_manager.java_services[name] = {
            "process": name,
            "jar_name": jar_name,
            "script": script,
            "pid": None
        }
        
        result = service_manager.save_java_services()
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/java/start/<process_name>', methods=['POST'])
def start_java_process(process_name):
    try:
        service = service_manager.java_services.get(process_name)
        if not service:
            return jsonify({"status": "error", "message": "进程不存在"})
            
        script_path = service.get("script")
        if not script_path:
            return jsonify({"status": "error", "message": "请先配置启动脚本路径"})
            
        with service_manager.operation_lock:
            os.system(f'start "" "{script_path}"')
            
        return jsonify({"status": "success", "message": f"{process_name} 已启动"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/java/stop/<process_name>', methods=['POST'])
def stop_java_process(process_name):
    try:
        service = service_manager.java_services.get(process_name)
        if not service:
            return jsonify({"status": "error", "message": "进程不存在"})
            
        pid = service.get("pid")
        if not pid:
            return jsonify({"status": "success", "message": f"{process_name} 未运行"})
            
        with service_manager.operation_lock:
            psutil.Process(pid).terminate()
            
        return jsonify({"status": "success", "message": f"{process_name} 已终止"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/java/configure/<process_name>', methods=['POST'])
def configure_java_process(process_name):
    try:
        data = request.json
        script_path = data.get('script')
        
        if not script_path:
            return jsonify({"status": "error", "message": "未提供脚本路径"})
            
        if process_name not in service_manager.java_services:
            return jsonify({"status": "error", "message": "进程不存在"})
            
        service_manager.java_services[process_name]["script"] = script_path
        result = service_manager.save_java_services()
        
        if result["status"] == "success":
            result["message"] = f"{process_name} 配置已更新"
            
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/java/delete/<process_name>', methods=['POST'])
def delete_java_process(process_name):
    try:
        if process_name not in service_manager.java_services:
            return jsonify({"status": "error", "message": "进程不存在"})
            
        # 如果进程正在运行，先终止它
        if service_manager.java_services[process_name]["pid"]:
            stop_java_process(process_name)
            
        # 删除配置
        del service_manager.java_services[process_name]
        result = service_manager.save_java_services()
        
        if result["status"] == "success":
            result["message"] = f"{process_name} 已删除"
            
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/middleware/nginx/port/<middleware_name>', methods=['GET'])
def get_nginx_port(middleware_name):
    try:
        middleware = service_manager.middlewares.get(middleware_name)
        if not middleware:
            return jsonify({"status": "error", "message": "中间件不存在"})
            
        work_dir = middleware.get("work_dir", "")
        if not work_dir:
            return jsonify({"status": "error", "message": "未设置工作目录"})
            
        nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
        if not os.path.exists(nginx_conf):
            return jsonify({"status": "error", "message": "未找到nginx配置文件"})
            
        port = service_manager.get_nginx_port(nginx_conf)
        if port:
            middleware["port"] = port
            service_manager.save_middlewares()
            return jsonify({"status": "success", "port": port})
        else:
            return jsonify({"status": "error", "message": "未找到端口配置"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/middleware/nginx/port/<middleware_name>', methods=['POST'])
def update_nginx_port(middleware_name):
    try:
        data = request.json
        new_port = data.get('port')
        
        if not new_port or not new_port.isdigit():
            return jsonify({"status": "error", "message": "请提供有效的端口号"})
            
        middleware = service_manager.middlewares.get(middleware_name)
        if not middleware:
            return jsonify({"status": "error", "message": "中间件不存在"})
            
        work_dir = middleware.get("work_dir", "")
        if not work_dir:
            return jsonify({"status": "error", "message": "未设置工作目录"})
            
        nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
        if not os.path.exists(nginx_conf):
            return jsonify({"status": "error", "message": "未找到nginx配置文件"})
            
        if service_manager.update_nginx_port(nginx_conf, new_port):
            middleware["port"] = new_port
            service_manager.save_middlewares()
            
            # 尝试重载nginx
            reload_middleware(middleware_name)
            
            return jsonify({
                "status": "success", 
                "message": "端口号已更新并重载nginx", 
                "port": new_port
            })
        else:
            return jsonify({"status": "error", "message": "更新配置文件失败"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# 添加nginx代理配置API
@app.route('/api/middleware/nginx/proxy/<middleware_name>', methods=['GET'])
def get_nginx_proxy(middleware_name):
    try:
        middleware = service_manager.middlewares.get(middleware_name)
        if not middleware:
            return jsonify({"status": "error", "message": "中间件不存在"})
            
        work_dir = middleware.get("work_dir", "")
        if not work_dir:
            return jsonify({"status": "error", "message": "未设置工作目录"})
            
        nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
        if not os.path.exists(nginx_conf):
            return jsonify({"status": "error", "message": "未找到nginx配置文件"})
        
        # 定义需要过滤的路径列表
        filter_paths = [
            r"location\s+/api/",
            r"location\s+/admin/api/files/upload/",
            r"location\s+/papi/",
            r"location\s+/w(?:\s|{)",
            r"location\s+/(?:\s|{)",
            r"location\s+/authcenter/",
            r"location\s+/usercenter/",
            r"location\s+/permissions/",
            r"location\s+/wish3dearth/",
            r"location\s+/datamanage/",
            r"location\s+~\s+\^/wish3dearth/static/v1\.0\.0/cad/api/v1/map/\(.*\)\$"
        ]
        
        # 读取nginx配置文件并解析代理配置
        try:
            with open(nginx_conf, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # 使用正则表达式查找所有location配置
            locations = re.finditer(r'location\s+([^{]+)\s*{\s*proxy_pass\s+([^;]+);', content)
            
            # 收集代理配置
            proxies = []
            for match in locations:
                location_block = f"location {match.group(1)}"
                
                # 检查是否需要过滤
                should_filter = False
                for filter_path in filter_paths:
                    if re.match(filter_path, location_block.strip()):
                        should_filter = True
                        break
                
                # 如果不需要过滤，则添加到结果中
                if not should_filter:
                    path = match.group(1).strip()
                    target = match.group(2).strip()
                    proxies.append({"path": path, "target": target})
            
            return jsonify({"status": "success", "proxies": proxies})
        except Exception as e:
            return jsonify({"status": "error", "message": f"读取nginx配置文件失败: {str(e)}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/middleware/nginx/proxy/<middleware_name>', methods=['POST'])
def add_nginx_proxy(middleware_name):
    try:
        data = request.json
        suffix = data.get('suffix')
        target = data.get('target')
        
        if not all([suffix, target]):
            return jsonify({"status": "error", "message": "缺少必要参数"})
            
        middleware = service_manager.middlewares.get(middleware_name)
        if not middleware:
            return jsonify({"status": "error", "message": "中间件不存在"})
            
        work_dir = middleware.get("work_dir", "")
        if not work_dir:
            return jsonify({"status": "error", "message": "未设置工作目录"})
            
        nginx_conf = os.path.join(work_dir, "conf", "nginx.conf")
        if not os.path.exists(nginx_conf):
            return jsonify({"status": "error", "message": "未找到nginx配置文件"})
        
        # 确保后缀以/开头
        if not suffix.startswith('/'):
            suffix = '/' + suffix
        
        # 读取nginx配置文件
        try:
            with open(nginx_conf, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 查找server_name行
            server_block = re.search(r'server\s*{[^}]*server_name[^;]*;', content, re.DOTALL)
            if not server_block:
                return jsonify({"status": "error", "message": "无法在配置文件中找到server配置块"})
            
            # 构建新的location配置
            location_config = f"\n    location {suffix} {{\n        proxy_pass {target};\n    }}"
            
            # 在server_name后插入location配置
            insert_pos = server_block.end()
            new_content = content[:insert_pos] + location_config + content[insert_pos:]
            
            # 写入配置文件
            with open(nginx_conf, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            # 重载nginx
            reload_middleware(middleware_name)
            
            return jsonify({"status": "success", "message": "代理配置已添加并重载nginx"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"更新nginx配置文件失败: {str(e)}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8082, debug=False)